import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

# import mysql.connector
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from mysql.connector import pooling

# In the Docker container we start the service with `uvicorn main:app`
# from the `/app` working directory. the module is therefore imported as
# top‑level `main` and a simple `from schemas import …` works reliably.
# keeping this explicit avoids any relative‑import drama inside the container.
from schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse


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
SECRET_KEY = required_env("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = required_env("ACCESS_TOKEN_EXPIRE_MINUTES", cast=int)

MYSQL_HOST = required_env("MYSQL_HOST")
MYSQL_PORT = required_env("MYSQL_PORT", int)
MYSQL_USER = required_env("MYSQL_USER")
MYSQL_PASSWORD = required_env("MYSQL_PASSWORD")
MYSQL_DATABASE = required_env("MYSQL_DATABASE")
DEFAULT_ADMIN_EMAIL = required_env("DEFAULT_ADMIN_EMAIL")
DEFAULT_ADMIN_PASSWORD = required_env("DEFAULT_ADMIN_PASSWORD")
DEFAULT_ADMIN_FULL_NAME = os.environ.get("DEFAULT_ADMIN_FULL_NAME", "System Admin")

app = FastAPI(title="Auth Service")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()
db_pool = None


def get_db_connection():
    """
    Acquire a database connection from the global connection pool.

    This helper is called throughout the code whenever a new MySQL
    connection is needed. The pool itself is initialized during
    application startup (`startup_event`), and if the pool is not yet
    ready this call will raise an exception.

    Returns:
        mysql.connector.connection.MySQLConnection: a connection object.
    """
    return db_pool.get_connection()


def seed_default_admin_user() -> None:
    """Create or overwrite the default admin user from environment values."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        import uuid

        admin_user_id = str(uuid.uuid4())
        admin_password_hash = hash_password(DEFAULT_ADMIN_PASSWORD)

        cursor.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, user_role)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                password_hash = VALUES(password_hash),
                full_name = VALUES(full_name),
                user_role = VALUES(user_role),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                admin_user_id,
                DEFAULT_ADMIN_EMAIL,
                admin_password_hash,
                DEFAULT_ADMIN_FULL_NAME,
                "Admin",
            ),
        )
        conn.commit()
        print(f"Ensured default admin user exists for {DEFAULT_ADMIN_EMAIL}")
    except Exception as e:
        print(f"Error seeding default admin user: {e}")
    finally:
        cursor.close()
        conn.close()


@app.on_event("startup")
async def startup_event():
    """
    FastAPI startup event handler.

    This coroutine is executed when the application starts. It attempts to
    establish a MySQL connection pool (stored in the module-wide `db_pool`)
    using environment variables defined at top of the file. Because the
    database service may not be immediately available (e.g. when running
    in Docker), the routine retries `max_retries` times with a delay
    between attempts. If a connection cannot be obtained after all retries,
    the exception propagates and prevents the app from starting.
    """
    global db_pool
    # Wait for MySQL to be ready
    import time

    max_retries = 30
    for i in range(max_retries):
        try:
            db_pool = pooling.MySQLConnectionPool(
                pool_name="auth_pool",
                pool_size=5,
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
            )
            print("Connected to database")
            seed_default_admin_user()
            break
        except Exception as e:
            if i < max_retries - 1:
                print(f"Waiting for database... ({i + 1}/{max_retries})")
                time.sleep(2)
            else:
                raise Exception(f"Could not connect to database: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """
    FastAPI shutdown event handler.

    Called during application teardown. The MySQL connection pool doesn't
    require explicit cleanup; connections are closed automatically, so this
    is currently a no-op but provided for future resource cleanup needs.
    """
    # Pool connections will be closed automatically
    pass


def hash_password(password: str) -> str:
    """
    Produce a bcrypt hash of a plaintext password.

    Args:
        password (str): The user's plaintext password.

    Returns:
        str: A UTF-8 decoded bcrypt hash suitable for storage in the
             database. The generated hash includes a random salt and
             work factor.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check a plaintext password against a stored bcrypt hash.

    Args:
        plain_password (str): Password provided by the user.
        hashed_password (str): The hash retrieved from the database.

    Returns:
        bool: True if the passwords match, False otherwise.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """
    Build and sign a JWT access token using HS256.

    Args:
        data (dict): Claims to include in the token payload (e.g. sub, email, role).
        expires_delta (Optional[timedelta]): Optional expiration delta. If
            omitted the global `ACCESS_TOKEN_EXPIRE_MINUTES` is used.

    Returns:
        str: The encoded JWT as a string.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT, raising HTTPExceptions on failure.

    Args:
        token (str): The JWT string from the Authorization header.

    Returns:
        dict: The decoded token payload.

    Raises:
        HTTPException: 401 Unauthorized if the token is expired or invalid.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    FastAPI dependency that extracts and verifies a bearer JWT.

    This function is injected into route handlers via `Depends`. It reads
    the `Authorization` header (handled by HTTPBearer), obtains the raw token,
    and uses `decode_token` to validate it. The returned payload may then be
    used by the endpoint to identify the current user.

    Raises:
        HTTPException: 401 Unauthorized if the token payload lacks `sub`
            or if `decode_token` failed.
    """
    token = credentials.credentials
    payload = decode_token(token)

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        )
    return payload


