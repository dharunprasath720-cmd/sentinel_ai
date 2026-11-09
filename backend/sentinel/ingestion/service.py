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


PAYLOAD_FIELDS = list(TransactionIn.model_fields)


def _fingerprint(values) -> tuple:
    """Identity of a FULL payload (every field) for conflict detection. A re-sent id whose
    label, status, merchant etc. differ is a conflict, never a silent duplicate.
    The DB returns naive UTC timestamps, so both sides are reduced to naive UTC."""
    out = []
    for f in PAYLOAD_FIELDS:
        v = values[f]
        if f == "ts":
            v = (v.astimezone(timezone.utc) if v.tzinfo is not None else v).replace(tzinfo=None)
        elif f == "amount":
            v = round(float(v), 6)
        out.append(v)
    return tuple(out)


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
        rows = session.scalars(select(Transaction).where(Transaction.external_id.in_(ext_ids)))
        existing = {r.external_id: _fingerprint({f: getattr(r, f) for f in PAYLOAD_FIELDS})
                    for r in rows}

    new_txns: list[Transaction] = []
    for t in valid:
        fp = _fingerprint(t.model_dump())
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
