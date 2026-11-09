import numpy as np
import pytest

from sentinel.risk.engine import (DEFAULT_POLICY_PATH, Normaliser, Policy, RiskEngine,
                                  RiskInputs, calibrate_thresholds, load_policy, threshold_report)

W = dict(ml_prob=0.35, anomaly=0.10, behaviour=0.15, graph=0.20, velocity=0.10,
         account_history=0.05, merchant_risk=0.05)


def policy(thresholds=(0.2, 0.4, 0.65), cap="HIGH", hold_requires_cluster=True):
    return Policy(version="test", weights=dict(W),
                  thresholds=dict(zip(("moderate", "high", "critical"), thresholds)),
                  single_source_cap=cap, hold_requires_cluster=hold_requires_cluster,
                  strong_source_min=0.5)


def inp(**kw):
    base = dict(ml_prob=0.0, anomaly=0.0, behaviour=0.0, graph=0.0, velocity=0.0,
                account_history=0.0, merchant_risk=0.0, cluster_flagged=False)
    base.update(kw)
    return RiskInputs(**base)


def test_deterministic():
    e = RiskEngine(policy())
    x = inp(ml_prob=0.7, graph=0.4, behaviour=0.9)
    assert e.assess(x) == e.assess(x)


def test_weights_applied_exactly():
    r = RiskEngine(policy()).assess(inp(ml_prob=0.8, anomaly=0.5, behaviour=0.2, graph=0.6,
                                        velocity=0.1, account_history=0.0, merchant_risk=0.4))
    assert r.risk_score == pytest.approx(0.51)
    assert r.contributions["ml_prob"] == pytest.approx(0.28)
    assert r.risk_level == "HIGH" and r.recommended_action == "REVIEW"
    assert r.calibrated_fraud_probability == 0.8  # only the ML probability is a probability


@pytest.mark.parametrize("ml,level,action", [
    (0.1, "LOW", "ALLOW"), (0.4, "MODERATE", "MONITOR"),
    (0.6, "HIGH", "REVIEW"), (0.9, "CRITICAL", "VERIFY")])
def test_levels_follow_thresholds(ml, level, action):
    r = RiskEngine(policy((0.1, 0.2, 0.3))).assess(inp(ml_prob=ml))
    assert (r.risk_level, r.recommended_action) == (level, action)


def test_anomaly_only_signals_capped_at_high_and_never_hold():
    r = RiskEngine(policy((0.05, 0.1, 0.2))).assess(
        inp(anomaly=1.0, behaviour=1.0, velocity=1.0, cluster_flagged=True))
    assert r.risk_score == pytest.approx(0.35)  # would be CRITICAL uncapped
    assert r.risk_level == "HIGH" and r.recommended_action == "REVIEW"


def test_hold_requires_flagged_cluster():
    e = RiskEngine(policy())
    everything = dict(ml_prob=1, anomaly=1, behaviour=1, graph=1, velocity=1,
                      account_history=1, merchant_risk=1)
    assert e.assess(inp(**everything)).recommended_action == "VERIFY"
    r = e.assess(inp(**everything, cluster_flagged=True))
    assert (r.risk_level, r.recommended_action) == ("CRITICAL", "HOLD_RECOMMENDED")


def test_factors_name_the_drivers():
    r = RiskEngine(policy()).assess(inp(behaviour=1.0))
    assert any("Behavioural deviation" in f for f in r.risk_factors)
    assert RiskEngine(policy()).assess(inp(ml_prob=1.0)).risk_factors[0].startswith("High model")


def test_all_zero_inputs_is_low_allow():
    r = RiskEngine(policy()).assess(inp())
    assert (r.risk_level, r.recommended_action, r.risk_factors) == ("LOW", "ALLOW", [])


def test_inputs_out_of_range_rejected():
    with pytest.raises(ValueError):
        inp(ml_prob=1.2)
    with pytest.raises(ValueError):
        inp(graph=-0.1)


