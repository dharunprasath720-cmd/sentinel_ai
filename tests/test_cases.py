from datetime import datetime, timezone

import pytest

from sentinel.cases import services
from sentinel.cases.orm import Alert, AuditLog, Case, CaseNote, RiskAssessmentRow, User
from sentinel.db import init_db, make_engine, session_scope
from sentinel.ingestion.orm import Transaction
from sentinel.risk.engine import RiskAssessment, RiskEngine, RiskInputs, load_policy, DEFAULT_POLICY_PATH
from sentinel.security import Forbidden, NotFound


@pytest.fixture
def engine():
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    with session_scope(eng) as s:
        s.add_all([
            User(username="ana", password_hash="x", role="analyst", business_id="A"),
            User(username="vic", password_hash="x", role="viewer", business_id="A"),
            User(username="adm", password_hash="x", role="admin", business_id="A"),
            User(username="bob", password_hash="x", role="analyst", business_id="B"),
        ])
        s.add(Transaction(external_id="T1", account_id="a1", merchant_id="m", amount=10.0,
                          currency="USD", ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
                          type="PAYMENT", status="completed", label=None, source="synthetic",
                          business_id="A"))
    return eng


def user(s, name):
    return s.query(User).filter_by(username=name).one()


def assessment(level="HIGH", action="REVIEW", score=0.5):
    return RiskAssessment(risk_score=score, risk_level=level, recommended_action=action,
                          calibrated_fraud_probability=0.7, risk_factors=["Behavioural deviation"],
                          contributions={}, policy_version="p1")


def seed_alerts(s, business="A"):
    services.record_assessment(s, business, "T1", assessment("HIGH"), "m1")
    services.record_assessment(s, business, "T2", assessment("MODERATE", "MONITOR", 0.25), "m1")
    return services.create_alerts(s, business, s.query(RiskAssessmentRow).filter_by(business_id=business).all())


def test_alert_creation_is_thresholded_and_idempotent(engine):
    with session_scope(engine) as s:
        created = seed_alerts(s)
        assert [a.txn_external_id for a in created] == ["T1"]  # MODERATE is below HIGH
    with session_scope(engine) as s:
        rows = s.query(RiskAssessmentRow).all()
        assert services.create_alerts(s, "A", rows) == []
        assert s.query(Alert).count() == 1
        services.record_assessment(s, "A", "T1", assessment("CRITICAL"), "m2")  # re-scoring same txn
        assert s.query(RiskAssessmentRow).filter_by(txn_external_id="T1").count() == 1


def test_case_lifecycle_writes_ordered_audit_entries(engine):
    with session_scope(engine) as s:
        alerts = seed_alerts(s)
        ana = user(s, "ana")
        case = services.open_case(s, ana, [a.id for a in alerts])
        services.add_note(s, ana, case.id, "Looks like a coordinated pattern; checking devices.")
        services.approve_action(s, ana, case.id, "REVIEW")
        services.resolve_case(s, ana, case.id, "suspicious")
        cid = case.id
    with session_scope(engine) as s:
        case = s.get(Case, cid)
        assert case.status == "resolved_suspicious" and case.approved_action == "REVIEW"
        assert s.query(CaseNote).count() == 1
        actions = [r.action for r in s.query(AuditLog).order_by(AuditLog.id)]
        assert actions == ["open_case", "add_note", "approve_action", "resolve_case"]
        approve = s.query(AuditLog).filter_by(action="approve_action").one()
        assert approve.actor == "ana" and approve.business_id == "A"
        assert approve.before["approved_action"] is None and approve.after["approved_action"] == "REVIEW"


def test_viewer_cannot_act_and_nothing_changes(engine):
    with session_scope(engine) as s:
        alerts = seed_alerts(s)
        case = services.open_case(s, user(s, "ana"), [a.id for a in alerts])
        cid = case.id
    before = None
    with session_scope(engine) as s:
        before = s.query(AuditLog).count()
    for call in (lambda s, v: services.approve_action(s, v, cid, "VERIFY"),
                 lambda s, v: services.add_note(s, v, cid, "hi"),
                 lambda s, v: services.resolve_case(s, v, cid, "cleared"),
                 lambda s, v: services.open_case(s, v, [1])):
        with pytest.raises(Forbidden):
            with session_scope(engine) as s:
                call(s, user(s, "vic"))
    with session_scope(engine) as s:
        assert s.get(Case, cid).approved_action is None and s.get(Case, cid).status == "open"
        assert s.query(AuditLog).count() == before
        assert services.list_alerts(s, user(s, "vic"))  # viewers may read


def test_business_isolation(engine):
    with session_scope(engine) as s:
        alerts = seed_alerts(s, "A")
        case = services.open_case(s, user(s, "ana"), [a.id for a in alerts])
        cid, aid = case.id, alerts[0].id
        # business B has the SAME transaction id: both coexist
        services.record_assessment(s, "B", "T1", assessment("HIGH"), "m1")
        assert s.query(RiskAssessmentRow).filter_by(txn_external_id="T1").count() == 2
    with session_scope(engine) as s:
        bob = user(s, "bob")
        for call in (lambda: services.add_note(s, bob, cid, "x"),
                     lambda: services.approve_action(s, bob, cid, "ALLOW"),
                     lambda: services.resolve_case(s, bob, cid, "cleared"),
                     lambda: services.open_case(s, bob, [aid])):
            with pytest.raises(NotFound):
                call()
        assert [a.business_id for a in services.list_alerts(s, bob)] == []


def test_invalid_action_and_outcome_rejected(engine):
    with session_scope(engine) as s:
        alerts = seed_alerts(s)
        ana = user(s, "ana")
        case = services.open_case(s, ana, [alerts[0].id])
        with pytest.raises(ValueError):
            services.approve_action(s, ana, case.id, "BLOCK_ACCOUNT")
        with pytest.raises(ValueError):
            services.resolve_case(s, ana, case.id, "confirmed_fraud")


def test_resolving_suspicious_never_sets_a_fraud_label(engine):
    with session_scope(engine) as s:
        alerts = seed_alerts(s)
        ana = user(s, "ana")
        case = services.open_case(s, ana, [alerts[0].id])
        services.resolve_case(s, ana, case.id, "suspicious")
    with session_scope(engine) as s:
        assert s.query(Transaction).filter_by(external_id="T1").one().label is None


def test_only_admin_reads_audit(engine):
    with session_scope(engine) as s:
        seed_alerts(s)
        services.open_case(s, user(s, "ana"), [1])
        with pytest.raises(Forbidden):
            services.list_audit(s, user(s, "ana"))
        assert len(services.list_audit(s, user(s, "adm"))) == 1


def test_audit_log_has_no_mutation_api():
    public = {n for n in dir(services) if not n.startswith("_")}
    assert not {n for n in public if "audit" in n and n not in {"audit", "list_audit"}}
    assert not any(n.startswith(("update_", "delete_", "edit_")) and "audit" in n for n in public)


def test_assessment_roundtrip_from_real_risk_engine(engine):
    r = RiskEngine(load_policy(DEFAULT_POLICY_PATH)).assess(
        RiskInputs(ml_prob=0.9, anomaly=0.5, behaviour=0.6, graph=0.8, velocity=0.4,
                   account_history=0.0, merchant_risk=0.0, cluster_flagged=True))
    with session_scope(engine) as s:
        row = services.record_assessment(s, "A", "T9", r, "lgbm-1")
        assert (row.risk_level, row.action) == (r.risk_level, r.recommended_action)
        assert row.factors == r.risk_factors and row.policy_version == r.policy_version
