"""Image resolution: pure title-matching logic plus live API integration."""
import socket

import pytest
import requests

from app.services.ai_service import AIService


def _network_service():
    """Build an AIService without its LLM init, wired for real HTTP calls.

    Mirrors the session and browser User-Agent the app uses at runtime so the
    live image lookups behave the same as production.
    """
    svc = AIService.__new__(AIService)
    svc.web_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    svc.web_session = requests.Session()
    return svc


# ------------------------------------------------------------- pure unit tests

@pytest.mark.parametrize("title,place,expected", [
    ("Gateway of India", "Gateway of India", True),
    ("Lake Palace", "Lake Palace", True),
    ("Lake Palace, Udaipur", "Lake Palace", True),       # substring
    ("Taj Mahal Palace Hotel", "Taj Mahal", True),       # token overlap
    ("Mumbai", "Gateway of India", False),               # unrelated city page
    ("List of monuments", "Charminar", False),
    ("Cristiano Ronaldo", "Hawa Mahal", False),
    ("", "Charminar", False),
    ("Charminar", "", False),
])
def test_title_matches(title, place, expected):
    assert AIService._title_matches(title, place) is expected


def test_resolve_image_returns_placeholder_for_garbage(monkeypatch):
    # Force both providers to find nothing -> placeholder, no crash.
    svc = AIService.__new__(AIService)  # avoid LLM/network init
    svc.web_headers = {}
    monkeypatch.setattr(svc, "_fetch_wikipedia_image", lambda *a, **k: "")
    monkeypatch.setattr(svc, "_fetch_commons_image", lambda *a, **k: "")
    from app.services.ai_service import PLACEHOLDER_IMAGE
    assert svc._resolve_image("Nope", "Nowhere") == PLACEHOLDER_IMAGE


def test_resolve_image_prefers_wikipedia(monkeypatch):
    svc = AIService.__new__(AIService)
    svc.web_headers = {}
    monkeypatch.setattr(svc, "_fetch_wikipedia_image", lambda *a, **k: "WIKI")
    monkeypatch.setattr(svc, "_fetch_commons_image", lambda *a, **k: "COMMONS")
    assert svc._resolve_image("X", "Y") == "WIKI"


def test_resolve_image_falls_back_to_commons(monkeypatch):
    svc = AIService.__new__(AIService)
    svc.web_headers = {}
    monkeypatch.setattr(svc, "_fetch_wikipedia_image", lambda *a, **k: "")
    monkeypatch.setattr(svc, "_fetch_commons_image", lambda *a, **k: "COMMONS")
    assert svc._resolve_image("X", "Y") == "COMMONS"


# ----------------------------------------------------------- live integration

def _online() -> bool:
    try:
        socket.create_connection(("en.wikipedia.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


@pytest.mark.network
@pytest.mark.skipif(not _online(), reason="no network")
@pytest.mark.parametrize("place,city", [
    ("Gateway of India", "Mumbai"),
    ("Charminar", "Hyderabad"),
    ("Hawa Mahal", "Jaipur"),
])
def test_live_wikipedia_returns_real_image(place, city):
    svc = _network_service()
    url = svc._fetch_wikipedia_image(place, city)
    assert url.startswith("http")
    assert url.lower().endswith((".jpg", ".jpeg", ".png"))


@pytest.mark.network
@pytest.mark.skipif(not _online(), reason="no network")
def test_live_unknown_place_yields_no_image():
    svc = _network_service()
    assert svc._fetch_wikipedia_image("Zzz Fake Attraction Qwerty", "Nowhereville") == ""
