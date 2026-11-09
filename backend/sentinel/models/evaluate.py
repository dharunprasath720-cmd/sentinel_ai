"""Fraud-appropriate evaluation. No accuracy. Undefined metrics are None and listed."""
import math

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score


def _ratio(num: float, den: float) -> float | None:
    return num / den if den > 0 else None


def evaluate_scores(y_true, scores, threshold: float) -> dict:
    """Metrics at `threshold`. Called with the review threshold, so `precision_at_review`
    equals `precision`; it is kept as a separate key because it is the operational number."""
    y = np.asarray(y_true).astype(int)
    s = np.asarray(scores, dtype=float)
    pred = (s >= threshold).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    n_pos, n_neg = tp + fn, tn + fp

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, n_pos)
    f1 = None
    if n_pos > 0:
        f1 = 0.0 if not precision and not recall else 2 * (precision or 0) * recall / ((precision or 0) + recall)
    two_class = n_pos > 0 and n_neg > 0
    m = {
        "precision": precision, "recall": recall, "f1": f1,
        "pr_auc": float(average_precision_score(y, s)) if n_pos > 0 else None,
        "roc_auc": float(roc_auc_score(y, s)) if two_class else None,
        "fpr": _ratio(fp, n_neg), "fnr": _ratio(fn, n_pos),
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "precision_at_review": precision,
        "n_flagged": tp + fp, "n_positive": n_pos, "threshold": float(threshold),
    }
    m["undefined"] = [k for k in ("precision", "recall", "f1", "pr_auc", "roc_auc", "fpr", "fnr")
                      if m[k] is None]
    return m


def choose_threshold(y_val, scores, review_budget_frac: float = 0.01) -> float:
    """Score of the k-th highest validation row, k = ceil(budget * n): flagging `>= threshold`
    sends about `review_budget_frac` of transactions to analysts."""
    s = np.sort(np.asarray(scores, dtype=float))[::-1]
    k = max(1, math.ceil(review_budget_frac * len(s)))
    return float(s[k - 1])


def fit_calibrator(val_scores, y_val) -> IsotonicRegression:
    """Isotonic calibration fitted on the validation slice only."""
    cal = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    cal.fit(np.asarray(val_scores, dtype=float), np.asarray(y_val).astype(int))
    return cal
