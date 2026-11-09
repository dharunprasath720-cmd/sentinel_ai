"""End-to-end on the REAL scorer: build a demo world, replay a window containing a fraud ring through
the live service, and investigate an alert. Prints the measured numbers for the Day 3 gate."""
import numpy as np
import pytest
from sqlalchemy.orm import Session

from sentinel.agent.agent import InvestigationAgent
from sentinel.agent.report import validate_citations
from sentinel.agent.tools import ToolBox
from sentinel.cases.orm import Alert, RiskAssessmentRow, User
from sentinel.demo import build_demo, load_demo, load_truth
from sentinel.ingestion.orm import Transaction
from sentinel.live.bus import EventBus
from sentinel.live.service import LiveService
from sentinel.security import verify_password

HIGH = {"HIGH", "CRITICAL"}


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    url, art, env = f"sqlite:///{out / 'demo.db'}", out / "artifacts", out / ".env.demo"
    build_demo(url, art, env_file=env, seed=42, n_accounts=200, days=20, log=lambda *a: None)
    engine, ctx = load_demo(url, art)
    return engine, ctx, load_truth(art), env


@pytest.fixture(scope="module")
def streamed(demo):
    engine, ctx, truth, _ = demo
    svc = LiveService(engine, ctx, EventBus())
    frame = ctx.demo_frame.reset_index(drop=True)
    ring_pos = [i for i, e in enumerate(frame["external_id"]) if truth.loc[e, "scenario"] == "ring"]
    assert ring_pos, "the replay stream must contain a ring"
    lo, hi = max(0, ring_pos[0] - 60), min(len(frame), ring_pos[0] + 120)
    events = [svc.process(r) for r in frame.iloc[lo:hi].to_dict("records")]
    events = [e for e in events if e]
    lat = np.array([e["latency_ms"] for e in events])
    print(f"\nreplayed {len(events)} events; latency p50 {np.percentile(lat, 50):.0f} ms, "
          f"p95 {np.percentile(lat, 95):.0f} ms; alerts {sum(e['alert'] for e in events)}")
    return svc, events


def test_build_stores_random_passwords_only_as_hashes(demo):
    engine, _, _, env = demo
    lines = dict(l.split("=", 1) for l in env.read_text().splitlines() if "=" in l)
    assert len(lines["SENTINEL_JWT_SECRET"]) >= 32
    with Session(engine) as s:
        for user, key in (("ana", "ANA_PASSWORD"), ("vic", "VIC_PASSWORD"), ("adm", "ADM_PASSWORD")):
            row = s.query(User).filter_by(username=user).one()
            assert verify_password(lines[key], row.password_hash) and lines[key] not in row.password_hash
        assert len({lines[k] for k in ("ANA_PASSWORD", "VIC_PASSWORD", "ADM_PASSWORD")}) == 3


def test_loaded_context_is_complete_and_history_is_assessed(demo):
    engine, ctx, _, _ = demo
    assert ctx.bundle and ctx.live_scorer and ctx.risk_engine and ctx.business_id == "demo_biz"
    assert len(ctx.demo_frame) > 300 and ctx.model_version.startswith("demo-")
    assert "label" in ctx.demo_frame.columns and ctx.demo_frame["label"].isna().all()  # unknown at scoring time
    assert "scenario" not in ctx.demo_frame.columns
    with Session(engine) as s:
        assert s.query(Transaction).count() == s.query(RiskAssessmentRow).count() > 1000
        assert s.query(Alert).count() > 0


def test_ring_in_the_live_stream_is_noticed_early_and_never_causes_a_false_hold(demo, streamed):
    """Plumbing/design check on a deliberately SMALL, fast world (the model is weak here: ~28 fraud
    rows in train). Measured detection quality on the full 500x30 demo is in PROJECT_PROGRESS.md:
    68% of ring events HIGH+ overall, 86% once the cluster is flagged. Bars here are set from the
    small-world measurement (HIGH+ 54%, at least MODERATE 96%), with margin."""
    _, _, truth, _ = demo
    _, events = streamed
    ring = [e for e in events if truth.loc[e["external_id"], "scenario"] == "ring"]
    assert len(ring) >= 8
    high_plus = sum(e["risk_level"] in HIGH for e in ring) / len(ring)
    noticed = sum(e["risk_level"] != "LOW" for e in ring) / len(ring)
    first_flag = next(i for i, e in enumerate(ring) if e["cluster_id"])  # StopIteration = never flagged
    holds_on_legit = [e for e in events if e["recommended_action"] == "HOLD_RECOMMENDED"
                      and truth.loc[e["external_id"], "label"] == 0]
    print(f"ring events {len(ring)}: HIGH+ {high_plus:.2f}, at least MODERATE {noticed:.2f}, "
          f"cluster first flagged at ring event #{first_flag + 1}; holds on non-fraud rows: {len(holds_on_legit)}")
    assert first_flag < 10 and noticed >= 0.80 and high_plus >= 0.40
    assert holds_on_legit == []


def test_every_event_was_persisted_and_alerts_match_high_risk(demo, streamed):
    engine, ctx, _, _ = demo
    svc, events = streamed
    with Session(engine) as s:
        for e in events[:50]:
            row = s.query(RiskAssessmentRow).filter_by(business_id="demo_biz", txn_external_id=e["external_id"]).one()
            assert row.risk_level == e["risk_level"] and row.details["inputs"]
            has_alert = s.query(Alert).filter_by(business_id="demo_biz", txn_external_id=e["external_id"]).count() == 1
            assert has_alert == (e["risk_level"] in HIGH) == e["alert"]
    assert svc.metrics.snapshot()["processed"] == len(events)


def test_an_alert_from_the_stream_gets_a_grounded_report(demo, streamed):
    engine, ctx, truth, _ = demo
    _, events = streamed
    alerted = next(e for e in events if e["alert"] and truth.loc[e["external_id"], "scenario"] == "ring")
    with Session(engine) as s:
        user = s.query(User).filter_by(username="ana").one()
        report = InvestigationAgent(None, ToolBox(s, ctx, user)).investigate(alerted["external_id"])
    assert report.classification == "suspicious" and report.llm_narrative is False
    assert validate_citations(report, set(report.evidence_ids)) == []
    assert report.risk_assessment["risk_level"] in HIGH and report.recommended_next_steps
