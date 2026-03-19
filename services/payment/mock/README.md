# Mock Payment Provider

Simulates a third-party payment gateway for local development and integration testing. It mirrors a typical payment-intent lifecycle and fires signed webhooks to the booking service upon confirmation, so the rest of the system can be exercised end-to-end without a real payment provider.

---

## How it works

```
Booking Service                Mock Payment Provider              Booking Service
      |                                 |                               |
      |-- POST /payments/intents ------>|                               |
      |<-- { intent_id, status } -------|                               |
      |                                 |                               |
      |-- GET  /payments/intents/{id}/confirm -->|                      |
      |<-- { ok: true, scheduled: true }---------|                      |
      |                                 |                               |
      |                                 |-- POST /payments/webhook ---->|
      |                                 |   (signed webhook, async)     |
```

1. The booking service creates a payment intent, receiving back an `intent_id`.
2. It then calls confirm on that intent. The mock immediately returns an acknowledgement while scheduling the webhook delivery in the background.
3. The webhook is delivered asynchronously to the booking service with the outcome — `capture_succeeded` 90% of the time, `capture_failed` 10% of the time — simulating real-world provider behaviour.
4. Every outbound webhook is signed with HMAC-SHA256 using the shared `WEBHOOK_SECRET`. The booking service verifies the `X-Signature` header before processing the event.

---

## Environment variables

Copy `.env.example` to `.env` and fill in the values.

| Variable            | Required | Description                                                                             |
|---------------------|----------|-----------------------------------------------------------------------------------------|
| `WEBHOOK_SECRET`    | Yes      | Shared HMAC-SHA256 secret. Must match the value configured in the booking service.      |
| `BOOKING_WEBHOOK_URL` | Yes    | Full URL of the booking service webhook receiver (e.g. `http://booking:8000/payments/webhook`). |
| `REDIS_URL`         | Yes      | Redis connection URL used for idempotency key storage (e.g. `redis://redis:6379/0`).   |

---

## API reference

### `POST /payments/intents`

Creates a new payment intent.

**Headers**

| Header            | Required | Description                                                      |
|-------------------|----------|------------------------------------------------------------------|
| `Idempotency-Key` | No       | Client-generated unique key. Repeated requests with the same key return the original intent without creating a duplicate. Cached for 24 hours in Redis. |

**Request body**

```json
{
  "intent_id": "550e8400-e29b-41d4-a716-446655440000",
  "amount": 4999,
  "currency": "usd"
}
```

| Field       | Required | Description                                      |
|-------------|----------|--------------------------------------------------|
| `intent_id` | Yes      | Caller-generated UUID (e.g. the reservation ID). |
| `amount`    | No       | Amount in the smallest currency unit (cents).    |
| `currency`  | No       | ISO 4217 currency code.                          |

**Response `200`**

```json
{
  "intent_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "requires_confirmation",
  "amount": 4999,
  "currency": "usd"
}
```

**Error responses**

| Status | Condition                          |
|--------|------------------------------------|
| `400`  | `intent_id` is missing from body.  |

---

### `GET /payments/intents/{intent_id}/confirm`

Confirms (captures) an existing payment intent and schedules an asynchronous webhook to the booking service.

**Path parameters**

| Parameter   | Description                             |
|-------------|-----------------------------------------|
| `intent_id` | UUID of the intent to confirm.          |

**Response `200`**

Always returned immediately, before the webhook is delivered.

```json
{
  "ok": true,
  "scheduled": true
}
```

**Webhook delivered to `BOOKING_WEBHOOK_URL`**

The outcome is non-deterministic: `capture_succeeded` 90% of the time, `capture_failed` 10% of the time.

```json
{
  "event": "capture_succeeded",
  "payment_id": "a1b2c3d4-...",
  "intent_id": "550e8400-...",
  "timestamp": 1742390400
}
```

| Field        | Description                                          |
|--------------|------------------------------------------------------|
| `event`      | `capture_succeeded` or `capture_failed`.             |
| `payment_id` | Unique UUID generated for this capture attempt.      |
| `intent_id`  | The intent UUID passed in the path.                  |
| `timestamp`  | Unix timestamp of when the confirmation was processed. |

The webhook includes an `X-Signature` header containing the HMAC-SHA256 hex digest of the JSON body, signed with `WEBHOOK_SECRET`. The booking service must verify this before trusting the payload:

```python
import hashlib, hmac, json

expected = hmac.new(
    WEBHOOK_SECRET.encode(),
    json.dumps(payload).encode(),
    hashlib.sha256,
).hexdigest()

assert hmac.compare_digest(expected, request.headers["X-Signature"])
```

> **Note:** There is a simulated 4-second processing delay before the webhook is dispatched, mimicking a slow payment provider. The HTTP response is returned to the caller before this delay completes.

---

## Running locally

```bash
cp .env.example .env
# edit .env with your values

docker build -t payment-mock .
docker run --env-file .env -p 9000:9000 payment-mock
```

The service will be available at `http://localhost:9000`. Interactive API docs are at `http://localhost:9000/docs`.
