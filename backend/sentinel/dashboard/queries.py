"""Read-only aggregate queries behind the dashboard. Every function is scoped to one business and
one data source; nothing here writes, and the ground-truth label is never selected."""
from collections import Counter
from typing import Literal

from sqlalchemy import and_
from sqlalchemy.orm import Session

from sentinel.cases.orm import Alert, Case, CaseAlert, RiskAssessmentRow
from sentinel.ingestion.orm import Transaction
from sentinel.pipeline import HIGH_PLUS
from sentinel.risk.engine import LEVELS

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


def list_cases(session: Session, business_id: str) -> list[dict]:
    counts = Counter(cid for (cid,) in session.query(CaseAlert.case_id)
                     .join(Case, Case.id == CaseAlert.case_id).filter(Case.business_id == business_id))
    cases = session.query(Case).filter_by(business_id=business_id).order_by(Case.id.desc()).all()
    return [{"id": c.id, "status": c.status, "approved_action": c.approved_action,
             "n_alerts": counts.get(c.id, 0), "created_at": c.created_at.isoformat()} for c in cases]
