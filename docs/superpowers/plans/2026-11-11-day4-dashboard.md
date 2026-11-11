# SENTINEL AI Day 4 Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add seven read-only API endpoints and a five-page React dashboard served by the existing FastAPI process, all working against the demo database.

**Architecture:** Query logic lives in `backend/sentinel/dashboard/queries.py` (reusing `ToolBox` for per-transaction and cluster reads); `backend/sentinel/api/dashboard.py` registers the routes inside `create_app`; `backend/sentinel/api/frontend.py` mounts `frontend/dist` last so API paths win. The frontend is a Vite + React + TypeScript SPA with hash routing, a typed API client, a fetch-based SSE hook and five pages.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pytest (existing); React, TypeScript, Vite, Tailwind, React Router (hash), TanStack Query, Recharts, `@xyflow/react`, Framer Motion, Lucide, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-11-11-dashboard-design.md` (read it first; it also names the parent spec `2026-11-09-sentinel-ai-design.md`).

## Global Constraints

- Every new endpoint: bearer token required (401), scoped to `user.business_id`, readable by all roles, never returns `label`, parameters validated (422), output capped.
- `source` ∈ `synthetic` | `paysim` | `paypal_sandbox`, default `synthetic`; sources are never blended.
- Risk levels in order: `LOW`, `MODERATE`, `HIGH`, `CRITICAL`; "HIGH+" = `HIGH` and `CRITICAL` (`sentinel.pipeline.HIGH_PLUS`).
- Wording: "suspicious value", never "fraud loss"; holds are "recommended", never automatic; no AI statement of fraud as fact.
- Font stack exactly `'Quincy CF', 'Astralaga', Georgia, serif`; dark navy theme; fonts are not bundled.
- Token held in memory and mirrored to `sessionStorage` only (never `localStorage`, never a URL); live stream read with `fetch` + `Authorization` header, not `EventSource`.
- Hash routing (`/#/...`); no existing API route or its tests change. The existing 379 tests stay green.
- Free text (notes, narratives, factors) is rendered as text, never as HTML.
- npm packages: exact versions (`--save-exact`), each a release at least 14 days old (check with `npm view <pkg> time --json`).
- Each endpoint, and each page, ends with its own commit. No secrets in the frontend.

## Review Focus

Failure modes the spec implies that no single task's happy path covers (each has a test in the owning task):

1. A `source` with no rows (e.g. `paypal_sandbox` before any webhook) must return zeros and empty lists, not errors or NaN (Task 1).
2. `GET /graph` with neither or both of `cluster`/`account`, an unknown account, or `hours` out of 1–168 must fail cleanly (404/422), never return an empty 200 that looks like a result (Task 4).
3. An SSE frame split across network chunks, CRLF line endings, keepalive comments and a malformed JSON frame must not crash or drop the next valid frame (Task 7).
4. A 401 on any call (expired token) must clear the session and return to login, and the stream must stop retrying on 401 instead of looping (Tasks 6, 7).
5. Text containing HTML (`<img src=x onerror=alert(1)>`) in a note or narrative must appear as literal text (Task 10).

---

## Task 1: Overview and model endpoints

**Files:**
- Create: `backend/sentinel/dashboard/__init__.py`, `backend/sentinel/dashboard/queries.py`, `backend/sentinel/api/dashboard.py`
- Modify: `backend/sentinel/api/app.py` (after `current_user` is defined, call `register_dashboard(app, get_session, current_user, context)`)
- Test: `tests/test_dashboard_api.py` (new; uses the session `world` fixture, `PW` from `conftest`, `make(world)` helper that builds `TestClient(create_app(db, secret=SECRET, context=AppContext(business_id="demo_biz", bundle=bundle)))`, and `auth(client, name)` like `tests/test_api_agent.py`)

