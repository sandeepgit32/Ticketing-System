# Booking Status Service

This microservice provides read-only access to booking information.
It is responsible for:

- Retrieving individual booking details
- Listing all bookings for the authenticated user
- Verifying JWT tokens by consulting the Auth service
- Health check endpoint

## Architecture

Implemented using **Flask** with a MySQL connection pool. Before handling
requests the service creates a connection pool (`status_pool`) during the
first request. CORS is enabled universally for simplicity.

## Configuration

Use environment variables or a `.env` file (copy from `.env.example`).

```env
# Database
MYSQL_HOST=database
MYSQL_PORT=3306
MYSQL_USER=ticketuser
MYSQL_PASSWORD=ticketpass
MYSQL_DATABASE=ticketing

# Auth service URL
auth to verify tokens
AUTH_SERVICE_URL=http://auth:8000
```

## Running

```bash
pip install -r requirements.txt
python main.py
```

In Docker the service starts automatically via `CMD ["python", "main.py"]`.

## API Endpoints

- `GET /bookings/<booking_id>` – returns booking details; requires a
  `Authorization: Bearer <token>` header.
- `GET /user/bookings?limit=50&offset=0` – paginated list of the current
  user’s bookings.
- `GET /health` – simple health response `{"status":"healthy"}`.

### Token verification

Tokens are forwarded to the auth service’s `/verify` endpoint. If the token
is missing, invalid, or auth service is unreachable, this service responds
with the appropriate HTTP error.

## Schema

Pydantic models live in `schemas.py` but they are only used internally for
response formatting; Flask returns the `.dict()` of each model.

## Notes

- This service is synchronous; HTTP calls to auth are blocking.
- Database credentials should be provided securely, and CORS tightened in
  production.
