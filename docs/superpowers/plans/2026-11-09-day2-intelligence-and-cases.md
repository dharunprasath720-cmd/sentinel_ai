# SENTINEL AI Day 2 — Harder Data, Behaviour, Graph, Risk, SHAP, Cases and Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Day 1 baseline into a credible intelligence stack: non-trivial synthetic fraud, honest calibration, behavioural baselines, graph cluster detection, a deterministic risk and decision engine, SHAP explanations, and a secured alert/case/audit backend.

**Architecture:** New packages `behaviour/`, `graph/`, `risk/`, `cases/`, `api/` plus `models/explain.py` and `pipeline.py`, all behind plain-Python interfaces. `pipeline.score_frame` replays transactions chronologically through features → models → behaviour → graph → risk. The API exposes only alerts, cases and auth (no scoring UI yet).

**Tech Stack:** Day 1 stack plus networkx (Louvain), PyYAML, argon2-cffi, PyJWT, FastAPI, httpx (test client).

**Spec:** `docs/superpowers/specs/2026-11-09-sentinel-ai-design.md` (§6 engines, §4 data model, §11 security) · Prior plan: `docs/superpowers/plans/2026-11-09-day1-data-and-ml.md` · Open items: `PROJECT_PROGRESS.md` ("Deferred to Day 2")

## Global Constraints

- Python 3.11 venv at `sentinel-ai/.venv`; code in `backend/sentinel/`, tests in `tests/`; run tests with the venv's `python -m pytest`. Day 1 tests (52) must stay green.
- Seed default `42`; everything deterministic. Source tags `synthetic|paysim|paypal_sandbox` are never pooled; every query is scoped by `business_id`.
- Point-in-time only: no feature, baseline or graph signal may use data at or after the scored row's timestamp. `label` and `scenario` are never inputs to features, behaviour, graph or risk.
- Risk maths is pure deterministic Python (no LLM). Only the calibrated ML probability may be called a probability; the composite is a `risk_score`. Output field is `calibrated_fraud_probability`.
- An anomaly or a shared identifier alone is never proof of fraud: a single-source signal cannot raise the level above HIGH, and the strongest automatic action is a recommendation (`ALLOW|MONITOR|REVIEW|VERIFY|HOLD_RECOMMENDED`). Nothing executes without analyst approval.
- Graph edges exist only where the data has the link (no null-derived edges). A shared device alone does not flag a cluster; flagging needs ≥3 co-occurring signals.
- Passwords hashed with argon2; JWT for auth; roles `admin|analyst|viewer`; audit log is append-only; secrets only from env/`.env`.
- Report only measured numbers; document limitations in `PROJECT_PROGRESS.md`.

## Review Focus

- First-ever transaction of an account (no baseline): behaviour indicators are neutral and the risk level is not raised by missing history alone. (Tasks 3, 5)
- Account whose history is identical amounts (MAD = 0) or a single prior amount: no division by zero, no inf/NaN z-score. (Task 3)
- Same `account_id` or device hash present in two businesses: graph clusters, alerts and cases never cross `business_id`. (Tasks 4, 7, 8)
- Expired or tampered JWT, or a `viewer` calling an analyst action: 401/403 and no state change. (Task 8)
- A policy file with missing weights or thresholds out of order: fails loudly at load, not silently at scoring. (Task 5)

---

### Task 1: Non-trivial synthetic fraud and new dependencies

**Files:**
- Modify: `requirements.txt` (add `networkx`, `pyyaml`, `argon2-cffi`, `pyjwt`, `fastapi`, `httpx`, `uvicorn`), `backend/sentinel/ingestion/synthetic.py`
- Test: `tests/test_synthetic.py`

**Interfaces:**
- Produces: unchanged `generate(seed: int = 42, n_accounts: int = 500, days: int = 30) -> pd.DataFrame` contract (same columns, `scenario` evaluation-only), with fraud that overlaps normal behaviour.

