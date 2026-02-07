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

### Get Event Details

**GET** `/booking/events/{event_id}`

Get event information and available seats. (Public endpoint)

**Response:** `200 OK`
```json
{
  "event_id": "event123",
  "name": "Event event123",
  "start_time": "2026-02-14T19:00:00Z",
  "venue": "Sample Stadium",
  "rows": [
    {
      "row_id": "A",
      "seats_count": 50,
      "available_intervals": [
        {
          "start": 1,
          "length": 50
        }
      ],
      "cached_at": "2026-02-07T12:00:00Z"
    }
  ]
}
```

---

### Reserve Seats

**POST** `/booking/bookings/reserve`

Reserve seats for an event. **Requires Authentication.**

**Headers:**
```
Authorization: Bearer <token>
```

**Request Body:**
```json
{
  "event_id": "event123",
  "num_seats": 2,
  "preferred_rows": ["A", "B"]
}
```

**Response:** `201 Created`
```json
{
  "reservation_id": "uuid",
  "event_id": "event123",
  "seats": [
    {
      "row": "A",
      "seat": 1,
      "event_id": "event123"
    },
    {
      "row": "A",
      "seat": 2,
      "event_id": "event123"
    }
  ],
  "expires_at": "2026-02-07T12:10:00Z",
  "status": "reserved"
}
```

**Errors:**
- `400 Bad Request` - Invalid num_seats
- `401 Unauthorized` - Missing or invalid token
- `409 Conflict` - No contiguous block available

---

### Capture Payment

**POST** `/booking/payments/capture`

Process payment for a reservation. **Requires Authentication.**

**Headers:**
```
Authorization: Bearer <token>
Idempotency-Key: unique-key (optional)
```

**Request Body:**
```json
{
  "reservation_id": "uuid",
  "payment_method": "card",
  "amount": 100.00
}
```

**Response:** `200 OK`
```json
{
  "intent_id": "uuid",
  "status": "requires_confirmation"
}
```

---

## Booking Status Endpoints

All booking status endpoints **require authentication**.

### Get Reservation Status

**GET** `/status/{reservation_id}`

Get the current status of a reservation.

**Headers:**
```
Authorization: Bearer <token>
```

**Response:** `200 OK`
```json
{
  "reservation_id": "uuid",
  "event_id": "event123",
  "user_id": "uuid",
  "status": "reserved",
  "seats": [
    {
      "row": "A",
      "seat": 1,
      "event_id": "event123"
    }
  ],
  "created_at": "2026-02-07T12:00:00Z",
  "expires_at": "2026-02-07T12:10:00Z",
  "confirmed_at": null
}
```

**Errors:**
- `401 Unauthorized` - Invalid token
- `403 Forbidden` - Not authorized to view this reservation
- `404 Not Found` - Reservation not found

---

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
  "reservation_id": "uuid",
  "event_id": "event123",
  "user_id": "uuid",
  "status": "confirmed",
  "seats": [
    {
      "row": "A",
      "seat": 1
    }
  ],
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
      "reservation_id": "uuid",
      "event_id": "event123",
      "user_id": "uuid",
      "status": "confirmed",
      "seats": [{"row": "A", "seat": 1}],
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

**POST** `/payment/intents/{intent_id}/confirm`

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
