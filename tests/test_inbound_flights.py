"""Inbound-flight / hub resolution: a destination with its own airport must
never be demoted to a hub just because flights are missing on a route/date."""
from app.services.travel_orchestrator import TravelOrchestrator, HUB_DISTANCE_KM


def _orch(candidates, flights_by_iata):
    """Builds an orchestrator with location + flight services stubbed."""
    orch = TravelOrchestrator.__new__(TravelOrchestrator)

    class _Loc:
        def find_airport_candidates(self, lon, lat):
            return candidates

    class _Flight:
        def get_airport_data(self, iata, cc=None):
            return {"code": iata, "cityName": _CITY[iata]}

        def get_flight_details(self, src, dst, date, scc, dcc, rate):
            return flights_by_iata.get(dst, [])

    orch.loc_svc = _Loc()
    orch.flight_svc = _Flight()
    return orch


_CITY = {"IXJ": "Jammu", "ATQ": "Amritsar", "DDN": "Dehra Dun", "DEL": "Delhi"}
_DEST = {"lon": 74.8, "lat": 32.7, "country_code": "IN"}


def test_own_airport_no_flights_does_not_promote_distant_hub():
    # Jammu (IXJ, 0 km) has no flights on this route/date; Amritsar (ATQ, 100 km)
    # does. The old logic flew to Amritsar and added an onward train. It must not.
    candidates = [
        {"iata": "IXJ", "city": "Jammu", "distance_km": 2.0},
        {"iata": "ATQ", "city": "Amritsar", "distance_km": 100.0},
    ]
    orch = _orch(candidates, flights_by_iata={"ATQ": [{"flight_no": "AI1"}]})
    flights, air, is_hub, hub_city = orch._resolve_inbound_flights(
        {"code": "BHO"}, "Bhopal", _DEST, "Jammu", "IN", "IN", "2026-06-28", 1.0)
    assert is_hub is False
    assert hub_city is None
    assert air["cityName"] == "Jammu"   # landed at its own airport, not Amritsar
    assert flights == []                # no flights -> trains handle it


def test_own_airport_with_flights_is_direct():
    candidates = [{"iata": "IXJ", "city": "Jammu", "distance_km": 2.0}]
    orch = _orch(candidates, flights_by_iata={"IXJ": [{"flight_no": "AI9"}]})
    flights, air, is_hub, hub_city = orch._resolve_inbound_flights(
        {"code": "BHO"}, "Bhopal", _DEST, "Jammu", "IN", "IN", "2026-06-28", 1.0)
    assert is_hub is False
    assert len(flights) == 1


def test_no_own_airport_still_promotes_hub():
    # Deep-interior destination (Gangotri): nearest airport is far, so it IS a
    # hub and the onward train is expected.
    candidates = [{"iata": "DDN", "city": "Dehra Dun", "distance_km": 180.0}]
    orch = _orch(candidates, flights_by_iata={"DDN": [{"flight_no": "6E1"}]})
    flights, air, is_hub, hub_city = orch._resolve_inbound_flights(
        {"code": "DEL"}, "Delhi", {"lon": 78.9, "lat": 30.9, "country_code": "IN"},
        "Gangotri", "IN", "IN", "2026-06-28", 1.0)
    assert is_hub is True
    assert hub_city == "Dehra Dun"
    assert len(flights) == 1
