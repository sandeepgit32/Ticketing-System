"""
Mock Payment Provider Service
==============================
Simulates a third-party payment gateway for local development and integration testing.

The service exposes endpoints mirroring the Razorpay payment-intent lifecycle so that
the gateway can switch between mock and Razorpay by only changing PAYMENT_SERVICE_URL:

  POST /payments/intents              — create a mock payment intent
  POST /payments/intents/{id}/confirm — confirm (capture) the intent

Upon confirmation the service fires a signed webhook to the booking service so that
the booking workflow can act on the payment outcome without polling.

Environment variables (see .env.example):
  WEBHOOK_SECRET      Shared HMAC-SHA256 secret used to sign outbound webhook payloads.
  BOOKING_WEBHOOK_URL URL of the booking service webhook receiver.
  REDIS_URL           Redis connection URL for idempotency and deduplication.
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Header, HTTPException
from fastapi.background import BackgroundTasks

# TTL for idempotency keys stored in Redis (24 hours).
IDEMPOTENCY_TTL = 86_400

# TTL for deduplication keys stored in Redis (24 hours).
DEDUP_TTL = 86_400


def required_env(key: str, cast=str):
    """Return the value of an environment variable or raise if missing."""
    value = os.environ.get(key)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return cast(value)


# Shared secret used to generate HMAC-SHA256 signatures on outbound webhooks.
# The booking service must use the same secret to verify authenticity.
WEBHOOK_SECRET = required_env("WEBHOOK_SECRET")

# Full URL of the booking service endpoint that receives payment webhook events.
BOOKING_WEBHOOK_URL = required_env("BOOKING_WEBHOOK_URL")

REDIS_URL = required_env("REDIS_URL")

redis_client: Optional[redis.Redis] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    yield
    if redis_client is not None:
        await redis_client.aclose()


app = FastAPI(title="Mock Payment Provider", lifespan=lifespan)


def generate_signature(body: str) -> str:
    """Generate an HMAC-SHA256 hex digest for the given request body.

    The booking service must recompute this signature using the shared
    ``WEBHOOK_SECRET`` and compare it to the ``X-Signature`` header to
    authenticate incoming webhook calls.

    Args:
        body: Raw JSON string of the webhook payload.

    Returns:
        str: Lowercase hexadecimal HMAC-SHA256 digest.
    """
    return hmac.new(WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


async def _forward_to_booking_service(payload: dict) -> None:
    """Forward a payment outcome to the booking service webhook.

    Uses Redis SETNX to guarantee the booking service receives each unique
    payment at most once, preventing duplicate events when retries occur.

    Args:
        payload: Webhook payload dict with keys ``event``, ``payment_id``,
                 ``intent_id``, and ``timestamp``.
    """
    mock_payment_id = payload.get("payment_id")
    if mock_payment_id:
        dedup_key = f"seen:{mock_payment_id}"
        was_new = await redis_client.set(dedup_key, "1", ex=DEDUP_TTL, nx=True)
        if not was_new:
            return  # already forwarded for this payment ID

    body = json.dumps(payload)
    signature = generate_signature(body)
    async with httpx.AsyncClient() as client:
        await client.post(
            BOOKING_WEBHOOK_URL,
            json=payload,
            headers={"X-Signature": signature},
        )


@app.post("/payments/intents")
async def create_intent(payload: dict, idempotency_key: str = Header(None)):
    """Create a new mock payment intent.

    Returns a response shaped like the Razorpay provider so the gateway and
    frontend can switch between them without code changes.  ``mock_order_id``
    corresponds to Razorpay's ``razorpay_order_id`` and ``key_id`` is set to
    ``"mock"`` to indicate no real checkout SDK is needed.

    Idempotency is supported via the optional ``Idempotency-Key`` request header.

    Args:
        payload: Must contain ``intent_id`` (a caller-generated UUID) and
            optionally ``amount``.
        idempotency_key: Optional client-generated unique key (HTTP header).

    Returns:
        dict: ``{intent_id, mock_order_id, status, amount, key_id}``

    Raises:
        HTTPException(400): If ``intent_id`` is missing from the payload.
    """
    if idempotency_key:
        cached = await redis_client.get(f"idempotency:{idempotency_key}")
        if cached:
            return json.loads(cached)

    intent_id = payload.get("intent_id")
    if not intent_id:
        raise HTTPException(status_code=400, detail="intent_id is required in payload")

    amount = float(payload.get("amount") or 0)
    mock_order_id = f"mock_order_{uuid.uuid4().hex[:16]}"

    intent = {
        "intent_id": intent_id,
        "mock_order_id": mock_order_id,
        "status": "requires_confirmation",
        "amount": amount,
        "key_id": "mock",
    }

    if idempotency_key:
        await redis_client.set(
            f"idempotency:{idempotency_key}", json.dumps(intent), ex=IDEMPOTENCY_TTL
        )

    return intent


@app.post("/payments/intents/{intent_id}/confirm")
async def confirm_intent(intent_id: str, payload: dict, background: BackgroundTasks):
    """Confirm (capture) an existing mock payment intent.

    Mirrors the Razorpay confirm endpoint signature so the gateway route and
    frontend adapter require no changes when switching providers.  The mock
    fields ``mock_payment_id``, ``mock_order_id``, and ``mock_signature`` are
    all optional — the mock does not perform real signature verification.

    Success is non-deterministic: the capture succeeds 90 % of the time and
    fails 10 % of the time, simulating real-world payment provider behaviour.

    Args:
        intent_id: Internal reservation UUID (path parameter).
        payload: Optionally contains ``mock_payment_id``, ``mock_order_id``,
                 and ``mock_signature`` (all ignored for verification, present
                 only to keep the call shape consistent with Razorpay).

    Returns:
        ``{"ok": True, "scheduled": True}``
    """
    import random

    success = random.random() < 0.9
    mock_payment_id = (
        payload.get("mock_payment_id") or f"mock_pay_{uuid.uuid4().hex[:16]}"
    )

    webhook_payload = {
        "event": "capture_succeeded" if success else "capture_failed",
        "payment_id": mock_payment_id,
        "intent_id": intent_id,
        "timestamp": int(time.time()),
    }

    background.add_task(_forward_to_booking_service, webhook_payload)
    return {"ok": True, "scheduled": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
