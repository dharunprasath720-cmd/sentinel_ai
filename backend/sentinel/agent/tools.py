"""The ten read-only investigation tools the agent may call.

Safety rules enforced here, in code (not in the prompt):
  * Scope: every query is filtered by the authenticated user's business_id. The model never
    supplies a business id (no tool has such a parameter) and an id from another business is
    simply "not found" - indistinguishable from a missing one.
  * Ground truth: the transaction `label` is never returned. Everything the agent says is a
    suspicion derived from retrieved evidence, never a confirmed outcome.
  * Untrusted text: any free text that came from outside (merchant ids, notes, ...) is passed
    through `sanitise` (control characters removed, length capped). Tool results are data, not
    instructions.
  * Evidence ids: each result lists `evidence_ids` (`txn:`, `acct:`, `cluster:`, `alert:`,
    `assessment:`) naming exactly the records it returned; reports may cite only those.
"""
import re
from datetime import timezone

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from sentinel.behaviour.engine import BehaviourEngine
from sentinel.cases.orm import Alert, RiskAssessmentRow
from sentinel.features.engine import build_features
from sentinel.graph.engine import find_clusters
from sentinel.ingestion.orm import Transaction
from sentinel.models.explain import explain_transaction
from sentinel.security import NotFound

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_TEXT = 80
HISTORY_LIMIT = 50
CLUSTER_LOOKBACK_SECS = 24 * 3600
CO_MERCHANT_SECS = 1800
HIGH_PLUS = {"HIGH", "CRITICAL"}


class ToolUnavailable(Exception):
    """The tool needs something that is not loaded (e.g. the model)."""


def sanitise(value, max_len: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", _CONTROL.sub(" ", str(value))).strip()
    return text if len(text) <= max_len else text[:max_len] + "…"


def eid(kind: str, value) -> str:
    return f"{kind}:{sanitise(value, 60)}"


def _iso(ts) -> str:
    ts = pd.Timestamp(ts)
    ts = ts.tz_localize(timezone.utc) if ts.tzinfo is None else ts.tz_convert(timezone.utc)
    return ts.isoformat()


def _schema(name, description, properties, required=None):
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": properties,
                             "required": list(properties) if required is None else required,
                             "additionalProperties": False}}


_STR = {"type": "string"}
TOOL_SCHEMAS = [
    _schema("get_transaction_details", "Facts about one transaction (amount, time, merchant, device, source). "
            "The fraud label is never available.", {"transaction_id": _STR}),
    _schema("get_account_history", "The account's most recent transactions with their risk levels, plus summary statistics.",
            {"account_id": _STR}),
    _schema("get_transaction_risk", "The stored risk assessment: score, level, recommended action, model probability, "
            "contributing factors and component inputs.", {"transaction_id": _STR}),
    _schema("get_behavioural_profile", "The account's learned normal behaviour (typical amount, hours, merchants, failure rate).",
            {"account_id": _STR}),
    _schema("get_related_accounts", "Accounts linked to this one by a shared device or by repeated same-merchant "
            "payments within minutes. Every link names the transactions that justify it.", {"account_id": _STR}),
    _schema("get_graph_cluster", "A detected account cluster: members, signals, density and evidence transactions.",
            {"cluster_id": _STR}),
    _schema("get_model_explanation", "SHAP feature contributions for the model's score on this transaction. These describe "
            "the model, not causes of fraud.", {"transaction_id": _STR}),
    _schema("get_recent_alerts", "The most recent alerts for this business.", {}),
    _schema("compare_transactions", "Side-by-side comparison of 2 to 10 transactions: time gaps, shared account/device/"
            "merchant, amount ratios.", {"transaction_ids": {"type": "array", "items": _STR,
                                                              "minItems": 2, "maxItems": 10}}),
    _schema("generate_investigation_report", "A deterministic, evidence-cited report skeleton for one transaction.",
            {"transaction_id": _STR}),
]
_SCHEMAS = {t["name"]: t for t in TOOL_SCHEMAS}


