"""PayPal Sandbox REST client.

Facts below are from developer.paypal.com (fetched 2026-11-09); items marked UNCONFIRMED were
not visible in the pages that could be read and must be checked on the first live call.
  * sandbox base https://api-m.sandbox.paypal.com, OAuth2 client credentials
    (token path /v1/oauth2/token is UNCONFIRMED)
  * orders: POST /v2/checkout/orders; capture needs prior buyer approval (rel:approve link)
  * PayPal-Request-Id is the idempotency header; one id is reused across retries of a call
  * webhook verification: POST /v1/notifications/verify-webhook-signature; `webhook_event` must be
    the received body, unmodified. Only the exact string "SUCCESS" counts as verified
    (other status values are UNCONFIRMED, so everything else fails closed)
  * capture response path purchase_units[0].payments.captures[0] is UNCONFIRMED
Secrets: the client secret and tokens are never logged; only method, path, status and the
PayPal debug id are.
"""
import base64
import json
import logging
import random
import time
import uuid
from typing import Mapping

import httpx

log = logging.getLogger("sentinel.paypal")
SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
TOKEN_PATH = "/v1/oauth2/token"  # UNCONFIRMED path, standard for PayPal REST
TOKEN_MARGIN_SECS = 30
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
WEBHOOK_HEADERS = ("auth_algo", "cert_url", "transmission_id", "transmission_sig", "transmission_time")


