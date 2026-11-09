from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from sentinel.db import init_db, make_engine, session_scope
from sentinel.ingestion.orm import Transaction


def _txn(**overrides):
    base = dict(
        external_id="T1", account_id="ACC_1", merchant_id="M_1", device_id=None,
        instrument_id=None, amount=10.0, currency="USD",
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc), type="PAYMENT",
        payment_method="card", status="completed", geo=None, label=None,
        source="synthetic", business_id="biz1",
    )
    base.update(overrides)
    return Transaction(**base)


@pytest.fixture
def engine():
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def test_unique_external_id(engine):
    with session_scope(engine) as s:
        s.add(_txn())
    with pytest.raises(IntegrityError):
        with session_scope(engine) as s:
            s.add(_txn(amount=99.0))


def test_source_required(engine):
    with pytest.raises(IntegrityError):
        with session_scope(engine) as s:
            s.add(_txn(source=None))


def test_optional_fields_nullable(engine):
    with session_scope(engine) as s:
        s.add(_txn(device_id=None, geo=None, merchant_id=None, label=None))
    with session_scope(engine) as s:
        t = s.query(Transaction).one()
        assert t.device_id is None and t.geo is None and t.label is None
