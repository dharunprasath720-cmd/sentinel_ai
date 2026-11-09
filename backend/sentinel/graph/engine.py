"""Graph intelligence: heterogeneous graph, suspicious-cluster detection, window indicators.

Rules
  * Edges exist only where the data has the link (null device/merchant/instrument = no edge).
  * Nodes are keyed (kind, business_id, id): the same id in two businesses never merges.
  * A shared identifier is weak evidence. A cluster is `flagged` only when >= 3 of 4 signals
    co-occur; `risk_indicator` = n_signals / 4. Nothing here assigns a fraud label.
  * `window_indicators` is point-in-time: only rows STRICTLY earlier than the current one
    (ties excluded) contribute, plus the current row's own account.
"""
import hashlib
from collections import deque
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import pandas as pd

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
SIGNALS = ["shared_device", "common_merchant", "tight_window", "similar_abnormal_behaviour"]
FLAG_AT = 3
LINK_SECS = 1800.0  # two accounts are "co-active" at a merchant only within 30 minutes


def _seconds(ts) -> np.ndarray:
    return (pd.to_datetime(ts, utc=True) - EPOCH).dt.total_seconds().to_numpy()


def _biz(df: pd.DataFrame) -> pd.Series:
    return df["business_id"] if "business_id" in df.columns else pd.Series("default", index=df.index)


@dataclass
class Cluster:
    cluster_id: str
    business_id: str
    accounts: list[str]
    devices: list[str]
    merchants: list[str]
    txn_ids: list[str]
    density: float
    signals: list[str]
    flagged: bool
    risk_indicator: float
    evidence: dict = field(default_factory=dict)


# ---------------------------------------------------------------- graph
def build_graph(df: pd.DataFrame) -> nx.Graph:
    d = df.assign(_b=_biz(df))
    G = nx.Graph()
    for biz, acct in d[["_b", "account_id"]].drop_duplicates().itertuples(index=False):
        G.add_node(("account", biz, acct), kind="account")
    for col, kind in (("merchant_id", "merchant"), ("device_id", "device"),
                      ("instrument_id", "instrument")):
        if col not in d.columns:
            continue
        agg = (d.dropna(subset=[col]).groupby(["_b", "account_id", col])
               .agg(n_txn=("external_id", "size"), total_amount=("amount", "sum"),
                    first_ts=("ts", "min"), last_ts=("ts", "max")).reset_index())
        for r in agg.itertuples(index=False):
            other = (kind, r._0, getattr(r, col))
            G.add_node(other, kind=kind)
            G.add_edge(("account", r._0, r.account_id), other, n_txn=int(r.n_txn),
                       total_amount=float(r.total_amount), first_ts=r.first_ts, last_ts=r.last_ts)
    return G


def cluster_degree_centrality(G: nx.Graph) -> dict:
    return nx.degree_centrality(G)


# ---------------------------------------------------------------- point-in-time window counts
def window_indicators(df: pd.DataFrame, window_hours: float = 2.0) -> pd.DataFrame:
    d = df.reset_index(drop=True).copy()
    d["_t"] = _seconds(d["ts"])
    d["_b"] = _biz(d).to_numpy()
    w = window_hours * 3600.0
    out = {"merchant_accounts_window": np.zeros(len(d), dtype=np.int64),
           "device_accounts_window": np.zeros(len(d), dtype=np.int64)}
    for col, name in (("merchant_id", "merchant_accounts_window"),
                      ("device_id", "device_accounts_window")):
        for _, g in d.dropna(subset=[col]).groupby(["_b", col], sort=False):
            g = g.sort_values(["_t", "external_id"], kind="mergesort")
            idx, t, acc = g.index.to_numpy(), g["_t"].to_numpy(), g["account_id"].to_numpy()
            counts: dict = {}
            window: deque = deque()
            i = 0
            while i < len(idx):
                j = i
                while j < len(idx) and t[j] == t[i]:
                    j += 1
                while window and window[0][0] < t[i] - w:
                    a = window.popleft()[1]
                    counts[a] -= 1
                    if counts[a] == 0:
                        del counts[a]
                for k in range(i, j):
                    out[name][idx[k]] = len(counts) + (acc[k] not in counts)
                for k in range(i, j):
                    window.append((t[k], acc[k]))
                    counts[acc[k]] = counts.get(acc[k], 0) + 1
                i = j
    return pd.DataFrame(out, index=df.index)


# ---------------------------------------------------------------- clusters
def _co_merchant_mask(sub: pd.DataFrame, w: float, anchor: np.ndarray) -> np.ndarray:
    """True where ANOTHER account's anchored (shared-device) transaction hit the same merchant
    within +/- w seconds. Anchoring keeps unrelated coincidental purchases out of the evidence."""
    mask = np.zeros(len(sub), dtype=bool)
    for _, g in sub.dropna(subset=["merchant_id"]).groupby("merchant_id", sort=False):
        g = g.sort_values("_t", kind="mergesort")
        idx, t, a = g.index.to_numpy(), g["_t"].to_numpy(), g["account_id"].to_numpy()
        anc = anchor[idx]
        for i in range(len(idx)):
            lo = np.searchsorted(t, t[i] - w, side="left")
            hi = np.searchsorted(t, t[i] + w, side="right")
            if ((a[lo:hi] != a[i]) & anc[lo:hi]).any():
                mask[idx[i]] = True
    return mask


