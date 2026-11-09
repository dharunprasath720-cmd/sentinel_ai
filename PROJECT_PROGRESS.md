# SENTINEL AI — Project Progress

Deadline: 4 days from 2026-11-09. Approach: thin vertical slice, then deepen.
Spec: `docs/superpowers/specs/2026-11-09-sentinel-ai-design.md` · Plans: `docs/superpowers/plans/` (day1, day2)

## Run it

```
py -3.11 -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt   # Python 3.11.4 used
.venv\Scripts\python -m pytest                                                      # 138 tests
set PYTHONPATH=backend && .venv\Scripts\python -m sentinel.models.run --dataset synthetic
```
Scoring: `sentinel.pipeline.score_frame(df, bundle, RiskEngine(load_policy(DEFAULT_POLICY_PATH)), fit_normalisers(train_df))`.
API: `sentinel.api.app.create_app(engine)` (needs `SENTINEL_JWT_SECRET`, 32+ chars).

## Day 1 — data layer, features, ML baselines: DONE
Validated idempotent ingestion (UTC-normalised, full-payload conflict detection), synthetic generator, PaySim loader (fixture only), leak-free point-in-time features, chronological split, LogReg / LightGBM / Isolation Forest with a review-budget threshold. Independent review fixed four real bugs (non-UTC timestamps, silently dropped label changes, always-zero model on fraud-free validation, hidden flag rate).

## Day 2 — harder data, calibration, behaviour, graph, risk, SHAP, cases, auth, API: DONE (verified 2026-11-09)

**Verified by running:** `pytest` **138 passed**. All numbers below are from real runs on `generate(seed=42)` (15,295 rows, 500 accounts x 30 days, fraud 2.04%), chronological 60/20/20.

**Models (test slice, review budget 1%):**

| model | PR-AUC | recall | precision | calibration (Brier raw -> calibrated) |
|---|---|---|---|---|
| logreg | 0.951 | 0.596 | 0.981 | Platt chosen: 0.0364 -> 0.0077 |
| lightgbm | 0.906 | 0.652 | 1.000 | isotonic chosen: 0.0078 -> 0.0079 (no gain) |
| iforest | 0.413 | 0.303 | 0.628 | not a probability |

Day 1 data was trivially separable (LightGBM PR-AUC 1.000); fraud now overlaps normal behaviour (27% of fraud at night vs 56% before; rings pay popular merchants, amounts 1.3-3x typical).

**Full pipeline on held-out rows (validation + test, 6,0xx rows), policy defaults:**

| scenario | LOW | MODERATE | HIGH | CRITICAL |
|---|---|---|---|---|
| normal | 5819 | 139 | 1 | 0 |
| legit_unusual | 0 | 8 | 0 | 0 |
| ring | 6 | 13 | 1 | 34 |
| burst (fraud + legit) | 14 | 21 | 46 | 16 |

- Fraud rows (131): **97 reach HIGH+ (74%)**, 20 MODERATE, 14 LOW. Of 98 HIGH+ rows, 97 are fraud: one false positive.
- 33 `HOLD_RECOMMENDED` recommendations, all on ring rows in flagged clusters; **0 holds on any non-fraud row**.
- All 8 legitimate-but-unusual purchases land at MONITOR: never REVIEW, never a hold, never called fraud.
- Graph: all 5 planted rings found as flagged clusters (shared device + common merchant + tight time window), 0 flagged non-ring clusters.
- SHAP additivity holds to 1e-4. Scoring throughput: 44.8 s for 15,295 rows.

**Built:** `behaviour/` (robust per-account baselines, contamination guard, neutral with no history), `graph/` (heterogeneous NetworkX graph, Louvain, 4-signal clusters, point-in-time window indicators), `risk/` (deterministic policy.yaml engine, single-source cap, hold needs a flagged cluster), `models/explain.py`, `pipeline.py` (two-pass, point-in-time), `cases/` (alerts, cases, notes, append-only audit), `security.py` (argon2, JWT, roles), `api/app.py` (login, alerts, cases, audit; business-scoped 404s).

## Known limitations — read before trusting or demoing
1. **26% of fraud is missed** (34 of 131): takeover bursts that resemble legitimate bursts, and the first ring transactions before the shared-device pattern exists (point-in-time scoring cannot know it yet).
2. **Legit-unusual purchases are MONITORed, not REVIEWed.** The demo story "flagged for review" needs either a lower REVIEW threshold or to be told as "flagged for monitoring".
3. **Flagged clusters carry 1-4 extra non-ring accounts.** Use the cluster's evidence transactions, not its member list, for per-transaction decisions.
4. **Synthetic data reflects the generator's assumptions**; rings share a device by construction. Results do not predict real-world performance. PaySim was never evaluated (fixture only).
5. **LightGBM calibration did not improve** on isotonic (within noise); LogReg's did.
6. **Policy thresholds (0.20 / 0.40 / 0.65) are starting values.** Budget-derived thresholds from validation were 0.17 / 0.52 / 0.65; `calibrate_thresholds` and `threshold_report` exist but the policy file has not been switched.
7. **`score_frame` is a batch replay** (44.8 s / 15k rows); too slow to call per event. Day 3's live path must score incrementally or stream precomputed results.
8. **Security gaps:** no rate limiting; denied (403) attempts are not audited; login is a JSON body not an OAuth2 form.
9. **Deferred from Day 1 review:** feature engine is not linear-time (1M rows ~285 s); `Account` primary key ignores `business_id`; empty-CSV error is unclear; `is_failed` is a label proxy in synthetic data; `train()` does not enforce a single `source`.
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
