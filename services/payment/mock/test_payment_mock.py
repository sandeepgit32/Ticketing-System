import importlib.util
import os
import sys

import pytest

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
