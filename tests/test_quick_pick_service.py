"""Full behavioural coverage for the Quick Pick bundle selector."""
import pytest

from app.services.quick_pick_service import QuickPickService


@pytest.fixture
def qp():
    return QuickPickService()


# --------------------------------------------------------------- price parsing

@pytest.mark.parametrize("raw,expected", [
    ("1,234", 1234.0),
    ("₹2,500.50", 2500.50),
    ("4500", 4500.0),
    ("N/A", 999999999.0),
    ("Sold Out", 999999999.0),
    ("", 999999999.0),
    (None, 999999999.0),
])
def test_parse_price(qp, raw, expected):
    assert qp._parse_price(raw) == expected


# ------------------------------------------------------------ duration parsing

@pytest.mark.parametrize("raw,expected", [
    (120, 120.0),
    ("2h 30m", 150.0),
    ("02:45", 165.0),
    ("90", 90.0),
    (None, 999999999.0),
    ("garbage", 999999999.0),
])
def test_duration_minutes(qp, raw, expected):
    assert qp._duration_minutes(raw) == expected


# ----------------------------------------------------------- arrival timezone

def test_flight_arrival_naive_is_unchanged(qp):
    dt = qp._parse_flight_arrival({"abs_arrival": "2026-06-24T18:00:00"})
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 6, 24, 18, 0)
    assert dt.tzinfo is None


def test_flight_arrival_utc_is_converted_to_ist(qp):
    # 18:00 UTC == 23:30 IST same day
    dt = qp._parse_flight_arrival({"abs_arrival": "2026-06-24T18:00:00+00:00"})
    assert (dt.hour, dt.minute) == (23, 30)
    assert dt.tzinfo is None


def test_flight_arrival_missing_or_bad(qp):
    assert qp._parse_flight_arrival({}) is None
    assert qp._parse_flight_arrival({"abs_arrival": "not-a-date"}) is None


def test_train_departure_both_formats(qp):
    a = qp._parse_train_departure({"departure_date": "24-06-2026", "departure": "22:00"})
    b = qp._parse_train_departure({"departure_date": "2026-06-24", "departure": "22:00"})
    assert a == b


# ----------------------------------------------------------------- ranking

def test_comfort_flights_prefer_fewer_stops(qp):
    flights = [
        {"id": "nonstop-long", "stops": 0, "duration": 240},
        {"id": "onestop-short", "stops": 1, "duration": 120},
    ]
    assert qp._pick_flight(flights, "Comfort")["id"] == "nonstop-long"


def test_budget_flights_prefer_cheapest(qp):
    flights = [
        {"id": "pricey", "stops": 0, "price": "9,000"},
        {"id": "cheap", "stops": 2, "price": "3,000"},
    ]
    assert qp._pick_flight(flights, "Budget")["id"] == "cheap"


def test_comfort_trains_prefer_higher_class(qp):
    trains = [
        {"id": "sleeper", "class": "SL", "duration": "10h 0m"},
        {"id": "ac2", "class": "2A", "duration": "12h 0m"},
    ]
    assert qp._pick_train(trains, "Comfort")["id"] == "ac2"


def test_budget_trains_prefer_cheapest_fare(qp):
    trains = [
        {"id": "ac", "class": "2A", "fare": "2,000"},
        {"id": "sl", "class": "SL", "fare": "500"},
    ]
    assert qp._pick_train(trains, "Budget")["id"] == "sl"


# -------------------------------------------------------- reachable transfers

def test_reachable_filters_by_transfer_buffer(qp):
    flight = {"abs_arrival": "2026-06-24T10:00:00"}  # lands 10:00, +90m => 11:30
    trains = [
        {"id": "too-soon", "departure_date": "24-06-2026", "departure": "11:00"},
        {"id": "ok", "departure_date": "24-06-2026", "departure": "12:00"},
    ]
    reachable, validated = qp._reachable_trains(flight, trains)
    assert validated is True
    assert [t["id"] for t in reachable] == ["ok"]


