import base64
import json
import logging

import httpx
import pytest

from sentinel.paypal.client import PayPalClient, PayPalError
from sentinel.paypal.settings import PayPalSettings

SECRET = "S3CR3T-client-secret-value"
TOKEN = "TOKEN-VALUE-abc123"


def token_response(expires_in=3600):
    return httpx.Response(200, json={"access_token": TOKEN, "expires_in": expires_in,
                                     "token_type": "Bearer"})


class Fake:
    """Programmable PayPal: routes by path, records requests."""
    def __init__(self, routes, expires_in=3600):
        self.routes, self.requests, self.sleeps = routes, [], []
        self.expires_in = expires_in

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return token_response(self.expires_in)
        r = self.routes[request.url.path]
        if callable(r):
            r = r(request)
        if isinstance(r, list):  # sequence of responses/exceptions, last one repeats
            item = r[min(len(self.calls(request.url.path)) - 1, len(r) - 1)]
        else:
            item = r
        if isinstance(item, Exception):
            raise item
        return item

    def calls(self, path):
        return [q for q in self.requests if q.url.path == path]

    def client(self, **kw):
        return PayPalClient("client-id", SECRET, transport=httpx.MockTransport(self.handler),
                            sleep=self.sleeps.append, **kw)


ORDER = {"id": "ORD-1", "status": "CREATED",
         "links": [{"rel": "self", "href": "https://x/self"},
                   {"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORD-1"}]}
CAPTURED = {"id": "ORD-1", "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [{
    "id": "CAP-9", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "42.50"},
    "create_time": "2026-11-09T10:00:00Z"}]}}]}


def test_token_is_cached_and_basic_auth_is_only_on_the_token_call():
    f = Fake({"/v2/checkout/orders/ORD-1": httpx.Response(200, json=ORDER)})
    c = f.client()
    c.get_order("ORD-1")
    c.get_order("ORD-1")
    token_calls = f.calls("/v1/oauth2/token")
    assert len(token_calls) == 1
    expected = base64.b64encode(f"client-id:{SECRET}".encode()).decode()
    assert token_calls[0].headers["authorization"] == f"Basic {expected}"
    assert b"grant_type=client_credentials" in token_calls[0].content
    for q in f.calls("/v2/checkout/orders/ORD-1"):
        assert q.headers["authorization"] == f"Bearer {TOKEN}"


def test_expired_token_is_refetched():
    f = Fake({"/v2/checkout/orders/ORD-1": httpx.Response(200, json=ORDER)}, expires_in=1)
    c = f.client()
    c.get_order("ORD-1")
    c.get_order("ORD-1")
    assert len(f.calls("/v1/oauth2/token")) == 2  # 1s lifetime is inside the refresh margin


def test_401_refreshes_the_token_once_and_retries():
    f = Fake({"/v2/checkout/orders/ORD-1": [httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"}),
                                            httpx.Response(200, json=ORDER)]})
    assert f.client().get_order("ORD-1")["id"] == "ORD-1"
    assert len(f.calls("/v1/oauth2/token")) == 2


def test_create_order_sends_verified_body_and_headers():
    f = Fake({"/v2/checkout/orders": httpx.Response(201, json=ORDER)})
    out = f.client().create_order("42.50", "USD", custom_id="ACC_00007", request_id="req-1")
    q = f.calls("/v2/checkout/orders")[0]
    assert json.loads(q.content) == {"intent": "CAPTURE", "purchase_units": [
        {"amount": {"currency_code": "USD", "value": "42.50"}, "custom_id": "ACC_00007"}]}
    assert q.headers["paypal-request-id"] == "req-1" and q.headers["prefer"] == "return=representation"
    assert out["id"] == "ORD-1" and out["approve_url"].endswith("token=ORD-1")


def test_transient_errors_are_retried_with_the_same_idempotency_key():
    f = Fake({"/v2/checkout/orders": [httpx.Response(429), httpx.Response(503),
                                      httpx.Response(500), httpx.Response(201, json=ORDER)]})
    f.client(max_retries=3).create_order("1.00", "USD")
    calls = f.calls("/v2/checkout/orders")
    assert len(calls) == 4 and len(f.sleeps) == 3 and f.sleeps == sorted(f.sleeps)
    assert len({q.headers["paypal-request-id"] for q in calls}) == 1  # a retry must not duplicate


def test_transport_errors_are_retried():
    f = Fake({"/v2/checkout/orders": [httpx.ConnectTimeout("slow"), httpx.Response(201, json=ORDER)]})
    assert f.client().create_order("1.00", "USD")["id"] == "ORD-1"


