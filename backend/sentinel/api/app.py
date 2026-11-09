"""Secured API for alerts, cases and audit.

Security model: JWT bearer tokens (HS256, secret from SENTINEL_JWT_SECRET, >= 32 chars; the app
refuses to start without one). The user's role and business are re-read from the database on
every request, so a role change or removal takes effect immediately. Every query is scoped to
the user's business: another business's ids are 404 (never 403, which would confirm they exist).
Failed logins are indistinguishable for unknown users and wrong passwords.
"""
import os
from typing import Literal

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from sentinel.cases import services
from sentinel.cases.orm import Alert, Case, CaseAlert, CaseNote, RiskAssessmentRow, User
from sentinel.db import session_scope
from sentinel.security import (AuthError, Forbidden, NotFound, create_token, decode_token,
                               hash_password, verify_password)

MIN_SECRET_LEN = 32
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


def _alert_dict(a: Alert) -> dict:
    return {"id": a.id, "txn_external_id": a.txn_external_id, "level": a.level, "status": a.status}


def create_app(engine: Engine, secret: str | None = None) -> FastAPI:
    secret = secret or os.environ.get("SENTINEL_JWT_SECRET")
    if not secret or len(secret) < MIN_SECRET_LEN:
        raise RuntimeError(f"SENTINEL_JWT_SECRET must be set and at least {MIN_SECRET_LEN} characters")

    app = FastAPI(title="SENTINEL AI", version="0.2.0")
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

    @app.post("/auth/login")
    def login(body: LoginIn, session: Session = Depends(get_session)):
        user = session.query(User).filter_by(username=body.username).one_or_none()
        ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
        if not (user and ok):
            raise AuthError("bad credentials")
        return {"access_token": create_token(user, secret), "token_type": "bearer", "role": user.role}

    @app.get("/alerts")
    def alerts(status: str | None = None, session: Session = Depends(get_session),
               user: User = Depends(current_user)):
        return [_alert_dict(a) for a in services.list_alerts(session, user, status)]

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

    return app
