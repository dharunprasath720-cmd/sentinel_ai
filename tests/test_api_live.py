import json
import threading
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from live_fakes import FakePayPal, FakeScorer, record
from sentinel.api.app import create_app
from sentinel.cases.orm import Alert, User
from sentinel.context import AppContext
from sentinel.db import init_db, make_engine, session_scope
from sentinel.ingestion.orm import Transaction
from sentinel.security import hash_password

SECRET = "live-api-test-secret-that-is-at-least-32-bytes"
PW = "Passw0rd-for-live-tests"
GOOD = {"paypal-transmission-sig": "good", "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1", "paypal-transmission-id": "t1",
        "paypal-transmission-time": "2026-11-09T10:00:00Z"}


def demo_frame(n=12):
    rows = []
    for i in range(n):
        rows.append({"external_id": f"SIM-{i}", "account_id": f"ACC_{i % 3}", "merchant_id": "M_1",
                     "device_id": None, "instrument_id": None, "amount": 300.0 if i % 2 else 10.0,
                     "currency": "USD", "ts": f"2026-03-01T11:{i:02d}:00+00:00", "type": "PAYMENT",
                     "payment_method": "card", "status": "completed", "geo": None, "label": None,
                     "source": "synthetic", "business_id": "A"})
    return pd.DataFrame(rows)


def capture_event(event_id="WH-1", capture_id="CAP-1", amount="250.00"):
    return json.dumps({"id": event_id, "event_type": "PAYMENT.CAPTURE.COMPLETED",
                       "create_time": "2026-11-09T10:00:01Z", "resource": {
                           "id": capture_id, "status": "COMPLETED", "custom_id": "ACC_00007",
                           "amount": {"value": amount, "currency_code": "USD"},
                           "create_time": "2026-11-09T10:00:00Z",
                           "payee": {"merchant_id": "MERCH1"}}}, indent=2).encode()


@pytest.fixture
def env():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with session_scope(engine) as s:
        for name, role, biz in (("ana", "analyst", "A"), ("vic", "viewer", "A"), ("bob", "analyst", "B")):
            s.add(User(username=name, password_hash=hash_password(PW), role=role, business_id=biz))
    scorer, paypal = FakeScorer(), FakePayPal()
    ctx = AppContext(business_id="A", live_scorer=scorer, paypal=paypal, webhook_id="WH123",
                     demo_frame=demo_frame(), model_version="m-1")
    app = create_app(engine, secret=SECRET, context=ctx)
    return TestClient(app), app, engine, scorer, paypal


def auth(client, name):
    r = client.post("/auth/login", json={"username": name, "password": PW})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class Publisher:
    """Publishes events from a thread until stopped (the SSE subscription may attach late)."""
    def __init__(self, bus, events):
        self.bus, self.events, self.stop = bus, events, threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop.is_set():
            for biz, ev in self.events:
                self.bus.publish(biz, ev)
            time.sleep(0.03)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self.stop.set()
        self.t.join(2)


def data_lines(response):
    return [json.loads(l[5:]) for l in response.text.splitlines() if l.startswith("data:")]


def test_live_endpoints_say_503_when_live_scoring_is_not_configured():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with session_scope(engine) as s:
        s.add(User(username="ana", password_hash=hash_password(PW), role="analyst", business_id="A"))
    client = TestClient(create_app(engine, secret=SECRET))
    h = auth(client, "ana")
    assert client.get("/metrics/live", headers=h).status_code == 503
    assert client.get("/stream/events", headers=h).status_code == 503
    assert client.post("/paypal/webhook", content=b"{}").status_code == 503


def test_stream_requires_a_token_and_delivers_sse_frames(env):
    client, app, *_ = env
    assert client.get("/stream/events?limit=1").status_code == 401
    ev = {"external_id": "S-1", "business_id": "A", "risk_level": "HIGH"}
    with Publisher(app.state.bus, [("A", ev)]):
        r = client.get("/stream/events?limit=1", headers=auth(client, "vic"))  # viewers may stream
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert data_lines(r) == [ev]


def test_stream_is_scoped_to_the_users_business(env):
    client, app, *_ = env
    events = [("A", {"external_id": "A-1", "business_id": "A"}),
              ("B", {"external_id": "B-1", "business_id": "B"})]
    with Publisher(app.state.bus, events):
        got_a = client.get("/stream/events?limit=1", headers=auth(client, "ana"))
        got_b = client.get("/stream/events?limit=1", headers=auth(client, "bob"))
    assert [e["external_id"] for e in data_lines(got_a)] == ["A-1"]
    assert [e["external_id"] for e in data_lines(got_b)] == ["B-1"]