**Interfaces:**
- Produces in `queries.py`: `Source = Literal["synthetic", "paysim", "paypal_sandbox"]`; `overview(session: Session, business_id: str, source: str) -> dict`; `models_summary(bundle) -> dict`.
- Produces in `api/dashboard.py`: `register_dashboard(app: FastAPI, get_session, current_user, context: AppContext | None) -> None`. Later tasks add routes inside it.
- `overview` returns `{"source", "transactions": {"total": int, "by_level": {"LOW": int, "MODERATE": int, "HIGH": int, "CRITICAL": int}}, "open_alerts": int, "open_cases": int, "flagged_clusters": int, "suspicious_value": float, "daily": [{"date": "YYYY-MM-DD", "transactions": int, "high_plus": int}]}`. Counts join `Transaction` (filtered by `source`) with `RiskAssessmentRow`; `suspicious_value` is the sum of `Transaction.amount` for HIGH+ rows; open alerts = `Alert.status == "open"` joined by transaction source; open cases = `Case.status in ("open","in_review")` having at least one alert on a transaction of that source; flagged clusters = distinct non-null `details["cluster_id"]`; `daily` groups by UTC date of `ts`, ascending.
- `models_summary(bundle)` returns `{"version", "evaluation": "held-out test split", "models": {name: {"pr_auc","roc_auc","precision","recall","f1","threshold","n_positive","calibrator","brier_raw","brier_calibrated"}}, "caveat": str}` built from `bundle.metrics` (keys absent for `iforest` calibration fields are `None`); `caveat` is a fixed sentence saying these are held-out numbers on synthetic data and that some suspicious activity is missed. Raises `ToolUnavailable`-style 503 in the route when the context has no bundle.
- Routes: `GET /metrics/overview?source=` and `GET /metrics/models`.

- [ ] **Step 1: Write the failing tests** in `tests/test_dashboard_api.py`: `test_overview_matches_independent_counts` (by_level sums equal `scored.risk_level.value_counts()`, `suspicious_value == df.loc[scored.risk_level.isin(HIGH_PLUS), "amount"].sum()` within 1e-6, `transactions.total == len(df)`, daily counts sum to total); `test_overview_empty_source_is_zeros` (`source=paypal_sandbox` gives total 0, all by_level 0, `suspicious_value == 0`, `daily == []`); `test_overview_validation_and_auth` (no token 401, `source=bogus` 422, viewer `vic` 200); `test_overview_is_business_scoped` (`bob` of `other_biz` sees total 0); `test_models_endpoint` (200 with keys `version`, `models.lightgbm.pr_auc`, `caveat`; 503 when the app is built without a bundle); `test_dashboard_responses_never_contain_label` (`"label"` not in response text of overview/models).
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_dashboard_api.py -q`. Expected: FAIL (404s / import error).
- [ ] **Step 3: Implement** `queries.overview`, `queries.models_summary`, `register_dashboard` and the two routes (`source: Source = "synthetic"` as the query parameter type gives the 422); call `register_dashboard` from `create_app`.
- [ ] **Step 4: Run** the new tests plus `python -m pytest -q`. Expected: all pass (379 existing + new).
- [ ] **Step 5: Commit** `git add backend tests && git commit -m "feat(api): overview and model metrics endpoints"`.

## Task 2: Transaction list and transaction detail

**Files:**
- Modify: `backend/sentinel/dashboard/queries.py`, `backend/sentinel/api/dashboard.py`
- Test: `tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: `register_dashboard`, `Source` (Task 1); `ToolBox(session, context, user)` from `sentinel.agent.tools` (methods `get_transaction_details`, `get_transaction_risk`, `get_model_explanation`, `get_related_accounts`; they raise `NotFound` for ids outside the business and `ToolUnavailable` when no model is loaded).
- Produces: `recent_transactions(session: Session, business_id: str, source: str, level: str | None, limit: int) -> list[dict]` newest-first (`ts` desc, then `external_id` desc), each item `{"external_id","ts","amount","account_id","merchant_id","source","risk_level","risk_score","action","cluster_id"}`; routes `GET /transactions?source=&level=&limit=` (`level` is a `Literal` of the four levels, `limit` is `Query(50, ge=1, le=200)`) and `GET /transactions/{id}` returning `{"details": <get_transaction_details>, "risk": <get_transaction_risk or None when NotFound>, "explanation": <get_model_explanation or None>, "explanation_unavailable": <str or None>, "related": <get_related_accounts or None>}`. An unknown or other-business id is 404.

