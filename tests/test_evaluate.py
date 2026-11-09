import numpy as np
import pytest

from sentinel.models.evaluate import choose_threshold, evaluate_scores, fit_calibrator

Y = np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
S = np.array([0.9, 0.8, 0.3, 0.7, 0.2, 0.1, 0.1, 0.05, 0.04, 0.01])


def test_metrics_hand_computed():
    m = evaluate_scores(Y, S, threshold=0.5)
    assert m["confusion_matrix"] == [[6, 1], [1, 2]]
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["f1"] == pytest.approx(2 / 3)
    assert m["fpr"] == pytest.approx(1 / 7)
    assert m["fnr"] == pytest.approx(1 / 3)
    assert m["precision_at_review"] == pytest.approx(2 / 3)
    assert m["roc_auc"] == pytest.approx(20 / 21)
    assert m["pr_auc"] == pytest.approx((1 + 1 + 0.75) / 3)
    assert m["n_positive"] == 3 and m["undefined"] == []
    assert m["flag_rate"] == pytest.approx(0.3)  # 3 of 10 rows flagged


def test_no_accuracy_key():
    assert "accuracy" not in evaluate_scores(Y, S, 0.5)


def test_no_positives_does_not_crash():
    m = evaluate_scores(np.zeros(10, dtype=int), S, threshold=0.5)
    assert m["n_positive"] == 0
    for k in ("recall", "pr_auc", "roc_auc", "f1", "fnr"):
        assert m[k] is None and k in m["undefined"]
    assert m["fpr"] == pytest.approx(3 / 10)  # scores 0.9, 0.8, 0.7 are >= 0.5


def test_no_negatives_does_not_crash():
    m = evaluate_scores(np.ones(10, dtype=int), S, threshold=0.5)
    assert m["fpr"] is None and "fpr" in m["undefined"]
    assert m["roc_auc"] is None


def test_choose_threshold_flags_budget_fraction():
    rng = np.random.default_rng(0)
    scores = rng.random(1000)
    y = (rng.random(1000) < 0.05).astype(int)
    thr = choose_threshold(y, scores, review_budget_frac=0.05)
    assert int((scores >= thr).sum()) == 50


def _brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def test_select_calibrator_fixes_miscalibrated_scores():
    from sentinel.models.evaluate import select_calibrator
    rng = np.random.default_rng(0)

    def sample(n):
        q = rng.uniform(0, 0.4, n)
        return q ** 0.4, (rng.random(n) < q).astype(int)  # scores inflated vs truth

    s, y = sample(5000)
    name, cal = select_calibrator(s, y)
    assert name != "raw"
    s2, y2 = sample(20000)
    assert _brier(y2, cal.predict(s2)) < _brier(y2, s2)


def test_select_calibrator_keeps_quality_when_already_calibrated():
    from sentinel.models.evaluate import select_calibrator
    rng = np.random.default_rng(1)
    q = rng.random(20000)
    y = (rng.random(20000) < q).astype(int)
    _, cal = select_calibrator(q, y)
    q2 = rng.random(20000)
    y2 = (rng.random(20000) < q2).astype(int)
    assert abs(_brier(y2, cal.predict(q2)) - _brier(y2, q2)) / _brier(y2, q2) < 0.01


def test_select_calibrator_degenerate_validation_falls_back_to_raw():
    from sentinel.models.evaluate import select_calibrator
    name, cal = select_calibrator(np.linspace(0, 1, 50), np.zeros(50, dtype=int))
    assert name == "raw"
    assert ((cal.predict(np.array([0.2, 0.9])) >= 0) & (cal.predict(np.array([0.2, 0.9])) <= 1)).all()


def test_reliability_curve_counts_and_omits_empty_bins():
    from sentinel.models.evaluate import reliability_curve
    p = np.array([0.05, 0.05, 0.95, 0.95, 0.95])
    y = np.array([0, 1, 1, 1, 0])
    curve = reliability_curve(y, p, bins=10)
    assert sum(b["n"] for b in curve) == 5
    assert len(curve) == 2  # only two non-empty bins
    low, high = curve
    assert low["mean_predicted"] == pytest.approx(0.05) and low["observed_rate"] == pytest.approx(0.5)
    assert high["observed_rate"] == pytest.approx(2 / 3)


def test_calibrator_monotonic_and_bounded():
    rng = np.random.default_rng(1)
    s = rng.random(500)
    y = (rng.random(500) < s * 0.3).astype(int)
    cal = fit_calibrator(s, y)
    out = cal.predict(np.linspace(0, 1, 101))
    assert (np.diff(out) >= -1e-12).all()
    assert out.min() >= 0 and out.max() <= 1
