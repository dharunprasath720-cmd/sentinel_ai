import pytest
from fastapi.testclient import TestClient

from sentinel.api.app import create_app
from sentinel.cases import services
from sentinel.cases.orm import AuditLog, Case, RiskAssessmentRow, User
from sentinel.db import init_db, make_engine, session_scope
from sentinel.risk.engine import RiskAssessment
from sentinel.security import hash_password

SECRET = "api-test-secret-that-is-at-least-32-bytes-long"
PW = "Passw0rd-for-tests"


def _a(level, action, score):
    return RiskAssessment(risk_score=score, risk_level=level, recommended_action=action,
                          calibrated_fraud_probability=0.8, risk_factors=["Suspicious account relationships"],
                          contributions={}, policy_version="p1")


@pytest.fixture
def env():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with session_scope(engine) as s:
        for name, role, biz in (("ana", "analyst", "A"), ("vic", "viewer", "A"),
                                ("adm", "admin", "A"), ("bob", "analyst", "B")):
            s.add(User(username=name, password_hash=hash_password(PW), role=role, business_id=biz))
        services.record_assessment(s, "A", "T1", _a("HIGH", "REVIEW", 0.55), "lgbm-1")
        services.create_alerts(s, "A", s.query(RiskAssessmentRow).all())
    return TestClient(create_app(engine, secret=SECRET)), engine


def login(client, name, password=PW):
    r = client.post("/auth/login", json={"username": name, "password": password})
    return r


def auth(client, name):
    return {"Authorization": f"Bearer {login(client, name).json()['access_token']}"}


def test_login_ok_and_bad_credentials_look_identical(env):
    client, _ = env
    ok = login(client, "ana")
    assert ok.status_code == 200 and ok.json()["role"] == "analyst" and ok.json()["token_type"] == "bearer"
    bad_pw, no_user = login(client, "ana", "wrong"), login(client, "nobody")
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()  # does not reveal which usernames exist


def test_missing_or_tampered_token_401(env):
    client, _ = env
    assert client.get("/alerts").status_code == 401
    assert client.get("/alerts", headers={"Authorization": "Bearer garbage"}).status_code == 401
    good = auth(client, "ana")["Authorization"]
    assert client.get("/alerts", headers={"Authorization": good + "x"}).status_code == 401


def test_analyst_full_flow_and_audit_visible_to_admin_only(env):
    client, _ = env
    h = auth(client, "ana")
    alerts = client.get("/alerts", headers=h).json()
    assert [a["txn_external_id"] for a in alerts] == ["T1"]
    case_id = client.post("/cases", json={"alert_ids": [alerts[0]["id"]]}, headers=h).json()["id"]
    assert client.post(f"/cases/{case_id}/notes", json={"body": "Shared device with 4 accounts."},
                       headers=h).status_code == 200
    assert client.post(f"/cases/{case_id}/approve-action", json={"action": "REVIEW"}, headers=h).status_code == 200
    assert client.post(f"/cases/{case_id}/resolve", json={"outcome": "suspicious"}, headers=h).status_code == 200
    detail = client.get(f"/cases/{case_id}", headers=h).json()
    assert detail["status"] == "resolved_suspicious" and detail["approved_action"] == "REVIEW"
    assert detail["notes"][0]["author"] == "ana" and detail["alerts"][0]["assessment"]["risk_level"] == "HIGH"
    assert client.get("/audit", headers=h).status_code == 403
    audit = client.get("/audit", headers=auth(client, "adm")).json()
    assert [e["action"] for e in audit] == ["open_case", "add_note", "approve_action", "resolve_case"]


def test_viewer_gets_403_on_actions_and_no_state_change(env):
    client, engine = env
    ana = auth(client, "ana")
    alert_id = client.get("/alerts", headers=ana).json()[0]["id"]
    case_id = client.post("/cases", json={"alert_ids": [alert_id]}, headers=ana).json()["id"]
    vic = auth(client, "vic")
    assert client.get("/alerts", headers=vic).status_code == 200  # viewers may read
    for method, path, body in (("post", f"/cases/{case_id}/approve-action", {"action": "VERIFY"}),
                               ("post", f"/cases/{case_id}/notes", {"body": "x"}),
                               ("post", f"/cases/{case_id}/resolve", {"outcome": "cleared"}),
                               ("post", "/cases", {"alert_ids": [alert_id]})):
        assert getattr(client, method)(path, json=body, headers=vic).status_code == 403
    with session_scope(engine) as s:
        case = s.get(Case, case_id)
        assert case.approved_action is None and case.status == "open"
        assert s.query(AuditLog).count() == 1  # only the analyst's open_case


def test_cross_business_ids_return_404_not_403(env):
    client, _ = env
    ana = auth(client, "ana")
    alert_id = client.get("/alerts", headers=ana).json()[0]["id"]
    case_id = client.post("/cases", json={"alert_ids": [alert_id]}, headers=ana).json()["id"]
    bob = auth(client, "bob")
    assert client.get(f"/cases/{case_id}", headers=bob).status_code == 404
    assert client.post(f"/cases/{case_id}/approve-action", json={"action": "ALLOW"}, headers=bob).status_code == 404
    assert client.post("/cases", json={"alert_ids": [alert_id]}, headers=bob).status_code == 404
    assert client.get("/alerts", headers=bob).json() == []
    assert client.get("/cases/99999", headers=ana).status_code == 404


def test_invalid_bodies_rejected_with_422(env):
    client, _ = env
    ana = auth(client, "ana")
    alert_id = client.get("/alerts", headers=ana).json()[0]["id"]
    case_id = client.post("/cases", json={"alert_ids": [alert_id]}, headers=ana).json()["id"]
    assert client.post(f"/cases/{case_id}/approve-action", json={"action": "BLOCK_ACCOUNT"}, headers=ana).status_code == 422
    assert client.post(f"/cases/{case_id}/resolve", json={"outcome": "confirmed_fraud"}, headers=ana).status_code == 422
    assert client.post(f"/cases/{case_id}/notes", json={"body": ""}, headers=ana).status_code == 422
    assert client.post("/cases", json={"alert_ids": []}, headers=ana).status_code == 422


def test_app_refuses_without_a_strong_secret(env, monkeypatch):
    _, engine = env
    monkeypatch.delenv("SENTINEL_JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        create_app(engine)
    with pytest.raises(RuntimeError):
        create_app(engine, secret="too-short")
    monkeypatch.setenv("SENTINEL_JWT_SECRET", SECRET)
    assert create_app(engine) is not None


def test_role_change_takes_effect_on_existing_token(env):
    client, engine = env
    ana = auth(client, "ana")
    with session_scope(engine) as s:
        s.query(User).filter_by(username="ana").one().role = "viewer"
    alert_id = client.get("/alerts", headers=ana).json()[0]["id"]
    assert client.post("/cases", json={"alert_ids": [alert_id]}, headers=ana).status_code == 403
