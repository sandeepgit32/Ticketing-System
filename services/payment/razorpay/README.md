# Razorpay Payment Provider

Integrates the Razorpay payment gateway using the **Orders API**. Handles the full payment lifecycle — order creation, frontend-signature verification, and a fallback Razorpay webhook — then forwards the outcome to the booking service via a signed webhook.

---

## How it works

```
Booking Service          Payment Service (Razorpay)         Razorpay
      |                          |                               |
      |-- POST /payments/intents -->                             |
      |<-- { intent_id,            |                             |
      |      razorpay_order_id,    |-- create order ------------>|
      |      key_id, ... } --------|<-- { order_id } ------------|
      |                           |                              |

Frontend (Vue)            Payment Service (Razorpay)         Razorpay
      |                          |                              |
      | opens Razorpay Checkout  |                              |
      | with key_id + order_id ------------------------------------------------>|
      |                          |                              |-- payment ---->|
      |<-- { payment_id,         |                              |                |
      |      order_id, sig } ----|----------------------------------------------|
      |                          |                              |
      |-- POST /payments/intents/{id}/confirm -->               |
      |      { razorpay_payment_id,              |              |
      |        razorpay_order_id,                |              |
      |        razorpay_signature }              |              |
      |<-- { ok: true, scheduled: true } --------|              |
      |                          |                              |
      |                          |-- POST /payments/webhook ---->
      |                          |   (signed, to booking svc)   |

                                           — OR (fallback) —

Razorpay                  Payment Service (Razorpay)    Booking Service
      |                          |                              |
      |-- POST /payments/webhook/razorpay -------->             |
      |                          | verify X-Razorpay-Signature  |
      |                          |-- POST /payments/webhook ---->
      |                          |   (signed, deduplicated)
```

1. The booking service calls `POST /payments/intents` to create a Razorpay order, receiving back `razorpay_order_id` and `key_id`.
2. The frontend opens Razorpay Checkout using those values. The customer completes payment on Razorpay's hosted UI.
3. Razorpay returns `razorpay_payment_id`, `razorpay_order_id`, and `razorpay_signature` to the frontend callback.
4. The frontend calls `POST /payments/intents/{id}/confirm`. The payment service verifies the signature and asynchronously forwards a `capture_succeeded` webhook to the booking service.
5. As a reliability fallback, Razorpay also fires `payment.captured` / `payment.failed` directly to `POST /payments/webhook/razorpay`. Redis deduplication ensures the booking service receives each outcome exactly once regardless of which path fires first.

---

## Environment variables

Copy `.env.example` to `.env` and fill in the values.

| Variable                  | Required | Description                                                                                     |
|---------------------------|----------|-------------------------------------------------------------------------------------------------|
| `RAZORPAY_KEY_ID`         | Yes      | Public Razorpay API key ID. Found in Dashboard → Settings → API Keys.                          |
| `RAZORPAY_KEY_SECRET`     | Yes      | Secret Razorpay API key. Never expose to the frontend.                                          |
| `RAZORPAY_WEBHOOK_SECRET` | Yes      | Webhook signing secret set in Dashboard → Settings → Webhooks. Verifies inbound webhooks.      |
| `WEBHOOK_SECRET`          | Yes      | Shared HMAC-SHA256 secret. Must match the value in the booking service.                         |
| `BOOKING_WEBHOOK_URL`     | Yes      | Full URL of the booking service webhook receiver (e.g. `http://booking:8000/payments/webhook`). |
| `REDIS_URL`               | Yes      | Redis connection URL for idempotency and payment deduplication.                                 |

---

## API reference

### `POST /payments/intents`

Creates a Razorpay order.

**Headers**

| Header            | Required | Description                                                                                              |
|-------------------|----------|----------------------------------------------------------------------------------------------------------|
| `Idempotency-Key` | No       | Client-generated unique key. Repeated requests with the same key return the original order from cache.  |

**Request body**

```json
{
  "intent_id": "550e8400-e29b-41d4-a716-446655440000",
  "amount": 4999
}
```

| Field       | Required | Description                                          |
|-------------|----------|------------------------------------------------------|
| `intent_id` | Yes      | Caller-generated UUID (e.g. the reservation ID).     |
| `amount`    | No       | Amount in INR. Converted to paise internally (×100). |

**Response `200`**

```json
{
  "intent_id": "550e8400-e29b-41d4-a716-446655440000",
  "razorpay_order_id": "order_ABC123",
  "status": "requires_confirmation",
  "amount": 4999,
  "key_id": "rzp_test_..."
}
```

**Error responses**

| Status | Condition                             |
|--------|---------------------------------------|
| `400`  | `intent_id` is missing from body.     |
| `502`  | Razorpay order creation API failure.  |

---

### `POST /payments/intents/{intent_id}/confirm`

Verifies the Razorpay payment signature from the frontend and schedules a webhook to the booking service.

**Path parameters**

| Parameter   | Description                                 |
|-------------|---------------------------------------------|
| `intent_id` | Internal reservation UUID.                  |

**Request body**

```json
{
  "razorpay_payment_id": "pay_XYZ456",
  "razorpay_order_id": "order_ABC123",
  "razorpay_signature": "<hmac-sha256-hex>"
}
```

**Response `200`**

```json
{ "ok": true, "scheduled": true }
```

**Error responses**

| Status | Condition                                            |
|--------|------------------------------------------------------|
| `400`  | Any required field is missing or signature is wrong. |

---

### `POST /payments/webhook/razorpay`

Receives signed webhooks directly from Razorpay (fallback reliability path).

**Headers**

| Header                   | Required | Description                                                     |
|--------------------------|----------|-----------------------------------------------------------------|
| `X-Razorpay-Signature`   | Yes      | HMAC-SHA256 hex digest of the raw body, signed by Razorpay.    |

**Handled event types**

| Event              | Forwarded as          |
|--------------------|-----------------------|
| `payment.captured` | `capture_succeeded`   |
| `payment.failed`   | `capture_failed`      |
| All others         | Acknowledged, ignored |

**Response `200`**

```json
{ "ok": true }
```

**Error responses**

| Status | Condition                              |
|--------|----------------------------------------|
| `400`  | Invalid signature or malformed JSON.   |

---

### Outbound webhook to booking service

For both the confirm and fallback paths the payment service forwards the outcome to `BOOKING_WEBHOOK_URL`. The body format is identical to the mock service so the booking service requires no changes.

```json
{
  "event": "capture_succeeded",
  "payment_id": "pay_XYZ456",
  "intent_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1742390400
}
```

The `X-Signature` header carries an HMAC-SHA256 hex digest of the JSON body, signed with `WEBHOOK_SECRET`. The booking service verifies this before processing.

---

## Running locally

```bash
cp .env.example .env
# edit .env with your Razorpay credentials

docker build -t payment-razorpay .
docker run --env-file .env -p 9000:9000 payment-razorpay
```

The service will be available at `http://localhost:9000`. Interactive API docs are at `http://localhost:9000/docs`.

## Running tests

```bash
cd services/payment/razorpay
pip install -r requirements.txt
pytest test_payment_razorpay.py -v
```

Tests run fully offline — the Razorpay SDK and Redis are mocked.