- [ ] **Step 1: Install the new dependencies** into the venv and run `scripts/check_env.py`; add the new packages to its list.
- [ ] **Step 2: Write failing tests** in `tests/test_synthetic.py` on `generate(seed=42)`: `test_fraud_not_concentrated_at_night` (share of fraud rows at hours 2–4 UTC < 0.30); `test_ring_merchants_are_shared_with_legit_traffic` (every ring merchant also appears in `normal` rows from ≥10 distinct accounts); `test_legit_night_activity_exists` (≥2% of `normal` rows at hours 1–4 UTC); `test_fraud_amounts_overlap_normal` (median fraud amount ≤ 3× the median `normal` amount of the same accounts); `test_lightgbm_not_trivial` (train with `sentinel.models.train.train`; test-slice `pr_auc` for `lightgbm` is between 0.15 and 0.95). Existing ring, burst, legit_unusual, fraud-rate and per-split-fraud tests must still pass.
- [ ] **Step 3: Run them**; expect the new tests to FAIL (night share ≈ 0.56, PR-AUC ≈ 1.0).
- [ ] **Step 4: Change the generator:** fraud bursts at hours drawn from the account's own peak hours half the time; burst/ring amounts 1.3–3× the account's typical amount instead of 4–8× / 150–400; rings pay a merchant chosen from the 10 most-used legitimate merchants; ~10% of accounts are night-shift (peak hours 1–4); add legitimate new-merchant bursts (label 0). Keep determinism, ids non-revealing, and splits with ≥25 fraud rows at default size.
- [ ] **Step 5: Run the full suite**; expect all PASS. Record the new default fraud rate and test PR-AUC in the ledger.
- [ ] **Step 6: Commit** `feat: make synthetic fraud overlap normal behaviour`.

### Task 2: Calibration selection and reliability curve

**Files:**
- Modify: `backend/sentinel/models/evaluate.py`, `backend/sentinel/models/train.py`, `backend/sentinel/models/run.py`
- Test: `tests/test_evaluate.py`, `tests/test_train.py`

**Interfaces:**
- Produces: `select_calibrator(val_scores, y_val, seed: int = 42) -> tuple[str, Calibrator]` where the name is `"raw"|"platt"|"isotonic"` chosen by 5-fold stratified cross-validated Brier on the validation slice (ties go to the simpler: raw < platt < isotonic) and `Calibrator.predict(scores) -> np.ndarray` in [0,1]; `reliability_curve(y_true, probs, bins: int = 10) -> list[dict]` with keys `bin_low, bin_high, n, mean_predicted, observed_rate`. `TrainedBundle.calibrator_names: dict[str, str]`.
- Consumes: Day 1 `fit_calibrator`, `TrainedBundle`.

- [ ] **Step 1: Write failing tests:** `test_select_calibrator_fixes_miscalibrated_scores` (scores = `p**0.4` of a Bernoulli(p) sample, n=5000: chosen name ≠ `"raw"` and calibrated Brier on a fresh sample < raw Brier); `test_select_calibrator_keeps_raw_when_calibrated` (n=20000 perfectly calibrated: calibrated Brier within 1% of raw); `test_reliability_curve_counts` (bin counts sum to n; empty bins omitted); in `test_train.py`: `test_bundle_records_calibrator_choice_and_never_worse_than_raw_in_cv` (`bundle.calibrator_names` has `logreg` and `lightgbm`), and the CLI report contains a "Reliability" section.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** in `evaluate.py`; `train()` uses `select_calibrator` instead of `fit_calibrator` (still validation-only; keep the existing spy test valid by routing through the same call site name or updating it, ledgering a ruling). `run.py` writes the reliability table for test-slice calibrated probabilities.
- [ ] **Step 4: Run the full suite**; expect PASS.
- [ ] **Step 5: Re-run the real CLI** and record whether calibrated Brier ≤ raw Brier on the harder data; if not, report it plainly in `PROJECT_PROGRESS.md`.
- [ ] **Step 6: Commit** `feat: calibration selection with reliability curve`.

### Task 3: Behavioural anomaly engine

**Files:**
- Create: `backend/sentinel/behaviour/__init__.py`, `backend/sentinel/behaviour/engine.py`
- Test: `tests/test_behaviour.py`