- [ ] **Step 1: Write the failing tests:** `test_transactions_list_order_filter_limit` (descending `ts`, `level=CRITICAL` returns only CRITICAL, `limit=3` returns 3, `limit=0` and `limit=201` are 422); `test_transactions_list_source_and_scope` (`paypal_sandbox` → `[]`; `bob` → `[]`); `test_transaction_detail_has_all_parts` (for a HIGH+ ring transaction picked with `pick(world, "ring", HIGH_PLUS)`: `risk.risk_level` matches, `explanation.contributions` non-empty, `related` present); `test_transaction_detail_404_and_scope` (unknown id 404, `bob` 404, no token 401); `test_transaction_detail_without_model` (app built without a bundle → 200 with `explanation is None` and a non-empty `explanation_unavailable`); `test_transaction_endpoints_never_expose_label`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** both queries/routes; the detail route builds a `ToolBox` and maps exceptions as specified.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(api): transaction list and detail endpoints`.

## Task 3: Case list

**Files:**
- Modify: `backend/sentinel/dashboard/queries.py`, `backend/sentinel/api/dashboard.py`
- Test: `tests/test_dashboard_api.py`

**Interfaces:**
- Produces: `list_cases(session: Session, business_id: str) -> list[dict]` newest-first by `Case.id` desc, items `{"id","status","approved_action","n_alerts","created_at"}` (`created_at` ISO string); route `GET /cases` (registered in `dashboard.py`; the existing `GET /cases/{case_id}` is unchanged).
- Consumes: `services.open_case(session, user, alert_ids)` to build test data.

- [ ] **Step 1: Write the failing tests:** `test_cases_list_shape_and_order` (open two cases through `POST /cases` as `ana`; list returns both newest first with correct `n_alerts`); `test_cases_list_scope_and_auth` (`bob` sees `[]`, no token 401, viewer 200); `test_case_detail_route_still_works` (`GET /cases/{id}` unchanged).
- [ ] **Step 2: Run.** Expected: FAIL (`GET /cases` is a 405 today).
- [ ] **Step 3: Implement** query and route.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(api): case list endpoint`.

## Task 4: Graph endpoints

**Files:**
- Modify: `backend/sentinel/dashboard/queries.py`, `backend/sentinel/api/dashboard.py`
- Test: `tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: `ToolBox.get_graph_cluster(cluster_id)` (returns `accounts`, `devices`, `merchants`, `signals`, `risk_indicator`, `flagged`, `evidence_transactions`; `NotFound` for unknown ids); `LEVELS` from `sentinel.risk.engine`.
- Produces: `flagged_clusters(session, business_id, source, toolbox, limit=20) -> list[dict]` items `{"cluster_id","n_accounts","n_devices","n_merchants","signals","risk_indicator"}` for the most recent distinct `details["cluster_id"]` values whose assessed transactions have the given source; `graph_for_cluster(session, business_id, toolbox, cluster_id) -> dict`; `graph_for_account(session, business_id, source, account_id, hours) -> dict`; routes `GET /graph/clusters?source=` and `GET /graph?cluster=|account=&hours=`.
- Graph payload: `{"nodes": [{"id": "account:ACC_1", "kind": "account"|"device"|"merchant", "label": str, "risk_level": str | None, "txn_count": int}], "edges": [{"source": node_id, "target": node_id, "kind": "uses_device"|"pays_merchant", "weight": int}], "truncated": bool}`. Node `risk_level` is the highest level among the assessments of that node's transactions in scope. Cluster mode uses the transactions in `evidence_transactions`; account mode uses the account's transactions in the `hours` window ending at the account's latest transaction, plus every transaction in that window (same business and source) sharing one of its devices or merchants. At most 200 nodes: keep the root account first, then others by descending `txn_count`; edges whose endpoint is dropped are removed; `truncated` is true when anything was dropped. Exactly one of `cluster`/`account` is required (422 otherwise); `hours` is `Query(24, ge=1, le=168)`; an unknown cluster or account is 404.

- [ ] **Step 1: Write the failing tests:** `test_graph_clusters_lists_flagged_ring_clusters` (non-empty on the world data, each item has the listed keys); `test_graph_for_cluster_has_ring_accounts_and_edges` (for a ring cluster id from the list: node kinds include account/device/merchant, every edge endpoint exists in `nodes`, `len(nodes) <= 200`); `test_graph_for_account` (a ring account returns itself as a node and its device node); `test_graph_parameter_validation` (neither param 422, both params 422, `hours=0` and `hours=169` 422, unknown account 404, unknown cluster 404); `test_graph_truncates_at_200_nodes` (monkeypatch the node cap constant to 3 and assert `truncated is True`, root account kept, no dangling edges); `test_graph_scope_and_auth` (`bob` gets 404 for a `demo_biz` account, no token 401).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** with a module constant `MAX_GRAPH_NODES = 200` so the test can patch it.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(api): graph cluster and neighbourhood endpoints`.

