import importlib.util
import os
import sys

import pytest

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

os.environ.setdefault("WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("BOOKING_WEBHOOK_URL", "http://localhost:8000/webhook")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

_spec = importlib.util.spec_from_file_location(
    "payment_mock_main", os.path.join(_SERVICE_DIR, "main.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

generate_signature = _mod.generate_signature


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
