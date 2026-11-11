# SENTINEL AI — Day 4 dashboard design

Status: approved in conversation 2026-11-11 (sections 1–3); this file is the written spec for review.
Builds on: `2026-11-09-sentinel-ai-design.md` (section 10, "Dashboard (5 pages)").

## 1. Purpose and success criteria

Give fraud analysts one web app on top of the existing API: see the portfolio, watch scoring live,
investigate a case, explore the graph, and ask the AI investigator, all against real data in the demo
database. Success means:

- All five pages work end to end against `scripts/serve.py` (no mock data, every control calls the API).
- A viewer can read everything but cannot change anything; analysts and admins can act. The server
  remains the authority; the UI only reflects it.
- Synthetic, PaySim and PayPal Sandbox data are never blended on screen. The wording is always
  "suspicious value", never "fraud loss". Holds are always "recommended"; nothing blocks automatically.
- `npm run build` + `serve.py` is the whole demo setup: one process, one URL (also works through the tunnel).

Out of scope: light theme, phone layout, i18n, user management, case reassignment, per-IP rate limiting
(already on the deferred list), any new model or scoring behaviour.

## 2. Architecture

```
browser (React SPA, hash routes)  --HTTP/JSON, Bearer-->  FastAPI (existing + new read endpoints)
        |                                                     |
        +-- fetch-streamed SSE (Authorization header) --------+  EventBus -> LiveService
```

- New folder `frontend/`: Vite + React + TypeScript + Tailwind, React Router (hash routing),
  TanStack Query, Recharts, `@xyflow/react` (React Flow), Framer Motion, Lucide. Exact versions are
  pinned in the implementation plan, using releases at least two weeks old.
- `serve.py` serves `frontend/dist` from the same address as the API when it exists, mounted after
  all API routes so API paths always win (`/docs` keeps working). Hash routing (`/#/cases`) is used
  because API paths such as `/cases` and `/alerts` would otherwise collide with page routes; no API
  route or existing test changes.
- During development Vite's dev server proxies API calls to the running backend.

## 3. New API endpoints (all read-only)

Every endpoint requires a valid bearer token, is scoped to the caller's business, is readable by all
roles, never returns `label`, caps its output and validates its parameters (422 on bad input).
`source` accepts only `synthetic`, `paysim`, `paypal_sandbox` and defaults to `synthetic`.
Where a ToolBox function already implements the query (transaction details, account history, risk,
related accounts, graph cluster, model explanation) the endpoint delegates to it.

| Endpoint | Returns |
|---|---|
| `GET /metrics/overview?source=` | transactions per risk level; open alerts; open cases; flagged clusters; total suspicious value (sum of amounts of HIGH and CRITICAL transactions); daily series (volume and HIGH+ count) |
| `GET /metrics/models` | model version, training dataset, held-out PR-AUC / recall / precision, calibration method, and a caveat string; sourced from the stored bundle, labelled "held-out evaluation" |
| `GET /transactions?source=&level=&limit=` | newest-first list with risk level, score, action; `limit` 1–200, default 50 |
| `GET /transactions/{id}` | transaction details, assessment with factors and policy/model versions, SHAP explanation, behaviour reasons, cluster id; 404 when the id is not in the caller's business |
| `GET /cases` | cases with status, alert count, approved action, newest first |
| `GET /graph/clusters?source=` | flagged clusters: id, account count, device/merchant counts, signals |
| `GET /graph?cluster=<id>` or `GET /graph?account=<id>&hours=<n>` | nodes (`id`, `kind` ∈ account/device/merchant, `label`, `risk_level`, `txn_count`) and edges (`source`, `target`, `kind`, `weight`); exactly one of `cluster`/`account` is required; `hours` 1–168, default 24; at most 200 nodes with `truncated: true` when cut |

Each endpoint is built test-first, including a two-business isolation test, an unauthenticated 401 test,
a viewer-can-read test and a "label never appears" test.

## 4. Frontend structure

