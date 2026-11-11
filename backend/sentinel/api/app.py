"""Secured API for alerts, cases and audit.

Security model: JWT bearer tokens (HS256, secret from SENTINEL_JWT_SECRET, >= 32 chars; the app
refuses to start without one). The user's role and business are re-read from the database on
every request, so a role change or removal takes effect immediately. Every query is scoped to
the user's business: another business's ids are 404 (never 403, which would confirm they exist).
Failed logins are indistinguishable for unknown users and wrong passwords.
"""
import asyncio
import json
import logging
import os
import threading
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from sentinel.agent.agent import InvestigationAgent
from sentinel.agent.tools import ToolBox
from sentinel.cases import services
from sentinel.cases.orm import Alert, Case, CaseAlert, CaseNote, RiskAssessmentRow, User
from sentinel.api.dashboard import register_dashboard
from sentinel.dashboard import queries
from sentinel.dashboard.queries import Source
from sentinel.context import AppContext
from sentinel.db import session_scope
from sentinel.live.bus import EventBus
from sentinel.live.service import LiveService, Simulator
from sentinel.paypal.webhook import (MAX_BODY_BYTES, BadEvent, InvalidSignature, PayloadTooLarge,
                                     VerificationUnavailable, process_webhook)
from sentinel.security import (AuthError, Conflict, Forbidden, NotFound, create_token,
                               decode_token, hash_password, require_role, verify_password)

MIN_SECRET_LEN = 32
HEARTBEAT_SECS = 15.0
_DUMMY_HASH = hash_password("timing-equaliser")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class CaseIn(BaseModel):
    alert_ids: list[int] = Field(min_length=1, max_length=100)


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ActionIn(BaseModel):
    action: Literal["ALLOW", "MONITOR", "REVIEW", "VERIFY", "HOLD_RECOMMENDED"]


