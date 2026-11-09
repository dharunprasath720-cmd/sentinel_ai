"""Glue for one live event: ingest -> score -> store assessment -> alert -> publish.

Idempotent: a record whose external_id already exists is a no-op (returns None) and is never
scored twice. Events are published only AFTER the database commit, so the stream never announces
work that was rolled back.
"""
import threading
import time
from collections import deque

import numpy as np
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sentinel.cases import services
from sentinel.context import AppContext
from sentinel.db import session_scope
from sentinel.ingestion.service import ingest
from sentinel.live.bus import EventBus


class LatencyMetrics:
    def __init__(self, keep: int = 5000):
        self._lat, self._lock = deque(maxlen=keep), threading.Lock()
        self.processed = self.alerts = 0

    def record(self, latency_ms: float, alert: bool) -> None:
        with self._lock:
            self._lat.append(latency_ms)
            self.processed += 1
            self.alerts += int(alert)

    def snapshot(self) -> dict:
        with self._lock:
            lat = np.array(self._lat) if self._lat else None
            return {"processed": self.processed, "alerts": self.alerts,
                    "p50_ms": None if lat is None else float(np.percentile(lat, 50)),
                    "p95_ms": None if lat is None else float(np.percentile(lat, 95)),
                    "max_ms": None if lat is None else float(lat.max())}


class LiveService:
    def __init__(self, db: Engine, context: AppContext, bus: EventBus):
        self.db, self.ctx, self.bus = db, context, bus
        self.metrics = LatencyMetrics()

    def score_and_store(self, session: Session, record: dict) -> dict | None:
        """Score an ALREADY-INGESTED record and persist its assessment/alert. Returns the event
        dict to publish after commit (None if the scorer already knew the event)."""
        scored = self.ctx.live_scorer.score(record)
        if scored is None:
            return None
        row = services.record_assessment(
            session, scored.business_id, scored.external_id, scored.assessment, self.ctx.model_version,
            details={"inputs": scored.inputs, "behaviour_reasons": scored.behaviour_reasons,
                     "cluster_id": scored.cluster_id, "late": scored.late})
        alerts = services.create_alerts(session, scored.business_id, [row], min_level="HIGH")
        self.metrics.record(scored.latency_ms, bool(alerts))
        a = scored.assessment
        return {
            "external_id": scored.external_id, "business_id": scored.business_id,
            "ts": str(record["ts"]), "amount": float(record["amount"]),
            "account_id": record["account_id"], "merchant_id": record.get("merchant_id"),
            "source": record.get("source"), "risk_score": round(a.risk_score, 4),
            "risk_level": a.risk_level, "recommended_action": a.recommended_action,
            "calibrated_fraud_probability": round(a.calibrated_fraud_probability, 4),
            "risk_factors": list(a.risk_factors), "cluster_id": scored.cluster_id,
            "alert": bool(alerts), "late": scored.late, "latency_ms": round(scored.latency_ms, 2),
            "emitted_at": time.time(),
        }

    def publish(self, event: dict) -> None:
        self.bus.publish(event["business_id"], event)

    def process(self, record: dict) -> dict | None:
        """Full path for one record. Returns the published event, or None for a duplicate."""
        event = None
        try:
            with session_scope(self.db) as session:
                result = ingest(session, [record])
                if result.rejected:
                    raise ValueError(f"record rejected: {result.rejected[0][1]}")
                if result.inserted == 0:
                    return None
                event = self.score_and_store(session, record)
        except IntegrityError:  # a concurrent delivery of the same record won the race
            return None
        if event:
            self.publish(event)
        return event


class Simulator:
    """Replays rows of a frame through LiveService at `speed` events/second (background thread)."""
    def __init__(self, service: LiveService):
        self.service = service
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.sent = 0
        self.errors = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, frame, speed: float, limit: int) -> None:
        if self.running:
            raise RuntimeError("simulator is already running")
        self._stop.clear()
        self.sent = self.errors = 0
        rows = frame.head(limit).to_dict("records")
        self._thread = threading.Thread(target=self._run, args=(rows, speed), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self, rows: list[dict], speed: float) -> None:
        for rec in rows:
            if self._stop.is_set():
                return
            try:
                self.service.process(rec)
                self.sent += 1
            except Exception:  # noqa: BLE001  (one bad row must not kill the replay)
                self.errors += 1
            self._stop.wait(1.0 / speed)

    def status(self) -> dict:
        return {"running": self.running, "sent": self.sent, "errors": self.errors}