- `src/api/` typed client; adds the token to every request; a 401 clears the session and returns to login.
- `src/auth/` login page, session holder (token in memory, mirrored to `sessionStorage`, never in
  `localStorage` or a URL), role helpers.
- `src/live/` stream hook: reads `/stream/events` with `fetch` and an `Authorization` header (the
  browser `EventSource` cannot set headers), parses SSE frames, reconnects with capped backoff, exposes
  connection state; the feed keeps the last 200 events.
- `src/pages/` Overview, LiveMonitoring, Investigation, GraphExplorer, Investigator.
- `src/components/` RiskBadge, MetricTile, DataTable, ConfirmDialog, EmptyState, ErrorState, Spinner.
- Global header: data-source selector (default synthetic; PayPal Sandbox visibly labelled), role badge,
  sign out.
- Theme: dark navy; font stack `'Quincy CF', 'Astralaga', Georgia, serif`. The two fonts are licensed
  and not bundled; the user installs them locally, otherwise the generic serif fallback is used.
- Roles: viewers get read-only pages (action controls hidden or disabled); a 403 from the server is
  still handled and shown plainly.
- Every list and chart has loading, empty and error states.

## 5. Pages

1. **Overview** — KPI tiles (transactions, open alerts, open cases, flagged clusters, suspicious value);
   risk-level distribution; daily volume vs HIGH+ chart; model panel showing PR-AUC, recall and precision
   together with the held-out caveat (accuracy never alone); recent alerts linking to Investigation.
2. **Live Monitoring** — simulator start/stop with speed and limit (analyst/admin only); live counters
   (processed, p50/p95 latency, dropped); feed of scored events with risk badges, HIGH+ highlighted,
   pause toggle, last 200 rows, row click opens Investigation; initial fill from `GET /transactions`.
3. **Investigation Workspace** — alerts and cases lists; select alerts and open a case; case detail with
   assessment, factors, SHAP bars, behaviour profile, related accounts; add note, approve action,
   resolve as suspicious/cleared, each behind a confirmation; audit timeline; "Generate AI report" shows
   cited findings with a badge for model-written vs deterministic fallback.
4. **Graph Explorer** — React Flow with account/device/merchant nodes coloured by risk; cluster list
   sidebar; account search; time-window filter; click a node to expand its neighbours via
   `GET /graph?account=`; a notice when the 200-node cap truncates.
5. **AI Investigator** — chat (analyst/admin only) showing the evidence each answer cites; clear messages
   for 503 (no model configured) and 502 (provider failure); a reply the server withholds for asserting
   fraud or an executed action is shown as a notice, not as text.

## 6. Error handling and security

- No secrets in the frontend; no token in URLs or logs; the API's existing CORS posture is unchanged
  (same-origin in production, dev proxy in development).
- Free text from the API (notes, report narrative) is rendered as text, never as HTML.
- Server errors are shown with their `detail` message where the API provides one; network failure shows
  a retry state, not a blank page.
- Destructive-looking actions (approve action, resolve) require a confirmation dialog naming what will
  happen; the audit log records them server-side as before.

## 7. Testing and verification

- Backend: pytest, RED first, for every new endpoint (section 3 list above). The full existing suite
  (379 tests) must stay green.
- Frontend: Vitest + Testing Library for the stream parser (frame splitting, keepalives, reconnect), the
  auth guard and 401 handling, the API client's error mapping, role-based control visibility, and
  RiskBadge/threshold rendering. Gate: type-check and production build succeed.
- End to end: run `serve.py`, log in with the demo users, exercise each page in the browser pane,
  including viewer vs analyst, simulator start/stop, opening and resolving a case, a graph expansion and
  an AI report; record what was and was not checked in `PROJECT_PROGRESS.md`.

## 8. Known risks

- Graph size: dense clusters can exceed 200 nodes; the cap and truncation notice are the mitigation.
- Fonts: Quincy CF / Astralaga must be installed locally; the fallback is a generic serif.
- Hash routing means page URLs contain `#`; accepted to avoid changing the API.
- Overview aggregates read the full transaction table; fine at demo scale (about 15k rows), and noted as
  a limit for larger data.
