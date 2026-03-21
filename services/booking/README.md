# Booking Service

This microservice manages event inventory and seat reservations for the ticketing system. It stores event and seat state in MySQL, uses Redis for fast runtime state and queues, and coordinates payment capture/webhook workflows.

## Responsibilities

- Load venue layouts and per-row pricing from `venue_config.yaml`.
- Expose venue and event APIs for listing and viewing event seat maps.
- Create events and pre-populate normalized seat inventory in MySQL.
- Reserve explicit seats with Redis Lua atomic hold + MySQL transaction persistence.
- Compensate Redis holds if DB persistence fails.
- Run expiry worker to release expired holds in Redis and MySQL.
- Support idempotent reservation retries using Redis (`Idempotency-Key`).
- Forward payment capture requests to the payment provider.
- Handle payment webhooks and create confirmed bookings.
- Publish notification jobs to Redis queues.
- Close events and clean up reservation runtime state.

## Configuration

The service validates required environment variables at import/startup. A `.env.example` file is included in this folder.

```env
# Redis
REDIS_URL=redis://redis:6379/0

# MySQL
MYSQL_HOST=database
MYSQL_PORT=3306
MYSQL_USER=ticketuser
MYSQL_PASSWORD=ticketpass
MYSQL_DATABASE=ticketing

# Payment provider base URL (required by /payments/capture)
PAYMENT_PROVIDER_URL=http://payment-mock:9000

# Reservation hold duration
RESERVATION_TTL_SECONDS=600
```

Notes:
- `PAYMENT_PROVIDER_URL` is required when calling `POST /payments/capture`.
- `RESERVATION_TTL_SECONDS` controls reservation expiry and idempotency cache TTL.
- The service loads `venue_config.yaml` on startup and uses it as source-of-truth for seat layout and row pricing.

## Data Model

The service expects the following MySQL tables from `services/database/init.sql`:

- `events`
- `seats`
- `reservations`
- `bookings`

Key points:
- `seats` is normalized by `(event_id, seat_id)` and tracks `occupied`, `reservation_id`, and `price`.
- `reservations.seats` and `bookings.seats` are JSON payloads.
- Reservation and booking status transitions are recorded in MySQL.

## Redis Usage

- `queue:notifications`: notification jobs for the notification service.
- `queue:jobs`: generic background jobs (webhook job fanout).
- `seats:{event_id}:bitmap`: primary in-memory reservation hold bitmap.
- `reservation:{reservation_id}` and `reservations:ttl`: runtime hold metadata and expiry index.
- `idempotency:{Idempotency-Key}`: cached response for reservation retries.

Lua scripts loaded at startup:

- `redis_reserve.lua`: contiguous block reservation strategy (available for row-based allocation).
- `redis_reserve_explicit.lua`: atomic explicit-seat hold for `/bookings/reserve`.
- `redis_release_explicit.lua`: atomic explicit-seat release (compensation and expiry cleanup).

## Why Redis Lua Scripting Is Used

The booking domain is highly concurrency-sensitive: many users can try to reserve the same seats at the same moment during a flash sale. Redis Lua scripting is used to make reservation-critical operations execute atomically inside Redis.

### Core reasons

- Atomic read-modify-write: with Lua, finding available seats and marking them as taken happens in one server-side operation. No other client can interleave commands mid-operation.
- Race condition prevention: without Lua, a client might `GET` availability and then `SET` new occupancy in separate calls, allowing another request to claim the same seats in between.
- Lower round-trips: complex logic (scan bitmap, pick block, write reservation metadata, set TTL, add sorted-set expiry index) runs in one call (`EVALSHA`) instead of many network calls.
- Deterministic behavior under load: a single script execution per reservation path avoids partial updates and inconsistent intermediate state during traffic spikes.
- Centralized reservation logic: seat-allocation rules live in one script, reducing duplicated lock/coordination code in application handlers.

### What the scripts do

At a high level:

