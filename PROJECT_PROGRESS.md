# SENTINEL AI — Project Progress

Deadline: 4 days from 2026-11-09. Approach: thin vertical slice, then deepen.
Spec: `docs/superpowers/specs/2026-11-09-sentinel-ai-design.md` · Plans: `docs/superpowers/plans/` (day1, day2)

## Run it

```
py -3.11 -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt   # Python 3.11.4 used
.venv\Scripts\python -m pytest                                                      # 379 tests, ~6 min
set PYTHONPATH=backend && .venv\Scripts\python -m sentinel.models.run --dataset synthetic
.venv\Scripts\python scripts\serve.py                  # builds the demo on first run (~3-4 min), then serves on :8000
```
Scoring (batch): `sentinel.pipeline.score_frame(df, bundle, RiskEngine(load_policy(DEFAULT_POLICY_PATH)), fit_normalisers(train_df))`.
API docs: http://127.0.0.1:8000/docs once `serve.py` is running. Demo logins (ana = analyst, vic = viewer, adm = admin) and the JWT secret are generated into `.env.demo` (git-ignored, never printed).
Optional integrations (environment or `.env`): `ANTHROPIC_API_KEY` for the Claude agent; `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` for the PayPal Sandbox webhook route.

## Day 1 — data layer, features, ML baselines: DONE
Validated idempotent ingestion (UTC-normalised, full-payload conflict detection), synthetic generator, PaySim loader (fixture only), leak-free point-in-time features, chronological split, LogReg / LightGBM / Isolation Forest with a review-budget threshold. An independent review fixed four real bugs.

## Day 2 — harder data, calibration, behaviour, graph, risk, SHAP, cases, auth, API: DONE (verified 2026-11-09)

**Verified by running:** `pytest` **158 passed**. Numbers below are from real runs on `generate(seed=42)` (15,711 rows, 500 accounts x 30 days, fraud 1.99%), chronological 60/20/20.

**Models (test slice, review budget 1%):**

| model | PR-AUC | recall | precision | calibration (Brier raw -> calibrated) |
|---|---|---|---|---|
| logreg | 0.794 | 0.424 | 0.907 | isotonic: 0.0507 -> 0.0115 |
| lightgbm | 0.867 | 0.511 | 1.000 | Platt: 0.0095 -> 0.0090 (small gain) |
| iforest | 0.351 | 0.228 | 0.568 | not a probability |

Separability history: Day 1 data gave LightGBM PR-AUC 1.000; making fraud overlap normal behaviour gave 0.906; adding legitimate multi-account devices and flash sales (after review) gave 0.867.

**Full pipeline on rows the models did not train on (validation + test; the validation slice also fitted the calibrators and thresholds), policy defaults:**

| scenario | LOW | MODERATE | HIGH | CRITICAL |
|---|---|---|---|---|
| normal | 5867 | 222 | 6 | 0 |
| legit_unusual | 0 | 5 | 0 | 0 |
| ring | 7 | 13 | 22 | 42 |
| burst (fraud + legitimate) | 15 | 19 | 55 | 11 |

- Fraud rows (154): **121 reach HIGH+ (79%)**, 18 MODERATE, 15 LOW.
- **HIGH+ precision is 89%**: of 136 HIGH+ rows, 15 are not fraud (6 normal, 9 from legitimate bursts / flash sales).
- 41 `HOLD_RECOMMENDED`, all on ring rows; **0 holds on any non-fraud row**.
- All 5 legitimate-but-unusual purchases land at MONITOR: never REVIEW, never a hold, never called fraud.
- Graph: 5 of 5 planted rings flagged (shared device + common merchant + tight window). 11 candidate clusters found; the other 6 (legitimate 3–6-account terminals, flash sales) are seen but **not** flagged; 0 flagged clusters without a ring account.
- SHAP additivity holds to 1e-4. Scoring throughput: 37.7 s for 15,711 rows.

**Built:** `behaviour/`, `graph/`, `risk/`, `models/explain.py`, `pipeline.py` (two-pass, point-in-time), `cases/` (alerts, cases, notes, append-only audit), `security.py`, `api/app.py`.

## Day 2 independent review (Opus, whole branch) — outcome
Reproduced and fixed, each with a test that failed first:
- **Business isolation (Critical):** behaviour baselines and feature history were keyed by account id alone; two businesses sharing account ids changed 213 of one business's risk levels and leaked another's typical amounts into explanations. All per-entity state is now keyed by business; a two-business pipeline test pins it.
- **Policy NaN (Important):** a NaN weight silently made every decision ALLOW. Policy loading now rejects non-finite, non-numeric and bool values, `strong_source_min` outside (0, 1], and truthy strings.
- **Case state machine (Important):** approving or re-resolving a resolved case reopened it; closed or already-used alerts could be reattached. Now a 409 Conflict (notes after closure are still allowed).
- **Graph results were partly by construction (Important):** legitimate shared devices only ever had 2 accounts, so "3+ accounts on a device" was effectively the ring label. Added legitimate 3–6-account devices and cross-account flash sales; headline numbers dropped to the table above.

