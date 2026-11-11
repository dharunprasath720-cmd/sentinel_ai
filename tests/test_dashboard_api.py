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


# ----------------------------------------------------------------------------- transactions
from agent_helpers import pick  # noqa: E402


def ring_txn(world):
    return world[0].loc[pick(world, "ring", HIGH_PLUS), "external_id"]


def test_transactions_list_order_filter_limit(world):
    client = make(world)
    ana = auth(client, "ana")
    rows = client.get("/transactions?limit=200", headers=ana).json()
    assert len(rows) == 200
    keys = [(r["ts"], r["external_id"]) for r in rows]
    assert keys == sorted(keys, reverse=True)
    assert {"external_id", "ts", "amount", "account_id", "merchant_id", "source", "risk_level", "risk_score",
            "action", "cluster_id"} <= set(rows[0])
    crit = client.get("/transactions?level=CRITICAL&limit=50", headers=ana).json()
    assert crit and all(r["risk_level"] == "CRITICAL" for r in crit)
    assert len(client.get("/transactions?limit=3", headers=ana).json()) == 3
    assert client.get("/transactions?limit=0", headers=ana).status_code == 422
    assert client.get("/transactions?limit=201", headers=ana).status_code == 422
    assert client.get("/transactions?level=SEVERE", headers=ana).status_code == 422


def test_transactions_list_source_and_scope(world):
    client = make(world)
    assert client.get("/transactions?source=paypal_sandbox", headers=auth(client, "ana")).json() == []
    assert client.get("/transactions", headers=auth(client, "bob")).json() == []
    assert client.get("/transactions").status_code == 401
    assert client.get("/transactions", headers=auth(client, "vic")).status_code == 200


def test_transaction_detail_has_all_parts(world):
    df, scored, *_ = world
    idx = pick(world, "ring", HIGH_PLUS)
    client = make(world)
    body = client.get(f"/transactions/{df.loc[idx, 'external_id']}", headers=auth(client, "vic")).json()
    assert body["details"]["transaction"]["external_id"] == df.loc[idx, "external_id"]
    assert body["risk"]["risk_level"] == scored.loc[idx, "risk_level"]
    assert body["explanation"]["contributions"] and body["explanation_unavailable"] is None
    assert "related" in body and body["related"]["account_id"] == df.loc[idx, "account_id"]


def test_transaction_detail_404_and_scope(world):
    client = make(world)
    t = ring_txn(world)
    assert client.get(f"/transactions/{t}").status_code == 401
    assert client.get("/transactions/does-not-exist", headers=auth(client, "ana")).status_code == 404
    assert client.get(f"/transactions/{t}", headers=auth(client, "bob")).status_code == 404


def test_transaction_detail_without_model(world):
    client = make(world, with_bundle=False)
    r = client.get(f"/transactions/{ring_txn(world)}", headers=auth(client, "ana"))
    body = r.json()
    assert r.status_code == 200 and body["explanation"] is None and body["explanation_unavailable"]
    assert body["risk"] is not None


def test_transaction_endpoints_never_expose_label(world):
    client = make(world)
    ana = auth(client, "ana")
    for path in ("/transactions?limit=20", f"/transactions/{ring_txn(world)}"):
        assert '"label"' not in client.get(path, headers=ana).text


# ----------------------------------------------------------------------------- cases
def open_case_via_api(client, headers, n_alerts):
    alerts = client.get("/alerts?status=open", headers=headers).json()
    assert len(alerts) >= n_alerts
    ids = [a["id"] for a in alerts[:n_alerts]]
    r = client.post("/cases", json={"alert_ids": ids}, headers=headers)
    assert r.status_code == 200
    return r.json()["id"]


def test_cases_list_shape_and_order(world):
    client = make(world)
    ana = auth(client, "ana")
    first = open_case_via_api(client, ana, 1)
    second = open_case_via_api(client, ana, 2)
    rows = client.get("/cases", headers=ana).json()
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids, reverse=True) and ids.index(second) < ids.index(first)
    by_id = {r["id"]: r for r in rows}
    assert by_id[first]["n_alerts"] == 1 and by_id[second]["n_alerts"] == 2
    assert {"id", "status", "approved_action", "n_alerts", "created_at"} <= set(by_id[second])


