import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx
import mysql.connector
import redis.asyncio as redis
import yaml
from db_utils import execute_query, fetch_all, fetch_one
from fastapi import FastAPI, Header, HTTPException, Request
from mysql.connector import pooling
from pydantic import BaseModel
from schema import ReserveRequest


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
reserve_sha = None
db_pool = None
venues_config = {}


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
    script_path = os.path.join(os.path.dirname(__file__), "redis_reserve.lua")
    with open(script_path, "r") as f:
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
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "venue_config.yaml")
        with open(cfg_path, "r") as vf:
            cfg = yaml.safe_load(vf)
            if cfg and "venues" in cfg and isinstance(cfg["venues"], dict):
                # new structure: venues is a mapping of display name -> properties
                for name, v in cfg["venues"].items():
                    # ensure we have a mutable copy
                    venue_entry = dict(v) if isinstance(v, dict) else {}
                    venue_entry.setdefault("name", name)
                    venues_config[name] = venue_entry
        print("Loaded venue_config.yaml")
    except Exception as e:
        print(f"Warning: could not load venue_config.yaml: {e}")


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
    }


@app.get("/events")
async def list_events():
    """Return a list of events stored in the database.

    The endpoint returns minimal metadata per event (id, name, venue, date) and
    normalizes timestamps to ISO 8601 dates.
    """
    events = []
    if db_pool:
        try:
            rows_db = fetch_all(
                db_pool, "SELECT event_id, name, start_time, venue FROM events"
            )

            for ev in rows_db:
                venue_name = ev.get("venue")
                start_time = ev.get("start_time")
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
                        "event_id": ev.get("event_id"),
                        "name": ev.get("name"),
                        "venue": venue_name,
                        "date": date_only,
                    }
                )
        except Exception as e:
            print(f"Warning: could not query events table for list: {e}")
            raise HTTPException(status_code=500, detail="could not fetch events")
    else:
        # No database connection; cannot list events
        print("Error: database unavailable, cannot fetch events list")
        raise HTTPException(status_code=503, detail="database unavailable")

    return {"events": events}


