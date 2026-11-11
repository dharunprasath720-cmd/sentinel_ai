"""Read-only aggregate queries behind the dashboard. Every function is scoped to one business and
one data source; nothing here writes, and the ground-truth label is never selected."""
from collections import Counter
from datetime import timedelta
from typing import Literal

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from sentinel.cases.orm import Alert, Case, CaseAlert, RiskAssessmentRow
from sentinel.ingestion.orm import Transaction
from sentinel.pipeline import HIGH_PLUS
from sentinel.risk.engine import LEVELS
from sentinel.security import NotFound

Source = Literal["synthetic", "paysim", "paypal_sandbox"]

CAVEAT = ("These are held-out evaluation numbers on synthetic data, not a guarantee on real traffic; "
          "some suspicious activity is missed, so recall is shown next to precision and PR-AUC.")


def _day(ts) -> str:
    return ts.strftime("%Y-%m-%d")


def overview(session: Session, business_id: str, source: str) -> dict:
    rows = (session.query(Transaction.ts, Transaction.amount, RiskAssessmentRow.risk_level,
                          RiskAssessmentRow.details)
            .outerjoin(RiskAssessmentRow, and_(RiskAssessmentRow.business_id == Transaction.business_id,
                                               RiskAssessmentRow.txn_external_id == Transaction.external_id))
            .filter(Transaction.business_id == business_id, Transaction.source == source).all())
    by_level = {level: 0 for level in LEVELS}
    daily: dict[str, list[int]] = {}
    suspicious, clusters = 0.0, set()
    for ts, amount, level, details in rows:
        slot = daily.setdefault(_day(ts), [0, 0])
        slot[0] += 1
        if level in by_level:
            by_level[level] += 1
        if level in HIGH_PLUS:
            slot[1] += 1
            suspicious += float(amount)
        cluster = (details or {}).get("cluster_id")
        if cluster:
            clusters.add(cluster)

    alert_q = (session.query(Alert.status, Alert.id)
               .join(Transaction, and_(Transaction.business_id == Alert.business_id,
                                       Transaction.external_id == Alert.txn_external_id))
               .filter(Alert.business_id == business_id, Transaction.source == source))
    open_alerts = sum(1 for status, _ in alert_q if status == "open")
    case_ids = {cid for (cid,) in
                session.query(Case.id)
                .join(CaseAlert, CaseAlert.case_id == Case.id)
                .join(Alert, Alert.id == CaseAlert.alert_id)
                .join(Transaction, and_(Transaction.business_id == Alert.business_id,
                                        Transaction.external_id == Alert.txn_external_id))
                .filter(Case.business_id == business_id, Case.status.in_(("open", "in_review")),
                        Transaction.source == source)}
    return {"source": source,
            "transactions": {"total": len(rows), "by_level": by_level},
            "open_alerts": open_alerts, "open_cases": len(case_ids), "flagged_clusters": len(clusters),
            "suspicious_value": suspicious,
            "daily": [{"date": d, "transactions": c[0], "high_plus": c[1]} for d, c in sorted(daily.items())]}


def models_summary(bundle) -> dict:
    keep = ("pr_auc", "roc_auc", "precision", "recall", "f1", "threshold", "n_positive",
            "calibrator", "brier_raw", "brier_calibrated")
    return {"version": bundle.version, "evaluation": "held-out test split",
            "models": {name: {k: m.get(k) for k in keep} for name, m in bundle.metrics.items()},
            "caveat": CAVEAT}


Level = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]


def recent_transactions(session: Session, business_id: str, source: str, level: str | None,
                        limit: int) -> list[dict]:
    q = (session.query(Transaction, RiskAssessmentRow)
         .outerjoin(RiskAssessmentRow, and_(RiskAssessmentRow.business_id == Transaction.business_id,
                                            RiskAssessmentRow.txn_external_id == Transaction.external_id))
         .filter(Transaction.business_id == business_id, Transaction.source == source))
    if level:
        q = q.filter(RiskAssessmentRow.risk_level == level)
    out = []
    for t, a in q.order_by(Transaction.ts.desc(), Transaction.external_id.desc()).limit(limit):
        out.append({"external_id": t.external_id, "ts": t.ts.isoformat(), "amount": float(t.amount),
                    "account_id": t.account_id, "merchant_id": t.merchant_id, "source": t.source,
                    "risk_level": a.risk_level if a else None,
                    "risk_score": a.risk_score if a else None,
                    "action": a.action if a else None,
                    "cluster_id": ((a.details or {}).get("cluster_id") if a else None)})
    return out


def _case_ids_in_source(session: Session, business_id: str, source: str) -> set[int]:
    return {cid for (cid,) in
            session.query(Case.id)
            .join(CaseAlert, CaseAlert.case_id == Case.id)
            .join(Alert, Alert.id == CaseAlert.alert_id)
            .join(Transaction, and_(Transaction.business_id == Alert.business_id,
                                    Transaction.external_id == Alert.txn_external_id))
            .filter(Case.business_id == business_id, Transaction.source == source)}


def list_cases(session: Session, business_id: str, source: str | None = None) -> list[dict]:
    """Newest first. With `source`, only cases holding at least one alert on that source's transactions."""
    counts = Counter(cid for (cid,) in session.query(CaseAlert.case_id)
                     .join(Case, Case.id == CaseAlert.case_id).filter(Case.business_id == business_id))
    cases = session.query(Case).filter_by(business_id=business_id).order_by(Case.id.desc()).all()
    if source is not None:
        keep = _case_ids_in_source(session, business_id, source)
        cases = [c for c in cases if c.id in keep]
    return [{"id": c.id, "status": c.status, "approved_action": c.approved_action,
             "n_alerts": counts.get(c.id, 0), "created_at": c.created_at.isoformat()} for c in cases]


