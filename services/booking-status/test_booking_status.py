import importlib.util
import os
import sys

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load service environment from .env so os.getenv() calls in main.py resolve correctly.
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(_SERVICE_DIR, ".env"), override=False)

# Clear any stale 'schemas' from a previously loaded service to ensure
# booking-status/schemas.py is found instead of auth/schemas.py.
sys.modules.pop("schemas", None)
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

_spec = importlib.util.spec_from_file_location(
    "booking_status_main", os.path.join(_SERVICE_DIR, "main.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

app = _mod.app
get_current_user_email = _mod.get_current_user_email
get_current_user_role = _mod.get_current_user_role
require_customer_access = _mod.require_customer_access


def test_health_route(monkeypatch):
    from unittest.mock import MagicMock

    # before_first_request triggers startup_event which tries to connect to MySQL.
    # Mock the pool constructor so the health route can be tested without a real DB.
    monkeypatch.setattr(
        _mod.pooling, "MySQLConnectionPool", lambda **kwargs: MagicMock()
    )
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "healthy"}


def test_get_current_user_email_missing_header():
    # Authentication is enforced by the API gateway; a missing X-User-Email
    # header is treated as an empty string at the service level. The gateway
    # guarantees the header is always present for authenticated routes.
    with app.test_request_context():
        assert get_current_user_email() == ""


def test_get_current_user_email_found_header():
    with app.test_request_context("/", headers={"X-User-Email": "user@example.com"}):
        assert get_current_user_email() == "user@example.com"


def test_get_current_user_role_found_header():
    with app.test_request_context("/", headers={"X-User-Role": "User"}):
        assert get_current_user_role() == "User"


def test_require_customer_access_blocks_admin():
    import pytest

    with app.test_request_context("/", headers={"X-User-Role": "Admin"}):
        with pytest.raises(Exception) as exc:
            require_customer_access()
        assert getattr(exc.value, "code", None) == 403


def test_user_bookings_route_rejects_admin(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(
        _mod.pooling, "MySQLConnectionPool", lambda **kwargs: MagicMock()
    )

    client = app.test_client()
    response = client.get(
        "/user/bookings",
        headers={"X-User-Email": "admin@example.com", "X-User-Role": "Admin"},
    )

    assert response.status_code == 403
    assert b"Admin access not allowed" in response.data
