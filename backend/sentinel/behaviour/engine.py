"""Per-account behavioural baselines and interpretable deviation indicators.

Design rules
  * Point-in-time: a transaction is scored BEFORE it updates its baseline, and rows sharing
    a timestamp never count each other (replay scores a whole tie group, then updates).
  * Robust baseline: median/MAD over the last `window` non-contaminated amounts. MAD is
    floored at 5% of the median (and 1e-9) so identical histories cannot divide by zero.
  * Neutral without history: until `min_history` clean transactions exist, the amount,
    merchant and hour indicators and the deviation score are 0 and there are no reasons.
  * Contamination guard: `update(..., contaminated=True)` (used for rows already scored
    HIGH or above) records velocity facts but never moves the baseline.
  * A deviation is an indicator, not a verdict: no single signal can reach a score of 1.0.
"""
from collections import deque
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
BURST_SECS = 600
DECAY = 0.98          # per clean transaction decay of the hour-of-day histogram
OFF_HOURS_P = 0.02    # an hour holding < 2% of the account's activity is "unusual"
SINGLE_CAP = 0.8      # ceiling for any one signal


@dataclass
class BehaviourIndicators:
    amount_robust_z: float = 0.0
    burst_count_10m: int = 0
    new_merchant: bool = False
    off_hours: bool = False
    failed_streak: int = 0
    n_history: int = 0
    deviation_score: float = 0.0
    reasons: list[str] = field(default_factory=list)


class _State:
    def __init__(self, window: int):
        self.amounts: deque = deque(maxlen=window)
        self.hours = np.zeros(24)
        self.merchants: set = set()
        self.recent: deque = deque()          # timestamps (all txns) within BURST_SECS
        self.fail_streak = 0
        self.n_history = 0                    # clean updates
        self.total = 0
        self.failed = 0
        self.last_clean_ts = None
        self.interarrival = None              # exponentially weighted mean, seconds


class BehaviourEngine:
    def __init__(self, window: int = 50, min_history: int = 5):
        self.window = window
        self.min_history = min_history
        self._state: dict[str, _State] = {}

    # ------------------------------------------------------------------ scoring
    def indicators(self, txn: dict) -> BehaviourIndicators:
        st = self._state.get(txn["account_id"]) or _State(self.window)
        ts, amount = txn["ts"], float(txn["amount"])
        burst = sum(1 for t in st.recent if 0 < (ts - t).total_seconds() <= BURST_SECS)
        streak = st.fail_streak + 1 if txn.get("status") == "failed" else 0
        ind = BehaviourIndicators(burst_count_10m=burst, failed_streak=streak,
                                  n_history=st.n_history)
        if st.n_history < self.min_history:
            return ind

        a = np.fromiter(st.amounts, dtype=float)
        med = float(np.median(a))
        mad = float(np.median(np.abs(a - med)))
        z = 0.6745 * (amount - med) / max(mad, 0.05 * med, 1e-9)
        merchant = txn.get("merchant_id")
        total_h = st.hours.sum()
        hour = ts.hour
        ind.amount_robust_z = float(z)
        ind.new_merchant = merchant is not None and merchant not in st.merchants
        ind.off_hours = total_h > 0 and st.hours[hour] / total_h < OFF_HOURS_P

        parts, reasons = [], []
        if z >= 3.5:
            parts.append(SINGLE_CAP * min(1.0, (z - 2.0) / 8.0))
            reasons.append(f"Amount {amount:.2f} is {z:.1f} robust deviations above this "
                           f"account's typical {med:.2f}")
        if burst >= 3:
            parts.append(SINGLE_CAP * min(1.0, (burst - 2) / 4.0))
            reasons.append(f"{burst} other payments in the last 10 minutes")
        if ind.new_merchant:
            parts.append(0.4)
            reasons.append("First payment to this merchant from this account")
        if ind.off_hours:
            parts.append(0.4)
            reasons.append(f"Outside the account's usual activity hours (hour {hour:02d} UTC)")
        if streak >= 3:
            parts.append(SINGLE_CAP * min(1.0, (streak - 1) / 4.0))
            reasons.append(f"{streak} consecutive failed payments")
        if parts:
            active = sum(1 for p in parts if p >= 0.3)
            ind.deviation_score = float(min(1.0, max(parts) + 0.1 * max(0, active - 1)))
        ind.reasons = reasons
        return ind

    # ------------------------------------------------------------------ learning
    def update(self, txn: dict, contaminated: bool = False) -> None:
        st = self._state.setdefault(txn["account_id"], _State(self.window))
        ts = txn["ts"]
        while st.recent and (ts - st.recent[0]).total_seconds() > BURST_SECS:
            st.recent.popleft()
        st.recent.append(ts)
        st.total += 1
        if txn.get("status") == "failed":
            st.failed += 1
            st.fail_streak += 1
        else:
            st.fail_streak = 0
        if contaminated:
            return
        st.amounts.append(float(txn["amount"]))
        st.hours *= DECAY
        st.hours[ts.hour] += 1.0
        if txn.get("merchant_id") is not None:
            st.merchants.add(txn["merchant_id"])
        if st.last_clean_ts is not None:
            gap = (ts - st.last_clean_ts).total_seconds()
            st.interarrival = gap if st.interarrival is None else 0.8 * st.interarrival + 0.2 * gap
        st.last_clean_ts = ts
        st.n_history += 1

    def profile(self, account_id: str) -> dict:
        st = self._state.get(account_id)
        if st is None or not st.amounts:
            return {"n_history": 0, "median_amount": None, "mad_amount": None,
                    "typical_hours": [], "mean_interarrival_secs": None,
                    "known_merchants": [], "failure_rate": 0.0}
        a = np.fromiter(st.amounts, dtype=float)
        med = float(np.median(a))
        return {"n_history": st.n_history, "median_amount": med,
                "mad_amount": float(np.median(np.abs(a - med))),
                "typical_hours": [int(h) for h in np.argsort(-st.hours, kind="stable")[:3]],
                "mean_interarrival_secs": st.interarrival,
                "known_merchants": sorted(st.merchants),
                "failure_rate": st.failed / st.total if st.total else 0.0}

    # ------------------------------------------------------------------ batch replay
    def replay(self, df: pd.DataFrame, contaminated_ids: frozenset = frozenset()) -> pd.DataFrame:
        """Chronological replay (mutates this engine). Rows with an identical timestamp are all
        scored before any of them updates the baseline. Index aligned to `df`."""
        d = df.reset_index(drop=True)
        ts = pd.to_datetime(d["ts"], utc=True)
        secs = (ts - EPOCH).dt.total_seconds().to_numpy()
        order = np.lexsort((d["external_id"].to_numpy(), secs))
        results: list[BehaviourIndicators | None] = [None] * len(d)
        i = 0
        while i < len(order):
            j = i
            while j < len(order) and secs[order[j]] == secs[order[i]]:
                j += 1
            group = []
            for pos in order[i:j]:
                row = d.iloc[pos]
                txn = {"external_id": row["external_id"], "account_id": row["account_id"],
                       "merchant_id": row.get("merchant_id"), "amount": row["amount"],
                       "status": row.get("status"), "ts": ts.iloc[pos]}
                if pd.isna(txn["merchant_id"]):
                    txn["merchant_id"] = None
                results[pos] = self.indicators(txn)
                group.append(txn)
            for txn in group:
                self.update(txn, contaminated=txn["external_id"] in contaminated_ids)
            i = j
        out = pd.DataFrame([asdict(r) for r in results])
        out.index = df.index
        return out
