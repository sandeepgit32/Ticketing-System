"""
Razorpay Payment Provider Service
===================================
Integrates the real Razorpay payment gateway using the Orders API.

Endpoints:
  POST /payments/intents              — create a Razorpay order (step 1)
  POST /payments/intents/{id}/confirm — verify frontend signature, forward
                                        capture outcome to booking service (step 2)
  POST /payments/webhook/razorpay     — receive Razorpay's direct webhook
                                        (fallback reliability path)

Environment variables (see .env.example):
  RAZORPAY_KEY_ID        Public Razorpay API key.
  RAZORPAY_KEY_SECRET    Secret Razorpay API key.
  RAZORPAY_WEBHOOK_SECRET  Webhook signing secret configured in Razorpay Dashboard.
  WEBHOOK_SECRET         Shared HMAC secret used to sign webhooks to booking service.
  BOOKING_WEBHOOK_URL    URL of the booking service webhook receiver.
  REDIS_URL              Redis connection URL for idempotency and dedup.
"""

import hashlib
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.background import BackgroundTasks

from razorpay_client import (
    create_order,
    create_razorpay_client,
    verify_payment_signature,
    verify_webhook_signature,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IDEMPOTENCY_TTL = 86_400  # 24 hours — cached intents
DEDUP_TTL = 86_400  # 24 hours — seen payment IDs


def required_env(key: str, cast=str):
    """Return the value of an environment variable or raise if missing."""
    value = os.environ.get(key)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return cast(value)


RAZORPAY_KEY_ID = required_env("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = required_env("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = required_env("RAZORPAY_WEBHOOK_SECRET")

# Shared HMAC-SHA256 secret used to sign outbound webhooks to the booking service.
WEBHOOK_SECRET = required_env("WEBHOOK_SECRET")

# Full URL of the booking service webhook receiver.
BOOKING_WEBHOOK_URL = required_env("BOOKING_WEBHOOK_URL")

REDIS_URL = required_env("REDIS_URL")

rzp_client = create_razorpay_client(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)

# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

redis_client: Optional[redis.Redis] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    yield
    if redis_client is not None:
        await redis_client.aclose()


app = FastAPI(title="Razorpay Payment Provider", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign_outbound_webhook(body: str) -> str:
    """Generate HMAC-SHA256 hex digest for outbound webhook to the booking service."""
    return hmac.new(WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


async def _forward_to_booking_service(payload: dict) -> None:
    """Forward a payment outcome to the booking service webhook.

    Uses Redis SETNX to guarantee the booking service receives each unique
    payment at most once, even when both the frontend-confirm path and the
    Razorpay fallback webhook fire for the same payment.

    Args:
        payload: Webhook payload dict with keys ``event``, ``payment_id``,
                 ``intent_id``, and ``timestamp``.
    """
    razorpay_payment_id = payload.get("payment_id")
    if razorpay_payment_id:
        dedup_key = f"seen:{razorpay_payment_id}"
        was_new = await redis_client.set(dedup_key, "1", ex=DEDUP_TTL, nx=True)
        if not was_new:
            return  # already forwarded for this payment ID

    body = json.dumps(payload)
    signature = _sign_outbound_webhook(body)
    async with httpx.AsyncClient() as client:
        await client.post(
            BOOKING_WEBHOOK_URL,
            json=payload,
            headers={"X-Signature": signature},
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/payments/intents")
async def create_intent(payload: dict, idempotency_key: str = Header(None)):
    """Create a Razorpay order (payment intent).

    Calls the Razorpay Orders API to create an order for the given
    ``intent_id`` and ``amount``.  The response includes ``razorpay_order_id``
    and ``key_id`` so the caller can open Razorpay Checkout without a separate
    round-trip to fetch the public key.

    Idempotency is supported via the optional ``Idempotency-Key`` request
    header.  Repeated requests with the same key return the original intent
    from Redis without creating a duplicate order.

    Args:
        payload: Must contain ``intent_id`` (caller-generated UUID, e.g. a
            reservation ID) and optionally ``amount`` (in INR).
        idempotency_key: Optional client-generated key header.

    Returns:
        dict: ``{intent_id, razorpay_order_id, status, amount, key_id}``

    Raises:
        HTTPException(400): If ``intent_id`` is missing.
        HTTPException(502): If Razorpay order creation fails.
    """
    if idempotency_key:
        cached = await redis_client.get(f"idempotency:{idempotency_key}")
        if cached:
            return json.loads(cached)

    intent_id = payload.get("intent_id")
    if not intent_id:
        raise HTTPException(status_code=400, detail="intent_id is required in payload")

    amount_inr = float(payload.get("amount") or 0)

    try:
        order = create_order(rzp_client, amount_inr, receipt=intent_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Razorpay order creation failed: {exc}"
        )

    intent = {
        "intent_id": intent_id,
        "razorpay_order_id": order["id"],
        "status": "requires_confirmation",
        "amount": amount_inr,
        "key_id": RAZORPAY_KEY_ID,
    }

    if idempotency_key:
        await redis_client.set(
            f"idempotency:{idempotency_key}",
            json.dumps(intent),
            ex=IDEMPOTENCY_TTL,
        )

    return intent


@app.post("/payments/intents/{intent_id}/confirm")
async def confirm_intent(intent_id: str, payload: dict, background: BackgroundTasks):
    """Verify the Razorpay payment signature and forward the outcome to the booking service.

    The frontend calls this endpoint after the customer completes payment on
    Razorpay Checkout, passing back the three Razorpay fields that Razorpay
    delivers to the checkout handler.  This service verifies the signature
    using the Razorpay SDK, then asynchronously forwards a ``capture_succeeded``
    webhook to the booking service.

    The response is returned immediately; webhook delivery happens in the
    background.  Deduplication in ``_forward_to_booking_service`` ensures the
    booking service receives at most one event even when both this path and the
    Razorpay fallback webhook fire for the same payment.

    Args:
        intent_id: Internal reservation UUID (path parameter).
        payload: Must contain ``razorpay_payment_id``, ``razorpay_order_id``,
                 and ``razorpay_signature``.

    Returns:
        ``{"ok": True, "scheduled": True}``

    Raises:
        HTTPException(400): If any required field is missing or the signature
            is invalid.
    """
    razorpay_payment_id = payload.get("razorpay_payment_id")
    razorpay_order_id = payload.get("razorpay_order_id")
    razorpay_signature = payload.get("razorpay_signature")

    if not razorpay_payment_id or not razorpay_order_id or not razorpay_signature:
        raise HTTPException(
            status_code=400,
            detail=(
                "razorpay_payment_id, razorpay_order_id, and razorpay_signature "
                "are required"
            ),
        )

    if not verify_payment_signature(
        rzp_client, razorpay_order_id, razorpay_payment_id, razorpay_signature
    ):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    webhook_payload = {
        "event": "capture_succeeded",
        "payment_id": razorpay_payment_id,
        "intent_id": intent_id,
        "timestamp": int(time.time()),
    }

    background.add_task(_forward_to_booking_service, webhook_payload)
    return {"ok": True, "scheduled": True}


@app.post("/payments/webhook/razorpay")
async def razorpay_webhook(request: Request, background: BackgroundTasks):
    """Receive and verify Razorpay's direct inbound webhook (fallback reliability path).

    Razorpay sends ``payment.captured`` or ``payment.failed`` events to this
    endpoint when configured in the Razorpay Dashboard.  This path covers the
    case where the customer's browser crashes or loses connectivity after
    Razorpay captures the payment but before the frontend calls the confirm
    endpoint, preventing bookings from being stranded in a paid-but-unconfirmed
    state forever.

    The ``X-Razorpay-Signature`` header is verified against the raw body using
    ``RAZORPAY_WEBHOOK_SECRET``.  Unrecognised event types are acknowledged and
    ignored.  Deduplication in ``_forward_to_booking_service`` ensures the
    booking service receives exactly one event when both this path and the
    confirm endpoint fire for the same payment.

    Returns:
        ``{"ok": True}`` for every valid (and signed) request, including
        ignored event types.

    Raises:
        HTTPException(400): If the signature is invalid or the body is not
            valid JSON.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not verify_webhook_signature(body, signature, RAZORPAY_WEBHOOK_SECRET):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        event_data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event_data.get("event")
    if event_type not in ("payment.captured", "payment.failed"):
        return {"ok": True}  # acknowledge and ignore

    payment_entity = event_data.get("payload", {}).get("payment", {}).get("entity", {})
    razorpay_payment_id = payment_entity.get("id")

    # Recover the internal intent_id from the receipt field on the order entity.
    # The receipt was set to the reservation UUID when the order was created.
    order_entity = event_data.get("payload", {}).get("order", {}).get("entity", {})
    intent_id = order_entity.get("receipt") or payment_entity.get("order_id")

    if not razorpay_payment_id:
        return {"ok": True}

    event = (
        "capture_succeeded" if event_type == "payment.captured" else "capture_failed"
    )

    webhook_payload = {
        "event": event,
        "payment_id": razorpay_payment_id,
        "intent_id": intent_id,
        "timestamp": int(time.time()),
    }

    background.add_task(_forward_to_booking_service, webhook_payload)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9000)
