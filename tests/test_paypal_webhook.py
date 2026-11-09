import json
import threading

import httpx
import pytest

from sentinel.db import init_db, make_engine, session_scope
from sentinel.ingestion.orm import Transaction
from sentinel.ingestion.schema import TransactionIn
from sentinel.paypal.client import PayPalClient, PayPalError
from sentinel.paypal.orm import PayPalEvent
from sentinel.paypal.webhook import (BadEvent, InvalidSignature, VerificationUnavailable,
                                     normalise_capture_event, process_webhook)

HEADERS = {"paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api.sandbox.paypal.com/c",
           "paypal-transmission-id": "tid-1", "paypal-transmission-sig": "sig==",
           "paypal-transmission-time": "2026-11-09T10:00:00Z"}
VERIFY_PATH = "/v1/notifications/verify-webhook-signature"


def event(event_id="WH-1", etype="PAYMENT.CAPTURE.COMPLETED", **resource):
    res = {"id": "CAP-9", "status": "COMPLETED", "amount": {"value": "42.50", "currency_code": "USD"},
           "create_time": "2026-11-09T10:00:00Z", "custom_id": "ACC_00007",
           "payee": {"merchant_id": "MERCH123", "email_address": "m@example.com"},
           "supplementary_data": {"related_ids": {"order_id": "ORD-1"}}}
    res.update(resource)
    return {"id": event_id, "event_type": etype, "create_time": "2026-11-09T10:00:01Z",
            "resource_type": "capture", "resource": res}


def raw(ev=None):
    # deliberately awkward bytes: odd spacing, newline, key order, non-ASCII and an escape
    ev = ev or event()
    s = json.dumps(ev, indent=3, ensure_ascii=False)
    return s.replace('"COMPLETED"', '"COMPLETED" ', 1).encode("utf-8") + b"\n"


def paypal(verify_response, max_retries=0):
    seen = []

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        seen.append(request)
        r = verify_response
        if isinstance(r, Exception):
            raise r
        return r
    return PayPalClient("id", "secret", transport=httpx.MockTransport(handler),
                        sleep=lambda s: None, max_retries=max_retries), seen


def ok():
    return httpx.Response(200, json={"verification_status": "SUCCESS"})


@pytest.fixture
def engine():
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def run(engine, client, body=None, headers=HEADERS):
    with session_scope(engine) as s:
        return process_webhook(s, client, headers, body if body is not None else raw(), "WH123", "biz1")


def counts(engine):
    with session_scope(engine) as s:
        return s.query(PayPalEvent).count(), s.query(Transaction).count()


def test_received_bytes_are_verified_verbatim(engine):
    client, seen = paypal(ok())
    body = raw()
    res = run(engine, client, body)
    assert res.status == "processed" and res.txn_external_id == "PP-CAP-9"
    assert b'"webhook_event":' + body + b"}" in seen[0].content  # identical bytes inside the request


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"verification_status": "FAILURE"}),
    httpx.Response(200, json={"verification_status": ""}),
    httpx.Response(200, json={}),
    httpx.Response(200, json={"verification_status": "success"}),
    httpx.Response(400, json={"name": "INVALID_REQUEST"}),
])
def test_anything_but_success_is_rejected_and_nothing_is_stored(engine, response):
    client, _ = paypal(response)
    with pytest.raises(InvalidSignature):
        run(engine, client)
    assert counts(engine) == (0, 0)


def test_missing_signature_headers_are_rejected_without_calling_paypal(engine):
    client, seen = paypal(ok())
    with pytest.raises(InvalidSignature):
        run(engine, client, headers={"paypal-transmission-id": "x"})
    assert seen == [] and counts(engine) == (0, 0)


