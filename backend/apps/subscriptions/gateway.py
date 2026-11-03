"""Payment gateway abstraction. Razorpay is the real provider; 'fake' exists for local testing only.

Only the public key id ever reaches the app. The key secret and webhook secret stay on the server.
"""
import hashlib
import hmac
import secrets

import requests
from django.conf import settings

from apps.common.errors import ApiProblem

FAKE_SECRET = "fake-gateway-secret-for-local-testing"


def _hmac(secret: str, message: str | bytes) -> str:
    msg = message.encode() if isinstance(message, str) else message
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


class RazorpayGateway:
    name = "razorpay"

    def key_id(self) -> str:
        return settings.RAZORPAY_KEY_ID

    def create_order(self, amount_paise: int, receipt: str) -> str:
        if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
            raise ApiProblem("Payments are not configured on this server.", "payments_unavailable", 503)
        try:
            r = requests.post(
                "https://api.razorpay.com/v1/orders",
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                json={"amount": amount_paise, "currency": "INR", "receipt": receipt[:40]},
                timeout=15,
            )
            r.raise_for_status()
            return r.json()["id"]
        except requests.RequestException:
            raise ApiProblem("The payment provider is unavailable. Please try again.", "gateway_error", 502)

    def verify_payment_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        expected = _hmac(settings.RAZORPAY_KEY_SECRET, f"{order_id}|{payment_id}")
        return bool(settings.RAZORPAY_KEY_SECRET) and hmac.compare_digest(expected, signature or "")

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        expected = _hmac(settings.RAZORPAY_WEBHOOK_SECRET, body)
        return bool(settings.RAZORPAY_WEBHOOK_SECRET) and hmac.compare_digest(expected, signature or "")


class FakeGateway(RazorpayGateway):
    """Local-only stand-in. Never enabled unless DEBUG is true."""
    name = "razorpay"  # stored as razorpay so the same rows/flows are exercised

    def key_id(self) -> str:
        return "rzp_test_fake"

    def create_order(self, amount_paise: int, receipt: str) -> str:
        return "order_fake_" + secrets.token_hex(8)

    def verify_payment_signature(self, order_id, payment_id, signature) -> bool:
        return hmac.compare_digest(_hmac(FAKE_SECRET, f"{order_id}|{payment_id}"), signature or "")

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        return hmac.compare_digest(_hmac(FAKE_SECRET, body), signature or "")


def get_gateway() -> RazorpayGateway:
    if settings.PAYMENT_GATEWAY == "fake":
        if not settings.DEBUG:
            raise ApiProblem("Fake payment gateway is disabled outside DEBUG.", "payments_unavailable", 503)
        return FakeGateway()
    return RazorpayGateway()


def fake_sign_payment(order_id: str, payment_id: str) -> str:  # used by tests / dev tools
    return _hmac(FAKE_SECRET, f"{order_id}|{payment_id}")


def fake_sign_webhook(body: bytes) -> str:
    return _hmac(FAKE_SECRET, body)
