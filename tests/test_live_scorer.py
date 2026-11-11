import numpy as np
import pandas as pd
import pytest

from sentinel.features.engine import build_features
from sentinel.ingestion.synthetic import generate
from sentinel.live.scorer import LiveScorer
from sentinel.models.split import chronological_split
from sentinel.models.train import train
from sentinel.pipeline import fit_normalisers, score_frame
from sentinel.risk.engine import DEFAULT_POLICY_PATH, RiskEngine, load_policy

HIGH_PLUS = {"HIGH", "CRITICAL"}
N_EVENTS = 450


def events_of(frame):
    return frame.to_dict("records")


@pytest.fixture(scope="module")
def world():
    df = generate(seed=42, n_accounts=300, days=20)
    tr, va, te = chronological_split(df)
    bundle = train(df, seed=42)
    engine = RiskEngine(load_policy(DEFAULT_POLICY_PATH))
    norms = fit_normalisers(tr)
    batch = score_frame(df, bundle, engine, norms)
    held = va.index.union(te.index)
    first_ring = min(i for i in held if df.loc[i, "scenario"] == "ring")
    start = max(0, first_ring - 100)  # replay a window that contains a ring
    history, stream = df.iloc[:start], df.iloc[start:start + N_EVENTS]
    scorer = LiveScorer(bundle, engine, norms, history, history_levels=batch.loc[history.index, "risk_level"])
    scored = [scorer.score(e) for e in events_of(stream)]
    return df, batch, stream, scorer, scored, (bundle, engine, norms)


def test_event_features_equal_batch_features(world):
    df, _, stream, _, scored, _ = world
    live = pd.DataFrame([s.features for s in scored], index=stream.index)
    batch = build_features(df).loc[stream.index]
    pd.testing.assert_frame_equal(live, batch, check_dtype=False, rtol=1e-9, atol=1e-9)


def test_levels_agree_with_batch(world):
    df, batch, stream, _, scored, _ = world
    live_levels = pd.Series([s.assessment.risk_level for s in scored], index=stream.index)
    agree = (live_levels == batch.loc[stream.index, "risk_level"]).mean()
    ring = stream.index[df.loc[stream.index, "scenario"] == "ring"]
    live_ring = live_levels[ring].isin(HIGH_PLUS).mean()
    batch_ring = batch.loc[ring, "risk_level"].isin(HIGH_PLUS).mean()
    print(f"\nlive/batch level agreement {agree:.3f}; ring HIGH+ live {live_ring:.2f} vs batch {batch_ring:.2f}; n={len(stream)} ring={len(ring)}")
    assert agree >= 0.90
    assert len(ring) >= 10 and abs(live_ring - batch_ring) <= 0.10


def test_duplicate_event_returns_cached_and_changes_nothing(world):
    _, _, stream, scorer, scored, _ = world
    before = scorer.n_processed
    again = scorer.score(events_of(stream.iloc[[5]])[0])
    assert again is scored[5] and scorer.n_processed == before


def test_late_event_is_flagged_and_does_not_move_baseline(world):
    df, _, stream, scorer, scored, _ = world
    victim = scored[len(scored) // 2]
    row = df.loc[stream.index[len(scored) // 2]].to_dict()
    before = scorer.behaviour_profile(row["account_id"], row["business_id"])
    late = dict(row, external_id="LATE-1", amount=row["amount"] * 40,
                ts=pd.Timestamp(stream["ts"].iloc[0]) - pd.Timedelta(hours=3))
    out = scorer.score(late)
    assert out.late is True and out.behaviour_reasons == [] and out.inputs["behaviour"] == 0
    assert scorer.behaviour_profile(row["account_id"], row["business_id"]) == before
    assert victim.late is False


def test_latency_is_measured_and_stays_in_a_sane_range(world):
    """Wall-clock latency depends on the machine. Measured on a quiet laptop: p50 81 ms, p95 162 ms;
    under heavy OneDrive/memory contention the same code gave p50 212 ms, p95 377-410 ms. So this
    only guards against pathological regressions (an accidental O(n^2) would be many seconds);
    the real numbers are reported by the Day 3 gate and /metrics/live."""
    *_, scored, _ = world
    lat = np.array([s.latency_ms for s in scored])
    print(f"\nlive scoring latency over {len(lat)} events: p50 {np.percentile(lat, 50):.1f} ms, "
          f"p95 {np.percentile(lat, 95):.1f} ms, max {lat.max():.1f} ms")
    assert (lat > 0).all() and np.percentile(lat, 95) < 1500


def test_businesses_do_not_influence_each_other():
    def biz(seed, name):
        d = generate(seed=seed, n_accounts=150, days=20)
        d["business_id"] = name  # same account ids and external ids in both
        return d

    a, b = biz(1, "A"), biz(2, "B")
    bundle = train(b, seed=42)
    engine = RiskEngine(load_policy(DEFAULT_POLICY_PATH))
    norms = fit_normalisers(chronological_split(b)[0])
    cut = int(len(b) * 0.9)
    stream_b = b.iloc[cut:cut + 80]
    alone = LiveScorer(bundle, engine, norms, b.iloc[:cut])
    mixed = LiveScorer(bundle, engine, norms, pd.concat([a.iloc[:cut], b.iloc[:cut]]))
    r_alone = [alone.score(e).assessment.risk_score for e in events_of(stream_b)]
    r_mixed = []
    for e in events_of(stream_b):
        mixed.score(dict(a.iloc[cut + len(r_mixed)].to_dict()))  # business A traffic in between
        r_mixed.append(mixed.score(e).assessment.risk_score)
    np.testing.assert_allclose(r_mixed, r_alone, rtol=1e-9, atol=1e-9)


def test_live_cluster_ids_match_the_ids_the_graph_engine_and_tools_compute(world):
    """Found while filming the demo: live scoring hashed its internal partition key ("default|synthetic")
    into the cluster id, so a live-flagged ring could not be opened in the Graph Explorer or by the agent's
    get_graph_cluster tool, both of which compute the id from the real business."""
    from sentinel.graph.engine import find_clusters
    from sentinel.pipeline import CLUSTER_LOOKBACK_SECS
    df, _, stream, _, scored, _ = world
    flagged = [(i, s) for i, s in zip(stream.index, scored) if s is not None and s.cluster_id]
    assert flagged, "the replay window contains a flagged ring"
    ts = pd.to_datetime(df["ts"], utc=True)
    for i, s in flagged[:5]:
        t = ts.loc[i]
        window = df[((ts >= t - pd.Timedelta(seconds=CLUSTER_LOOKBACK_SECS)) & (ts < t)) | (df.index == i)]
        expected = {c.cluster_id for c in find_clusters(window)
                    if c.flagged and df.loc[i, "external_id"] in set(c.txn_ids)}
        assert s.cluster_id in expected, f"{s.cluster_id} is not one of {expected}"