def test_reachable_unparseable_arrival_returns_all_unvalidated(qp):
    flight = {"abs_arrival": "bad"}
    trains = [{"id": "x", "departure_date": "24-06-2026", "departure": "12:00"}]
    reachable, validated = qp._reachable_trains(flight, trains)
    assert validated is False
    assert reachable == trains


# ----------------------------------------------------- bundle: multi-modal

def _hub_results(train_departure):
    return {
        "multimodal": True,  # international fly-to-gateway-then-train shape
        "hub_flight_fallback": [{"id": "f1", "stops": 0, "abs_arrival": "2026-06-24T10:00:00", "price": "5,000"}],
        "trains": [{"id": "t1", "class": "2A", "fare": "1,000",
                    "departure_date": "24-06-2026", "departure": train_departure}],
        "hotels": [],
    }


def test_multimodal_with_reachable_train_is_ok(qp):
    bundle = qp.select_best_bundle(_hub_results("12:00"), "Comfort")
    assert bundle["flight"]["id"] == "f1"
    assert bundle["train"]["id"] == "t1"
    assert bundle["transfer_status"] == "ok"


def test_multimodal_without_reachable_train_flags_no_connection(qp):
    # Train departs before flight arrival + buffer.
    bundle = qp.select_best_bundle(_hub_results("10:30"), "Comfort")
    assert bundle["flight"]["id"] == "f1"
    assert bundle["transfer_status"] == "no_connection"
    # Still returns a best-effort onward train rather than nothing.
    assert bundle["train"] is not None


def test_multimodal_unverified_when_arrival_unparseable(qp):
    results = _hub_results("12:00")
    results["hub_flight_fallback"][0]["abs_arrival"] = "bad"
    bundle = qp.select_best_bundle(results, "Comfort")
    assert bundle["transfer_status"] == "unverified"


# ----------------------------------------------------- bundle: single mode

def test_budget_picks_cheaper_train_over_flight(qp):
    results = {
        "flights": [{"id": "f", "stops": 0, "price": "5,000"}],
        "trains": [{"id": "t", "class": "SL", "fare": "800"}],
        "hotels": [],
    }
    bundle = qp.select_best_bundle(results, "Budget")
    assert bundle["train"]["id"] == "t"
    assert bundle["flight"] is None
    assert "transfer_status" not in bundle  # single-mode: no transfer flag


def test_budget_picks_cheaper_flight_over_train(qp):
    results = {
        "flights": [{"id": "f", "stops": 0, "price": "900"}],
        "trains": [{"id": "t", "class": "SL", "fare": "3,000"}],
        "hotels": [],
    }
    bundle = qp.select_best_bundle(results, "Budget")
    assert bundle["flight"]["id"] == "f"
    assert bundle["train"] is None


def test_comfort_prefers_flight_when_available(qp):
    results = {
        "flights": [{"id": "f", "stops": 0, "duration": 120}],
        "trains": [{"id": "t", "class": "1A"}],
        "hotels": [],
    }
    bundle = qp.select_best_bundle(results, "Comfort")
    assert bundle["flight"]["id"] == "f"
    assert bundle["train"] is None


def test_comfort_falls_back_to_train_without_flights(qp):
    results = {"flights": [], "trains": [{"id": "t", "class": "2A"}], "hotels": []}
    bundle = qp.select_best_bundle(results, "Comfort")
    assert bundle["flight"] is None
    assert bundle["train"]["id"] == "t"


def test_hub_flight_used_when_no_onward_train(qp):
    # Hill stations (Ooty, Mahabaleshwar): a flight reaches a nearby hub but no
    # train connects onward. The bundle must still offer the hub flight, not be empty.
    results = {
        "hub_flight_fallback": [{"id": "hub", "stops": 0, "price": "5,000"}],
        "flights": [], "trains": [], "hotels": [{"id": "h", "rating": 4, "price": "2,000"}],
    }
    for pref in ("Comfort", "Budget"):
        bundle = qp.select_best_bundle(results, pref)
        assert bundle["flight"] and bundle["flight"]["id"] == "hub", pref
        assert bundle["hotel"] is not None


