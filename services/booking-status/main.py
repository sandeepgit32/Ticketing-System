import os
from datetime import datetime, timezone

import httpx
import mysql.connector
from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from mysql.connector import pooling

# The container starts with `uvicorn main:app` from the service directory,
# loading `main` as a top‑level module. Relative imports would fail in that
# environment, so import schemas as a plain module name; the working directory
# (`/app`) is on sys.path inside the container.
from schemas import BookingDetails, UserBookingsResponse

# Configuration
MYSQL_HOST = os.getenv("MYSQL_HOST", "database")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "ticketuser")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ticketpass")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ticketing")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth:8000")

app = Flask(__name__)
CORS(app, origins="*", supports_credentials=True)
db_pool = None


def get_db_connection():
    """
    Get a MySQL connection from the shared pool.

    The pool is initialized during the first request by `startup_event`. If
    the pool has not yet been created this will raise an exception.

    Returns:
        mysql.connector.connection.MySQLConnection: usable connection object.
    """
    return db_pool.get_connection()


@app.before_first_request
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
        except Exception as e:
            if i < max_retries - 1:
                print(f"Waiting for database... ({i + 1}/{max_retries})")
                time.sleep(2)
            else:
                raise


def verify_token():
    """
    Extract the bearer JWT from the `Authorization` header and validate it.

    The token is forwarded to the auth microservice's `/verify` endpoint.
    If the header is missing or malformed the request aborts with 401. Network
    errors produce a 503, and a non‑200 response from auth results in 401.

    Returns:
        dict: The JSON payload returned by auth (contains `user_id`, etc.).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        abort(401, description="Missing or invalid Authorization header")

    token = auth_header.split(None, 1)[1]

    try:
        response = httpx.post(
            f"{AUTH_SERVICE_URL}/verify",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except httpx.RequestError:
        abort(503, description="Auth service unavailable")

    if response.status_code != 200:
        abort(401, description="Invalid or expired token")

    return response.json()


@app.route("/bookings/<booking_id>", methods=["GET"])
def get_booking_details(booking_id: str):
    """
    Retrieve a single booking record and ensure the caller owns it.

    Args:
        booking_id (str): UUID of the booking to fetch.

    Returns:
        flask.Response: JSON-serialized booking details.

    The endpoint relies on `verify_token()` to authenticate. If the booking
    does not exist a 404 error is returned. If the authenticated user does not
    match the booking's `user_id`, a 403 is raised.
    """
    current_user = verify_token()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            """SELECT booking_id, event_id, user_id, status, 
                      seats, payment_status, total_amount, created_at, updated_at, expires_at 
               FROM bookings WHERE booking_id = %s""",
            (booking_id,),
        )
        booking = cursor.fetchone()

        if not booking:
            abort(404, description="Booking not found")

        # Check if user has access to this booking
        if booking["user_id"] != current_user.get("user_id"):
            abort(403, description="Access denied")

        import json

        model = BookingDetails(
            booking_id=booking["booking_id"],
            event_id=booking["event_id"],
            user_id=booking["user_id"],
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
        return jsonify(model.dict())
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

    The token is validated via `verify_token`. Results include a `total`
    count and a `bookings` list.
    """
    current_user = verify_token()
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        user_id = current_user.get("user_id")

        # Get total count
        cursor.execute(
            "SELECT COUNT(*) as total FROM bookings WHERE user_id = %s", (user_id,)
        )
        total = cursor.fetchone()["total"]

        # Get bookings with pagination
        cursor.execute(
            """SELECT booking_id, event_id, user_id, status, 
                      seats, payment_status, total_amount, created_at, updated_at, expires_at 
               FROM bookings 
               WHERE user_id = %s 
               ORDER BY created_at DESC 
               LIMIT %s OFFSET %s""",
            (user_id, limit, offset),
        )
        bookings = cursor.fetchall()

        import json

        booking_list = []
        for booking in bookings:
            booking_list.append(
                BookingDetails(
                    booking_id=booking["booking_id"],
                    event_id=booking["event_id"],
                    user_id=booking["user_id"],
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
        return jsonify(response_model.dict())
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
