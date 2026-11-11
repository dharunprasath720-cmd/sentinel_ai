import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import PW
from sentinel.api.app import create_app
from sentinel.context import AppContext
from sentinel.pipeline import HIGH_PLUS

SECRET = "dashboard-api-test-secret-that-is-at-least-32-bytes"
LEVELS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]


def make(world, with_bundle=True):
    df, scored, bundle, db = world
    ctx = AppContext(business_id="demo_biz", bundle=bundle if with_bundle else None)
    return TestClient(create_app(db, secret=SECRET, context=ctx))


def auth(client, name):
    r = client.post("/auth/login", json={"username": name, "password": PW})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ----------------------------------------------------------------------------- overview
def test_overview_matches_independent_counts(world):
    df, scored, *_ = world
    client = make(world)
    body = client.get("/metrics/overview", headers=auth(client, "ana")).json()
    expected = scored["risk_level"].value_counts()
    assert body["source"] == "synthetic"
    assert body["transactions"]["total"] == len(df)
    for level in LEVELS:
        assert body["transactions"]["by_level"][level] == int(expected.get(level, 0))
    bad = scored["risk_level"].isin(HIGH_PLUS)
    assert body["suspicious_value"] == pytest.approx(float(df.loc[bad, "amount"].sum()), abs=1e-6)
    assert sum(d["transactions"] for d in body["daily"]) == len(df)
    assert sum(d["high_plus"] for d in body["daily"]) == int(bad.sum())
    days = pd.to_datetime(df["ts"], utc=True).dt.strftime("%Y-%m-%d")
    assert [d["date"] for d in body["daily"]] == sorted(days.unique())


def test_overview_counts_open_alerts_and_flagged_clusters(world):
    client = make(world)
    body = client.get("/metrics/overview", headers=auth(client, "ana")).json()
    alerts = client.get("/alerts", headers=auth(client, "ana")).json()
    assert body["open_alerts"] == sum(1 for a in alerts if a["status"] == "open")
    assert body["flagged_clusters"] >= 1  # the demo data contains fraud rings
    assert body["open_cases"] >= 0


def test_overview_empty_source_is_zeros(world):
    client = make(world)
    body = client.get("/metrics/overview?source=paypal_sandbox", headers=auth(client, "ana")).json()
    assert body["transactions"]["total"] == 0
    assert all(v == 0 for v in body["transactions"]["by_level"].values())
    assert body["suspicious_value"] == 0 and body["daily"] == []
    assert body["open_alerts"] == 0 and body["open_cases"] == 0 and body["flagged_clusters"] == 0


def test_overview_validation_and_auth(world):
    client = make(world)
    assert client.get("/metrics/overview").status_code == 401
    assert client.get("/metrics/overview?source=bogus", headers=auth(client, "ana")).status_code == 422
    assert client.get("/metrics/overview", headers=auth(client, "vic")).status_code == 200  # viewers may read


def test_overview_is_business_scoped(world):
    client = make(world)
    body = client.get("/metrics/overview", headers=auth(client, "bob")).json()
    assert body["transactions"]["total"] == 0 and body["open_alerts"] == 0


# ----------------------------------------------------------------------------- models
def test_models_endpoint(world):
    client = make(world)
    body = client.get("/metrics/models", headers=auth(client, "vic")).json()
    assert body["version"] and body["evaluation"] == "held-out test split"
    lgbm = body["models"]["lightgbm"]
    assert {"pr_auc", "recall", "precision", "calibrator", "brier_raw", "brier_calibrated"} <= set(lgbm)
    assert body["models"]["iforest"]["calibrator"] is None
    assert "held-out" in body["caveat"] and "missed" in body["caveat"]
    assert client.get("/metrics/models").status_code == 401


def test_models_endpoint_503_without_a_model(world):
    client = make(world, with_bundle=False)
    assert client.get("/metrics/models", headers=auth(client, "ana")).status_code == 503


def test_dashboard_responses_never_contain_label(world):
    client = make(world)
    ana = auth(client, "ana")
    for path in ("/metrics/overview", "/metrics/models"):
        assert "label" not in client.get(path, headers=ana).text.lower().replace("calibrat", "")
