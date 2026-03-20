import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# required_env() raises RuntimeError if any var is absent; set before loading.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SMTP_HOST", "smtp.example.com")
os.environ.setdefault("SMTP_PORT", "587")
os.environ.setdefault("SMTP_USER", "")
os.environ.setdefault("SMTP_PASSWORD", "")
os.environ.setdefault("FROM_EMAIL", "noreply@example.com")

if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

# notification/main.py has a blocking `while True: redis_client.brpop(...)` at
# module level.  Mock Redis before exec_module so the loop terminates on the
# second brpop call via SystemExit (which bypasses the `except Exception` guard).
_mock_redis = MagicMock()
_brpop_calls = [0]


def _fake_brpop(*args, **kwargs):
    _brpop_calls[0] += 1
    if _brpop_calls[0] > 1:
        raise SystemExit(0)
    return None  # first call: loop continues, second call: SystemExit breaks out


_mock_redis.brpop = _fake_brpop

_spec = importlib.util.spec_from_file_location(
    "notification_main", os.path.join(_SERVICE_DIR, "main.py")
)
_notification_mod = importlib.util.module_from_spec(_spec)

with patch("redis.Redis.from_url", return_value=_mock_redis):
    try:
        _spec.loader.exec_module(_notification_mod)
    except SystemExit:
        pass  # expected — all function definitions are already complete

generate_reservation_email = _notification_mod.generate_reservation_email
generate_payment_confirmation_email = (
    _notification_mod.generate_payment_confirmation_email
)
generate_payment_failed_email = _notification_mod.generate_payment_failed_email
process_notification = _notification_mod.process_notification


def test_generate_reservation_email():
    data = {
        "reservation_id": "res-1",
        "event_name": "Concert",
        "seats": ["A1", "B2"],
        "expires_at": "2026-01-01T00:00:00Z",
    }

    subject, text_body, html_body = generate_reservation_email(data)
    assert "Reservation Confirmed - Concert" in subject
    assert "A1" in text_body
    assert "B2" in html_body


def test_generate_email_invalid_seats_raises():
    with pytest.raises(ValueError):
        generate_reservation_email(
            {"reservation_id": "r", "event_name": "Concert", "seats": "not-a-list"}
        )


def test_process_notification_unknown_type(monkeypatch):
    # Ensure function returns cleanly for unknown type and does not raise.
    # Patch on the loaded module object since it isn't registered as 'main'.
    monkeypatch.setattr(_notification_mod, "send_email", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        _notification_mod, "log_notification", lambda *args, **kwargs: None
    )

    process_notification({"type": "unknown", "data": {"user_email": "u@example.com"}})


def test_process_notification_reservation_confirmed(monkeypatch):
    called = {}

    def fake_send_email(to_email, subject, html_body, text_body=None):
        called["email"] = to_email
        return True

    monkeypatch.setattr(_notification_mod, "send_email", fake_send_email)
    monkeypatch.setattr(
        _notification_mod, "log_notification", lambda *args, **kwargs: None
    )

    process_notification(
        {
            "type": "reservation_confirmed",
            "data": {
                "user_email": "u@example.com",
                "reservation_id": "R1",
                "event_name": "Concert",
                "seats": ["A1"],
                "expires_at": "2026-01-01T00:00:00Z",
            },
        }
    )

    assert called["email"] == "u@example.com"
