import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import mysql.connector
import redis.asyncio as redis
import yaml
from db_utils import execute_query, fetch_all, fetch_one, require_db_pool
from fastapi import FastAPI, Header, HTTPException, Request
from mysql.connector import pooling
from schema import CreateEventRequest, ReserveRequest


def _load_json_map(value):
    """Helper to load a JSON map from a DB field, with error handling."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


def _parse_seat_id(seat_id: str) -> tuple[str, int]:
    """
    Parse a seat ID into its row and column components.
    Example: "A12" -> ("A", 12)
    """
    i = 0
    while i < len(seat_id) and seat_id[i].isalpha():
        i += 1
    row = seat_id[:i].upper()
    col_raw = seat_id[i:]
    if not row or not col_raw.isdigit():
        raise ValueError(f"invalid seat id: {seat_id}")
    return row, int(col_raw)


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


REDIS_URL = required_env("REDIS_URL")
RESERVATION_TTL_SECONDS = required_env("RESERVATION_TTL_SECONDS", int)

# MySQL Configuration
MYSQL_HOST = required_env("MYSQL_HOST")
MYSQL_PORT = required_env("MYSQL_PORT", int)
MYSQL_USER = required_env("MYSQL_USER")
MYSQL_PASSWORD = required_env("MYSQL_PASSWORD")
MYSQL_DATABASE = required_env("MYSQL_DATABASE")

# Queue names
NOTIFICATION_QUEUE = "queue:notifications"

app = FastAPI(title="Booking Service")
redis_client: Optional[redis.Redis] = None

# SHA1 hash of the loaded Redis Lua reservation script.
# Stored during startup via `script_load()` and used by `EVALSHA` for faster execution
# without re-sending the full script on each request.
reserve_sha = None

db_pool = None
venues_config = {}


def load_venue_config(cfg_path: Optional[str] = None) -> None:
    """Load venue configuration YAML into the global `venues_config`.

    Args:
        cfg_path: Optional path to the YAML file. Defaults to `venue_config.yaml` next to this module.
    """
    global venues_config
    if cfg_path is None:
        cfg_path = os.path.join(os.path.dirname(__file__), "venue_config.yaml")

    # Reset to avoid stale data when reloading
    venues_config = {}

    try:
        with open(cfg_path, "r") as vf:
            cfg = yaml.safe_load(vf)
            if cfg and "venues" in cfg and isinstance(cfg["venues"], dict):
                # new structure: venues is a mapping of display name -> properties
                for name, v in cfg["venues"].items():
                    # ensure we have a mutable copy
                    venue_entry = dict(v) if isinstance(v, dict) else {}
                    venue_entry.setdefault("name", name)

                    # Ensure seat price is present and normalized
                    seat_price = venue_entry.get("seat_price", {})
                    if isinstance(seat_price, dict):
                        normalized = {}
                        for row_key, price in seat_price.items():
                            try:
                                normalized[row_key] = float(price)
                            except Exception:
                                normalized[row_key] = price
                        venue_entry["seat_price"] = normalized

                    venues_config[name] = venue_entry
        print("Loaded venue_config.yaml")
    except Exception as e:
        print(f"Warning: could not load venue_config.yaml: {e}")


def build_default_seat_maps(venue_cfg: dict) -> tuple[dict, dict]:
    """Build default availability + price maps for a venue.

    Availability is initialized to 0 for all seats and pricing comes from the
    venue configuration's per-row pricing.

    Args:
        venue_cfg: The venue configuration dict (from `venues_config`).

    Returns:
        A tuple `(availability_map, price_map)`.

    Raises:
        HTTPException: if the venue configuration is missing required fields.
    """

    rows_list = venue_cfg.get("rows") or []
    cols = venue_cfg.get("columns") or []
    if not cols or not rows_list:
        raise HTTPException(
            status_code=500, detail="Venue configuration missing columns or rows"
        )

    seat_price_by_row = venue_cfg.get("seat_price", {}) or {}

    seat_availability_map = {}
    seat_price_map = {}

    for r in rows_list:
        row_price = seat_price_by_row.get(r, 0)
        for c in cols:
            key = f"{r}{c}"
            seat_availability_map[key] = 0
            seat_price_map[key] = float(row_price) if row_price is not None else 0

    return seat_availability_map, seat_price_map


@app.on_event("startup")
async def startup_event():
    """Initialize global resources used by the booking service.

    This performs the following steps:
      - Establishes a Redis client and loads the Lua reservation script.
      - Connects to MySQL using a pooled connection.
      - Loads venue configuration from `venue_config.yaml`.

    The globals `redis_client`, `reserve_sha`, `db_pool`, and `venues_config` are populated.
    """
    global redis_client, reserve_sha, db_pool

    # Initialize Redis
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    # Load lua script
    lua_script_path = os.path.join(os.path.dirname(__file__), "redis_reserve.lua")
    with open(lua_script_path, "r") as f:
        script = f.read()
    reserve_sha = await redis_client.script_load(script)
    print("Loaded reserve Lua script, sha=", reserve_sha)

    # Initialize MySQL
    import time as sync_time

    max_retries = 30
    for i in range(max_retries):
        try:
            db_pool = pooling.MySQLConnectionPool(
                pool_name="booking_pool",
                pool_size=5,
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
            )
            print("Connected to database")
            break
        except Exception as e:
            if i < max_retries - 1:
                print(f"Waiting for database... ({i + 1}/{max_retries})")
                sync_time.sleep(2)
            else:
                print(f"Warning: Could not connect to database: {e}")

    # Load venue configuration (after package imports and app root available)
    load_venue_config()


@app.get("/venues")
async def list_venues():
    """Return all configured venues (id and name)."""
    venues = []
    for name in venues_config.keys():
        venues.append({"name": name})
    return {"venues": venues}


@app.get("/venues/{venue_name}")
async def get_venue(venue_name: str):
    """Return details for a single venue by name or id."""
    venue = venues_config.get(venue_name)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    # return copy to avoid accidental mutation
    return {
        "name": venue.get("name"),
        "rows": venue.get("rows"),
        "columns": venue.get("columns"),
        "seat_price": venue.get("seat_price"),
    }


@app.get("/events")
async def list_events():
    """Return a list of events stored in the database.

    The endpoint returns minimal metadata per event (id, name, venue, date) and
    normalizes timestamps to ISO 8601 dates.
    """
    events = []

    # Ensure DB is available
    database_pool = require_db_pool(db_pool)

    try:
        rows_db = fetch_all(
            database_pool, "SELECT event_id, name, start_time, venue FROM events"
        )

        for event in rows_db:
            venue_name = event.get("venue")
            start_time = event.get("start_time")
            try:
                if isinstance(start_time, (datetime,)):
                    start_iso = start_time.isoformat()
                else:
                    start_iso = str(start_time)
            except Exception:
                raise HTTPException(
                    status_code=500, detail="invalid start_time format in database"
                )

            # Only include minimal fields for the list endpoint
            date_only = start_iso.split("T")[0] if "T" in start_iso else start_iso
            events.append(
                {
                    "event_id": event.get("event_id"),
                    "name": event.get("name"),
                    "venue": venue_name,
                    "date": date_only,
                }
            )
    except Exception as e:
        print(f"Warning: could not query events table for list: {e}")
        raise HTTPException(status_code=500, detail="could not fetch events")

    return {"events": events}


@app.get("/events/{event_id}")
async def get_event(event_id: str):
    """Return details for a single event, including venue seating layout.

    The venue layout is inferred from the loaded venue configuration.
    """
    # Ensure DB is available and fetch event
    database_pool = require_db_pool(db_pool)

    event = None
    try:
        event = fetch_one(
            database_pool, "SELECT * FROM events WHERE event_id = %s", (event_id,)
        )
    except Exception as e:
        print(f"Warning: could not query events table: {e}")

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Determine venue configuration (match by name or id)
    venue_name = event.get("venue")
    venue_cfg = None
    if venue_name and venues_config:
        venue_cfg = venues_config.get(venue_name)

    # Build seat_arrangements data from venue config or fallback
    seat_arrangements = []
    if venue_cfg:
        rows_list = venue_cfg.get("rows")
        cols = venue_cfg.get("columns")
        if not cols or not rows_list:
            raise HTTPException(
                status_code=500, detail="Venue configuration missing columns or rows"
            )
        for r in rows_list:
            seat_arrangements.append(
                {
                    "row_id": r,
                    "columns": cols,
                }
            )
    else:
        raise HTTPException(
            status_code=500, detail="Venue configuration not found for event"
        )

    # Build seat-level availability and pricing maps (keyed by seat ID like "A1").
    seat_availability_map = _load_json_map(event.get("seat_availability_map"))
    seat_price_map = _load_json_map(event.get("seat_price_map"))

    # normalize start_time to isoformat
    start_time = event.get("start_time")
    try:
        if isinstance(start_time, (datetime,)):
            start_iso = start_time.isoformat()
        else:
            start_iso = str(start_time)
    except Exception:
        raise HTTPException(
            status_code=500, detail="invalid start_time format in database"
        )

    return {
        "event_id": event.get("event_id", event_id),
        "name": event.get("name", f"Event {event_id}"),
        "start_time": start_iso,
        "venue": event.get("venue", "Sample Stadium"),
        "seat_arrangements": seat_arrangements,
        "seat_availability_map": seat_availability_map,
        "seat_price_map": seat_price_map,
    }


@app.post("/events", status_code=201)
async def create_event(req: CreateEventRequest):
    """Create a new event record.

    This endpoint stores event metadata in MySQL, including optional per-seat
    availability/pricing maps. The maps must be provided by the caller and are
    stored as JSON in the database.
    """
    # Generate event_id if not provided
    event_id = str(uuid.uuid4())

    # Ensure venue exists in config (required for later lookups)
    if req.venue and venues_config.get(req.venue) is None:
        raise HTTPException(status_code=400, detail="Unknown venue")

    # Persist to DB
    database_pool = require_db_pool(db_pool)

    # Build default seat maps from venue config
    # - availability: all seats closed (0)
    # - pricing: derived from per-row pricing in config
    venue_cfg = venues_config.get(req.venue)
    seat_availability_map, seat_price_map = (
        build_default_seat_maps(venue_cfg) if venue_cfg else ({}, {})
    )

    try:
        execute_query(
            database_pool,
            """INSERT INTO events (event_id, name, venue, start_time, seat_availability_map, seat_price_map)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                event_id,
                req.name,
                req.venue,
                req.start_time,
                json.dumps(seat_availability_map),
                json.dumps(seat_price_map),
            ),
        )
    except Exception as e:
        # Unique key violation or other insert errors
        print(f"Error inserting event: {e}")
        raise HTTPException(status_code=500, detail="could not create event")

    return {"event_id": event_id}


