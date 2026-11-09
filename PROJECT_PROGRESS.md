# SENTINEL AI — Project Progress

Deadline: 4 days from 2026-11-09. Approach: thin vertical slice, then deepen.
Spec: `docs/superpowers/specs/2026-11-09-sentinel-ai-design.md` · Day 1 plan: `docs/superpowers/plans/2026-11-09-day1-data-and-ml.md`

## Run it

```
py -3.11 -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt   # Python 3.11.4 used
.venv\Scripts\python -m pytest                                                      # 49 tests
set PYTHONPATH=backend && .venv\Scripts\python -m sentinel.models.run --dataset synthetic
```

## Day 1 — data layer, features, ML baselines: DONE (verified 2026-11-09)

**Verified by running, not by reading:**
- `pytest`: **49 passed**, no warnings. Environment check: Python 3.11.4, pandas 3.1.1, scikit-learn 1.9.1, lightgbm 4.7.0, shap 0.51.0, SQLAlchemy 2.1.8, pydantic 2.14.3.
- Re-running the CLI with seed 42 reproduces `metrics.json` exactly (ignoring latency and version string).
- Leakage test: features of the first N rows are identical whether or not later rows exist; flipping `label`/`scenario` changes no feature.

**Measured, synthetic data (15,504 rows, 500 accounts x 30 days, fraud 2.03%), chronological 60/20/20, test slice:**

| model | precision | recall | F1 | PR-AUC | FPR | FNR | latency ms/row |
|---|---|---|---|---|---|---|---|
| logreg | 1.000 | 0.825 | 0.904 | 0.997 | 0.0000 | 0.175 | 2.45 |
| lightgbm | 1.000 | 0.889 | 0.941 | 1.000 | 0.0000 | 0.111 | 1.68 |
| iforest | 0.920 | 0.365 | 0.523 | 0.760 | 0.0007 | 0.635 | 20.40 |

Splits hold 183 / 69 / 63 fraud rows (train / val / test). Review threshold flags ~1% of validation transactions. Full report: `artifacts/<version>/report.md` (git-ignored).

## Known problems — read before trusting these numbers

1. **The synthetic fraud is too easy.** LightGBM PR-AUC 1.000 means the planted rings and bursts (large amounts, odd hours, new merchants) are trivially separable. The spec requires a demo that is not unrealistically easy. **Day 2 first task:** make fraud overlap normal behaviour (normal-sized amounts, daytime hours, some takeover bursts that look like legit bursts) so the graph and behaviour engines add value, then re-run the report.
2. **Isotonic calibration made Brier worse** (lightgbm 0.0004 raw -> 0.0040 calibrated; logreg 0.0012 -> 0.0022). Likely cause: the validation slice has few positives (69) and a shifted score distribution. Do not ship calibrated probabilities as "calibrated" until re-checked on the harder dataset (consider Platt scaling or more validation data).
3. **PaySim not evaluated.** Only a hand-written fixture in PaySim's column layout was tested; the real file needs a Kaggle login and goes in `data/raw/paysim.csv`.
4. **Plan deviations** (also in the ledger): generator rebuilt so fraud events are spread over time (random placement left val/test with 0–6 fraud rows); ring size 5 accounts x 5–6 txns instead of 6 x 10–12. `precision_at_review` equals `precision` by construction.
5. Isolation Forest single-row latency is 20 ms — fine for the demo, slow for high volume.
6. Docker/Postgres paths are untested on this machine (neither installed).

## Roadmap

| Day | Target | Status |
|---|---|---|
| 1 | Scaffold, data, ingestion, features, ML + eval | **done** |
| 2 | Harder synthetic data, graph, behaviour, risk, SHAP, auth/cases | not started |
| 3 | Claude agent, SSE, PayPal Sandbox live | not started |
| 4 | Dashboard (5 pages), tests, README, demo video | not started |

## Needed from the user (Day 3 at the latest)
`ANTHROPIC_API_KEY`; PayPal Sandbox Client ID/Secret + webhook ID (and a public tunnel for webhooks). Optional: PaySim CSV from Kaggle.
