"""Incremental, per-event scoring that agrees with the batch pipeline.

For one event the features and graph window counts are computed on a SMALL slice of history:
every stored row of the same business that shares the event's account, merchant or device, plus
the event itself. Those are exactly the rows the point-in-time feature definitions read, so the
event's features equal the batch features (checked in tests). Behaviour baselines persist in one
BehaviourEngine, cluster flags are computed as-of the event from the previous 24h only.

Differences from the batch two-pass pipeline (documented, measured in tests):
  * single pass: an event updates baselines after being scored (HIGH+ events are excluded from
    baselines), instead of pass 1 deciding contamination for pass 2;
  * account/merchant history uses the live running counts of earlier HIGH+ events, seeded from
    `history_levels` when the caller has them.
Late events (older than the newest event of their business) are scored from `ts <`-correct history
but with neutral behaviour and never touch a baseline; they are flagged `late=True`.
Everything is keyed by business_id; the same ids in two businesses never interact.
"""
import bisect
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sentinel.behaviour.engine import BehaviourEngine, BehaviourIndicators
from sentinel.features.engine import build_features
from sentinel.graph.engine import find_clusters, window_indicators
from sentinel.pipeline import CLUSTER_LOOKBACK_SECS, CLUSTER_TRIGGER_ACCOUNTS, HIGH_PLUS, graph_signal
from sentinel.risk.engine import RiskAssessment, RiskInputs

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def _none(v):
    return None if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)) else v


@dataclass
class ScoredEvent:
    external_id: str
    business_id: str
    assessment: RiskAssessment
    inputs: dict
    behaviour_reasons: list[str]
    cluster_id: str | None
    late: bool
    latency_ms: float
    features: pd.Series = field(repr=False)


