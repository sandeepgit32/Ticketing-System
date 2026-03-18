import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import redis.asyncio as redis
import yaml
from db_utils import execute_query, fetch_all, fetch_one, require_db_pool
from fastapi import FastAPI, Header, HTTPException, Request
from mysql.connector import pooling
from schema import CreateEventRequest, ReserveRequest


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
reserve_explicit_sha = None
release_explicit_sha = None

db_pool = None
venues_config = {}
expiry_worker_task: Optional[asyncio.Task] = None
expiry_worker_stop_event: Optional[asyncio.Event] = None


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


def _normalize_seat_ids(selected_seats: list) -> list[str]:
    """Parse, normalise, and deduplicate a list of raw seat ID strings.

    Each seat ID is validated to be a non-empty string, parsed into its row
    letter(s) and column number via ``_parse_seat_id``, then reassembled into
    a canonical upper-case form (e.g. ``"a1"`` → ``"A1"``).

    Args:
        selected_seats: Raw seat ID values from the request payload.

    Returns:
        List of normalised seat ID strings in the same order as the input,
        with no duplicates.

    Raises:
        HTTPException(400): If any element is not a non-empty string, if any
            seat ID cannot be parsed, or if the list contains duplicates after
            normalisation.
    """
    normalized: list[str] = []
    for seat_id in selected_seats:
        if not isinstance(seat_id, str) or not seat_id:
            raise HTTPException(status_code=400, detail="Invalid seat id")
        try:
            row, col = _parse_seat_id(seat_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid seat id: {seat_id}")
        normalized.append(f"{row}{col}")

    if len(normalized) != len(set(normalized)):
        raise HTTPException(status_code=400, detail="Duplicate seats in selected_seats")

    return normalized


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


def build_default_seat_rows(venue_cfg: dict) -> list[tuple[str, int, float]]:
    """Build default per-seat rows for DB insertion.

    Args:
        venue_cfg: The venue configuration dict (from `venues_config`).

    Returns:
        List of tuples: `(seat_id, occupied, price)`.

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

    seat_rows = []

    for r in rows_list:
        row_price = seat_price_by_row.get(r, 0)
        for c in cols:
            key = f"{r}{c}"
            price = float(row_price) if row_price is not None else 0
            seat_rows.append((key, 0, price))

    return seat_rows


def build_seat_index_map(venue_cfg: Optional[dict]) -> dict:
    """Build a deterministic mapping from seat ID to its zero-based bitmap index.

    The index order is derived from ``build_default_seat_rows``, which iterates
    rows then columns in the order they appear in the venue configuration.  The
    same order must be used everywhere a seat bitmap is written or read so that
    bit positions remain consistent across restarts and service instances.

    Args:
        venue_cfg: Venue configuration dict loaded from ``venues_config``.  If
            ``None`` or empty, an empty mapping is returned without error.

    Returns:
        Dict mapping seat ID strings (e.g. ``"A1"``) to their integer bitmap
        index.  Returns ``{}`` if the venue config is absent or invalid.

    Example:
        >>> venue_cfg = {"rows": ["A", "B"], "columns": [1, 2]}
        >>> build_seat_index_map(venue_cfg)
        {"A1": 0, "A2": 1, "B1": 2, "B2": 3}
    """
    if not venue_cfg:
        return {}
    try:
        seat_order = [seat_id for seat_id, _, _ in build_default_seat_rows(venue_cfg)]
    except HTTPException:
        return {}
    return {seat_id: idx for idx, seat_id in enumerate(seat_order)}


def _reservation_redis_keys(event_id: str, reservation_id: str) -> tuple[str, str, str]:
    """Return the three Redis key names used for a reservation.

    All reservation-related Redis operations share a fixed key schema so that
    the Lua scripts, the expiry worker, and the application layer all reference
    the same keys without hard-coding strings in multiple places.

    Keys:
        - ``seats:<event_id>:bitmap`` — Per-event bitfield where each bit
          represents one seat's occupied state (1 = held/booked, 0 = free).
        - ``reservation:<reservation_id>`` — Redis hash storing metadata for a
          single reservation (event_id, user_email, seat_indexes, expires_at).
        - ``reservations:ttl`` — Sorted set used as a TTL index; each member is
          a ``reservation_id`` and its score is the Unix expiry timestamp.

    Args:
        event_id: UUID of the event.
        reservation_id: UUID of the reservation.

    Returns:
        Tuple of ``(bitmap_key, reservation_key, ttl_key)``.
    """
    return (
        f"seats:{event_id}:bitmap",
        f"reservation:{reservation_id}",
        "reservations:ttl",
    )


async def _release_redis_hold(
    event_id: str, reservation_id: str, seat_indexes: list[int]
) -> None:
    """Best-effort release of Redis seat bits and reservation metadata.

    Invokes ``redis_release_explicit.lua`` via EVALSHA to atomically:

    - Clear each bit in the event seat bitmap corresponding to ``seat_indexes``.
    - Delete the reservation hash (``reservation:<reservation_id>``).
    - Remove the reservation from the TTL sorted set (``reservations:ttl``).

    All three operations are performed inside the Lua script so they cannot
    leave the bitmap and the reservation hash in an inconsistent state.

    Failures are intentionally swallowed: Redis is the speed layer and its
    state will eventually be reconciled by the expiry worker on restart or
    the next TTL scan.

    Args:
        event_id: UUID of the event whose bitmap needs updating.
        reservation_id: UUID of the reservation being released.
        seat_indexes: Zero-based bitmap indexes of the seats to free.  If the
            list is empty the function returns immediately without any I/O.
    """
    if not seat_indexes:
        return

    bitmap_key, reservation_key, ttl_key = _reservation_redis_keys(
        event_id, reservation_id
    )
    try:
        await redis_client.evalsha(
            release_explicit_sha,
            3,
            bitmap_key,
            reservation_key,
            ttl_key,
            reservation_id,
            json.dumps(seat_indexes),
        )
    except Exception:
        # Redis is auxiliary. Failures are tolerated and handled by worker retry.
        pass


async def _release_expired_reservation_in_db(reservation_id: str) -> None:
    """Expire a reservation in MySQL and free its seats if still in `reserved` state.

    Acquires a ``FOR UPDATE`` lock on the target reservation row to prevent
    concurrent expiry from double-updating the same row.  Only proceeds with
    seat-freeing and status update if the reservation is currently in
    ``reserved`` status — rows already ``confirmed`` or ``expired`` are skipped
    to avoid corrupting completed bookings.

    Steps performed inside a single transaction:

    1. Lock and fetch the reservation row.
    2. Early-return (commit with no writes) if the row is missing or not in
       ``reserved`` status.
    3. Set ``occupied = 0`` and ``reservation_id = NULL`` on every seat that
       was held by this reservation (matched by ``reservation_id`` to avoid
       freeing seats already re-claimed by a newer reservation).
    4. Update the reservation ``status`` to ``expired``.

    Errors are caught and logged; the transaction is rolled back on failure so
    the database is never left partially updated.

    Args:
        reservation_id: UUID of the reservation to expire.
    """
    database_pool = require_db_pool(db_pool)
    conn = database_pool.get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        cursor.execute(
            """SELECT reservation_id, event_id, seats, status
               FROM reservations
               WHERE reservation_id = %s
               FOR UPDATE""",
            (reservation_id,),
        )
        reservation_row = cursor.fetchone()
        if not reservation_row:
            conn.commit()
            return

        if (reservation_row.get("status") or "").lower() != "reserved":
            conn.commit()
            return

        raw_seats = reservation_row.get("seats")
        seat_ids = []
        if isinstance(raw_seats, str):
            seat_ids = json.loads(raw_seats)
        elif isinstance(raw_seats, list):
            seat_ids = raw_seats

        if seat_ids:
            placeholders = ", ".join(["%s"] * len(seat_ids))
            cursor.execute(
                f"""UPDATE seats
                    SET occupied = 0, reservation_id = NULL
                    WHERE event_id = %s
                      AND seat_id IN ({placeholders})
                      AND reservation_id = %s""",
                (
                    reservation_row.get("event_id"),
                    *seat_ids,
                    reservation_id,
                ),
            )

        cursor.execute(
            """UPDATE reservations
               SET status = %s
               WHERE reservation_id = %s
                 AND status = %s""",
            ("expired", reservation_id, "reserved"),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error expiring reservation in DB ({reservation_id}): {e}")
    finally:
        cursor.close()
        conn.close()


async def _process_expired_reservation(reservation_id: str) -> None:
    """Fully expire a single reservation from both Redis and MySQL.

    Orchestrates the two-phase expiry for one reservation ID surfaced by the
    TTL sorted set:

    1. **Redis phase**: Read the reservation hash
       (``reservation:<reservation_id>``) to retrieve ``event_id`` and
       ``seat_indexes``.  If the hash is still present, invoke
       ``_release_redis_hold`` to clear bitmap bits and remove the hash and TTL
       entry atomically.  If the hash is already gone (e.g. it expired
       naturally via Redis TTL), remove the stale entry from
       ``reservations:ttl`` directly.

    2. **DB phase**: Call ``_release_expired_reservation_in_db`` to free seat
       rows and mark the reservation as ``expired`` in MySQL, regardless of
       whether the Redis phase succeeded.

    Errors in the Redis phase are caught so that the DB phase always runs.

    Args:
        reservation_id: UUID of the reservation to expire.
    """
    reservation_key = f"reservation:{reservation_id}"
    try:
        payload = await redis_client.hgetall(reservation_key)
    except Exception:
        payload = {}

    event_id = payload.get("event_id")
    raw_indexes = payload.get("seat_indexes")
    seat_indexes = []
    if raw_indexes:
        try:
            parsed = json.loads(raw_indexes)
            if isinstance(parsed, list):
                seat_indexes = [int(i) for i in parsed]
        except Exception:
            seat_indexes = []

    if event_id and seat_indexes:
        await _release_redis_hold(event_id, reservation_id, seat_indexes)
    else:
        # If payload is already gone, ensure TTL index no longer references it.
        try:
            await redis_client.zrem("reservations:ttl", reservation_id)
        except Exception:
            pass

    await _release_expired_reservation_in_db(reservation_id)


async def _reservation_expiry_worker(stop_event: asyncio.Event) -> None:
    """Background task that continuously releases expired reservation holds.

    Polls the ``reservations:ttl`` sorted set once per second, fetching up to
    100 reservation IDs whose score (Unix expiry timestamp) is <= now.  Each
    expired reservation is processed by ``_process_expired_reservation``, which
    frees the Redis bitmap bits and marks the MySQL reservation as ``expired``.

    The worker runs until ``stop_event`` is set (triggered by
    ``shutdown_event``).  Any unhandled exception in the polling loop is caught
    and logged, then the worker sleeps for one second before retrying, so a
    transient Redis or DB error cannot permanently kill the background task.

    Args:
        stop_event: Asyncio event set by ``shutdown_event`` to signal the worker
            to exit its loop cleanly.
    """
    while not stop_event.is_set():
        try:
            now_epoch = int(time.time())
            expired = await redis_client.zrangebyscore(
                "reservations:ttl", "-inf", now_epoch, start=0, num=100
            )
            if not expired:
                await asyncio.sleep(1)
                continue

            for reservation_id in expired:
                await _process_expired_reservation(reservation_id)
        except Exception as e:
            print(f"Reservation expiry worker error: {e}")
            await asyncio.sleep(1)


@app.on_event("startup")
async def startup_event():
    """Initialize global resources used by the booking service.

    This performs the following steps:
      - Establishes a Redis client and loads the Lua reservation script.
      - Connects to MySQL using a pooled connection.
      - Loads venue configuration from `venue_config.yaml`.

    The globals `redis_client`, `reserve_sha`, `db_pool`, and `venues_config` are populated.
    """
    global \
        redis_client, \
        reserve_sha, \
        reserve_explicit_sha, \
        release_explicit_sha, \
        db_pool
    global expiry_worker_task, expiry_worker_stop_event

    # Initialize Redis
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    # Load lua script
    lua_script_path = os.path.join(os.path.dirname(__file__), "redis_reserve.lua")
    with open(lua_script_path, "r") as f:
        script = f.read()
    reserve_sha = await redis_client.script_load(script)
    print("Loaded reserve Lua script, sha=", reserve_sha)

    reserve_explicit_path = os.path.join(
        os.path.dirname(__file__), "redis_reserve_explicit.lua"
    )
    with open(reserve_explicit_path, "r") as f:
        reserve_explicit_script = f.read()
    reserve_explicit_sha = await redis_client.script_load(reserve_explicit_script)
    print("Loaded explicit reserve Lua script, sha=", reserve_explicit_sha)

    release_explicit_path = os.path.join(
        os.path.dirname(__file__), "redis_release_explicit.lua"
    )
    with open(release_explicit_path, "r") as f:
        release_explicit_script = f.read()
    release_explicit_sha = await redis_client.script_load(release_explicit_script)
    print("Loaded explicit release Lua script, sha=", release_explicit_sha)

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

    # Start expiry worker after all dependencies are ready.
    expiry_worker_stop_event = asyncio.Event()
    expiry_worker_task = asyncio.create_task(
        _reservation_expiry_worker(expiry_worker_stop_event)
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Stop background workers and close Redis connections."""
    global expiry_worker_task, expiry_worker_stop_event

    if expiry_worker_stop_event is not None:
        expiry_worker_stop_event.set()

    if expiry_worker_task is not None:
        await expiry_worker_task
        expiry_worker_task = None

    if redis_client is not None:
        await redis_client.aclose()


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
    # Ensure DB is available and fetch event + seats in a single query.
    database_pool = require_db_pool(db_pool)

    try:
        rows = fetch_all(
            database_pool,
            """SELECT e.event_id, e.name, e.venue, e.start_time, e.closed, s.seat_id, s.occupied, s.price
               FROM events e
               LEFT JOIN seats s ON s.event_id = e.event_id
               WHERE e.event_id = %s""",
            (event_id,),
        )
    except Exception as e:
        print(f"Warning: could not query event details: {e}")
        raise HTTPException(status_code=500, detail="could not fetch event")

    if not rows:
        raise HTTPException(status_code=404, detail="Event not found")

    event = rows[0]
    venue_name = event.get("venue")
    venue_cfg = venues_config.get(venue_name) if venue_name and venues_config else None

    seat_availability_map = {}
    seat_price_map = {}
    for row in rows:
        seat_id = row.get("seat_id")
        if not seat_id:
            continue

        try:
            occupied = int(row.get("occupied", 0))
        except Exception:
            occupied = 0

        price = row.get("price", 0)
        try:
            price = float(price) if price is not None else 0
        except Exception:
            price = 0

        seat_availability_map[seat_id] = 1 if occupied else 0
        seat_price_map[seat_id] = price

    seat_arrangements = []
    if venue_cfg:
        rows_list = venue_cfg.get("rows")
        cols = venue_cfg.get("columns")
        if not cols or not rows_list:
            raise HTTPException(
                status_code=500, detail="Venue configuration missing columns or rows"
            )
        for r in rows_list:
            seat_arrangements.append([f"{r}{c}" for c in cols])
    else:
        raise HTTPException(
            status_code=500, detail="Venue configuration not found for event"
        )

    start_time = event.get("start_time")
    try:
        if isinstance(start_time, datetime):
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
        "closed": int(event.get("closed") or 0),
        "seat_arrangements": seat_arrangements,
        "seat_availability_map": seat_availability_map,
        "seat_price_map": seat_price_map,
    }


