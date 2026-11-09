import asyncio
import threading

import pytest

from live_fakes import FakeScorer, record
from sentinel.cases.orm import Alert, RiskAssessmentRow
from sentinel.context import AppContext
from sentinel.db import init_db, make_engine, session_scope
from sentinel.ingestion.orm import Transaction
from sentinel.live.bus import EventBus
from sentinel.live.service import LiveService


def make(db_url="sqlite:///:memory:"):
    eng = make_engine(db_url)
    init_db(eng)
    bus = EventBus()
    ctx = AppContext(business_id="A", live_scorer=FakeScorer(), model_version="m-1")
    return eng, bus, ctx, LiveService(eng, ctx, bus)


def counts(eng):
    with session_scope(eng) as s:
        return (s.query(Transaction).count(), s.query(RiskAssessmentRow).count(), s.query(Alert).count())


def test_event_bus_isolates_businesses_and_cleans_up_on_close():
    async def main():
        bus = EventBus()
        a, b = bus.subscribe("A"), bus.subscribe("B")
        t = threading.Thread(target=bus.publish, args=("A", {"n": 1}))  # publishers are threads
        t.start(); t.join()
        assert await asyncio.wait_for(a.get(), 1) == {"n": 1}
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(b.get(), 0.2)  # business B never sees A's event
        assert bus.subscriber_count("A") == 1
        a.close(); b.close()
        assert bus.subscriber_count("A") == 0 and bus.subscriber_count("B") == 0
    asyncio.run(main())


def test_full_queue_drops_and_counts_instead_of_blocking():
    async def main():
        bus = EventBus(maxsize=2)
        sub = bus.subscribe("A")
        for i in range(5):
            bus.publish("A", {"n": i})
        await asyncio.sleep(0.05)
        assert bus.dropped == 3 and sub.queue.qsize() == 2
    asyncio.run(main())


def test_same_record_twice_is_one_transaction_one_assessment_one_alert():
    eng, bus, ctx, svc = make()
    first = svc.process(record(1, amount=500))
    assert first["alert"] is True and first["risk_level"] == "HIGH"
    assert svc.process(record(1, amount=500)) is None  # duplicate: nothing happens
    assert counts(eng) == (1, 1, 1) and ctx.live_scorer.seen == ["EV-1"]


def test_low_risk_event_is_stored_and_published_without_an_alert():
    eng, bus, ctx, svc = make()
    ev = svc.process(record(2, amount=10))
    assert ev["alert"] is False and ev["risk_level"] == "LOW" and counts(eng) == (1, 1, 0)


def test_published_event_has_the_fields_the_dashboard_needs():
    eng, bus, ctx, svc = make()
    got = []

    async def main():
        sub = bus.subscribe("A")
        await asyncio.get_running_loop().run_in_executor(None, svc.process, record(3, amount=300))
        got.append(await asyncio.wait_for(sub.get(), 1))
    asyncio.run(main())
    ev = got[0]
    for k in ("external_id", "business_id", "ts", "amount", "account_id", "merchant_id", "risk_score",
              "risk_level", "recommended_action", "risk_factors", "cluster_id", "alert", "late",
              "latency_ms", "source"):
        assert k in ev, k


def test_event_for_another_business_never_reaches_this_subscriber():
    eng, bus, ctx, svc = make()

    async def main():
        a, b = bus.subscribe("A"), bus.subscribe("B")
        await asyncio.get_running_loop().run_in_executor(None, svc.process, record(4, amount=300, business="B"))
        assert (await asyncio.wait_for(b.get(), 1))["business_id"] == "B"
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(a.get(), 0.2)
    asyncio.run(main())


def test_invalid_record_is_rejected_and_stores_nothing():
    eng, bus, ctx, svc = make()
    with pytest.raises(ValueError):
        svc.process(record(5, amount=-3))
    assert counts(eng) == (0, 0, 0) and ctx.live_scorer.seen == []


def test_concurrent_duplicate_deliveries_process_once(tmp_path):
    eng, bus, ctx, svc = make(f"sqlite:///{tmp_path / 'live.db'}")
    out, errors = [], []

    def worker():
        try:
            out.append(svc.process(record(6, amount=300)))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errors and sum(1 for o in out if o) == 1
    assert counts(eng) == (1, 1, 1) and ctx.live_scorer.seen == ["EV-6"]


def test_metrics_report_counts_and_latency_percentiles():
    eng, bus, ctx, svc = make()
    for i in range(10):
        svc.process(record(10 + i, amount=300 if i % 2 else 10, minute=i))
    m = svc.metrics.snapshot()
    assert (m["processed"], m["alerts"]) == (10, 5)
    assert m["p50_ms"] == m["p95_ms"] == m["max_ms"] == 2.5