## Task 5: Serve the built frontend

**Files:**
- Create: `backend/sentinel/api/frontend.py`
- Modify: `scripts/serve.py` (call `mount_frontend(app, ROOT / "frontend" / "dist")` on the app returned by `create_app`, before `uvicorn.run`, and print one line saying whether the dashboard is being served or `npm run build` is needed)
- Test: `tests/test_frontend_mount.py`

**Interfaces:**
- Produces: `mount_frontend(app: FastAPI, dist_dir: Path) -> bool` — mounts `StaticFiles(directory=dist_dir, html=True)` at `/` and returns `True` only if `dist_dir/index.html` exists; otherwise mounts nothing and returns `False`. Must be called after all routes are registered.

- [ ] **Step 1: Write the failing tests:** `test_mount_serves_index_and_api_still_wins` (tmp dist with `index.html`; `GET /` returns it; `GET /alerts` without a token is still 401; `GET /docs` still 200); `test_mount_returns_false_when_no_build` (empty tmp dir → `False`, `GET /` is 404).
- [ ] **Step 2: Run** `python -m pytest tests/test_frontend_mount.py -q`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** `mount_frontend` and the `serve.py` call.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(api): serve built dashboard from the API process`.

## Task 6: Frontend scaffold, theme, API client, session, shell

**Files:**
- Create: `frontend/` Vite React-TS project (`package.json`, `tsconfig*.json`, `vite.config.ts` with a dev proxy of `/auth`, `/alerts`, `/cases`, `/audit`, `/agent`, `/stream`, `/metrics`, `/transactions`, `/graph`, `/simulate` to `http://127.0.0.1:8000`, Vitest `jsdom` environment, `index.html`), `src/main.tsx`, `src/App.tsx`, `src/theme.css`, `src/api/{client.ts,types.ts}`, `src/auth/{session.tsx,Login.tsx,roles.ts}`, `src/components/{Shell.tsx,SourceSelector.tsx,RiskBadge.tsx,MetricTile.tsx,EmptyState.tsx,ErrorState.tsx,Spinner.tsx,ConfirmDialog.tsx}`, `src/source.tsx`
- Modify: `.gitignore` (add `frontend/node_modules/`, `frontend/dist/`)
- Test: `frontend/src/api/client.test.ts`, `frontend/src/auth/session.test.tsx`, `frontend/src/components/RiskBadge.test.tsx`

