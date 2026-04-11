"""
Prometheus metrics configuration for PLTG stack.

This module defines Prometheus metrics for the ticketing system. Metrics are
collected by Prometheus (scrapes every 15 seconds) and visualized in Grafana.

Metric Types:
    - Counter: Monotonically increasing values (e.g., total requests)
    - Gauge: Can go up or down (e.g., current queue size)
    - Histogram: Distributes values into buckets (e.g., request latency)
    - Summary: Like histogram but uses quantiles instead of buckets

Label Cardinality:
    Be careful with labels - too many unique combinations = high memory usage.
    Example: {method: GET|POST, endpoint: /api/auth/..., status: 200|4xx|5xx}
    If you have 3 methods × 10 endpoints × 3 statuses = 90 metric series
    But if you add user_id as label: 90 × 1000 users = 90k+ series (BAD!)

Usage:
    from services.common.metrics_config import (
        http_requests_total,
        http_request_duration_seconds,
        setup_prometheus_metrics
    )

    # Initialize metrics (call in main.py)
    setup_prometheus_metrics()

    # Increment counter
    http_requests_total.labels(method="GET", status=200).inc()

    # Record latency (duration in seconds)
    with http_request_duration_seconds.labels(endpoint="/api/booking/reserve").time():
        do_something()

Reference: https://prometheus.io/docs/concepts/metric_types/
Reference: https://github.com/prometheus/client_python
"""

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Summary,
    Info,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
    start_http_server,
)
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ==================== HTTP / API Metrics ====================
# These track API traffic patterns and performance

# Counter: Total HTTP requests received by service (all endpoints, methods, statuses)
# Labels: job (service name), method (GET/POST/etc), endpoint, status (200/4xx/5xx)
# Use Case: Calculate request rate per endpoint, identify error rate
http_requests_total = Counter(
    name="http_requests_total",
    documentation="Total HTTP requests received by the service",
    labelnames=["method", "endpoint", "status"],
)