@app.post("/events", status_code=201)
async def create_event(req: CreateEventRequest):
    """Create a new event record.

    This endpoint stores event metadata in MySQL and pre-populates the `seats`
    table for the event using the configured venue layout and pricing.
    """
    event_id = str(uuid.uuid4())

    if req.venue and venues_config.get(req.venue) is None:
        raise HTTPException(status_code=400, detail="Unknown venue")

    database_pool = require_db_pool(db_pool)
    venue_cfg = venues_config.get(req.venue)
    seat_rows = build_default_seat_rows(venue_cfg) if venue_cfg else []

    conn = database_pool.get_connection()
    cursor = conn.cursor()
    try:
        conn.start_transaction()
        cursor.execute(
            """INSERT INTO events (event_id, name, venue, start_time)
               VALUES (%s, %s, %s, %s)""",
            (event_id, req.name, req.venue, req.start_time),
        )

        if seat_rows:
            cursor.executemany(
                """INSERT INTO seats (event_id, seat_id, occupied, reservation_id, price)
                   VALUES (%s, %s, %s, %s, %s)""",
                [
                    (event_id, seat_id, occupied, None, price)
                    for seat_id, occupied, price in seat_rows
                ],
            )

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error inserting event: {e}")
        raise HTTPException(status_code=500, detail="could not create event")
    finally:
        cursor.close()
        conn.close()

    return {"event_id": event_id}


