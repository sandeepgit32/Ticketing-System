import os
import uuid
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel
import mysql.connector
from mysql.connector import pooling

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
SEATS_PER_ROW = int(os.getenv('SEATS_PER_ROW', '50'))
RESERVATION_TTL_SECONDS = int(os.getenv('RESERVATION_TTL_SECONDS', '600'))

# MySQL Configuration
MYSQL_HOST = os.getenv('MYSQL_HOST', 'database')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
MYSQL_USER = os.getenv('MYSQL_USER', 'ticketuser')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'ticketpass')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'ticketing')

# Queue names
NOTIFICATION_QUEUE = 'queue:notifications'

app = FastAPI(title='Booking Service')
redis_client: Optional[redis.Redis] = None
reserve_sha = None
db_pool = None


class ReserveRequest(BaseModel):
    event_id: str
    num_seats: int
    preferred_rows: Optional[List[str]] = None
    user_id: Optional[str] = None


def get_db_connection():
    """Get a connection from the pool"""
    return db_pool.get_connection()


@app.on_event('startup')
async def startup_event():
    global redis_client, reserve_sha, db_pool
    
    # Initialize Redis
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    
    # Load lua script
    script_path = os.path.join(os.path.dirname(__file__), 'redis_reserve.lua')
    with open(script_path, 'r') as f:
        script = f.read()
    reserve_sha = await redis_client.script_load(script)
    print('Loaded reserve Lua script, sha=', reserve_sha)
    
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
                database=MYSQL_DATABASE
            )
            print("Connected to database")
            break
        except Exception as e:
            if i < max_retries - 1:
                print(f"Waiting for database... ({i+1}/{max_retries})")
                sync_time.sleep(2)
            else:
                print(f"Warning: Could not connect to database: {e}")