**Interfaces:**
- Consumes: transaction dicts using `TransactionIn` field names (`ts` as `pd.Timestamp` UTC).
- Produces: `BehaviourIndicators` dataclass (`amount_robust_z: float, burst_count_10m: int, new_merchant: bool, off_hours: bool, failed_streak: int, n_history: int, deviation_score: float in [0,1], reasons: list[str]`); `BehaviourEngine(window: int = 50, min_history: int = 5)` with `indicators(txn: dict) -> BehaviourIndicators`, `update(txn: dict, contaminated: bool = False) -> None`, `profile(account_id: str) -> dict` (median, MAD, typical hours, mean inter-arrival secs, known merchants, failure rate); `replay(df: pd.DataFrame, contaminated_ids: frozenset[str] = frozenset()) -> pd.DataFrame` (indicator columns, index aligned to `df`, rows processed in `(ts, external_id)` order, each scored **before** it updates the baseline).

- [ ] **Step 1: Write failing tests:** `test_first_transaction_is_neutral` (n_history 0 → `deviation_score == 0`, empty reasons); `test_mad_zero_no_nan` (20 identical amounts then a different one: finite z, uses a documented floor); `test_sudden_spend_increase_flags` (z above 3.5 and reason text mentions the amount); `test_burst_detected` (6 txns within 10 minutes → `burst_count_10m == 5` at the 6th); `test_new_merchant_and_off_hours`; `test_failed_streak`; `test_contaminated_rows_do_not_move_baseline` (update with `contaminated=True` leaves `profile` median unchanged); `test_replay_is_point_in_time` (indicators for the first N rows equal those computed on only the first N); `test_deviation_is_not_a_verdict` (a legitimate large purchase scores < 1.0 and carries reasons, not a label).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** per-account state: last `window` non-contaminated amounts (median/MAD, MAD floored at `0.05 × median`, z = 0.6745·(x−median)/MAD), exponentially decayed 24-bin hour histogram (off-hours when bin probability < 2%), known-merchant set, recent timestamps, failure streak. Indicators are neutral (`0`/False) while `n_history < min_history`. `deviation_score` is a documented, bounded combination (max of normalised z/burst/new-merchant/off-hours/streak signals, with a small bonus for each additional co-occurring signal), clipped to [0,1].
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: behavioural anomaly engine`.

### Task 4: Graph intelligence engine

**Files:**
- Create: `backend/sentinel/graph/__init__.py`, `backend/sentinel/graph/engine.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: DataFrame with `TransactionIn` columns.
- Produces: `build_graph(df) -> nx.Graph` (nodes `("account"|"merchant"|"device"|"instrument", id)` with attribute `kind`; edges only from non-null columns; edge attrs `n_txn, total_amount, first_ts, last_ts`); `Cluster` dataclass (`cluster_id: str` = stable hash of sorted accounts, `accounts, devices, merchants, txn_ids: list[str]`, `density: float`, `signals: list[str]`, `flagged: bool`, `risk_indicator: float in [0,1]`, `evidence: dict`); `find_clusters(df, behaviour: pd.DataFrame | None = None, min_accounts: int = 3, window_hours: float = 3.0) -> list[Cluster]`; `window_indicators(df, window_hours: float = 2.0) -> pd.DataFrame` with columns `merchant_accounts_window, device_accounts_window` (distinct accounts seen in the window **strictly before** each row, plus itself; 0 when the id is null); `cluster_degree_centrality(G) -> dict`.
- Signals (name strings): `shared_device` (≥3 accounts on one device), `common_merchant` (≥60% of cluster transactions go to one merchant), `tight_window` (those transactions fall within `window_hours`), `similar_abnormal_behaviour` (needs `behaviour`; mean `deviation_score` of cluster rows ≥ 0.5). A cluster is `flagged` only with ≥3 signals; `risk_indicator = n_signals / 4`.

