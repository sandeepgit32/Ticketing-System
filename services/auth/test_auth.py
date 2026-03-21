import importlib.util
import os
import sys
from datetime import timedelta

import pytest
from dotenv import load_dotenv

# Load auth's main.py under a unique module name so pytest's shared sys.modules
# does not collide with other services' main.py files.
_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(_SERVICE_DIR, ".env"), override=False)
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
    payload = {"sub": "user-abc", "email": "user@example.com", "role": "Admin"}
    token = create_access_token(payload, expires_delta=timedelta(minutes=2))

    decoded = decode_token(token)
    assert decoded["sub"] == payload["sub"]
    assert decoded["email"] == payload["email"]
    assert decoded["role"] == payload["role"]


def test_decode_token_invalid_raises_http_exception():
    with pytest.raises(Exception):
        decode_token("this-is-not-a-jwt")


def test_seed_default_admin_user_upserts_admin(monkeypatch):
    captured = {}

    class FakeCursor:
        def execute(self, query, params=None):
            captured["query"] = query
            captured["params"] = params

        def close(self):
            captured["cursor_closed"] = True

    class FakeConn:
        def cursor(self, dictionary=True):
            captured["dictionary"] = dictionary
            return FakeCursor()

        def commit(self):
            captured["committed"] = True

        def close(self):
            captured["conn_closed"] = True

    monkeypatch.setattr(_mod, "get_db_connection", lambda: FakeConn())
    monkeypatch.setattr(_mod, "hash_password", lambda password: f"hashed:{password}")

    _mod.seed_default_admin_user()

    assert "INSERT INTO users" in captured["query"]
    assert "ON DUPLICATE KEY UPDATE" in captured["query"]
    assert captured["params"][1] == _mod.DEFAULT_ADMIN_EMAIL
    assert captured["params"][2] == f"hashed:{_mod.DEFAULT_ADMIN_PASSWORD}"
    assert captured["params"][3] == _mod.DEFAULT_ADMIN_FULL_NAME
    assert captured["params"][4] == "Admin"
    assert captured["committed"] is True
    assert captured["cursor_closed"] is True
    assert captured["conn_closed"] is True
