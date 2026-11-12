# Devpost submission draft

Copy each section into the matching field. Everything here is taken from measured results in `PROJECT_PROGRESS.md`;
edit the voice freely, but keep the numbers and the caveats together.

**Project name:** SENTINEL AI

**Tagline:** Payment-fraud intelligence you can audit: every score explained, every AI claim cited, every action decided by a human.

**Repository:** https://github.com/dharunprasath720-cmd/sentinel_ai

**Demo video:** (paste your public YouTube link)

---

## Inspiration

Fraud tools tend to fail in one of two ways: a black box that blocks customers with no explanation, or a pile of alerts
nobody can work through. I wanted to see how far a small system could go if it had to show its reasoning at every step,
and if an AI assistant were only allowed to say what it could prove.

## What it does

SENTINEL AI scores payments as they arrive and helps an analyst decide what to do about them.

- **Scores every payment** from seven signals: a calibrated model probability, an anomaly score, behaviour against the
  account's own baseline, graph relationships, velocity, account history and merchant history. The combination is plain
  arithmetic from a versioned policy file, so the same inputs always give the same answer.
- **Finds coordinated rings.** Accounts that share a device, pay the same merchant and act within minutes are clustered
  and flagged.
- **Explains itself.** Named risk factors, SHAP contributions for the model, and the linked accounts.
- **Takes real PayPal Sandbox payments.** A `PAYMENT.CAPTURE.COMPLETED` webhook is verified with PayPal's signature
  verification API before it is trusted, then scored like any other payment and shown live in the dashboard.
- **Investigates with Claude.** An AI investigator answers questions and writes case reports using ten read-only tools.
  Every claim must cite an evidence id the tools actually returned. Replies that state fraud as fact, or claim an action
  was taken, are withheld.
- **Leaves the decision to a person.** Actions are recommendations only. Nothing is blocked automatically, and every
  analyst action is written to an append-only audit log.

The dashboard has five pages: Overview, Live Monitoring, Investigation Workspace, Graph Explorer and AI Investigator.

**How AG Grid is used.** Fraud triage is a table problem, so the two places an analyst actually works are AG Grid tables. The live feed receives scored events as row updates keyed by transaction id, so an analyst can sort, filter any column or search while new events keep streaming in, and the view does not reset. Each row carries an in-cell risk bar and a severity badge, HIGH and CRITICAL rows are highlighted, and the filtered view exports to CSV. In Investigation, open alerts appear in a triage grid: sort by severity, filter, tick several rows and open a single case from the selection. Only the free Community edition is used.

## How PayPal is used

- **OAuth 2.0** client-credentials tokens against the Sandbox.
- **Orders v2**: create and capture an order (exercised with a real Sandbox buyer approval).
- **Webhooks**: `PAYMENT.CAPTURE.COMPLETED` delivered to the app, verified through
  `POST /v1/notifications/verify-webhook-signature` using the exact bytes received. Only a literal `SUCCESS` is accepted;
  the certificate URL must be an https `paypal.com` host; duplicates are dropped by event id.
- The capture webhook carries no payer identity, so an unlinked payment is scored as its own account instead of being
  merged into someone else's history. PayPal data is kept in its own partition and never blended with synthetic data.
- Refunds are implemented in the client but were never run, and I say so in the README.

## How AI is used

- **Claude (`claude-opus-5-5`) as the investigator.** It can only call read-only, business-scoped tools, never supplies a
  business id, and cannot see the ground-truth label. Its output is checked: uncited claims, fraud-as-fact and
  "action taken" statements are rejected, with one corrective retry and then a deterministic evidence-cited fallback.
- **Machine learning for scoring:** logistic regression, LightGBM and Isolation Forest, with probability calibration chosen
  on a validation slice, and SHAP for explanations.
- **Graph analysis:** NetworkX with Louvain community detection for shared-device and common-merchant clusters.

## How I built it