@app.post("/bookings/reserve", status_code=201)
async def reserve(
    req: ReserveRequest,
    idempotency_key: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None),
):
    """Reserve explicit seats for an event.

    This endpoint reserves seats passed via `selected_seats`
    (for example: ["A1", "B2"]).

    It updates the event seat availability map and stores the reservation in MySQL.

    - `idempotency_key`: Optional key used to deduplicate retries.
    - `x_user_email`: Caller identity used for reservation ownership and notifications.
      Auth is enforced in the API Gateway; this service trusts forwarded identity headers.
    """
    # Validate request payload shape before any external I/O.
    selected_seats = req.selected_seats or []
    if not selected_seats:
        raise HTTPException(status_code=400, detail="selected_seats must not be empty")

    # User email is the only accepted identity for this endpoint.
    user_email = x_user_email
    if not user_email:
        raise HTTPException(status_code=400, detail="x_user_email is required")

    # Fast idempotency path: return a cached response for repeated requests.
    idemp_key = None
    if idempotency_key:
        idemp_key = f"idempotency:{idempotency_key}"
        try:
            existing = await redis_client.get(idemp_key)
            if existing:
                return json.loads(existing)
        except Exception:
            # Best-effort cache lookup; never block reservation flow.
            pass

    reservation_id = str(uuid.uuid4())
    expires_at = int(time.time()) + RESERVATION_TTL_SECONDS

    # Load the event's current seat availability map from DB.
    database_pool = require_db_pool(db_pool)

    seat_availability_map = {}

    try:
        event = fetch_one(
            database_pool,
            "SELECT seat_availability_map FROM events WHERE event_id = %s",
            (req.event_id,),
        )
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Warning: could not query event for reservation: {e}")

    # This map is used for both conflict checks and persistence.
    seat_availability_map = _load_json_map(event.get("seat_availability_map"))
    if not seat_availability_map:
        raise HTTPException(
            status_code=500, detail="Seat availability map not found for event"
        )

    # Validate seat states can be parsed as integers; keep flow resilient.
    for seat_id, state in seat_availability_map.items():
        try:
            state = int(state)
        except Exception as e:
            print(f"Warning: invalid seat state for {seat_id}: {state}, error: {e}")
            state = 0

    seats = []
    reserved_seat_ids = []
    event_bitmap_key = f"seats:{req.event_id}:bitmap"

    # Build deterministic seat indexes for Redis bitmap sync.
    seat_order = sorted(
        seat_availability_map.keys(), key=lambda sid: _parse_seat_id(sid)
    )
    seat_index_map = {seat_id: idx for idx, seat_id in enumerate(seat_order)}

    # Parse and validate every requested seat before mutating state.
    normalized_seats = []
    for seat_id in selected_seats:
        if not isinstance(seat_id, str) or not seat_id:
            raise HTTPException(status_code=400, detail="Invalid seat id")

        try:
            row, col = _parse_seat_id(seat_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid seat id: {seat_id}")

        normalized = f"{row}{col}"
        if normalized not in seat_availability_map:
            raise HTTPException(
                status_code=400, detail=f"Invalid seat for venue: {seat_id}"
            )
        if seat_availability_map.get(normalized) is None:
            raise HTTPException(
                status_code=500,
                detail=f"Seat availability map missing seat: {normalized}",
            )
        elif seat_availability_map.get(normalized) == 1:
            raise HTTPException(
                status_code=409, detail=f"Seat already reserved: {normalized}"
            )
        normalized_seats.append((normalized, row, col))

    # Prevent duplicate seats within a single request.
    normalized_ids = [seat[0] for seat in normalized_seats]
    if len(normalized_ids) != len(set(normalized_ids)):
        raise HTTPException(status_code=400, detail="Duplicate seats in selected_seats")

    # Apply reservation to DB map; sync Redis bitmap as best effort.
    for normalized, row, col in normalized_seats:
        seat_availability_map[normalized] = 1
        reserved_seat_ids.append(normalized)
        seats.append(normalized)
        try:
            # Keep allocator bitmap aligned with DB state.
            seat_idx = seat_index_map.get(normalized)
            if seat_idx is not None:
                await redis_client.setbit(event_bitmap_key, seat_idx, 1)
        except Exception:
            # DB remains the source of truth if Redis update fails.
            pass

    # Persist updated seat availability for the event.
    for seat_id in reserved_seat_ids:
        seat_availability_map[seat_id] = 1
    try:
        execute_query(
            database_pool,
            "UPDATE events SET seat_availability_map = %s WHERE event_id = %s",
            (json.dumps(seat_availability_map), req.event_id),
        )
    except Exception as e:
        print(f"Warning: could not update seat_availability_map: {e}")

    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    # Store reservation details in MySQL for downstream payment/booking flow.
    try:
        execute_query(
            database_pool,
            """INSERT INTO reservations (reservation_id, event_id, user_email, status, seats, expires_at) 
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                reservation_id,
                req.event_id,
                user_email,
                "reserved",
                json.dumps(seats),
                datetime.fromtimestamp(expires_at, tz=timezone.utc),
            ),
        )
    except Exception as e:
        print(f"Error storing reservation in MySQL: {e}")

    # Enqueue confirmation notification.
    notification = {
        "type": "reservation_confirmed",
        "data": {
            "user_email": user_email,
            "reservation_id": reservation_id,
            "event_id": req.event_id,
            "event_name": f"Event {req.event_id}",
            "seats": seats,
            "expires_at": expires_at_iso,
        },
    }
    await redis_client.lpush(NOTIFICATION_QUEUE, json.dumps(notification))

    response = {
        "reservation_id": reservation_id,
        "event_id": req.event_id,
        "seats": seats,
        "expires_at": expires_at_iso,
        "status": "reserved",
    }

    if idemp_key:
        try:
            await redis_client.set(
                idemp_key, json.dumps(response), ex=RESERVATION_TTL_SECONDS
            )
        except Exception:
            # Best-effort idempotency cache write.
            pass

    return response


@app.post("/payments/capture")
async def payments_capture(body: dict, idempotency_key: Optional[str] = Header(None)):
    """Capture a payment by forwarding the request to the configured payment provider.

    This is a minimal implementation used for local development and testing.
    """
    # Minimal implementation: forward to mock provider
    payment_provider = required_env("PAYMENT_PROVIDER_URL")
    async with httpx.AsyncClient() as client:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        r = await client.post(
            f"{payment_provider}/payments/intents",
            json=body,
            headers=headers,
            timeout=10,
        )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


@app.post("/payments/webhook")
async def payments_webhook(request: Request):
    """Handle payment provider webhooks.

    Expected payloads include `capture_succeeded` and `capture_failed` events.
    Successful captures create a booking and update reservation status.
    """
    payload = await request.json()
    # naive signature validation (in real system, verify HMAC header)
    event = payload.get("event")
    if not event:
        raise HTTPException(status_code=400, detail="invalid webhook")

    # Handle payment events
    if event == "capture_succeeded":
        # Payment successful - create booking
        booking_id = str(uuid.uuid4())
        reservation_id = payload.get("intent_id", "unknown")

        # Ensure DB is available
        database_pool = require_db_pool(db_pool)

        # Store booking in MySQL
        try:
            # Get reservation details
            reservation = fetch_one(
                database_pool,
                "SELECT * FROM reservations WHERE reservation_id = %s",
                (reservation_id,),
            )

            if reservation:
                # Create booking
                execute_query(
                    database_pool,
                    """INSERT INTO bookings (booking_id, reservation_id, event_id, user_email, status, seats, payment_status, total_amount) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        booking_id,
                        reservation_id,
                        reservation["event_id"],
                        reservation["user_email"],
                        "confirmed",
                        reservation["seats"],
                        "completed",
                        100.00,
                    ),
                )

                # Update reservation status
                execute_query(
                    database_pool,
                    "UPDATE reservations SET status = %s, confirmed_at = %s WHERE reservation_id = %s",
                    ("confirmed", datetime.now(timezone.utc), reservation_id),
                )

                # Get user email (simplified - would need to join with users table)
                seats = (
                    json.loads(reservation["seats"])
                    if isinstance(reservation["seats"], str)
                    else reservation["seats"]
                )

                # Publish success notification
                notification = {
                    "type": "payment_confirmed",
                    "data": {
                        "user_email": reservation.get("user_email", "user@example.com"),
                        "booking_id": booking_id,
                        "reservation_id": reservation_id,
                        "event_id": reservation["event_id"],
                        "event_name": f"Event {reservation['event_id']}",
                        "seats": seats,
                        "total_amount": 100.00,
                    },
                }
                await redis_client.lpush(NOTIFICATION_QUEUE, json.dumps(notification))

        except Exception as e:
            print(f"Error processing payment webhook: {e}")

    elif event == "capture_failed":
        # Payment failed - publish notification
        reservation_id = payload.get("intent_id", "unknown")
        notification = {
            "type": "payment_failed",
            "data": {
                "user_email": "user@example.com",
                "reservation_id": reservation_id,
                "event_id": "unknown",
                "event_name": "Event",
                "reason": "Payment processing failed",
            },
        }
        await redis_client.lpush(NOTIFICATION_QUEUE, json.dumps(notification))

    # Enqueue job for worker processing
    job = {
        "job_id": str(uuid.uuid4()),
        "type": "payment_webhook",
        "payload": payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await redis_client.lpush("queue:jobs", json.dumps(job))
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