- [ ] **Step 1: Write failing tests** using hand-built frames and `generate(...)`: `test_no_edges_from_nulls`; `test_family_shared_device_not_flagged` (2 accounts, one device, normal traffic → not flagged); `test_ring_detected_with_evidence` (planted ring from `generate`: one flagged cluster containing every ring account, `signals` ⊇ {shared_device, common_merchant, tight_window}, and no flagged cluster contains a non-ring account only); `test_legit_unusual_account_not_in_flagged_cluster`; `test_clusters_never_cross_business` (identical device hash in two `business_id`s → separate clusters); `test_window_indicators_point_in_time` (first N rows unchanged when later rows are removed); `test_louvain_deterministic_with_seed`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** `find_clusters` on the account-projection of the shared-device/shared-merchant graph per `business_id`, using `networkx.community.louvain_communities(seed=42)`; compute density with `nx.density` on the induced account graph; `window_indicators` via per-key sorted timestamps and strictly-prior distinct sets.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: graph cluster detection`.

### Task 5: Risk scoring and decision engine

**Files:**
- Create: `backend/sentinel/risk/__init__.py`, `backend/sentinel/risk/engine.py`, `backend/sentinel/risk/policy.yaml`
- Test: `tests/test_risk.py`

**Interfaces:**
- Produces: `Policy` dataclass (`version: str, weights: dict[str,float], thresholds: dict[str,float]` keys `moderate, high, critical`, `single_source_cap: str = "HIGH"`, `hold_requires_cluster: bool = True`); `load_policy(path: Path) -> Policy` (raises `ValueError` on missing weight keys, weights not summing to 1±1e-6, or thresholds not strictly increasing in (0,1)); `RiskInputs` (`ml_prob, anomaly, behaviour, graph, velocity, account_history, merchant_risk`, each float in [0,1], plus `cluster_flagged: bool`); `Normaliser.fit(values) -> Normaliser` with `transform(x) -> float` (percentile rank against the fitted training distribution, in [0,1]); `RiskAssessment` (`risk_score, risk_level ∈ {LOW,MODERATE,HIGH,CRITICAL}, recommended_action, calibrated_fraud_probability, risk_factors: list[str], contributions: dict[str,float], policy_version`); `RiskEngine(policy)` with `assess(inputs: RiskInputs) -> RiskAssessment`; `calibrate_thresholds(scores, labels, review_budget_frac: float) -> dict[str,float]` (moderate/high/critical at the top-10%/top-budget/top-budget/4 validation-score quantiles, strictly increasing).
- Weights in `policy.yaml` (sum 1.0): ml_prob 0.35, anomaly 0.10, behaviour 0.15, graph 0.20, velocity 0.10, account_history 0.05, merchant_risk 0.05.
- Actions: LOW→ALLOW, MODERATE→MONITOR, HIGH→REVIEW, CRITICAL→VERIFY, or HOLD_RECOMMENDED only when `cluster_flagged` and level is CRITICAL.
- Cap: if every one of `ml_prob`, `graph` < 0.5 (no strong independent source), the level is capped at `single_source_cap`.

- [ ] **Step 1: Write failing tests:** `test_deterministic` (same inputs twice → equal outputs); `test_weights_applied_exactly` (hand-computed score for one input); `test_levels_follow_thresholds`; `test_anomaly_only_capped_at_high` (anomaly=behaviour=velocity=1, others 0 → level ≤ HIGH, action never HOLD_RECOMMENDED); `test_hold_requires_cluster`; `test_factors_name_the_drivers` (strings like "Behavioural deviation" present when behaviour contribution is the largest); `test_no_history_inputs_zero_does_not_raise_level` (all zeros → LOW); `test_bad_policy_fails_loudly` (parametrized: missing weight, weights sum 0.9, thresholds [0.5,0.4,0.9], threshold ≥ 1); `test_normaliser_percentile_and_bounds`; `test_calibrate_thresholds_increasing_and_budget`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** with `yaml.safe_load`; `risk_score = Σ weight·input`; contributions are `weight·input`; factor strings come from a fixed table keyed by component with a 0.25 contribution-share minimum.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: deterministic risk and decision engine`.

### Task 6: SHAP explanations

**Files:**
- Create: `backend/sentinel/models/explain.py`
- Test: `tests/test_explain.py`

**Interfaces:**
- Consumes: `TrainedBundle` (LightGBM at `bundle.lgbm`), `FEATURE_COLUMNS`.
- Produces: `explain_transaction(bundle, features_row: pd.Series, top_k: int = 5) -> dict` with `base_value: float, margin: float, contributions: list[{"feature": str, "value": float, "shap": float}]` sorted by `|shap|` desc, and `note: str` stating contributions describe the model's score, not causes; `global_importance(bundle, X: pd.DataFrame, max_rows: int = 2000) -> list[dict]` (`feature, mean_abs_shap`, desc).