**Interfaces:**
- Produces: `class ApiError extends Error { status: number; detail: string }`; `createClient(opts: { getToken: () => string | null; onUnauthorized: () => void; fetchImpl?: typeof fetch; baseUrl?: string }): { get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T>; post<T>(path: string, body?: unknown): Promise<T> }` — adds `Authorization: Bearer`, serialises JSON, maps non-2xx to `ApiError` using the response `detail` (string, or `"Invalid request"` when `detail` is not a string), calls `onUnauthorized` on 401 before throwing; `Role = "viewer" | "analyst" | "admin"`; `canAct(role: Role | null): boolean` (analyst or admin); `SessionProvider` and `useSession(): { token: string | null; role: Role | null; username: string | null; login(username: string, password: string): Promise<void>; logout(): void; client: ApiClient }` persisting `{token, role, username}` under `sentinel.session` in `sessionStorage` inside try/catch; `useSource(): { source: Source; setSource(s: Source): void }` with `Source = "synthetic" | "paysim" | "paypal_sandbox"`, default `"synthetic"`; `RiskBadge({ level })` mapping the four levels to distinct text labels (never colour alone); route table in `App.tsx` using `HashRouter`: `/` Overview, `/live`, `/investigation` and `/investigation/:txnId`, `/graph`, `/investigator`, `/login`, with unauthenticated users redirected to `/login`. Pages are stubs showing their title until Tasks 8–12.
- Types in `types.ts` mirror the response shapes in Tasks 1–4 and the existing endpoints (`Alert`, `CaseSummary`, `CaseDetail`, `Overview`, `ModelsSummary`, `TxnListItem`, `TxnDetail`, `GraphPayload`, `LiveEvent` with the fields published by `LiveService`, `LiveMetrics`, `InvestigationReport`, `AuditEntry`).

- [ ] **Step 1: Pick and install versions.** For `vite`, `react`, `react-dom`, `typescript`, `tailwindcss` (+ its Vite plugin), `react-router-dom`, `@tanstack/react-query`, `recharts`, `@xyflow/react`, `framer-motion`, `lucide-react`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom` run `npm view <pkg> time --json`, choose the newest release at least 14 days old, and `npm install --save-exact`. Expected: `npm ls` shows no errors; record the chosen versions in the commit message.
- [ ] **Step 2: Write the failing tests:** `client.test.ts` — `attaches the bearer token`, `maps 403 detail to ApiError`, `401 calls onUnauthorized once then throws`, `non-string detail becomes "Invalid request"`; `session.test.tsx` — `login stores session in sessionStorage only` (assert `localStorage` untouched), `logout clears it`, `a 401 from any call logs out`; `RiskBadge.test.tsx` — `shows the level text for each level`; roles — `canAct` truthy for analyst/admin, falsy for viewer/null.
- [ ] **Step 3: Run** `npm test --prefix frontend -- --run`. Expected: FAIL.
- [ ] **Step 4: Implement** the files above. `theme.css` defines CSS variables for the dark navy palette and `font-family: 'Quincy CF', 'Astralaga', Georgia, serif` on `body`. `Shell` has the header (title, `SourceSelector` with PayPal Sandbox visibly labelled, role badge, sign out) and a nav to the five pages.
- [ ] **Step 5: Run** `npm test --prefix frontend -- --run`, `npx tsc --noEmit -p frontend`, `npm run build --prefix frontend`. Expected: tests pass, no type errors, `frontend/dist/index.html` exists.
- [ ] **Step 6: Commit** `feat(frontend): scaffold, theme, api client, session, app shell`.

## Task 7: Live stream hook

**Files:**
- Create: `frontend/src/live/sse.ts`, `frontend/src/live/useLiveStream.ts`
- Test: `frontend/src/live/sse.test.ts`, `frontend/src/live/useLiveStream.test.tsx`

**Interfaces:**
- Consumes: `LiveEvent`, `Role` types (Task 6).
- Produces: `class SseParser { push(text: string): unknown[] }` — accepts arbitrary text chunks, handles `\n` and `\r\n`, joins multi-line `data:` fields, ignores `:`-prefixed comment lines, returns parsed JSON objects for each completed frame and silently skips a frame whose JSON is invalid; `useLiveStream(opts: { token: string | null; onUnauthorized: () => void; maxRows?: number; fetchImpl?: typeof fetch }): { events: LiveEvent[]; state: "connecting" | "open" | "reconnecting" | "closed"; paused: boolean; setPaused(p: boolean): void; clear(): void }` — `fetch('/stream/events', { headers: { Authorization } , signal })`, reads the body with a `TextDecoder` stream, newest event first, keeps at most `maxRows` (default 200), reconnects with delays 1s doubling to a 15s cap, on HTTP 401 sets state `"closed"`, calls `onUnauthorized` and does not reconnect; while `paused` new events are dropped from the visible list but the connection stays open; aborts on unmount.

- [ ] **Step 1: Write the failing tests:** `sse.test.ts` — `splits a frame across chunks`, `handles CRLF`, `joins multi-line data`, `ignores keepalive comments`, `skips malformed JSON and still parses the next frame`; `useLiveStream.test.tsx` — `delivers events newest first and caps at maxRows`, `401 closes without retrying and calls onUnauthorized`, `network error reconnects with backoff` (fake timers), `paused hides new events`, `aborts on unmount`.
- [ ] **Step 2: Run** `npm test --prefix frontend -- --run live`. Expected: FAIL.
- [ ] **Step 3: Implement** both files.
- [ ] **Step 4: Run** the same command plus `npx tsc --noEmit -p frontend`. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): fetch-based live stream hook with tested SSE parser`.