def test_cases_list_scope_and_auth(world):
    client = make(world)
    assert client.get("/cases").status_code == 401
    assert client.get("/cases", headers=auth(client, "bob")).json() == []
    assert client.get("/cases", headers=auth(client, "vic")).status_code == 200


def test_case_detail_route_still_works(world):
    client = make(world)
    ana = auth(client, "ana")
    cid = open_case_via_api(client, ana, 1)
    body = client.get(f"/cases/{cid}", headers=ana).json()
    assert body["id"] == cid and len(body["alerts"]) == 1


# ----------------------------------------------------------------------------- graph
def ring_cluster_id(client, headers):
    clusters = client.get("/graph/clusters", headers=headers).json()
    assert clusters, "the demo data contains flagged rings"
    return clusters[0]["cluster_id"]


def assert_well_formed(g):
    ids = {n["id"] for n in g["nodes"]}
    assert len(ids) == len(g["nodes"]) and len(g["nodes"]) <= 200
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert {n["kind"] for n in g["nodes"]} <= {"account", "device", "merchant"}
    assert all(n["risk_level"] in LEVELS + [None] for n in g["nodes"])
    assert isinstance(g["truncated"], bool)


def test_graph_clusters_lists_flagged_ring_clusters(world):
    client = make(world)
    rows = client.get("/graph/clusters", headers=auth(client, "vic")).json()
    assert rows and len(rows) <= 20
    assert {"cluster_id", "n_accounts", "n_devices", "n_merchants", "signals", "risk_indicator"} <= set(rows[0])
    assert client.get("/graph/clusters?source=paypal_sandbox", headers=auth(client, "ana")).json() == []


def test_graph_for_cluster_has_ring_accounts_and_edges(world):
    client = make(world)
    ana = auth(client, "ana")
    g = client.get(f"/graph?cluster={ring_cluster_id(client, ana)}", headers=ana).json()
    assert_well_formed(g)
    kinds = {n["kind"] for n in g["nodes"]}
    assert "account" in kinds and "device" in kinds and g["edges"]


def test_graph_for_account(world):
    df, *_ = world
    idx = pick(world, "ring", HIGH_PLUS)
    acct, dev = df.loc[idx, "account_id"], df.loc[idx, "device_id"]
    client = make(world)
    g = client.get(f"/graph?account={acct}&hours=24", headers=auth(client, "ana")).json()
    assert_well_formed(g)
    ids = {n["id"] for n in g["nodes"]}
    assert f"account:{acct}" in ids and (pd.isna(dev) or f"device:{dev}" in ids)


def test_graph_parameter_validation(world):
    client = make(world)
    ana = auth(client, "ana")
    acct = world[0].loc[pick(world, "ring", HIGH_PLUS), "account_id"]
    assert client.get("/graph", headers=ana).status_code == 422
    assert client.get(f"/graph?cluster=C1&account={acct}", headers=ana).status_code == 422
    assert client.get(f"/graph?account={acct}&hours=0", headers=ana).status_code == 422
    assert client.get(f"/graph?account={acct}&hours=169", headers=ana).status_code == 422
    assert client.get("/graph?account=NOPE", headers=ana).status_code == 404
    assert client.get("/graph?cluster=CL_nope", headers=ana).status_code == 404


def test_graph_truncates_at_the_node_cap(world, monkeypatch):
    from sentinel.dashboard import queries
    monkeypatch.setattr(queries, "MAX_GRAPH_NODES", 3)
    df, *_ = world
    acct = df.loc[pick(world, "ring", HIGH_PLUS), "account_id"]
    client = make(world)
    g = client.get(f"/graph?account={acct}&hours=168", headers=auth(client, "ana")).json()
    ids = {n["id"] for n in g["nodes"]}
    assert g["truncated"] is True and len(ids) == 3 and f"account:{acct}" in ids
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])


def test_graph_scope_and_auth(world):
    client = make(world)
    acct = world[0].loc[pick(world, "ring", HIGH_PLUS), "account_id"]
    assert client.get(f"/graph?account={acct}").status_code == 401
    assert client.get(f"/graph?account={acct}", headers=auth(client, "bob")).status_code == 404
    assert client.get("/graph/clusters", headers=auth(client, "bob")).json() == []
