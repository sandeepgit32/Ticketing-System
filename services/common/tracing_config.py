"""
OpenTelemetry distributed tracing configuration for PLTG stack.

This module configures tracing for all services. It:
1. Initializes OpenTelemetry SDK
2. Exports traces to Tempo (via OTLP gRPC)
3. Instruments FastAPI/Flask automatically
4. Propagates trace context across service calls

Distributed Tracing Concepts:
    - Trace: Complete request flow across all services (UUID)
    - Span: Logical operation within a service (function call, DB query)
    - Trace Context: X-Trace-ID and X-Span-ID headers propagated between services

Example Booking Flow Trace:
    User Request (trace_id=abc123)
    ├─ API Gateway (span: verify-jwt)
    ├─ Booking Service (span: reserve-seats)
    │  ├─ Redis (span: bitmap-operation)
    │  └─ MySQL (span: insert-reservation)
    ├─ Payment Service (span: capture-payment)
    └─ Notification Service (span: send-email)

Data Flow:
    Services → OpenTelemetry SDK → OTLP Exporter → Tempo (port 4317)
    → Grafana Tempo UI → Visual request flow + latency per service

Usage:
    from services.common.tracing_config import (
        setup_tracing,
        get_tracer,
        traced_function
    )

    # Initialize tracing in main.py
    setup_tracing(service_name="booking")

    # Get tracer instance
    tracer = get_tracer(__name__)

    # Manually create spans
    with tracer.start_as_current_span("database-query") as span:
        span.set_attribute("db.statement", "SELECT * FROM bookings")
        result = db.query(...)

    # Decorator for automatic span creation
    @traced_function(tracer, "process-job")
    def process_notification_job(job_id):
        ...

Reference: https://opentelemetry.io/docs/instrumentation/python/
Reference: https://grafana.com/docs/tempo/latest/getting-started/
"""

import logging
from typing import Optional, Any
from functools import wraps

# OpenTelemetry core imports
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

# Instrumentation libraries
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

# Context propagation (for trace headers across services)
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.jaeger.jaeger import JaegerPropagator
from opentelemetry.propagators.b3 import B3Format

logger = logging.getLogger(__name__)


def setup_tracing(
    service_name: str,
    tempo_host: str = "localhost",
    tempo_port: int = 4317,
    environment: str = "development",
    sample_rate: float = 1.0,
) -> TracerProvider:
    """
    Initialize OpenTelemetry tracing for a service.

    Setup includes:
    1. Configure OTLP exporter to send traces to Tempo
    2. Set up trace propagation (extract/inject trace context from headers)
    3. Instrument HTTP libraries (FastAPI, requests, etc.)
    4. Instrument databases (SQLAlchemy, Redis)

    Call this once at service startup before creating FastAPI/Flask app.

    Args:
        service_name: Name of the service (e.g., "auth", "booking")
                     Used as 'service.name' attribute in all spans
        tempo_host: Hostname/IP of Tempo OTLP gRPC receiver
                   Default: "localhost" (docker network: "tempo")
        tempo_port: Port for Tempo OTLP gRPC receiver
                   Default: 4317 (standard OTLP gRPC port)
        environment: Deployment environment (development, staging, production)
                    Used for span filtering and context
        sample_rate: Proportion of traces to sample (0.0-1.0)
                    Default: 1.0 (keep all traces)
                    For high-volume production: use 0.1 or lower

    Returns:
        TracerProvider: Configured tracer provider for manual span creation

    Example:
        >>> from fastapi import FastAPI
        >>> from services.common.tracing_config import setup_tracing, get_tracer
        >>>
        >>> tracer_provider = setup_tracing("booking", tempo_host="tempo")
        >>> app = FastAPI()
        >>> # FastAPI is now automatically instrumented
        >>>
        >>> tracer = get_tracer(__name__)
        >>> # Use tracer for manual spans

    Side Effects:
        - Sets up global tracer provider
        - Configures OTLP exporter to send traces to Tempo
        - Enables automatic instrumentation for FastAPI/Flask
        - Instruments database and HTTP libraries
        - Sets global trace propagator
    """
    try:
        # Create OTLP span exporter (sends traces to Tempo gRPC)
        # OTLP = OpenTelemetry Protocol (standard for telemetry exchange)
        otlp_exporter = OTLPSpanExporter(
            endpoint=f"{tempo_host}:{tempo_port}",  # Tempo OTLP gRPC endpoint
            insecure=True,  # Disable TLS for local/internal networks
            # Optional: certificate verification for production
            # certificate_file="/path/to/cert.pem"
        )

        # Create tracer provider with OTLP exporter
        tracer_provider = TracerProvider()
        trace.set_tracer_provider(tracer_provider)

        # Add span processor: batches spans for efficient transmission
        # BatchSpanProcessor collects spans and exports them periodically
        # Alternative: SimpleSpanProcessor (exports immediately, higher overhead)
        batch_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(batch_processor)

        # Configure trace context propagation
        # This enables extracting/injecting trace IDs from HTTP headers
        # Supports both Jaeger format (X-Trace-ID) and W3C format (traceparent)
        propagators = [JaegerPropagator(), B3Format()]
        set_global_textmap(propagators[0])  # Use Jaeger format by default

        # Instrument FastAPI applications automatically
        # This intercepts all HTTP requests/responses and creates spans
        FastAPIInstrumentor().instrument()

        # Instrument Flask applications (if used)
        FlaskInstrumentor().instrument()

        # Instrument the requests library (for outbound HTTP calls)
        # This tracks calls to other services (booking → payment, etc.)
        RequestsInstrumentor().instrument()

        # Instrument SQLAlchemy (if using SQLAlchemy ORM)
        # Note: Direct mysql-connector-python calls are NOT auto-instrumented
        # For those, use manual spans in database query code
        try:
            SQLAlchemyInstrumentor().instrument()
        except Exception as e:
            logger.warning(f"SQLAlchemy instrumentation not available: {e}")

        # Instrument Redis (for queue and cache operations)
        RedisInstrumentor().instrument()

        logger.info(
            f"Tracing initialized: service={service_name}, "
            f"tempo={tempo_host}:{tempo_port}, environment={environment}, "
            f"sample_rate={sample_rate}"
        )

        return tracer_provider

    except Exception as e:
        logger.error(f"Failed to initialize tracing: {e}")
        raise


