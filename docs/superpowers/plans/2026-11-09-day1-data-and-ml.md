# SENTINEL AI Day 1 — Data Layer, Features and ML Baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tested pipeline that generates/loads labelled transactions, ingests them idempotently into a database, builds leak-free point-in-time features, and trains and evaluates LogReg, LightGBM and Isolation Forest with calibration and a review-budget threshold.

**Architecture:** Package `sentinel` under `backend/`, run from the `sentinel-ai/` root. SQLAlchemy models (SQLite default, Postgres via `DATABASE_URL`), one shared feature function used for training and inference, models saved as versioned artifacts with a JSON metrics report.

**Tech Stack:** Python venv (3.12 preferred, see Task 1), pandas, numpy, scikit-learn, LightGBM, SHAP (installed now, used Day 2), SQLAlchemy 2, pydantic 2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-sentinel-ai-design.md`

## Global Constraints

- All paths are relative to `sentinel-ai/`; tests live in `tests/`, code in `backend/sentinel/`.
- `DATABASE_URL` env var selects the DB; default `sqlite:///./sentinel.db`. Seed default `42` everywhere.
- Every transaction has `source ∈ {"synthetic","paysim","paypal_sandbox"}` and a `business_id`; sources are never pooled in one training run.
- Optional fields (`device_id`, `instrument_id`, `geo`, `merchant_id`) stay `None` when absent; nothing is inferred or invented.
- Chronological train/val/test split only; features use history strictly **before** the row's timestamp.
- Imbalance handling: class weights + threshold tuning. **No SMOTE.**
- Calibration is fitted on the validation slice only. Accuracy is never reported as a headline metric.
- Reported metrics: precision, recall, F1, PR-AUC, ROC-AUC, FPR, FNR, confusion matrix, precision at the review threshold, inference latency.
- Device and instrument identifiers are hashed/synthetic. Never print or store real personal data.
- Measured numbers are written into docs only from actual runs.

## Review Focus

- Account with a single transaction: features are finite (no NaN/inf), std defaults to 0. (Task 6)
- Transactions with identical timestamps: results are deterministic and a row never counts itself or its same-timestamp peers as "prior". (Task 6)
- Bad rows in a CSV (zero/negative/NaN amount, bad currency, unparsable or naive timestamp): rejected with a reason, valid rows still load. (Task 3)
- Same `external_id` re-sent with a different payload: first record kept, counted as a conflict, never silently overwritten. (Task 3)
- A split or dataset with zero positives: evaluation returns a result with undefined metrics flagged instead of crashing. (Task 8)

---

### Task 1: Scaffold and environment check

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.gitignore`, `.env.example`, `backend/sentinel/__init__.py`, `backend/sentinel/config.py`, `scripts/check_env.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `sentinel.config.get_settings() -> Settings` with fields `database_url: str`, `seed: int`, `artifacts_dir: Path`, `data_dir: Path`.

- [ ] **Step 1: Choose the interpreter.** Run `py -0p`. If a 3.12 or 3.11 interpreter exists, use it; otherwise try 3.14. Create `.venv` there and install `requirements.txt` (pandas, numpy, scikit-learn, lightgbm, shap, sqlalchemy, pydantic, pydantic-settings, pytest). If any package fails to install on 3.14, stop and ask the user to approve installing Python 3.12 (`winget install Python.Python.3.12`) before continuing.
- [ ] **Step 2: Write the failing test** `tests/test_config.py::test_defaults_and_env_override`: with no env, `get_settings().database_url == "sqlite:///./sentinel.db"` and `seed == 42`; with `DATABASE_URL` set via `monkeypatch`, that value is returned (clear the settings cache between cases).
- [ ] **Step 3: Run it** (`pytest tests/test_config.py -v`); expect FAIL (module missing).
- [ ] **Step 4: Implement** `config.py` with `pydantic-settings`, cached via `functools.lru_cache`. Add `scripts/check_env.py` that imports each dependency and prints versions; `.gitignore` covers `.venv`, `*.db`, `.env`, `artifacts/`, `data/raw/`.
- [ ] **Step 5: Run** `pytest tests/test_config.py -v` (PASS) and `python scripts/check_env.py` (every import succeeds; paste the versions into `PROJECT_PROGRESS.md`).
- [ ] **Step 6: Commit** (`git init` first; the repo does not exist yet): `chore: scaffold sentinel-ai and verify environment`.