@app.get("/events/{event_id}/close")
async def close_event(event_id: str):
    """Close an event after it has started and clean up runtime state."""
    database_pool = require_db_pool(db_pool)

    conn = database_pool.get_connection()
    cursor = conn.cursor(dictionary=True)
    reservation_ids = []
    try:
        conn.start_transaction()

        cursor.execute(
            "SELECT event_id, start_time, closed FROM events WHERE event_id = %s FOR UPDATE",
            (event_id,),
        )
        event = cursor.fetchone()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        if int(event.get("closed") or 0) == 1:
            conn.rollback()
            return {"event_id": event_id, "status": "already_closed"}

        start_time = event.get("start_time")
        if not isinstance(start_time, datetime):
            raise HTTPException(status_code=500, detail="invalid start_time format")
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        now_utc = datetime.now(timezone.utc)
        if now_utc <= start_time:
            raise HTTPException(
                status_code=409,
                detail="Event cannot be closed before or at start_time",
            )

        cursor.execute(
            "SELECT reservation_id FROM reservations WHERE event_id = %s",
            (event_id,),
        )
        reservation_ids = [
            row["reservation_id"]
            for row in cursor.fetchall()
            if row.get("reservation_id")
        ]

        cursor.execute("DELETE FROM seats WHERE event_id = %s", (event_id,))
        cursor.execute("DELETE FROM bookings WHERE event_id = %s", (event_id,))
        cursor.execute("DELETE FROM reservations WHERE event_id = %s", (event_id,))
        cursor.execute("UPDATE events SET closed = 1 WHERE event_id = %s", (event_id,))

        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print(f"Error closing event: {e}")
        raise HTTPException(status_code=500, detail="could not close event")
    finally:
        cursor.close()
        conn.close()

    try:
        await redis_client.delete(f"seats:{event_id}:bitmap")
    except Exception:
        pass

    for reservation_id in reservation_ids:
        try:
            await redis_client.delete(f"reservation:{reservation_id}")
            await redis_client.zrem("reservations:ttl", reservation_id)
        except Exception:
            pass

    return {"event_id": event_id, "status": "closed"}


