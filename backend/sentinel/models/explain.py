"""SHAP explanations for the LightGBM model.

SHAP values describe how each feature moved THIS model's score away from its average; they
are not causes of fraud and say nothing about intent. For a binary LightGBM model the values
are in log-odds: base_value + sum(shap) == the model's raw margin (checked in the tests).
"""
import warnings

import numpy as np
import pandas as pd
import shap

NOTE = ("Contributions describe how each feature moved this model's score relative to its "
        "average prediction. They are not causes of fraud and are not proof of wrongdoing.")


def _shap_matrix(explainer, X: pd.DataFrame) -> np.ndarray:
    with warnings.catch_warnings():
        # shap warns that binary LightGBM now returns a list; handled just below
        warnings.filterwarnings("ignore", message="LightGBM binary classifier",
                                category=UserWarning)
        sv = explainer.shap_values(X)
    if isinstance(sv, list):  # one array per class
        sv = sv[1] if len(sv) > 1 else sv[0]
    sv = np.asarray(sv)
    return sv[..., 1] if sv.ndim == 3 else sv


def explain_transaction(bundle, features_row: pd.Series, top_k: int = 5) -> dict:
    cols = bundle.feature_columns
    X = features_row[cols].to_frame().T.astype(float)
    explainer = shap.TreeExplainer(bundle.lgbm)
    sv = _shap_matrix(explainer, X)[0]
    base = float(np.asarray(explainer.expected_value).ravel()[-1])
    order = np.argsort(-np.abs(sv), kind="stable")[:top_k]
    return {
        "base_value": base,
        "margin": float(bundle.lgbm.predict(X, raw_score=True)[0]),
        "contributions": [{"feature": cols[i], "value": float(X.iloc[0, i]), "shap": float(sv[i])}
                          for i in order],
        "note": NOTE,
    }


def global_importance(bundle, X: pd.DataFrame, max_rows: int = 2000) -> list[dict]:
    """Mean |SHAP| per feature over a (seeded) sample of at most `max_rows` rows."""
    cols = bundle.feature_columns
    sample = X[cols] if len(X) <= max_rows else X[cols].sample(max_rows, random_state=42)
    sv = _shap_matrix(shap.TreeExplainer(bundle.lgbm), sample.astype(float))
    imp = np.abs(sv).mean(axis=0)
    return [{"feature": cols[i], "mean_abs_shap": float(imp[i])}
            for i in np.argsort(-imp, kind="stable")]