### Task 2: Database models

**Files:**
- Create: `backend/sentinel/db.py`, `backend/sentinel/ingestion/__init__.py`, `backend/sentinel/ingestion/orm.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `Base`; `make_engine(url: str | None = None) -> Engine`; `init_db(engine) -> None`; `session_scope(engine) -> ContextManager[Session]` (commit on success, rollback on error). ORM classes `Transaction`, `Account`, `Merchant`, `Device`, `PaymentInstrument` with the columns in spec §4 (`Transaction.external_id` unique, `source` and `business_id` non-null).

- [ ] **Step 1: Write failing tests** in `tests/test_db.py`: `test_unique_external_id` (second insert of the same `external_id` raises `IntegrityError`), `test_source_required` (insert without `source` fails), `test_optional_fields_nullable` (insert with `device_id=None`, `geo=None` succeeds).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** per the Interfaces using SQLAlchemy 2 declarative typing; tests use `sqlite:///:memory:`.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: database models`.

### Task 3: Validation and idempotent ingestion

**Files:**
- Create: `backend/sentinel/ingestion/schema.py`, `backend/sentinel/ingestion/service.py`
- Test: `tests/test_ingestion.py`

**Interfaces:**
- Consumes: Task 2 `Transaction`, `session_scope`.
- Produces: `TransactionIn` (pydantic: `external_id, account_id, merchant_id?, device_id?, instrument_id?, amount>0 finite, currency` 3 uppercase letters, `ts` timezone-aware (naive rejected), `type, payment_method?, status ∈ {completed,failed,pending}, geo?, label ∈ {0,1,None}, source` Literal of the three sources, `business_id`). `IngestResult(inserted:int, duplicates:int, conflicts:int, rejected:list[tuple[int,str]])`. `ingest(session, records: Iterable[dict]) -> IngestResult`. `ingest_csv(session, path: Path, source: str, business_id: str) -> IngestResult`.

- [ ] **Step 1: Write failing tests:** `test_valid_rows_inserted`; `test_reingest_same_record_is_noop` (second call: `inserted=0, duplicates=n`); `test_same_id_different_payload_counts_conflict_and_keeps_first`; `test_bad_rows_rejected_with_reason` (amounts 0, -5, NaN; currency "usd1"; naive timestamp; each in a 6-row batch with 1 valid row → `inserted=1`, `len(rejected)==5`, reasons non-empty); `test_csv_roundtrip` using `tmp_path`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** with per-row validation (never abort the batch); create `Account`/`Merchant`/`Device` rows on first sight; dedup on `external_id`; conflict = existing `external_id` with differing `amount/account_id/ts`.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: validated idempotent ingestion`.

### Task 4: Synthetic data generator

**Files:**
- Create: `backend/sentinel/ingestion/synthetic.py`
- Test: `tests/test_synthetic.py`

**Interfaces:**
- Consumes: Task 3 `TransactionIn` field names (columns must match).
- Produces: `generate(seed: int = 42, n_accounts: int = 500, days: int = 30) -> pd.DataFrame` with `TransactionIn` columns plus `scenario ∈ {normal, burst, ring, legit_unusual}` (evaluation-only; never a feature). `source="synthetic"`.

- [ ] **Step 1: Write failing tests:** `test_deterministic_for_seed` (two calls equal; different seed differs); `test_planted_ring` (≥4 accounts with `scenario=="ring"` share one `device_id`, all pay one `merchant_id` within a 2-hour window, labelled 1); `test_legit_unusual_not_fraud` (every `legit_unusual` row has `label==0` and amount above that account's 99th percentile of its `normal` rows); `test_fraud_rate_realistic` (overall label mean between 0.5% and 5%); `test_not_every_unusual_is_fraud` (`burst` rows include both labels).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** with `numpy.random.default_rng(seed)`: lognormal amounts per account, hour-of-day preferences, a few bursts (some fraud, some legit), one ring of 6 accounts, 15–25 legitimate-unusual large purchases, a few shared devices among *legitimate* family accounts (so shared device ≠ fraud). IDs like `ACC_0001`, device IDs as hash strings.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: synthetic generator with planted ring`.

