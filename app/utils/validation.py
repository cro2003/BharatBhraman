"""Small, dependency-free input validators shared across API routes."""
import re
from datetime import datetime

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

VALID_PREFERENCES = {"Comfort", "Budget"}


def is_iso_date(value) -> bool:
    """True if ``value`` is a 'YYYY-MM-DD' calendar date string."""
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def is_valid_email(value) -> bool:
    """Lightweight email shape check (not full RFC 5322)."""
    return isinstance(value, str) and bool(_EMAIL_RE.match(value.strip()))


def normalize_preference(value) -> str:
    """Coerce a preference to one of the supported personas, defaulting to Comfort."""
    return value if value in VALID_PREFERENCES else "Comfort"


def same_place(origin, destination) -> bool:
    """True if origin and destination refer to the same place (case/space-insensitive)."""
    if not isinstance(origin, str) or not isinstance(destination, str):
        return False
    return origin.strip().lower() == destination.strip().lower()
