"""Input validators used by the API routes."""
import pytest

from app.utils.validation import (
    is_iso_date,
    is_valid_email,
    normalize_preference,
    same_place,
)


@pytest.mark.parametrize("value,expected", [
    ("2026-06-24", True),
    ("2026-13-01", False),   # invalid month
    ("2026-02-30", False),   # invalid day
    ("24-06-2026", False),   # wrong format
    ("", False),
    (None, False),
    (20260624, False),
])
def test_is_iso_date(value, expected):
    assert is_iso_date(value) is expected


@pytest.mark.parametrize("value,expected", [
    ("a@b.com", True),
    ("first.last@sub.domain.co", True),
    ("no-at-sign", False),
    ("missing@domain", False),
    ("@nodomain.com", False),
    ("", False),
    (None, False),
])
def test_is_valid_email(value, expected):
    assert is_valid_email(value) is expected


@pytest.mark.parametrize("value,expected", [
    ("Comfort", "Comfort"),
    ("Budget", "Budget"),
    ("luxury", "Comfort"),
    (None, "Comfort"),
    ("", "Comfort"),
])
def test_normalize_preference(value, expected):
    assert normalize_preference(value) == expected


@pytest.mark.parametrize("a,b,expected", [
    ("Mumbai", "mumbai", True),
    ("  Delhi ", "delhi", True),
    ("Mumbai", "Pune", False),
    (None, "Pune", False),
])
def test_same_place(a, b, expected):
    assert same_place(a, b) is expected
