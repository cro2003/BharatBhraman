import logging
import math
import requests
import os
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

PLACE_ALIASES = {
    "sundarbans": "Sundarban West Bengal",
    "sundarban": "Sundarban West Bengal",
}


class LocationService:
    """
    Handles geocoding and proximity-based place discovery using the Geoapify API.
    Used for resolving city coordinates and finding the nearest major airport hubs.
    """
    def __init__(self):
        """Initializes the location service with API keys and base URLs."""
        self.api_key = os.environ.get('LOCATION')
        self.base_v1 = "https://api.geoapify.com/v1"
        self.base_v2 = "https://api.geoapify.com/v2"
        self._capitals = None
        self._wiki_headers = {"User-Agent": "BharatBhraman/1.0 (travel planner)"}

    def country_capital(self, country_code: str) -> str:
        """Capital city for an ISO country code, from country.io (cached)."""
        if self._capitals is None:
            try:
                self._capitals = requests.get("https://country.io/capital.json", timeout=8).json()
            except Exception as exc:
                logger.warning("country.io capital fetch failed: %s", exc)
                self._capitals = {}
        return (self._capitals or {}).get((country_code or "").upper(), "")

    def state_capital(self, name: str) -> str:
        """
        Capital city of a state/admin region via Wikidata's 'capital' property (P36).
        Deterministic and source-backed (no LLM). Returns "" if not found.
        """
        if not name:
            return ""
        base = "https://www.wikidata.org/w/api.php"
        try:
            search = requests.get(base, params={
                "action": "wbsearchentities", "search": name, "language": "en",
                "format": "json", "limit": 5, "type": "item",
            }, headers=self._wiki_headers, timeout=10).json()
        except Exception as exc:
            logger.warning("Wikidata search failed for '%s': %s", name, exc)
            return ""

        admin_words = ("state", "union territory", "province", "country", "region", "territory")
        for hit in search.get("search", []):
            desc = (hit.get("description") or "").lower()
            if not any(w in desc for w in admin_words):
                continue
            try:
                qid = hit["id"]
                ent = requests.get(base, params={
                    "action": "wbgetentities", "ids": qid, "props": "claims", "format": "json",
                }, headers=self._wiki_headers, timeout=10).json()
                claims = ent["entities"][qid]["claims"].get("P36")
                if not claims:
                    continue
                cap_qid = claims[0]["mainsnak"]["datavalue"]["value"]["id"]
                lbl = requests.get(base, params={
                    "action": "wbgetentities", "ids": cap_qid, "props": "labels",
                    "languages": "en", "format": "json",
                }, headers=self._wiki_headers, timeout=10).json()
                return lbl["entities"][cap_qid]["labels"]["en"]["value"]
            except Exception as exc:
                logger.warning("Wikidata capital lookup failed for '%s': %s", name, exc)
                continue
        return ""

    @staticmethod
    def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance in kilometres between two lat/lon points."""
        radius = 6371.0
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (
            math.sin(d_lat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
        )
        return radius * 2 * math.asin(math.sqrt(a))

    def _normalize_location_result(self, result: Optional[Dict]) -> Optional[Dict]:
        """
        Ensures downstream consumers always have a city-like label available,
        preferring the most specific label (district/town over the broad state,
        so 'Nainital' shows Nainital, not 'Uttarakhand').
        """
        if not result:
            return None

        normalized = dict(result)
        city = (
            normalized.get("city")
            or normalized.get("county")
            or normalized.get("name")
            or normalized.get("address_line1")
            or normalized.get("state")
            or normalized.get("formatted")
        )
        if isinstance(city, str) and city and city == city.lower():
            city = city.title()
        normalized["city"] = city
        return normalized

    def get_location_data(self, query: str, near: Optional[tuple] = None) -> Optional[Dict]:
        """
        Resolves a textual city/place into structured coordinate metadata.

        Home market is India: try an India-restricted geocode first (so 'Kochi'
        resolves to Kerala, not Kochi Prefecture in Japan), and only fall back to
        a worldwide search when there's no Indian match (so foreign origins like
        'London' / 'Dubai' still resolve correctly).

        A few region names are ambiguous to the geocoder (their India match is a
        broad region or coincidental amenity, so a bare worldwide search picks a
        same-named foreign place); PLACE_ALIASES maps those to a disambiguated
        India query. place_types are the settlement/region result types trusted
        for an India match; 'county' covers Indian districts used as destinations
        (e.g. Kutch), which geocode as a county, not a settlement.

        ``near`` is an optional ``(lat, lon)`` anchor that biases results toward
        that point, disambiguating same-named places (e.g. the station 'Vijaypur
        Jammu' resolves near Jammu, not the unrelated Vijaypur in MP).
        """
        query = PLACE_ALIASES.get(query.strip().lower(), query)
        url = f"{self.base_v1}/geocode/search"
        base = {"text": query, "format": "json", "apiKey": self.api_key}
        if near and near[0] is not None and near[1] is not None:
            base["bias"] = f"proximity:{near[1]},{near[0]}"
        place_types = {"city", "postcode", "town", "village", "locality",
                       "municipality", "district", "county"}
        try:
            india = requests.get(url, params={**base, "filter": "countrycode:in"}, timeout=10).json()
            results = india.get('results', [])
            top = results[0] if results else None
            if not (top and self._india_match_trusted(top, query, place_types)):
                world = requests.get(url, params=base, timeout=10).json().get('results', [])
                if world:
                    top = world[0]
            return self._normalize_location_result(top) if top else None
        except Exception as exc:
            logger.warning("Geocoding failed for '%s': %s", query, exc)
            return None

    @staticmethod
    def _india_match_trusted(res, query, place_types) -> bool:
        """
        Whether an India-restricted geocode hit is trustworthy. City/town/county
        matches are trusted directly. POSTCODE matches are prone to fuzzy
        cross-name hits — a foreign city name landing on an unrelated Indian
        postcode area ('Tokyo' -> 'Nuner') — so they're trusted only when the
        query actually appears in the result label. Real Indian cities (Bhopal,
        Kochi, Ujjain…) come back as a postcode whose name IS the query, so they
        stay trusted; 'Tokyo' falls through to the worldwide search. The query is
        matched against the settlement name (city/name) only, not the full
        formatted address (which for 'Tokyo' contains the hamlet 'Tokyo Nunar').
        """
        rt = (res or {}).get('result_type')
        if rt not in place_types:
            return False
        if rt != 'postcode':
            return True
        ql = (query or '').strip().lower()
        if not ql:
            return False
        hay = " ".join(str(res.get(k) or "") for k in ("city", "name")).lower()
        return bool(hay.strip()) and (ql in hay or (ql.split()[0] in hay if ql.split() else False))

    def search_locations(self, query: str) -> List[Dict]:
        """Returns a list of potential location matches for user selection (autocomplete)."""
        url = f"{self.base_v1}/geocode/search"
        params = {
            "text": query,
            "format": "json",
            "bias": "countrycode:in",
            "limit": 5,
            "apiKey": self.api_key
        }
        try:
            response = requests.get(url, params=params, timeout=10).json()
            return [
                self._normalize_location_result(result)
                for result in response.get('results', [])
            ]
        except Exception as exc:
            logger.warning("Location autocomplete failed for '%s': %s", query, exc)
            return []

    def find_airport_candidates(self, lon: float, lat: float, radius_km: int = 600, limit: int = 40) -> List[Dict]:
        """
        Returns airports near a point, nearest first, each with a distance_km.
        Used to find a viable hub by expanding outward and flight-checking each
        candidate (Geoapify can't tell us which airports have commercial service,
        so the caller validates by actually searching for flights).
        """
        url = f"{self.base_v2}/places"
        params = {
            "categories": "airport,airport.international",
            "filter": f"circle:{lon},{lat},{radius_km * 1000}",
            "bias": f"proximity:{lon},{lat}",
            "limit": limit,
            "apiKey": self.api_key,
        }
        try:
            response = requests.get(url, params=params, timeout=12).json()
            seen, candidates = set(), []
            for f in response.get('features', []):
                props = f.get('properties', {})
                iata = (props.get('airport', {}) or {}).get('iata') or props.get('ref')
                if not iata or len(str(iata)) != 3:
                    continue
                iata = str(iata).upper()
                if iata in seen:
                    continue
                seen.add(iata)
                a_lat, a_lon = props.get('lat'), props.get('lon')
                distance = self.haversine_km(lat, lon, a_lat, a_lon) if a_lat is not None and a_lon is not None else None
                candidates.append({
                    "iata": iata,
                    "city": props.get('city') or props.get('name'),
                    "name": props.get('name'),
                    "lat": a_lat,
                    "lon": a_lon,
                    "distance_km": distance,
                })
            candidates.sort(key=lambda c: c['distance_km'] if c['distance_km'] is not None else 9999)
            return candidates
        except Exception as exc:
            logger.warning("Airport candidates lookup failed at (%s, %s): %s", lat, lon, exc)
            return []

    def find_nearest_airport(self, lon: float, lat: float, city_name: str = None) -> Optional[Dict]:
        """Finds the nearest major commercial airport hub using coordinate proximity and importance scoring."""
        url = f"{self.base_v2}/places"
        params = {
            "categories": "airport,airport.international",
            "filter": f"circle:{lon},{lat},100000",
            "limit": 20,
            "apiKey": self.api_key
        }
        
        INTL_ORIGIN_GATEWAYS = ["LHR", "LGW", "LCY", "LAX", "JFK", "SFO", "DXB", "SIN"]
        INDIA_METRO_HUBS = ["BOM", "DEL", "BLR", "HYD", "MAA", "CCU"]
        PRIMARY_HUBS = INTL_ORIGIN_GATEWAYS + INDIA_METRO_HUBS

        try:
            response = requests.get(url, params=params, timeout=10).json()
            features = response.get('features', [])
            
            if not features: return None

            candidates = []
            for f in features:
                props = f.get('properties', {})
                name = props.get('name', '').lower()
                city = (props.get('city') or "").lower()
                iata = props.get('airport', {}).get('iata') or props.get('ref')
                a_lon, a_lat = props.get('lon'), props.get('lat')

                if iata and len(str(iata)) == 3:
                    score = 0
                    iata_upper = str(iata).upper()

                    if city_name and (city_name.lower() in name or city_name.lower() in city):
                        score += 100

                    if iata_upper in PRIMARY_HUBS:
                        score += 50

                    score += props.get('rank', {}).get('importance', 0) * 10

                    distance_km = (
                        self.haversine_km(lat, lon, a_lat, a_lon)
                        if a_lat is not None and a_lon is not None else None
                    )

                    candidates.append({
                        "city": props.get('city') or props.get('name'),
                        "iata": iata_upper,
                        "name": props.get('name'),
                        "lat": a_lat,
                        "lon": a_lon,
                        "distance_km": distance_km,
                        "score": score
                    })

            if candidates:
                candidates.sort(key=lambda x: x['score'], reverse=True)
                return candidates[0]

            props = features[0].get('properties', {})
            a_lon, a_lat = props.get('lon'), props.get('lat')
            return {
                "city": props.get('city') or props.get('name'),
                "iata": None,
                "name": props.get('name'),
                "lat": a_lat,
                "lon": a_lon,
                "distance_km": (
                    self.haversine_km(lat, lon, a_lat, a_lon)
                    if a_lat is not None and a_lon is not None else None
                ),
            }
        except Exception as exc:
            logger.warning("Nearest-airport lookup failed at (%s, %s): %s", lat, lon, exc)
            return None
