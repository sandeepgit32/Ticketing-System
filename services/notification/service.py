import os
import json
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import redis

# Configuration
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
NOTIFICATION_QUEUE = 'queue:notifications'

# Mailtrap SMTP Configuration
SMTP_HOST = os.getenv('SMTP_HOST', 'sandbox.smtp.mailtrap.io')
SMTP_PORT = int(os.getenv('SMTP_PORT', '2525'))
SMTP_USER = os.getenv('SMTP_USER', '')  # Set your Mailtrap username
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')  # Set your Mailtrap password
FROM_EMAIL = os.getenv('FROM_EMAIL', 'noreply@ticketing-system.com')

# Connect to Redis
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

print('Notification Service started, connecting to Redis...')
print(f'SMTP configured: {SMTP_HOST}:{SMTP_PORT}')


def send_email(to_email: str, subject: str, html_body: str, text_body: str = None):
    """Send email via Mailtrap SMTP"""
    try:
        # Check if SMTP credentials are configured
        if not SMTP_USER or not SMTP_PASSWORD:
            print(f"[MOCK EMAIL] To: {to_email}, Subject: {subject}")
            print(f"[MOCK EMAIL] Body: {text_body or html_body[:100]}")
            return True
        
        msg = MIMEMultipart('alternative')
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Add text and HTML parts
        if text_body:
            part1 = MIMEText(text_body, 'plain')
            msg.attach(part1)
        
        part2 = MIMEText(html_body, 'html')
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
    """Generate reservation confirmation email"""
    user_email = notification_data.get('user_email', 'user@example.com')
    reservation_id = notification_data.get('reservation_id', 'N/A')
    event_name = notification_data.get('event_name', 'Event')
    seats = notification_data.get('seats', [])
    expires_at = notification_data.get('expires_at', 'N/A')
    
    subject = f"Reservation Confirmed - {event_name}"
    
    text_body = f"""
Reservation Confirmed!

Reservation ID: {reservation_id}
Event: {event_name}
Seats: {', '.join([f"Row {s.get('row', '?')} Seat {s.get('seat', '?')}" for s in seats])}
Expires At: {expires_at}

Please complete your payment before the reservation expires.

Thank you for using our ticketing system!
    """
    
    html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #4CAF50;">Reservation Confirmed!</h2>
    <p><strong>Reservation ID:</strong> {reservation_id}</p>
    <p><strong>Event:</strong> {event_name}</p>
    <p><strong>Seats:</strong></p>
    <ul>
        {''.join([f"<li>Row {s.get('row', '?')} - Seat {s.get('seat', '?')}</li>" for s in seats])}
    </ul>
    <p><strong>Expires At:</strong> {expires_at}</p>
    <p style="color: #ff5722;">⏰ Please complete your payment before the reservation expires.</p>
    <hr style="border: 1px solid #eee;">
    <p style="font-size: 12px; color: #666;">Thank you for using our ticketing system!</p>
</body>
</html>
    """
    
    return subject, text_body, html_body


def generate_payment_confirmation_email(notification_data: dict) -> tuple:
    """Generate payment confirmation email"""
    user_email = notification_data.get('user_email', 'user@example.com')
    booking_id = notification_data.get('booking_id', 'N/A')
    event_name = notification_data.get('event_name', 'Event')
    seats = notification_data.get('seats', [])
    total_amount = notification_data.get('total_amount', 0)
    
    subject = f"Payment Confirmed - {event_name}"
    
    text_body = f"""
Payment Confirmed!

Booking ID: {booking_id}
Event: {event_name}
Seats: {', '.join([f"Row {s.get('row', '?')} Seat {s.get('seat', '?')}" for s in seats])}
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
        {''.join([f"<li>Row {s.get('row', '?')} - Seat {s.get('seat', '?')}</li>" for s in seats])}
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
    """Generate payment failed email"""
    user_email = notification_data.get('user_email', 'user@example.com')
    reservation_id = notification_data.get('reservation_id', 'N/A')
    event_name = notification_data.get('event_name', 'Event')
    reason = notification_data.get('reason', 'Payment processing failed')
    
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
    """Process a notification from the queue"""
    notification_type = notification.get('type')
    notification_data = notification.get('data', {})
    user_email = notification_data.get('user_email')
    
    if not user_email:
        print(f"No user email in notification: {notification}")
        return
    
    print(f"Processing notification: {notification_type} for {user_email}")
    
    # Generate email based on notification type
    if notification_type == 'reservation_confirmed':
        subject, text_body, html_body = generate_reservation_email(notification_data)
    elif notification_type == 'payment_confirmed':
        subject, text_body, html_body = generate_payment_confirmation_email(notification_data)
    elif notification_type == 'payment_failed':
        subject, text_body, html_body = generate_payment_failed_email(notification_data)
    else:
        print(f"Unknown notification type: {notification_type}")
        return
    
    # Send email
    send_email(user_email, subject, html_body, text_body)
    
    # Log notification
    log_notification(notification)


def log_notification(notification: dict):
    """Log notification to console and optionally to a file"""
    timestamp = datetime.now().isoformat()
    log_entry = {
        'timestamp': timestamp,
        'notification': notification
    }
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
        print(f'Notification service error: {e}')
        time.sleep(1)