class PayPalError(Exception):
    def __init__(self, status: int, name: str | None = None, message: str = "",
                 debug_id: str | None = None, issue: str | None = None, retryable: bool = False):
        super().__init__(f"PayPal {status} {name or ''} {message}".strip())
        self.status, self.name, self.message = status, name, message
        self.debug_id, self.issue, self.retryable = debug_id, issue, retryable


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str = SANDBOX_BASE,
                 transport: httpx.BaseTransport | None = None, max_retries: int = 3,
                 sleep=time.sleep, clock=time.monotonic, timeout: float = 15.0):
        self._id, self._secret = client_id, client_secret
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)
        self.max_retries, self._sleep, self._clock = max_retries, sleep, clock
        self._token: str | None = None
        self._token_expiry = 0.0

    # ------------------------------------------------------------------ auth
    def _access_token(self) -> str:
        if self._token and self._clock() < self._token_expiry:
            return self._token
        basic = base64.b64encode(f"{self._id}:{self._secret}".encode()).decode()
        r = self._http.post(TOKEN_PATH, data={"grant_type": "client_credentials"},
                            headers={"Authorization": f"Basic {basic}"})
        log.debug("paypal POST %s -> %s", TOKEN_PATH, r.status_code)
        if r.status_code != 200:
            raise PayPalError(r.status_code, "AUTHENTICATION_FAILURE", "token request failed",
                              retryable=r.status_code in RETRYABLE_STATUS)
        body = r.json()
        self._token = body["access_token"]
        self._token_expiry = self._clock() + int(body.get("expires_in", 0)) - TOKEN_MARGIN_SECS
        return self._token

    # ------------------------------------------------------------------ transport
    def _request(self, method: str, path: str, *, json_body=None, content: bytes | None = None,
                 headers: Mapping[str, str] | None = None, idempotent_id: str | None = None) -> dict:
        extra = dict(headers or {})
        if idempotent_id:
            extra["PayPal-Request-Id"] = idempotent_id  # fixed per call: retries reuse it
        refreshed = False
        attempt = 0
        while True:
            try:
                r = self._http.request(
                    method, path, json=json_body, content=content,
                    headers={**extra, "Authorization": f"Bearer {self._access_token()}",
                             **({"Content-Type": "application/json"} if content is not None else {})})
            except httpx.TransportError as exc:
                log.warning("paypal %s %s transport error: %s", method, path, type(exc).__name__)
                if attempt >= self.max_retries:
                    raise PayPalError(0, "TRANSPORT_ERROR", type(exc).__name__, retryable=True) from exc
                self._backoff(attempt)
                attempt += 1
                continue
            debug_id = r.headers.get("paypal-debug-id")
            log.info("paypal %s %s -> %s debug_id=%s", method, path, r.status_code, debug_id)
            if r.status_code == 401 and not refreshed:
                self._token, refreshed = None, True
                continue
            if r.status_code in RETRYABLE_STATUS:
                if attempt >= self.max_retries:
                    raise self._error(r, retryable=True)
                self._backoff(attempt)
                attempt += 1
                continue
            if r.status_code >= 400:
                raise self._error(r, retryable=False)
            return r.json() if r.content else {}

    def _backoff(self, attempt: int) -> None:
        self._sleep(0.5 * (2 ** attempt) + random.uniform(0, 0.25))

    @staticmethod
    def _error(r: httpx.Response, retryable: bool) -> PayPalError:
        try:
            body = r.json()
        except ValueError:
            body = {}
        details = body.get("details") or [{}]
        return PayPalError(r.status_code, body.get("name"), body.get("message", ""),
                           body.get("debug_id") or r.headers.get("paypal-debug-id"),
                           details[0].get("issue"), retryable)

    # ------------------------------------------------------------------ orders
    def create_order(self, amount: str, currency: str, custom_id: str | None = None,
                     request_id: str | None = None) -> dict:
        unit: dict = {"amount": {"currency_code": currency, "value": amount}}
        if custom_id:
            unit["custom_id"] = custom_id
        raw = self._request("POST", "/v2/checkout/orders",
                            json_body={"intent": "CAPTURE", "purchase_units": [unit]},
                            headers={"Prefer": "return=representation"},
                            idempotent_id=request_id or str(uuid.uuid4()))
        approve = next((l["href"] for l in raw.get("links", [])
                        if l.get("rel") in ("approve", "payer-action")), None)
        return {"id": raw["id"], "status": raw.get("status"), "approve_url": approve, "raw": raw}

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/v2/checkout/orders/{order_id}")

    def capture_order(self, order_id: str, request_id: str | None = None) -> dict:
        raw = self._request("POST", f"/v2/checkout/orders/{order_id}/capture", json_body={},
                            headers={"Prefer": "return=representation"},
                            idempotent_id=request_id or str(uuid.uuid4()))
        try:  # UNCONFIRMED response path: fail with a clear error rather than guess
            cap = raw["purchase_units"][0]["payments"]["captures"][0]
            return {"capture_id": cap["id"], "status": cap["status"],
                    "amount": cap["amount"]["value"], "currency": cap["amount"]["currency_code"],
                    "create_time": cap.get("create_time"), "order_id": raw.get("id", order_id),
                    "raw": raw}
        except (KeyError, IndexError, TypeError) as exc:
            raise PayPalError(200, "UNEXPECTED_RESPONSE",
                              f"unexpected capture response shape (keys: {sorted(raw)})") from exc

    def refund_capture(self, capture_id: str, amount: str | None = None, currency: str | None = None,
                       note: str | None = None, request_id: str | None = None) -> dict:
        """Empty body = full refund; an `amount` object = partial (per PayPal docs).
        UNTESTED against the live Sandbox; nothing in the app calls it yet."""
        body: dict = {}
        if amount is not None:
            body["amount"] = {"currency_code": currency, "value": amount}
        if note:
            body["note_to_payer"] = note
        return self._request("POST", f"/v2/payments/captures/{capture_id}/refund", json_body=body,
                             idempotent_id=request_id or str(uuid.uuid4()))

    # ------------------------------------------------------------------ webhooks
    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes, webhook_id: str) -> bool:
        """True only if PayPal answers verification_status == "SUCCESS". The received body is
        embedded byte-for-byte (never parsed and re-serialised). Raises PayPalError when PayPal
        itself is unreachable or rejects our credentials."""
        h = {k.lower().replace("-", "_").removeprefix("paypal_"): v for k, v in headers.items()}
        if any(not h.get(k) for k in WEBHOOK_HEADERS):
            return False
        parts = [b'"%s":%s' % (k.encode(), json.dumps(h[k]).encode()) for k in WEBHOOK_HEADERS]
        parts.append(b'"webhook_id":' + json.dumps(webhook_id).encode())
        payload = b"{" + b",".join(parts) + b',"webhook_event":' + raw_body + b"}"
        out = self._request("POST", "/v1/notifications/verify-webhook-signature", content=payload)
        return out.get("verification_status") == "SUCCESS"
