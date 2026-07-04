"""Server-side trip-context builder for the AI assistant (the only trusted source)."""
from app.services.ai_service import AIService


def test_no_trip():
    assert "No trip" in AIService.build_trip_context(None)
    assert "No trip" in AIService.build_trip_context({})


def test_route_and_currency():
    trip = {
        "source": {"city": "Mumbai"},
        "destination": {"city": "Bhopal"},
        "currency": "INR",
        "segments": {},
    }
    ctx = AIService.build_trip_context(trip)
    assert "Mumbai -> Bhopal" in ctx
    assert "Currency: INR" in ctx


def test_segments_included():
    trip = {
        "source": {"city": "Delhi"},
        "destination": {"city": "Goa"},
        "currency": "INR",
        "segments": {
            "flight": {"airline": "IndiGo", "flight_no": "6E123", "departure": "08:00",
                       "arrival": "10:00", "stops": 0, "price": "5,000"},
            "train": {"name": "Rajdhani", "train_no": "12951", "class": "2A",
                      "departure": "16:00", "arrival": "08:00", "fare": "2,000"},
            "hotel": {"name": "Taj", "rating": 5, "price": "9,000"},
        },
    }
    ctx = AIService.build_trip_context(trip)
    assert "IndiGo" in ctx and "6E123" in ctx
    assert "Rajdhani" in ctx and "2A" in ctx
    assert "Taj" in ctx


def test_transfer_warning_surfaced():
    trip = {
        "source": {"city": "A"}, "destination": {"city": "B"},
        "segments": {}, "transfer_status": "no_connection",
    }
    ctx = AIService.build_trip_context(trip)
    assert "no_connection" in ctx


def test_ok_transfer_not_warned():
    trip = {
        "source": {"city": "A"}, "destination": {"city": "B"},
        "segments": {}, "transfer_status": "ok",
    }
    assert "transfer" not in AIService.build_trip_context(trip).lower()


def test_itinerary_places_listed():
    trip = {
        "source": {"city": "A"}, "destination": {"city": "B"}, "segments": {},
        "itinerary": [
            {"placeNameEnglish": "Gateway of India"},
            {"placeName": "Marine Drive"},
            "junk",
        ],
    }
    ctx = AIService.build_trip_context(trip)
    assert "Gateway of India" in ctx
    assert "Marine Drive" in ctx


def test_location_as_plain_string():
    trip = {"source": "Pune", "destination": "Nashik", "segments": {}}
    ctx = AIService.build_trip_context(trip)
    assert "Pune -> Nashik" in ctx