## Day 3 — PayPal Sandbox client + webhook, live scoring, event stream, Claude investigation agent: BUILT, live integrations NOT yet exercised

**Verified by running:** `pytest` **379 passed** (~6 min, after the review fixes below). Real server driven over HTTP by a smoke script: login and role checks, SSE stream, simulator, metrics, agent report, and the 503s for unconfigured integrations.

**What is built**
- `paypal/`: Sandbox client (token cache, retries with one idempotency key per call, no secrets in logs); webhook verification that sends PayPal the **exact received bytes**, accepts only a literal `"SUCCESS"`, fails closed, answers 503 when PayPal is unreachable, deduplicates on `event_id` (4 concurrent deliveries → 1 row).
- `live/`: incremental `LiveScorer` (features identical to batch; risk levels agree 100% on 450 consecutive events), event bus, `LiveService` (ingest → score → assessment → alert → publish after commit), simulator, `/stream/events` (SSE), `/metrics/live`, `/paypal/webhook`.
- `agent/`: ten read-only, business-scoped tools (the model never supplies a business id; the ground-truth label is never exposed); a report whose facts come from the tools and whose narrative must cite evidence the tools actually returned; guards against claiming fraud, against classifications that contradict the deterministic risk level, and against injected instructions; a bounded chat loop (auto tool choice, 8 iterations, citations checked).
- `demo.py` + `scripts/serve.py`: reproducible demo world (history in the DB, model trained on history only, 30% of the data held back as the replay stream with labels removed).

**Measured** (full demo: 500 accounts × 30 days, model trained on the first 70% only)

