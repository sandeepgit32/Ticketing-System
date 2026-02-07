import os
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import mysql.connector
from mysql.connector import pooling
import httpx

# Configuration
MYSQL_HOST = os.getenv('MYSQL_HOST', 'mysql')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
MYSQL_USER = os.getenv('MYSQL_USER', 'ticketuser')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'ticketpass')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'ticketing')
AUTH_SERVICE_URL = os.getenv('AUTH_SERVICE_URL', 'http://auth:8000')

app = FastAPI(title='Booking Status Service')
security = HTTPBearer()
db_pool = None


class ReservationStatus(BaseModel):
    reservation_id: str
    event_id: str
    user_id: str
    status: str  # reserved, confirmed, expired, cancelled
    seats: List[dict]
    created_at: str
    expires_at: Optional[str] = None
    confirmed_at: Optional[str] = None


class BookingDetails(BaseModel):
    booking_id: str
    reservation_id: str
    event_id: str
    user_id: str
    status: str
    seats: List[dict]
    payment_status: str
    total_amount: Optional[float] = None
    created_at: str
    updated_at: str


class UserBookingsResponse(BaseModel):
    bookings: List[BookingDetails]
    total: int


def get_db_connection():
    """Get a connection from the pool"""
    return db_pool.get_connection()


def init_db():
    """Initialize database tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Reservations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            reservation_id VARCHAR(36) PRIMARY KEY,
            event_id VARCHAR(36) NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            status VARCHAR(20) NOT NULL,
            seats JSON NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NULL,
            confirmed_at TIMESTAMP NULL,
            INDEX idx_user_id (user_id),
            INDEX idx_event_id (event_id),
            INDEX idx_status (status)
        )
    """)
    
    # Bookings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id VARCHAR(36) PRIMARY KEY,
            reservation_id VARCHAR(36) NOT NULL,
            event_id VARCHAR(36) NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            status VARCHAR(20) NOT NULL,
            seats JSON NOT NULL,
            payment_status VARCHAR(20) NOT NULL,
            total_amount DECIMAL(10, 2) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_user_id (user_id),
            INDEX idx_reservation_id (reservation_id),
            INDEX idx_status (status)
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()


@app.on_event('startup')
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
                database=MYSQL_DATABASE
            )
            init_db()
            print("Connected to MySQL and initialized database")
            break
        except Exception as e:
            if i < max_retries - 1:
                print(f"Waiting for MySQL... ({i+1}/{max_retries})")
                time.sleep(2)
            else:
                raise Exception(f"Could not connect to MySQL: {e}")


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token with auth service"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AUTH_SERVICE_URL}/verify",
                headers={"Authorization": f"Bearer {credentials.credentials}"}
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token"
                )
            return response.json()
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service unavailable"
        )


@app.get('/status/{reservation_id}', response_model=ReservationStatus)
async def get_reservation_status(
    reservation_id: str,
    current_user: dict = Depends(verify_token)
):
    """Get reservation status by ID"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute(
            """SELECT reservation_id, event_id, user_id, status, seats, 
                      created_at, expires_at, confirmed_at 
               FROM reservations WHERE reservation_id = %s""",
            (reservation_id,)
        )
        reservation = cursor.fetchone()
        
        if not reservation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reservation not found"
            )
        
        # Check if user has access to this reservation
        if reservation['user_id'] != current_user.get('user_id'):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        import json
        return ReservationStatus(
            reservation_id=reservation['reservation_id'],
            event_id=reservation['event_id'],
            user_id=reservation['user_id'],
            status=reservation['status'],
            seats=json.loads(reservation['seats']) if isinstance(reservation['seats'], str) else reservation['seats'],
            created_at=reservation['created_at'].isoformat(),
            expires_at=reservation['expires_at'].isoformat() if reservation['expires_at'] else None,
            confirmed_at=reservation['confirmed_at'].isoformat() if reservation['confirmed_at'] else None
        )
    finally:
        cursor.close()
        conn.close()


@app.get('/bookings/{booking_id}', response_model=BookingDetails)
async def get_booking_details(
    booking_id: str,
    current_user: dict = Depends(verify_token)
):
    """Get booking details by ID"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute(
            """SELECT booking_id, reservation_id, event_id, user_id, status, 
                      seats, payment_status, total_amount, created_at, updated_at 
               FROM bookings WHERE booking_id = %s""",
            (booking_id,)
        )
        booking = cursor.fetchone()
        
        if not booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found"
            )
        
        # Check if user has access to this booking
        if booking['user_id'] != current_user.get('user_id'):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        import json
        return BookingDetails(
            booking_id=booking['booking_id'],
            reservation_id=booking['reservation_id'],
            event_id=booking['event_id'],
            user_id=booking['user_id'],
            status=booking['status'],
            seats=json.loads(booking['seats']) if isinstance(booking['seats'], str) else booking['seats'],
            payment_status=booking['payment_status'],
            total_amount=float(booking['total_amount']) if booking['total_amount'] else None,
            created_at=booking['created_at'].isoformat(),
            updated_at=booking['updated_at'].isoformat()
        )
    finally:
        cursor.close()
        conn.close()


@app.get('/user/bookings', response_model=UserBookingsResponse)
async def get_user_bookings(
    current_user: dict = Depends(verify_token),
    limit: int = 50,
    offset: int = 0
):
    """Get all bookings for the current user"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        user_id = current_user.get('user_id')
        
        # Get total count
        cursor.execute(
            "SELECT COUNT(*) as total FROM bookings WHERE user_id = %s",
            (user_id,)
        )
        total = cursor.fetchone()['total']
        
        # Get bookings with pagination
        cursor.execute(
            """SELECT booking_id, reservation_id, event_id, user_id, status, 
                      seats, payment_status, total_amount, created_at, updated_at 
               FROM bookings 
               WHERE user_id = %s 
               ORDER BY created_at DESC 
               LIMIT %s OFFSET %s""",
            (user_id, limit, offset)
        )
        bookings = cursor.fetchall()
        
        import json
        booking_list = []
        for booking in bookings:
            booking_list.append(BookingDetails(
                booking_id=booking['booking_id'],
                reservation_id=booking['reservation_id'],
                event_id=booking['event_id'],
                user_id=booking['user_id'],
                status=booking['status'],
                seats=json.loads(booking['seats']) if isinstance(booking['seats'], str) else booking['seats'],
                payment_status=booking['payment_status'],
                total_amount=float(booking['total_amount']) if booking['total_amount'] else None,
                created_at=booking['created_at'].isoformat(),
                updated_at=booking['updated_at'].isoformat()
            ))
        
        return UserBookingsResponse(
            bookings=booking_list,
            total=total
        )
    finally:
        cursor.close()
        conn.close()


@app.get('/health')
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
