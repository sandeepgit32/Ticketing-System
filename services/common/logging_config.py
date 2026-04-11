"""
Structured logging configuration for PLTG stack integration.

This module provides JSON-formatted logging with trace ID correlation for all services.
All logs are output in JSON format to stdout, which can be ingested by Loki for
centralized log aggregation and querying.

Log Format:
    {
        "timestamp": "2026-02-07T12:00:00Z",
        "level": "INFO",
        "service": "auth",
        "trace_id": "550e8400-e29b-41d4-a716-446655440000",
        "message": "User registered",
        "user_id": "user123",
        "extra_field": "additional context"
    }

Trace ID Correlation:
    - Trace ID is generated in the API Gateway for each request
    - Propagated to all downstream services via X-Trace-ID header
    - Included in all log entries for request correlation
    - Used to trace a request's entire flow: API → Auth → Booking → Payment

Usage:
    from services.common.logging_config import setup_logging, get_logger

    # Initialize logging (call once at service startup)
    setup_logging(service_name="auth")

    # Get logger instance
    logger = get_logger(__name__)

    # Log with context
    logger.info("User registered", extra={"user_id": user_id, "email": email})

    # Log errors
    try:
        do_something()
    except Exception as e:
        logger.exception("Failed to do something", extra={"error_details": str(e)})

Reference: https://docs.python.org/3/library/logging.html
Reference: https://grafana.com/docs/loki/latest/logql/
"""

import json
import logging
import sys
from contextlib import contextmanager
from typing import Any, Dict, Optional
from datetime import datetime
from uuid import uuid4

# Thread-local storage for context (trace ID, user ID, etc.)
import threading

_context = threading.local()


def get_trace_id() -> str:
    """
    Get the current trace ID from thread-local context.

    Returns the trace ID set by set_trace_id(), or a new UUID if not set.
    This ensures every log entry has a trace ID for correlation.

    Returns:
        str: Current trace ID (36-character UUID)

    Example:
        >>> trace_id = get_trace_id()
        >>> trace_id  # doctest: +SKIP
        '550e8400-e29b-41d4-a716-446655440000'
    """
    return getattr(_context, "trace_id", str(uuid4()))


def set_trace_id(trace_id: str) -> None:
    """
    Set the trace ID in thread-local context.

    The trace ID should be generated in the API Gateway and extracted from
    the X-Trace-ID header in all downstream services. This enables log
    correlation across the entire request flow.

    Args:
        trace_id: Unique identifier for this request (typically a UUID)

    Example:
        >>> set_trace_id('550e8400-e29b-41d4-a716-446655440000')
        >>> get_trace_id()
        '550e8400-e29b-41d4-a716-446655440000'
    """
    _context.trace_id = trace_id


@contextmanager
def trace_context(trace_id: str):
    """
    Context manager to set trace ID for a block of code.

    Useful for processing background jobs or async tasks where you want
    to preserve trace ID context.

    Args:
        trace_id: Trace ID to use within the context

    Yields:
        None

    Example:
        >>> with trace_context('550e8400-e29b-41d4-a716-446655440000'):
        ...     logger.info("Processing job")
        ...     # All logs in this block will have the same trace_id
    """
    old_trace_id = getattr(_context, "trace_id", None)
    set_trace_id(trace_id)
    try:
        yield
    finally:
        if old_trace_id:
            set_trace_id(old_trace_id)
        else:
            if hasattr(_context, "trace_id"):
                delattr(_context, "trace_id")


