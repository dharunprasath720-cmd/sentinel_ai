# Day 4 dashboard — verification record (2026-11-11)

Run against `scripts/serve.py --port 8001` (the real demo database: 10,997 history rows, 8 flagged
clusters; Claude and PayPal Sandbox configured), in the built-in browser pane, on a build whose
unit suites were green at each step. Passwords and keys were never printed or stored in this file.

## Automated gates (final)
- Backend: `pytest` **407 passed** (379 before Day 4, +25 dashboard endpoints, +2 source filters, +1 tool-schema regression).
- Frontend: `vitest` **93 passed** in 15 files; `tsc --noEmit` clean; `npm run build` OK.

## Walked in the browser
| Check | Result |
|---|---|
| Wrong password | "Invalid or missing credentials", stays on login |
| Login as analyst | Overview: 10,997 transactions, 160 open alerts, 8 flagged clusters, model panel with recall next to PR-AUC and the held-out caveat |
| Live Monitoring + replay | Stream "Connected"; events arrive on top; ring account rows rated HIGH highlighted; p50 150 ms, p95 200 ms over 117 events; 0 dropped |
| Investigation | Real live-scored transaction: factors, SHAP contributions, behaviour reasons; open case from a CRITICAL alert, add note, approve "Hold recommended" (confirmation says nothing is blocked automatically), resolve as suspicious (confirmation says it does not confirm fraud); controls disappear once resolved |
| AI report (real Claude, about 50 s) | Model-written narrative, suspicious not fraud, cites evidence ids, lists limitations, flags the over-confident 1.00 probability |
| AI Investigator chat (real Claude, about 60 s) | "I can't say whether it's fraud", cited evidence, score vs probability kept apart |
| Invalid/expired token | Redirected to login, session cleared |
| Viewer | Every page loads read-only (no simulator, case actions or chat input); direct writes return 403 (`/simulate/start`, `/cases/1/notes`, `/agent/chat`) |
| Data source = PayPal Sandbox | Overview shows exactly 1 transaction, 0 alerts; Live shows only the real PayPal row `PP-…`, LOW/ALLOW |

## Defects the walk found (each fixed test-first, see PROJECT_PROGRESS.md)
Chat 502 (tool schema `minItems`), null latency crash, report `confidence` object crash, false empty audit
timeline for analysts, zone-less timestamps.

## Not verified
- Graph Explorer canvas rendering (React Flow stayed hidden because the pane was hidden): layout, edges and
  click-to-expand untested visually; nodes were confirmed in the DOM with correct labels and risk levels.
- The serif fonts (Quincy CF / Astralaga) are not installed on this machine; the Georgia fallback rendered.
- A refusal triggering the model fallback; behaviour with PaySim-scale data.

## Side effects left in the demo database
One case (`#1`, resolved suspicious, with a note and an approved action) and 117 replayed events were
created by this walk-through. `python scripts/serve.py --rebuild` resets the demo.
