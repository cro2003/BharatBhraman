import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from ..utils.ssl_adapter import build_legacy_session

logger = logging.getLogger(__name__)

CITY_STATION_ALIASES = {
    "goa": "Madgaon",
}


class TrainService:
    """
    Provides train search and real-time fare capabilities using hybrid APIs.
    Uses RailYatri for stable station lookups and ConfirmTkt for detailed search and multi-class fares.

    RailYatri and ConfirmTkt reject modern TLS, so requests go through a
    legacy-SSL session (build_legacy_session), and RailYatri/ConfirmTkt expect
    the journey date as DD-MM-YYYY. CITY_STATION_ALIASES is a data-quirk override
    (not a general spelling fix — that's the prefix-fallback in get_station_data):
    RailYatri marks Sanvordem as Goa's poorly-connected "city" node, so 'goa' is
    routed to the real hub, Madgaon.
    """
    def __init__(self):
        """Initializes the train service with legacy SSL support and required headers."""
        self.session = build_legacy_session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }

    @staticmethod
    def _pick_station(items: List[Dict], query: str, state_hint: str = None) -> Optional[Dict]:
        """
        Resolves a query to a city's principal railway station. Picking items[0]
        blindly is wrong: 'Goa' returns 'GOHAD ROAD' (code GOA) first. RailYatri
        marks the canonical city node with is_city=true (e.g. Mumbai -> MMCT,
        Delhi -> NDLS, Jaipur -> JP), so we resolve to that city node first and
        only fall back to station-name / substring matches.

        A state_hint (from the geocoder) disambiguates same-named places — e.g.
        'Dwarka' exists both in Gujarat and as a Delhi locality; without the hint
        the Delhi one (mapped to New Delhi) wins, sending trains to the wrong city.

        Nodes without a real station_code are discarded first: RailYatri sometimes
        returns is_city nodes with null code (e.g. the junk "Dehra Gopipur HP"
        match for "Dehra Dun"), which are useless for a search.
        """
        items = [it for it in (items or []) if it.get('station_code')]
        if not items:
            return None

        if state_hint:
            sh = state_hint.strip().lower()
            in_state = [it for it in items if (it.get('state_name') or '').strip().lower() == sh]
            if in_state:
                items = in_state

        q = (query or "").strip().lower()

        city_node = next(
            (it for it in items
             if it.get('is_city') and (it.get('city_name') or '').strip().lower() == q),
            None,
        )
        if city_node:
            return city_node

        for it in items:
            if (it.get('city_name') or '').strip().lower() == q:
                return it

        for it in items:
            if (it.get('station_name') or '').strip().lower() == q:
                return it
        for it in items:
            if q in (it.get('city_name') or '').lower() or q in (it.get('station_name') or '').lower():
                return it

        return items[0]

    def _search_stations(self, query: str) -> List[Dict]:
        """
        Queries RailYatri for stations. Tries the exact query, then a
        space-collapsed variant (IRCTC city names like "Dehra Dun" don't match
        RailYatri's concatenated "Dehradun"), then progressively shorter prefixes
        (transliteration variants, e.g. 'Chitrakoot' vs 'Chitrakut'). This
        generalises spelling/spacing mismatches without per-city aliases.

        A term is only accepted if at least one returned item carries a real
        station_code — RailYatri sometimes returns a code-less city node for a
        near-miss (e.g. "Dehra Dun" -> "Dehra Gopipur HP"), which must not stop
        the fallback chain.
        """
        url = "https://api.railyatri.in/api/common_city_station_search.json"
        q = (query or "").strip()
        terms = [q]
        collapsed = q.replace(" ", "")
        if collapsed and collapsed != q:
            terms.append(collapsed)
        for length in range(len(q) - 1, 2, -1):
            terms.append(q[:length])
        seen = set()
        ordered = [t for t in terms if t and not (t in seen or seen.add(t))]
        for term in ordered[:7]:
            try:
                resp = self.session.get(url, params={'q': term}, headers=self.headers,
                                        timeout=10, verify=False).json()
                items = resp.get('items', [])
                if any(it.get('station_code') for it in items):
                    return items
            except Exception as exc:
                logger.warning("Station lookup failed for '%s': %s", term, exc)
                return []
        return []

    def get_station_data(self, query: str, state_hint: str = None) -> Optional[Dict]:
        """
        Resolves a city or station name to its official Indian Railways station code.

        :param query: Name of the city or station. Ex: 'Mumbai' or 'Dadar'
        :param state_hint: Optional geocoded state to disambiguate same-named places.
        :return: Dictionary containing 'station_name' and 'station_code', or None.
        """
        search_query = CITY_STATION_ALIASES.get((query or "").strip().lower(), query)
        items = self._search_stations(search_query)
        chosen = self._pick_station(items, search_query, state_hint)
        if chosen:
            return {
                "station_name": chosen.get('station_name'),
                "station_code": chosen.get('station_code'),
            }
        return None

    def get_train_details(self, source_query: str, dest_query: str, date: str, currency_rate: float = 1.0,
                          pref_type: str = "Comfort", source_state: str = None, dest_state: str = None) -> List[Dict]:
        """
        Fetches trains between stations with real-time fares and localized pricing using a step-down class priority.

        :param source_query: Origin city name. Ex: 'Delhi'
        :param dest_query: Destination city name. Ex: 'Mumbai'
        :param date: Journey date. Format: 'DD-MM-YYYY'
        :param currency_rate: Local currency multiplier (1 INR = X local). Ex: 0.012
        :param pref_type: User preference ('Comfort' or 'Budget').
        :param source_state: Optional geocoded state of the origin (disambiguation).
        :param dest_state: Optional geocoded state of the destination (disambiguation).
        :return: List of train dictionaries with number, name, time, class, and fare.
        """
        src = self.get_station_data(source_query, source_state)
        dest = self.get_station_data(dest_query, dest_state)
        
        if not src or not dest: return []

        url = "https://cttrainsapi.confirmtkt.com/api/v1/trains/search"
        params = {
            "sourceStationCode": src['station_code'],
            "destinationStationCode": dest['station_code'],
            "dateOfJourney": date,
            "addAvailabilityCache": "true"
        }

        try:
            resp_raw = self.session.get(url, params=params, headers=self.headers, timeout=15, verify=False)
            data = resp_raw.json()
            raw_trains = data.get('data', {}).get('trainList', [])

            if not raw_trains: return []

            if pref_type == "Comfort":
                pref_classes = ['1A', '2A', 'EC', '3A', '3E', 'CC', 'SL', '2S']
            else:
                pref_classes = ['3A', '3E', 'SL', 'CC', '2A', '1A', 'EC', '2S']

            train_list = []
            for t in raw_trains:
                try:
                    cache = t.get('availabilityCache', {})
                    best_class = "N/A"
                    fare = 0

                    for cls_code in pref_classes:
                        cls_info = cache.get(cls_code)
                        if cls_info and cls_info.get('fare'):
                            best_class = cls_code
                            fare = float(cls_info['fare'])
                            break

                    if fare == 0 and cache:
                        first_cls = next(iter(cache))
                        best_class = first_cls
                        fare = float(cache[first_cls].get('fare', 0) or 0)

                    converted_fare = round(fare * currency_rate, 2)
                    duration_min = t.get('duration')

                    arrival_date = date
                    try:
                        if isinstance(duration_min, int) and t.get('departureTime'):
                            dep_dt = datetime.strptime(f"{date} {t.get('departureTime')}", "%d-%m-%Y %H:%M")
                            arrival_date = (dep_dt + timedelta(minutes=duration_min)).strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        arrival_date = date

                    train_list.append({
                        "train_no": t.get('trainNumber'),
                        "name": t.get('trainName'),
                        "source": t.get('fromStnName'),
                        "departure": t.get('departureTime'),
                        "departure_date": date,
                        "destination": t.get('toStnName'),
                        "arrival": t.get('arrivalTime'),
                        "arrival_date": arrival_date,
                        "duration": f"{duration_min // 60}h {duration_min % 60}m" if isinstance(duration_min, int) else "N/A",
                        "fare": f"{converted_fare:,}" if fare > 0 else "N/A",
                        "class": best_class,
                        "status": "Available"
                    })
                except Exception as exc:
                    logger.warning("Skipping malformed train record: %s", exc)

            return train_list
        except Exception as exc:
            logger.warning("Train search failed %s->%s on %s: %s", source_query, dest_query, date, exc)
            return []
