# API Documentation

## Base URL

All API requests should be made to the API Gateway:

```
http://localhost:8000
```

## Authentication

Most endpoints require JWT authentication. Include the token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

---

## Auth Endpoints

### Register User

**POST** `/auth/register`

Create a new user account.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "full_name": "John Doe"
}
```

**Response:** `201 Created`
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "full_name": "John Doe",
  "created_at": "2026-02-07T12:00:00Z"
}
```

**Errors:**
- `409 Conflict` - Email already registered

---

### Login

**POST** `/auth/login`

Login and receive JWT token.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**Errors:**
- `401 Unauthorized` - Invalid credentials

---

### Verify Token

**POST** `/auth/verify`

Verify JWT token validity.

**Headers:**
```
Authorization: Bearer <token>
```

**Response:** `200 OK`
```json
{
  "valid": true,
  "user_id": "uuid",
  "email": "user@example.com",
  "full_name": "John Doe"
}
```

**Errors:**
- `401 Unauthorized` - Invalid or expired token

---

## Booking Endpoints

### List Venues

**GET** `/booking/venues`

Return all configured venues. Public endpoint.

**Response:** `200 OK`
```json
{
  "venues": [
    { "name": "Sample Stadium" }
  ]
}
```

---

### Get Venue Details

**GET** `/booking/venues/{venue_name}`

Return the seating layout and pricing for a venue. Public endpoint.

**Response:** `200 OK`
```json
{
  "name": "Sample Stadium",
  "rows": ["A", "B", "C", "D"],
  "columns": [1, 2, 3, 4, 5],
  "seat_price": {
    "A": 75.0,
    "B": 50.0
  }
}
```

**Errors:**
- `404 Not Found` - Venue not found

---

### List Events

**GET** `/booking/events`

Return a list of all events. Public endpoint.

**Response:** `200 OK`
```json
{
  "events": [
    {
      "event_id": "evt-abc123",
      "name": "Rock Concert 2026",
      "venue": "Sample Stadium",
      "date": "2026-06-15",
      "num_seats_available": 142,
      "list_of_prices": [50.0, 75.0]
    }
  ]
}
```

---

### Get Event Details

**GET** `/booking/events/{event_id}`

Get event information and available seats. Public endpoint.

**Response:** `200 OK`
```json
{
  "event_id": "evt-abc123",
  "name": "Rock Concert 2026",
  "start_time": "2026-06-15T19:00:00",
  "venue": "Sample Stadium",
  "closed": 0,
  "seat_arrangements": [
    ["A1", "A2", "A3", "A4"],
    ["B1", "B2", "B3", "B4"]
  ],
  "seat_availability_map": {
    "A1": 0,
    "A2": 1,
    "B1": 0,
    "B2": 0
  },
  "seat_price_map": {
    "A1": 75.0,
    "A2": 75.0,
    "B1": 50.0,
    "B2": 50.0
  }
}
```

**Errors:**
- `404 Not Found` - Event not found

---

### Create Event

**POST** `/booking/events`

Create a new event and pre-populate its seats from the venue configuration. **Requires Authentication.**

**Headers:**
```
Authorization: Bearer <token>
```

**Request Body:**
```json
{
  "name": "Rock Concert 2026",
  "venue": "Sample Stadium",
  "start_time": "2026-06-15T19:00:00"
}
```

**Response:** `201 Created`
```json
{
  "event_id": "a3f1c2d4-5678-90ab-cdef-1234567890ab"
}
```

**Errors:**
- `400 Bad Request` - Unknown venue
- `401 Unauthorized` - Missing or invalid token

---

### Close Event

**GET** `/booking/events/{event_id}/close`

Mark an event as closed so no new reservations can be made. Outstanding reservations are expired and seats freed. **Requires Authentication.**

**Headers:**
```
Authorization: Bearer <token>
```

**Response:** `200 OK`
```json
{
  "event_id": "evt-abc123",
  "status": "closed"
}
```

**Errors:**
- `401 Unauthorized` - Missing or invalid token
- `404 Not Found` - Event not found

---

### Reserve Seats

**POST** `/booking/bookings/reserve`

Reserve specific seats for an event. **Requires Authentication.**

**Headers:**
```
Authorization: Bearer <token>
Idempotency-Key: unique-key (optional)
```

**Request Body:**
```json
{
  "event_id": "evt-abc123",
  "selected_seats": ["A1", "A2"]
}
```

**Response:** `201 Created`
```json
{
  "reservation_id": "uuid",
  "event_id": "evt-abc123",
  "seats": ["A1", "A2"],
  "expires_at": "2026-02-07T12:10:00Z",
  "status": "reserved"
}
```

