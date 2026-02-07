import os
from datetime import datetime, timezone
from typing import List, Optional

import httpx
import mysql.connector
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from mysql.connector import pooling
from pydantic import BaseModel

# Configuration
MYSQL_HOST = os.getenv("MYSQL_HOST", "database")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "ticketuser")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ticketpass")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ticketing")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth:8000")

app = FastAPI(title="Booking Status Service")
security = HTTPBearer()
db_pool = None


class BookingDetails(BaseModel):
    booking_id: str
    event_id: str
    user_id: str
    status: str  # reserved, confirmed, expired, cancelled
    seats: List[dict]
    payment_status: str
    total_amount: Optional[float] = None
    created_at: str
    updated_at: str
    expires_at: Optional[str] = None


class UserBookingsResponse(BaseModel):
    bookings: List[BookingDetails]
    total: int


def get_db_connection():
    """Get a connection from the pool"""
    return db_pool.get_connection()


@app.on_event("startup")
async def startup_event():
    global db_pool
    # Wait for MySQL to be ready
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
                raise Exception(f"Could not connect to database: {e}")


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token with auth service"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AUTH_SERVICE_URL}/verify",
                headers={"Authorization": f"Bearer {credentials.credentials}"},
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                )
            return response.json()
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service unavailable",
        )


@app.get("/bookings/{booking_id}", response_model=BookingDetails)
async def get_booking_details(
    booking_id: str, current_user: dict = Depends(verify_token)
):
    """Get booking details by ID"""
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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
            )

        # Check if user has access to this booking
        if booking["user_id"] != current_user.get("user_id"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )

        import json

        return BookingDetails(
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
    finally:
        cursor.close()
        conn.close()


@app.get("/user/bookings", response_model=UserBookingsResponse)
async def get_user_bookings(
    current_user: dict = Depends(verify_token), limit: int = 50, offset: int = 0
):
    """Get all bookings for the current user"""
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

        return UserBookingsResponse(bookings=booking_list, total=total)
    finally:
        cursor.close()
        conn.close()


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