### Task 5: PaySim loader (optional dataset)

**Files:**
- Create: `backend/sentinel/ingestion/paysim.py`, `tests/fixtures/paysim_sample.csv` (≈20 hand-written rows in the real PaySim column layout, clearly marked as a fixture)
- Test: `tests/test_paysim.py`

**Interfaces:**
- Produces: `load_paysim(path: Path, business_id: str = "paysim") -> pd.DataFrame` with `TransactionIn` columns, `source="paysim"`, `ts = 2026-01-01 UTC + step hours`, `external_id = f"PS{row_index}"`, `merchant_id = nameDest`, `label = isFraud`. The columns `oldbalanceOrg, newbalanceOrig, oldbalanceDest, newbalanceDest, isFlaggedFraud` are dropped (known label leakage).

- [ ] **Step 1: Write failing tests** on the fixture: output columns match the schema, balance columns absent, `ts` is timezone-aware and monotonic in `step`, `source` all `"paysim"`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement.** PaySim is a Kaggle download that needs a login; the real file goes in `data/raw/paysim.csv`. If it is missing, Task 9 runs on synthetic only and the report says PaySim was not evaluated.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: paysim loader`.

### Task 6: Point-in-time feature engine

**Files:**
- Create: `backend/sentinel/features/__init__.py`, `backend/sentinel/features/engine.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Consumes: DataFrame with `TransactionIn` columns.
- Produces: `FEATURE_COLUMNS: list[str]` and `build_features(df: pd.DataFrame) -> pd.DataFrame` (same index as `df`, columns exactly `FEATURE_COLUMNS`). Columns: `amount, log_amount, hour, day_of_week, is_failed, type_code, txn_count_5m, txn_count_1h, txn_count_24h, acct_mean_amount, acct_std_amount, amount_z, secs_since_prev, acct_failed_rate, device_account_count, acct_instrument_count, merchant_account_count, repeat_counterparty_count`. Every history-based column counts only rows with `ts` strictly earlier than the current row (same-timestamp rows excluded) and, for `device_account_count`, `merchant_account_count`, distinct counts as of that timestamp. `label` and `scenario` are never read.

- [ ] **Step 1: Write failing tests:** `test_no_future_leakage` (features for the first N rows are identical when computed on only the first N rows versus the full frame); `test_ignores_label_and_scenario` (flipping every `label` and `scenario` leaves features unchanged); `test_single_txn_account_finite` (all values finite, `acct_std_amount==0`, `secs_since_prev` uses a documented sentinel); `test_same_timestamp_ties_deterministic` (shuffling input row order does not change per-row features, and tied rows do not count each other); `test_window_counts` on a hand-built 5-row frame with known 5m/1h/24h counts; `test_device_account_count_grows_over_time`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** by sorting on `(ts, external_id)` and using per-group, strictly-prior expanding/rolling logic; restore the original order at the end. Avoid O(n²): use `searchsorted` over per-account sorted timestamps.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: point-in-time feature engine`.

### Task 7: Chronological split

**Files:**
- Create: `backend/sentinel/models/__init__.py`, `backend/sentinel/models/split.py`
- Test: `tests/test_split.py`

**Interfaces:**
- Produces: `chronological_split(df, train_frac: float = 0.6, val_frac: float = 0.2) -> tuple[DataFrame, DataFrame, DataFrame]` (train, val, test) ordered by `ts`; all of train precedes val precedes test; sizes within 1 row of the fractions; no row in two splits.

- [ ] **Step 1: Write failing tests** for ordering, disjointness, sizes, and `ValueError` when fractions sum ≥ 1.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** by sorting on `(ts, external_id)` and slicing by index. Features are computed on the **full** frame first (they are point-in-time), then sliced.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: chronological split`.

### Task 8: Evaluation, calibration and threshold

