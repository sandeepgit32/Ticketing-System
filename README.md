# BookEventTicket (Flash Sale)

This repository contains a complete microservices-based booking platform designed to handle flash-sale style events. The system includes authentication, booking management, payment processing, notifications, and a complete API gateway architecture.

## System Architecture

The system follows the block diagram architecture with the following components:

### Core Services

1. **API Gateway** (Port 8000)
   - Single entry point for all client requests
   - JWT token verification
   - Request routing to microservices
   - Built with FastAPI

2. **Auth Service** (Port 8002)
   - User registration and authentication
   - JWT token generation and verification
   - Built with FastAPI + MySQL
   - Uses bcrypt for password hashing

3. **Booking Service** (Port 8001)
   - Seat reservation using Redis bitmap
   - Event management
   - Payment capture coordination
   - Publishes notifications to queue
   - Built with FastAPI + Redis + MySQL

4. **Booking Status Service** (Port 8003)
   - Check reservation status
   - Get booking details
   - User booking history
   - Built with FastAPI + MySQL
   - Protected routes (requires authentication)

5. **Payment Services** (Port 9001 externally, both run on :8000 internally)
   - **Mock provider** (`payment-mock`) — zero-config local development, no credentials needed
   - **Razorpay provider** (`payment-razorpay`) — real payment processing via Razorpay Orders API
   - Both expose identical endpoints; switch by changing one env var (see [Switching Payment Providers](#switching-payment-providers))
   - Built with FastAPI

6. **Notification Service**
   - Processes notification queue
   - Sends emails via Mailtrap SMTP
   - Background worker process
   - Supports reservation confirmations, payment confirmations, and failure notifications

7. **Worker Service**
   - Background job processing
   - Handles payment webhooks
   - Built on Redis queue

### Infrastructure

- **MySQL Database** (Port 3306)
  - User accounts
  - Reservations and bookings
  - Event data

- **Redis** (Port 6379)
  - Fast seat allocation using bitmaps
  - Job queues for async processing
  - Notification queue

- **Frontend** (Port 5173)
  - Modern Vue.js 3 application with Composition API
  - Complete authentication system (login/register)
  - Interactive seat selection and booking flow
  - User booking history and management
  - Professional UI with responsive design
  - State management with Pinia
  - Routing with Vue Router

## Getting Started

### Prerequisites

- Docker & Docker Compose
- (Optional) Mailtrap account for email testing

### Installation

1. Clone the repository:
   ```bash
   cd ticketing-system
   ```

2. Create environment file:
   ```bash
   cp .env.example .env
   ```

3. (Optional) Add your Mailtrap credentials to `.env`:
   ```
   MAILTRAP_USER=your_username
   MAILTRAP_PASSWORD=your_password
   ```
   Sign up at https://mailtrap.io/ for free email testing.

4. Start all services:
   ```bash
   docker compose up --build
   ```

5. Wait for all services to be healthy. You should see:
   - MySQL initializing and ready
   - Auth service connected to MySQL
   - Booking service connected to Redis and MySQL
   - Booking Status service ready
   - Notification service listening on queue
   - API Gateway routing requests
   - Frontend served on http://localhost:5173

6. Access the application:
   - **Frontend Application**: http://localhost:5173
   - **API Gateway**: http://localhost:8000
   - First-time users will see the login/registration page

### Service Endpoints

All requests should go through the **API Gateway** at `http://localhost:8000`

#### Authentication Endpoints

- `POST /auth/register` - Register a new user
  ```json
  {
    "email": "user@example.com",
    "password": "securepassword",
    "full_name": "John Doe"
  }
  ```

- `POST /auth/login` - Login and get JWT token
  ```json
  {
    "email": "user@example.com",
    "password": "securepassword"
  }
  ```
  Returns:
  ```json
  {
    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "token_type": "bearer",
    "expires_in": 3600
  }
  ```

- `POST /auth/verify` - Verify JWT token (requires Bearer token)

#### Booking Endpoints

- `GET /booking/events/{event_id}` - Get event details (public)

- `POST /booking/bookings/reserve` - Reserve seats (requires auth)
  ```json
  {
    "event_id": "event123",
    "num_seats": 2,
    "preferred_rows": ["A"]
  }
  ```
  Headers: `Authorization: Bearer <token>`

- `POST /booking/payments/capture` - Capture payment (requires auth)
  ```json
  {
    "reservation_id": "uuid",
    "payment_method": "card"
  }
  ```

#### Booking Status Endpoints (All require authentication)

- `GET /status/{reservation_id}` - Get reservation status
- `GET /status/bookings/{booking_id}` - Get booking details
- `GET /status/user/bookings` - Get all user bookings (with pagination)
  - Query params: `?limit=50&offset=0`

### Using the System

#### Option 1: Web Interface (Recommended)

1. **Open the frontend**: Navigate to http://localhost:5173 in your browser

2. **Register an account**: Click "Sign Up" and create a new account with your email and password

3. **Browse events**: View available events with pricing and seat availability

4. **Book tickets**: 
   - Click on an event
   - Select number of seats and preferred row
   - View the interactive seat map
   - Click "Reserve Seats"
   - Choose payment method
   - Complete booking

5. **View bookings**: Check "My Bookings" to see all your ticket reservations

#### Option 2: API (For Testing/Development)

1. **Register a user:**
   ```bash
   curl -X POST http://localhost:8000/auth/register \
     -H "Content-Type: application/json" \
     -d '{
       "email": "test@example.com",
       "password": "password123",
       "full_name": "Test User"
     }'
   ```

2. **Login to get token:**
   ```bash
   curl -X POST http://localhost:8000/auth/login \
     -H "Content-Type: application/json" \
     -d '{
       "email": "test@example.com",
       "password": "password123"
     }'
   ```
   Save the `access_token` from the response.

2. **Reserve seats:**
   ```bash
   curl -X POST http://localhost:8000/booking/bookings/reserve \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <YOUR_TOKEN>" \
     -d '{
       "event_id": "event123",
       "num_seats": 2,
       "preferred_rows": ["A"]
     }'
   ```

3. **Check reservation status:**
   ```bash
   curl -X GET http://localhost:8000/status/<RESERVATION_ID> \
     -H "Authorization: Bearer <YOUR_TOKEN>"
   ```

4. **View your bookings:**
   ```bash
   curl -X GET http://localhost:8000/status/user/bookings \
     -H "Authorization: Bearer <YOUR_TOKEN>"
   ```

## Development

### Data Flow

The system is designed as a series of coordinated microservices; each step is owned by a single service and connected via the API Gateway and Redis queues.

1. **Login / Register**
   - The frontend calls `POST /auth/register` or `POST /auth/login` on the API Gateway.
   - Auth Service validates credentials against MySQL, issues a JWT token, and returns it to the frontend.

2. **View events**
   - The frontend requests `GET /booking/events` via the API Gateway.
   - Booking Service queries MySQL (`events`, `seats`) and returns event metadata and seat availability.

3. **Select seats + reserve**
   - The frontend submits `POST /booking/bookings/reserve` with the selected seat IDs and the user's JWT token.
   - Booking Service generates a **reservation ID** (UUID) and an expiration timestamp.
   - Booking Service calls a Redis Lua script to atomically reserve seats in a Redis bitmap and store reservation metadata (reservation ID, seat indexes, expiry).
   - Booking Service then inserts a row into MySQL `reservations` table:
     - `reservation_id` (UUID)
     - `event_id`
     - `user_email` (from forwarded header)
     - `status = reserved`
     - `seats` (JSON list)
     - `expires_at` (UTC timestamp)
     The `reservations` table is for temporary seat holds before payment capture.
   - Booking Service publishes a notification message to Redis `queue:notifications` (type `reservation_confirmed`).

4. **Payment**
   - The frontend calls `POST /booking/payments/capture` with `reservation_id` and payment data.
   - Booking Service forwards the request to the Payment Service (mock provider) and returns the response.

5. **Payment webhook processing**
   - Payment Service sends a webhook (`POST /payments/webhook`) back to Booking Service.
   - Booking Service creates a **booking ID** (UUID) and inserts into MySQL `bookings`:
     - `booking_id` (UUID)
     - `reservation_id`
     - `event_id`
     - `user_email`
     - `status = confirmed`
     - `seats` (JSON list)
     - `payment_status` (completed / failed)
     - `total_amount`
   - Booking Service updates the corresponding `reservations` row to `status = confirmed` (or `expired`/`failed`).
   - Booking Service publishes a notification message to Redis `queue:notifications` (type `payment_confirmed` or `payment_failed`).

6. **Notification delivery**
   - Notification Service continuously consumes messages from `queue:notifications`.
   - It builds an email based on the notification type and sends it via SMTP (Mailtrap by default).
   - If SMTP credentials are not configured, it logs a mock email to stdout.

7. **Expiration / cleanup**
   - Booking Service runs a background expiry worker that scans Redis for expired reservations and releases seats.
   - Expired reservations are also updated in MySQL and removed from Redis.

### Project Structure

```
ticketing-system/
├── services/
│   ├── auth/              # Authentication service
│   ├── booking/           # Booking service
│   ├── booking-status/    # Status checking service
│   ├── gateway/           # API Gateway
│   ├── notification/      # Notification service
│   ├── payment/
│   │   ├── mock/          # Mock payment provider (local dev)
│   │   └── razorpay/      # Razorpay payment provider (production)
│   └── worker/            # Background worker
├── frontend/vue/          # Vue.js frontend (refactored)
│   ├── src/
│   │   ├── components/    # Reusable UI components
│   │   ├── views/         # Page components
│   │   ├── stores/        # Pinia state management
│   │   ├── router/        # Vue Router configuration
│   │   └── services/      # API integration layer
│   └── README.md          # Frontend documentation
├── infra/helm/            # Kubernetes Helm charts
├── docker-compose.yml     # Docker services configuration
└── README.md
```

### Switching Payment Providers

The gateway routes all payment traffic to a single configurable URL. Both providers expose identical endpoints on port 8000 internally.

**Step 1 — Tell the gateway which provider to use** (`services/gateway/.env`):
```env
# Mock (local dev — no credentials needed):
PAYMENT_SERVICE_URL=http://payment-mock:8000

# Razorpay (real payments):
PAYMENT_SERVICE_URL=http://payment-razorpay:8000
```

**Step 2 — Tell the booking service the same** (`services/booking/.env`):
```env
# Mock:
PAYMENT_PROVIDER_URL=http://payment-mock:8000

# Razorpay:
PAYMENT_PROVIDER_URL=http://payment-razorpay:8000
```

**Step 3 (Razorpay only) — Add credentials** (`services/payment/razorpay/.env`):
```env
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_key_secret
RAZORPAY_WEBHOOK_SECRET=any_strong_string
WEBHOOK_SECRET=must_match_booking_WEBHOOK_SECRET
BOOKING_WEBHOOK_URL=http://booking:8000/payments/webhook
REDIS_URL=redis://redis:6379/0
```
Get test credentials from the [Razorpay Dashboard](https://dashboard.razorpay.com/) → Settings → API Keys.

**Step 4 — Restart**:
```bash
docker compose up --build gateway booking payment-mock payment-razorpay
```

The mock provider works out of the box with no credentials — `services/payment/mock/.env` is pre-configured for local development.

---

### Direct Service Access (for debugging)

While the API Gateway is the recommended entry point, you can access services directly:

- API Gateway: http://localhost:8000
- Booking Service: http://localhost:8001
- Auth Service: http://localhost:8002
- Booking Status: http://localhost:8003
- Payment Mock: http://localhost:9001
- Frontend: http://localhost:5173

### Viewing Logs

View logs for all services:
```bash
docker compose logs -f
```

View logs for specific service:
```bash
docker compose logs -f gateway
docker compose logs -f notification
docker compose logs -f booking
```

### Database Access

Connect to MySQL:
```bash
docker compose exec mysql mysql -u ticketuser -pticketpass ticketing
```

Connect to Redis:
```bash
docker compose exec redis redis-cli
```

### Notification Testing

If you don't configure Mailtrap credentials, notifications will be logged to console in mock mode. Check notification service logs:
```bash
docker compose logs -f notification
```

To use real email testing with Mailtrap:
1. Sign up at https://mailtrap.io/
2. Get your SMTP credentials from the inbox settings
3. Add them to your `.env` file
4. Restart services: `docker compose up -d notification`

## Deployment

### Kubernetes Deployment

Helm charts are provided in `infra/helm/booking/` directory:

```bash
cd infra/helm/booking
helm install ticketing-system . --namespace ticketing --create-namespace
```

The Helm chart includes:
- Deployment configurations
- Service definitions
- KEDA ScaledObject for autoscaling

### Environment Variables

Key environment variables for production:

- `JWT_SECRET_KEY` - Strong secret for JWT signing
- `MYSQL_PASSWORD` - Strong database password
- `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` - Production email service
- `REDIS_URL` - Redis connection string

## Architecture Highlights

### Message Queues (Redis)

The system uses Redis for two types of queues:

1. **Notification Queue** (`queue:notifications`)
   - Published by: Booking Service
   - Consumed by: Notification Service
   - Purpose: Async email notifications

2. **Job Queue** (`queue:jobs`)
   - Published by: Booking Service
   - Consumed by: Worker Service
   - Purpose: Background job processing

### Database Schema

**MySQL Tables:**
- `users` - User accounts and authentication
- `reservations` - Temporary seat reservations
- `bookings` - Confirmed bookings after payment
- `events` - Event information

**Redis Data:**
- Seat bitmaps for fast allocation
- Lua scripts for atomic operations

### Security

- JWT-based authentication with expiry
- Password hashing with bcrypt
- Token verification on protected routes
- API Gateway handles all authentication
- Service-to-service communication via internal network

## Future Enhancements

- [ ] Add rate limiting to API Gateway
- [ ] Implement refresh tokens
- [ ] Add booking expiration worker
- [ ] Add monitoring and metrics (Prometheus)
- [ ] Implement distributed tracing
- [ ] Add caching layer
- [ ] WebSocket support for real-time updates

## License

MIT License

## Support

For issues and questions, please open an issue on the repository.