class LiveScorer:
    def __init__(self, bundle, engine, normalisers, history: pd.DataFrame | None = None,
                 history_levels: pd.Series | None = None):
        self.bundle, self.engine, self.norms = bundle, engine, normalisers
        self._lock = threading.RLock()
        self._rows: list[dict] = []
        self._idx = {k: defaultdict(list) for k in ("acct", "merch", "dev")}
        self._time = defaultdict(list)            # business -> sorted [(ts_secs, position)]
        self._newest: dict[str, float] = {}
        self._seen: dict[tuple, ScoredEvent] = {}
        self._beh = BehaviourEngine()
        self._acct = defaultdict(lambda: [0, 0])  # (business, account) -> [events, HIGH+ events]
        self._merch = defaultdict(lambda: [0, 0])
        self.n_processed = 0
        if history is not None and len(history):
            self._warm_start(history, history_levels)

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _partition(business_id: str, source: str) -> str:
        """Scorer state is partitioned by (business, data source): synthetic, PaySim and PayPal
        Sandbox rows are never blended - not into features, baselines, clusters or the 'newest event'
        clock (one PayPal event dated today must not make all earlier-dated traffic 'late')."""
        return f"{business_id}|{source}"

    @classmethod
    def _row(cls, txn: dict) -> dict:
        biz = _none(txn.get("business_id")) or "default"
        source = _none(txn.get("source")) or "unknown"
        return {"external_id": txn["external_id"], "account_id": txn["account_id"],
                "merchant_id": _none(txn.get("merchant_id")), "device_id": _none(txn.get("device_id")),
                "instrument_id": _none(txn.get("instrument_id")), "amount": float(txn["amount"]),
                "ts": pd.to_datetime(txn["ts"], utc=True), "type": txn.get("type", "PAYMENT"),
                "status": txn.get("status", "completed"),
                "business_id": cls._partition(biz, source),  # internal partition key
                "_biz": biz}                                  # the real business, for outputs

    def _store(self, row: dict) -> None:
        pos, biz = len(self._rows), row["business_id"]
        self._rows.append(row)
        self._idx["acct"][(biz, row["account_id"])].append(pos)
        if row["merchant_id"] is not None:
            self._idx["merch"][(biz, row["merchant_id"])].append(pos)
        if row["device_id"] is not None:
            self._idx["dev"][(biz, row["device_id"])].append(pos)
        t = (row["ts"] - EPOCH).total_seconds()
        bisect.insort(self._time[biz], (t, pos))
        self._newest[biz] = max(self._newest.get(biz, t), t)

    def _warm_start(self, history: pd.DataFrame, levels: pd.Series | None) -> None:
        h = history.reset_index(drop=True)
        if "business_id" not in h.columns:
            h["business_id"] = "default"
        source = h["source"] if "source" in h.columns else pd.Series("unknown", index=h.index)
        partition = h["business_id"].astype(str) + "|" + source.fillna("unknown").astype(str)
        self._beh.replay(h.assign(business_id=partition))  # persistent baselines from history
        bad = (levels.isin(HIGH_PLUS).to_numpy() if levels is not None else np.zeros(len(h), bool))
        order = np.lexsort((h["external_id"].to_numpy(), pd.to_datetime(h["ts"], utc=True).to_numpy()))
        recs = h.to_dict("records")
        for i in order:
            row = self._row(recs[i])
            self._store(row)
            self._seen[(row["business_id"], row["external_id"])] = None  # known, nothing to return
            for counter, key in ((self._acct, (row["business_id"], row["account_id"])),
                                 (self._merch, (row["business_id"], row["merchant_id"]))):
                if key[1] is not None:
                    counter[key][0] += 1
                    counter[key][1] += int(bad[i])

    # ------------------------------------------------------------------ queries
    def behaviour_profile(self, account_id: str, business_id: str, source: str = "synthetic") -> dict:
        with self._lock:
            return self._beh.profile(account_id, self._partition(business_id, source))

    # ------------------------------------------------------------------ scoring
    def _slice(self, row: dict) -> pd.DataFrame:
        biz = row["business_id"]
        pos = set(self._idx["acct"].get((biz, row["account_id"]), ()))
        if row["merchant_id"] is not None:
            pos |= set(self._idx["merch"].get((biz, row["merchant_id"]), ()))
        if row["device_id"] is not None:
            pos |= set(self._idx["dev"].get((biz, row["device_id"]), ()))
        return pd.DataFrame([self._rows[p] for p in sorted(pos)] + [row]).reset_index(drop=True)

    def _cluster_flag(self, row: dict, t: float) -> tuple[bool, str | None]:
        times = self._time[row["business_id"]]
        lo = bisect.bisect_left(times, (t - CLUSTER_LOOKBACK_SECS, -1))
        hi = bisect.bisect_left(times, (t, -1))  # strictly before the event
        hist = pd.DataFrame([self._rows[p] for _, p in times[lo:hi]] + [row])
        for c in find_clusters(hist):
            if c.flagged and row["external_id"] in set(c.txn_ids):
                return True, c.cluster_id
        return False, None

    def score(self, txn: dict) -> ScoredEvent:
        with self._lock:
            t0 = time.perf_counter()
            row = self._row(txn)
            biz = row["business_id"]
            cached = self._seen.get((biz, row["external_id"]))
            if cached is not None or (biz, row["external_id"]) in self._seen:
                return cached
            t = (row["ts"] - EPOCH).total_seconds()
            late = biz in self._newest and t < self._newest[biz]

            sub = self._slice(row)
            feats = build_features(sub).iloc[[-1]]
            win = window_indicators(sub).iloc[-1]
            dev_n, mer_n = int(win["device_accounts_window"]), int(win["merchant_accounts_window"])
            flagged, cluster_id = (self._cluster_flag(row, t)
                                   if dev_n >= CLUSTER_TRIGGER_ACCOUNTS else (False, None))
            preds = self.bundle.predict(feats).iloc[0]

            beh_txn = {k: row[k] for k in ("external_id", "account_id", "business_id", "merchant_id",
                                           "amount", "status", "ts")}
            ind = BehaviourIndicators() if late else self._beh.indicators(beh_txn)
            a_n, a_bad = self._acct[(biz, row["account_id"])]
            m_n, m_bad = self._merch[(biz, row["merchant_id"])] if row["merchant_id"] is not None else (0, 0)
            clip = lambda x: float(min(1.0, max(0.0, x)))  # noqa: E731
            inputs = {
                "ml_prob": clip(preds["lgbm_prob"]), "anomaly": clip(preds["anomaly_score"]),
                "behaviour": clip(ind.deviation_score),
                "graph": clip(float(graph_signal(dev_n, mer_n, flagged))),
                "velocity": clip(self.norms["velocity"].transform(float(feats["txn_count_1h"].iloc[0]), strict=True)),
                "account_history": clip(a_bad / a_n if a_n else 0.0),
                "merchant_risk": clip(m_bad / m_n if m_n else 0.0),
            }
            assessment = self.engine.assess(RiskInputs(**inputs, cluster_flagged=flagged))

            bad = assessment.risk_level in HIGH_PLUS
            self._acct[(biz, row["account_id"])][0] += 1
            self._acct[(biz, row["account_id"])][1] += int(bad)
            if row["merchant_id"] is not None:
                self._merch[(biz, row["merchant_id"])][0] += 1
                self._merch[(biz, row["merchant_id"])][1] += int(bad)
            if not late:
                self._beh.update(beh_txn, contaminated=bad)
            self._store(row)
            self.n_processed += 1
            event = ScoredEvent(
                external_id=row["external_id"], business_id=row["_biz"], assessment=assessment,
                inputs={**inputs, "cluster_flagged": flagged}, behaviour_reasons=list(ind.reasons),
                cluster_id=cluster_id, late=late, latency_ms=(time.perf_counter() - t0) * 1000.0,
                features=feats.iloc[0])
            self._seen[(biz, row["external_id"])] = event
            return event
