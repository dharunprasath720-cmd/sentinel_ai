# SENTINEL AI — Project Progress

Deadline: 4 days from 2026-11-09. Approach: thin vertical slice, then deepen.
Spec: `docs/superpowers/specs/2026-11-09-sentinel-ai-design.md` · Plans: `docs/superpowers/plans/` (day1, day2)

## Run it

```
py -3.11 -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt   # Python 3.11.4 used
.venv\Scripts\python -m pytest                                                      # 158 tests
set PYTHONPATH=backend && .venv\Scripts\python -m sentinel.models.run --dataset synthetic
```
Scoring: `sentinel.pipeline.score_frame(df, bundle, RiskEngine(load_policy(DEFAULT_POLICY_PATH)), fit_normalisers(train_df))`.
API: `sentinel.api.app.create_app(engine)` (needs `SENTINEL_JWT_SECRET`, 32+ chars).

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

## Known limitations — read before trusting or demoing
1. **21% of fraud is missed** (33 of 154): takeover bursts that resemble legitimate bursts, and the first ring transactions before the shared-device pattern exists (point-in-time scoring cannot know it yet).
2. **Legit-unusual purchases are MONITORed, not REVIEWed.** The demo story "flagged for review" needs a lower REVIEW threshold or is told as "flagged for monitoring".
3. **Flagged clusters carry 1–4 extra non-ring accounts.** Use a cluster's evidence transactions, not its member list, for per-transaction decisions.
4. **Synthetic data reflects the generator's assumptions** (rings share a device by construction). Results do not predict real-world performance. PaySim was never evaluated.
5. **Policy thresholds (0.20 / 0.40 / 0.65) are starting values**; `calibrate_thresholds` / `threshold_report` exist but are not wired into the policy file.
6. **`score_frame` is a batch replay** (37.7 s / 15.7k rows); too slow per event. Day 3's live path must score incrementally or stream precomputed results.
7. **Security gaps:** no rate limiting; denied (403) attempts are not audited; login is a JSON body.
8. **Deferred minors from the Day 2 review:** a validly signed token with a non-integer `sub`, or an id above 2^63, returns 422/500 instead of 401/404 (needs our secret to trigger); a device-window count alone can satisfy the graph "strong source" test (unreachable under default weights); `Normaliser.transform(nan)` returns 1.0; `calibrate_thresholds` on constant scores flags everything; `account_history` / `merchant_risk` are raw shares, not percentile-normalised as the spec says; `/alerts` and `/audit` are unpaginated; `services._case` is used by the API as a private function; several functions (`build_graph`, `cluster_degree_centrality`, `profile`, explain helpers) have no production caller yet; the cluster step re-runs Louvain per trigger row.
9. **Deferred from the Day 1 review:** feature engine is not linear-time (1M rows ~285 s); `Account` primary key ignores `business_id`; empty-CSV error is unclear; `is_failed` is a label proxy in synthetic data; `train()` does not enforce a single `source`.
10. Docker/Postgres paths untested here (neither installed).

## Roadmap

| Day | Target | Status |
|---|---|---|
| 1 | Scaffold, data, ingestion, features, ML + eval | **done** |
| 2 | Harder data, graph, behaviour, risk, SHAP, auth/cases/API | **done** |
| 3 | Claude agent + tools, SSE live stream, PayPal Sandbox live | not started |
| 4 | Dashboard (5 pages), tests, README, demo video | not started |

## Needed from the user (Day 3 at the latest)
`ANTHROPIC_API_KEY`; PayPal Sandbox Client ID/Secret + webhook ID (and a public tunnel for webhooks). Optional: PaySim CSV from Kaggle.