def test_default_policy_file_loads_and_is_consistent():
    p = load_policy(DEFAULT_POLICY_PATH)
    assert sum(p.weights.values()) == pytest.approx(1.0)
    assert p.thresholds["moderate"] < p.thresholds["high"] < p.thresholds["critical"] < 1


YAML_OK = """version: t
weights: {ml_prob: 0.35, anomaly: 0.10, behaviour: 0.15, graph: 0.20, velocity: 0.10, account_history: 0.05, merchant_risk: 0.05}
thresholds: {moderate: 0.2, high: 0.4, critical: 0.65}
single_source_cap: HIGH
hold_requires_cluster: true
strong_source_min: 0.5
"""


@pytest.mark.parametrize("old,new", [
    ("merchant_risk: 0.05", "merchant_risk_x: 0.05"),                 # missing weight key
    ("merchant_risk: 0.05", "merchant_risk: 0.0"),                    # weights sum to 0.95
    ("{moderate: 0.2, high: 0.4, critical: 0.65}", "{moderate: 0.5, high: 0.4, critical: 0.9}"),  # not increasing
    ("critical: 0.65", "critical: 1.0"),                              # threshold not < 1
    ("single_source_cap: HIGH", "single_source_cap: SEVERE"),         # unknown level
    ("anomaly: 0.10", "anomaly: .nan"),                               # NaN weight must not load
    ("anomaly: 0.10", "anomaly: .inf"),
    ("anomaly: 0.10", 'anomaly: "0.10"'),                             # string weight
    ("anomaly: 0.10", "anomaly: true"),                               # bool is not a number
    ("moderate: 0.2,", "moderate: .nan,"),
    ("strong_source_min: 0.5", "strong_source_min: .nan"),            # would disable the cap
    ("strong_source_min: 0.5", "strong_source_min: -1"),
    ("strong_source_min: 0.5", "strong_source_min: 0"),
    ("strong_source_min: 0.5", "strong_source_min: 1.5"),
    ("hold_requires_cluster: true", 'hold_requires_cluster: "false"'),  # truthy string
])
def test_bad_policy_fails_loudly(tmp_path, old, new):
    p = tmp_path / "p.yaml"
    p.write_text(YAML_OK.replace(old, new))
    with pytest.raises(ValueError):
        load_policy(p)


def test_good_policy_yaml_loads(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(YAML_OK)
    assert load_policy(p).version == "t"


def test_normaliser_percentile_and_bounds():
    n = Normaliser.fit([1, 2, 3, 4])
    assert n.transform(2) == 0.5 and n.transform(10) == 1.0 and n.transform(0) == 0.0
    with pytest.raises(ValueError):
        Normaliser.fit([])


def test_normaliser_strict_mode_does_not_inflate_common_values():
    # 90% of training rows have value 0 (typical): "<=" would map 0 to 0.9, strict maps it to 0
    n = Normaliser.fit([0] * 90 + [1] * 5 + [4] * 5)
    assert n.transform(0) == 0.9
    assert n.transform(0, strict=True) == 0.0
    assert n.transform(4, strict=True) == 0.95


def test_calibrate_thresholds_follow_review_budget():
    scores = np.random.default_rng(0).random(2000)
    t = calibrate_thresholds(scores, review_budget_frac=0.05)
    assert t["moderate"] < t["high"] < t["critical"] < 1
    assert (scores >= t["high"]).mean() == pytest.approx(0.05, abs=0.003)
    assert (scores >= t["critical"]).mean() == pytest.approx(0.0125, abs=0.003)


def test_threshold_report_counts_and_precision():
    scores = np.array([0.9, 0.8, 0.5, 0.3, 0.1, 0.05])
    labels = np.array([1, 0, 1, 0, 0, 0])
    rep = threshold_report(scores, labels, {"moderate": 0.2, "high": 0.45, "critical": 0.85})
    assert rep["high"] == {"n": 3, "rate": 0.5, "precision": pytest.approx(2 / 3), "recall": 1.0}
    assert rep["critical"]["n"] == 1 and rep["critical"]["precision"] == 1.0