def test_exhausted_retries_raise_a_retryable_error():
    f = Fake({"/v2/checkout/orders": httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE"})})
    with pytest.raises(PayPalError) as e:
        f.client(max_retries=2).create_order("1.00", "USD")
    assert e.value.retryable and e.value.status == 503
    assert len(f.calls("/v2/checkout/orders")) == 3


def test_client_errors_are_not_retried_and_carry_diagnostics():
    body = {"name": "UNPROCESSABLE_ENTITY", "message": "bad", "debug_id": "dbg-77",
            "details": [{"issue": "ORDER_NOT_APPROVED"}]}
    f = Fake({"/v2/checkout/orders/ORD-1/capture": httpx.Response(422, json=body)})
    with pytest.raises(PayPalError) as e:
        f.client().capture_order("ORD-1")
    err = e.value
    assert (err.status, err.name, err.debug_id, err.issue) == (422, "UNPROCESSABLE_ENTITY", "dbg-77", "ORDER_NOT_APPROVED")
    assert not err.retryable and len(f.calls("/v2/checkout/orders/ORD-1/capture")) == 1


def test_capture_order_parses_the_capture():
    f = Fake({"/v2/checkout/orders/ORD-1/capture": httpx.Response(201, json=CAPTURED)})
    out = f.client().capture_order("ORD-1")
    assert (out["capture_id"], out["status"], out["amount"], out["currency"], out["order_id"]) == \
        ("CAP-9", "COMPLETED", "42.50", "USD", "ORD-1")
    assert out["create_time"] == "2026-11-09T10:00:00Z"


def test_unexpected_capture_shape_is_a_clear_error():
    f = Fake({"/v2/checkout/orders/ORD-1/capture": httpx.Response(201, json={"id": "ORD-1", "status": "COMPLETED"})})
    with pytest.raises(PayPalError, match="unexpected capture response"):
        f.client().capture_order("ORD-1")


def test_refund_body_is_empty_for_full_and_has_amount_for_partial():
    f = Fake({"/v2/payments/captures/CAP-9/refund": httpx.Response(201, json={"id": "REF-1", "status": "COMPLETED"})})
    c = f.client()
    assert c.refund_capture("CAP-9")["id"] == "REF-1"
    c.refund_capture("CAP-9", amount="5.00", currency="USD", note="customer request")
    full, partial = f.calls("/v2/payments/captures/CAP-9/refund")
    assert json.loads(full.content) == {}
    assert json.loads(partial.content) == {"amount": {"currency_code": "USD", "value": "5.00"},
                                           "note_to_payer": "customer request"}


HEADERS = {"PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert",
           "PAYPAL-TRANSMISSION-ID": "tid-1", "PAYPAL-TRANSMISSION-SIG": "sig==",
           "PAYPAL-TRANSMISSION-TIME": "2026-11-09T10:00:00Z"}
RAW = b'{ "id" : "WH-1",\n  "event_type":"PAYMENT.CAPTURE.COMPLETED", "name": "caf\\u00e9" }'


def verify_route(status_value):
    return httpx.Response(200, json={"verification_status": status_value}) if status_value is not None \
        else httpx.Response(200, json={})


def test_verify_webhook_posts_the_received_bytes_verbatim():
    f = Fake({"/v1/notifications/verify-webhook-signature": verify_route("SUCCESS")})
    assert f.client().verify_webhook({k.lower(): v for k, v in HEADERS.items()}, RAW, "WH123") is True
    sent = f.calls("/v1/notifications/verify-webhook-signature")[0].content
    assert b'"webhook_event":' + RAW + b"}" in sent  # byte-identical, never re-serialised
    body = json.loads(sent)
    assert (body["auth_algo"], body["transmission_id"], body["webhook_id"]) == ("SHA256withRSA", "tid-1", "WH123")


@pytest.mark.parametrize("status", ["FAILURE", "success", "", None, "SUCCESS "])
def test_only_exact_success_verifies(status):
    f = Fake({"/v1/notifications/verify-webhook-signature": verify_route(status)})
    assert f.client().verify_webhook(HEADERS, RAW, "WH123") is False


def test_verify_with_a_missing_header_is_false_and_makes_no_call():
    f = Fake({})
    partial = {k: v for k, v in HEADERS.items() if k != "PAYPAL-TRANSMISSION-SIG"}
    assert f.client().verify_webhook(partial, RAW, "WH123") is False
    assert f.requests == []


def test_logs_never_contain_secrets_or_tokens(caplog):
    caplog.set_level(logging.DEBUG)
    f = Fake({"/v2/checkout/orders": httpx.Response(201, json=ORDER)})
    f.client().create_order("1.00", "USD")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "sentinel.paypal" in {r.name for r in caplog.records}
    assert SECRET not in text and TOKEN not in text and "authorization" not in text.lower()


def test_settings_from_env_names_missing_variables_but_not_values(monkeypatch):
    for k in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", SECRET)
    with pytest.raises(RuntimeError) as e:
        PayPalSettings.from_env()
    assert "PAYPAL_CLIENT_ID" in str(e.value) and "PAYPAL_WEBHOOK_ID" in str(e.value)
    assert SECRET not in str(e.value)
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH1")
    s = PayPalSettings.from_env()
    assert (s.client_id, s.webhook_id) == ("cid", "WH1") and SECRET not in repr(s)
