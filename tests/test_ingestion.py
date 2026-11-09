import pandas as pd
import pytest

from sentinel.db import init_db, make_engine, session_scope
from sentinel.ingestion.orm import Account, Device, Merchant, Transaction
from sentinel.ingestion.service import ingest, ingest_csv


@pytest.fixture
def engine():
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def _rec(i, **kw):
    base = dict(
        external_id=f"T{i}", account_id="ACC_1", merchant_id="M_1",
        amount=10.0 + i, currency="USD", ts="2026-01-01T00:00:00+00:00",
        type="PAYMENT", status="completed", source="synthetic", business_id="biz1",
    )
    base.update(kw)
    return base


def test_valid_rows_inserted(engine):
    with session_scope(engine) as s:
        res = ingest(s, [_rec(1), _rec(2, device_id="DEV_1")])
        assert (res.inserted, res.duplicates, res.conflicts, res.rejected) == (2, 0, 0, [])
    with session_scope(engine) as s:
        assert s.query(Transaction).count() == 2
        assert s.query(Account).count() == 1
        assert s.query(Merchant).count() == 1
        assert s.query(Device).count() == 1  # only created where a device_id exists


def test_reingest_same_record_is_noop(engine):
    with session_scope(engine) as s:
        ingest(s, [_rec(1), _rec(2)])
    with session_scope(engine) as s:
        res = ingest(s, [_rec(1), _rec(2)])
        assert (res.inserted, res.duplicates, res.conflicts) == (0, 2, 0)
    with session_scope(engine) as s:
        assert s.query(Transaction).count() == 2


def test_same_id_different_payload_counts_conflict_and_keeps_first(engine):
    with session_scope(engine) as s:
        ingest(s, [_rec(1)])
    with session_scope(engine) as s:
        res = ingest(s, [_rec(1, amount=9999.0)])
        assert (res.inserted, res.duplicates, res.conflicts) == (0, 0, 1)
    with session_scope(engine) as s:
        assert s.query(Transaction).one().amount == 11.0


def test_bad_rows_rejected_with_reason(engine):
    rows = [
        _rec(1),
        _rec(2, amount=0),
        _rec(3, amount=-5),
        _rec(4, amount=float("nan")),
        _rec(5, currency="usd1"),
        _rec(6, ts="2026-01-01T00:00:00"),  # naive timestamp
    ]
    with session_scope(engine) as s:
        res = ingest(s, rows)
        assert res.inserted == 1
        assert len(res.rejected) == 5
        assert all(isinstance(i, int) and reason for i, reason in res.rejected)
        assert sorted(i for i, _ in res.rejected) == [1, 2, 3, 4, 5]


def test_csv_roundtrip(engine, tmp_path):
    df = pd.DataFrame([{k: v for k, v in _rec(i).items() if k not in ("source", "business_id")}
                       for i in range(1, 4)])
    path = tmp_path / "t.csv"
    df.to_csv(path, index=False)
    with session_scope(engine) as s:
        res = ingest_csv(s, path, source="synthetic", business_id="biz1")
        assert res.inserted == 3
    with session_scope(engine) as s:
        t = s.query(Transaction).filter_by(external_id="T1").one()
        assert t.source == "synthetic" and t.business_id == "biz1"
        assert t.device_id is None  # missing CSV column stays null, not "nan"


def test_non_utc_offset_stored_as_utc_and_resend_is_duplicate(engine):
    from datetime import datetime
    rec = _rec(1, ts="2026-01-01T12:00:00+05:30")  # = 06:30 UTC
    with session_scope(engine) as s:
        assert ingest(s, [rec]).inserted == 1
    with session_scope(engine) as s:
        stored = s.query(Transaction).one().ts
        assert stored.replace(tzinfo=None) == datetime(2026, 1, 1, 6, 30)
        res = ingest(s, [rec])
        assert (res.duplicates, res.conflicts) == (1, 0)


def test_changed_label_status_or_merchant_is_a_conflict_and_first_is_kept(engine):
    with session_scope(engine) as s:
        ingest(s, [_rec(1, label=0, status="pending")])
    with session_scope(engine) as s:
        res = ingest(s, [_rec(1, label=1, status="completed", merchant_id="M2")])
        assert (res.duplicates, res.conflicts) == (0, 1)
    with session_scope(engine) as s:
        t = s.query(Transaction).one()
        assert (t.label, t.status, t.merchant_id) == (0, "pending", "M_1")