class ResolveIn(BaseModel):
    outcome: Literal["suspicious", "cleared"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]  # clients can never inject a system turn
    content: str = Field(min_length=1, max_length=8000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def _ends_with_user(self):
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return self


class SimulateIn(BaseModel):
    speed: float = Field(gt=0, le=1000, description="events per second")
    limit: int = Field(ge=1, le=100000)


def _alert_dict(a: Alert) -> dict:
    return {"id": a.id, "txn_external_id": a.txn_external_id, "level": a.level, "status": a.status}


def create_app(engine: Engine, secret: str | None = None,
               context: AppContext | None = None, webhook_concurrency: int = 8) -> FastAPI:
    secret = secret or os.environ.get("SENTINEL_JWT_SECRET")
    if not secret or len(secret) < MIN_SECRET_LEN:
        raise RuntimeError(f"SENTINEL_JWT_SECRET must be set and at least {MIN_SECRET_LEN} characters")

    app = FastAPI(title="SENTINEL AI", version="0.3.0")
    app.state.context = context
    bus = EventBus()
    live = LiveService(engine, context, bus) if context is not None and context.live_scorer else None
    simulator = Simulator(live) if live else None
    app.state.bus, app.state.live, app.state.simulator = bus, live, simulator

    def need_live() -> None:
        if live is None:
            raise HTTPException(status_code=503, detail="live scoring is not configured")
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(AuthError)
    async def _auth(_: Request, __: AuthError):
        return JSONResponse({"detail": "Invalid or missing credentials"}, status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(Forbidden)
    async def _forbidden(_: Request, exc: Forbidden):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, __: NotFound):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.exception_handler(InvalidSignature)
    async def _bad_signature(_: Request, __: InvalidSignature):
        return JSONResponse({"detail": "webhook signature not verified"}, status_code=401)

    @app.exception_handler(VerificationUnavailable)
    async def _verification_down(_: Request, __: VerificationUnavailable):
        # temporary: PayPal retries deliveries that get a 5xx
        return JSONResponse({"detail": "signature verification temporarily unavailable"},
                            status_code=503, headers={"Retry-After": "30"})

    @app.exception_handler(PayloadTooLarge)
    async def _too_large(_: Request, exc: PayloadTooLarge):
        return JSONResponse({"detail": str(exc)}, status_code=413)

    @app.exception_handler(BadEvent)
    async def _bad_event(_: Request, exc: BadEvent):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(Conflict)
    async def _conflict(_: Request, exc: Conflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def _bad_value(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def get_session():
        with session_scope(engine) as s:
            yield s

    def current_user(session: Session = Depends(get_session), creds=Depends(bearer)) -> User:
        if creds is None:
            raise AuthError("no token")
        claims = decode_token(creds.credentials, secret)
        user = session.get(User, int(claims["sub"]))
        if user is None:
            raise AuthError("unknown user")
        return user

    register_dashboard(app, get_session, current_user, context)

    @app.post("/auth/login")
    def login(body: LoginIn, session: Session = Depends(get_session)):
        user = session.query(User).filter_by(username=body.username).one_or_none()
        ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
        if not (user and ok):
            raise AuthError("bad credentials")
        return {"access_token": create_token(user, secret), "token_type": "bearer", "role": user.role}

    @app.get("/alerts")
    def alerts(status: str | None = None, source: Source | None = None,
               session: Session = Depends(get_session), user: User = Depends(current_user)):
        rows = (services.list_alerts(session, user, status) if source is None
                else queries.alerts_in_source(session, user.business_id, status, source))
        return [_alert_dict(a) for a in rows]

    @app.post("/cases")
    def open_case(body: CaseIn, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
        case = services.open_case(session, user, body.alert_ids)
        return {"id": case.id, "status": case.status}

    @app.get("/cases/{case_id}")
    def get_case(case_id: int, session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
        case = services._case(session, user, case_id)
        alert_rows = (session.query(Alert).join(CaseAlert, CaseAlert.alert_id == Alert.id)
                      .filter(CaseAlert.case_id == case.id).order_by(Alert.id).all())
        out_alerts = []
        for a in alert_rows:
            row = session.query(RiskAssessmentRow).filter_by(
                business_id=case.business_id, txn_external_id=a.txn_external_id).one_or_none()
            d = _alert_dict(a)
            d["assessment"] = None if row is None else {
                "risk_score": row.risk_score, "risk_level": row.risk_level, "action": row.action,
                "calibrated_fraud_probability": row.calibrated_fraud_probability,
                "factors": row.factors, "model_version": row.model_version,
                "policy_version": row.policy_version}
            out_alerts.append(d)
        notes = (session.query(CaseNote, User.username).join(User, User.id == CaseNote.author_id)
                 .filter(CaseNote.case_id == case.id).order_by(CaseNote.id).all())
        return {"id": case.id, "status": case.status, "approved_action": case.approved_action,
                "alerts": out_alerts,
                "notes": [{"author": name, "body": n.body, "ts": n.ts.isoformat()} for n, name in notes]}

    @app.post("/cases/{case_id}/notes")
    def add_note(case_id: int, body: NoteIn, session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
        note = services.add_note(session, user, case_id, body.body)
        return {"id": note.id}

    @app.post("/cases/{case_id}/approve-action")
    def approve(case_id: int, body: ActionIn, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
        case = services.approve_action(session, user, case_id, body.action)
        return {"id": case.id, "status": case.status, "approved_action": case.approved_action}

    @app.post("/cases/{case_id}/resolve")
    def resolve(case_id: int, body: ResolveIn, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
        case = services.resolve_case(session, user, case_id, body.outcome)
        return {"id": case.id, "status": case.status}

    @app.get("/audit")
    def audit(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return [{"id": e.id, "ts": e.ts.isoformat(), "actor": e.actor, "action": e.action,
                 "target": e.target, "before": e.before, "after": e.after}
                for e in services.list_audit(session, user)]

    # ------------------------------------------------------------------ investigation agent
    def agent_for(session: Session, user: User) -> InvestigationAgent:
        require_role(user.role, {"analyst", "admin"})
        ctx = context or AppContext()
        return InvestigationAgent(ctx.llm, ToolBox(session, ctx, user))

    @app.post("/agent/report/{transaction_id}")
    def agent_report(transaction_id: str = Path(min_length=1, max_length=200),
                     session: Session = Depends(get_session), user: User = Depends(current_user)):
        """Grounded investigation report. Without a configured language model this is the
        deterministic, evidence-cited report (llm_narrative=false)."""
        return agent_for(session, user).investigate(transaction_id).model_dump()

    @app.post("/agent/chat")
    def agent_chat(body: ChatIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
        agent = agent_for(session, user)
        if agent.llm is None:
            raise HTTPException(status_code=503, detail="no language model is configured for chat")
        try:
            return agent.chat([m.model_dump() for m in body.messages])
        except Exception as exc:  # noqa: BLE001  (provider/network failures: never leak details)
            logging.getLogger("sentinel.agent").warning("chat model call failed: %s", type(exc).__name__)
            raise HTTPException(status_code=502, detail="the language model request failed") from exc

    # ------------------------------------------------------------------ live scoring
    def authenticate(creds) -> tuple[str, str]:
        """(business_id, role) for a bearer token, using a short-lived session so a long-lived
        stream never pins a database connection."""
        if creds is None:
            raise AuthError("no token")
        claims = decode_token(creds.credentials, secret)
        with session_scope(engine) as s:
            user = s.get(User, int(claims["sub"]))
            if user is None:
                raise AuthError("unknown user")
            return user.business_id, user.role

    @app.get("/stream/events")
    async def stream_events(limit: int | None = Query(None, ge=1, le=10000), creds=Depends(bearer)):
        business_id, _ = authenticate(creds)
        need_live()

        async def frames():
            sub = bus.subscribe(business_id)
            sent = 0
            try:
                yield ": connected\n\n"
                while limit is None or sent < limit:
                    try:
                        event = await asyncio.wait_for(sub.get(), timeout=HEARTBEAT_SECS)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(event)}\n\n"
                    sent += 1
            finally:
                sub.close()

        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/metrics/live")
    def metrics_live(user: User = Depends(current_user)):
        need_live()
        mine = user.business_id  # a business sees only its own counters
        sim = simulator.status() if mine == context.business_id else {"running": False, "sent": 0, "errors": 0}
        return {**live.metrics_for(mine).snapshot(), "dropped": bus.dropped_for(mine), "simulator": sim}

    def simulator_guard(user: User) -> None:
        need_live()
        require_role(user.role, {"analyst", "admin"})
        if user.business_id != context.business_id:  # the replay belongs to one business
            raise Forbidden("the simulator belongs to another business")

    @app.post("/simulate/start")
    def simulate_start(body: SimulateIn, user: User = Depends(current_user)):
        simulator_guard(user)
        if context.demo_frame is None:
            raise HTTPException(status_code=503, detail="no demo data is loaded")
        try:
            simulator.start(context.demo_frame, body.speed, body.limit)
        except RuntimeError as exc:
            raise Conflict(str(exc)) from exc
        return {"started": True, "speed": body.speed, "limit": body.limit}

    @app.post("/simulate/stop")
    def simulate_stop(user: User = Depends(current_user)):
        simulator_guard(user)
        simulator.stop()
        return simulator.status()

    webhook_slots = threading.BoundedSemaphore(max(1, webhook_concurrency))

    async def read_limited(request: Request) -> bytes:
        """Read the body but stop as soon as it exceeds MAX_BODY_BYTES (never buffer an unbounded body)."""
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            raise PayloadTooLarge(f"body is larger than {MAX_BODY_BYTES} bytes")
        chunks, total = [], 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_BODY_BYTES:
                raise PayloadTooLarge(f"body is larger than {MAX_BODY_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    @app.post("/paypal/webhook")
    async def paypal_webhook(request: Request):
        """Authenticated by PayPal's signature, not by a bearer token."""
        if live is None or context.paypal is None or not context.webhook_id:
            raise HTTPException(status_code=503, detail="PayPal webhook handling is not configured")
        raw = await read_limited(request)  # the exact bytes PayPal signed, capped in size
        headers = {k.lower(): v for k, v in request.headers.items()}

        def work():
            pending = []
            with session_scope(engine) as session:
                result = process_webhook(session, context.paypal, headers, raw,
                                         context.webhook_id, context.business_id)
                if result.status == "processed":
                    event = live.score_and_store(session, result.record)
                    if event:
                        pending.append(event)
            for event in pending:  # only after the commit
                live.publish(event)
            return result

        # This route is unauthenticated and each request may call PayPal: cap how many verifications
        # run at once so a flood cannot exhaust the shared worker pool. PayPal redelivers a 503.
        if not webhook_slots.acquire(blocking=False):
            return JSONResponse({"detail": "busy, retry later"}, status_code=503, headers={"Retry-After": "5"})
        try:
            result = await run_in_threadpool(work)
        finally:
            webhook_slots.release()
        return {"status": result.status, "transaction": result.txn_external_id}

    return app
