# Razorpay Integration — Step-by-Step Instructions

Follow these steps to go from a fresh Razorpay account to a fully working payment flow in this system.

---

## Step 1 — Create a Razorpay account

> **Note:** Razorpay requires personal and business details — including a **PAN number** — during sign-up, even to access Test Mode. This is mandatory and cannot be bypassed.
>
> **If you do not want to provide a PAN number, stop here and use the mock payment service** (`services/payment/mock/`) for local development and testing. It implements the same API contract and all automated tests pass against it without any credentials.

1. Go to [https://razorpay.com](https://razorpay.com) and click **Sign Up**.
2. Enter your mobile number and verify it with the OTP sent by Razorpay.
3. Fill in your business details: business name, business type (individual/sole proprietor is accepted), and **PAN** (mandatory).
4. Verify your email address.
5. You will now have access to the dashboard in **Test Mode**. Full KYC (bank account, address proof, etc.) is only required before switching to **Live Mode** to accept real payments.

---

## Step 2 — Switch to Test Mode and generate API keys

1. Log in to the [Razorpay Dashboard](https://dashboard.razorpay.com).
2. In the top-right corner, ensure **Test Mode** is selected (toggle next to your account name).
3. Navigate to **Settings → API Keys**.
4. Click **Generate Test Key**.
5. Copy both values that appear:
   - **Key ID** — starts with `rzp_test_`
   - **Key Secret** — shown only once; copy it immediately.
6. Keep these safe. You will add them to `.env` in Step 4.

> For production, switch to **Live Mode** and repeat this process to get `rzp_live_` keys.

---

## Step 3 — Configure the webhook endpoint in Razorpay

The payment service has a fallback endpoint that Razorpay calls directly when the frontend cannot complete the confirm step (e.g. browser crash after payment).

1. In the Razorpay Dashboard, go to **Settings → Webhooks**.
2. Click **Add New Webhook**.
3. Set **Webhook URL** to the public URL of the payment service's fallback endpoint:
   ```
   https://<your-domain>/payments/webhook/razorpay
   ```
   > In local development, use a tunnelling tool such as [ngrok](https://ngrok.com):
   > ```bash
   > ngrok http 9000
   > # copy the https URL, e.g. https://abc123.ngrok.io
   > # Webhook URL: https://abc123.ngrok.io/payments/webhook/razorpay
   > ```
4. Under **Active Events**, enable:
   - `payment.captured`
   - `payment.failed`
5. Set a **Secret** (any strong random string, e.g. `openssl rand -hex 32`).
   Copy this value — it goes into `RAZORPAY_WEBHOOK_SECRET` in `.env`.
6. Click **Save**.

---

## Step 4 — Configure environment variables

Navigate to the payment service directory:

```bash
cd services/payment/razorpay
cp .env.example .env
```

Open `.env` and fill in the following values:

| Variable                  | Where to find it                                     |
|---------------------------|------------------------------------------------------|
| `RAZORPAY_KEY_ID`         | Dashboard → Settings → API Keys (Key ID)             |
| `RAZORPAY_KEY_SECRET`     | Dashboard → Settings → API Keys (Key Secret)         |
| `RAZORPAY_WEBHOOK_SECRET` | Dashboard → Settings → Webhooks (the secret you set) |
| `WEBHOOK_SECRET`          | Any shared secret you choose; must match booking service |
| `BOOKING_WEBHOOK_URL`     | URL of the booking service webhook endpoint          |
| `REDIS_URL`               | Your Redis connection string                         |

Example `.env` for local Docker Compose:

```
RAZORPAY_KEY_ID=rzp_test_AbCdEfGhIjKlMn
RAZORPAY_KEY_SECRET=AbCdEfGhIjKlMnOpQrStUv
RAZORPAY_WEBHOOK_SECRET=myrandomwebhooksecret
WEBHOOK_SECRET=shared-booking-secret
BOOKING_WEBHOOK_URL=http://booking:8000/payments/webhook
REDIS_URL=redis://redis:6379/0
```

Also update the booking service's env to set:
```
PAYMENT_PROVIDER_URL=http://payment-razorpay:9000
```

---

## Step 5 — Build and run the service

**With Docker:**

```bash
docker build -t payment-razorpay .
docker run --env-file .env -p 9000:9000 payment-razorpay
```

**With Docker Compose** (alongside the rest of the system):

Update `docker-compose.yml` to point the booking service at the new payment service, then:

```bash
docker compose up --build
```

Verify the service is healthy:

```bash
curl http://localhost:9000/docs   # opens interactive API docs
```

---

## Step 6 — Test the payment flow end-to-end

### 6a. Test with the interactive docs (manual)

1. Open `http://localhost:9000/docs`.
2. Call `POST /payments/intents` with a test payload:
   ```json
   { "intent_id": "test-reservation-001", "amount": 500 }
   ```
3. Note the `razorpay_order_id` and `key_id` in the response.
4. Use Razorpay's test card details to simulate a payment:
   - **Card number**: `4111 1111 1111 1111`
   - **Expiry**: any future date
   - **CVV**: any 3 digits
   - **OTP**: `1234`

### 6b. Run the automated tests (offline, no real API calls)

```bash
cd services/payment/razorpay
pip install -r requirements.txt
pytest test_payment_razorpay.py -v
```

All tests mock the Razorpay SDK and Redis — no credentials required.

### 6c. Test the Razorpay webhook fallback

1. Make sure your ngrok tunnel is running and the webhook URL is configured in the Dashboard (see Step 3).
2. In the Razorpay Dashboard, go to **Settings → Webhooks**, open your webhook, and click **Test** to send a sample `payment.captured` event.
3. Check the payment service logs — you should see it verify the signature and forward to the booking service.

---

## Step 7 — Go live

1. In the Razorpay Dashboard, switch to **Live Mode**.
2. Generate new **Live API Keys** (Settings → API Keys).
3. Update `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` in your production `.env` / secrets store.
4. Update the webhook URL to your production domain and generate a new `RAZORPAY_WEBHOOK_SECRET`.
5. Complete Razorpay KYC if not done already.

> Never commit real API keys or secrets to version control. Use a secrets manager (e.g. AWS Secrets Manager, HashiCorp Vault, Kubernetes Secrets) in production.
