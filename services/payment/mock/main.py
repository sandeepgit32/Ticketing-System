"""
Mock Payment Provider Service
==============================
Simulates a third-party payment gateway for local development and integration testing.

The service exposes two endpoints mirroring a typical payment-intent lifecycle:
  1. POST /payments/intents              — create a payment intent
  2. GET  /payments/intents/{id}/confirm — confirm (capture) the intent

Upon confirmation the service fires a signed webhook to the booking service so that
the booking workflow can act on the payment outcome without polling.

Environment variables (see .env.example):
  WEBHOOK_SECRET      Shared HMAC-SHA256 secret used to sign outbound webhook payloads.
  BOOKING_WEBHOOK_URL URL of the booking service webhook receiver.
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Optional

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Header, HTTPException
from fastapi.background import BackgroundTasks

app = FastAPI(title="Mock Payment Provider")

redis_client: Optional[redis.Redis] = None

# TTL for idempotency keys stored in Redis (24 hours).
IDEMPOTENCY_TTL = 86400


def required_env(key: str, cast=str):
    """Return the value of an environment variable or raise if missing.

    Args:
        key: The name of the environment variable.
        cast: Optional callable to cast the string value.

    Raises:
        RuntimeError: if the environment variable is not set.
    """

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


def generate_signature(body: str) -> str:
    """
    Generate an HMAC-SHA256 hex digest for the given request body.

    The booking service must recompute this signature using the shared
    ``WEBHOOK_SECRET`` and compare it to the ``X-Signature`` header to
    authenticate incoming webhook calls.

    Args:
        body: Raw JSON string of the webhook payload.

    Returns:
        str: Lowercase hexadecimal HMAC-SHA256 digest.
    """
    return hmac.new(WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


@app.on_event("startup")
async def startup_event():
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)


@app.on_event("shutdown")
async def shutdown_event():
    if redis_client is not None:
        await redis_client.aclose()


@app.post("/payments/intents")
async def create_intent(payload: dict, idempotency_key: str = Header(None)):
    """
    Create a new payment intent.

    Registers a payment intent using the ``intent_id`` supplied in the request
    body.  The caller is responsible for generating and providing a unique
    ``intent_id`` (e.g. a reservation UUID).  Returns an intent object with
    status ``requires_confirmation``.

    Idempotency is supported via the ``Idempotency-Key`` request header: if the
    same key is sent more than once, the original intent is returned without
    creating a duplicate.

    Args:
        payload: Payment details supplied by the caller.  Must include
            ``intent_id`` (a caller-generated UUID) and should include
            ``amount``.
        idempotency_key: Optional client-generated unique key (HTTP header).

    Returns:
        dict: The created (or previously cached) payment intent.

    Raises:
        HTTPException(400): If ``intent_id`` is missing from the payload.
    """
    # Return the cached intent if the client is retrying with the same key.
    if idempotency_key:
        cached = await redis_client.get(f"idempotency:{idempotency_key}")
        if cached:
            return json.loads(cached)

    intent_id = payload.get("intent_id")
    if not intent_id:
        raise HTTPException(status_code=400, detail="intent_id is required in payload")

    intent = {
        "intent_id": intent_id,
        "status": "requires_confirmation",
        "amount": payload.get("amount"),
    }

    # Only persist to the idempotency store when a key was provided.
    if idempotency_key:
        await redis_client.set(
            f"idempotency:{idempotency_key}", json.dumps(intent), ex=IDEMPOTENCY_TTL
        )

    return intent


@app.get("/payments/intents/{intent_id}/confirm")
async def confirm_intent(intent_id: str, background: BackgroundTasks):
    """
    Confirm (capture) an existing payment intent.

    Triggers a webhook notification to the booking service in the background so
    the HTTP response is returned to the caller immediately, decoupling the
    booking service's processing from the payment provider's response time.

    The webhook payload is signed with HMAC-SHA256 using ``WEBHOOK_SECRET`` and
    delivered in the ``X-Signature`` header, allowing the receiver to verify the
    payload has not been tampered with.

    Success is non-deterministic: the capture succeeds 90% of the time and
    fails 10% of the time, simulating real-world payment provider behaviour.

    FastAPI injects BackgroundTasks automatically from the function signature,
    so it doesn't need to be passed by the caller; it never appeared in the request body

    Args:
        intent_id: UUID of the intent to confirm.

    Returns:
        dict: Acknowledgement that the webhook has been scheduled.

    Examples:
        Successful capture (90% probability)::

            GET /payments/intents/abc-123/confirm
            -> {"ok": True, "scheduled": True}
            # Webhook delivered: {"event": "capture_succeeded", ...}

        Failed capture (10% probability)::

            GET /payments/intents/abc-123/confirm
            -> {"ok": True, "scheduled": True}
            # Webhook delivered: {"event": "capture_failed", ...}
    """
    import random

    success = random.random() < 0.9

    # Build the webhook event payload that mirrors a real provider's callback.
    payload = {
        "event": "capture_succeeded" if success else "capture_failed",
        "payment_id": str(uuid.uuid4()),  # unique ID for this capture attempt
        "intent_id": intent_id,
        "timestamp": int(time.time()),
    }

    # Simulate a delay in processing the confirmation (e.g. to test timeouts).
    time.sleep(4)

    async def send_webhook():
        """Send the signed webhook to the booking service."""
        signature = generate_signature(json.dumps(payload))
        async with httpx.AsyncClient() as client:
            await client.post(
                BOOKING_WEBHOOK_URL,
                json=payload,
                headers={"X-Signature": signature},
            )

    # Schedule the webhook delivery as a background task so the caller receives
    # an immediate response rather than waiting for the HTTP round-trip.
    background.add_task(send_webhook)
    return {"ok": True, "scheduled": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9000)