def test_rail_hub_is_alternative_not_onward(qp):
    # Hill station: a railhead train + a hub flight are ALTERNATIVES (rail_hub set),
    # not a fly-then-train multimodal. Budget should take the cheaper train; Comfort
    # the flight. It must NOT be flagged as a multimodal transfer.
    results = {
        "hub_flight_fallback": [{"id": "f", "stops": 0, "price": "6,000"}],
        "trains": [{"id": "t", "class": "SL", "fare": "900"}],
        "rail_hub": "Coimbatore",
        "hotels": [],
    }
    budget = qp.select_best_bundle(results, "Budget")
    assert budget["train"] and budget["train"]["id"] == "t"
    assert budget["flight"] is None
    assert "transfer_status" not in budget  # not multimodal
    comfort = qp.select_best_bundle(results, "Comfort")
    assert comfort["flight"] and comfort["flight"]["id"] == "f"


def test_comfort_prefers_a_clearly_faster_train(qp):
    # A short-hop flight via a distant hub (6h25m) is slower than the direct
    # train (3h45m) — Comfort should take the train, not the flight.
    results = {
        "flights": [{"id": "f", "stops": 1, "price": "12,000", "duration": "6h 25m"}],
        "trains": [{"id": "t", "class": "3A", "fare": "1,200", "duration": "3:45"}],
        "hotels": [],
    }
    comfort = qp.select_best_bundle(results, "Comfort")
    assert comfort["train"] and comfort["train"]["id"] == "t" and comfort["flight"] is None


def test_comfort_keeps_flight_when_faster(qp):
    # Flight (2h) beats the train (30h) — Comfort flies.
    results = {
        "flights": [{"id": "f", "stops": 0, "price": "5,000", "duration": "2h 0m"}],
        "trains": [{"id": "t", "class": "3A", "fare": "900", "duration": "30:00"}],
        "hotels": [],
    }
    comfort = qp.select_best_bundle(results, "Comfort")
    assert comfort["flight"] and comfort["flight"]["id"] == "f" and comfort["train"] is None


def test_domestic_hub_flight_and_direct_train_are_alternatives(qp):
    # Mount Abu: no own airport (hub flight to Udaipur) + a direct train to its
    # railhead, NO rail_hub and NOT multimodal. Domestically these are
    # ALTERNATIVES, never paired as legs. Budget -> train, Comfort -> flight.
    results = {
        "hub_flight_fallback": [{"id": "f", "stops": 0, "price": "7,000"}],
        "trains": [{"id": "t", "class": "SL", "fare": "800"}],
        "hotels": [],
    }
    budget = qp.select_best_bundle(results, "Budget")
    assert budget["train"] and budget["train"]["id"] == "t" and budget["flight"] is None
    comfort = qp.select_best_bundle(results, "Comfort")
    assert comfort["flight"] and comfort["flight"]["id"] == "f" and comfort["train"] is None
    assert "transfer_status" not in budget and "transfer_status" not in comfort


# ----------------------------------------------------------------- hotels

def test_comfort_hotel_is_highest_rated(qp):
    results = {"flights": [], "trains": [], "hotels": [
        {"id": "a", "rating": 3, "price": "2,000"},
        {"id": "b", "rating": 5, "price": "8,000"},
    ]}
    assert qp.select_best_bundle(results, "Comfort")["hotel"]["id"] == "b"


def test_budget_hotel_is_cheapest(qp):
    results = {"flights": [], "trains": [], "hotels": [
        {"id": "a", "rating": 3, "price": "2,000"},
        {"id": "b", "rating": 5, "price": "8,000"},
    ]}
    assert qp.select_best_bundle(results, "Budget")["hotel"]["id"] == "a"


# --------------------------------------------------------------- empty input

def test_empty_results_returns_all_none(qp):
    bundle = qp.select_best_bundle({}, "Comfort")
    assert bundle["flight"] is None
    assert bundle["train"] is None
    assert bundle["hotel"] is None
    assert bundle["itinerary"] == []
    assert "transfer_status" not in bundle
