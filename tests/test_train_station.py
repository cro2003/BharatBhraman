"""Station-picking logic: city-node preference and state disambiguation."""
from app.services.train_service import TrainService


def test_prefers_city_node_over_minor_station():
    # 'Goa' first item is GOHAD ROAD (code GOA); the city node must win.
    items = [
        {"station_name": "GOHAD ROAD", "station_code": "GOA", "is_city": False, "city_name": "GOHAD ROAD"},
        {"station_name": "Madgaon", "station_code": "MAO", "is_city": True, "city_name": "Goa"},
    ]
    assert TrainService._pick_station(items, "Goa")["station_code"] == "MAO"


def test_state_hint_disambiguates_same_named_places():
    # 'Dwarka' exists in Gujarat (DWK) and as a Delhi locality mapped to NDLS.
    items = [
        {"station_name": "DWARKA", "station_code": "DWK", "is_city": False,
         "city_name": "DWARKA", "state_name": "GUJARAT"},
        {"station_name": "NEW DELHI", "station_code": "NDLS", "is_city": True,
         "city_name": "Dwarka", "state_name": "Delhi"},
    ]
    # Without a hint, the is_city Delhi node wins (the original bug).
    assert TrainService._pick_station(items, "Dwarka")["station_code"] == "NDLS"
    # With the geocoded state, the Gujarat station is chosen.
    assert TrainService._pick_station(items, "Dwarka", "Gujarat")["station_code"] == "DWK"


def test_state_hint_ignored_when_no_match():
    items = [{"station_name": "JAIPUR", "station_code": "JP", "is_city": True,
              "city_name": "Jaipur", "state_name": "RAJASTHAN"}]
    # A non-matching hint must not discard the only sensible result.
    assert TrainService._pick_station(items, "Jaipur", "Kerala")["station_code"] == "JP"


def test_exact_station_name_match():
    items = [
        {"station_name": "Some Junction", "station_code": "SJN", "is_city": False, "city_name": "Elsewhere"},
        {"station_name": "Dadar", "station_code": "DR", "is_city": False, "city_name": "Mumbai"},
    ]
    assert TrainService._pick_station(items, "Dadar")["station_code"] == "DR"


def test_empty_items_returns_none():
    assert TrainService._pick_station([], "Anywhere") is None


def test_skips_code_less_city_node():
    # RailYatri returned a junk is_city node with a null code for "Dehra Dun"
    # ("Dehra Gopipur HP"). A code-less node is unusable and must be skipped in
    # favour of the real station, never selected as items[0].
    items = [
        {"station_name": None, "station_code": None, "is_city": True,
         "city_name": "Dehra Gopipur HP"},
        {"station_name": "DEHRADUN", "station_code": "DDN", "is_city": True,
         "city_name": "Dehradun"},
    ]
    assert TrainService._pick_station(items, "Dehra Dun")["station_code"] == "DDN"


def test_all_code_less_items_returns_none():
    items = [{"station_name": None, "station_code": None, "is_city": True,
              "city_name": "Junk"}]
    assert TrainService._pick_station(items, "Junk") is None
