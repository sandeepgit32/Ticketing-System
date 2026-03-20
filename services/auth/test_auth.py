import importlib.util
import os
import sys
from datetime import timedelta

import pytest

# Load auth's main.py under a unique module name so pytest's shared sys.modules
# does not collide with other services' main.py files.
_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.modules.pop("schemas", None)  # avoid cross-service schemas.py conflict
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

_spec = importlib.util.spec_from_file_location(
    "auth_main", os.path.join(_SERVICE_DIR, "main.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

hash_password = _mod.hash_password
verify_password = _mod.verify_password
create_access_token = _mod.create_access_token
decode_token = _mod.decode_token


def test_hash_and_verify_password():
    raw_password = "SuperSecret123!"
    hashed = hash_password(raw_password)

    assert hashed != raw_password
    assert verify_password(raw_password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_create_and_decode_access_token():
    payload = {"sub": "user-abc", "email": "user@example.com"}
    token = create_access_token(payload, expires_delta=timedelta(minutes=2))

    decoded = decode_token(token)
    assert decoded["sub"] == payload["sub"]
    assert decoded["email"] == payload["email"]


def test_decode_token_invalid_raises_http_exception():
    with pytest.raises(Exception):
        decode_token("this-is-not-a-jwt")
