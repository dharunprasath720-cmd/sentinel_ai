# SENTINEL AI — Architecture

SENTINEL is a modular monolith: one FastAPI process with strict package boundaries, a React dashboard
served by the same process, and optional Claude and PayPal Sandbox integrations. The diagrams below are
Mermaid and render on GitHub. Where a diagram shows a safety rule, the code that enforces it is named.

## 1. System overview

```mermaid
flowchart LR
  subgraph Sources["Data sources (never blended)"]
    SYN["synthetic"]
    PSM["paysim"]
    PPS["paypal_sandbox"]
  end
  PPW["PayPal webhook"] --> VER["signature verification"]
  VER --> PPS
  Sources --> ING["ingestion: validate, normalise, dedup"]
  ING --> DB[("SQLAlchemy DB: SQLite, Postgres via DATABASE_URL")]
  ING --> FE["features: point-in-time extractor"]
  FE --> ML["models: calibrated probability, anomaly score"]
  FE --> BEH["behaviour: per-account baselines"]
  FE --> GR["graph: shared devices and merchants, clusters"]
  ML --> RISK["risk: deterministic score and policy"]
  BEH --> RISK
  GR --> RISK
  RISK --> CASES["cases: alerts, cases, append-only audit"]
  CASES --> API["FastAPI: REST and SSE"]
  API --> UI["React dashboard, 5 pages"]
  UI --> AG["agent: Claude with 10 read-only tools"]
  AG -. "reads, never writes" .-> RISK
  AG -. reads .-> GR
  AG -. reads .-> BEH
  AG -. reads .-> ML
```

| Package (`backend/sentinel/`) | Responsibility |
|---|---|
| `ingestion/` | Schema, idempotent ingest with conflict detection, synthetic generator, PaySim loader |
| `features/` | The single feature extractor used by training, batch and live scoring (prevents training/serving skew) |
| `models/` | Logistic regression, LightGBM, Isolation Forest, calibration, SHAP, evaluation |
| `behaviour/` | Robust per-account baselines and deviation indicators |
| `graph/` | NetworkX account/device/merchant graph, Louvain clusters, four signals |
| `risk/` | Pure-Python deterministic scoring and `policy.yaml` (strictly validated) |
| `pipeline.py` | Two-pass, point-in-time batch scoring |
| `live/` | Incremental scorer, event bus, replay simulator |
| `paypal/` | Sandbox client (OAuth, orders, capture, refund) and webhook handling |
| `agent/` | Claude investigator: tools, report, chat, claim filters |
| `cases/` | Alerts, cases, notes, state machine, audit log |
| `dashboard/`, `api/` | Read-only dashboard queries; routes, auth, static serving |

## 2. What happens to one transaction

Batch and live scoring follow the same steps. Features use only history strictly before the event.

```mermaid
sequenceDiagram
  participant S as Source
  participant I as ingestion
  participant F as features
  participant M as models
  participant B as behaviour
  participant G as graph
  participant R as risk
  participant C as cases
  participant U as dashboard
  S->>I: raw event
  I->>I: validate, normalise, dedup on external_id
  I->>F: stored transaction
  F->>M: features from history before the event
  F->>B: same history
  F->>G: edges that existed before the event
  M->>R: calibrated probability, anomaly score
  B->>R: deviation indicators
  G->>R: cluster indicators
  R->>C: assessment with model and policy versions
  C->>C: create an alert at HIGH or above, write an audit entry
  C->>U: SSE event with the scoring latency
```

## 3. How the risk decision is made

```mermaid
flowchart TD
  IN["Seven inputs, each 0 to 1: model probability, anomaly, behaviour, graph, velocity, account history, merchant risk"] --> W["Weighted score from policy.yaml"]
  W --> CAP["Single-source cap: without a strong source (model probability or graph at least 0.5) the level stops at HIGH"]
  CAP --> LVL["Level: LOW, MODERATE, HIGH, CRITICAL"]
  LVL --> ACT["Recommended action: ALLOW, MONITOR, REVIEW, VERIFY, HOLD_RECOMMENDED"]
  CL["Flagged cluster"] --> ACT
  ACT --> HUM["Analyst approves or rejects. Nothing is executed automatically."]
```

- The score is arithmetic, not a model output. Only `calibrated_fraud_probability` is a probability, and the
  UI labels it that way. "Suspicious value" is the sum of HIGH and CRITICAL amounts, never a fraud loss.
- Weights are 0.35 model, 0.20 graph, 0.15 behaviour, 0.10 anomaly, 0.10 velocity, 0.05 account history,
  0.05 merchant risk. Level thresholds are 0.20 (MODERATE), 0.40 (HIGH) and 0.65 (CRITICAL).
- Anomaly, behaviour and velocity alone are never proof: without a strong source the level cannot exceed HIGH.
- `HOLD_RECOMMENDED` is only suggested for a CRITICAL transaction inside a flagged cluster (three or more of the
  four graph signals), never from a high score alone.
- The policy file is validated strictly: NaN, non-numeric or out-of-range values are rejected at load.

## 4. A real PayPal Sandbox payment

```mermaid
sequenceDiagram
  participant P as PayPal Sandbox
  participant T as public tunnel
  participant W as /paypal/webhook
  participant V as PayPal verify API
  participant L as live scorer
  participant D as dashboard
  P->>T: PAYMENT.CAPTURE.COMPLETED, signed
  T->>W: POST, raw body
  W->>W: size cap, certificate URL must be https on paypal.com
  W->>V: verify-webhook-signature with the exact received bytes
  V-->>W: SUCCESS or anything else
  W->>W: only a literal SUCCESS passes, duplicates dropped by event id
  W->>L: normalised event, account PAYPAL_UNLINKED plus capture id
  L->>L: score, store assessment, create alert if HIGH or above
  L->>D: SSE event, source paypal_sandbox
```

The capture webhook carries no payer identity, so an unlinked payment becomes its own pseudo-account instead of
being merged into one customer. PayPal events are scored in their own partition (see section 6).

## 5. The investigation agent's boundary

```mermaid
flowchart LR
  Q["Analyst question or report request"] --> LLM["Claude"]
  LLM -->|"tool calls, no business id"| TB["ToolBox: 10 read-only tools, scoped to the user's business"]
  TB -->|"results with evidence ids"| LLM
  LLM --> CHK["Checks: every claim cites an id the tools returned; no fraud-as-fact; no executed-action claims"]
  CHK -->|pass| OUT["Report or chat reply with citations"]
  CHK -->|"fail twice or no model"| DET["Deterministic evidence-cited report"]
```

- The model never supplies a business id and cannot reach the ground-truth label; tool errors are results, not crashes.
- A chat reply that states fraud as fact, or claims an action was taken, is withheld and shown as a notice.
- Without an API key the report still works (deterministic) and chat is off.

## 6. Data separation

Scorer state is partitioned by business and data source (`"{business}|{source}"`). Synthetic, PaySim and PayPal
Sandbox rows never share features, baselines, clusters or the "newest event" clock. The dashboard has a data
source selector, and every aggregate, list and graph is filtered by it. All per-entity state is keyed by
business, so two businesses with the same account ids never interact (pinned by a two-business pipeline test).

## 7. Deployment

One process: `python scripts/serve.py` serves the API, the SSE stream and the built dashboard from the same
address. PayPal needs a public URL for webhooks, so use a tunnel (cloudflared or ngrok). SQLite is the tested
database; Postgres is supported through `DATABASE_URL` but was not run. There is no Docker image yet.