- [ ] **Step 1: Write failing tests:** `test_additivity` (`base_value + Σ all shap ≈ raw model margin` to 1e-4, using `explain_transaction` with `top_k=len(FEATURE_COLUMNS)`); `test_contributions_sorted_and_top_k`; `test_global_importance_ranked_and_sampled` (never uses more than `max_rows`); `test_note_present`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** with `shap.TreeExplainer(bundle.lgbm)`; handle SHAP returning either a list or a single array for binary models.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: SHAP explanations`.

### Task 7: Scoring pipeline and the demo scenario check

**Files:**
- Create: `backend/sentinel/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Tasks 2–6 (`build_features`, `TrainedBundle.predict`, `BehaviourEngine.replay`, `window_indicators`, `find_clusters`, `RiskEngine`, `Normaliser`).
- Produces: `score_frame(df, bundle, engine: RiskEngine, normalisers: dict[str, Normaliser]) -> pd.DataFrame` aligned to `df.index` with columns `risk_score, risk_level, recommended_action, calibrated_fraud_probability, cluster_id, cluster_flagged` and the component inputs; `fit_normalisers(train_df, bundle) -> dict[str, Normaliser]` (fitted on the **train** slice only).
- Velocity input = normalised `txn_count_1h`; `account_history` = fraction of the account's prior transactions that scored HIGH+ (strictly before); `merchant_risk` = same for the merchant.

- [ ] **Step 1: Write failing tests on `generate(seed=42, n_accounts=300, days=20)` with a trained bundle:** `test_ring_rows_reach_review_or_above` (≥70% of `ring` rows in the test slice are HIGH+ with action REVIEW or stronger); `test_legit_unusual_flagged_for_review_but_never_hold` (≥60% of `legit_unusual` test rows are MONITOR or REVIEW, none are HOLD_RECOMMENDED, and none carry a fraud claim — assessment has no `confirmed` field); `test_low_risk_for_most_normal_rows` (≥90% of `normal` test rows are LOW/MODERATE); `test_point_in_time` (scores of the first N test rows unchanged when later rows are removed); `test_normalisers_fit_on_train_only`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement.** If a threshold above fails honestly (the harder data and weights need tuning), adjust **weights/thresholds in `policy.yaml`**, never the tests' expectations, and ledger a ruling with the measured before/after numbers.
- [ ] **Step 4: Run the suite**; expect PASS. Print the confusion of `scenario × risk_level` and keep it for `PROJECT_PROGRESS.md`.
- [ ] **Step 5: Commit** `feat: scoring pipeline and demo-scenario check`.

### Task 8: Persistence, audit and case workflow

**Files:**
- Create: `backend/sentinel/cases/__init__.py`, `backend/sentinel/cases/orm.py`, `backend/sentinel/cases/services.py`, `backend/sentinel/security.py`
- Modify: `backend/sentinel/db.py` (`init_db` registers the new tables)
- Test: `tests/test_cases.py`, `tests/test_security.py`

**Interfaces:**
- Produces ORM: `User(id, username unique, password_hash, role, business_id)`, `RiskAssessmentRow(txn_external_id unique, business_id, risk_score, risk_level, action, calibrated_fraud_probability, factors JSON, model_version, policy_version)`, `Alert(id, business_id, txn_external_id, level, status ∈ {open, in_review, closed})`, `Case(id, business_id, status ∈ {open, in_review, resolved_suspicious, resolved_cleared}, assignee_id)`, `CaseAlert`, `CaseNote(id, case_id, author_id, body, ts)`, `AuditLog(id, ts, business_id, actor, action, target, before JSON, after JSON)`.
- Security: `hash_password(pw: str) -> str` (argon2), `verify_password(pw, hash) -> bool`, `create_token(user, secret, ttl_minutes=60) -> str`, `decode_token(token, secret) -> dict` (raises `AuthError` on expired/tampered), `require_role(user_role, allowed: set[str]) -> None` (raises `Forbidden`).
- Services (all take a `Session` and an acting `User`, and always scope by `user.business_id`): `record_assessment(session, assessment_row)`; `create_alerts(session, business_id, assessments, min_level="HIGH") -> list[Alert]` (idempotent per transaction); `open_case(session, user, alert_ids) -> Case`; `add_note(session, user, case_id, body) -> CaseNote`; `approve_action(session, user, case_id, action: str) -> Case` (analyst/admin only; records the action as **approved recommendation**, executes nothing; `action ∈ {ALLOW, MONITOR, REVIEW, VERIFY, HOLD_RECOMMENDED}`); `resolve_case(session, user, case_id, outcome ∈ {suspicious, cleared})` (status only; never sets a fraud label); `audit(session, business_id, actor, action, target, before, after)`. There is no update or delete function for `AuditLog`.

