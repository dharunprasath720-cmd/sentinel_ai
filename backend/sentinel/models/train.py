"""Train LogReg, LightGBM and Isolation Forest on a chronological split.

Imbalance: class weights (LogReg), scale_pos_weight (LightGBM); no resampling.
Calibration: isotonic, fitted on the VALIDATION slice only. Review threshold: chosen on the
validation slice so about `review_budget_frac` of transactions are flagged for review.
Ranking metrics (PR-AUC, ROC-AUC) and thresholds use raw scores (calibration is monotone;
isotonic plateaus would only add ties). Calibrated probabilities are what `predict` returns.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from sentinel.features.engine import FEATURE_COLUMNS, build_features
from sentinel.models.evaluate import (choose_threshold, evaluate_scores, reliability_curve,
                                      select_calibrator)
from sentinel.models.split import chronological_split


@dataclass
class TrainedBundle:
    version: str
    feature_columns: list[str]
    lr: object
    lgbm: object
    iforest: object
    iso_sorted: np.ndarray
    calibrators: dict
    thresholds: dict
    metrics: dict
    split_info: dict
    calibrator_names: dict

    def _iso(self, X: pd.DataFrame) -> np.ndarray:
        raw = -self.iforest.score_samples(X)
        return np.searchsorted(self.iso_sorted, raw, side="right") / len(self.iso_sorted)

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        X = features[self.feature_columns]
        return pd.DataFrame({
            "lr_prob": self.calibrators["logreg"].predict(self.lr.predict_proba(X)[:, 1]),
            "lgbm_prob": self.calibrators["lightgbm"].predict(self.lgbm.predict_proba(X)[:, 1]),
            "anomaly_score": self._iso(X),
        }, index=features.index)

    def save(self, directory: Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, directory / "bundle.joblib")

    @classmethod
    def load(cls, directory: Path) -> "TrainedBundle":
        return joblib.load(Path(directory) / "bundle.joblib")


def _latency_ms(fn, X: pd.DataFrame, n: int = 30) -> float:
    """Median single-row inference latency in milliseconds."""
    times = []
    for i in range(min(n, len(X))):
        row = X.iloc[[i]]
        t0 = time.perf_counter()
        fn(row)
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def _split_summary(part: pd.DataFrame) -> dict:
    ts = pd.to_datetime(part["ts"], utc=True)
    return {"n": int(len(part)), "n_positive": int(part["label"].sum()),
            "positive_rate": float(part["label"].mean()),
            "start": ts.min().isoformat(), "end": ts.max().isoformat()}


def train(df: pd.DataFrame, seed: int = 42, review_budget_frac: float = 0.01,
          dataset: str = "synthetic") -> TrainedBundle:
    if df["label"].isna().any():
        raise ValueError("training requires a label on every row")
    feats = build_features(df)  # point-in-time, computed once on the full frame
    tr, va, te = chronological_split(df)
    Xtr, Xva, Xte = (feats.loc[p.index] for p in (tr, va, te))
    ytr, yva, yte = (p["label"].astype(int).to_numpy() for p in (tr, va, te))
    if len(np.unique(ytr)) < 2:
        raise ValueError("training split contains a single class; cannot fit supervised models")

    if yva.sum() == 0:
        raise ValueError("validation split contains no fraud rows; calibration and the review "
                         "threshold would be meaningless. Use more data or spread fraud over time.")

    lr = make_pipeline(StandardScaler(),
                       LogisticRegression(class_weight="balanced", max_iter=1000, random_state=seed))
    lr.fit(Xtr, ytr)
    pos = int(ytr.sum())
    lgbm = LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=31,
                          scale_pos_weight=(len(ytr) - pos) / pos, random_state=seed,
                          n_jobs=2, verbose=-1)
    lgbm.fit(Xtr, ytr)
    iforest = IsolationForest(n_estimators=100, random_state=seed, n_jobs=2).fit(Xtr)
    iso_sorted = np.sort(-iforest.score_samples(Xtr))

    bundle = TrainedBundle(
        version=f"{dataset}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}",
        feature_columns=list(FEATURE_COLUMNS), lr=lr, lgbm=lgbm, iforest=iforest,
        iso_sorted=iso_sorted, calibrators={}, thresholds={}, metrics={},
        split_info={"train": _split_summary(tr), "val": _split_summary(va),
                    "test": _split_summary(te)},
        calibrator_names={},
    )

    scored = {
        "logreg": (lr.predict_proba(Xva)[:, 1], lr.predict_proba(Xte)[:, 1],
                   lambda r: lr.predict_proba(r)),
        "lightgbm": (lgbm.predict_proba(Xva)[:, 1], lgbm.predict_proba(Xte)[:, 1],
                     lambda r: lgbm.predict_proba(r)),
        "iforest": (bundle._iso(Xva), bundle._iso(Xte), lambda r: bundle._iso(r)),
    }
    for name, (val_s, test_s, infer) in scored.items():
        thr = choose_threshold(yva, val_s, review_budget_frac)
        m = evaluate_scores(yte, test_s, thr)
        m["latency_ms"] = _latency_ms(infer, Xte)
        if name != "iforest":
            cal_name, cal = select_calibrator(val_s, yva, seed)
            bundle.calibrators[name] = cal
            bundle.calibrator_names[name] = cal_name
            m["calibrator"] = cal_name
            m["brier_raw"] = float(brier_score_loss(yte, test_s))
            m["brier_calibrated"] = float(brier_score_loss(yte, cal.predict(test_s)))
            m["reliability"] = reliability_curve(yte, cal.predict(test_s))
        bundle.thresholds[name] = thr
        bundle.metrics[name] = m
    return bundle
