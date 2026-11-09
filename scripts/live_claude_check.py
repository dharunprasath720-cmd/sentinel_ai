"""Run ONE real Claude investigation against the demo database and print what happened.

  python scripts/live_claude_check.py [--txn <external_id>] [--no-fallbacks]

Needs ANTHROPIC_API_KEY (environment or .env) and a built demo (python scripts/serve.py once).
Spends real API money (one Opus 5.5 call, plus one retry only if validation rejects the first).
Prints the report summary, whether the narrative came from the model, any fallback notes, the
citation-validation result and the token usage. Prompts and completions are never logged.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy.orm import Session  # noqa: E402

from sentinel.agent.agent import InvestigationAgent  # noqa: E402
from sentinel.agent.llm import AnthropicLLM  # noqa: E402
from sentinel.agent.report import validate_citations  # noqa: E402
from sentinel.agent.tools import ToolBox  # noqa: E402
from sentinel.cases.orm import RiskAssessmentRow, User  # noqa: E402
from sentinel.context import AppContext  # noqa: E402
from sentinel.db import make_engine  # noqa: E402
from sentinel.models.train import TrainedBundle  # noqa: E402


def main() -> None:
    for name in (".env",):
        p = ROOT / name
        if p.exists():
            for line in p.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    ap = argparse.ArgumentParser()
    ap.add_argument("--txn")
    ap.add_argument("--no-fallbacks", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    if not (ROOT / "demo.db").exists():
        sys.exit("No demo database. Run: python scripts/serve.py   (once, then stop it)")
    llm = AnthropicLLM.from_env()
    if llm is None:
        sys.exit("No Anthropic credentials found (set ANTHROPIC_API_KEY or run `ant auth login`).")
    llm.use_fallbacks = not args.no_fallbacks

    engine = make_engine(f"sqlite:///{(ROOT / 'demo.db').as_posix()}")
    ctx = AppContext(business_id="demo_biz", bundle=TrainedBundle.load(ROOT / "artifacts" / "demo"), llm=llm)
    with Session(engine) as s:
        user = s.query(User).filter_by(username="ana").one()
        txn = args.txn or (s.query(RiskAssessmentRow).filter_by(business_id="demo_biz")
                           .order_by(RiskAssessmentRow.risk_score.desc()).first().txn_external_id)
        report = InvestigationAgent(llm, ToolBox(s, ctx, user)).investigate(txn)
    print(f"\ntransaction: {txn}")
    print(f"narrative written by the model: {report.llm_narrative}")
    print(f"classification: {report.classification} | risk: {report.risk_assessment['risk_level']}")
    print(f"notes: {report.notes or 'none'}")
    print(f"citation violations: {validate_citations(report, set(report.evidence_ids)) or 'none'}")
    print(f"findings: model {len(report.model_findings)}, behaviour {len(report.behavioural_findings)}, "
          f"graph {len(report.graph_findings)}, supporting {len(report.supporting_evidence)}")
    print(f"\nsummary: {report.summary}")


if __name__ == "__main__":
    main()