- [ ] **Step 1: Write failing tests:** `test_password_hash_roundtrip_and_not_plaintext`; `test_token_expired_and_tampered_rejected`; `test_viewer_cannot_approve` (raises `Forbidden`, no `Case` change, no `AuditLog` row for success); `test_alert_creation_idempotent`; `test_case_lifecycle_writes_audit_entries` (open, note, approve, resolve → ordered audit rows with actor and before/after); `test_business_isolation` (user of business B cannot see, note on, or approve business A's case → raises `NotFound`; same `txn_external_id` string in two businesses coexists); `test_resolve_suspicious_never_sets_label` (transactions' `label` unchanged); `test_audit_has_no_mutation_api` (module exposes no `update_audit`/`delete_audit`).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement.** `RiskAssessmentRow.txn_external_id` uniqueness is per business (composite unique with `business_id`). Note: Day 1's `Account` primary key ignores `business_id`; do not build cross-business features on it here, and ledger that as deferred.
- [ ] **Step 4: Run**; expect PASS.
- [ ] **Step 5: Commit** `feat: cases, audit and security services`.

### Task 9: Secured API for alerts and cases

**Files:**
- Create: `backend/sentinel/api/__init__.py`, `backend/sentinel/api/app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 8 services/security.
- Produces: `create_app(engine, secret: str | None = None) -> FastAPI` (secret defaults to env `SENTINEL_JWT_SECRET`; the app refuses to start without one). Endpoints: `POST /auth/login` (form: username, password → `{access_token, token_type, role}`), `GET /alerts`, `POST /cases` (body `{alert_ids}`), `GET /cases/{id}`, `POST /cases/{id}/notes`, `POST /cases/{id}/approve-action` (body `{action}`), `POST /cases/{id}/resolve`, `GET /audit` (admin only). All except login require `Authorization: Bearer`; request bodies validated with pydantic; unknown ids → 404 (never 403 for another business's id).

- [ ] **Step 1: Write failing tests with `fastapi.testclient.TestClient` and an in-memory DB seeded by a helper:** `test_login_ok_and_bad_password_401`; `test_missing_or_tampered_token_401`; `test_viewer_gets_403_on_approve_and_no_state_change`; `test_analyst_full_flow_and_audit_visible_to_admin_only`; `test_cross_business_case_id_returns_404`; `test_invalid_action_422`; `test_app_refuses_without_secret`.
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** with FastAPI dependencies for current user and role checks; map `AuthError→401`, `Forbidden→403`, `NotFound→404`.
- [ ] **Step 4: Run the whole suite**; expect PASS.
- [ ] **Step 5: Commit** `feat: secured alerts and cases API`.

### Task 10: Day 2 gate

**Files:**
- Modify: `PROJECT_PROGRESS.md`

- [ ] **Step 1:** Run `pytest -q` (all green) and the real CLI plus a scored run on the default synthetic data; capture the `scenario × risk_level` table, the new model metrics, and the calibration comparison.
- [ ] **Step 2:** Update `PROJECT_PROGRESS.md`: Day 2 done, measured numbers only, remaining limitations (rate limiting not yet added; `Account` key ignores `business_id`; feature-engine speed), and the Day 3 starting point.
- [ ] **Step 3: Commit** `docs: day 2 verified`.
