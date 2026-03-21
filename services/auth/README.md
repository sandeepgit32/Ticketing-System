# Auth Service

This microservice handles user authentication and registration for BookEventTicket.

## Responsibilities

- Register new users with email, password, and full name.
- Hash passwords using bcrypt before saving to the database.
- Authenticate users and issue JWT access tokens.
- Verify and decode JWT tokens for protected routes.
- Provide a `get_current_user` dependency for other services to retrieve the authenticated user's information.

## Configuration

Environment variables are used for configuration. A `.env.example` file is provided with the required keys.

```env
# JWT settings
JWT_SECRET_KEY=your-secret-key-change-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Database settings
MYSQL_HOST=database
MYSQL_PORT=3306
MYSQL_USER=ticketuser
MYSQL_PASSWORD=ticketpass
MYSQL_DATABASE=ticketing
```

Copy `.env.example` to `.env` and fill in real values before running the service.

## Database

The service expects a MySQL database with a `users` table. During startup it establishes a connection pool using `mysql.connector.pooling`.

Example schema:

```sql
CREATE TABLE users (
    user_id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Running the Service

The service is built with FastAPI. Before launching be sure you have a
`.env` file with the proper settings (see above) or export the required
variables in your shell.

```bash
# install requirements
pip install -r requirements.txt

# either source .env or export values manually
# (e.g. `export JWT_SECRET_KEY=…`)

# start with uvicorn from inside the auth directory
uvicorn main:app --host 0.0.0.0 --port 8000
```

> **Note on imports:** the code uses a resilient import for the Pydantic
> schemas (see `main.py`). When running as a script or via `uvicorn main:app`
> the module name is `main` and relative imports would fail; the fallback
> to `from schemas import …` ensures the file can load correctly in that
> context. If you prefer running the service as a package instead, you can
> `cd ..` and execute `python -m services.auth.main` or `uvicorn
> services.auth.main:app`.

## API Endpoints

### `POST /register`
Registers a new user.

**Request body** (JSON):
```json
{
  "email": "user@example.com",
  "password": "secret",
  "full_name": "Jane Doe"
}
```

**Behavior**:
1. Checks if a user with the provided email already exists.
2. Hashes the password with `bcrypt` using the `hash_password` helper.
3. Generates a `uuid4` as the `user_id`.
4. Inserts a new record into the `users` table.
5. Returns the created user (sans password) as `UserResponse` with a `201` status.

**Response example**:
```json
{
  "user_id": "...",
  "email": "user@example.com",
  "full_name": "Jane Doe",
  "created_at": "2026-03-07T12:34:56.789Z"
}
```

### `POST /login`
Authenticates a user and returns a JWT access token.

**Request body**:
```json
{
  "email": "user@example.com",
  "password": "secret"
}
```

**Behavior**:
1. Queries the `users` table by email.
2. Verifies the password with `verify_password`, which compares the provided password against the stored hash using `bcrypt`.
3. If credentials are valid, generates a JWT via `create_access_token`. The token payload includes `sub` (user_id), `email`, and `full_name`, and it expires according to `ACCESS_TOKEN_EXPIRE_MINUTES`.
4. Returns a `TokenResponse` with the token, type, and expiration (in seconds).

**Response example**:
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### `POST /verify`
Utility endpoint to validate a JWT and return the decoded user info.

This endpoint is **not** typically called by end users directly. It exists to support other services or client-side logic that needs to confirm whether a token is still good before performing more expensive operations.

**Who calls it?**
- **Frontend applications** may hit `/verify` on startup or periodically, using the token stored in local storage, to decide if the user should stay logged in or be redirected to login again.
- **Other back-end services** (e.g. booking, payment) can forward tokens to auth’s `/verify` when implementing proxy‑style validation instead of decoding the JWT themselves. This centralizes token validation logic and keeps services decoupled.

**When & why?**:
1. **User logs in** via `POST /login` and receives an access token.
2. The **client stores** the token (e.g. in memory, `localStorage`, or a cookie).
3. Before performing an action that requires authentication, the client may call `/verify`:
   - If the response returns `valid: true`, the client proceeds to call the protected API (booking, etc.).
   - If the token is invalid or expired (`401`), the client knows it must prompt the user to re‑authenticate or obtain a new token.
4. For services that consume the token, they can optionally forward the token to `/verify` as a safeguard or audit step; the auth service will respond with the decoded payload or reject it. This is helpful when services are written in different languages and you want a single source of truth for token rules.
5. After `/verify` confirms the token, the calling code uses the returned payload (`user_id`, `email`, `full_name`) as needed.

**Example client sequence**:
```text
# user opens app
> GET /events  (frontend attaches Bearer token)
  -> gateway forwards with same header
     -> auth gateway hits /verify to ensure token is valid
        -> returns {valid: true, user_id: ...}
  -> booking service processes request using user_id
```

**Request**:
- Method: `POST`
- Headers: `Authorization: Bearer <token>`
- Body: *none*

**Behavior**:
1. Protected by the `get_current_user` dependency which reads the bearer token and passes it to `decode_token`.
2. `decode_token` verifies signature, expiration, and returns the payload or raises a `401` error.
3. `get_current_user` ensures the payload contains a `sub` (user ID) and returns the payload.
4. The endpoint then responds with a JSON object built from that payload.

**Successful response example**:
```json
{
  "valid": true,
  "user_id": "123e4567-e89b-12d3-a456-426614174000",
  "email": "user@example.com",
  "full_name": "Jane Doe"
}
```

**Error responses**:
- `401 Unauthorized` if the token is missing, expired, or invalid.
- The error body mirrors FastAPI’s default `detail` message from the raised `HTTPException`.

### `GET /health`
Simple health check returning `{"status": "healthy"}`.

### Protected routes & dependencies
The `security` dependency (`HTTPBearer`) and helper `get_current_user` are used to guard any future endpoints. `get_current_user`:

1. Reads the `Authorization` header, extracts the bearer token.
2. Calls `decode_token` which verifies signature and exp with PyJWT.
3. Raises `401` errors on invalid/expired tokens.
4. Returns the token payload (including `sub`, `email`, `full_name`).

Other services (e.g., booking) can include this dependency to ensure requests are authenticated and obtain the current user.

## Notes

- Make sure to change `JWT_SECRET_KEY` in production.
- Database credentials should not be hard-coded or committed.
- CORS is currently allowing all origins; tighten as needed.
