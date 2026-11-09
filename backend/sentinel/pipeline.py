"""Chronological scoring pipeline: features -> models -> behaviour -> graph -> risk.

Everything a row sees is point-in-time (history strictly before its timestamp), so scoring a
prefix of a frame gives identical results for those rows.

Two passes, both point-in-time:
  pass 1  score every row with account/merchant history inputs at 0;
  pass 2  re-run behaviour with pass-1 HIGH+ rows excluded from the baselines (contamination
          guard) and add account/merchant history = the share of PRIOR transactions that
          pass 1 rated HIGH or CRITICAL.
Cluster flags are computed as-of each trigger row (>= 3 accounts on its device in the last
2h) from the preceding 24h only, so they never use later data.
"""
import numpy as np
import pandas as pd

from sentinel.behaviour.engine import BehaviourEngine
from sentinel.features.engine import build_features
from sentinel.graph.engine import find_clusters, window_indicators
from sentinel.risk.engine import Normaliser, RiskEngine, RiskInputs

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
HIGH_PLUS = {"HIGH", "CRITICAL"}
CLUSTER_LOOKBACK_SECS = 24 * 3600
CLUSTER_TRIGGER_ACCOUNTS = 3


def graph_signal(device_accounts, merchant_accounts, flagged):
    """Graph risk input in [0, 1] from point-in-time window counts (distinct accounts seen on the
    device / at the merchant in the last 2h, including this one) and the as-of cluster flag.
    Shared by the batch pipeline and the live scorer so the two cannot drift apart."""
    dev = np.clip((np.asarray(device_accounts) - 1) / 4.0, 0, 1) * 0.8
    mer = np.clip((np.asarray(merchant_accounts) - 2) / 6.0, 0, 1) * 0.5
    return np.where(flagged, 0.9, np.maximum(dev, mer))


def fit_normalisers(train_df: pd.DataFrame) -> dict[str, Normaliser]:
    """Fitted on the TRAIN slice only."""
    return {"velocity": Normaliser.fit(build_features(train_df)["txn_count_1h"])}


def _secs(ts) -> np.ndarray:
    return (pd.to_datetime(ts, utc=True) - EPOCH).dt.total_seconds().to_numpy()


def _cluster_flags(d: pd.DataFrame, win: pd.DataFrame) -> tuple[np.ndarray, list]:
    t = _secs(d["ts"])
    biz = d["business_id"].to_numpy() if "business_id" in d else np.full(len(d), "default")
    flagged = np.zeros(len(d), dtype=bool)
    cluster_id: list = [None] * len(d)
    for pos in np.flatnonzero(win["device_accounts_window"].to_numpy() >= CLUSTER_TRIGGER_ACCOUNTS):
        prior = (biz == biz[pos]) & (t < t[pos]) & (t >= t[pos] - CLUSTER_LOOKBACK_SECS)
        sel = np.flatnonzero(prior)
        hist = pd.concat([d.iloc[sel], d.iloc[[pos]]])
        for c in find_clusters(hist):
            if c.flagged and d["external_id"].iloc[pos] in set(c.txn_ids):
                flagged[pos], cluster_id[pos] = True, c.cluster_id
                break
    return flagged, cluster_id


def _prior_rate(d: pd.DataFrame, key_cols: list[str], bad: np.ndarray) -> np.ndarray:
    """Share of strictly-earlier rows with the same key that are `bad` (0 if none)."""
    t = _secs(d["ts"])
    out = np.zeros(len(d))
    keys = d[key_cols].copy()
    for _, g in keys.dropna().groupby(key_cols, sort=False):
        idx = g.index.to_numpy()
        idx = idx[np.argsort(t[idx], kind="mergesort")]
        tg = t[idx]
        cum = np.concatenate([[0.0], np.cumsum(bad[idx])])
        left = np.searchsorted(tg, tg, side="left")
        out[idx] = np.where(left > 0, cum[left] / np.maximum(left, 1), 0.0)
    return out


def _assess_all(engine, ml, anomaly, behaviour, graph, velocity, acct_hist, merch_hist, flagged):
    rows = []
    for i in range(len(ml)):
        a = engine.assess(RiskInputs(
            ml_prob=float(ml[i]), anomaly=float(anomaly[i]), behaviour=float(behaviour[i]),
            graph=float(graph[i]), velocity=float(velocity[i]), account_history=float(acct_hist[i]),
            merchant_risk=float(merch_hist[i]), cluster_flagged=bool(flagged[i])))
        rows.append((a.risk_score, a.risk_level, a.recommended_action,
                     a.calibrated_fraud_probability, a.risk_factors, a.policy_version))
    return pd.DataFrame(rows, columns=["risk_score", "risk_level", "recommended_action",
                                       "calibrated_fraud_probability", "risk_factors",
                                       "policy_version"])


def score_frame(df: pd.DataFrame, bundle, engine: RiskEngine,
                normalisers: dict[str, Normaliser]) -> pd.DataFrame:
    d = df.reset_index(drop=True)
    feats = build_features(d)
    preds = bundle.predict(feats)
    win = window_indicators(d)
    flagged, cluster_id = _cluster_flags(d, win)

    graph = graph_signal(win["device_accounts_window"].to_numpy(),
                         win["merchant_accounts_window"].to_numpy(), flagged)
    velocity = np.array([normalisers["velocity"].transform(v, strict=True)
                         for v in feats["txn_count_1h"]])
    ml, anomaly = preds["lgbm_prob"].to_numpy(), preds["anomaly_score"].to_numpy()
    zeros = np.zeros(len(d))

    beh1 = BehaviourEngine().replay(d)["deviation_score"].to_numpy()
    pass1 = _assess_all(engine, ml, anomaly, beh1, graph, velocity, zeros, zeros, flagged)
    high1 = pass1["risk_level"].isin(HIGH_PLUS).to_numpy()

    biz_vals = (d["business_id"].to_numpy() if "business_id" in d
                else np.full(len(d), None, dtype=object))
    contaminated = frozenset(zip(biz_vals[high1], d.loc[high1, "external_id"]))  # (business, id)
    beh2 = BehaviourEngine().replay(d, contaminated_ids=contaminated)["deviation_score"].to_numpy()
    bad = high1.astype(float)
    biz_col = ["business_id"] if "business_id" in d else []
    acct_hist = _prior_rate(d, biz_col + ["account_id"], bad)
    merch_hist = _prior_rate(d, biz_col + ["merchant_id"], bad)
    final = _assess_all(engine, ml, anomaly, beh2, graph, velocity, acct_hist, merch_hist, flagged)

    inputs = pd.DataFrame({"ml_prob": ml, "anomaly": anomaly, "behaviour": beh2, "graph": graph,
                           "velocity": velocity, "account_history": acct_hist,
                           "merchant_risk": merch_hist, "cluster_flagged": flagged,
                           "cluster_id": pd.array(cluster_id, dtype="string")})
    out = pd.concat([final, inputs], axis=1)
    out.index = df.index
    return out
