import importlib.util
import os
import sys

import pytest
from fastapi.testclient import TestClient

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load service environment from .env so required_env() calls in main.py resolve correctly.
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(_SERVICE_DIR, ".env"), override=False)

if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

_spec = importlib.util.spec_from_file_location(
    "payment_mock_main", os.path.join(_SERVICE_DIR, "main.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

generate_signature = _mod.generate_signature


# ---------------------------------------------------------------------------
# generate_signature unit tests
# ---------------------------------------------------------------------------


def test_generate_signature_returns_64_char_hex():
    payload = '{"event":"capture_succeeded"}'
    sig = generate_signature(payload)
    assert isinstance(sig, str)
    assert len(sig) == 64


def test_generate_signature_is_deterministic():
    payload = '{"event":"capture_succeeded"}'
    assert generate_signature(payload) == generate_signature(payload)


def test_generate_signature_differs_for_different_payloads():
    sig1 = generate_signature('{"event":"capture_succeeded"}')
    sig2 = generate_signature('{"event":"capture_failed"}')
    assert sig1 != sig2


# ---------------------------------------------------------------------------
# API shape tests via TestClient (no Redis required — routes are tested for
# request/response shape only; background tasks are not awaited here)
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal async-compatible Redis stub for unit tests."""

    async def get(self, key):
        return None

    async def set(self, key, value, ex=None, nx=False):
        return True

    async def aclose(self):
        pass


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch):
    monkeypatch.setattr(_mod, "redis_client", _FakeRedis())


@pytest.fixture()
def client(monkeypatch):
    # Stub out the webhook forwarding so tests don't need a live booking service.
    async def _noop_forward(payload):
        pass

    monkeypatch.setattr(_mod, "_forward_to_booking_service", _noop_forward)
    return TestClient(_mod.app, raise_server_exceptions=True)


def test_create_intent_missing_intent_id(client):
    resp = client.post("/payments/intents", json={})
    assert resp.status_code == 400


def test_create_intent_returns_expected_shape(client):
    resp = client.post(
        "/payments/intents", json={"intent_id": "res-abc", "amount": 500}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent_id"] == "res-abc"
    assert body["status"] == "requires_confirmation"
    assert body["key_id"] == "mock"
    assert body["amount"] == 500.0
    assert body["mock_order_id"].startswith("mock_order_")


def test_confirm_intent_returns_ok(client):
    resp = client.post(
        "/payments/intents/res-abc/confirm",
        json={"mock_payment_id": "mock_pay_xyz", "mock_order_id": "mock_order_xyz"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "scheduled": True}


def test_confirm_intent_accepts_empty_body(client):
    resp = client.post("/payments/intents/res-abc/confirm", json={})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "scheduled": True}