## Task 8: Overview page

**Files:**
- Create: `frontend/src/pages/Overview.tsx`
- Modify: `frontend/src/App.tsx` (replace the stub)
- Test: `frontend/src/pages/Overview.test.tsx`

**Interfaces:**
- Consumes: `useSession().client`, `useSource()`, `Overview` and `ModelsSummary` types, `MetricTile`, `EmptyState`, `ErrorState`, `Spinner`; endpoints `GET /metrics/overview`, `GET /metrics/models`, `GET /alerts?status=open`.
- Produces: `Overview` page: five `MetricTile`s (transactions, open alerts, open cases, flagged clusters, suspicious value labelled "suspicious value"), a risk-level distribution bar chart and a daily volume vs HIGH+ line chart (Recharts), a model panel listing PR-AUC, recall and precision together for each model plus the `caveat` text, and the ten newest open alerts each linking to `#/investigation/<txn id>`. Query keys include `source`.

- [ ] **Step 1: Write the failing tests** (mock `client`): `shows tiles from the response`, `shows loading then content`, `shows the empty state when total is 0` (no NaN text on the page), `shows the error state with the server detail on failure`, `model panel shows recall next to PR-AUC and the caveat`, `changing source refetches with the new source`.
- [ ] **Step 2: Run** `npm test --prefix frontend -- --run Overview`. Expected: FAIL.
- [ ] **Step 3: Implement** the page.
- [ ] **Step 4: Run** tests, `tsc`, build. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): overview page`.

## Task 9: Live Monitoring page

**Files:**
- Create: `frontend/src/pages/LiveMonitoring.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/pages/LiveMonitoring.test.tsx`

**Interfaces:**
- Consumes: `useLiveStream`, `canAct`, `useSession()`, endpoints `GET /transactions?source=&limit=50` (initial fill), `GET /metrics/live` (polled every 2s), `POST /simulate/start` `{speed, limit}`, `POST /simulate/stop`.
- Produces: `LiveMonitoring` page: counters (processed, p50, p95, dropped, simulator running/sent/errors), connection-state indicator, pause/resume toggle, event table (time, account, amount, `RiskBadge`, action, cluster) with HIGH+ rows highlighted, row click navigates to `#/investigation/<external_id>`; simulator form (speed 1–1000, limit 1–100000, validated client-side) shown only when `canAct(role)`; a 409 from start shows "A replay is already running"; 503 shows the server detail.