**Files:**
- Create: `backend/sentinel/models/evaluate.py`
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Produces: `evaluate_scores(y_true, scores, threshold: float) -> dict` with keys `precision, recall, f1, pr_auc, roc_auc, fpr, fnr, confusion_matrix ([[tn,fp],[fn,tp]]), precision_at_review, n_positive, undefined: list[str]`; when there are zero positives or zero negatives, affected metrics are `None` and named in `undefined`. `choose_threshold(y_val, scores, review_budget_frac: float = 0.01) -> float` (the score above which the top `review_budget_frac` of validation transactions fall). `fit_calibrator(val_scores, y_val) -> IsotonicRegression`.

- [ ] **Step 1: Write failing tests:** metrics on a hand-computed 10-row example (exact precision/recall/FPR/FNR/confusion matrix); `test_no_positives_does_not_crash` (returns dict, `undefined` lists `recall`, `pr_auc`, `roc_auc`); `test_choose_threshold_flags_budget_fraction`; `test_calibrator_monotonic`; the returned dict contains no `accuracy` key.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** with scikit-learn metric functions plus explicit guards.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: fraud-appropriate evaluation and calibration`.

### Task 9: Training bundle and CLI report

**Files:**
- Create: `backend/sentinel/models/train.py`, `backend/sentinel/models/run.py`
- Test: `tests/test_train.py`

**Interfaces:**
- Consumes: Tasks 4–8 (`generate`, `load_paysim`, `build_features`, `FEATURE_COLUMNS`, `chronological_split`, `evaluate_scores`, `choose_threshold`, `fit_calibrator`).
- Produces: `train(df, seed: int = 42, review_budget_frac: float = 0.01) -> TrainedBundle` holding LogReg (scaled, `class_weight="balanced"`), LightGBM (`scale_pos_weight` from the train split), Isolation Forest (fit on train rows, scores rank-normalised), per-model calibrators fitted on val, per-model thresholds, and metrics on test. `TrainedBundle.predict(features: DataFrame) -> DataFrame` with columns `lr_prob, lgbm_prob, anomaly_score` (calibrated probabilities for the supervised models). `TrainedBundle.save(dir: Path)` / `TrainedBundle.load(dir: Path)`. CLI: `python -m sentinel.models.run --dataset synthetic|paysim` writes `artifacts/<version>/{bundle.joblib, metrics.json, report.md}`; report table lists model, precision, recall, F1, PR-AUC, ROC-AUC, FPR, FNR, precision@review, per-row inference latency (ms), and confusion matrix.

- [ ] **Step 1: Write failing tests** on `generate(seed=42, n_accounts=150, days=20)`: `test_train_runs_and_reports_all_models` (metrics for all three models present, no `accuracy` key); `test_calibrator_fit_only_on_val` (patch `fit_calibrator` and assert it was called with val-index scores only); `test_save_load_roundtrip_predicts_identically`; `test_predict_columns_and_ranges` (probabilities in [0,1]); `test_lgbm_beats_random_pr_auc` (test PR-AUC > positive rate); `test_cli_writes_report` using `tmp_path`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement.** Model version string is `f"{dataset}-{utc timestamp}"`. Keep training under ~60 s on the synthetic default size.
- [ ] **Step 4: Run** `pytest tests/test_train.py -v`; expect PASS.
- [ ] **Step 5: Run the real thing:** `python -m sentinel.models.run --dataset synthetic`. Open `report.md` and record the real numbers.
- [ ] **Step 6: Commit** `feat: model training, calibration and evaluation report`.

### Task 10: Day 1 gate

**Files:**
- Modify: `PROJECT_PROGRESS.md`

- [ ] **Step 1:** Run `pytest -q` (all green) and re-run the CLI from a clean checkout path to confirm reproducibility (same seed → identical `metrics.json`).
- [ ] **Step 2:** Update `PROJECT_PROGRESS.md`: mark Day 1 complete, paste the measured metrics table and pytest summary, list limitations found (for example whether the planted ring is trivially separable, PaySim not evaluated if the file was absent), and the Day 2 starting point.
- [ ] **Step 3: Commit** `docs: day 1 verified`.