**Errors:**
- `400 Bad Request` - Empty seat list, invalid seat ID, or duplicate seats
- `401 Unauthorized` - Missing or invalid token
- `404 Not Found` - Event not found
- `409 Conflict` - Seat already reserved or event is closed

---

### Capture Payment

**POST** `/booking/payments/capture`

Forward a payment capture request to the payment provider. **Requires Authentication.**

**Headers:**
```
Authorization: Bearer <token>
Idempotency-Key: unique-key (optional)
```

**Request Body:**
```json
{
  "intent_id": "uuid",
  "amount": 150.00,
  "currency": "USD"
}
```

**Response:** `200 OK`
```json
{
  "intent_id": "uuid",
  "status": "requires_confirmation",
  "amount": 150.00,
  "currency": "USD"
}
```

**Errors:**
- `401 Unauthorized` - Missing or invalid token
- `402 Payment Required` - Payment declined
- `503 Service Unavailable` - Payment provider unavailable

---

## Booking Status Endpoints

All booking status endpoints **require authentication**.

### Get Booking Details

**GET** `/status/bookings/{booking_id}`

Get details of a confirmed booking.

**Headers:**
```
Authorization: Bearer <token>
```

**Response:** `200 OK`
```json
{
  "booking_id": "uuid",
  "event_id": "event123",
  "event_name": "Rock Concert 2026",
  "event_start_time": "2026-06-15T19:00:00",
  "user_email": "user@example.com",
  "status": "confirmed",
  "seats": ["A1", "A2"],
  "payment_status": "completed",
  "total_amount": 100.00,
  "created_at": "2026-02-07T12:00:00Z",
  "updated_at": "2026-02-07T12:05:00Z"
}
```

**Errors:**
- `401 Unauthorized` - Invalid token
- `403 Forbidden` - Not authorized to view this booking
- `404 Not Found` - Booking not found

---

### Get User Bookings

**GET** `/status/user/bookings`

Get all bookings for the authenticated user.

**Headers:**
```
Authorization: Bearer <token>
```

**Query Parameters:**
- `limit` (optional, default: 50) - Number of results per page
- `offset` (optional, default: 0) - Pagination offset

**Response:** `200 OK`
```json
{
  "bookings": [
    {
      "booking_id": "uuid",
      "event_id": "event123",
      "event_name": "Rock Concert 2026",
      "event_start_time": "2026-06-15T19:00:00",
      "user_email": "user@example.com",
      "status": "confirmed",
      "seats": ["A1"],
      "payment_status": "completed",
      "total_amount": 100.00,
      "created_at": "2026-02-07T12:00:00Z",
      "updated_at": "2026-02-07T12:05:00Z"
    }
  ],
  "total": 1
}
```

---

## Payment Service Endpoints (Testing Only)

These endpoints are for testing the mock payment provider. In production, these would be replaced with real payment provider APIs.

### Create Payment Intent

**POST** `/payment/intents`

Create a payment intent.

**Headers:**
```
Idempotency-Key: unique-key (optional)
```

**Request Body:**
```json
{
  "amount": 100.00,
  "currency": "USD",
  "metadata": {
    "reservation_id": "uuid"
  }
}
```

---

### Confirm Payment Intent

**GET** `/payment/intents/{intent_id}/confirm`

Confirm and process a payment intent.

**Query Parameters:**
- `success` (optional, default: true) - Simulate success or failure
- `delay_ms` (optional, default: 0) - Delay webhook delivery

---

## Status Codes

- `200 OK` - Request successful
- `201 Created` - Resource created successfully
- `400 Bad Request` - Invalid request parameters
- `401 Unauthorized` - Authentication required or invalid
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `409 Conflict` - Resource conflict (e.g., email already exists)
- `500 Internal Server Error` - Server error
- `503 Service Unavailable` - Service temporarily unavailable

---

## Error Response Format

All error responses follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

---

## Rate Limiting

Currently not implemented. Consider adding rate limiting for production use.

---

## Webhooks

### Payment Webhook

The payment service sends webhooks to the booking service at:

```
POST /booking/payments/webhook
```

**Webhook Payload:**
```json
{
  "event": "capture_succeeded",
  "payment_id": "uuid",
  "intent_id": "uuid",
  "timestamp": 1234567890
}
```

Possible event types:
- `capture_succeeded` - Payment successful
- `capture_failed` - Payment failed

---

## Notification System

The system automatically sends email notifications for:

1. **Reservation Confirmed** - When seats are successfully reserved
2. **Payment Confirmed** - When payment is processed and booking is confirmed
3. **Payment Failed** - When payment processing fails

Configure Mailtrap credentials in `.env` to receive actual emails during development.