@app.get("/events/{event_id}")
async def get_event(event_id: str):
    """Return details for a single event, including venue seating layout.

    The venue layout is inferred from the loaded venue configuration.
    """
    # Try to fetch event from DB if available
    event = None
    if db_pool:
        try:
            event = fetch_one(
                db_pool, "SELECT * FROM events WHERE event_id = %s", (event_id,)
            )
        except Exception as e:
            print(f"Warning: could not query events table: {e}")
    else:
        raise HTTPException(status_code=503, detail="database unavailable")

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Determine venue configuration (match by name or id)
    venue_name = event.get("venue")
    venue_cfg = None
    if venue_name and venues_config:
        venue_cfg = venues_config.get(venue_name)

    # Build rows data from venue config or fallback
    rows = []
    if venue_cfg:
        rows_list = venue_cfg.get("rows", [])
        cols = venue_cfg.get("columns")
        if not cols:
            raise HTTPException(
                status_code=500, detail="Venue configuration missing columns"
            )
        seats_count = len(cols)
        for r in rows_list:
            rows.append(
                {
                    "row_id": r,
                    "seats_count": seats_count,
                    "available_intervals": [{"start": 1, "length": seats_count}],
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    else:
        raise HTTPException(
            status_code=500, detail="Venue configuration not found for event"
        )

    # normalize start_time to isoformat
    start_time = event.get("start_time")
    try:
        if isinstance(start_time, (datetime,)):
            start_iso = start_time.isoformat()
        else:
            start_iso = str(start_time)
    except Exception:
        start_iso = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    return {
        "event_id": event.get("event_id", event_id),
        "name": event.get("name", f"Event {event_id}"),
        "start_time": start_iso,
        "venue": event.get("venue", "Sample Stadium"),
        "rows": rows,
    }


@app.post("/bookings/reserve", status_code=201)
async def reserve(
    req: ReserveRequest,
    idempotency_key: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None),
):
    """Reserve seats for an event.

    This endpoint allocates a contiguous block of seats for the specified row
    and event using a Redis Lua script, then records a reservation in MySQL.

    - `idempotency_key` is optional and can be used to deduplicate requests.
    - `x_user_id` / `x_user_email` are used for tracking and notifications.
    """
    if req.num_seats < 1:
        raise HTTPException(status_code=400, detail="num_seats must be >= 1")

    # Use user_id from header or request body
    user_id = x_user_id or req.user_id or "anon"

    # Idempotency: if provided, attempt to reuse the previous response
    idemp_key = None
    if idempotency_key:
        idemp_key = f"idempotency:{idempotency_key}"
        try:
            existing = await redis_client.get(idemp_key)
            if existing:
                return json.loads(existing)
        except Exception:
            # best effort only; do not block reservation flow
            pass

    # pick a row
    row = None
    if req.preferred_rows and len(req.preferred_rows) > 0:
        row = req.preferred_rows[0]
    else:
        # random pick
        row = "A"

    reservation_id = str(uuid.uuid4())
    expires_at = int(time.time()) + RESERVATION_TTL_SECONDS

    # Determine seats per row for event/venue (must match venue config)
    seats_per_row = None
    if db_pool:
        try:
            evt = fetch_one(
                db_pool, "SELECT venue FROM events WHERE event_id = %s", (req.event_id,)
            )
            if not evt:
                raise HTTPException(status_code=404, detail="Event not found")

            venue_cfg = venues_config.get(evt.get("venue"))
            if venue_cfg:
                cols = venue_cfg.get("columns")
                if cols:
                    seats_per_row = len(cols)
                    if row not in venue_cfg.get("rows", []):
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid row for event venue",
                        )
        except HTTPException:
            raise
        except Exception as e:
            print(f"Warning: could not determine venue configuration for event: {e}")

    if seats_per_row is None:
        raise HTTPException(
            status_code=500, detail="Venue configuration not found for event"
        )

    key = f"seats:{req.event_id}:row:{row}:bitmap"
    try:
        res = await redis_client.evalsha(
            reserve_sha,
            1,
            key,
            req.num_seats,
            reservation_id,
            req.event_id,
            row,
            user_id,
            0,
            RESERVATION_TTL_SECONDS,
            expires_at,
            seats_per_row,
        )
    except redis.exceptions.ResponseError as e:
        if "NO_BLOCK" in str(e):
            raise HTTPException(status_code=409, detail="No contiguous block available")
        raise

    # res = [reservation_id, seats_json, expiry_epoch]
    seats = json.loads(res[1])
    expires_at_iso = datetime.fromtimestamp(int(res[2]), tz=timezone.utc).isoformat()

    # Store reservation in MySQL
    if db_pool:
        try:
            execute_query(
                db_pool,
                """INSERT INTO reservations (reservation_id, event_id, user_id, status, seats, expires_at) 
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    reservation_id,
                    req.event_id,
                    user_id,
                    "reserved",
                    json.dumps(seats),
                    datetime.fromtimestamp(int(res[2]), tz=timezone.utc),
                ),
            )
        except Exception as e:
            print(f"Error storing reservation in MySQL: {e}")

    # Publish notification
    notification = {
        "type": "reservation_confirmed",
        "data": {
            "user_email": x_user_email or "user@example.com",
            "reservation_id": reservation_id,
            "event_id": req.event_id,
            "event_name": f"Event {req.event_id}",
            "seats": seats,
            "expires_at": expires_at_iso,
        },
    }
    await redis_client.lpush(NOTIFICATION_QUEUE, json.dumps(notification))

    response = {
        "reservation_id": res[0],
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
            # Best-effort cache; do not break the reservation flow
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

        # Store booking in MySQL
        if db_pool:
            try:
                # Get reservation details
                reservation = fetch_one(
                    db_pool,
                    "SELECT * FROM reservations WHERE reservation_id = %s",
                    (reservation_id,),
                )

                if reservation:
                    # Create booking
                    execute_query(
                        db_pool,
                        """INSERT INTO bookings (booking_id, reservation_id, event_id, user_id, status, seats, payment_status, total_amount) 
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            booking_id,
                            reservation_id,
                            reservation["event_id"],
                            reservation["user_id"],
                            "confirmed",
                            reservation["seats"],
                            "completed",
                            100.00,
                        ),
                    )

                    # Update reservation status
                    execute_query(
                        db_pool,
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
                            "user_email": "user@example.com",  # Would get from user lookup
                            "booking_id": booking_id,
                            "reservation_id": reservation_id,
                            "event_id": reservation["event_id"],
                            "event_name": f"Event {reservation['event_id']}",
                            "seats": seats,
                            "total_amount": 100.00,
                        },
                    }
                    await redis_client.lpush(
                        NOTIFICATION_QUEUE, json.dumps(notification)
                    )

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
