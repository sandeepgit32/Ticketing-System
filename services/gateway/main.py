import os
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ==================== PLTG Stack Imports ====================
# Gateway is the entry point for all requests and should:
# 1. Generate/extract trace ID (for distributed tracing)
# 2. Propagate trace ID to all downstream services
# 3. Collect metrics on request routing
import sys

sys.path.insert(0, "/app/../common")
from logging_config import setup_logging, get_logger, set_trace_id, get_trace_id
from tracing_config import setup_tracing
from prometheus_client import make_asgi_app, Counter, Histogram

# Initialize structured logging (all logs will be JSON with trace IDs)
setup_logging(service_name="gateway", log_level="INFO")
logger = get_logger(__name__)

# Initialize distributed tracing to Tempo
setup_tracing(service_name="gateway", tempo_host="tempo", environment="development")

# Define custom metrics for API Gateway routing
request_routed_total = Counter(
    name="gateway_requests_routed_total",
    documentation="Total requests routed to downstream services",
    labelnames=["service", "endpoint", "status"],
)

request_routing_latency_seconds = Histogram(
    name="gateway_routing_latency_seconds",
    documentation="Time spent routing request to downstream service (seconds)",
    labelnames=["service"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


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
AUTH_SERVICE_URL = required_env("AUTH_SERVICE_URL")
BOOKING_SERVICE_URL = required_env("BOOKING_SERVICE_URL")
BOOKING_STATUS_SERVICE_URL = required_env("BOOKING_STATUS_SERVICE_URL")
PAYMENT_SERVICE_URL = required_env("PAYMENT_SERVICE_URL")

# For browser-based frontend, set explicit CORS origin(s). Example: http://localhost:5173,http://localhost:5174
FRONTEND_ORIGINS = required_env(
    "FRONTEND_ORIGINS", cast=lambda v: [o.strip() for o in v.split(",") if o.strip()]
)

app = FastAPI(title="API Gateway", version="1.0.0")

# ==================== Mount Prometheus Metrics Endpoint ====================
# Prometheus scrapes /metrics endpoint every 15 seconds
# Exposes all HTTP metrics and custom routing metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ==================== Trace ID Middleware ====================
# This middleware extracts or generates a trace ID for each request
# The trace ID enables end-to-end request correlation across all services
@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """
    Extract or generate X-Trace-ID header for distributed tracing.

    Purpose:
    - Creates a unique trace ID for each request
    - Extracts trace ID from frontend if already present (browser tracing)
    - Stores trace ID in thread-local context for logging correlation
    - Propagates trace ID to all downstream services

    The trace ID format is a UUID (36 chars).
    Prometheus and Tempo use this to correlate metrics, logs, and traces.
    """
    # Check if trace ID already exists in request headers (from frontend or previous service)
    trace_id = request.headers.get("X-Trace-ID") or request.headers.get("x-trace-id")

    # If no trace ID, generate one
    if not trace_id:
        trace_id = str(uuid4())
        logger.debug(f"Generated new trace ID: {trace_id}")

    # Store trace ID in thread-local context for use in logging throughout this request
    set_trace_id(trace_id)

    # Call the actual endpoint
    response = await call_next(request)

    # Add trace ID to response headers so client can correlate
    response.headers["X-Trace-ID"] = trace_id

    return response


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """
    Verify JWT token with auth service for protected routes.

    Propagates trace ID to auth service for request correlation.
    """
    if not credentials:
        return None

    try:
        async with httpx.AsyncClient() as client:
            # ==================== Trace Context Propagation ====================
            # Include X-Trace-ID header to correlate this call with the original request
            # This allows distributed tracing to show the complete flow: gateway → auth
            trace_id = get_trace_id()

            response = await client.post(
                f"{AUTH_SERVICE_URL}/verify",
                headers={
                    "Authorization": f"Bearer {credentials.credentials}",
                    "X-Trace-ID": trace_id,  # Propagate trace ID
                },
            )
            if response.status_code == 200:
                return response.json()
            return None
    except httpx.RequestError:
        return None


async def proxy_request(
    request: Request,
    target_url: str,
    user_info: dict = None,
    preserve_authorization: bool = False,
):
    """
    Proxy request to target service.

    Responsibility:
    - Forward request to downstream service
    - Propagate trace ID for distributed tracing
    - Forward user info from JWT verification
    - Measure routing latency
    """
    try:
        # Prepare headers
        headers = dict(request.headers)
        headers.pop("host", None)  # Remove host header
        if not preserve_authorization:
            headers.pop("authorization", None)
        # Strip JWT; downstream services use X-User-Email
        # Strip any client-supplied X-User-Email to prevent spoofing;
        # the header is only set below from the gateway-verified token.
        headers.pop("x-user-email", None)
        headers.pop("x-user-role", None)

        # ==================== Trace Context Propagation ====================
        # Ensure X-Trace-ID is included in all downstream requests
        # This enables Tempo to correlate spans across service boundaries
        trace_id = get_trace_id()
        headers["X-Trace-ID"] = trace_id

        # Add user info if authenticated
        if user_info:
            headers["X-User-Email"] = user_info.get("email", "")
            headers["X-User-Role"] = user_info.get("role", "User")

        # Get request body
        body = await request.body()

        # Make request to target service
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=request.query_params,
            )

            # Normalize response content and forward headers safely
            outgoing_headers = {
                k: v
                for k, v in response.headers.items()
                if k.lower()
                not in [
                    "content-length",
                    "transfer-encoding",
                    "content-encoding",
                    "connection",
                ]
            }

            content = response.content
            media_type = response.headers.get("content-type")

            return Response(
                content=content,
                status_code=response.status_code,
                headers=outgoing_headers,
                media_type=media_type,
            )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unavailable: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gateway error: {str(e)}",
        )


