import importlib.util
import os
import sys

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment from .env before the module import so required_env() succeeds.
load_dotenv(dotenv_path=os.path.join(_SERVICE_DIR, ".env"), override=False)

if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

# Use a unique module name to avoid sys.modules['main'] collision.
_spec = importlib.util.spec_from_file_location(
    "booking_main", os.path.join(_SERVICE_DIR, "main.py")
)
booking_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(booking_main)


def test_parse_seat_id_valid():
    assert booking_main._parse_seat_id("A1") == ("A", 1)
    assert booking_main._parse_seat_id("b12") == ("B", 12)


def test_parse_seat_id_invalid():
    with pytest.raises(ValueError):
        booking_main._parse_seat_id("")
    with pytest.raises(ValueError):
        booking_main._parse_seat_id("A")
    with pytest.raises(ValueError):
        booking_main._parse_seat_id("1A")


def test_normalize_seat_ids_success():
    assert booking_main._normalize_seat_ids(["a1", "B2"]) == ["A1", "B2"]


def test_normalize_seat_ids_duplicate_fails():
    with pytest.raises(HTTPException) as exc:
        booking_main._normalize_seat_ids(["A1", "a1"])
    assert exc.value.status_code == 400


def test_build_default_seat_rows_and_map():
    cfg = {"rows": ["A", "B"], "columns": [1, 2], "seat_price": {"A": 10, "B": 20}}
    rows = booking_main.build_default_seat_rows(cfg)
    assert rows[0] == ("A1", 0, 10.0)
    assert rows[-1] == ("B2", 0, 20.0)

    mapping = booking_main.build_seat_index_map(cfg)
    assert mapping == {"A1": 0, "A2": 1, "B1": 2, "B2": 3}


def test_build_default_seat_rows_missing_cols_or_rows_raises():
    with pytest.raises(HTTPException):
        booking_main.build_default_seat_rows({"rows": [], "columns": []})
