"""
Quick Pick auto-selection logic.

IST is a fixed offset (India has a single timezone with no DST, avoiding a
tzdata dependency). Flight arrivals may be tz-aware/UTC while train departures
are always local IST, so everything is normalised to IST-naive before comparison
for the transfer-buffer maths. TRAIN_CLASS_RANK orders Indian Railways classes
by comfort (higher == more comfortable): 1A First AC, EC Executive Chair Car,
2A Second AC, 3A Third AC, 3E Third AC Economy, CC Chair Car, SL Sleeper,
2S Second Sitting.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

TRAIN_CLASS_RANK = {
    "1A": 7,
    "EC": 6,
    "2A": 5,
    "3A": 4,
    "3E": 3,
    "CC": 2,
    "SL": 1,
    "2S": 0,
}

_INF = 999999999.0


class QuickPickService:
    """
    Handles the automated selection logic for the 'Quick Pick' feature.
    Intelligently bundles flights, trains, and hotels based on 'Comfort' or
    'Budget' preferences, validating flight->train transfers where the
    destination is reached via a hub airport plus an onward train.
    """

    def __init__(self):
        """Initializes the quick pick service."""
        self.min_transfer_minutes = 90

    def _parse_price(self, price_str) -> float:
        """Converts a formatted price string to a comparable float."""
        if not price_str or price_str == "N/A" or "Sold" in str(price_str):
            return _INF
        try:
            clean = re.sub(r'[^\d.]', '', str(price_str))
            return float(clean) if clean else _INF
        except Exception:
            return _INF

    def _parse_flight_arrival(self, flight: Optional[Dict]) -> Optional[datetime]:
        """Parses a flight's absolute arrival into an IST-naive datetime."""
        arrival_iso = (flight or {}).get("abs_arrival")
        if not arrival_iso:
            return None
        try:
            dt = datetime.fromisoformat(arrival_iso)
        except Exception:
            return None
        if dt.tzinfo is not None:
            dt = dt.astimezone(IST).replace(tzinfo=None)
        return dt

    def _parse_train_departure(self, train: Optional[Dict]) -> Optional[datetime]:
        """Parses a train's departure (IST-naive). Tolerates either date format."""
        if not train:
            return None
        departure_date = train.get("departure_date")
        departure_time = train.get("departure")
        if not departure_date or not departure_time:
            return None
        for fmt in ("%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(f"{departure_date} {departure_time}", fmt)
            except Exception:
                continue
        return None

    @staticmethod
    def _duration_minutes(value) -> float:
        """
        Best-effort parse of a travel duration into minutes for comfort ranking.
        Accepts ints (minutes), 'Xh Ym', or 'HH:MM'. Unknown -> infinity (sorts last).
        """
        if value is None:
            return _INF
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        m = re.search(r'(\d+)\s*h\s*(\d+)\s*m', text)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        if ":" in text:
            try:
                h, mn = text.split(":")[:2]
                return int(h) * 60 + int(mn)
            except Exception:
                pass
        digits = re.sub(r'[^\d]', '', text)
        return float(digits) if digits else _INF

    def _sort_flights(self, flights: List[Dict], preference: str) -> List[Dict]:
        if preference == "Budget":
            return sorted(flights, key=lambda f: self._parse_price(f.get('price')))
        return sorted(
            flights,
            key=lambda f: (int(f.get('stops') or 0), self._duration_minutes(f.get('duration'))),
        )

    def _sort_trains(self, trains: List[Dict], preference: str) -> List[Dict]:
        if preference == "Budget":
            return sorted(trains, key=lambda t: self._parse_price(t.get('fare')))
        return sorted(
            trains,
            key=lambda t: (
                -TRAIN_CLASS_RANK.get(t.get('class', ''), -1),
                self._duration_minutes(t.get('duration')),
            ),
        )

    def _pick_flight(self, flights: List[Dict], preference: str) -> Optional[Dict]:
        ordered = self._sort_flights(flights, preference) if flights else []
        return ordered[0] if ordered else None

    def _pick_train(self, trains: List[Dict], preference: str) -> Optional[Dict]:
        ordered = self._sort_trains(trains, preference) if trains else []
        return ordered[0] if ordered else None

    def _pick_hotel(self, hotels: List[Dict], preference: str) -> Optional[Dict]:
        if not hotels:
            return None
        if preference == "Comfort":
            return sorted(hotels, key=lambda x: float(x.get('rating', 0) or 0), reverse=True)[0]
        return sorted(hotels, key=lambda x: self._parse_price(x.get('price')))[0]

    def _reachable_trains(self, flight: Optional[Dict], trains: List[Dict]) -> Tuple[List[Dict], bool]:
        """
        Filters trains departing at least ``min_transfer_minutes`` after the
        flight lands. Returns (reachable, validated). ``validated`` is False when
        the flight arrival could not be parsed — in that case the full list is
        returned as a best effort, but the caller must treat the connection as
        unverified rather than guaranteed.
        """
        arrival_dt = self._parse_flight_arrival(flight)
        if not arrival_dt:
            return trains, False

        minimum_departure = arrival_dt + timedelta(minutes=self.min_transfer_minutes)
        reachable = [
            t for t in trains
            if (dep := self._parse_train_departure(t)) and dep >= minimum_departure
        ]
        return reachable, True

    def select_best_bundle(self, results: Dict, preference: str = "Comfort") -> Dict:
        """
        Automatically selects the most suitable travel segments for the persona.

        Only an INTERNATIONAL fly-to-gateway-THEN-train trip (results['multimodal'])
        pairs a hub flight with an onward train; domestically a hub flight and a
        train are ALTERNATIVES (e.g. Mount Abu: fly to Udaipur OR train to Abu
        Road), never paired. In single-mode, when the destination has no airport
        and no connecting train, the hub flights are still offered (last leg by
        road) so hill stations like Ooty/Mahabaleshwar don't produce an empty
        bundle. In Comfort mode flying is preferred, but a clearly-faster direct
        train wins (a short hop routed via a distant hub — Bhopal->Delhi->Indore
        6h25m — can be slower than the 3h45m direct train).
        """
        flight: Optional[Dict] = None
        train: Optional[Dict] = None
        transfer_status: Optional[str] = None

        direct_flights = results.get('flights', []) or []
        fallback_flights = results.get('hub_flight_fallback', []) or []
        trains = results.get('trains', []) or []

        is_multi_modal = bool(results.get('multimodal')) and bool(fallback_flights and trains)

        if is_multi_modal:
            candidate_flights = self._sort_flights(fallback_flights, preference)
            saw_validation = False

            for candidate in candidate_flights:
                reachable, validated = self._reachable_trains(candidate, trains)
                saw_validation = saw_validation or validated
                if reachable:
                    flight = candidate
                    train = self._pick_train(reachable, preference)
                    transfer_status = "ok" if validated else "unverified"
                    break

            if flight is None:
                flight = candidate_flights[0] if candidate_flights else None
                train = self._pick_train(trains, preference)
                transfer_status = "no_connection" if saw_validation else "unverified"

        else:
            available_flights = direct_flights or fallback_flights

            if preference == "Budget":
                cheapest_f = self._pick_flight(available_flights, "Budget")
                cheapest_t = self._pick_train(trains, "Budget")
                f_price = self._parse_price(cheapest_f.get('price')) if cheapest_f else _INF
                t_price = self._parse_price(cheapest_t.get('fare')) if cheapest_t else _INF

                if cheapest_t and t_price <= f_price:
                    train = cheapest_t
                elif cheapest_f:
                    flight = cheapest_f
                elif cheapest_t:
                    train = cheapest_t
            else:
                flight = self._pick_flight(available_flights, "Comfort")
                best_train = self._pick_train(trains, "Comfort")
                if flight is None:
                    train = best_train
                elif best_train:
                    f_min = self._duration_minutes(flight.get('duration'))
                    t_min = self._duration_minutes(best_train.get('duration'))
                    if f_min != _INF and t_min != _INF and t_min < f_min:
                        flight, train = None, best_train

        hotel = self._pick_hotel(results.get('hotels', []) or [], preference)

        bundle = {
            "flight": flight,
            "train": train,
            "hotel": hotel,
            "itinerary": results.get('itinerary', []),
        }
        if is_multi_modal:
            bundle["transfer_status"] = transfer_status
        return bundle
