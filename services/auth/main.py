import os
import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import mysql.connector
from mysql.connector import pooling

# Configuration
SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', '60'))

MYSQL_HOST = os.getenv('MYSQL_HOST', 'mysql')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
MYSQL_USER = os.getenv('MYSQL_USER', 'ticketuser')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'ticketpass')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'ticketing')

app = FastAPI(title='Auth Service')

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


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    created_at: str


def get_db_connection():
    """Get a connection from the pool"""
    return db_pool.get_connection()


def init_db():
    """Initialize database tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id VARCHAR(36) PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            full_name VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_email (email)
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
                pool_name="auth_pool",
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


@app.on_event('shutdown')
async def shutdown_event():
    # Pool connections will be closed automatically
    pass


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc)
    })
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Dependency to get current user from JWT token"""
    token = credentials.credentials
    payload = decode_token(token)
    
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    return payload


@app.post('/register', response_model=UserResponse, status_code=201)
async def register(req: RegisterRequest):
    """Register a new user"""
    import uuid
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Check if user already exists
        cursor.execute("SELECT user_id FROM users WHERE email = %s", (req.email,))
        if cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered"
            )
        
        # Create new user
        user_id = str(uuid.uuid4())
        password_hash = hash_password(req.password)
        
        cursor.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, %s, %s)",
            (user_id, req.email, password_hash, req.full_name)
        )
        conn.commit()
        
        # Fetch the created user
        cursor.execute("SELECT user_id, email, full_name, created_at FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        return UserResponse(
            user_id=user['user_id'],
            email=user['email'],
            full_name=user['full_name'],
            created_at=user['created_at'].isoformat()
        )
    finally:
        cursor.close()
        conn.close()


@app.post('/login', response_model=TokenResponse)
async def login(req: LoginRequest):
    """Login and get JWT token"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Find user
        cursor.execute(
            "SELECT user_id, email, password_hash, full_name FROM users WHERE email = %s",
            (req.email,)
        )
        user = cursor.fetchone()
        
        if not user or not verify_password(req.password, user['password_hash']):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password"
            )
        
        # Create access token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": user['user_id'],
                "email": user['email'],
                "full_name": user['full_name']
            },
            expires_delta=access_token_expires
        )
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
    finally:
        cursor.close()
        conn.close()


@app.post('/verify')
async def verify_token(current_user: dict = Depends(get_current_user)):
    """Verify JWT token and return user info"""
    return {
        "valid": True,
        "user_id": current_user.get("sub"),
        "email": current_user.get("email"),
        "full_name": current_user.get("full_name")
    }


@app.get('/health')
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
