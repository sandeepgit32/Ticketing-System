import importlib.util
import os
import sys

import pytest
from fastapi.testclient import TestClient

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

_spec = importlib.util.spec_from_file_location(
    "gateway_main", os.path.join(_SERVICE_DIR, "main.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

app = _mod.app

client = TestClient(app)


def test_health_route():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_returns_service_info():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "API Gateway"


def test_protected_route_without_token_returns_401():
    # POST /booking/events requires auth; no Authorization header -> 401
    response = client.post("/booking/events", json={"name": "Test"})
    assert response.status_code == 401


def test_protected_status_route_without_token_returns_401():
    response = client.get("/status/bookings/some-booking-id")
    assert response.status_code == 401


def test_auth_verify_forwards_authorization_header(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        content = b'{"valid": true}'

        @property
        def headers(self):
            return {"content-type": "application/json"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, url, headers=None, content=None, params=None):
            captured["headers"] = headers
            captured["method"] = method
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setattr(_mod.httpx, "AsyncClient", lambda timeout=30.0: FakeClient())

    response = client.post(
        "/auth/verify",
        headers={"Authorization": "Bearer token-value"},
    )

    assert response.status_code == 200
    assert captured["headers"]["authorization"] == "Bearer token-value"


def test_create_event_requires_admin_role(monkeypatch):
    async def fake_verify_token():
        return {"email": "user@example.com", "role": "User"}

    app.dependency_overrides[_mod.verify_token] = fake_verify_token
    monkeypatch.setattr(_mod, "proxy_request", lambda *args, **kwargs: {"ok": True})

    response = client.post(
        "/booking/events",
        json={"name": "Test"},
        headers={"Authorization": "Bearer token"},
    )
    app.dependency_overrides.clear()
    assert response.status_code == 403


def test_create_event_allows_admin_role(monkeypatch):
    async def fake_verify_token():
        return {"email": "admin@example.com", "role": "Admin"}

    async def fake_proxy_request(request, target_url, user_info=None):
        return {"ok": True, "user_info": user_info, "target_url": target_url}

    app.dependency_overrides[_mod.verify_token] = fake_verify_token
    monkeypatch.setattr(_mod, "proxy_request", fake_proxy_request)

    response = client.post(
        "/booking/events",
        json={"name": "Test"},
        headers={"Authorization": "Bearer token"},
    )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["user_info"]["role"] == "Admin"
