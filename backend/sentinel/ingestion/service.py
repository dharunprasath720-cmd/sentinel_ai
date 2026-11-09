from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.ingestion.orm import Account, Device, Merchant, Transaction
from sentinel.ingestion.schema import TransactionIn


@dataclass
class IngestResult:
    inserted: int = 0
    duplicates: int = 0
    conflicts: int = 0
    rejected: list[tuple[int, str]] = field(default_factory=list)


def _fingerprint(amount: float, account_id: str, ts: datetime) -> tuple:
    """Identity of a payload for conflict detection (DB may return naive UTC)."""
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return (round(float(amount), 6), account_id, ts)


def _existing_ids(session: Session, model, ids: set[str]) -> set[str]:
    if not ids:
        return set()
    return set(session.scalars(select(model.id).where(model.id.in_(ids))))


def ingest(session: Session, records: Iterable[dict]) -> IngestResult:
    result = IngestResult()
    valid: list[TransactionIn] = []
    for i, rec in enumerate(records):
        try:
            valid.append(TransactionIn(**rec))
        except (ValidationError, TypeError) as exc:
            result.rejected.append((i, str(exc).replace("\n", " ")[:200]))

    ext_ids = {t.external_id for t in valid}
    existing: dict[str, tuple] = {}
    if ext_ids:
        rows = session.execute(
            select(Transaction.external_id, Transaction.amount,
                   Transaction.account_id, Transaction.ts)
            .where(Transaction.external_id.in_(ext_ids))
        )
        existing = {r[0]: _fingerprint(r[1], r[2], r[3]) for r in rows}

    new_txns: list[Transaction] = []
    for t in valid:
        fp = _fingerprint(t.amount, t.account_id, t.ts)
        if t.external_id in existing:
            if existing[t.external_id] == fp:
                result.duplicates += 1
            else:
                result.conflicts += 1
            continue
        existing[t.external_id] = fp  # also dedups within the batch
        new_txns.append(Transaction(**t.model_dump()))
        result.inserted += 1

    accounts = {t.account_id for t in new_txns}
    merchants = {t.merchant_id for t in new_txns if t.merchant_id}
    devices = {t.device_id for t in new_txns if t.device_id}
    biz = {t.account_id: t.business_id for t in new_txns}
    session.add_all(
        [Account(id=a, business_id=biz[a]) for a in accounts - _existing_ids(session, Account, accounts)]
        + [Merchant(id=m) for m in merchants - _existing_ids(session, Merchant, merchants)]
        + [Device(id=d) for d in devices - _existing_ids(session, Device, devices)]
    )
    session.add_all(new_txns)
    session.flush()
    return result


def ingest_csv(session: Session, path: Path, source: str, business_id: str) -> IngestResult:
    df = pd.read_csv(path, dtype=str)
    df = df.astype(object).where(df.notna(), None)
    df["source"] = source
    df["business_id"] = business_id
    return ingest(session, df.to_dict("records"))
