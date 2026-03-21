# Notification Service

This microservice sends transactional emails (reservation confirmations, payment receipts, etc.) for BookEventTicket.

It operates as a background worker that reads notification messages from a Redis queue and sends emails via SMTP (Mailtrap by default).

---

## How it works

1. The service listens on a Redis list/queue (`queue:notifications`).
2. When a notification is pushed into the queue, the service pops it, determines the notification type, and builds an email body.
3. Emails are sent via SMTP. If SMTP credentials are not configured, the service prints a mock email to stdout (useful for local development).

---

## Notification Queue Contract

Notification messages are JSON objects pushed into Redis at `queue:notifications`. Each message must include at least:

- `type`: The notification type (e.g. `reservation_confirmed`, `payment_confirmed`, `payment_failed`)
- `data`: An object containing the payload for the notification

Example message:

```json
{
  "type": "reservation_confirmed",
  "data": {
    "user_email": "user@example.com",
    "reservation_id": "abc123",
    "event_name": "Concert",
    "seats": ["A1", "A2"],
    "expires_at": "2026-03-15T14:00:00Z"
  }
}
```

---

## Configuration

The service reads configuration from environment variables. Defaults are provided for local development:

```env
# Redis queue
REDIS_URL=redis://localhost:6379/0

# SMTP (Mailtrap defaults)
SMTP_HOST=sandbox.smtp.mailtrap.io
SMTP_PORT=2525
SMTP_USER=
SMTP_PASSWORD=
FROM_EMAIL=noreply@ticketing-system.com
```

**Note:** If `SMTP_USER` or `SMTP_PASSWORD` are empty, the service will not send real emails and will instead print a mock email to the console.

---

## Running the Service

From the `services/notification` directory:

```bash
pip install -r requirements.txt
python main.py
```

In Docker scenarios, the service is typically started via the project `docker-compose.yml` or another orchestration layer.

---

## Extending Notifications

To add a new notification type:

1. Add a new `elif` branch in `process_notification()` in `main.py`.
2. Implement a `generate_*_email()` helper that returns `(subject, text_body, html_body)`.
3. Ensure the message producer populates the `type` and `data` fields accordingly.

---

## Notes

- The service uses blocking `BRPOP` to consume jobs with a 5 second timeout.
- Errors are logged to stdout and the loop continues after a short sleep.
