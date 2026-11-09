import pandas as pd
import pytest

from sentinel.graph.engine import (build_graph, cluster_degree_centrality, find_clusters,
                                   window_indicators)
from sentinel.ingestion.synthetic import generate

T0 = pd.Timestamp("2026-03-01 12:00", tz="UTC")


def _df(rows):
    out = []
    for i, r in enumerate(rows):
        base = dict(external_id=f"T{i}", account_id="A", merchant_id=None, device_id=None,
                    instrument_id=None, amount=10.0, ts=T0, business_id="b1")
        base.update(r)
        out.append(base)
    return pd.DataFrame(out)


def _m(minutes):
    return T0 + pd.Timedelta(minutes=minutes)


@pytest.fixture(scope="module")
def synth():
    return generate(seed=42)


@pytest.fixture(scope="module")
def synth_clusters(synth):
    return find_clusters(synth)


def test_no_edges_from_nulls():
    G = build_graph(_df([dict(), dict(account_id="B")]))
    assert G.number_of_edges() == 0
    assert {d["kind"] for _, d in G.nodes(data=True)} == {"account"}


def test_typed_nodes_and_edge_stats():
    G = build_graph(_df([dict(device_id="D", merchant_id="M", amount=5.0),
                         dict(device_id="D", merchant_id="M", amount=7.0, ts=_m(10))]))
    assert {d["kind"] for _, d in G.nodes(data=True)} == {"account", "device", "merchant"}
    edge = G[("account", "b1", "A")][("device", "b1", "D")]
    assert edge["n_txn"] == 2 and edge["total_amount"] == 12.0
    assert edge["first_ts"] == T0 and edge["last_ts"] == _m(10)


def test_family_pair_sharing_a_device_not_flagged():
    df = _df([dict(account_id="A", device_id="D", merchant_id="M1"),
              dict(account_id="B", device_id="D", merchant_id="M2", ts=_m(60 * 24))])
    assert [c for c in find_clusters(df) if c.flagged] == []


def test_shared_device_alone_not_flagged():
    df = _df([dict(account_id=a, device_id="D", merchant_id=f"M{i}", ts=_m(60 * 24 * i))
              for i, a in enumerate("ABC")])
    clusters = find_clusters(df)
    assert clusters and all(not c.flagged for c in clusters)
    assert clusters[0].signals == ["shared_device"]


def test_ring_detected_with_evidence(synth, synth_clusters):
    ring = synth[synth["scenario"] == "ring"]
    groups = [set(g["account_id"]) for _, g in ring.groupby("device_id") if g["account_id"].nunique() >= 4]
    assert len(groups) >= 3
    flagged = [c for c in synth_clusters if c.flagged]
    for members in groups:
        hit = [c for c in flagged if len(members & set(c.accounts)) >= 4]
        assert hit, "ring not found"
        assert {"shared_device", "common_merchant", "tight_window"} <= set(hit[0].signals)
        assert hit[0].risk_indicator >= 0.75
    ring_accounts = set(ring["account_id"])
    assert all(ring_accounts & set(c.accounts) for c in flagged)  # no flagged cluster without ring accounts


def test_legit_unusual_accounts_not_in_flagged_clusters(synth, synth_clusters):
    ring_accounts = set(synth[synth["scenario"] == "ring"]["account_id"])
    lu = set(synth[synth["scenario"] == "legit_unusual"]["account_id"]) - ring_accounts
    in_flagged = {a for c in synth_clusters if c.flagged for a in c.accounts}
    assert lu and not (lu & in_flagged)


def test_clusters_never_cross_business():
    rows = []
    for biz in ("b1", "b2"):
        for a in "ABC":  # identical account ids and device hash in both businesses
            rows += [dict(account_id=a, device_id="D", merchant_id="M", ts=_m(5 * len(rows)),
                          business_id=biz) for _ in range(2)]
    clusters = find_clusters(_df(rows))
    assert {c.business_id for c in clusters} == {"b1", "b2"}
    assert len(clusters) == 2 and all(len(c.accounts) == 3 for c in clusters)


def test_window_indicators_values():
    df = _df([dict(account_id="A", merchant_id="M", device_id="D", ts=_m(0)),
              dict(account_id="B", merchant_id="M", device_id="D", ts=_m(30)),
              dict(account_id="C", merchant_id="M", ts=_m(60)),
              dict(account_id="A", merchant_id="M", device_id="D", ts=_m(300)),
              dict(account_id="Z", ts=_m(310))])
    w = window_indicators(df, window_hours=2.0)
    assert w["merchant_accounts_window"].tolist() == [1, 2, 3, 1, 0]
    assert w["device_accounts_window"].tolist() == [1, 2, 0, 1, 0]


def test_window_indicators_point_in_time(synth):
    head = synth.iloc[:400]
    pd.testing.assert_frame_equal(window_indicators(synth).iloc[:400], window_indicators(head))


def test_louvain_is_deterministic(synth, synth_clusters):
    again = find_clusters(synth)
    assert [c.cluster_id for c in again] == [c.cluster_id for c in synth_clusters]


def test_degree_centrality_covers_all_nodes():
    G = build_graph(_df([dict(device_id="D", merchant_id="M")]))
    cent = cluster_degree_centrality(G)
    assert set(cent) == set(G.nodes) and all(0 <= v <= 1 for v in cent.values())
