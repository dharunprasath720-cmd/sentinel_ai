"""Verified, idempotent PayPal webhook processing.

Flow: cheap local checks (valid JSON object with an id/type) -> signature verification by PayPal
on the EXACT received bytes -> idempotency on event_id -> normalisation -> ingestion.
Fail closed: anything not verified is stored nowhere. PayPal being unreachable is a *temporary*
failure (-> 503 so PayPal retries), a failed verification is a *rejection* (-> 401).

Which fields come from where (be explicit; PayPal exposes no internal fraud signals):
  from PayPal : capture id, amount, currency, status, create time, payee merchant id,
                order id (supplementary_data), our own `custom_id` if we set one when creating the order
  demo-only   : device_id, geo, instrument, behaviour history, labels. Absent for PayPal events
                (stay None); features that need them degrade to their "missing" values.
  not provided: payer identity is not in PAYMENT.CAPTURE.COMPLETED, so the fraud account id is the
                `custom_id` we attached at order creation, else "PAYPAL_UNLINKED".
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Mapping

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sentinel.ingestion.service import ingest
from sentinel.paypal.client import PayPalClient, PayPalError
from sentinel.paypal.orm import PayPalEvent

CAPTURE_COMPLETED = "PAYMENT.CAPTURE.COMPLETED"
UNLINKED = "PAYPAL_UNLINKED"


class InvalidSignature(Exception):
    """Not verified by PayPal (HTTP 401)."""


class VerificationUnavailable(Exception):
    """Could not ask PayPal, or our credentials were refused (HTTP 503: PayPal will retry)."""


class BadEvent(Exception):
    """Malformed or unusable payload (HTTP 400)."""


@dataclass
class WebhookResult:
    status: Literal["processed", "duplicate", "ignored"]
    txn_external_id: str | None = None
    record: dict | None = field(default=None, repr=False)  # normalised row, for the scorer


def normalise_capture_event(event: dict, business_id: str) -> dict:
    res = event.get("resource")
    try:
        if not isinstance(res, dict):
            raise KeyError("resource")
        payee = res.get("payee") or {}
        return {
            "external_id": f"PP-{res['id']}",
            "account_id": res.get("custom_id") or UNLINKED,
            "merchant_id": payee.get("merchant_id"),
            "device_id": None, "instrument_id": None,
            "amount": float(res["amount"]["value"]),
            "currency": res["amount"]["currency_code"],
            "ts": res.get("create_time") or event["create_time"],
            "type": "PAYMENT", "payment_method": "paypal", "status": "completed",
            "geo": None, "label": None,
            "source": "paypal_sandbox", "business_id": business_id,
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise BadEvent(f"capture event is missing or has an invalid field: {exc!r}") from exc


def process_webhook(session: Session, client: PayPalClient, headers: Mapping[str, str],
                    raw_body: bytes, webhook_id: str, business_id: str) -> WebhookResult:
    try:  # cheap local rejection first: garbage never costs a PayPal call
        event = json.loads(raw_body)
    except ValueError as exc:
        raise BadEvent("body is not valid JSON") from exc
    if not (isinstance(event, dict) and isinstance(event.get("id"), str)
            and isinstance(event.get("event_type"), str)):
        raise BadEvent("body is not a PayPal event object (needs string id and event_type)")

    try:
        verified = client.verify_webhook(headers, raw_body, webhook_id)
    except PayPalError as exc:
        if exc.retryable or exc.status in (401, 403):
            raise VerificationUnavailable(str(exc)) from exc
        raise InvalidSignature(str(exc)) from exc
    if not verified:
        raise InvalidSignature("PayPal did not verify this webhook")

    if session.get(PayPalEvent, event["id"]) is not None:
        return WebhookResult("duplicate")

    record = None
    if event["event_type"] == CAPTURE_COMPLETED:
        record = normalise_capture_event(event, business_id)  # BadEvent before anything is stored

    row = PayPalEvent(event_id=event["id"], event_type=event["event_type"],
                      received_at=datetime.now(timezone.utc), payload=event)
    session.add(row)
    try:
        session.flush()
    except IntegrityError:  # a concurrent delivery of the same event won the race
        session.rollback()
        return WebhookResult("duplicate")

    if record is None:
        row.processed_at = datetime.now(timezone.utc)
        return WebhookResult("ignored")

    result = ingest(session, [record])
    if result.rejected:
        raise BadEvent(f"transaction rejected: {result.rejected[0][1]}")
    row.txn_external_id = record["external_id"]
    row.processed_at = datetime.now(timezone.utc)
    if result.inserted == 0:  # new event id for a capture we already have
        return WebhookResult("duplicate", record["external_id"])
    return WebhookResult("processed", record["external_id"], record)