# Histogram: HTTP request duration (latency) in seconds
# Labels: method, endpoint
# Buckets: 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0 seconds
# Use Case: Identify slow endpoints, calculate P95/P99 latency
http_request_duration_seconds = Histogram(
    name="http_request_duration_seconds",
    documentation="HTTP request duration in seconds",
    labelnames=["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Gauge: Current HTTP requests in progress (inflight)
# Labels: method, endpoint
# Use Case: Detect if requests are queuing, identify bottlenecks
http_requests_in_progress = Gauge(
    name="http_requests_in_progress",
    documentation="Number of HTTP requests currently being processed",
    labelnames=["method", "endpoint"],
)

# Counter: HTTP request errors (exceptions, validation failures, etc.)
# Labels: method, endpoint, error_type (ValidationError, DatabaseError, etc.)
# Use Case: Track error types and identify patterns
http_request_errors_total = Counter(
    name="http_request_errors_total",
    documentation="Total HTTP request errors by type",
    labelnames=["method", "endpoint", "error_type"],
)

# ==================== Authentication Metrics ====================
# These track authentication events and performance

# Counter: Successful user logins
# Labels: method (password, oauth, etc.)
# Use Case: Track user login trends, identify unusual patterns
auth_login_total = Counter(
    name="auth_login_total",
    documentation="Total successful user logins",
    labelnames=["method"],
)

# Counter: Failed login attempts
# Labels: reason (invalid_password, user_not_found, account_locked)
# Use Case: Detect brute force attacks, identify common error patterns
auth_login_failed_total = Counter(
    name="auth_login_failed_total",
    documentation="Total failed login attempts",
    labelnames=["reason"],
)

# Counter: New user registrations
# Use Case: Track growth rate, identify registration issues
auth_registration_total = Counter(
    name="auth_registration_total", documentation="Total new user registrations"
)

# Histogram: JWT token generation latency
# Use Case: Detect slower crypto operations, identify performance degradation
auth_token_generation_seconds = Histogram(
    name="auth_token_generation_seconds",
    documentation="JWT token generation duration in seconds",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1),
)

# ==================== Booking Service Metrics ====================
# These track seat reservations and booking flow

# Counter: Successful seat reservations
# Labels: venue, event_id
# Use Case: Track booking volume per event/venue
booking_reserved_total = Counter(
    name="booking_reserved_total",
    documentation="Total successful seat reservations",
    labelnames=["venue"],
)

# Counter: Failed reservation attempts
# Labels: reason (no_seats_available, invalid_seats, event_closed)
# Use Case: Identify common blocking issues for users
booking_reservation_failed_total = Counter(
    name="booking_reservation_failed_total",
    documentation="Total failed reservation attempts",
    labelnames=["reason"],
)

# Gauge: Currently available seats per event
# Labels: event_id, venue
# Use Case: Monitor seat availability, predict sell-out times
booking_available_seats = Gauge(
    name="booking_available_seats",
    documentation="Number of available seats in the system",
    labelnames=["venue"],
)

# Gauge: Active (non-expired) reservations
# Use Case: Monitor active bookings, calculate conversion rate
booking_active_reservations = Gauge(
    name="booking_active_reservations",
    documentation="Number of active (non-expired) seat reservations",
)

# Histogram: Seat reservation latency
# Use Case: Identify bottlenecks in Redis bitmap operations or database writes
booking_reservation_latency_seconds = Histogram(
    name="booking_reservation_latency_seconds",
    documentation="Seat reservation duration in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ==================== Payment Metrics ====================
# These track payment processing

# Counter: Payment capture requests
# Labels: None (capture all attempts, regardless of success)
# Use Case: Track payment volume and success rate
payment_capture_total = Counter(
    name="payment_capture_total", documentation="Total payment capture attempts"
)

# Counter: Successful payments
# Use Case: Track successful transaction volume
payment_capture_succeeded_total = Counter(
    name="payment_capture_succeeded_total",
    documentation="Total successful payment captures",
)

# Counter: Failed payments
# Labels: reason (declined, timeout, provider_error)
# Use Case: Identify payment processing issues
payment_capture_failed_total = Counter(
    name="payment_capture_failed_total",
    documentation="Total failed payment captures",
    labelnames=["reason"],
)

# Histogram: Payment processing latency
# Use Case: Identify slow payment provider calls
payment_capture_latency_seconds = Histogram(
    name="payment_capture_latency_seconds",
    documentation="Payment capture duration in seconds",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

# ==================== Notification/Queue Metrics ====================
# These track async job processing

# Gauge: Current queue depth (messages waiting to be processed)
# Labels: queue_name (notifications, jobs, etc.)
# Use Case: Detect backlog, identify slow consumers
queue_depth = Gauge(
    name="queue_depth",
    documentation="Number of messages in job queue",
    labelnames=["queue_name"],
)

# Counter: Messages processed from queue
# Labels: queue_name, status (success, failed)
# Use Case: Track queue throughput and error rate
queue_messages_processed_total = Counter(
    name="queue_messages_processed_total",
    documentation="Total messages processed from queue",
    labelnames=["queue_name", "status"],
)

# Histogram: Job processing latency
# Use Case: Identify slow job types, queue processing bottlenecks
queue_processing_latency_seconds = Histogram(
    name="queue_processing_latency_seconds",
    documentation="Job processing duration from queue (seconds)",
    labelnames=["queue_name"],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0),
)

# ==================== Database Metrics ====================
# These track database operations (if using prometheus MySQL exporter)

# Note: These are typically collected via mysqld_exporter and not created here
# But documented for reference
# Examples:
# - mysql_global_status_threads_connected
# - mysql_global_status_questions (total queries)
# - mysql_slow_queries_total
# - mysql_query_latency_seconds

# ==================== System / Business Metrics ====================
# These track high-level business indicators

# Counter: Completed bookings (payment successful)
# Labels: event_id, venue
# Use Case: Track sales/bookings over time, identify popular events
booking_created_total = Counter(
    name="booking_created_total",
    documentation="Total confirmed bookings (after payment)",
    labelnames=["venue"],
)

# Gauge: Revenue (sum of booking amounts) - NOTE: Use histograms for amounts!
# More accurate: track payment amounts with Summary or Histogram
booking_revenue_total = Counter(
    name="booking_revenue_total",
    documentation="Total revenue from completed bookings (in cents)",
    labelnames=["venue"],
)

# Counter: User registrations (complement to auth_registration_total)
# Use Case: Track new user growth
users_registered_total = Counter(
    name="users_registered_total", documentation="Total user registrations"
)

# Gauge: Active users (logged in within last N hours)
# Computed from login timestamps
active_users = Gauge(
    name="active_users", documentation="Number of users logged in within last hour"
)


def setup_prometheus_metrics(port: int = 8000) -> None:
    """
    Initialize Prometheus metrics collection.

    Call this once at service startup to expose metrics on an HTTP endpoint.
    Prometheus will scrape this endpoint every 15 seconds (configured in prometheus.yml).

    Args:
        port: Port to expose metrics on (should match service port if using
              same server, or different port if separate metrics server)

    Example:
        >>> from fastapi import FastAPI
        >>> from services.common.metrics_config import setup_prometheus_metrics
        >>> app = FastAPI()
        >>>
        >>> if __name__ == "__main__":
        ...     setup_prometheus_metrics(port=8000)
        ...     uvicorn.run(app, host="0.0.0.0", port=8000)

    Side Effects:
        - Creates HTTP endpoint at http://service:port/metrics
        - Prometheus scrape job will call this endpoint every 15s
        - Blocks further setup until metrics endpoint starts (usually immediate)
    """
    try:
        # Note: In practice, we'll use FastAPI integration (PrometheusMiddleware)
        # rather than a separate metrics port. This function is here for reference.
        logger.info(f"Prometheus metrics configured (port={port})")
    except Exception as e:
        logger.error(f"Failed to setup Prometheus metrics: {e}")
        raise


def get_registry() -> CollectorRegistry:
    """
    Get the Prometheus metrics registry.

    The registry maintains all metrics and is used by the metrics exporter.
    Typically not needed as we use the default REGISTRY.

    Returns:
        CollectorRegistry: The default Prometheus registry
    """
    return REGISTRY