async def _apply_redis_seat_hold(
    event_id: str,
    reservation_id: str,
    user_email: str,
    expires_at: int,
    seat_indexes: list[int],
) -> None:
    """Atomically mark seats as held in Redis using the explicit-seat Lua script.

    Derives the three Redis keys required by the Lua script from `event_id` and
    `reservation_id` (bitmap key, reservation hash key, TTL sorted-set key) and
    invokes ``redis_reserve_explicit.lua`` via EVALSHA.

    The Lua script checks each bit in the seat bitmap, sets the bits for all
    requested `seat_indexes`, stores reservation metadata in a Redis hash, and
    adds the reservation to the TTL sorted set — all within a single atomic
    operation.  If any seat is already taken the script returns a ``SEAT_TAKEN``
    error instead of partially applying the hold.

    Args:
        event_id: UUID of the target event; used to build Redis key names.
        reservation_id: UUID generated for this reservation; used as the Redis
            hash key suffix and stored inside the hash as the owner identifier.
        user_email: Email address of the reserving user; stored in the Redis
            reservation hash for downstream expiry and notification use.
        expires_at: Unix timestamp (seconds) at which the hold should expire.
            Passed to the Lua script to populate the TTL sorted set score.
        seat_indexes: Zero-based integer indexes into the venue seat bitmap
            corresponding to each requested seat.  The Lua script uses these to
            set and check individual bitmap bits.

    Raises:
        HTTPException(409): If one or more seats are already held (either the
            Lua script returns a non-OK status or raises ``SEAT_TAKEN``).
        HTTPException(503): If an unexpected Redis error occurs (e.g. connection
            failure, script not loaded).
    """
    bitmap_key, reservation_key, ttl_key = _reservation_redis_keys(
        event_id, reservation_id
    )
    try:
        hold_result = await redis_client.evalsha(
            reserve_explicit_sha,
            3,
            bitmap_key,
            reservation_key,
            ttl_key,
            reservation_id,
            event_id,
            user_email,
            str(expires_at),
            str(RESERVATION_TTL_SECONDS),
            json.dumps(seat_indexes),
        )
        if not hold_result or hold_result[0] != "OK":
            raise HTTPException(status_code=409, detail="Seats are no longer available")
    except HTTPException:
        raise
    except Exception as e:
        if "SEAT_TAKEN" in str(e):
            raise HTTPException(status_code=409, detail="Seats are no longer available")
        print(f"Error applying Redis hold: {e}")
        raise HTTPException(status_code=503, detail="reservation service unavailable")


