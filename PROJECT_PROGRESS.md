# SENTINEL AI — Project Progress

Deadline: 4 days from 2026-11-09. Approach: thin vertical slice, then deepen.

## Phase 1 — Requirements and architecture
- [x] Environment inspected (Python 3.14.3, Node 24, 7.9 GB RAM; no Docker, no PostgreSQL, no git repo)
- [x] Design spec written: `docs/superpowers/specs/2026-11-09-sentinel-ai-design.md`
- [ ] Spec reviewed and approved by user  <-- current gate
- [ ] Python dependency wheel check (3.14 vs 3.11/3.12) — first task of Day 1

## Roadmap
| Day | Target | Status |
|---|---|---|
| 1 | Scaffold, data, ingestion, features, ML + eval | not started |
| 2 | Graph, behaviour, risk, SHAP, auth/cases | not started |
| 3 | Claude agent, SSE, PayPal Sandbox live | not started |
| 4 | Dashboard (5 pages), tests, README, demo video | not started |

## Known limitations / open items
- Needs from user: ANTHROPIC_API_KEY, PayPal Sandbox credentials + webhook ID (Day 3).
- Docker/Postgres paths will be untested on this machine.
- No application code exists yet; nothing has been run or measured.