class JSONFormatter(logging.Formatter):
    """
    JSON logging formatter for structured logging.

    Converts Python logging records into JSON format suitable for Loki ingestion.
    Each log entry includes:
    - timestamp: ISO 8601 format
    - level: Log level (INFO, WARNING, ERROR, etc.)
    - service: Service name (configured at logger setup)
    - trace_id: Request trace ID for correlation
    - message: Log message
    - Any extra fields passed via the 'extra' parameter

    This formatter is compatible with Loki's JSON parser, which automatically
    extracts these fields for ad-hoc querying and aggregation.
    """

    def __init__(self, service_name: str):
        """
        Initialize JSON formatter with service name.

        Args:
            service_name: Name of the service (e.g., 'auth', 'booking')
                         Will be included in all log entries
        """
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record as JSON.

        Args:
            record: Python logging.LogRecord to format

        Returns:
            str: JSON-formatted log entry

        Example output:
            {
                "timestamp": "2026-02-07T12:00:00.123456Z",
                "level": "INFO",
                "service": "auth",
                "trace_id": "550e8400-e29b-41d4-a716-446655440000",
                "logger": "services.auth.main",
                "message": "User authenticated",
                "user_id": "user123"
            }
        """
        # Build base log entry structure
        log_entry = {
            # ISO 8601 timestamp with millisecond precision
            "timestamp": datetime.utcnow().isoformat() + "Z",
            # Log level (uppercased)
            "level": record.levelname,
            # Service name for filtering
            "service": self.service_name,
            # Trace ID for correlation across services
            "trace_id": get_trace_id(),
            # Logger module for detailed debugging
            "logger": record.name,
            # Main log message
            "message": record.getMessage(),
        }

        # Add exception info if present (for error/exception logs)
        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)

        # Add any extra fields passed via logger.info(..., extra={...})
        if hasattr(record, "__dict__"):
            # Exclude standard LogRecord fields
            skip_fields = {
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "getMessage",
            }
            for key, value in record.__dict__.items():
                # Add any custom fields from extra parameter
                if key not in skip_fields and not key.startswith("_"):
                    # Skip fields that start with underscore (internal)
                    log_entry[key] = value

        # Convert to JSON and return as single line (important for Loki)
        return json.dumps(log_entry, default=str)


def setup_logging(service_name: str, log_level: str = "INFO") -> None:
    """
    Configure JSON logging for a service.

    Call this once at service startup (in main.py). Configures the root logger
    to output JSON to stdout, which can be captured by docker/kubernetes and
    forwarded to Loki.

    Args:
        service_name: Name of the service (e.g., "auth", "booking")
                     Used as 'service' field in all logs
        log_level: Python logging level as string
                  (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Example:
        >>> setup_logging("auth", log_level="INFO")
        >>> logger = get_logger(__name__)
        >>> logger.info("Service started")
        {"timestamp": "...", "level": "INFO", "service": "auth", ...}

    Side Effects:
        - Reconfigures Python's root logger
        - Redirects all logging output to stdout as JSON
        - Sets propagate=False on handlers to avoid duplicate logs
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))

    # Remove existing handlers to avoid duplicate logs
    root_logger.handlers.clear()

    # Create stdout handler (logs go to docker/kubernetes stdout)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, log_level))

    # Create JSON formatter for this service
    formatter = JSONFormatter(service_name=service_name)
    handler.setFormatter(formatter)

    # Attach formatter to handler and handler to logger
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    This is the standard way to get a logger in Python code. The logger
    uses the JSON formatter configured by setup_logging().

    Args:
        name: Logger name, typically __name__ of the module
              (e.g., "services.auth.main")

    Returns:
        logging.Logger: Configured logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing request", extra={"user_id": "123"})
    """
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event_type: str,
    message: str,
    level: str = "INFO",
    **context,
) -> None:
    """
    Log a structured event with context.

    This is a convenience function for logging business events with
    consistent formatting and context capture.

    Args:
        logger: Logger instance (from get_logger())
        event_type: Type of event (e.g., "user_registered", "payment_captured")
        message: Human-readable event description
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        **context: Additional context fields to include in log
                   (e.g., user_id="123", email="user@example.com")

    Example:
        >>> logger.info("User registered", extra={
        ...     "event_type": "user_registered",
        ...     "user_id": user_id,
        ...     "email": email
        ... })
    """
    log_data = {"event_type": event_type, **context}
    log_func = getattr(logger, level.lower())
    log_func(message, extra=log_data)