Python 3.11 with FastAPI, SQLAlchemy and SQLite on the backend; React, TypeScript, Vite, Recharts and React Flow on the
frontend, served by the same process. One feature extractor serves training, batch scoring and live scoring, and features
only ever use history from before the event, which prevents the model from seeing the future. The live stream uses
Server-Sent Events read with `fetch`, so the access token never goes in a URL.

The project was built during the hackathon, test-first: 412 backend tests and 120 frontend tests.

## Results (synthetic data)

Measured on a synthetic demo world of 500 accounts over 30 days with 1.99% fraud, split chronologically. These are
numbers on data I designed, not a guarantee on real traffic.

- LightGBM on its held-out slice: PR-AUC 0.739, recall 0.479, precision 0.767.
- Full pipeline on validation and test rows: 79% of fraud reached HIGH or above, with 89% precision at that level and no
  hold recommended on any non-fraud row.
- All five planted rings were flagged, with no flagged cluster lacking a ring account.
- Live scoring latency: p50 81 ms, p95 162 ms on a quiet laptop.

## Challenges

- **Honest evaluation.** My first synthetic data was too easy (PR-AUC 1.000). I made fraud overlap normal behaviour and
  added legitimate shared devices and flash sales, and the numbers dropped to the ones above.
- **Bugs that only real integrations exposed.** The first live chat call failed because a tool schema used a validator
  the API rejects; the first real webhook showed the capture event has no payer identity; filming the demo showed that
  live-flagged clusters could not be opened in the graph view. Each was fixed with a test that failed first.
- **Keeping the AI honest.** Simple keyword filters for "fraud" were easy to get around, so claim detection works at
  sentence level and applies to chat as well as reports.

## What I'm proud of

Independent reviews of the whole codebase after each stage, and a README table that says exactly what was and was not
verified, including the parts that are untested.

## Limits

About a fifth of planted fraud is missed (bursts that look legitimate, and the first ring payments before the pattern
exists). The data is synthetic. PayPal is Sandbox only. SQLite, no rate limiting, and a single process: this is a
hackathon prototype, not a production system.

## What's next

An approved-case refund workflow through PayPal, evaluation on a public dataset, per-IP rate limiting, and Postgres.

---

## Tools used (for the "Tools" field)

| Tool | How it was used |
|---|---|
| **PayPal Developer Platform (Sandbox)** | OAuth, Orders v2 create and capture, `PAYMENT.CAPTURE.COMPLETED` webhooks with signature verification |
| **Claude Opus 5.5 (Anthropic API)** | The in-product AI investigator: tool-using reports and chat, grounded in retrieved evidence |
| **Claude Code** | AI coding assistant used to write, test and review the project's code and documentation |
| **LightGBM, scikit-learn, SHAP** | Fraud probability model, baselines, anomaly detection, calibration and explanations |
| **NetworkX** | Account, device and merchant graph; cluster detection |
| **FastAPI, SQLAlchemy, SQLite** | API, persistence |
| **AG Grid Community (MIT)** | The analyst's working surface: the live event feed (streaming rows keyed by transaction id, so filters and sort survive new events, in-cell risk bars, quick search, CSV export of the filtered view) and the alert triage grid (multi-select rows, open one case from the selection). Free tier only; no Enterprise features |
| **React, TypeScript, Vite, Recharts, React Flow, Framer Motion** | Dashboard |
| **Playwright, ffmpeg** | Scripted, captioned demo recording |
| **cloudflared** | Public tunnel so PayPal Sandbox could reach the local webhook during testing |

**"Built with" tags:** python, fastapi, react, typescript, paypal, claude, anthropic, lightgbm, scikit-learn, shap, networkx, sqlite, vite, ag-grid

## Run instructions (if the form asks)

See the Quick start in the repository README: create a Python 3.11 environment, `pip install -r requirements.txt`,
`npm install --prefix frontend`, `npm run build --prefix frontend`, then `python scripts/serve.py` and open
http://127.0.0.1:8000/. Demo logins are generated into `.env.demo`. No API keys are needed to run it; an Anthropic key
turns on the AI narrative and chat, and PayPal Sandbox keys turn on the webhook.