- [ ] **Step 1: Write the failing tests:** `renders initial transactions then live events on top`, `HIGH+ rows are marked and a click navigates`, `viewer sees no simulator controls`, `analyst start posts speed and limit`, `invalid speed blocks the request`, `409 shows the already-running message`, `pause stops new rows appearing`, `counters render from /metrics/live`.
- [ ] **Step 2: Run** `npm test --prefix frontend -- --run LiveMonitoring`. Expected: FAIL.
- [ ] **Step 3: Implement** the page.
- [ ] **Step 4: Run** tests, `tsc`, build. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): live monitoring page`.

## Task 10: Investigation Workspace

**Files:**
- Create: `frontend/src/pages/Investigation.tsx`, `frontend/src/pages/investigation/{CaseList.tsx,TransactionPanel.tsx,CasePanel.tsx,ReportPanel.tsx}`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/pages/Investigation.test.tsx`

**Interfaces:**
- Consumes: `canAct`, `ConfirmDialog`, `RiskBadge`; endpoints `GET /alerts`, `GET /cases`, `GET /cases/{id}`, `POST /cases` `{alert_ids}`, `POST /cases/{id}/notes` `{body}`, `POST /cases/{id}/approve-action` `{action}` (`ALLOW|MONITOR|REVIEW|VERIFY|HOLD_RECOMMENDED`), `POST /cases/{id}/resolve` `{outcome}` (`suspicious|cleared`), `GET /audit` (filter client-side to entries whose `target === "case:<id>"`), `GET /transactions/{id}`, `POST /agent/report/{txn}`.
- Produces: the page with a left list (alerts tab with checkboxes + "Open case" and cases tab); `TransactionPanel` (details, risk factors, SHAP contribution bars from `explanation.contributions`, behaviour reasons, related accounts, an "explanations unavailable" notice when `explanation_unavailable` is set); `CasePanel` (assessment per alert, notes list and add-note form, approve-action select and resolve buttons each behind `ConfirmDialog` stating exactly what will happen, audit timeline); `ReportPanel` (summary, findings with their evidence ids, contradictory evidence, missing information, next steps, a badge "model-written" vs "deterministic fallback" from `llm_narrative`, and `notes`). Action controls are hidden for viewers; a 403/409 shows the server detail. `#/investigation/:txnId` opens the transaction panel for that id; all user/model text is rendered as text.

- [ ] **Step 1: Write the failing tests:** `lists alerts and opens a case from selected alerts`, `transaction panel shows factors and SHAP bars`, `unavailable explanation shows a notice`, `viewer sees no action buttons`, `resolve requires confirmation naming the outcome` (cancel sends nothing, confirm posts), `409 on a resolved case shows the server detail`, `report shows the model-written vs fallback badge`, `HTML in a note and in a report summary renders as literal text` (assert the literal string `<img src=x onerror=alert(1)>` appears and no `img` element exists), `audit timeline shows only this case`.
- [ ] **Step 2: Run** `npm test --prefix frontend -- --run Investigation`. Expected: FAIL.
- [ ] **Step 3: Implement** the page and panels.
- [ ] **Step 4: Run** tests, `tsc`, build. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): investigation workspace`.

## Task 11: Graph Explorer

**Files:**
- Create: `frontend/src/pages/GraphExplorer.tsx`, `frontend/src/pages/graph/{layout.ts,GraphCanvas.tsx}`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/pages/graph/layout.test.ts`, `frontend/src/pages/GraphExplorer.test.tsx`

**Interfaces:**
- Consumes: `GraphPayload` type, endpoints `GET /graph/clusters`, `GET /graph?cluster=`, `GET /graph?account=&hours=`.
- Produces: `layoutGraph(g: GraphPayload): { nodes: FlowNode[]; edges: FlowEdge[] }` (pure, deterministic: nodes placed on three columns by `kind` and ordered by id) and `mergeGraphs(a: GraphPayload, b: GraphPayload): GraphPayload` (union by node id and by edge `source|target|kind`, `truncated` is the OR); `GraphExplorer` with a cluster list sidebar, account search box, hours select (1, 6, 24, 72, 168), React Flow canvas with node colour **and** text label by `risk_level` and node shape/icon by `kind`, a "graph truncated at 200 nodes" notice when `truncated`, and click-to-expand on an account node that fetches `GET /graph?account=` and merges the result.

