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


def test_calibrator_monotonic_and_bounded():
    rng = np.random.default_rng(1)
    s = rng.random(500)
    y = (rng.random(500) < s * 0.3).astype(int)
    cal = fit_calibrator(s, y)
    out = cal.predict(np.linspace(0, 1, 101))
    assert (np.diff(out) >= -1e-12).all()
    assert out.min() >= 0 and out.max() <= 1
