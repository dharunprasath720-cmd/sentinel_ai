"""Point-in-time feature engine, shared by training, batch scoring and live scoring.

Every history-based feature uses only transactions with a timestamp STRICTLY earlier than
the current row (rows with an identical timestamp never count each other), so the value of
a row's features never depends on later data. Columns `label` and `scenario` are never read.

Conventions for missing history / identifiers:
  * no prior transaction: counts 0, mean 0, std 0, z 0, failed rate 0,
    secs_since_prev = GAP_CAP_SECS (gaps are also capped at 30 days)
  * missing device/instrument/merchant id: the related count is 0
  * std is the population standard deviation of prior amounts
"""
import numpy as np
import pandas as pd

GAP_CAP_SECS = 30 * 86400
TYPE_CODES = {"PAYMENT": 0, "TRANSFER": 1, "CASH_OUT": 2, "DEBIT": 3, "CASH_IN": 4}
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")

FEATURE_COLUMNS = [
    "amount", "log_amount", "hour", "day_of_week", "is_failed", "type_code",
    "txn_count_5m", "txn_count_1h", "txn_count_24h",
    "acct_mean_amount", "acct_std_amount", "amount_z", "secs_since_prev", "acct_failed_rate",
    "device_account_count", "acct_instrument_count", "merchant_account_count",
    "repeat_counterparty_count",
]


def _distinct_before(s: pd.DataFrame, key: str, val: str) -> np.ndarray:
    """For each row: distinct `val`s seen under `key` strictly before its timestamp,
    plus the row's own `val`. Rows with a missing key or val get 0."""
    out = np.zeros(len(s), dtype=np.int64)
    ts = s["_t"].to_numpy()
    sub = s[[key, val]].dropna()
    for _, g in sub.groupby(key, sort=False):
        idx = g.index.to_numpy()
        vals = g[val].to_numpy()
        seen: set = set()
        i = 0
        while i < len(idx):
            j = i
            while j < len(idx) and ts[idx[j]] == ts[idx[i]]:
                j += 1
            for k in range(i, j):
                out[idx[k]] = len(seen) + (vals[k] not in seen)
            seen.update(vals[i:j])
            i = j
    return out


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.reset_index(drop=True)
    ts_utc = pd.to_datetime(d["ts"], utc=True)
    t_all = (ts_utc - EPOCH).dt.total_seconds().to_numpy()
    order = np.lexsort((d["external_id"].to_numpy(), t_all))
    s = d.iloc[order].reset_index(drop=True)
    s["_t"] = t_all[order]
    ts_s = ts_utc.iloc[order].reset_index(drop=True)
    n = len(s)

    amount = s["amount"].to_numpy(dtype=float)
    failed = (s["status"] == "failed").to_numpy(dtype=float)
    t = s["_t"].to_numpy()

    f = {c: np.zeros(n) for c in FEATURE_COLUMNS}
    f["amount"] = amount
    f["log_amount"] = np.log1p(amount)
    f["hour"] = ts_s.dt.hour.to_numpy(dtype=float)
    f["day_of_week"] = ts_s.dt.day_of_week.to_numpy(dtype=float)
    f["is_failed"] = failed
    f["type_code"] = s["type"].map(TYPE_CODES).fillna(-1).to_numpy(dtype=float)
    f["secs_since_prev"][:] = GAP_CAP_SECS

    for _, idx in s.groupby("account_id", sort=False).indices.items():
        ta = t[idx]
        left = np.searchsorted(ta, ta, side="left")  # rows strictly earlier
        for name, w in (("txn_count_5m", 300), ("txn_count_1h", 3600), ("txn_count_24h", 86400)):
            f[name][idx] = left - np.searchsorted(ta, ta - w, side="left")
        cs = np.concatenate([[0.0], np.cumsum(amount[idx])])
        cs2 = np.concatenate([[0.0], np.cumsum(amount[idx] ** 2)])
        cf = np.concatenate([[0.0], np.cumsum(failed[idx])])
        has = left > 0
        cnt = np.where(has, left, 1)
        mean = np.where(has, cs[left] / cnt, 0.0)
        var = np.where(has, np.maximum(cs2[left] / cnt - mean ** 2, 0.0), 0.0)
        std = np.sqrt(var)
        f["acct_mean_amount"][idx] = mean
        f["acct_std_amount"][idx] = std
        f["amount_z"][idx] = np.where(std > 0, (amount[idx] - mean) / np.where(std > 0, std, 1), 0.0)
        f["acct_failed_rate"][idx] = np.where(has, cf[left] / cnt, 0.0)
        prev = np.where(has, ta[np.maximum(left - 1, 0)], 0.0)
        f["secs_since_prev"][idx] = np.where(has, np.minimum(ta - prev, GAP_CAP_SECS), GAP_CAP_SECS)

    pairs = s.dropna(subset=["merchant_id"]).groupby(["account_id", "merchant_id"], sort=False).indices
    pair_pos = s.dropna(subset=["merchant_id"]).index.to_numpy()
    for _, loc in pairs.items():
        idx = pair_pos[loc]
        tp = t[idx]
        f["repeat_counterparty_count"][idx] = np.searchsorted(tp, tp, side="left")

    f["device_account_count"] = _distinct_before(s, "device_id", "account_id")
    f["acct_instrument_count"] = _distinct_before(s, "account_id", "instrument_id")
    f["merchant_account_count"] = _distinct_before(s, "merchant_id", "account_id")

    feats = pd.DataFrame(f)[FEATURE_COLUMNS]
    inv = np.empty_like(order)
    inv[order] = np.arange(n)
    out = feats.iloc[inv].reset_index(drop=True)
    out.index = df.index
    return out