@app.get('/events/{event_id}')
async def get_event(event_id: str):
    # Minimal mocked event with few rows
    rows = []
    for r in ['A', 'B', 'C', 'D', 'E']:
        rows.append({
            'row_id': r,
            'seats_count': SEATS_PER_ROW,
            'available_intervals': [{ 'start': 1, 'length': SEATS_PER_ROW }],
            'cached_at': datetime.now(timezone.utc).isoformat()
        })
    return {
        'event_id': event_id,
        'name': f'Event {event_id}',
        'start_time': (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        'venue': 'Sample Stadium',
        'rows': rows
    }


@app.post('/bookings/reserve', status_code=201)
async def reserve(req: ReserveRequest, idempotency_key: Optional[str] = Header(None), x_user_id: Optional[str] = Header(None), x_user_email: Optional[str] = Header(None)):
    if req.num_seats < 1:
        raise HTTPException(status_code=400, detail='num_seats must be >=1')
    
    # Use user_id from header or request body
    user_id = x_user_id or req.user_id or 'anon'
    
    # pick a row
    row = None
    if req.preferred_rows and len(req.preferred_rows) > 0:
        row = req.preferred_rows[0]
    else:
        # random pick
        row = 'A'

    reservation_id = str(uuid.uuid4())
    expires_at = int(time.time()) + RESERVATION_TTL_SECONDS

    key = f'seats:{req.event_id}:row:{row}:bitmap'
    try:
        res = await redis_client.evalsha(reserve_sha, 1, key,
                                         req.num_seats, reservation_id, req.event_id, row, user_id, 0, RESERVATION_TTL_SECONDS, expires_at, SEATS_PER_ROW)
    except redis.exceptions.ResponseError as e:
        if 'NO_BLOCK' in str(e):
            raise HTTPException(status_code=409, detail='No contiguous block available')
        raise

    # res = [reservation_id, seats_json, expiry_epoch]
    seats = json.loads(res[1])
    expires_at_iso = datetime.fromtimestamp(int(res[2]), tz=timezone.utc).isoformat()
    
    # Store reservation in MySQL
    if db_pool:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO reservations (reservation_id, event_id, user_id, status, seats, expires_at) 
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (reservation_id, req.event_id, user_id, 'reserved', json.dumps(seats), datetime.fromtimestamp(int(res[2]), tz=timezone.utc))
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error storing reservation in MySQL: {e}")
    
    # Publish notification
    notification = {
        'type': 'reservation_confirmed',
        'data': {
            'user_email': x_user_email or 'user@example.com',
            'reservation_id': reservation_id,
            'event_id': req.event_id,
            'event_name': f'Event {req.event_id}',
            'seats': seats,
            'expires_at': expires_at_iso
        }
    }
    await redis_client.lpush(NOTIFICATION_QUEUE, json.dumps(notification))
    
    return {
        'reservation_id': res[0],
        'event_id': req.event_id,
        'seats': seats,
        'expires_at': expires_at_iso,
        'status': 'reserved'
    }


@app.post('/payments/capture')
async def payments_capture(body: dict, idempotency_key: Optional[str] = Header(None)):
    # Minimal implementation: forward to mock provider
    payment_provider = os.getenv('PAYMENT_PROVIDER_URL', 'http://payment-mock:9000')
    async with httpx.AsyncClient() as client:
        headers = {}
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        r = await client.post(f'{payment_provider}/payments/intents', json=body, headers=headers, timeout=10)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


@app.post('/payments/webhook')
async def payments_webhook(request: Request):
    payload = await request.json()
    # naive signature validation (in real system, verify HMAC header)
    event = payload.get('event')
    if not event:
        raise HTTPException(status_code=400, detail='invalid webhook')
    
    # Handle payment events
    if event == 'capture_succeeded':
        # Payment successful - create booking
        booking_id = str(uuid.uuid4())
        reservation_id = payload.get('intent_id', 'unknown')
        
        # Store booking in MySQL
        if db_pool:
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                
                # Get reservation details
                cursor.execute(
                    "SELECT * FROM reservations WHERE reservation_id = %s",
                    (reservation_id,)
                )
                reservation = cursor.fetchone()
                
                if reservation:
                    # Create booking
                    cursor.execute(
                        """INSERT INTO bookings (booking_id, reservation_id, event_id, user_id, status, seats, payment_status, total_amount) 
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (booking_id, reservation_id, reservation['event_id'], reservation['user_id'], 'confirmed', 
                         reservation['seats'], 'completed', 100.00)
                    )
                    
                    # Update reservation status
                    cursor.execute(
                        "UPDATE reservations SET status = %s, confirmed_at = %s WHERE reservation_id = %s",
                        ('confirmed', datetime.now(timezone.utc), reservation_id)
                    )
                    
                    conn.commit()
                    
                    # Get user email (simplified - would need to join with users table)
                    seats = json.loads(reservation['seats']) if isinstance(reservation['seats'], str) else reservation['seats']
                    
                    # Publish success notification
                    notification = {
                        'type': 'payment_confirmed',
                        'data': {
                            'user_email': 'user@example.com',  # Would get from user lookup
                            'booking_id': booking_id,
                            'reservation_id': reservation_id,
                            'event_id': reservation['event_id'],
                            'event_name': f"Event {reservation['event_id']}",
                            'seats': seats,
                            'total_amount': 100.00
                        }
                    }
                    await redis_client.lpush(NOTIFICATION_QUEUE, json.dumps(notification))
                
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Error processing payment webhook: {e}")
    
    elif event == 'capture_failed':
        # Payment failed - publish notification
        reservation_id = payload.get('intent_id', 'unknown')
        notification = {
            'type': 'payment_failed',
            'data': {
                'user_email': 'user@example.com',
                'reservation_id': reservation_id,
                'event_id': 'unknown',
                'event_name': 'Event',
                'reason': 'Payment processing failed'
            }
        }
        await redis_client.lpush(NOTIFICATION_QUEUE, json.dumps(notification))
    
    # Enqueue job for worker processing
    job = {
        'job_id': str(uuid.uuid4()),
        'type': 'payment_webhook',
        'payload': payload,
        'created_at': datetime.now(timezone.utc).isoformat()
    }
    await redis_client.lpush('queue:jobs', json.dumps(job))
    return {'ok': True}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
