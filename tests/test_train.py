import json

import numpy as np
import pandas as pd
import pytest

import sentinel.models.train as train_mod
from sentinel.features.engine import build_features
from sentinel.ingestion.synthetic import generate
from sentinel.models.run import main as run_main
from sentinel.models.split import chronological_split
from sentinel.models.train import TrainedBundle, train

MODELS = {"logreg", "lightgbm", "iforest"}
REQUIRED = {"precision", "recall", "f1", "pr_auc", "roc_auc", "fpr", "fnr",
            "confusion_matrix", "precision_at_review", "latency_ms"}


@pytest.fixture(scope="module")
def df():
    return generate(seed=42, n_accounts=200, days=20)


@pytest.fixture(scope="module")
def bundle(df):
    return train(df, seed=42)


def test_train_runs_and_reports_all_models(bundle):
    assert set(bundle.metrics) == MODELS
    for name, m in bundle.metrics.items():
        assert REQUIRED <= set(m), name
        assert "accuracy" not in m


def test_calibrator_fit_only_on_val(df, monkeypatch):
    calls = []
    real = train_mod.select_calibrator

    def spy(val_scores, y_val, *args, **kwargs):
        calls.append(len(val_scores))
        return real(val_scores, y_val, *args, **kwargs)

    monkeypatch.setattr(train_mod, "select_calibrator", spy)
    train(df, seed=42)
    n_val = len(chronological_split(df)[1])
    assert calls == [n_val, n_val]  # logreg + lightgbm, validation slice only


def test_predict_columns_and_ranges(bundle, df):
    out = bundle.predict(build_features(df).head(200))
    assert list(out.columns) == ["lr_prob", "lgbm_prob", "anomaly_score"]
    assert out.notna().all().all()
    assert ((out >= 0) & (out <= 1)).all().all()


def test_save_load_roundtrip_predicts_identically(bundle, df, tmp_path):
    bundle.save(tmp_path)
    loaded = TrainedBundle.load(tmp_path)
    feats = build_features(df).head(300)
    pd.testing.assert_frame_equal(bundle.predict(feats), loaded.predict(feats))
    assert loaded.version == bundle.version


def test_lgbm_beats_random_pr_auc(bundle):
    base_rate = bundle.split_info["test"]["positive_rate"]
    assert bundle.metrics["lightgbm"]["pr_auc"] > base_rate


def test_bundle_records_calibrator_choice(bundle):
    assert set(bundle.calibrator_names) == {"logreg", "lightgbm"}
    assert set(bundle.calibrator_names.values()) <= {"raw", "platt", "isotonic"}
    for m in (bundle.metrics["logreg"], bundle.metrics["lightgbm"]):
        assert sum(b["n"] for b in m["reliability"]) == bundle.split_info["test"]["n"]


def test_validation_without_positives_raises_clear_error(df):
    d = df.copy()
    val_idx = chronological_split(d)[1].index
    d.loc[val_idx, "label"] = 0
    with pytest.raises(ValueError, match="validation"):
        train(d, seed=42)


def test_split_info_records_chronology(bundle):
    info = bundle.split_info
    assert info["train"]["end"] <= info["val"]["start"] <= info["val"]["end"] <= info["test"]["start"]


def test_cli_writes_report(tmp_path):
    code = run_main(["--dataset", "synthetic", "--accounts", "150", "--days", "20",
                     "--out", str(tmp_path)])
    assert code == 0
    run_dir = next(tmp_path.iterdir())
    assert (run_dir / "bundle.joblib").exists()
    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert set(metrics["models"]) == MODELS
    report = (run_dir / "report.md").read_text()
    assert "lightgbm" in report and "accuracy" not in report.lower()
    assert "flag rate" in report.lower()  # realised rate shown next to the stated budget
    assert "Reliability" in report


def test_cli_paysim_missing_file_is_clean_error(tmp_path):
    code = run_main(["--dataset", "paysim", "--paysim-path", str(tmp_path / "nope.csv"),
                     "--out", str(tmp_path)])
    assert code == 2
