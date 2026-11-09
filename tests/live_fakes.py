"""Test doubles shared by the live-service and API tests (not part of the product)."""
import threading

import pandas as pd

from sentinel.live.scorer import ScoredEvent
from sentinel.paypal.client import PayPalError
from sentinel.risk.engine import RiskAssessment


class FakeScorer:
    """Scores amount >= 100 as HIGH, everything else LOW. Remembers what it was asked."""
    def __init__(self):
        self.seen, self._lock = [], threading.Lock()

    def score(self, txn):
        with self._lock:
            self.seen.append(txn["external_id"])
        high = float(txn["amount"]) >= 100
        a = RiskAssessment(risk_score=0.6 if high else 0.05, risk_level="HIGH" if high else "LOW",
                           recommended_action="REVIEW" if high else "ALLOW",
                           calibrated_fraud_probability=0.7 if high else 0.01,
                           risk_factors=["High model fraud probability"] if high else [],
                           contributions={}, policy_version="test-policy")
        return ScoredEvent(
            external_id=txn["external_id"], business_id=txn.get("business_id", "A"), assessment=a,
            inputs={"ml_prob": 0.7 if high else 0.01, "anomaly": 0.1, "behaviour": 0.0, "graph": 0.0,
                    "velocity": 0.0, "account_history": 0.0, "merchant_risk": 0.0,
                    "cluster_flagged": False},
            behaviour_reasons=[], cluster_id=None, late=False, latency_ms=2.5,
            features=pd.Series(dtype=float))


class FakePayPal:
    """Verifies only when the transmission signature header is 'good'."""
    def __init__(self, mode="ok"):
        self.mode, self.bodies = mode, []

    def verify_webhook(self, headers, raw_body, webhook_id):
        self.bodies.append(raw_body)
        if self.mode == "outage":
            raise PayPalError(503, "SERVICE_UNAVAILABLE", retryable=True)
        return self.mode == "ok" and headers.get("paypal-transmission-sig") == "good"


def record(i, amount=10.0, business="A", account="ACC_1", minute=0):
    return {"external_id": f"EV-{i}", "account_id": account, "merchant_id": "M_1", "device_id": None,
            "instrument_id": None, "amount": amount, "currency": "USD",
            "ts": f"2026-03-01T10:{minute:02d}:00+00:00", "type": "PAYMENT", "payment_method": "card",
            "status": "completed", "geo": None, "label": None, "source": "synthetic",
            "business_id": business}