def test_stream_limit_is_validated(env):
    client, *_ = env
    assert client.get("/stream/events?limit=0", headers=auth(client, "ana")).status_code == 422


def wait_until(predicate, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_simulator_roles_validation_and_replay(env):
    client, app, engine, scorer, _ = env
    assert client.post("/simulate/start", json={"speed": 100, "limit": 5}, headers=auth(client, "vic")).status_code == 403
    # an analyst of ANOTHER business may not drive this business's replay
    assert client.post("/simulate/start", json={"speed": 100, "limit": 5}, headers=auth(client, "bob")).status_code == 403
    assert client.post("/simulate/stop", headers=auth(client, "bob")).status_code == 403
    ana = auth(client, "ana")
    assert client.post("/simulate/start", json={"speed": 0, "limit": 5}, headers=ana).status_code == 422
    assert client.post("/simulate/start", json={"speed": 100, "limit": 0}, headers=ana).status_code == 422
    assert client.post("/simulate/start", json={"speed": 500, "limit": 5}, headers=ana).status_code == 200
    assert wait_until(lambda: client.get("/metrics/live", headers=ana).json()["processed"] == 5)
    assert wait_until(lambda: not client.get("/metrics/live", headers=ana).json()["simulator"]["running"])
    with session_scope(engine) as s:
        assert s.query(Transaction).count() == 5 and s.query(Alert).count() == 2  # 300.0 rows are HIGH


def test_only_one_simulator_runs_at_a_time_and_it_can_be_stopped(env):
    client, *_ = env
    ana = auth(client, "ana")
    assert client.post("/simulate/start", json={"speed": 1, "limit": 12}, headers=ana).status_code == 200
    assert client.post("/simulate/start", json={"speed": 1, "limit": 12}, headers=ana).status_code == 409
    assert client.post("/simulate/stop", headers=ana).status_code == 200
    assert not client.get("/metrics/live", headers=ana).json()["simulator"]["running"]


def test_metrics_live_shape(env):
    client, *_ = env
    m = client.get("/metrics/live", headers=auth(client, "vic")).json()
    for k in ("processed", "alerts", "p50_ms", "p95_ms", "max_ms", "dropped", "simulator"):
        assert k in m
    assert set(m["simulator"]) == {"running", "sent", "errors"}


def post(client, body, headers=GOOD):
    return client.post("/paypal/webhook", content=body, headers=headers)  # note: NO bearer token


def test_webhook_route_scores_end_to_end_and_is_idempotent(env):
    client, app, engine, scorer, paypal = env
    body = capture_event()
    r = post(client, body)
    assert r.status_code == 200 and r.json() == {"status": "processed", "transaction": "PP-CAP-1"}
    assert paypal.bodies == [body]  # the route handed PayPal the exact received bytes
    assert scorer.seen == ["PP-CAP-1"]
    with session_scope(engine) as s:
        t = s.query(Transaction).one()
        assert (t.source, t.account_id, t.amount) == ("paypal_sandbox", "ACC_00007", 250.0)
        assert s.query(Alert).count() == 1  # the fake scorer rates 250 as HIGH
    again = post(client, body)
    assert again.status_code == 200 and again.json()["status"] == "duplicate"
    assert scorer.seen == ["PP-CAP-1"]


def test_webhook_route_status_codes(env):
    client, app, engine, scorer, paypal = env
    assert post(client, capture_event("WH-2", "CAP-2"), headers={**GOOD, "paypal-transmission-sig": "forged"}).status_code == 401
    assert post(client, b"not json").status_code == 400
    paypal.mode = "outage"
    assert post(client, capture_event("WH-3", "CAP-3")).status_code == 503
    with session_scope(engine) as s:
        assert s.query(Transaction).count() == 0 and s.query(Alert).count() == 0
    assert scorer.seen == []


def test_oversized_webhook_bodies_are_rejected_before_any_paypal_call(env):
    client, app, engine, scorer, paypal = env
    big = b'{"id":"WH-BIG","event_type":"X","pad":"' + b"a" * 70_000 + b'"}'
    r = post(client, big)
    assert r.status_code == 413 and paypal.bodies == [] and scorer.seen == []


def test_concurrent_webhook_verifications_are_capped_so_the_pool_cannot_be_exhausted():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)

    class Blocking(FakePayPal):
        def __init__(self):
            super().__init__()
            self.entered, self.release = threading.Event(), threading.Event()

        def verify_webhook(self, headers, raw_body, webhook_id):
            self.entered.set()
            self.release.wait(10)
            return True

    pp = Blocking()
    ctx = AppContext(business_id="A", live_scorer=FakeScorer(), paypal=pp, webhook_id="WH123", model_version="m")
    app = create_app(engine, secret=SECRET, context=ctx, webhook_concurrency=1)
    first = {}
    t = threading.Thread(target=lambda: first.update(r=post(TestClient(app), capture_event("WH-A", "CAP-A"))))
    t.start()
    assert pp.entered.wait(5)
    second = post(TestClient(app), capture_event("WH-B", "CAP-B"))
    assert second.status_code == 503 and "retry-after" in second.headers  # shed immediately, PayPal retries later
    pp.release.set()
    t.join(10)
    assert first["r"].status_code == 200