async def _reserve_seats_in_db(
    database_pool,
    event_id: str,
    reservation_id: str,
    user_email: str,
    normalized_seats: list[str],
    expires_at: int,
) -> None:
    """Persist a seat reservation to MySQL within a single serialisable transaction.

    Acquires a ``FOR UPDATE`` row lock on the event record to guard against
    concurrent close operations, then acquires ``FOR UPDATE`` locks on every
    requested seat row to prevent double-booking at the database level.

    The transaction performs three writes:

    1. Sets ``occupied = 1`` and ``reservation_id`` on each seat row.
    2. Inserts a new row into the ``reservations`` table with status
       ``"reserved"`` and the computed ``expires_at`` timestamp.

    On any failure the transaction is rolled back before the exception is
    re-raised, so the database is never left in a partially-written state.
    The caller is responsible for releasing the corresponding Redis hold if
    this function raises.

    Args:
        database_pool: Active MySQL connection pool (``mysql.connector`` pool).
        event_id: UUID of the event being reserved.
        reservation_id: UUID generated for this reservation; written to both
            the ``seats`` and ``reservations`` tables.
        user_email: Email address of the reserving user; stored in the
            ``reservations`` row for ownership tracking and notifications.
        normalized_seats: List of normalised seat IDs (e.g. ``["A1", "B2"]``)
            whose rows will be locked and updated.
        expires_at: Unix timestamp (seconds) stored as the reservation's
            ``expires_at`` value; converted to a UTC datetime before insert.

    Raises:
        HTTPException(404): If the event row does not exist.
        HTTPException(409): If the event is closed or any seat is already
            occupied (``occupied = 1``) at the time of the DB lock.
        HTTPException(400): If any seat ID in `normalized_seats` has no
            corresponding row in the ``seats`` table for the event.
        HTTPException(500): For any other unexpected database error.
    """
    conn = database_pool.get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        # Lock the event row first to prevent concurrent close operations while we're
        # reserving seats.
        cursor.execute(
            "SELECT event_id, venue, closed FROM events WHERE event_id = %s FOR UPDATE",
            (event_id,),
        )
        event_row = cursor.fetchone()
        if not event_row:
            raise HTTPException(status_code=404, detail="Event not found")
        if int(event_row.get("closed") or 0) == 1:
            raise HTTPException(status_code=409, detail="Event is closed")

        seat_placeholders = ", ".join(["%s"] * len(normalized_seats))
        # The `SELECT ... FOR UPDATE` clause in MySQL is used within a transaction to select specific
        # rows and apply an exclusive lock on those selected rows, preventing other transactions
        # from modifying those rows until the current transaction is committed or rolled back.
        # This is crucial for maintaining data integrity when multiple transactions might be trying
        # to reserve the same seats concurrently.
        cursor.execute(
            f"""SELECT seat_id, occupied FROM seats
                WHERE event_id = %s AND seat_id IN ({seat_placeholders})
                FOR UPDATE""",
            (event_id, *normalized_seats),
        )
        seat_rows = cursor.fetchall()

        if len(seat_rows) != len(normalized_seats):
            existing = {row["seat_id"] for row in seat_rows}
            missing = [sid for sid in normalized_seats if sid not in existing]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid seat for venue: {missing[0]}",
            )

        seat_state = {row["seat_id"]: row for row in seat_rows}
        for seat_id in normalized_seats:
            occupied = int(seat_state[seat_id].get("occupied") or 0)
            if occupied == 1:
                raise HTTPException(
                    status_code=409, detail=f"Seat already reserved: {seat_id}"
                )
        # All seats are available; proceed to update them and insert the reservation.
        cursor.executemany(
            """UPDATE seats
               SET occupied = 1, reservation_id = %s
               WHERE event_id = %s AND seat_id = %s""",
            [(reservation_id, event_id, seat_id) for seat_id in normalized_seats],
        )
        # Insert the reservation row with status "reserved" and the computed expiry time.
        cursor.execute(
            """INSERT INTO reservations (reservation_id, event_id, user_email, status, seats, expires_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                reservation_id,
                event_id,
                user_email,
                "reserved",
                json.dumps(normalized_seats),
                datetime.fromtimestamp(expires_at, tz=timezone.utc),
            ),
        )

        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print(f"Error reserving seats: {e}")
        raise HTTPException(status_code=500, detail="could not reserve seats")
    finally:
        cursor.close()
        conn.close()


@app.post("/bookings/reserve", status_code=201)
async def reserve(
    req: ReserveRequest,
    idempotency_key: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None),
):
    """Reserve explicit seats for an event.

    This endpoint reserves seats passed via `selected_seats`
    (for example: ["A1", "B2"]).

    It updates seat rows in the `seats` table and stores the reservation in MySQL.

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

    # Validate and reserve seats in Redis first, then persist in DB.
    database_pool = require_db_pool(db_pool)

    # Parse, normalise, and deduplicate seat IDs before mutating any state.
    normalized_seats = _normalize_seat_ids(selected_seats)

    # Read event metadata before Redis hold for seat-map validation.
    event_row = fetch_one(
        database_pool,
        "SELECT event_id, venue, closed FROM events WHERE event_id = %s",
        (req.event_id,),
    )
    if not event_row:
        raise HTTPException(status_code=404, detail="Event not found")
    if int(event_row.get("closed") or 0) == 1:
        raise HTTPException(status_code=409, detail="Event is closed")

    venue_cfg = venues_config.get(event_row.get("venue"))
    if not venue_cfg:
        raise HTTPException(
            status_code=500,
            detail="Venue configuration not found or invalid for event",
        )
    seat_index_map = build_seat_index_map(venue_cfg)

    seat_indexes = [seat_index_map.get(seat_id) for seat_id in normalized_seats]
    for seat_id in normalized_seats:
        seat_idx = seat_index_map.get(seat_id)
        if seat_idx is None:
            raise HTTPException(
                status_code=400, detail=f"Invalid seat for venue: {seat_id}"
            )
        seat_indexes.append(seat_idx)

    await _apply_redis_seat_hold(
        req.event_id, reservation_id, user_email, expires_at, seat_indexes
    )
    try:
        await _reserve_seats_in_db(
            database_pool,
            req.event_id,
            reservation_id,
            user_email,
            normalized_seats,
            expires_at,
        )
    except Exception:
        await _release_redis_hold(req.event_id, reservation_id, seat_indexes)
        raise

    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    # Enqueue confirmation notification.
    notification = {
        "type": "reservation_confirmed",
        "data": {
            "user_email": user_email,
            "reservation_id": reservation_id,
            "event_id": req.event_id,
            "event_name": f"Event {req.event_id}",
            "seats": normalized_seats,
            "expires_at": expires_at_iso,
        },
    }
    await redis_client.lpush(NOTIFICATION_QUEUE, json.dumps(notification))

    response = {
        "reservation_id": reservation_id,
        "event_id": req.event_id,
        "seats": normalized_seats,
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

    This is a minimal implementation used for local development and testing.  The
    endpoint reads ``PAYMENT_PROVIDER_URL`` from the environment, proxies the
    request body to ``POST {PAYMENT_PROVIDER_URL}/payments/intents``, and returns
    the provider's JSON response verbatim.  Any HTTP error from the provider is
    re-raised as an ``HTTPException`` with the same status code.

    Args:
        body: Arbitrary JSON payload forwarded to the payment provider.  At
            minimum the provider expects an ``intent_id`` (a reservation UUID)
            and an ``amount`` field, for example::

                {
                    "intent_id": "a3f1c2d4-...",
                    "amount": 5000,
                    "currency": "usd"
                }

        idempotency_key: Optional ``Idempotency-Key`` header value forwarded
            unchanged to the payment provider so that retried requests are not
            double-charged.  When omitted, no idempotency header is sent.

    Returns:
        The JSON body returned by the payment provider on success, for example::

            {
                "intent_id": "a3f1c2d4-...",
                "status": "pending",
                "amount": 5000,
                "currency": "usd"
            }

    Raises:
        HTTPException: Propagates the provider's HTTP status code (>= 400) and
            response body verbatim when the upstream call fails.  Common codes:

            * ``402`` - insufficient funds / card declined.
            * ``409`` - duplicate intent (idempotency collision).
            * ``503`` - payment provider temporarily unavailable.
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

    Expected payloads include ``capture_succeeded`` and ``capture_failed``
    events delivered by the configured payment provider.  The endpoint processes
    each event synchronously before enqueuing a generic job to ``queue:jobs``
    for any downstream worker that needs the raw payload.

    Event handling summary:

    * **capture_succeeded** - Looks up the reservation identified by
      ``intent_id``, inserts a confirmed ``bookings`` row, updates the
      ``reservations`` row to ``confirmed``, and pushes a
      ``payment_confirmed`` notification onto the Redis notification queue.
      If the reservation cannot be found the booking step is skipped silently
      (logged to stdout).

    * **capture_failed** - Pushes a ``payment_failed`` notification onto the
      Redis notification queue.  No database writes are performed.

    * **Any other event type** - Passes through to the job queue without
      specific handling.

    .. note::
        Webhook signature verification is not yet implemented.  Production
        deployments should validate an HMAC header before trusting the payload.

    Args:
        request: The raw FastAPI ``Request`` object.  The JSON body is read
            once and must conform to the webhook payload schema described below.

    Webhook payload schema::

        {
            "event": "capture_succeeded" | "capture_failed",  # required
            "intent_id": "<reservation-uuid>"                  # required
        }

    Returns:
        ``{"ok": True}`` on success (``200 OK``) regardless of whether the
        reservation was found, so the provider does not retry unnecessarily.

    Raises:
        HTTPException(400): When the ``event`` field is missing from the payload.
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

                # Parse seats from reservation for notification (handle both JSON string and list formats)
                seats = (
                    json.loads(reservation["seats"])
                    if isinstance(reservation["seats"], str)
                    else reservation["seats"]
                )

                # Publish success notification
                notification = {
                    "type": "payment_confirmed",
                    "data": {
                        "user_email": reservation.get("user_email"),
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