class ToolBox:
    def __init__(self, session: Session, context, user):
        self.s, self.ctx, self.biz = session, context, user.business_id

    # ------------------------------------------------------------------ dispatch
    def dispatch(self, name: str, args: dict) -> dict:
        """Model-facing entry point: never raises; failures are error results with no data."""
        schema = _SCHEMAS.get(name)
        if schema is None:
            return {"error": "unknown_tool", "message": f"There is no tool named {sanitise(name, 40)!r}."}
        props = schema["input_schema"]["properties"]
        if not isinstance(args, dict) or set(args) != set(props):
            return {"error": "bad_arguments", "message": f"{name} takes exactly: {sorted(props)}."}
        for key, spec in props.items():
            v = args[key]
            if spec["type"] == "string" and not (isinstance(v, str) and 0 < len(v) <= 200):
                return {"error": "bad_arguments", "message": f"{key} must be a non-empty string."}
            if spec["type"] == "array" and not (isinstance(v, list) and 2 <= len(v) <= 10
                                                and all(isinstance(x, str) and x for x in v)):
                return {"error": "bad_arguments", "message": f"{key} must be a list of 2 to 10 ids."}
        try:
            return getattr(self, name)(**args)
        except NotFound:
            return {"error": "not_found", "message": "No such record in your business."}
        except ToolUnavailable as exc:
            return {"error": "unavailable", "message": str(exc)}

    # ------------------------------------------------------------------ data helpers
    def _txn(self, external_id: str) -> Transaction:
        t = self.s.query(Transaction).filter_by(business_id=self.biz, external_id=external_id).one_or_none()
        if t is None:
            raise NotFound(external_id)
        return t

    def _account_rows(self, account_id: str) -> list[Transaction]:
        rows = (self.s.query(Transaction).filter_by(business_id=self.biz, account_id=account_id)
                .order_by(Transaction.ts, Transaction.external_id).all())
        if not rows:
            raise NotFound(account_id)
        return rows

    def _assessment(self, external_id: str) -> RiskAssessmentRow | None:
        return (self.s.query(RiskAssessmentRow)
                .filter_by(business_id=self.biz, txn_external_id=external_id).one_or_none())

    @staticmethod
    def _frame(rows) -> pd.DataFrame:
        return pd.DataFrame([{
            "external_id": r.external_id, "account_id": r.account_id, "merchant_id": r.merchant_id,
            "device_id": r.device_id, "instrument_id": r.instrument_id, "amount": r.amount,
            "ts": pd.to_datetime(r.ts, utc=True), "type": r.type, "status": r.status,
            "business_id": r.business_id} for r in rows])

    @staticmethod
    def _public(t: Transaction) -> dict:
        return {"external_id": sanitise(t.external_id), "account_id": sanitise(t.account_id),
                "merchant_id": sanitise(t.merchant_id) or None, "device_id": sanitise(t.device_id) or None,
                "instrument_id": sanitise(t.instrument_id) or None, "amount": float(t.amount),
                "currency": sanitise(t.currency, 3), "ts": _iso(t.ts), "type": sanitise(t.type),
                "payment_method": sanitise(t.payment_method) or None, "status": sanitise(t.status),
                "geo": sanitise(t.geo) or None, "source": sanitise(t.source)}

    # ------------------------------------------------------------------ the ten tools
    def get_transaction_details(self, transaction_id: str) -> dict:
        t = self._txn(transaction_id)
        d = self._public(t)
        missing = [k for k in ("merchant_id", "device_id", "instrument_id", "geo", "payment_method") if d[k] is None]
        return {"transaction": d, "missing_fields": missing, "data_provenance": d["source"],
                "evidence_ids": [eid("txn", t.external_id), eid("acct", t.account_id)]}

    def get_account_history(self, account_id: str) -> dict:
        rows = self._account_rows(account_id)
        amounts = np.array([r.amount for r in rows])
        recent = rows[-HISTORY_LIMIT:][::-1]
        levels = {a.txn_external_id: a.risk_level for a in
                  self.s.query(RiskAssessmentRow).filter(
                      RiskAssessmentRow.business_id == self.biz,
                      RiskAssessmentRow.txn_external_id.in_([r.external_id for r in recent]))}
        return {
            "account_id": sanitise(account_id),
            "summary": {"n_transactions": len(rows), "mean_amount": float(amounts.mean()),
                        "median_amount": float(np.median(amounts)), "max_amount": float(amounts.max()),
                        "first_ts": _iso(rows[0].ts), "last_ts": _iso(rows[-1].ts)},
            "recent": [{"external_id": sanitise(r.external_id), "ts": _iso(r.ts), "amount": float(r.amount),
                        "merchant_id": sanitise(r.merchant_id) or None, "status": sanitise(r.status),
                        "risk_level": levels.get(r.external_id)} for r in recent],
            "evidence_ids": [eid("acct", account_id)] + [eid("txn", r.external_id) for r in recent]}

    def get_transaction_risk(self, transaction_id: str) -> dict:
        t = self._txn(transaction_id)
        a = self._assessment(t.external_id)
        if a is None:
            raise NotFound("no risk assessment")
        d = a.details or {}
        alert = self.s.query(Alert).filter_by(business_id=self.biz, txn_external_id=t.external_id).one_or_none()
        ids = [eid("txn", t.external_id), eid("assessment", t.external_id)]
        if alert:
            ids.append(f"alert:{alert.id}")
        return {"transaction_id": sanitise(t.external_id), "risk_score": a.risk_score, "risk_level": a.risk_level,
                "recommended_action": a.action,
                "calibrated_fraud_probability": a.calibrated_fraud_probability,
                "risk_factors": [sanitise(f, 120) for f in (a.factors or [])],
                "component_inputs": d.get("inputs", {}), "behaviour_reasons": d.get("behaviour_reasons", []),
                "cluster_id": d.get("cluster_id"), "scored_late": bool(d.get("late", False)),
                "model_version": sanitise(a.model_version), "policy_version": sanitise(a.policy_version),
                "alert": None if alert is None else {"id": alert.id, "status": alert.status, "level": alert.level},
                "note": "risk_score is a composite score; only calibrated_fraud_probability is a model probability. "
                        "Neither is a confirmed outcome.",
                "evidence_ids": ids}

    def _replay(self, rows):
        eng = BehaviourEngine()
        return eng, eng.replay(self._frame(rows))

    def get_behavioural_profile(self, account_id: str) -> dict:
        rows = self._account_rows(account_id)
        eng, _ = self._replay(rows)
        p = eng.profile(rows[0].account_id)
        p["known_merchants"] = [sanitise(m) for m in p["known_merchants"][:25]]
        return {"account_id": sanitise(account_id), "n_transactions": len(rows), "profile": p,
                "evidence_ids": [eid("acct", account_id)]}

    def _behaviour_for(self, t: Transaction) -> dict:
        rows = [r for r in self._account_rows(t.account_id) if (r.ts, r.external_id) <= (t.ts, t.external_id)]
        _, ind = self._replay(rows)
        row = ind[self._frame(rows)["external_id"] == t.external_id].iloc[-1]
        return {"reasons": [sanitise(r, 160) for r in row["reasons"]], "n_history": int(row["n_history"]),
                "deviation_score": float(row["deviation_score"])}

    def get_related_accounts(self, account_id: str) -> dict:
        mine = self._account_rows(account_id)
        devices = {r.device_id for r in mine if r.device_id}
        merchants = {r.merchant_id for r in mine if r.merchant_id}
        q = self.s.query(Transaction).filter(Transaction.business_id == self.biz,
                                             Transaction.account_id != account_id)
        others = [r for r in q.all() if (r.device_id in devices) or (r.merchant_id in merchants)]
        my_by_merchant: dict = {}
        for r in mine:
            if r.merchant_id:
                my_by_merchant.setdefault(r.merchant_id, []).append(r)
        links: dict[str, list] = {}
        shared: dict[tuple, list] = {}
        pairs: dict[tuple, list] = {}
        for o in others:
            if o.device_id in devices:
                shared.setdefault((o.account_id, o.device_id), []).append(o.external_id)
            for m in my_by_merchant.get(o.merchant_id, ()):
                if abs((pd.Timestamp(o.ts) - pd.Timestamp(m.ts)).total_seconds()) <= CO_MERCHANT_SECS:
                    pairs.setdefault((o.account_id, o.merchant_id), []).append(o.external_id)
        for (acct, dev), tx in shared.items():
            links.setdefault(acct, []).append({"type": "shared_device", "device_id": sanitise(dev),
                                               "txn_ids": [sanitise(x) for x in tx[:5]]})
        for (acct, mer), tx in pairs.items():
            if len(tx) >= 2:  # a single coincidence is not a relationship
                links.setdefault(acct, []).append({"type": "co_merchant_burst", "merchant_id": sanitise(mer),
                                                   "pairs": len(tx), "txn_ids": [sanitise(x) for x in sorted(set(tx))[:5]]})
        related = sorted(({"account_id": sanitise(a), "links": l} for a, l in links.items()),
                         key=lambda r: (-len(r["links"]), r["account_id"]))[:20]
        ids = [eid("acct", account_id)] + [eid("acct", r["account_id"]) for r in related] + \
              [eid("txn", x) for r in related for l in r["links"] for x in l["txn_ids"]]
        return {"account_id": sanitise(account_id), "related": related,
                "note": "A shared device or merchant is a relationship to examine, not evidence of wrongdoing.",
                "evidence_ids": list(dict.fromkeys(ids))}

    def get_graph_cluster(self, cluster_id: str) -> dict:
        a = (self.s.query(RiskAssessmentRow).filter(
            RiskAssessmentRow.business_id == self.biz,
            RiskAssessmentRow.details["cluster_id"].as_string() == cluster_id)
            .order_by(RiskAssessmentRow.id.desc()).first())
        if a is None:
            raise NotFound(cluster_id)
        t = self._txn(a.txn_external_id)
        lo = pd.Timestamp(t.ts) - pd.Timedelta(seconds=CLUSTER_LOOKBACK_SECS)
        rows = [r for r in self.s.query(Transaction).filter(Transaction.business_id == self.biz,
                                                             Transaction.ts >= lo.to_pydatetime(),
                                                             Transaction.ts <= pd.Timestamp(t.ts).to_pydatetime()).all()]
        for c in find_clusters(self._frame(rows)):
            if c.cluster_id == cluster_id:
                ids = [eid("cluster", c.cluster_id)] + [eid("acct", x) for x in c.accounts[:20]] + \
                      [eid("txn", x) for x in c.txn_ids[:50]]
                return {"cluster_id": c.cluster_id, "accounts": [sanitise(x) for x in c.accounts],
                        "devices": [sanitise(x) for x in c.devices], "merchants": [sanitise(x) for x in c.merchants],
                        "signals": c.signals, "flagged": c.flagged, "risk_indicator": c.risk_indicator,
                        "density": c.density,
                        "evidence": {k: (sanitise(v) if isinstance(v, str) else v) for k, v in c.evidence.items()
                                     if k != "shared_devices"},
                        "evidence_transactions": [sanitise(x) for x in c.txn_ids[:50]],
                        "note": "Member accounts can include accounts that are only loosely attached; the "
                                "evidence transactions are the reliable part.",
                        "evidence_ids": ids}
        raise NotFound(cluster_id)

    def get_model_explanation(self, transaction_id: str) -> dict:
        if self.ctx is None or getattr(self.ctx, "bundle", None) is None:
            raise ToolUnavailable("no model is loaded, so explanations are unavailable")
        t = self._txn(transaction_id)
        q = self.s.query(Transaction).filter(Transaction.business_id == self.biz,
                                             Transaction.ts <= t.ts)
        rows = [r for r in q.filter((Transaction.account_id == t.account_id)
                                    | (Transaction.merchant_id == t.merchant_id)
                                    | (Transaction.device_id == t.device_id)).all()
                if r.account_id == t.account_id or (t.merchant_id and r.merchant_id == t.merchant_id)
                or (t.device_id and r.device_id == t.device_id)]
        frame = self._frame(rows)
        feats = build_features(frame)
        row = feats[frame["external_id"] == t.external_id].iloc[0]
        out = explain_transaction(self.ctx.bundle, row, top_k=5)
        out["contributions"] = [{**c, "value": float(c["value"]), "shap": float(c["shap"])} for c in out["contributions"]]
        return {**out, "transaction_id": sanitise(t.external_id),
                "evidence_ids": [eid("txn", t.external_id), eid("assessment", t.external_id)]}

    def get_recent_alerts(self) -> dict:
        alerts = (self.s.query(Alert).filter_by(business_id=self.biz).order_by(Alert.id.desc()).limit(20).all())
        by_txn = {a.txn_external_id: a for a in self.s.query(RiskAssessmentRow).filter(
            RiskAssessmentRow.business_id == self.biz,
            RiskAssessmentRow.txn_external_id.in_([a.txn_external_id for a in alerts]))}
        out = [{"alert_id": a.id, "transaction_id": sanitise(a.txn_external_id), "level": a.level, "status": a.status,
                "risk_score": getattr(by_txn.get(a.txn_external_id), "risk_score", None)} for a in alerts]
        return {"alerts": out, "evidence_ids": [f"alert:{a['alert_id']}" for a in out] +
                [eid("txn", a["transaction_id"]) for a in out]}

    def compare_transactions(self, transaction_ids: list[str]) -> dict:
        txns = [self._txn(i) for i in transaction_ids]
        ordered = sorted(txns, key=lambda t: (t.ts, t.external_id))
        clusters = []
        for t in ordered:
            a = self._assessment(t.external_id)
            clusters.append((a.details or {}).get("cluster_id") if a else None)
        steps = []
        for (a, ca), (b, cb) in zip(zip(ordered, clusters), list(zip(ordered, clusters))[1:]):
            steps.append({"from": sanitise(a.external_id), "to": sanitise(b.external_id),
                          "gap_seconds": (pd.Timestamp(b.ts) - pd.Timestamp(a.ts)).total_seconds(),
                          "same_account": a.account_id == b.account_id,
                          "same_device": bool(a.device_id) and a.device_id == b.device_id,
                          "same_merchant": bool(a.merchant_id) and a.merchant_id == b.merchant_id,
                          "amount_ratio": float(b.amount / a.amount) if a.amount else None,
                          "same_cluster": ca is not None and ca == cb})
        return {"transactions": [self._public(t) for t in ordered], "consecutive_comparisons": steps,
                "summary": {"all_same_account": len({t.account_id for t in ordered}) == 1,
                            "all_same_device": len({t.device_id for t in ordered}) == 1 and ordered[0].device_id is not None,
                            "all_same_merchant": len({t.merchant_id for t in ordered}) == 1 and ordered[0].merchant_id is not None,
                            "time_span_seconds": (pd.Timestamp(ordered[-1].ts) - pd.Timestamp(ordered[0].ts)).total_seconds()},
                "evidence_ids": list(dict.fromkeys(eid("txn", t.external_id) for t in ordered))}

    def generate_investigation_report(self, transaction_id: str) -> dict:
        tx = self.get_transaction_details(transaction_id)
        risk = self.get_transaction_risk(transaction_id)
        t = self._txn(transaction_id)
        evidence: set[str] = set(tx["evidence_ids"]) | set(risk["evidence_ids"])
        txn_id, assess_id = eid("txn", t.external_id), eid("assessment", t.external_id)

        def finding(claim, ids):
            evidence.update(ids)
            return {"claim": claim, "evidence_ids": list(ids)}

        model, behaviour, graph, support, contra, missing = [], [], [], [], [], []
        p = risk["calibrated_fraud_probability"]
        model.append(finding(f"The model's fraud probability for this transaction is {p:.2f} "
                             f"(risk level {risk['risk_level']}, composite score {risk['risk_score']:.2f}).",
                             [txn_id, assess_id]))
        try:
            ex = self.get_model_explanation(transaction_id)
            for c in ex["contributions"][:3]:
                model.append(finding(f"{c['feature']} = {c['value']:.2f} moved the model score by {c['shap']:+.2f} "
                                     "(describes the model, not a cause).", ex["evidence_ids"]))
        except ToolUnavailable:
            missing.append("Model explanation unavailable: no model is loaded.")

        beh = self._behaviour_for(t)
        if beh["n_history"] < 5:
            behaviour.append(finding("The account has too little history to establish a behavioural baseline.",
                                     [eid("acct", t.account_id), txn_id]))
        for reason in beh["reasons"]:
            behaviour.append(finding(reason, [eid("acct", t.account_id), txn_id]))
        if beh["n_history"] >= 5 and not beh["reasons"]:
            behaviour.append(finding("No deviation from the account's established behaviour was recorded.",
                                     [eid("acct", t.account_id), txn_id]))

        cid = risk["cluster_id"]
        if cid:
            try:
                cl = self.get_graph_cluster(cid)
                graph.append(finding(f"The transaction belongs to cluster {cl['cluster_id']} with signals "
                                     f"{', '.join(cl['signals'])} (flagged={cl['flagged']}).",
                                     [eid("cluster", cid), txn_id]))
            except NotFound:
                graph.append(finding(f"The assessment references cluster {sanitise(cid)}, which could not be "
                                     "re-derived from current data.", [assess_id]))
        else:
            graph.append(finding("No flagged cluster contains this transaction.", [txn_id]))
        rel = self.get_related_accounts(t.account_id)
        if rel["related"]:
            graph.append(finding(f"{len(rel['related'])} other account(s) are linked to this account through shared "
                                 "devices or same-merchant payments within minutes.",
                                 [eid("acct", t.account_id)] + [eid("acct", r["account_id"]) for r in rel["related"][:5]]))

        for f in risk["risk_factors"]:
            support.append(finding(f, [assess_id]))
        inputs = risk["component_inputs"]
        if risk["risk_level"] in HIGH_PLUS and p < 0.2:
            contra.append(finding(f"The model probability is low ({p:.2f}); the elevated risk comes from other signals.", [assess_id]))
        if risk["risk_level"] in HIGH_PLUS and inputs.get("behaviour", 0) == 0 and beh["n_history"] >= 5:
            contra.append(finding("No behavioural deviation was recorded for this transaction.", [txn_id]))
        if risk["risk_level"] == "LOW" and (inputs.get("anomaly", 0) > 0.8 or beh["reasons"]):
            contra.append(finding("Some anomaly signals are present even though the overall risk is low.", [assess_id]))

        for f in tx["missing_fields"]:
            missing.append(f"{f} is not available from source '{tx['data_provenance']}'.")
        missing.append("No confirmed outcome (chargeback or customer confirmation) is available: this is a suspicion, not a verdict.")

        steps = {"ALLOW": "No action required; keep routine monitoring.",
                 "MONITOR": "Watch the account and re-score after its next transactions.",
                 "REVIEW": "Analyst review of this transaction and the linked accounts; contact the customer if appropriate.",
                 "VERIFY": "Request additional verification from the account holder before further activity.",
                 "HOLD_RECOMMENDED": "A temporary hold is recommended for analyst approval; nothing is executed automatically."}
        independent = int(inputs.get("ml_prob", 0) >= 0.5) + int(inputs.get("graph", 0) >= 0.5) + int(inputs.get("behaviour", 0) >= 0.5)
        level = "high" if risk["risk_level"] in HIGH_PLUS and independent >= 2 else \
                "medium" if risk["risk_level"] in HIGH_PLUS or independent >= 1 else "low"
        classification = ("suspicious" if risk["risk_level"] in HIGH_PLUS else
                          "insufficient_evidence" if risk["risk_level"] == "MODERATE" else "likely_legitimate")
        return {
            "case_id": f"CASE-{sanitise(t.external_id, 40)}", "transaction": tx["transaction"],
            "risk_assessment": {k: risk[k] for k in ("risk_score", "risk_level", "recommended_action",
                                                     "calibrated_fraud_probability", "risk_factors")},
            "model_findings": model, "behavioural_findings": behaviour, "graph_findings": graph,
            "supporting_evidence": support, "contradictory_evidence": contra, "missing_information": missing,
            "recommended_next_steps": [steps[risk["recommended_action"]]],
            "confidence": {"level": level, "limitations": [
                "Scores are model-based suspicion, not a confirmed outcome.",
                "Training and demo data are synthetic; behaviour on real traffic is unmeasured.",
                "Cluster membership can include loosely attached accounts."]},
            "classification": classification, "llm_narrative": False,
            "evidence_ids": sorted(evidence)}
