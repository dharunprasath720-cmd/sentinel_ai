"""CLI: python -m sentinel.models.run --dataset synthetic|paysim"""
import argparse
import json
import sys
from pathlib import Path

from sentinel.config import get_settings
from sentinel.ingestion.paysim import load_paysim
from sentinel.ingestion.synthetic import generate
from sentinel.models.train import TrainedBundle, train


def _fmt(v, digits: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def _report(bundle: TrainedBundle, meta: dict) -> str:
    L = [f"# Model report: {bundle.version}", "",
         f"Dataset: **{meta['dataset']}** ({meta['n_rows']} rows). "
         f"Chronological split 60/20/20. Review budget: the threshold is set on the validation "
         f"slice to flag about {meta['review_budget_frac']:.1%} of transactions there. The "
         "realised flag rate on the test slice (below) can differ: scores shift over time and "
         "ties at the threshold flag extra rows.", "",
         "## Splits", "", "| split | rows | fraud | rate | from | to |", "|---|---|---|---|---|---|"]
    for k, s in bundle.split_info.items():
        L.append(f"| {k} | {s['n']} | {s['n_positive']} | {s['positive_rate']:.2%} | "
                 f"{s['start'][:16]} | {s['end'][:16]} |")
    L += ["", "## Test-set comparison", "",
          "| model | precision | recall | F1 | PR-AUC | ROC-AUC | FPR | FNR | precision@review | test flag rate | latency ms/row (model only) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in bundle.metrics.items():
        L.append(f"| {name} | {_fmt(m['precision'])} | {_fmt(m['recall'])} | {_fmt(m['f1'])} | "
                 f"{_fmt(m['pr_auc'])} | {_fmt(m['roc_auc'])} | {_fmt(m['fpr'], 4)} | "
                 f"{_fmt(m['fnr'])} | {_fmt(m['precision_at_review'])} | "
                 f"{_fmt(m['flag_rate'], 4)} | {m['latency_ms']:.2f} |")
    L += ["", "## Confusion matrices (rows: actual, cols: predicted; [[TN, FP], [FN, TP]])", ""]
    for name, m in bundle.metrics.items():
        L.append(f"- **{name}** at threshold {m['threshold']:.4f}: `{m['confusion_matrix']}`")
    L += ["", "## Calibration (Brier score on test, lower is better)", ""]
    for name, m in bundle.metrics.items():
        if "brier_raw" in m:
            L.append(f"- **{name}**: raw {m['brier_raw']:.4f} -> calibrated {m['brier_calibrated']:.4f}")
    L += ["", "## Limitations", "",
          "- Metrics come from one time-ordered split of the stated dataset; no cross-dataset claim.",
          "- Isolation Forest scores are unsupervised anomaly ranks, not probabilities.",
          "- Undefined metrics are shown as n/a (e.g. no positives in the test slice)."]
    if meta["dataset"] == "synthetic":
        L.append("- Synthetic data reflects the generator's assumptions, including planted rings; "
                 "good scores here do not predict real-world performance.")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    s = get_settings()
    p = argparse.ArgumentParser(prog="sentinel.models.run")
    p.add_argument("--dataset", choices=["synthetic", "paysim"], default="synthetic")
    p.add_argument("--paysim-path", type=Path, default=s.data_dir / "raw" / "paysim.csv")
    p.add_argument("--max-rows", type=int, default=300_000,
                   help="paysim only: first N rows (by step) to keep memory/time laptop-safe")
    p.add_argument("--accounts", type=int, default=500)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--seed", type=int, default=s.seed)
    p.add_argument("--budget", type=float, default=0.01)
    p.add_argument("--out", type=Path, default=s.artifacts_dir)
    a = p.parse_args(argv)

    if a.dataset == "synthetic":
        df = generate(seed=a.seed, n_accounts=a.accounts, days=a.days)
    else:
        if not a.paysim_path.exists():
            print(f"PaySim file not found: {a.paysim_path}. Download it from Kaggle "
                  "(login required) and place it there.", file=sys.stderr)
            return 2
        df = load_paysim(a.paysim_path).sort_values("ts", kind="stable").head(a.max_rows)
        df = df.reset_index(drop=True)

    bundle = train(df, seed=a.seed, review_budget_frac=a.budget, dataset=a.dataset)
    run_dir = a.out / bundle.version
    bundle.save(run_dir)
    meta = {"dataset": a.dataset, "n_rows": int(len(df)), "review_budget_frac": a.budget}
    (run_dir / "metrics.json").write_text(json.dumps(
        {"version": bundle.version, **meta, "split_info": bundle.split_info,
         "thresholds": bundle.thresholds, "models": bundle.metrics}, indent=2))
    (run_dir / "report.md").write_text(_report(bundle, meta), encoding="utf-8")
    print(f"wrote {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
