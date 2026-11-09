"""Two businesses reusing the same account ids / external ids must never influence each other."""
import pandas as pd
import pytest

from sentinel.behaviour.engine import BehaviourEngine
from sentinel.features.engine import build_features
from sentinel.ingestion.synthetic import generate
from sentinel.models.split import chronological_split
from sentinel.models.train import train
from sentinel.pipeline import fit_normalisers, score_frame
from sentinel.risk.engine import DEFAULT_POLICY_PATH, RiskEngine, load_policy


def biz(seed, name, n_accounts, days):
    d = generate(seed=seed, n_accounts=n_accounts, days=days)
    d["business_id"] = name  # SAME account ids (ACC_00000...) and SAME external ids as the other
    return d


def test_features_ignore_other_businesses():
    a, b = biz(1, "A", 70, 8), biz(2, "B", 70, 8)
    both = pd.concat([a, b], ignore_index=True)
    mixed = build_features(both)[both["business_id"] == "B"].reset_index(drop=True)
    alone = build_features(b.reset_index(drop=True))
    pd.testing.assert_frame_equal(mixed, alone)


def test_behaviour_ignores_other_businesses():
    a, b = biz(1, "A", 70, 8), biz(2, "B", 70, 8)
    both = pd.concat([a, b], ignore_index=True)
    mixed = BehaviourEngine().replay(both)[both["business_id"] == "B"].reset_index(drop=True)
    alone = BehaviourEngine().replay(b.reset_index(drop=True))
    pd.testing.assert_frame_equal(mixed, alone)


def test_behaviour_contamination_is_scoped_to_business():
    a = biz(1, "A", 70, 8)
    b = a.copy()
    b["business_id"] = "B"  # identical ids and timestamps in both businesses
    both = pd.concat([a, b], ignore_index=True)
    ids = frozenset(("A", e) for e in a["external_id"].head(50))  # only business A's rows excluded
    out = BehaviourEngine().replay(both, contaminated_ids=ids)
    only_b = BehaviourEngine().replay(b.reset_index(drop=True))
    pd.testing.assert_frame_equal(out[both["business_id"] == "B"].reset_index(drop=True), only_b)


def test_pipeline_scores_ignore_other_businesses():
    a, b = biz(1, "A", 150, 20), biz(2, "B", 150, 20)
    bundle = train(b, seed=42)
    engine = RiskEngine(load_policy(DEFAULT_POLICY_PATH))
    norms = fit_normalisers(chronological_split(b)[0])
    alone = score_frame(b.reset_index(drop=True), bundle, engine, norms)
    both = pd.concat([a, b], ignore_index=True)
    mixed = score_frame(both, bundle, engine, norms)[both["business_id"] == "B"].reset_index(drop=True)
    pd.testing.assert_series_equal(mixed["risk_score"], alone["risk_score"], rtol=1e-9, atol=1e-9)
    assert mixed["risk_level"].tolist() == alone["risk_level"].tolist()
    assert mixed["risk_factors"].tolist() == alone["risk_factors"].tolist()
