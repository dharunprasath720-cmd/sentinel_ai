"""Alert, case and audit workflow. Every function is scoped to the acting user's business.

Rules: viewers read only; analysts/admins act; admins read the audit log. An approved action
is a RECORDED RECOMMENDATION - nothing is executed. "suspicious" is a case outcome, never a
fraud label: no function here touches Transaction.label. There is deliberately no function
that updates or deletes audit entries.
"""
from typing import Iterable

from sqlalchemy.orm import Session

from sentinel.cases.orm import Alert, AuditLog, Case, CaseAlert, CaseNote, RiskAssessmentRow, User
from sentinel.risk.engine import LEVELS, RiskAssessment
from sentinel.security import Conflict, Forbidden, NotFound, require_role

ACTOR_ROLES = {"analyst", "admin"}
ACTIONS = {"ALLOW", "MONITOR", "REVIEW", "VERIFY", "HOLD_RECOMMENDED"}
OUTCOMES = {"suspicious": "resolved_suspicious", "cleared": "resolved_cleared"}


def audit(session: Session, business_id: str, actor: str, action: str, target: str,
          before: dict | None = None, after: dict | None = None) -> None:
    session.add(AuditLog(business_id=business_id, actor=actor, action=action, target=target,
                         before=before, after=after))


def record_assessment(session: Session, business_id: str, txn_external_id: str,
                      a: RiskAssessment, model_version: str) -> RiskAssessmentRow:
    """One row per (business, transaction); re-scoring updates it in place."""
    row = (session.query(RiskAssessmentRow)
           .filter_by(business_id=business_id, txn_external_id=txn_external_id).one_or_none())
    if row is None:
        row = RiskAssessmentRow(business_id=business_id, txn_external_id=txn_external_id)
        session.add(row)
    row.risk_score, row.risk_level, row.action = a.risk_score, a.risk_level, a.recommended_action
    row.calibrated_fraud_probability = a.calibrated_fraud_probability
    row.factors, row.model_version, row.policy_version = list(a.risk_factors), model_version, a.policy_version
    session.flush()
    return row


def create_alerts(session: Session, business_id: str, rows: Iterable[RiskAssessmentRow],
                  min_level: str = "HIGH") -> list[Alert]:
    """Create an alert for each qualifying row that has none yet; returns the NEW alerts."""
    created = []
    for row in rows:
        if row.business_id != business_id or LEVELS.index(row.risk_level) < LEVELS.index(min_level):
            continue
        exists = session.query(Alert).filter_by(
            business_id=business_id, txn_external_id=row.txn_external_id).first()
        if exists is None:
            alert = Alert(business_id=business_id, txn_external_id=row.txn_external_id,
                          level=row.risk_level)
            session.add(alert)
            created.append(alert)
    session.flush()
    return created


def list_alerts(session: Session, user: User, status: str | None = None) -> list[Alert]:
    q = session.query(Alert).filter_by(business_id=user.business_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(Alert.id).all()


def _case(session: Session, user: User, case_id: int) -> Case:
    case = session.get(Case, case_id)
    if case is None or case.business_id != user.business_id:
        raise NotFound(f"case {case_id}")
    return case


def _require_unresolved(case: Case) -> None:
    """A resolved case is closed: it cannot be re-approved, reopened or flipped. (Notes may
    still be added after closure.)"""
    if case.status.startswith("resolved"):
        raise Conflict(f"case {case.id} is already {case.status}")


def open_case(session: Session, user: User, alert_ids: list[int]) -> Case:
    require_role(user.role, ACTOR_ROLES)
    ids = set(alert_ids)
    if not ids:
        raise ValueError("a case needs at least one alert")
    alerts = session.query(Alert).filter(Alert.id.in_(ids), Alert.business_id == user.business_id).all()
    if len(alerts) != len(ids):
        raise NotFound("alert")
    if any(a.status != "open" for a in alerts):
        raise Conflict("alert is already in a case or closed")
    case = Case(business_id=user.business_id, assignee_id=user.id, status="open")
    session.add(case)
    session.flush()
    for a in alerts:
        session.add(CaseAlert(case_id=case.id, alert_id=a.id))
        a.status = "in_review"
    audit(session, user.business_id, user.username, "open_case", f"case:{case.id}",
          None, {"status": "open", "alert_ids": sorted(ids)})
    session.flush()
    return case


def add_note(session: Session, user: User, case_id: int, body: str) -> CaseNote:
    require_role(user.role, ACTOR_ROLES)
    case = _case(session, user, case_id)
    note = CaseNote(case_id=case.id, author_id=user.id, body=body)
    session.add(note)
    audit(session, user.business_id, user.username, "add_note", f"case:{case.id}",
          None, {"length": len(body)})
    session.flush()
    return note


def approve_action(session: Session, user: User, case_id: int, action: str) -> Case:
    """Record an approved recommendation. Executes nothing."""
    require_role(user.role, ACTOR_ROLES)
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {sorted(ACTIONS)}")
    case = _case(session, user, case_id)
    _require_unresolved(case)
    before = {"status": case.status, "approved_action": case.approved_action}
    case.approved_action, case.status = action, "in_review"
    audit(session, user.business_id, user.username, "approve_action", f"case:{case.id}", before,
          {"status": case.status, "approved_action": action})
    session.flush()
    return case


def resolve_case(session: Session, user: User, case_id: int, outcome: str) -> Case:
    require_role(user.role, ACTOR_ROLES)
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}")
    case = _case(session, user, case_id)
    _require_unresolved(case)
    before = {"status": case.status}
    case.status = OUTCOMES[outcome]
    for link in session.query(CaseAlert).filter_by(case_id=case.id):
        session.get(Alert, link.alert_id).status = "closed"
    audit(session, user.business_id, user.username, "resolve_case", f"case:{case.id}", before,
          {"status": case.status})
    session.flush()
    return case


def list_audit(session: Session, user: User) -> list[AuditLog]:
    require_role(user.role, {"admin"})
    return (session.query(AuditLog).filter_by(business_id=user.business_id)
            .order_by(AuditLog.id).all())
