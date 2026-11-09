import numpy as np
import pytest

import sentinel.models.explain as explain_mod
from sentinel.features.engine import FEATURE_COLUMNS, build_features
from sentinel.ingestion.synthetic import generate
from sentinel.models.explain import explain_transaction, global_importance
from sentinel.models.train import train


@pytest.fixture(scope="module")
def setup():
    df = generate(seed=42, n_accounts=200, days=20)
    return train(df, seed=42), build_features(df)


def test_additivity_base_plus_contributions_equals_model_margin(setup):
    bundle, X = setup
    for pos in (50, 800, 2000):
        row = X.iloc[pos]
        out = explain_transaction(bundle, row, top_k=len(FEATURE_COLUMNS))
        margin = float(bundle.lgbm.predict(row.to_frame().T[FEATURE_COLUMNS], raw_score=True)[0])
        assert abs(out["base_value"] + sum(c["shap"] for c in out["contributions"]) - margin) < 1e-4
        assert abs(out["margin"] - margin) < 1e-6


def test_contributions_sorted_by_magnitude_and_top_k(setup):
    bundle, X = setup
    out = explain_transaction(bundle, X.iloc[100])
    assert len(out["contributions"]) == 5
    mags = [abs(c["shap"]) for c in out["contributions"]]
    assert mags == sorted(mags, reverse=True)
    assert {"feature", "value", "shap"} <= set(out["contributions"][0])
    assert out["contributions"][0]["feature"] in FEATURE_COLUMNS


def test_note_says_contributions_are_not_causes(setup):
    bundle, X = setup
    note = explain_transaction(bundle, X.iloc[0])["note"].lower()
    assert "not" in note and "cause" in note


def test_global_importance_ranked_and_row_capped(setup, monkeypatch):
    bundle, X = setup
    seen = []
    real = explain_mod.shap.TreeExplainer

    class Spy:
        def __init__(self, model, *a, **k):
            self._e = real(model, *a, **k)
            self.expected_value = self._e.expected_value

        def shap_values(self, data, *a, **k):
            seen.append(len(data))
            return self._e.shap_values(data, *a, **k)

    monkeypatch.setattr(explain_mod.shap, "TreeExplainer", Spy)
    imp = global_importance(bundle, X, max_rows=300)
    assert seen == [300]  # sampled, never the full frame
    assert [i["feature"] for i in imp] != [] and len(imp) == len(FEATURE_COLUMNS)
    vals = [i["mean_abs_shap"] for i in imp]
    assert vals == sorted(vals, reverse=True) and all(v >= 0 for v in vals)
