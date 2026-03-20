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
