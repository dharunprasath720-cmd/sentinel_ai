from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from sentinel.api.app import create_app
from sentinel.cases import services
from sentinel.cases.orm import RiskAssessmentRow
from sentinel.context import AppContext
from sentinel.db import init_db, make_engine, session_scope
from sentinel.paypal.orm import PayPalEvent
from sentinel.risk.engine import RiskAssessment

SECRET = "context-test-secret-that-is-at-least-32-bytes"


@pytest.fixture
def engine():
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def test_details_roundtrip(engine):
    a = RiskAssessment(risk_score=0.5, risk_level="HIGH", recommended_action="REVIEW",
                       calibrated_fraud_probability=0.7, risk_factors=["x"], contributions={},
                       policy_version="p1")
    details = {"inputs": {"ml_prob": 0.7}, "behaviour_reasons": ["First payment to this merchant"],
               "cluster_id": "CL_1", "late": False}
    with session_scope(engine) as s:
        services.record_assessment(s, "A", "T1", a, "m1", details=details)
    with session_scope(engine) as s:
        assert s.query(RiskAssessmentRow).one().details == details
        # details are optional: older callers keep working
        services.record_assessment(s, "A", "T2", a, "m1")
        assert s.query(RiskAssessmentRow).filter_by(txn_external_id="T2").one().details is None


def test_paypal_event_id_is_unique(engine):
    now = datetime.now(timezone.utc)
    with session_scope(engine) as s:
        s.add(PayPalEvent(event_id="WH-1", event_type="PAYMENT.CAPTURE.COMPLETED",
                          received_at=now, payload={"id": "WH-1"}))
    with pytest.raises(IntegrityError):
        with session_scope(engine) as s:
            s.add(PayPalEvent(event_id="WH-1", event_type="PAYMENT.CAPTURE.COMPLETED",
                              received_at=now, payload={"id": "WH-1"}))


def test_create_app_works_with_and_without_context(engine):
    assert create_app(engine, secret=SECRET).state.context is None
    ctx = AppContext(business_id="biz1")
    assert create_app(engine, secret=SECRET, context=ctx).state.context is ctx
    assert ctx.live_scorer is None and ctx.paypal is None and ctx.llm is None