def alerts_in_source(session: Session, business_id: str, status: str | None, source: str) -> list[Alert]:
    q = (session.query(Alert)
         .join(Transaction, and_(Transaction.business_id == Alert.business_id,
                                 Transaction.external_id == Alert.txn_external_id))
         .filter(Alert.business_id == business_id, Transaction.source == source))
    if status:
        q = q.filter(Alert.status == status)
    return q.order_by(Alert.id).all()


MAX_GRAPH_NODES = 200
_RANK = {level: i for i, level in enumerate(LEVELS)}


def _levels_for(session: Session, business_id: str, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    return {a.txn_external_id: a.risk_level for a in session.query(RiskAssessmentRow).filter(
        RiskAssessmentRow.business_id == business_id, RiskAssessmentRow.txn_external_id.in_(ids))}


def _build_graph(txns: list[Transaction], levels: dict[str, str], root: str | None = None) -> dict:
    """Account/device/merchant graph over `txns`. Node risk is the highest level among its
    transactions; at most MAX_GRAPH_NODES nodes (the root account is always kept first)."""
    nodes: dict[str, dict] = {}
    edges: dict[tuple, int] = {}

    def touch(kind: str, key: str, level: str | None) -> str:
        nid = f"{kind}:{key}"
        n = nodes.setdefault(nid, {"id": nid, "kind": kind, "label": key, "risk_level": None, "txn_count": 0})
        n["txn_count"] += 1
        if level and (n["risk_level"] is None or _RANK[level] > _RANK[n["risk_level"]]):
            n["risk_level"] = level
        return nid

    for t in txns:
        level = levels.get(t.external_id)
        acct = touch("account", t.account_id, level)
        for kind, key, edge_kind in (("device", t.device_id, "uses_device"),
                                     ("merchant", t.merchant_id, "pays_merchant")):
            if key:
                edge = (acct, touch(kind, key, level), edge_kind)
                edges[edge] = edges.get(edge, 0) + 1

    ordered = sorted(nodes.values(), key=lambda n: (n["id"] != f"account:{root}", -n["txn_count"], n["id"]))
    kept = {n["id"] for n in ordered[:MAX_GRAPH_NODES]}
    return {"nodes": [n for n in ordered if n["id"] in kept],
            "edges": [{"source": s, "target": t, "kind": k, "weight": w}
                      for (s, t, k), w in sorted(edges.items()) if s in kept and t in kept],
            "truncated": len(ordered) > len(kept)}


def flagged_clusters(session: Session, business_id: str, source: str, toolbox, limit: int = 20) -> list[dict]:
    rows = (session.query(RiskAssessmentRow.id, RiskAssessmentRow.details)
            .join(Transaction, and_(Transaction.business_id == RiskAssessmentRow.business_id,
                                    Transaction.external_id == RiskAssessmentRow.txn_external_id))
            .filter(RiskAssessmentRow.business_id == business_id, Transaction.source == source)
            .order_by(RiskAssessmentRow.id.desc()))
    seen: list[str] = []
    for _, details in rows:
        cid = (details or {}).get("cluster_id")
        if cid and cid not in seen:
            seen.append(cid)
    out = []
    for cid in seen:
        if len(out) >= limit:
            break
        try:
            c = toolbox.get_graph_cluster(cid)
        except NotFound:
            continue
        out.append({"cluster_id": c["cluster_id"], "n_accounts": len(c["accounts"]),
                    "n_devices": len(c["devices"]), "n_merchants": len(c["merchants"]),
                    "signals": c["signals"], "risk_indicator": c["risk_indicator"]})
    return out


def graph_for_cluster(session: Session, business_id: str, toolbox, cluster_id: str) -> dict:
    c = toolbox.get_graph_cluster(cluster_id)  # NotFound for unknown ids / other businesses
    txns = session.query(Transaction).filter(
        Transaction.business_id == business_id,
        Transaction.external_id.in_(c["evidence_transactions"])).all()
    return _build_graph(txns, _levels_for(session, business_id, [t.external_id for t in txns]))


def graph_for_account(session: Session, business_id: str, source: str, account_id: str, hours: int) -> dict:
    base = Transaction.business_id == business_id, Transaction.source == source
    latest = (session.query(Transaction.ts).filter(*base, Transaction.account_id == account_id)
              .order_by(Transaction.ts.desc()).first())
    if latest is None:
        raise NotFound(account_id)
    lo = latest[0] - timedelta(hours=hours)
    mine = session.query(Transaction).filter(*base, Transaction.account_id == account_id,
                                             Transaction.ts >= lo).all()
    devices = {t.device_id for t in mine if t.device_id}
    merchants = {t.merchant_id for t in mine if t.merchant_id}
    shared = []
    if devices or merchants:
        cond = []
        if devices:
            cond.append(Transaction.device_id.in_(devices))
        if merchants:
            cond.append(Transaction.merchant_id.in_(merchants))
        shared = session.query(Transaction).filter(*base, Transaction.ts >= lo, Transaction.ts <= latest[0],
                                                   Transaction.account_id != account_id, or_(*cond)).all()
    txns = mine + shared
    return _build_graph(txns, _levels_for(session, business_id, [t.external_id for t in txns]), root=account_id)