- [ ] **Step 1: Write the failing tests:** `layout.test.ts` — `layout is deterministic and keeps every edge endpoint`, `mergeGraphs unions nodes and edges without duplicates`; `GraphExplorer.test.tsx` — `shows clusters and loads one on click`, `search loads the account neighbourhood`, `unknown account shows the 404 detail`, `truncated notice appears`, `clicking an account node expands and merges` (mock React Flow's canvas as a list of buttons if needed), `empty cluster list shows the empty state`.
- [ ] **Step 2: Run** `npm test --prefix frontend -- --run graph` and `GraphExplorer`. Expected: FAIL.
- [ ] **Step 3: Implement** the files.
- [ ] **Step 4: Run** tests, `tsc`, build. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): graph explorer`.

## Task 12: AI Investigator chat

**Files:**
- Create: `frontend/src/pages/Investigator.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/pages/Investigator.test.tsx`

**Interfaces:**
- Consumes: `canAct`, `POST /agent/chat` `{messages: [{role, content}]}` (response shape as returned by `InvestigationAgent.chat`: read `backend/sentinel/agent/agent.py` to type it before writing `types.ts` additions).
- Produces: `Investigator` page: message list, input (max 8000 chars, the server's limit), send posts the whole conversation ending with the user turn; shows the cited evidence ids under each assistant reply; a reply the server withheld (as signalled by the chat response) is shown as a notice, not as message text; 503 → "No language model is configured"; 502 → "The language model request failed. Try again."; viewers see an explanation and no input; replies are rendered as text.

- [ ] **Step 1: Write the failing tests:** `sends the full conversation ending with the user turn`, `shows citations under a reply`, `withheld reply is a notice`, `503 and 502 show their messages`, `viewer sees no input`, `reply containing HTML renders literally`, `input over 8000 chars is blocked`.
- [ ] **Step 2: Run** `npm test --prefix frontend -- --run Investigator`. Expected: FAIL.
- [ ] **Step 3: Implement** the page.
- [ ] **Step 4: Run** tests, `tsc`, build. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontend): ai investigator chat`.

## Task 13: End-to-end verification and docs

**Files:**
- Modify: `PROJECT_PROGRESS.md`
- Create: `docs/superpowers/day4-verification.md` (what was checked, with results)

**Interfaces:**
- Consumes: everything above; demo logins `ana`/`vic`/`adm` from `.env.demo` (read passwords from the file; never print them).

- [ ] **Step 1: Full automated gates.** Run `.venv\Scripts\python -m pytest -q`, `npm test --prefix frontend -- --run`, `npx tsc --noEmit -p frontend`, `npm run build --prefix frontend`. Expected: all pass; record counts.
- [ ] **Step 2: Start the app** with `.venv\Scripts\python scripts\serve.py` (it should say the dashboard is being served) and open `http://127.0.0.1:8000/` in the browser pane.
- [ ] **Step 3: Walk every page as `ana`:** login, Overview numbers match `/metrics/overview`, start the simulator and watch rows arrive with p50/p95 counters, open a case from a HIGH+ alert, add a note, approve an action, resolve it, generate an AI report, open the Graph Explorer cluster and expand an account, ask the investigator a question. Record each result and any defect found; fix defects with a failing test first.
- [ ] **Step 4: Walk as `vic` (viewer):** every page loads, no action controls appear, a direct API write returns 403.
- [ ] **Step 5: Check the failure cases:** wrong password, an expired/invalid token (edit `sessionStorage`) returns to login, switching source to PayPal Sandbox shows the PayPal row(s) only and empty states elsewhere, mobile-width is out of scope (note only).
- [ ] **Step 6: Update `PROJECT_PROGRESS.md`** with a Day 4 section: what is built, what was verified in the browser, test counts, and what was not checked (e.g. fonts not installed → fallback seen, any untested control). Write `day4-verification.md` with the same facts.
- [ ] **Step 7: Commit** `docs: day 4 dashboard verification and progress`.
