"""Deterministic risk scoring and decision policy (no LLM, no randomness).

Normalisation: each input is a value in [0, 1]. Model/anomaly/graph/behaviour inputs are
already in range; velocity, account and merchant history are converted with `Normaliser`
(percentile rank against the TRAINING distribution).
Combination: risk_score = sum(weight_i * input_i), weights from policy.yaml (sum 1).
Levels: score >= critical|high|moderate thresholds. Cap: unless ml_prob or graph reaches
`strong_source_min`, the level cannot exceed `single_source_cap` (an anomaly alone is never
proof). Actions are recommendations only; HOLD_RECOMMENDED needs CRITICAL + a flagged cluster.
"""
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

DEFAULT_POLICY_PATH = Path(__file__).with_name("policy.yaml")
LEVELS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
COMPONENTS = ["ml_prob", "anomaly", "behaviour", "graph", "velocity", "account_history",
              "merchant_risk"]
FACTOR_TEXT = {
    "ml_prob": "High model fraud probability",
    "anomaly": "Unusual transaction pattern (anomaly score)",
    "behaviour": "Behavioural deviation from the account's baseline",
    "graph": "Suspicious account relationships",
    "velocity": "Unusual transaction frequency",
    "account_history": "Account has prior high-risk activity",
    "merchant_risk": "Merchant shows elevated risk indicators",
}
FACTOR_MIN_SHARE = 0.25


@dataclass
class Policy:
    version: str
    weights: dict
    thresholds: dict
    single_source_cap: str = "HIGH"
    hold_requires_cluster: bool = True
    strong_source_min: float = 0.5


def _number(value, name: str) -> float:
    """Strictly a finite number: no strings, bools, NaN or inf (NaN would silently turn every
    decision into ALLOW because every comparison with NaN is False)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def load_policy(path: Path) -> Policy:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        weights = {k: _number(v, f"weight '{k}'") for k, v in raw["weights"].items()}
        th = {k: _number(v, f"threshold '{k}'") for k, v in raw["thresholds"].items()}
        strong = _number(raw["strong_source_min"], "strong_source_min")
        hold = raw["hold_requires_cluster"]
        if not isinstance(hold, bool):
            raise ValueError(f"hold_requires_cluster must be true or false, got {hold!r}")
        policy = Policy(version=str(raw["version"]), weights=weights, thresholds=th,
                        single_source_cap=str(raw["single_source_cap"]),
                        hold_requires_cluster=hold, strong_source_min=strong)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"policy file is missing or malformed: {exc!r}") from exc
    if not 0 < strong <= 1:
        raise ValueError(f"strong_source_min must be in (0, 1], got {strong}")
    if set(weights) != set(COMPONENTS):
        raise ValueError(f"weights must be exactly {COMPONENTS}, got {sorted(weights)}")
    if abs(sum(weights.values()) - 1.0) > 1e-6 or min(weights.values()) < 0:
        raise ValueError(f"weights must be non-negative and sum to 1.0 (sum={sum(weights.values())})")
    if set(th) != {"moderate", "high", "critical"}:
        raise ValueError("thresholds must be exactly moderate, high, critical")
    if not 0 < th["moderate"] < th["high"] < th["critical"] < 1:
        raise ValueError(f"thresholds must be strictly increasing within (0, 1): {th}")
    if policy.single_source_cap not in LEVELS:
        raise ValueError(f"single_source_cap must be one of {LEVELS}")
    return policy


@dataclass
class RiskInputs:
    ml_prob: float
    anomaly: float
    behaviour: float
    graph: float
    velocity: float
    account_history: float
    merchant_risk: float
    cluster_flagged: bool = False

    def __post_init__(self):
        for name in COMPONENTS:
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {v}")


@dataclass
class RiskAssessment:
    risk_score: float
    risk_level: str
    recommended_action: str
    calibrated_fraud_probability: float
    risk_factors: list[str] = field(default_factory=list)
    contributions: dict = field(default_factory=dict)
    policy_version: str = ""


class Normaliser:
    """Percentile rank against a fitted (training) distribution, output in [0, 1]."""
    def __init__(self, sorted_values: np.ndarray):
        self._v = sorted_values

    @classmethod
    def fit(cls, values) -> "Normaliser":
        v = np.sort(np.asarray(values, dtype=float))
        if len(v) == 0:
            raise ValueError("cannot fit a Normaliser on no values")
        return cls(v)

    def transform(self, x: float, strict: bool = False) -> float:
        """Share of training values <= x, or strictly < x when `strict` (use strict for
        tie-heavy counts, where 0 is typical and must map to 0, not to ~0.9)."""
        side = "left" if strict else "right"
        return float(np.searchsorted(self._v, x, side=side) / len(self._v))


class RiskEngine:
    def __init__(self, policy: Policy):
        self.policy = policy

    def assess(self, x: RiskInputs) -> RiskAssessment:
        p = self.policy
        contributions = {c: p.weights[c] * getattr(x, c) for c in COMPONENTS}
        score = float(sum(contributions.values()))
        th = p.thresholds
        level = ("CRITICAL" if score >= th["critical"] else "HIGH" if score >= th["high"]
                 else "MODERATE" if score >= th["moderate"] else "LOW")
        if max(x.ml_prob, x.graph) < p.strong_source_min:
            level = LEVELS[min(LEVELS.index(level), LEVELS.index(p.single_source_cap))]
        if level == "CRITICAL":
            action = ("HOLD_RECOMMENDED" if x.cluster_flagged or not p.hold_requires_cluster
                      else "VERIFY")
        else:
            action = {"LOW": "ALLOW", "MODERATE": "MONITOR", "HIGH": "REVIEW"}[level]
        factors = []
        if score > 0:
            ranked = sorted(contributions.items(), key=lambda kv: -kv[1])
            factors = [FACTOR_TEXT[c] for c, v in ranked if v / score >= FACTOR_MIN_SHARE]
        return RiskAssessment(risk_score=score, risk_level=level, recommended_action=action,
                              calibrated_fraud_probability=x.ml_prob, risk_factors=factors,
                              contributions=contributions, policy_version=p.version)


def calibrate_thresholds(scores, review_budget_frac: float) -> dict:
    """Thresholds from validation risk scores and the analyst review budget: HIGH flags the
    budget fraction, CRITICAL a quarter of it, MODERATE max(10%, 4x budget). Strictly increasing."""
    s = np.asarray(scores, dtype=float)
    rates = {"moderate": min(0.5, max(0.10, 4 * review_budget_frac)),
             "high": review_budget_frac, "critical": review_budget_frac / 4}
    out, prev = {}, 0.0
    for name in ("moderate", "high", "critical"):
        t = float(np.quantile(s, 1 - rates[name]))
        out[name] = max(t, prev + 1e-6)
        prev = out[name]
    return out


def threshold_report(scores, labels, thresholds: dict) -> dict:
    """Operational view of each threshold on labelled data: volume, precision, recall."""
    s, y = np.asarray(scores, dtype=float), np.asarray(labels).astype(int)
    out = {}
    for name, t in thresholds.items():
        flagged = s >= t
        n = int(flagged.sum())
        out[name] = {"n": n, "rate": n / len(s) if len(s) else 0.0,
                     "precision": float(y[flagged].mean()) if n else None,
                     "recall": float(y[flagged].sum() / y.sum()) if y.sum() else None}
    return out
