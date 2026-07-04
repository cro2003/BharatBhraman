import logging
import threading
import time
from typing import List, Dict, Optional
from ..utils.ssl_adapter import build_legacy_session

logger = logging.getLogger(__name__)

_SESSION_TTL = 600


class FlightService:
    """
    Provides flight search capabilities using the IRCTC Air API.
    Handles precise airport resolution and real-time flight availability across domestic and international routes.

    IRCTC Air rejects modern TLS, so requests go through a legacy-SSL session
    (build_legacy_session); a SessionId is cached for _SESSION_TTL seconds to
    cut call volume against IRCTC's aggressive rate limiting.
    """
    def __init__(self):
        """Initializes the flight service with a browser-like, legacy-compatible session."""
        self.session = build_legacy_session()
        self.base_url = "https://www.air.irctc.co.in/airstqcNewUserTwo/air"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Origin': 'https://www.air.irctc.co.in',
            'Referer': 'https://www.air.irctc.co.in/',
            'Accept': 'application/json, text/plain, */*'
        }
        self._session_id = None
        self._session_id_at = 0.0
        self._session_lock = threading.Lock()

    def _get_session_id(self) -> Optional[str]:
        """
        Returns a cached IRCTC SessionId, refetching only after the TTL expires.

        Guarded by a lock: this service is a shared singleton hit concurrently by
        the orchestrator's thread-pool fan-out, so the cache read/refresh must not
        race.
        """
        with self._session_lock:
            now = time.time()
            if self._session_id and (now - self._session_id_at) < _SESSION_TTL:
                return self._session_id
            try:
                url = f"{self.base_url}/infos?appType=WEB"
                resp = self.session.get(url, headers=self.headers, verify=False, timeout=10)
                if resp.status_code != 200:
                    return self._session_id
                self._session_id = resp.json().get('SessionId')
                self._session_id_at = now
                return self._session_id
            except Exception as exc:
                logger.warning("IRCTC Air session fetch failed: %s", exc)
                return self._session_id

    def get_airport_data(self, query: str, country_code: str = None) -> Optional[Dict]:
        """
        Resolves a city name or IATA code to its official IRCTC airport object.
        Uses hierarchical matching (Code -> City Name -> Partial Match).

        :param query: City name or 3-letter IATA code. Ex: 'Mumbai' or 'LAX'
        :param country_code: Optional ISO country code for refined filtering. Ex: 'IN' or 'US'
        :return: A dictionary containing 'code', 'cityName', and 'name', or None if not found.
        """
        is_iata = len(query) == 3 and query.isupper()
        search_key = query if is_iata else (f"{query} {country_code}" if country_code else query)
            
        try:
            url = f"{self.base_url}/airportsByKey?searchKey={search_key}"
            resp = self.session.get(url, headers=self.headers, verify=False, timeout=10)
            if resp.status_code != 200:
                return None
            result = resp.json()
            items = result.get('data', [])
            
            if not items:
                if search_key != query:
                    return self.get_airport_data(query)
                return None

            for item in items:
                code = item.get('code', '').upper()
                c_name = item.get('cityName', '').lower()
                q_lower = query.lower()
                if q_lower.upper() == code: return item
                if q_lower == c_name: return item
                
            for item in items:
                c_name = item.get('cityName', '').lower()
                a_name = item.get('name', '').lower()
                q_lower = query.lower()
                if q_lower in c_name or q_lower in a_name: return item
                
            return items[0]
        except Exception as exc:
            logger.warning("Airport lookup failed for '%s': %s", query, exc)
            return None

    def get_flight_details(self, origin_query: str, dest_query: str, date: str, origin_country: str = "IN", dest_country: str = "IN", currency_rate: float = 1.0) -> List[Dict]:
        """
        Fetches real-time flight availability and localizes prices. A missing
        price is surfaced as "N/A" rather than 0, so a price-less flight never
        sorts as the cheapest option.

        :param origin_query: Origin city or code. Ex: 'Delhi'
        :param dest_query: Destination city or code. Ex: 'Mumbai'
        :param date: Departure date. Format: 'YYYY-MM-DD'
        :param origin_country: Origin ISO country code. Default: 'IN'
        :param dest_country: Destination ISO country code. Default: 'IN'
        :param currency_rate: Multiplier for localized pricing (1 INR = X Local). Ex: 0.012
        :return: A list of flight dictionaries with airline, time, duration, and price.
        """
        sid = self._get_session_id()
        origin = self.get_airport_data(origin_query, origin_country)
        dest = self.get_airport_data(dest_query, dest_country)
        
        if not origin or not dest:
            return []

        payload = {
            "tripType": "O", "departureDate": date, "returnDate": "",
            "noOfAdults": "1", "noOfChildren": "0", "noOfInfants": "0",
            "origin": origin['code'],
            "destination": dest['code'],
            "destinationCity": dest['cityName'],
            "originCity": origin['cityName'],
            "classOfTravel": "Economy", "airline": "", "src": "web",
            "isDefence": False, "originCountry": origin_country, "destinationCountry": dest_country,
            "isSeniorCitizen": False, "isStudent": False, "bookingCategory": "0", "eType": "0", "ltc": False
        }

        search_headers = {**self.headers, 'Content-Type': 'application/json'}
        if sid: search_headers['sessionid'] = str(sid)
        
        try:
            url = f"{self.base_url}/search"
            resp = self.session.post(url, headers=search_headers, json=payload, verify=False, timeout=20)
            if resp.status_code != 200: return []
                
            data = resp.json()
            raw_flights = data.get('data', {}).get('flights', [])
            
            processed_flights = []
            for f in raw_flights:
                try:
                    raw_price = f.get('price')
                    if raw_price in (None, "", 0, "0"):
                        price_str = "N/A"
                    else:
                        converted_price = round(float(raw_price) * currency_rate, 2)
                        price_str = f"{converted_price:,}"

                    segments = f.get('lstFlightDetails', [])
                    abs_arrival = segments[-1].get('arrivalDate', '') if segments else ""

                    processed_flights.append({
                        "flight_no": f.get('flightNumber'),
                        "airline": f.get('carrierName'),
                        "source": origin.get('cityName', ''),
                        "destination": dest.get('cityName', ''),
                        "departure": f.get('departureTime'),
                        "arrival": f.get('arrivalTime'),
                        "abs_arrival": abs_arrival,
                        "duration": f.get('duration'),
                        "price": price_str,
                        "stops": f.get('stops', 0),
                        "segments": segments
                    })
                except Exception as exc:
                    logger.warning("Skipping malformed flight record: %s", exc)
            return processed_flights
        except Exception as exc:
            logger.warning("Flight search failed %s->%s on %s: %s", origin_query, dest_query, date, exc)
            return []