1. `redis_reserve_explicit.lua` checks all requested seat indexes and flips them from free (`0`) to held (`1`) atomically.
2. The same script writes reservation metadata (`reservation:<id>`) with TTL and indexes expiry in `reservations:ttl`.
3. The API then persists the reservation in MySQL using `SELECT ... FOR UPDATE`.
4. If DB write fails, `redis_release_explicit.lua` compensates by clearing held bits and metadata.
5. A background expiry worker processes `reservations:ttl`, releases Redis holds, and marks DB reservations as `expired` while freeing DB seats.

`redis_reserve.lua` remains available for contiguous block allocation use cases:

1. Reads an event-row bitmap representing seat occupancy.
2. Finds contiguous free blocks that satisfy the requested seat count.
3. Selects a candidate block (randomized for basic fairness).
4. Flips the target bits from free (`0`) to occupied (`1`) atomically.
5. Writes reservation metadata (`reservation:<id>`) with expiry.
6. Adds reservation expiry to `reservations:ttl` for cleanup workflows.

Because all of that happens in one Redis execution context, either the whole reservation update is applied or none of it is.

### Why not only database transactions?

MySQL transactions are authoritative and are still used in current explicit-seat reservation flow. Lua in Redis is complementary for scenarios that need very fast in-memory seat allocation (for example contiguous-block allocation by row):

- Redis bitmaps are memory-efficient for seat occupancy checks.
- In-memory script execution is typically faster than repeated DB row locking at very high QPS.
- Redis can manage short-lived reservation TTL state naturally.

### Trade-offs and production notes

- Redis is fast, but persistent booking truth should remain in MySQL (source of record).
- Script complexity must be versioned/tested carefully because allocation bugs affect many users quickly.
- Long-running Lua scripts block Redis while executing, so scripts should stay bounded and efficient.
- If script logic changes, deploy strategy should account for script SHA refresh and backward compatibility.

In this codebase, the active explicit-seat reservation flow now uses Redis Lua as a fast atomic gate before MySQL commit, with compensation and expiry reconciliation to keep state aligned.

## Running the Service

### Local (without Docker)

From inside `services/booking`:

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env with real values if needed
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Docker Compose

From repository root:

```bash
docker compose up --build booking
```

The booking service is exposed at `http://localhost:8001` in the default compose setup.

## Authentication and Identity

The booking service itself does not decode JWTs. For reservation ownership it expects identity forwarded in headers:

- `X-User-Email` (required by `POST /bookings/reserve`)

In normal operation, the API Gateway validates bearer tokens and injects `X-User-Email` before forwarding requests.

## API Endpoints

### `GET /venues`
Return all configured venues.

**Response example**:
```json
{
  "venues": [
    {"name": "Central Park Arena"},
    {"name": "Grand Theater"}
  ]
}
```

### `GET /venues/{venue_name}`
Return a single venue configuration.

**Response example**:
```json
{
  "name": "Central Park Arena",
  "rows": ["A", "B", "C"],
  "columns": [1, 2, 3],
  "seat_price": {"A": 1000.0, "B": 1000.0, "C": 800.0}
}
```

**Errors**:
- `404 Not Found` if venue does not exist.

### `GET /events`
Return all events with minimal metadata, including available seat count and distinct prices of available seats.

**Response example**:
```json
{
  "events": [
    {
      "event_id": "e8d8...",
      "name": "Summer Music Festival",
      "venue": "Central Park Arena",
      "date": "2026-07-15",
      "num_seats_available": 142,
      "list_of_prices": [50.0, 75.0, 100.0]
    }
  ]
}
```

### `GET /events/{event_id}`
Return full event details and seat maps.

**Response example**:
```json
{
  "event_id": "e8d8...",
  "name": "Summer Music Festival",
  "start_time": "2026-07-15T19:00:00",
  "venue": "Central Park Arena",
  "closed": 0,
  "seat_arrangements": [["A1", "A2"], ["B1", "B2"]],
  "seat_availability_map": {"A1": 0, "A2": 1},
  "seat_price_map": {"A1": 1000.0, "A2": 1000.0}
}
```

**Errors**:
- `404 Not Found` if event does not exist.
- `500 Internal Server Error` if venue config for event is missing/invalid.

### `POST /events`
Create an event and seed its seats from `venue_config.yaml`.

