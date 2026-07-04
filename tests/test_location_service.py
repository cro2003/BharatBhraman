"""Distance maths backing hub-vs-own-airport classification."""
from app.services.location_service import LocationService

# Reference coordinates
BANGALORE = (12.9716, 77.5946)
BLR_AIRPORT = (13.1986, 77.7066)   # ~30 km from city centre
VIDISHA = (23.5251, 77.8081)
BHOPAL_AIRPORT = (23.2875, 77.3374)  # ~55 km from Vidisha


def test_haversine_zero_distance():
    assert LocationService.haversine_km(*BANGALORE, *BANGALORE) == 0


def test_haversine_known_distance_is_symmetric():
    d1 = LocationService.haversine_km(*VIDISHA, *BHOPAL_AIRPORT)
    d2 = LocationService.haversine_km(*BHOPAL_AIRPORT, *VIDISHA)
    assert round(d1, 3) == round(d2, 3)


def test_own_airport_is_near():
    # Bangalore's own airport sits within the hub threshold of its city.
    d = LocationService.haversine_km(*BANGALORE, *BLR_AIRPORT)
    assert d < 40


def test_hub_airport_is_far():
    # Vidisha has no airport; the nearest (Bhopal) is well beyond the threshold.
    d = LocationService.haversine_km(*VIDISHA, *BHOPAL_AIRPORT)
    assert d > 35
