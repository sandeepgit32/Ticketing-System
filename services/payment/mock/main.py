"""
Mock Payment Provider Service
==============================
Simulates a third-party payment gateway for local development and integration testing.

The service exposes three endpoints mirroring a typical payment-intent lifecycle:
  1. POST /payments/intents         — create a payment intent
  2. POST /payments/intents/{id}/confirm — confirm (capture) the intent
  3. POST /admin/next               — placeholder for deterministic test control

Upon confirmation the service fires a signed webhook to the booking service so that
the booking workflow can act on the payment outcome without polling.

Environment variables (see .env.example):
  WEBHOOK_SECRET      Shared HMAC-SHA256 secret used to sign outbound webhook payloads.
  BOOKING_WEBHOOK_URL URL of the booking service webhook receiver.
"""

import os
import uuid
import time
import hmac
import hashlib
import json
from fastapi import FastAPI, Header, HTTPException
from fastapi.background import BackgroundTasks
import httpx

app = FastAPI(title="Mock Payment Provider")

# In-memory store that maps idempotency keys to previously created intents.
# This ensures that retried requests with the same key return the same intent.
intents: dict = {}

# Shared secret used to generate HMAC-SHA256 signatures on outbound webhooks.
# The booking service must use the same secret to verify authenticity.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")

# Full URL of the booking service endpoint that receives payment webhook events.
BOOKING_WEBHOOK_URL = os.getenv(
    "BOOKING_WEBHOOK_URL", "http://booking:8000/payments/webhook"
)


@app.post("/payments/intents")
async def create_intent(payload: dict, idempotency_key: str = Header(None)):
    """
    Create a new payment intent.

    Accepts an arbitrary JSON payload (e.g. amount, currency, booking reference)
    and returns an intent object with status ``requires_confirmation``.

    Idempotency is supported via the ``Idempotency-Key`` request header: if the
    same key is sent more than once, the original intent is returned without
    creating a duplicate.

    Args:
        payload: Arbitrary payment details supplied by the caller.
        idempotency_key: Optional client-generated unique key (HTTP header).

    Returns:
        dict: The created (or previously cached) payment intent.
    """
    # Return the cached intent if the client is retrying with the same key.
    if idempotency_key and idempotency_key in intents:
        return intents[idempotency_key]

    intent_id = str(uuid.uuid4())
    intent = {
        "intent_id": intent_id,
        "status": "requires_confirmation",
        "payload": payload,
    }

    # Only persist to the idempotency store when a key was provided.
    if idempotency_key:
        intents[idempotency_key] = intent

    return intent


@app.post("/payments/intents/{intent_id}/confirm")
async def confirm_intent(
    intent_id: str, background: BackgroundTasks, delay_ms: int = 0, success: bool = True
):
    """
    Confirm (capture) an existing payment intent.

    Triggers a webhook notification to the booking service in the background so
    the HTTP response is returned to the caller immediately, decoupling the
    booking service's processing from the payment provider's response time.

    The webhook payload is signed with HMAC-SHA256 using ``WEBHOOK_SECRET`` and
    delivered in the ``X-Signature`` header, allowing the receiver to verify the
    payload has not been tampered with.

    Args:
        intent_id: UUID of the intent to confirm.
        background: FastAPI background task runner.
        delay_ms: Reserved for future use — intended to simulate processing delay.
        success: When ``True`` the webhook reports ``capture_succeeded``,
                 otherwise ``capture_failed``.

    Returns:
        dict: Acknowledgement that the webhook has been scheduled.
    """
    # Build the webhook event payload that mirrors a real provider's callback.
    payload = {
        "event": "capture_succeeded" if success else "capture_failed",
        "payment_id": str(uuid.uuid4()),  # unique ID for this capture attempt
        "intent_id": intent_id,
        "timestamp": int(time.time()),
    }

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


@app.post("/admin/next")
async def set_next(payload: dict):
    """
    Configure the outcome of the next payment confirmation (stub).

    Intended to allow test suites to pre-program whether the next
    ``/payments/intents/{id}/confirm`` call should succeed or fail, enabling
    fully deterministic integration tests without modifying query parameters.

    Currently a no-op placeholder — behaviour can be wired up as needed.

    Args:
        payload: Configuration dict (e.g. ``{"success": false}``).

    Returns:
        dict: Simple acknowledgement.
    """
    # TODO: store payload to influence the next confirm call deterministically.
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9000)