**Request body**:
```json
{
  "name": "Summer Music Festival",
  "venue": "Central Park Arena",
  "start_time": "2026-07-15T19:00:00"
}
```

**Response** (`201 Created`):
```json
{
  "event_id": "generated-uuid"
}
```

**Errors**:
- `400 Bad Request` for unknown venue.
- `500 Internal Server Error` on DB insert/transaction failure.

### `GET /events/{event_id}/close`
Close an event only after its `start_time` has passed. This endpoint:

1. Locks event row and validates close conditions.
2. Deletes related seats/bookings/reservations rows.
3. Marks `events.closed = 1`.
4. Deletes Redis bitmap and reservation keys (best effort).

**Response example**:
```json
{
  "event_id": "e8d8...",
  "status": "closed"
}
```

Possible responses:
- `{"status": "already_closed"}` when the event is already closed.
- `409 Conflict` when called before or at `start_time`.
- `404 Not Found` if event is missing.

### `POST /bookings/reserve`
Reserve explicit seats for an event.

**Headers**:
- `X-User-Email: user@example.com` (required)
- `Idempotency-Key: <unique-key>` (optional)

**Request body**:
```json
{
  "event_id": "e8d8...",
  "selected_seats": ["A1", "A2"]
}
```

Behavior:
1. Validates request shape and seat IDs (e.g. `A12`).
2. Normalizes seat IDs and rejects duplicates.
3. Maps seats to deterministic bitmap indexes from venue config.
4. Runs `redis_reserve_explicit.lua` to atomically hold all requested seats.
5. Persists `seats` and `reservations` in MySQL transaction (`FOR UPDATE`).
6. If DB write fails, runs `redis_release_explicit.lua` to roll back Redis hold.
7. Pushes reservation notification to Redis queue.
8. Optionally caches response under idempotency key.

**Response** (`201 Created`):
```json
{
  "reservation_id": "generated-uuid",
  "event_id": "e8d8...",
  "seats": ["A1", "A2"],
  "expires_at": "2026-03-14T12:34:56+00:00",
  "status": "reserved"
}
```

**Errors**:
- `400 Bad Request` for invalid/missing seats or missing `X-User-Email`.
- `404 Not Found` if event does not exist.
- `409 Conflict` if event is closed or seat already reserved.
- `500 Internal Server Error` for transaction failures.

### `POST /payments/capture`
Proxy payment intent/capture request to the configured payment provider.

**Headers**:
- `Idempotency-Key: <unique-key>` (optional)

**Request body**:
- Passed through as-is to `${PAYMENT_PROVIDER_URL}/payments/intents`.

**Response**:
- Returns the payment provider JSON response.

**Errors**:
- Mirrors upstream status codes for payment provider failures.

### `POST /payments/webhook`
Handle payment provider webhook callbacks.

Supported event values in payload:
- `capture_succeeded`: creates booking, marks reservation confirmed, emits `payment_confirmed` notification.
- `capture_failed`: emits `payment_failed` notification.

For all webhook events, a job envelope is pushed to `queue:jobs`.

**Example payload**:
```json
{
  "event": "capture_succeeded",
  "intent_id": "reservation-id-or-provider-intent-id"
}
```

**Response**:
```json
{"ok": true}
```

## Example Curl

Reserve seats directly against booking service (no gateway):

```bash
curl -X POST http://localhost:8001/bookings/reserve \
  -H "Content-Type: application/json" \
  -H "X-User-Email: user@example.com" \
  -H "Idempotency-Key: reserve-123" \
  -d '{
    "event_id": "<event-id>",
    "selected_seats": ["A1", "A2"]
  }'
```

## Operational Notes

- This service treats MySQL as the source of truth for seat occupancy.
- Redis Lua is used as a high-speed reservation hold gate before DB persistence.
- Expired holds are released by a background worker across Redis and MySQL.
- Closing an event is destructive for related seat/reservation/booking rows.
- Webhook signature validation is currently naive; use HMAC verification in production.
- CORS, auth hardening, and stricter webhook trust controls should be tightened for production environments.