def test_metrics_are_per_business(env):
    client, app, *_ = env
    app.state.live.process(record(1, amount=300, business="A"))
    mine = client.get("/metrics/live", headers=auth(client, "ana")).json()
    other = client.get("/metrics/live", headers=auth(client, "bob")).json()
    assert mine["processed"] == 1 and mine["alerts"] == 1
    assert other["processed"] == 0 and other["alerts"] == 0 and other["dropped"] == 0
    assert other["simulator"] == {"running": False, "sent": 0, "errors": 0}

def test_simulator_can_start_part_way_through_the_stream(env):
    client, app, engine, scorer, _ = env
    ana = auth(client, "ana")
    r = client.post("/simulate/start", json={"speed": 500, "limit": 100, "offset": 8}, headers=ana)
    assert r.status_code == 200 and r.json()["offset"] == 8
    assert wait_until(lambda: not client.get("/metrics/live", headers=ana).json()["simulator"]["running"])
    with session_scope(engine) as s:
        # only SIM-8 to SIM-11 were replayed: the skipped events are not scored or stored
        assert {t.external_id for t in s.query(Transaction)} == {"SIM-8", "SIM-9", "SIM-10", "SIM-11"}
    assert scorer.seen == ["SIM-8", "SIM-9", "SIM-10", "SIM-11"]


def test_offset_defaults_to_zero_and_limit_counts_from_the_offset(env):
    client, app, engine, scorer, _ = env
    ana = auth(client, "ana")
    r = client.post("/simulate/start", json={"speed": 500, "limit": 3}, headers=ana)
    assert r.json()["offset"] == 0
    assert wait_until(lambda: not client.get("/metrics/live", headers=ana).json()["simulator"]["running"])
    assert scorer.seen == ["SIM-0", "SIM-1", "SIM-2"]
    client.post("/simulate/start", json={"speed": 500, "limit": 2, "offset": 5}, headers=ana)
    assert wait_until(lambda: scorer.seen[-2:] == ["SIM-5", "SIM-6"])


def test_offset_is_validated(env):
    client, *_ = env
    ana = auth(client, "ana")
    assert client.post("/simulate/start", json={"speed": 100, "limit": 5, "offset": -1}, headers=ana).status_code == 422
    assert client.post("/simulate/start", json={"speed": 100, "limit": 5, "offset": 1.5}, headers=ana).status_code == 422
    beyond = client.post("/simulate/start", json={"speed": 100, "limit": 5, "offset": 12}, headers=ana)  # 12 events: 0 to 11
    assert beyond.status_code == 422 and "beyond" in beyond.json()["detail"]
    assert client.post("/simulate/start", json={"speed": 500, "limit": 5, "offset": 11}, headers=ana).status_code == 200  # the last event


def test_a_rejected_offset_does_not_start_or_block_the_simulator(env):
    client, *_ = env
    ana = auth(client, "ana")
    assert client.post("/simulate/start", json={"speed": 100, "limit": 5, "offset": 99}, headers=ana).status_code == 422
    assert not client.get("/metrics/live", headers=ana).json()["simulator"]["running"]
    assert client.post("/simulate/start", json={"speed": 500, "limit": 2}, headers=ana).status_code == 200  # not a 409
