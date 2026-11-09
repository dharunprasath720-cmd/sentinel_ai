import numpy as np
import pandas as pd
import pytest

from sentinel.features.engine import build_features
from sentinel.ingestion.synthetic import generate
from sentinel.models.split import chronological_split
from sentinel.models.train import train
from sentinel.pipeline import fit_normalisers, score_frame
from sentinel.risk.engine import DEFAULT_POLICY_PATH, RiskEngine, load_policy

HIGH_PLUS = {"HIGH", "CRITICAL"}


@pytest.fixture(scope="module")
def world():
    df = generate(seed=42, n_accounts=300, days=20)
    tr, va, te = chronological_split(df)
    bundle = train(df, seed=42)
    engine = RiskEngine(load_policy(DEFAULT_POLICY_PATH))
    norms = fit_normalisers(tr)
    scored = score_frame(df, bundle, engine, norms)
    held_out = va.index.union(te.index)  # rows the models never trained on (val + test)
    return df, tr, held_out, bundle, engine, norms, scored


def _table(df, scored, idx):
    return pd.crosstab(df.loc[idx, "scenario"], scored.loc[idx, "risk_level"])


def test_output_columns_and_alignment(world):
    df, _, _, _, _, _, scored = world
    assert scored.index.equals(df.index)
    for c in ("risk_score", "risk_level", "recommended_action", "calibrated_fraud_probability",
              "cluster_flagged", "risk_factors", "ml_prob", "graph", "behaviour"):
        assert c in scored.columns
    assert "confirmed" not in " ".join(scored.columns).lower()  # suspicion, never a verdict
    assert scored["risk_score"].between(0, 1).all()


def test_ring_rows_reach_review_or_above(world):
    df, _, te, *_, scored = world
    ring = te[df.loc[te, "scenario"] == "ring"]
    assert len(ring) >= 10
    hit = scored.loc[ring, "risk_level"].isin(HIGH_PLUS) & scored.loc[ring, "recommended_action"].isin(
        ["REVIEW", "VERIFY", "HOLD_RECOMMENDED"])
    assert hit.mean() >= 0.70, _table(df, scored, te)


def test_legit_unusual_flagged_for_review_but_never_hold(world):
    df, _, te, *_, scored = world
    lu = te[df.loc[te, "scenario"] == "legit_unusual"]
    assert len(lu) >= 3
    assert (scored.loc[lu, "recommended_action"] != "HOLD_RECOMMENDED").all()
    assert scored.loc[lu, "recommended_action"].isin(["MONITOR", "REVIEW"]).mean() >= 0.60, \
        scored.loc[lu, ["risk_score", "risk_level", "ml_prob", "behaviour", "anomaly"]]


def test_most_normal_rows_are_low_or_moderate(world):
    df, _, te, *_, scored = world
    normal = te[df.loc[te, "scenario"] == "normal"]
    assert (~scored.loc[normal, "risk_level"].isin(HIGH_PLUS)).mean() >= 0.90, _table(df, scored, te)


def test_scores_are_point_in_time(world):
    df, _, _, bundle, engine, norms, scored = world
    n = 1500
    head = score_frame(df.iloc[:n], bundle, engine, norms)
    pd.testing.assert_frame_equal(scored.iloc[:n], head, check_exact=False, rtol=1e-9, atol=1e-9)


def test_normalisers_fit_on_train_slice_only(world):
    df, tr, _, _, _, norms, _ = world
    expected = np.sort(build_features(tr)["txn_count_1h"].to_numpy())
    np.testing.assert_array_equal(norms["velocity"]._v, expected)
    assert len(norms["velocity"]._v) == len(tr) < len(df)