@pytest.mark.parametrize("response", [
    httpx.ConnectTimeout("timeout"),
    httpx.Response(500, json={"name": "INTERNAL_SERVER_ERROR"}),
    httpx.Response(503),
    httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"}),   # our credentials, not the sender's fault
])
def test_verification_outage_is_unavailable_and_stores_nothing(engine, response):
    client, _ = paypal(response)
    with pytest.raises(VerificationUnavailable):
        run(engine, client)
    assert counts(engine) == (0, 0)


def test_duplicate_event_id_is_idempotent(engine):
    client, _ = paypal(ok())
    assert run(engine, client).status == "processed"
    assert run(engine, client).status == "duplicate"
    assert counts(engine) == (1, 1)


def test_concurrent_duplicates_create_one_row(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'wh.db'}")
    init_db(eng)
    client, _ = paypal(ok())
    results, errors = [], []

    def worker():
        try:
            results.append(run(eng, client).status)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and sorted(results) == ["duplicate"] * 3 + ["processed"]
    assert counts(eng) == (1, 1)


def test_verified_non_capture_event_is_ignored_and_recorded_once(engine):
    client, _ = paypal(ok())
    body = raw(event("WH-2", "BILLING.SUBSCRIPTION.CREATED"))
    assert run(engine, client, body).status == "ignored"
    assert run(engine, client, body).status == "duplicate"
    assert counts(engine) == (1, 0)


@pytest.mark.parametrize("body", [b"not json", b"[]", b'"str"', b"{}"])
def test_malformed_payloads_are_bad_events_and_never_reach_paypal(engine, body):
    client, seen = paypal(ok())
    with pytest.raises(BadEvent):
        run(engine, client, body)
    assert seen == [] and counts(engine) == (0, 0)


def test_verified_capture_without_usable_resource_is_bad_event(engine):
    client, _ = paypal(ok())
    bad = event()
    del bad["resource"]["amount"]
    with pytest.raises(BadEvent):
        run(engine, client, raw(bad))
    assert counts(engine) == (0, 0)


def test_normalised_record_is_valid_and_labelled_paypal_sandbox():
    rec = normalise_capture_event(event(), "biz1")
    t = TransactionIn(**rec)
    assert (t.source, t.external_id, t.account_id, t.merchant_id, t.amount, t.currency) == \
        ("paypal_sandbox", "PP-CAP-9", "ACC_00007", "MERCH123", 42.5, "USD")
    assert t.device_id is None and t.geo is None and t.label is None  # demo-only fields stay empty
    # an unlinked payer must not be merged with other unlinked payers: one pseudo-account per capture
    a = normalise_capture_event(event(custom_id=None, id="CAP-1"), "biz1")["account_id"]
    b = normalise_capture_event(event(custom_id=None, id="CAP-2"), "biz1")["account_id"]
    assert a.startswith("PAYPAL_UNLINKED") and b.startswith("PAYPAL_UNLINKED") and a != b


@pytest.mark.parametrize("cert_url", [
    "http://api.sandbox.paypal.com/c",                 # not https
    "https://evil.example.com/c",
    "https://paypal.com.evil.com/c",                    # suffix trick
    "https://api.sandbox.paypal.com.evil.com/c",
    "ftp://api.sandbox.paypal.com/c",
    "https://" + "a" * 600 + ".paypal.com/c",           # absurd length
    "not a url",
])
def test_cert_url_must_be_an_https_paypal_host_and_nothing_is_sent_to_paypal_otherwise(engine, cert_url):
    client, seen = paypal(ok())
    with pytest.raises(InvalidSignature):
        run(engine, client, headers={**HEADERS, "paypal-cert-url": cert_url})
    assert seen == [] and counts(engine) == (0, 0)


def test_deeply_nested_json_is_a_bad_event_not_a_crash(engine):
    client, seen = paypal(ok())
    with pytest.raises(BadEvent):
        run(engine, client, b"[" * 200_000)
    assert seen == []


def test_header_names_are_case_insensitive(engine):
    client, _ = paypal(ok())
    upper = {k.upper(): v for k, v in HEADERS.items()}
    assert run(engine, client, headers=upper).status == "processed"