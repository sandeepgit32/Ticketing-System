import json
import os
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import redis


def required_env(key: str, cast=str):
    """Read an environment variable and raise an error if it is missing.

    This helper is used to ensure required configuration is present at startup.
    It is intentionally strict so the service fails fast during deployment or local
    testing when a required value is not provided.

    Args:
        key: The name of the environment variable to read.
        cast: Optional callable used to cast the string value (e.g. `int`).

    Returns:
        The cast value of the environment variable.

    Raises:
        RuntimeError: If the environment variable is not set.
    """

    value = os.environ.get(key)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return cast(value)


# Configuration (required via environment)
REDIS_URL = required_env("REDIS_URL")
NOTIFICATION_QUEUE = "queue:notifications"

# SMTP Configuration
SMTP_HOST = required_env("SMTP_HOST")
SMTP_PORT = required_env("SMTP_PORT", int)
SMTP_USER = required_env("SMTP_USER")
SMTP_PASSWORD = required_env("SMTP_PASSWORD")
FROM_EMAIL = required_env("FROM_EMAIL")

# Connect to Redis
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

print("Notification Service started, connecting to Redis...")
print(f"SMTP configured: {SMTP_HOST}:{SMTP_PORT}")


def send_email(to_email: str, subject: str, html_body: str, text_body: str = None):
    """Send an email via SMTP.

    The service is configured to use Mailtrap by default, but any SMTP server
    can be used by setting the corresponding environment variables.

    If SMTP credentials are missing, the function logs a mock email to stdout instead
    of attempting to send a real message (useful for local development).

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        html_body: HTML email body.
        text_body: Optional plain-text email body.

    Returns:
        True if the email was successfully sent (or mocked); False on failure.
    """
    try:
        # Check if SMTP credentials are configured
        if not SMTP_USER or not SMTP_PASSWORD:
            print(f"[MOCK EMAIL] To: {to_email}, Subject: {subject}")
            print(f"[MOCK EMAIL] Body: {text_body or html_body[:100]}")
            return True

        msg = MIMEMultipart("alternative")
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject

        # Add text and HTML parts
        if text_body:
            part1 = MIMEText(text_body, "plain")
            msg.attach(part1)

        part2 = MIMEText(html_body, "html")
        msg.attach(part2)

        # Send email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False


def generate_reservation_email(notification_data: dict) -> tuple:
    """Build subject + body for a reservation confirmation email.

    Args:
        notification_data: Payload from the notification queue. Expected keys:
            - reservation_id
            - event_name
            - seats: list of seat labels (e.g. ["A1", "A2"])
            - expires_at

    Returns:
        A tuple `(subject, text_body, html_body)` suitable for `send_email()`.

    Raises:
        ValueError: If `seats` is not a list of strings.
    """
    reservation_id = notification_data.get("reservation_id")
    event_name = notification_data.get("event_name")
    seats = notification_data.get("seats") or []
    expires_at = notification_data.get("expires_at")

    if not isinstance(seats, list) or not all(isinstance(s, str) for s in seats):
        raise ValueError("`seats` must be a list of strings like ['A1', 'A2']")

    subject = f"Reservation Confirmed - {event_name}"

    seat_labels = seats

    text_body = f"""
Reservation Confirmed!

Reservation ID: {reservation_id}
Event: {event_name}
Seats: {", ".join(seat_labels)}
Expires At: {expires_at}

Please complete your payment before the reservation expires.

Thank you for using BookEventTicket!
    """

    html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #4CAF50;">Reservation Confirmed!</h2>
    <p><strong>Reservation ID:</strong> {reservation_id}</p>
    <p><strong>Event:</strong> {event_name}</p>
    <p><strong>Seats:</strong></p>
    <ul>
        {"".join([f"<li>{label}</li>" for label in seat_labels])}
    </ul>
    <p><strong>Expires At:</strong> {expires_at}</p>
    <p style="color: #ff5722;">⏰ Please complete your payment before the reservation expires.</p>
    <hr style="border: 1px solid #eee;">
    <p style="font-size: 12px; color: #666;">Thank you for using BookEventTicket!</p>
</body>
</html>
    """

    return subject, text_body, html_body


def generate_payment_confirmation_email(notification_data: dict) -> tuple:
    """Build subject + body for a payment confirmation email.

    Args:
        notification_data: Payload from the notification queue. Expected keys:
            - booking_id
            - event_name
            - seats: list of seat labels (e.g. ["A1", "A2"])
            - total_amount

    Returns:
        A tuple `(subject, text_body, html_body)` suitable for `send_email()`.

    Raises:
        ValueError: If `seats` is not a list of strings.
    """
    booking_id = notification_data.get("booking_id")
    event_name = notification_data.get("event_name")
    seats = notification_data.get("seats") or []
    total_amount = notification_data.get("total_amount")

    if not isinstance(seats, list) or not all(isinstance(s, str) for s in seats):
        raise ValueError("`seats` must be a list of strings like ['A1', 'A2']")

    seat_labels = seats

    subject = f"Payment Confirmed - {event_name}"

    text_body = f"""
