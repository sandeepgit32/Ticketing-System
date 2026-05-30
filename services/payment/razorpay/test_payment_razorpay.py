"""
Unit and integration tests for the Razorpay payment service.

Tests are structured into two groups:
  1. razorpay_client.py — pure function tests (signature verification).
     These never call the real Razorpay API or Redis.
  2. main.py endpoints — FastAPI TestClient tests with Razorpay SDK and
     Redis mocked out so the service is runnable in isolation.

Run with:
    pytest test_payment_razorpay.py -v
"""

import hashlib
import hmac
import importlib.util
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dotenv import load_dotenv

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env so required_env() calls in main.py resolve without a real deployment.
load_dotenv(dotenv_path=os.path.join(_SERVICE_DIR, ".env"), override=False)

if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

# ---------------------------------------------------------------------------
# Helpers — compute expected signatures the same way Razorpay does
# ---------------------------------------------------------------------------

_FAKE_KEY_SECRET = "test_key_secret"
_FAKE_WEBHOOK_SECRET = "test_webhook_secret"
_FAKE_ORDER_ID = "order_test123"
_FAKE_PAYMENT_ID = "pay_test456"


def _make_payment_sig(order_id: str, payment_id: str, secret: str) -> str:
    """Replicate Razorpay's payment signature: HMAC-SHA256(order_id|payment_id)."""
    msg = f"{order_id}|{payment_id}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _make_webhook_sig(body: bytes, secret: str) -> str:
    """Replicate Razorpay's webhook signature: HMAC-SHA256(raw_body)."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# razorpay_client — signature verification (no network, no SDK calls)
# ---------------------------------------------------------------------------

from razorpay_client import verify_webhook_signature


class TestVerifyWebhookSignature:
    def test_valid_signature_returns_true(self):
        body = b'{"event":"payment.captured"}'
        sig = _make_webhook_sig(body, _FAKE_WEBHOOK_SECRET)
        assert verify_webhook_signature(body, sig, _FAKE_WEBHOOK_SECRET) is True

    def test_tampered_body_returns_false(self):
        body = b'{"event":"payment.captured"}'
        sig = _make_webhook_sig(body, _FAKE_WEBHOOK_SECRET)
        tampered = b'{"event":"payment.failed"}'
        assert verify_webhook_signature(tampered, sig, _FAKE_WEBHOOK_SECRET) is False

    def test_wrong_secret_returns_false(self):
        body = b'{"event":"payment.captured"}'
        sig = _make_webhook_sig(body, _FAKE_WEBHOOK_SECRET)
        assert verify_webhook_signature(body, sig, "wrong_secret") is False

    def test_empty_signature_returns_false(self):
        body = b'{"event":"payment.captured"}'
        assert verify_webhook_signature(body, "", _FAKE_WEBHOOK_SECRET) is False


class TestVerifyPaymentSignature:
    """Test verify_payment_signature via the Razorpay SDK (real HMAC logic)."""

    def test_valid_signature_returns_true(self):
        from razorpay_client import create_razorpay_client, verify_payment_signature

        client = create_razorpay_client("rzp_test_key", _FAKE_KEY_SECRET)
        sig = _make_payment_sig(_FAKE_ORDER_ID, _FAKE_PAYMENT_ID, _FAKE_KEY_SECRET)
        assert (
            verify_payment_signature(client, _FAKE_ORDER_ID, _FAKE_PAYMENT_ID, sig)
            is True
        )

    def test_invalid_signature_returns_false(self):
        from razorpay_client import create_razorpay_client, verify_payment_signature

        client = create_razorpay_client("rzp_test_key", _FAKE_KEY_SECRET)
        assert (
            verify_payment_signature(
                client, _FAKE_ORDER_ID, _FAKE_PAYMENT_ID, "bad_signature"
            )
            is False
        )

    def test_wrong_order_id_returns_false(self):
        from razorpay_client import create_razorpay_client, verify_payment_signature

        client = create_razorpay_client("rzp_test_key", _FAKE_KEY_SECRET)
        sig = _make_payment_sig(_FAKE_ORDER_ID, _FAKE_PAYMENT_ID, _FAKE_KEY_SECRET)
        assert (
            verify_payment_signature(client, "order_different", _FAKE_PAYMENT_ID, sig)
            is False
        )


# ---------------------------------------------------------------------------
# FastAPI endpoint tests — Razorpay SDK and Redis mocked
# ---------------------------------------------------------------------------


def _make_app_client():
    """Build a FastAPI TestClient with Razorpay SDK and Redis patched out."""
    from unittest.mock import AsyncMock, MagicMock

    # Patch Razorpay client at module level before importing main.
    fake_rzp_client = MagicMock()
    fake_rzp_client.order.create.return_value = {
        "id": "order_fake123",
        "amount": 499900,
        "currency": "INR",
        "receipt": "test-receipt",
        "status": "created",
    }
    # verify_payment_signature on the SDK utility raises nothing = valid.
    fake_rzp_client.utility.verify_payment_signature.return_value = None

    fake_redis = AsyncMock()
    fake_redis.get.return_value = None
    fake_redis.set.return_value = True
    fake_redis.aclose = AsyncMock()

    with (
        patch("razorpay_client.create_razorpay_client", return_value=fake_rzp_client),
        patch("redis.asyncio.from_url", return_value=fake_redis),
    ):
        # Re-import main fresh with the patches active.
        if "main" in sys.modules:
            del sys.modules["main"]

        import main as payment_main

        payment_main.rzp_client = fake_rzp_client
        payment_main.redis_client = fake_redis

        # Replace _forward_to_booking_service with a no-op so background tasks
        # never attempt real HTTP calls.  Python looks up globals at call time,
        # so this assignment is picked up when confirm_intent / razorpay_webhook
        # execute background.add_task(_forward_to_booking_service, ...).
        payment_main._forward_to_booking_service = AsyncMock()

        from fastapi.testclient import TestClient

        return (
            TestClient(payment_main.app, raise_server_exceptions=True),
            fake_rzp_client,
            fake_redis,
        )


class TestCreateIntent:
    def test_returns_intent_with_razorpay_fields(self):
        client, _, _ = _make_app_client()
        resp = client.post(
            "/payments/intents",
            json={"intent_id": "res-uuid-001", "amount": 4999},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["intent_id"] == "res-uuid-001"
        assert body["razorpay_order_id"] == "order_fake123"
        assert body["status"] == "requires_confirmation"
        assert body["amount"] == 4999.0
        assert "key_id" in body

    def test_missing_intent_id_returns_400(self):
        client, _, _ = _make_app_client()
        resp = client.post("/payments/intents", json={"amount": 100})
        assert resp.status_code == 400

    def test_idempotency_key_returns_cached_intent(self):
        client, _, fake_redis = _make_app_client()
        cached = json.dumps(
            {
                "intent_id": "res-uuid-002",
                "razorpay_order_id": "order_cached",
                "status": "requires_confirmation",
                "amount": 500,
                "key_id": "rzp_test_x",
            }
        )
        fake_redis.get.return_value = cached
        resp = client.post(
            "/payments/intents",
            json={"intent_id": "res-uuid-002", "amount": 500},
            headers={"Idempotency-Key": "idem-key-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["razorpay_order_id"] == "order_cached"


class TestConfirmIntent:
    def test_valid_signature_returns_scheduled(self):
        client, fake_rzp, _ = _make_app_client()
        # SDK utility raises nothing = valid signature.
        fake_rzp.utility.verify_payment_signature.return_value = None
        resp = client.post(
            "/payments/intents/res-uuid-001/confirm",
            json={
                "razorpay_payment_id": _FAKE_PAYMENT_ID,
                "razorpay_order_id": _FAKE_ORDER_ID,
                "razorpay_signature": "any_sig",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "scheduled": True}

    def test_invalid_signature_returns_400(self):
        from razorpay.errors import SignatureVerificationError

        client, fake_rzp, _ = _make_app_client()
        fake_rzp.utility.verify_payment_signature.side_effect = (
            SignatureVerificationError
        )
        resp = client.post(
            "/payments/intents/res-uuid-001/confirm",
            json={
                "razorpay_payment_id": _FAKE_PAYMENT_ID,
                "razorpay_order_id": _FAKE_ORDER_ID,
                "razorpay_signature": "bad_sig",
            },
        )
        assert resp.status_code == 400

    def test_missing_fields_returns_400(self):
        client, _, _ = _make_app_client()
        resp = client.post(
            "/payments/intents/res-uuid-001/confirm",
            json={"razorpay_payment_id": _FAKE_PAYMENT_ID},
        )
        assert resp.status_code == 400


class TestRazorpayWebhook:
    def _valid_body_and_sig(self, event_type: str = "payment.captured") -> tuple:
        body = json.dumps(
            {
                "event": event_type,
                "payload": {
                    "payment": {
                        "entity": {"id": _FAKE_PAYMENT_ID, "order_id": _FAKE_ORDER_ID}
                    },
                    "order": {
                        "entity": {"id": _FAKE_ORDER_ID, "receipt": "res-uuid-003"}
                    },
                },
            }
        ).encode()
        sig = _make_webhook_sig(body, "your_razorpay_webhook_secret_here")
        return body, sig

    def test_valid_captured_event_returns_ok(self):
        client, _, _ = _make_app_client()
        body, sig = self._valid_body_and_sig("payment.captured")
        resp = client.post(
            "/payments/webhook/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_invalid_signature_returns_400(self):
        client, _, _ = _make_app_client()
        body, _ = self._valid_body_and_sig()
        resp = client.post(
            "/payments/webhook/razorpay",
            content=body,
            headers={
                "X-Razorpay-Signature": "badsig",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 400

    def test_unrecognised_event_type_returns_ok(self):
        client, _, _ = _make_app_client()
        body, sig = self._valid_body_and_sig("order.paid")
        resp = client.post(
            "/payments/webhook/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