def _densest_window(t: np.ndarray, accounts: np.ndarray, w: float) -> tuple[int, float, int]:
    """Largest number of transactions inside any window of length w: (count, span_secs, n_accounts)."""
    order = np.argsort(t, kind="mergesort")
    t, accounts = t[order], accounts[order]
    best = (0, 0.0, 0)
    for i in range(len(t)):
        j = np.searchsorted(t, t[i] + w, side="right")
        if j - i > best[0]:
            best = (int(j - i), float(t[j - 1] - t[i]), len(set(accounts[i:j])))
    return best


def _projection(b: pd.DataFrame, w: float) -> nx.Graph:
    """Account graph: shared device (weight 3 each) and same-merchant-within-window (1 each)."""
    P = nx.Graph()
    P.add_nodes_from(b["account_id"].unique())
    for _, g in b.dropna(subset=["device_id"]).groupby("device_id", sort=False):
        accts = sorted(g["account_id"].unique())
        for i in range(len(accts)):
            for j in range(i + 1, len(accts)):
                P.add_edge(accts[i], accts[j],
                           weight=P.get_edge_data(accts[i], accts[j], {}).get("weight", 0) + 3)
    for _, g in b.dropna(subset=["merchant_id"]).groupby("merchant_id", sort=False):
        g = g.sort_values("_t", kind="mergesort")
        t, a = g["_t"].to_numpy(), g["account_id"].to_numpy()
        for i in range(len(t)):
            j = i + 1
            while j < len(t) and t[j] - t[i] <= w:
                if a[j] != a[i]:
                    P.add_edge(a[i], a[j], weight=P.get_edge_data(a[i], a[j], {}).get("weight", 0) + 1)
                j += 1
    # coincidental same-merchant payments are not a relationship: keep an edge only if the pair
    # is linked by a shared device (weight 3) or co-occurs at a merchant at least 3 times
    P.remove_edges_from([(u, v) for u, v, wt in P.edges(data="weight") if wt < 3])
    return P


def _clusters_for_business(biz: str, b: pd.DataFrame, min_accounts: int, w: float) -> list[Cluster]:
    b = b.reset_index(drop=True)
    P = _projection(b, min(w, LINK_SECS))
    if P.number_of_edges() == 0:
        return []
    found = []
    for comm in nx.community.louvain_communities(P, weight="weight", seed=42):
        if len(comm) < min_accounts:
            continue
        accts = sorted(comm)
        sub = b[b["account_id"].isin(comm)].reset_index(drop=True)
        dev_n = sub.dropna(subset=["device_id"]).groupby("device_id")["account_id"].nunique()
        shared = dev_n[dev_n >= 2]
        # evidence anchors on devices shared by >= 3 accounts (the shared_device threshold); a
        # 2-account device is ordinary (family, couple) and must not dilute the evidence
        on_shared = sub["device_id"].isin(dev_n[dev_n >= 3].index).to_numpy()
        ev = sub[on_shared | _co_merchant_mask(sub, w, on_shared)]
        signals, evidence = [], {"shared_devices": {k: int(v) for k, v in shared.items()}}
        if (dev_n >= 3).any():
            signals.append("shared_device")
        if len(ev):
            top = ev["merchant_id"].value_counts()
            if len(top):
                top_m, share = top.index[0], float(top.iloc[0] / len(ev))
                evidence.update(top_merchant=top_m, merchant_share=share)
                if share >= 0.6:
                    signals.append("common_merchant")
                tm = ev[ev["merchant_id"] == top_m]
                n_in, span, n_acc = _densest_window(tm["_t"].to_numpy(), tm["account_id"].to_numpy(), w)
                evidence.update(window_minutes=span / 60.0, burst_share=n_in / len(tm))
                if n_in >= 3 and n_acc >= 2 and n_in / len(tm) >= 0.6:
                    signals.append("tight_window")
            if "_dev" in ev.columns and ev["_dev"].notna().any():
                evidence["mean_deviation"] = float(ev["_dev"].mean())
                if evidence["mean_deviation"] >= 0.5:
                    signals.append("similar_abnormal_behaviour")
        if not signals:
            continue
        cid = "CL_" + hashlib.sha1((biz + "|" + ",".join(accts)).encode()).hexdigest()[:10]
        found.append(Cluster(
            cluster_id=cid, business_id=biz, accounts=accts, devices=sorted(shared.index),
            merchants=sorted(ev["merchant_id"].dropna().unique())[:10],
            txn_ids=ev["external_id"].tolist(), density=float(nx.density(P.subgraph(accts))),
            signals=[s for s in SIGNALS if s in signals], flagged=len(signals) >= FLAG_AT,
            risk_indicator=len(signals) / len(SIGNALS), evidence=evidence))
    return found


def find_clusters(df: pd.DataFrame, behaviour: pd.DataFrame | None = None,
                  min_accounts: int = 3, window_hours: float = 3.0) -> list[Cluster]:
    """Community-detect (Louvain, seed 42) per business and score each community's signals.
    `behaviour`: optional frame aligned to `df` with a `deviation_score` column."""
    d = df.copy()
    d["_t"] = _seconds(d["ts"])
    d["_b"] = _biz(d).to_numpy()
    if behaviour is not None:
        d["_dev"] = behaviour["deviation_score"].reindex(d.index).to_numpy()
    out: list[Cluster] = []
    for biz, b in d.groupby("_b", sort=True):
        out += _clusters_for_business(str(biz), b, min_accounts, window_hours * 3600.0)
    return sorted(out, key=lambda c: (-c.risk_indicator, -len(c.accounts), c.cluster_id))