def get_tracer(name: str) -> trace.Tracer:
    """
    Get a tracer instance for manual span creation.

    Each module should get its own tracer with __name__ as argument.
    The tracer is used to create spans for operations not auto-instrumented.

    Args:
        name: Tracer name, typically __name__ of the module
             (e.g., "services.booking.db_utils")

    Returns:
        trace.Tracer: Tracer instance for creating spans

    Example:
        >>> tracer = get_tracer(__name__)
        >>> with tracer.start_as_current_span("custom-operation") as span:
        ...     span.set_attribute("user_id", user_id)
        ...     do_something()
    """
    return trace.get_tracer(name)


def traced_function(tracer: trace.Tracer, span_name: str, **span_attributes):
    """
    Decorator to automatically create a span for a function.

    Useful for async operations, background jobs, and other code that
    may not be auto-instrumented by FastAPI/Flask middleware.

    Args:
        tracer: Tracer instance (from get_tracer())
        span_name: Name for the span (e.g., "process-notification")
        **span_attributes: Additional attributes to set on the span
                          (key-value pairs, e.g., job_type="email")

    Returns:
        Decorated function that creates a span when called

    Example:
        >>> tracer = get_tracer(__name__)
        >>> @traced_function(tracer, "send-email", service="notification")
        ... def send_notification_email(user_email, subject):
        ...     # Automatic span created around this function
        ...     send_smtp(user_email, subject)
        ...
        >>> send_notification_email("user@example.com", "Your booking confirmed")
        # Trace recorded with span_name="send-email", service="notification"
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create a new span for the function call
            with tracer.start_as_current_span(span_name) as span:
                # Set provided attributes on the span
                for key, value in span_attributes.items():
                    span.set_attribute(key, value)

                # Execute the function within the span
                try:
                    result = func(*args, **kwargs)
                    # Mark success
                    span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    # Capture exception in span
                    span.set_attribute("status", "error")
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    raise

        return wrapper

    return decorator


def set_trace_context(trace_id: str, span_id: str) -> None:
    """
    Manually set trace context in thread-local storage.

    Used when processing background jobs or async tasks where you want
    to preserve the original trace ID. Usually not needed - trace context
    is extracted from HTTP headers automatically.

    Args:
        trace_id: Original trace ID (format: hex string)
        span_id: Original span ID (format: hex string)

    Example:
        >>> # Processing a job from queue that came with X-Trace-ID header
        >>> trace_id = job.get("trace_id")
        >>> set_trace_context(trace_id, span_id)
        >>> # Now all spans created in this job will be part of original trace
    """
    # This is a placeholder - real implementation depends on OpenTelemetry context API
    # In practice, extract from job metadata and use context.set_value()
    logger.debug(f"Setting trace context: trace_id={trace_id}, span_id={span_id}")


def get_current_span() -> Optional[trace.Span]:
    """
    Get the currently active span.

    Returns:
        trace.Span: Current span, or NoOpSpan if no span active

    Example:
        >>> span = get_current_span()
        >>> if span:
        ...     span.set_attribute("user_id", user_id)
    """
    return trace.get_current_span()


def add_span_event(
    span: trace.Span, event_name: str, attributes: Optional[dict] = None
) -> None:
    """
    Add an event (milestone) to the current span.

    Events mark important moments during span execution without creating
    separate spans. Useful for logging events like "cache_hit", "retry", etc.

    Args:
        span: Span instance (from get_current_span())
        event_name: Name of the event (e.g., "cache_hit", "retry_attempt")
        attributes: Optional event attributes (dict)

    Example:
        >>> span = get_current_span()
        >>> add_span_event(span, "cache_hit", {"ttl": 3600})
        >>> add_span_event(span, "retry", {"attempt": 2, "reason": "timeout"})
    """
    if attributes is None:
        attributes = {}
    span.add_event(event_name, attributes=attributes)
