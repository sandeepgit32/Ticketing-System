import os

from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from mysql.connector import pooling

# The container starts with `uvicorn main:app` from the service directory,
# loading `main` as a top‑level module. Relative imports would fail in that
# environment, so import schemas as a plain module name; the working directory
# (`/app`) is on sys.path inside the container.
from schemas import BookingDetails, UserBookingsResponse


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


# Configuration
MYSQL_HOST = required_env("MYSQL_HOST")
MYSQL_PORT = required_env("MYSQL_PORT", cast=int)
MYSQL_USER = required_env("MYSQL_USER")
MYSQL_PASSWORD = required_env("MYSQL_PASSWORD")
MYSQL_DATABASE = required_env("MYSQL_DATABASE")

app = Flask(__name__)
CORS(app, origins="*", supports_credentials=True)
db_pool = None


def get_db_connection():
    """
    Get a MySQL connection from the shared pool.

    The pool is initialized during the first request by `startup_event`. If
    the pool has not yet been created this will initialize it lazily.

    Returns:
        mysql.connector.connection.MySQLConnection: usable connection object.
    """
    global db_pool
    if db_pool is None:
        startup_event()
    return db_pool.get_connection()


def startup_event():
    """
    Create a connection pool when the app handles its first HTTP request.

    This helper retries up to 30 times waiting for the database host to be
    reachable; it is useful when the service and database come up simultaneously
    in Docker. Failure after all retries will abort startup with an exception.
    """
    global db_pool
    import time

    max_retries = 30
    for i in range(max_retries):
        try:
            db_pool = pooling.MySQLConnectionPool(
                pool_name="status_pool",
                pool_size=5,
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
            )
            print("Connected to database")
            break
        except Exception:
            if i < max_retries - 1:
                print(f"Waiting for database... ({i + 1}/{max_retries})")
                time.sleep(2)
            else:
                raise


# Flask 2.3 removed `before_first_request`; `before_serving` may not exist
# in some versions. Register the startup hook when available.
if hasattr(app, "before_first_request"):
    app.before_first_request(startup_event)
elif hasattr(app, "before_serving"):
    app.before_serving(startup_event)
else:
    # No lifecycle hook available; fallback to lazy initialization in get_db_connection.
    pass


def get_current_user_email() -> str:
    """
    Read authenticated user identity from the gateway-forwarded header.

    Authentication is enforced by the API gateway before the request reaches
    this service. The gateway verifies the JWT and forwards the authenticated
    user's email via the X-User-Email header, so this service can trust it.

    Returns:
        str: Authenticated user's email.
    """
    return request.headers.get("X-User-Email", "")


@app.route("/bookings/<booking_id>", methods=["GET"])
def get_booking_details(booking_id: str):
    """
    Retrieve a single booking record and ensure the caller owns it.

    Args:
        booking_id (str): UUID of the booking to fetch.

    Returns:
        flask.Response: JSON-serialized booking details.

    The endpoint relies on gateway-provided `X-User-Email` identity. If the
    booking does not exist a 404 error is returned. If the authenticated user
    does not match the booking's `user_email`, a 403 is raised.
    """
    current_user_email = get_current_user_email()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            """SELECT booking_id, event_id, user_email, status, 
                      seats, payment_status, total_amount, created_at, updated_at, expires_at 
               FROM bookings WHERE booking_id = %s""",
            (booking_id,),
        )
        booking = cursor.fetchone()

        if not booking:
            abort(404, description="Booking not found")

        # Check if user has access to this booking
        if booking["user_email"] != current_user_email:
            abort(403, description="Access denied")

        import json

        model = BookingDetails(
            booking_id=booking["booking_id"],
            event_id=booking["event_id"],
            user_email=booking["user_email"],
            status=booking["status"],
            seats=json.loads(booking["seats"])
            if isinstance(booking["seats"], str)
            else booking["seats"],
            payment_status=booking["payment_status"],
            total_amount=float(booking["total_amount"])
            if booking["total_amount"]
            else None,
            created_at=booking["created_at"].isoformat(),
            updated_at=booking["updated_at"].isoformat(),
            expires_at=booking["expires_at"].isoformat()
            if booking["expires_at"]
            else None,
        )
        return jsonify(model.model_dump())
    finally:
        cursor.close()
        conn.close()


@app.route("/user/bookings", methods=["GET"])
def get_user_bookings():
    """
    Return a paginated list of bookings belonging to the authenticated user.

    Query parameters:
      - `limit` (int, default 50)
      - `offset` (int, default 0)

    The current user is identified via gateway-forwarded `X-User-Email`.
    Results include a `total` count and a `bookings` list.
    """
    user_email = get_current_user_email()
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Get total count
        cursor.execute(
            "SELECT COUNT(*) as total FROM bookings WHERE user_email = %s",
            (user_email,),
        )
        total = cursor.fetchone()["total"]

        # Get bookings with pagination
        cursor.execute(
            """SELECT booking_id, event_id, user_email, status, 
                      seats, payment_status, total_amount, created_at, updated_at, expires_at 
               FROM bookings 
               WHERE user_email = %s 
               ORDER BY created_at DESC 
               LIMIT %s OFFSET %s""",
            (user_email, limit, offset),
        )
        bookings = cursor.fetchall()

        import json

        booking_list = []
        for booking in bookings:
            booking_list.append(
                BookingDetails(
                    booking_id=booking["booking_id"],
                    event_id=booking["event_id"],
                    user_email=booking["user_email"],
                    status=booking["status"],
                    seats=json.loads(booking["seats"])
                    if isinstance(booking["seats"], str)
                    else booking["seats"],
                    payment_status=booking["payment_status"],
                    total_amount=float(booking["total_amount"])
                    if booking["total_amount"]
                    else None,
                    created_at=booking["created_at"].isoformat(),
                    updated_at=booking["updated_at"].isoformat(),
                    expires_at=booking["expires_at"].isoformat()
                    if booking["expires_at"]
                    else None,
                )
            )

        response_model = UserBookingsResponse(bookings=booking_list, total=total)
        return jsonify(response_model.model_dump())
    finally:
        cursor.close()
        conn.close()


@app.route("/health", methods=["GET"])
def health():
    """
    Simple health check used by orchestration systems.

    Returns 200 with `{"status":"healthy"}` when the service is running.
    """
    return jsonify({"status": "healthy"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
