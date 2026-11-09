"""Investigation report model and the guards that keep an LLM-written narrative honest.

The facts in a report (transaction, risk assessment) always come from the deterministic tools.
The model only writes the narrative parts, and `validate_citations` rejects a narrative that
  * cites an evidence id no tool returned, or a finding with no evidence at all,
  * claims confirmed fraud (the system only ever has suspicion), or
  * classifies against the deterministic risk level (a HIGH/CRITICAL transaction cannot be
    called 'likely_legitimate', a LOW one cannot be called 'suspicious') - so text injected into
    a transaction field cannot talk the report into a different verdict.
"""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

Classification = Literal["suspicious", "insufficient_evidence", "likely_legitimate"]
SECTIONS = ("model_findings", "behavioural_findings", "graph_findings", "supporting_evidence",
            "contradictory_evidence")
# "confirmed fraud" / "is fraudulent" - but not "not confirmed fraud" / "unconfirmed fraud"
FORBIDDEN_CLAIM = re.compile(r"(?<!not )(?<!un)confirmed fraud|\b(?:is|are|was|were) (?:clearly |definitely |certainly )?fraudulent"
                             r"|committed fraud", re.I)
ALLOWED_BY_LEVEL = {"LOW": {"likely_legitimate", "insufficient_evidence"},
                    "MODERATE": {"suspicious", "insufficient_evidence", "likely_legitimate"},
                    "HIGH": {"suspicious", "insufficient_evidence"},
                    "CRITICAL": {"suspicious", "insufficient_evidence"}}
_UNSUPPORTED_SCHEMA_KEYS = {"minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum",
                            "pattern", "default", "title"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Finding(_Strict):
    claim: str
    evidence_ids: list[str]


class Confidence(_Strict):
    level: Literal["low", "medium", "high"]
    limitations: list[str]


class NarrativePart(_Strict):
    """What the language model is asked to write."""
    summary: str
    model_findings: list[Finding]
    behavioural_findings: list[Finding]
    graph_findings: list[Finding]
    supporting_evidence: list[Finding]
    contradictory_evidence: list[Finding]
    missing_information: list[str]
    recommended_next_steps: list[str]
    confidence: Confidence
    classification: Classification


class InvestigationReport(_Strict):
    case_id: str
    transaction: dict
    risk_assessment: dict
    summary: str = ""
    model_findings: list[Finding]
    behavioural_findings: list[Finding]
    graph_findings: list[Finding]
    supporting_evidence: list[Finding]
    contradictory_evidence: list[Finding]
    missing_information: list[str]
    recommended_next_steps: list[str]
    confidence: Confidence
    classification: Classification
    llm_narrative: bool
    evidence_ids: list[str]
    notes: list[str] = []


def narrative_json_schema() -> dict:
    """The NarrativePart schema without validators the structured-output API does not accept
    (local pydantic validation still enforces them)."""
    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in _UNSUPPORTED_SCHEMA_KEYS}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node
    return strip(NarrativePart.model_json_schema())


def violations(part, retrieved_ids: set[str], risk_level: str | None = None) -> list[str]:
    out = []
    for section in SECTIONS:
        for f in getattr(part, section):
            if not f.evidence_ids:
                out.append(f"{section}: the finding '{f.claim[:60]}' has no evidence ids")
            for e in f.evidence_ids:
                if e not in retrieved_ids:
                    out.append(f"{section}: cites {e}, which no tool returned")
    texts = [part.summary, *part.missing_information, *part.recommended_next_steps,
             *part.confidence.limitations] + [f.claim for s in SECTIONS for f in getattr(part, s)]
    for t in texts:
        if FORBIDDEN_CLAIM.search(t):
            out.append(f"claims fraud as established ('{t[:60]}'); only suspicion is known")
    if risk_level in ALLOWED_BY_LEVEL and part.classification not in ALLOWED_BY_LEVEL[risk_level]:
        out.append(f"classification '{part.classification}' contradicts the deterministic risk level {risk_level}")
    return out


def violation_kinds(problems: list[str]) -> str:
    """Describe problems by kind only, so rejected model output is never echoed into a report."""
    kinds = {"which no tool returned": "evidence the tools never returned",
             "has no evidence ids": "findings without evidence",
             "claims fraud": "fraud asserted as established",
             "contradicts the deterministic": "classification contradicting the risk level",
             "did not match the report schema": "output in the wrong format"}
    found = [label for key, label in kinds.items() if any(key in p for p in problems)]
    return ", ".join(found) or "invalid content"


def validate_citations(report: InvestigationReport, retrieved_ids: set[str]) -> list[str]:
    return violations(report, retrieved_ids, report.risk_assessment.get("risk_level"))