| item | result |
|---|---|
| model on its own test slice | PR-AUC 0.739, recall 0.479, precision 0.767 |
| ring events in the live stream (28) | 19 HIGH, 6 MODERATE, 3 LOW → **68% HIGH+**; **86% once the cluster is flagged** (first flag at ring event #8) |
| small fast test world (200 × 20, weak model) | ring HIGH+ 54%, at least MODERATE 96%, flagged at event #5, 0 holds on non-fraud rows |
| live scoring latency, quiet laptop | p50 81 ms, p95 162 ms |
| same, under heavy OneDrive/memory contention | p50 ~200–212 ms, p95 ~320–410 ms (in-process); p50 135–197 ms, p95 236–318 ms over real HTTP |
| SSE over real HTTP | 6 events delivered, first within 0.4 s of simulator start |
| replaying 40 stream events twice | 40 processed, then 10 new (30 duplicates dropped) |

**NOT exercised yet — do not claim these work**
- **PayPal Sandbox, live:** no real order, approval, capture or webhook has run. The assumed OAuth path (`/v1/oauth2/token`), capture-response path (`purchase_units[0].payments.captures[0]`), whether `custom_id` is echoed, and the unapproved-order error name are **unconfirmed** (all fail closed or raise a clear error). Run `scripts/paypal_sandbox_check.py` (needs your Sandbox credentials and a Sandbox buyer account) with `scripts/serve.py` behind a public tunnel.
- **Claude, live:** no real API call has run. The refusal-fallback parameter (`fallbacks: "default"` via `extra_body` + beta `server-side-fallback-2026-07-01`) and the structured-output request shape are **unverified**; `AnthropicLLM(use_fallbacks=False)` disables the former. Run `scripts/live_claude_check.py`.
- **Refunds:** the client method exists (`refund_capture`) but nothing calls it and it has never run; an approved-case refund workflow is not built.
- PayPal's Transaction Search / reporting API: not built (response details unverified).

## Day 3 independent review (Opus, whole branch) — outcome

Reproduced by the reviewer and fixed here, each with a test that failed first (suite now **379 passed**):
- **PayPal and synthetic traffic shared scorer state.** One PayPal event dated "now" set the business's newest-event clock to November, after which every January-dated simulator event was treated as "late" and got no behaviour scoring (reproduced: an outlier scored 0.8, then 0.0). Scorer state is now partitioned by (business, data source); outputs still report the real business.
- **All unlinked PayPal payers merged into one account** (12 distinct payers in 2 minutes looked like one customer with velocity 1.0). An unlinked payment is now its own pseudo-account, `PAYPAL_UNLINKED:<capture id>`.
- **The unauthenticated webhook could be used to flood PayPal and stall the API.** Now: the certificate URL must be an https `paypal.com` host (checked before any outbound call), verification is never retried, a 64 KB body cap (413), at most 8 verifications in flight (excess get 503 + Retry-After), and absurdly nested JSON is a 400 instead of a 500.
- **The fraud-claim filter was easy to bypass** ("definitely a fraud", "Fraud confirmed.", "fraudster", line breaks) and nothing blocked "the account has been blocked". Replaced with sentence-level detectors (`agent/claims.py`, 48 cases) applied to every narrative field **and to chat replies, which are now withheld** when they assert fraud or an executed action. MODERATE-risk transactions can no longer be classified `likely_legitimate`. A test also checks the deterministic report never trips its own filters.
- **`/metrics/live` leaked other businesses' counts.** Counters and drop counts are now per business.
- Also fixed: an unexpected exception inside a tool now becomes an error result instead of a chat failure.

Deferred (decided, not forgotten): two simultaneous simulator starts can run two replay threads; scorer state changes before the database commit (a failed commit leaves behaviour having learnt a rolled-back row); the SSE stream does not re-check auth after it opens and authenticates with synchronous database I/O on the event loop; `get_related_accounts` and the model-explanation query load more rows than needed; `LiveScorer` memory grows without bound (`_rows`, `_seen`, indices); `live_claude_check.py` and one test validate a report against its own evidence ids (cannot fail); **demo credentials (`.env.demo`) are written into the OneDrive-synced folder by default**; no per-IP rate limit on the webhook, and none on LLM-backed endpoints.

## Known limitations — read before trusting or demoing
1. **21% of fraud is missed** (33 of 154): takeover bursts that resemble legitimate bursts, and the first ring transactions before the shared-device pattern exists (point-in-time scoring cannot know it yet).
2. **Legit-unusual purchases are MONITORed, not REVIEWed.** The demo story "flagged for review" needs a lower REVIEW threshold or is told as "flagged for monitoring".
3. **Flagged clusters carry 1–4 extra non-ring accounts.** Use a cluster's evidence transactions, not its member list, for per-transaction decisions.
4. **Synthetic data reflects the generator's assumptions** (rings share a device by construction). Results do not predict real-world performance. PaySim was never evaluated.
5. **Policy thresholds (0.20 / 0.40 / 0.65) are starting values**; `calibrate_thresholds` / `threshold_report` exist but are not wired into the policy file.
6. **Live scoring takes ~80–400 ms per event** depending on machine load (the batch `score_frame` is still ~38 s per 15k rows). Fine for a demo stream of a few events per second, not for high volume. Each event slices ALL rows of its account/merchant/device, so latency grows with a popular merchant's history.
7. **Security gaps:** no rate limiting (including the LLM-backed endpoints: an analyst can spend tokens freely); denied (403) attempts are not audited; login is a JSON body. The webhook route is authenticated only by PayPal's signature and is not rate limited.
7b. **The live scorer's warm start** replays history without contamination information and starts account/merchant history counters from the batch levels; measured agreement with batch was 100% on 450 events, but it is single-pass where batch is two-pass.
7c. **Environment:** the project lives inside OneDrive. During testing OneDrive had used 27,000 CPU-seconds and only ~0.8 GB of 7.9 GB RAM was free, which made everything ~2.5× slower and flaked a timing test. Move the project out of OneDrive, or exclude `.venv`, `artifacts` and `*.db` from sync, before the demo.
8. **Deferred minors from the Day 2 review:** a validly signed token with a non-integer `sub`, or an id above 2^63, returns 422/500 instead of 401/404 (needs our secret to trigger); a device-window count alone can satisfy the graph "strong source" test (unreachable under default weights); `Normaliser.transform(nan)` returns 1.0; `calibrate_thresholds` on constant scores flags everything; `account_history` / `merchant_risk` are raw shares, not percentile-normalised as the spec says; `/alerts` and `/audit` are unpaginated; `services._case` is used by the API as a private function; several functions (`build_graph`, `cluster_degree_centrality`, `profile`, explain helpers) have no production caller yet; the cluster step re-runs Louvain per trigger row.
9. **Deferred from the Day 1 review:** feature engine is not linear-time (1M rows ~285 s); `Account` primary key ignores `business_id`; empty-CSV error is unclear; `is_failed` is a label proxy in synthetic data; `train()` does not enforce a single `source`.
10. Docker/Postgres paths untested here (neither installed).

## Roadmap

| Day | Target | Status |
|---|---|---|
| 1 | Scaffold, data, ingestion, features, ML + eval | **done** |
| 2 | Harder data, graph, behaviour, risk, SHAP, auth/cases/API | **done** |
| 3 | Claude agent + tools, SSE live stream, PayPal Sandbox | **built and tested offline; live PayPal and live Claude checks pending (need credentials)** |
| 4 | Dashboard (5 pages), tests, README, demo video | not started |

## Needed from the user (Day 3 at the latest)
`ANTHROPIC_API_KEY`; PayPal Sandbox Client ID/Secret + webhook ID (and a public tunnel for webhooks). Optional: PaySim CSV from Kaggle.