@app.post("/register", response_model=UserResponse, status_code=201)
async def register(req: RegisterRequest):
    """
    Register a new user in the system.

    Args:
        req (RegisterRequest): Registration request containing email, password, and full_name.

    Returns:
        UserResponse: A response object containing the newly created user's information including:
            - user_id: Unique identifier for the user (UUID format)
            - email: User's email address
            - full_name: User's full name
            - created_at: ISO format timestamp of user creation

    Raises:
        HTTPException: With status code 409 CONFLICT if the email is already registered in the system.

    Note:
        - Password is hashed using hash_password() before storage
        - Database connection is automatically closed in the finally block
        - dictionary=True parameter in cursor() returns results as dictionaries instead of tuples,
          allowing access to columns by name (e.g., user["email"]) rather than by index (e.g., user[0])
    """
    import uuid

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Check if user already exists
        cursor.execute("SELECT user_id FROM users WHERE email = %s", (req.email,))
        if cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )

        # Create new user
        user_id = str(uuid.uuid4())
        password_hash = hash_password(req.password)

        cursor.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name, user_role) VALUES (%s, %s, %s, %s, %s)",
            (user_id, req.email, password_hash, req.full_name, "User"),
        )
        conn.commit()

        # Fetch the created user
        cursor.execute(
            "SELECT user_id, email, full_name, user_role, created_at FROM users WHERE user_id = %s",
            (user_id,),
        )
        user = cursor.fetchone()

        return UserResponse(
            user_id=user["user_id"],
            email=user["email"],
            full_name=user["full_name"],
            role=user.get("user_role", "User"),
            created_at=user["created_at"].isoformat(),
        )
    finally:
        cursor.close()
        conn.close()


@app.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """
    Authenticate a user and issue a JWT access token.

    Args:
        req (LoginRequest): Contains `email` and `password`.

    Returns:
        TokenResponse: Contains `access_token`, `token_type`, and
                       `expires_in` (seconds).

    Raises:
        HTTPException: 401 Unauthorized for invalid credentials.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Find user
        cursor.execute(
            "SELECT user_id, email, password_hash, full_name, user_role FROM users WHERE email = %s",
            (req.email,),
        )
        user = cursor.fetchone()

        if not user or not verify_password(req.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )

        # Create access token
        access_token_expires_at = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": user["user_id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "role": user.get("user_role", "User"),
            },
            expires_delta=access_token_expires_at,
        )

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
    finally:
        cursor.close()
        conn.close()


@app.post("/verify")
async def verify_token(current_user: dict = Depends(get_current_user)):
    """
    Endpoint used to validate an incoming JWT and return its payload.

    When the endpoint is invoked:
    1. FastAPI executes the dependency `get_current_user` before calling this
       function. That dependency reads the `Authorization` header via the
       `HTTPBearer` security scheme, extracts the bearer token and passes it
       to `decode_token()`.
    2. `decode_token()` verifies the token signature and expiration. If the
       token is missing, expired or invalid, an HTTPException with status 401
       will be raised and this handler will **not** execute.
    3. On success, `get_current_user` returns the decoded payload dictionary
       which is injected into the `current_user` parameter below.
    4. This handler simply formats that payload into a JSON response.

    No request body is read; only the Authorization header is used.

    Args:
        current_user (dict): Decoded token payload supplied by the dependency.

    Returns:
        dict: Keys `valid`, `user_id`, `email`, `full_name` for the client.
    """
    return {
        "valid": True,
        "user_id": current_user.get("sub"),
        "email": current_user.get("email"),
        "full_name": current_user.get("full_name"),
        "role": current_user.get("role", "User"),
    }


@app.get("/health")
async def health():
    """
    Simple health check endpoint.

    Returns a 200 status with a JSON object indicating the service is running.
    """
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