# ============== Health & Info ==============


@app.get("/")
async def root():
    """API Gateway information"""
    return {
        "service": "API Gateway",
        "version": "1.0.0",
        "endpoints": {
            "auth": "/auth/*",
            "booking": "/booking/*",
            "status": "/status/*",
            "payment": "/payment/*",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "service": "api-gateway"}


# ============== Auth Service Routes ==============


@app.post("/auth/register")
async def auth_register(request: Request):
    """Register a new user"""
    target_url = f"{AUTH_SERVICE_URL}/register"
    return await proxy_request(request, target_url)


@app.post("/auth/login")
async def auth_login(request: Request):
    """Login and get JWT token"""
    target_url = f"{AUTH_SERVICE_URL}/login"
    return await proxy_request(request, target_url)


@app.post("/auth/verify")
async def auth_verify(request: Request):
    """Verify JWT token"""
    target_url = f"{AUTH_SERVICE_URL}/verify"
    return await proxy_request(request, target_url, preserve_authorization=True)


# ============== Booking Service Routes ==============


@app.get("/booking/venues")
async def list_venues(request: Request):
    """List all venues"""
    target_url = f"{BOOKING_SERVICE_URL}/venues"
    return await proxy_request(request, target_url)


@app.get("/booking/venues/{venue_name}")
async def get_venue(venue_name: str, request: Request):
    """Get venue details"""
    target_url = f"{BOOKING_SERVICE_URL}/venues/{venue_name}"
    return await proxy_request(request, target_url)


@app.get("/booking/events")
async def list_events(request: Request):
    """List all events"""
    target_url = f"{BOOKING_SERVICE_URL}/events"
    return await proxy_request(request, target_url)


@app.get("/booking/events/{event_id}")
async def get_event(event_id: str, request: Request):
    """Get event details"""
    target_url = f"{BOOKING_SERVICE_URL}/events/{event_id}"
    return await proxy_request(request, target_url)


@app.post("/booking/events")
async def create_event(request: Request, user_info: dict = Depends(verify_token)):
    """Create a new event (requires authentication)"""
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    if user_info.get("role") != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )

    target_url = f"{BOOKING_SERVICE_URL}/events"
    return await proxy_request(request, target_url, user_info=user_info)


@app.get("/booking/events/{event_id}/close")
async def close_event(
    event_id: str, request: Request, user_info: dict = Depends(verify_token)
):
    """Close an event (requires authentication)"""
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    if user_info.get("role") != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )

    target_url = f"{BOOKING_SERVICE_URL}/events/{event_id}/close"
    return await proxy_request(request, target_url, user_info=user_info)


@app.post("/booking/bookings/reserve")
async def reserve_seats(request: Request, user_info: dict = Depends(verify_token)):
    """Reserve seats (requires authentication)"""
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    target_url = f"{BOOKING_SERVICE_URL}/bookings/reserve"
    return await proxy_request(request, target_url, user_info=user_info)


@app.post("/booking/payments/capture")
async def capture_payment(request: Request, user_info: dict = Depends(verify_token)):
    """Capture payment (requires authentication)"""
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    target_url = f"{BOOKING_SERVICE_URL}/payments/capture"
    return await proxy_request(request, target_url, user_info=user_info)


@app.post("/booking/payments/webhook")
async def payment_webhook(request: Request):
    """Payment webhook endpoint"""
    target_url = f"{BOOKING_SERVICE_URL}/payments/webhook"
    return await proxy_request(request, target_url)


# ============== Booking Status Service Routes ==============


@app.get("/status/bookings/{booking_id}")
async def get_booking_details(
    booking_id: str, request: Request, user_info: dict = Depends(verify_token)
):
    """Get booking details (requires authentication)"""
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    target_url = f"{BOOKING_STATUS_SERVICE_URL}/bookings/{booking_id}"
    return await proxy_request(request, target_url, user_info=user_info)


@app.get("/status/user/bookings")
async def get_user_bookings(request: Request, user_info: dict = Depends(verify_token)):
    """Get user bookings (requires authentication)"""
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    target_url = f"{BOOKING_STATUS_SERVICE_URL}/user/bookings"
    return await proxy_request(request, target_url, user_info=user_info)


# ============== Payment Service Routes (for testing) ==============


@app.post("/payment/intents")
async def create_payment_intent(request: Request):
    """Create payment intent"""
    target_url = f"{PAYMENT_SERVICE_URL}/payments/intents"
    return await proxy_request(request, target_url)


@app.get("/payment/intents/{intent_id}/confirm")
async def confirm_payment_intent(intent_id: str, request: Request):
    """Confirm payment intent"""
    target_url = f"{PAYMENT_SERVICE_URL}/payments/intents/{intent_id}/confirm"
    return await proxy_request(request, target_url)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