Payment Confirmed!

Booking ID: {booking_id}
Event: {event_name}
Seats: {", ".join(seat_labels)}
Total Amount: ${total_amount}

Your tickets have been confirmed. Enjoy the event!

Thank you for your purchase!
    """

    html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #4CAF50;">✓ Payment Confirmed!</h2>
    <p><strong>Booking ID:</strong> {booking_id}</p>
    <p><strong>Event:</strong> {event_name}</p>
    <p><strong>Seats:</strong></p>
    <ul>
        {"".join([f"<li>{label}</li>" for label in seat_labels])}
    </ul>
    <p><strong>Total Amount:</strong> <span style="color: #4CAF50; font-size: 18px;">${total_amount}</span></p>
    <p style="color: #4CAF50; font-weight: bold;">🎉 Your tickets have been confirmed. Enjoy the event!</p>
    <hr style="border: 1px solid #eee;">
    <p style="font-size: 12px; color: #666;">Thank you for your purchase!</p>
</body>
</html>
    """

    return subject, text_body, html_body


def generate_payment_failed_email(notification_data: dict) -> tuple:
    """Build subject + body for a payment failure notification email.

    Args:
        notification_data: Payload from the notification queue. Expected keys:
            - reservation_id
            - event_name
            - reason (optional)

    Returns:
        A tuple `(subject, text_body, html_body)` suitable for `send_email()`.
    """
    reservation_id = notification_data.get("reservation_id")
    event_name = notification_data.get("event_name")
    reason = notification_data.get("reason", "Payment processing failed")

    subject = f"Payment Failed - {event_name}"

    text_body = f"""
Payment Failed

Reservation ID: {reservation_id}
Event: {event_name}
Reason: {reason}

Your reservation has been released. Please try again if you still wish to book tickets.

If you have any questions, please contact our support team.
    """

    html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #f44336;">⚠ Payment Failed</h2>
    <p><strong>Reservation ID:</strong> {reservation_id}</p>
    <p><strong>Event:</strong> {event_name}</p>
    <p><strong>Reason:</strong> {reason}</p>
    <p>Your reservation has been released. Please try again if you still wish to book tickets.</p>
    <hr style="border: 1px solid #eee;">
    <p style="font-size: 12px; color: #666;">If you have any questions, please contact our support team.</p>
</body>
</html>
    """

    return subject, text_body, html_body


def process_notification(notification: dict):
    """Process a notification message from Redis.

    The message should be a JSON object with:
      - `type`: the notification category (e.g. reservation_confirmed)
      - `data`: payload used to compose the email

    This function selects the correct email template, sends the email, and logs the
    result.

    Args:
        notification: The parsed notification object.
    """
    notification_type = notification.get("type")
    notification_data = notification.get("data", {})
    user_email = notification_data.get("user_email")

    if not user_email:
        print(f"No user email in notification: {notification}")
        return

    print(f"Processing notification: {notification_type} for {user_email}")

    # Generate email based on notification type
    if notification_type == "reservation_confirmed":
        subject, text_body, html_body = generate_reservation_email(notification_data)
    elif notification_type == "payment_confirmed":
        subject, text_body, html_body = generate_payment_confirmation_email(
            notification_data
        )
    elif notification_type == "payment_failed":
        subject, text_body, html_body = generate_payment_failed_email(notification_data)
    else:
        print(f"Unknown notification type: {notification_type}")
        return

    # Send email
    send_email(user_email, subject, html_body, text_body)

    # Log notification
    log_notification(notification)


def log_notification(notification: dict):
    """Log a processed notification.

    Currently this writes a JSON entry to stdout. It is designed to be simple so
    that the service can be monitored in container logs.

    Args:
        notification: The original notification payload.
    """
    timestamp = datetime.now().isoformat()
    log_entry = {"timestamp": timestamp, "notification": notification}
    print(f"[{timestamp}] Notification logged: {json.dumps(log_entry)}")


# Main worker loop
while True:
    try:
        # Pop notification from queue (blocking with 5 second timeout)
        notification_json = redis_client.brpop(NOTIFICATION_QUEUE, timeout=5)

        if not notification_json:
            continue

        # Parse notification
        _, notification_data = notification_json
        notification = json.loads(notification_data)

        # Process notification
        process_notification(notification)

    except Exception as e:
        print(f"Notification service error: {e}")
        time.sleep(1)
