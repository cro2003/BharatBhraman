"""
Travel search orchestration.

Constants:
- HUB_DISTANCE_KM: if the nearest airport to the destination is farther than
  this, the destination has no airport of its own and we fly to that hub and
  continue by train.
- TRANSFER_MAX_KM: longest road transfer surfaced as a "cab to the destination"
  leg; beyond this the gap is a regional hop, not a last-mile cab (e.g. Delhi for
  Leh, 600+ km), so the cab note is omitted.
- ONWARD_TRAIN_BUFFER_MIN: buffer after a flight lands before an onward train can
  realistically be caught.
- INDIAN_INTL_GATEWAYS: major Indian airports with broad international
  connectivity; for an international trip into a remote Indian town the inbound
  flight lands at the nearest of these and the journey completes by train.
- RAILLESS_STATES: states/UTs with no usable passenger railway AND no
  road-reachable railhead in a neighbouring state, so searching trains there only
  yields name-collision matches elsewhere (e.g. "Havelock" -> a Ghaziabad
  station). These are flight-only. NE hill states and Sikkim are deliberately
  EXCLUDED: their standard railheads (New Jalpaiguri for Sikkim/Darjeeling,
  Guwahati for Meghalaya/Arunachal, Dimapur for Nagaland) sit in a neighbouring
  state within road range, so the railhead fallback there is genuinely useful.

The background search worker runs on a daemon thread (create_search_job), not in
a request context, so it never touches flask.session/g — everything is passed as
args and persisted to the job doc.
"""
import logging
import threading
import concurrent.futures
import uuid
import datetime
from typing import Dict, Optional
from .flight_service import FlightService
from .train_service import TrainService
from .hotel_service import HotelService
from .location_service import LocationService
from .ai_service import AIService
from .currency_service import CurrencyService
from ..database.connection import db

logger = logging.getLogger(__name__)

HUB_DISTANCE_KM = 50.0

TRANSFER_MAX_KM = 250.0

ONWARD_TRAIN_BUFFER_MIN = 90

STALE_JOB_SECONDS = 300

INDIAN_INTL_GATEWAYS = [
    {"iata": "DEL", "city": "Delhi", "lat": 28.5562, "lon": 77.1000},
    {"iata": "BOM", "city": "Mumbai", "lat": 19.0896, "lon": 72.8656},
    {"iata": "BLR", "city": "Bengaluru", "lat": 13.1986, "lon": 77.7066},
    {"iata": "MAA", "city": "Chennai", "lat": 12.9941, "lon": 80.1709},
    {"iata": "HYD", "city": "Hyderabad", "lat": 17.2403, "lon": 78.4294},
    {"iata": "CCU", "city": "Kolkata", "lat": 22.6547, "lon": 88.4467},
]

RAILLESS_STATES = {
    "andaman and nicobar islands",
    "lakshadweep",
    "ladakh",
}


def _train_departs_after(train: Dict, arrival_dt: datetime.datetime,
                         buffer_min: int = ONWARD_TRAIN_BUFFER_MIN) -> bool:
    """
    True if a train can be caught after a flight that lands at ``arrival_dt``
    (departs at least ``buffer_min`` later, or on a later day). Trains whose
    departure can't be parsed are treated as catchable (don't exclude them).
    """
    dd = (train.get('departure_date') or '').strip()
    tt = (train.get('departure') or '').strip()
    if not dd:
        return True
    base = None
    for fmt in ('%d-%m-%Y', '%Y-%m-%d'):
        try:
            base = datetime.datetime.strptime(dd, fmt)
            break
        except ValueError:
            continue
    if base is None:
        return True
    try:
        hh, mm = (int(x) for x in tt.split(':')[:2])
        dep = base.replace(hour=hh, minute=mm)
    except (ValueError, IndexError):
        dep = base
    return dep >= arrival_dt + datetime.timedelta(minutes=buffer_min)


class TravelOrchestrator:
    """
    The central coordinator for all travel-related searches.
    Manages background asynchronous jobs and synchronizes complex multi-modal segments
    to ensure time-synchronized itineraries (e.g., flight arrival vs train departure).
    """
    def __init__(self):
        """Initializes the orchestrator with all modular travel and logic services."""
        self.flight_svc = FlightService()
        self.train_svc = TrainService()
        self.hotel_svc = HotelService()
        self.loc_svc = LocationService()
        self.ai_svc = AIService()
        self.curr_svc = CurrencyService()
        self.jobs = db['trip_jobs']
        self.place_capitals = db['place_capitals']

    ADMIN_RESULT_TYPES = {"state", "country"}

    def _resolve_location(self, query: str) -> Optional[Dict]:
        """
        Resolves user input to a city. The app plans at city level, so if the
        input is a state/country (e.g. 'Kerala', 'India'), it is mapped to that
        area's capital city and re-geocoded. A 'county' (district, e.g. Nainital)
        is intentionally NOT treated as an admin area — it keeps its own town name
        rather than jumping to the state capital.
        """
        loc = self.loc_svc.get_location_data(query)
        if not loc or loc.get('result_type') not in self.ADMIN_RESULT_TYPES:
            return loc

        name = loc.get('state') or loc.get('city') or loc.get('name') or query
        country = loc.get('country') or ""
        country_code = loc.get('country_code') or ""
        capital = self._capital_for(name, loc.get('result_type'), country_code)
        if not capital or capital.lower() == (name or "").lower():
            return loc

        city_loc = self.loc_svc.get_location_data(f"{capital}, {country}" if country else capital)
        if city_loc and city_loc.get('result_type') not in self.ADMIN_RESULT_TYPES:
            logger.info("Resolved %s '%s' to capital city '%s'", loc.get('result_type'), name, capital)
            return city_loc
        return loc

    def _capital_for(self, name: str, admin_type: str, country_code: str) -> str:
        """
        Returns the capital city for a state/country using deterministic sources
        (country.io for countries, Wikidata for states), cached in MongoDB.
        """
        cache_id = f"{admin_type}:{(name or '').lower()}:{(country_code or '').lower()}"
        try:
            cached = self.place_capitals.find_one({"_id": cache_id})
            if cached:
                return cached.get("capital", "")
        except Exception:
            pass

        if admin_type == "country":
            capital = self.loc_svc.country_capital(country_code)
        else:
            capital = self.loc_svc.state_capital(name)

        if capital:
            try:
                self.place_capitals.update_one(
                    {"_id": cache_id}, {"$set": {"capital": capital}}, upsert=True
                )
            except Exception as exc:
                logger.warning("Could not cache capital for '%s': %s", name, exc)
        return capital

    def _resolve_inbound_flights(self, src_airport, src_label, dest_loc, dest_label,
                                 src_cc, dest_cc, date, rate):
        """
        Determines which airport to fly into and the flights to it, by trying
        candidate airports from nearest outward and validating that flights
        actually exist (rather than assuming the nearest airport has service).

        For international trips into India the candidate pool is augmented with
        major gateways, because no data source reliably flags which Indian
        airports have international service.

        Airports within HUB_DISTANCE_KM are all "local" to the destination —
        flying into any counts as reaching it directly (a short cab), not a hub
        needing an onward train — and all are tried nearest-first (a city can have
        a tiny serviceless airport beside a larger one, e.g. Darjeeling: Pakyong
        39km no flights, Bagdogra 40km with flights). This also stops a distant
        airport being promoted to a hub when the destination has its own service
        (the Jammu case). A foreign airport is never used for an Indian
        destination — border towns (e.g. Tawang) have Chinese/Myanmar airports
        among their nearest candidates.

        is_dest_hub is True only when we land at a different city than the
        destination (far away and names don't match) — so London->Mumbai, landing
        at Mumbai's own airport, stays a direct flight, not a hub.

        Returns (flights, hub_airport, is_dest_hub, hub_city).
        """
        src_code = src_airport['code'] if src_airport else src_label
        is_intl = src_cc != dest_cc

        nearby = self.loc_svc.find_airport_candidates(dest_loc['lon'], dest_loc['lat'])

        own_airports = [c for c in nearby if (c.get('distance_km') or 1e9) <= HUB_DISTANCE_KM]

        order = list(nearby)
        if not is_intl and own_airports:
            order = own_airports
        elif is_intl and dest_cc == "IN":
            gateways = sorted(
                INDIAN_INTL_GATEWAYS,
                key=lambda g: LocationService.haversine_km(dest_loc['lat'], dest_loc['lon'], g['lat'], g['lon']),
            )
            gw_cands = [{
                "iata": g["iata"], "city": g["city"], "name": g["city"],
                "lat": g["lat"], "lon": g["lon"],
                "distance_km": LocationService.haversine_km(dest_loc['lat'], dest_loc['lon'], g['lat'], g['lon']),
            } for g in gateways]
            order = nearby[:1] + gw_cands

        chosen_air = chosen_cand = None
        flights = []
        tried, seen = 0, set()
        for cand in order:
            if tried >= 6:
                break
            if cand['iata'] in seen:
                continue
            seen.add(cand['iata'])
            air = self.flight_svc.get_airport_data(cand['iata'], dest_cc)
            if not air:
                continue
            if dest_cc == "IN" and (air.get('countryCode') or "IN").upper() != "IN":
                continue
            tried += 1
            fl = self.flight_svc.get_flight_details(src_code, air['code'], date, src_cc, dest_cc, rate)
            if fl:
                chosen_air, chosen_cand, flights = air, cand, fl
                break

        if chosen_cand is None:
            fallback = order[0] if order else None
            if fallback:
                chosen_cand = fallback
                chosen_air = self.flight_svc.get_airport_data(fallback['iata'], dest_cc)

        if chosen_cand is None:
            return [], None, False, None

        distance = chosen_cand.get('distance_km')
        airport_city = (chosen_air.get('cityName') if chosen_air else chosen_cand.get('city')) or ''
        name_match = bool(dest_label) and dest_label.lower() in airport_city.lower()
        is_dest_hub = distance is not None and distance > HUB_DISTANCE_KM and not name_match
        hub_city = airport_city if is_dest_hub else None
        return flights, chosen_air, is_dest_hub, hub_city

    def _dest_gateway_city(self, dest_loc: Dict, dest_label: str) -> Optional[str]:
        """
        The destination's local gateway city — the city of the airport nearest the
        destination, which also serves as its nearest railhead (e.g. Dehradun for
        Gangotri). Returns None when the destination has its own nearby airport
        (i.e. it's not a deep-interior place needing an external railhead).
        """
        try:
            cands = self.loc_svc.find_airport_candidates(dest_loc['lon'], dest_loc['lat'])
        except Exception:
            return None
        if not cands:
            return None
        nearest = cands[0]
        if (nearest.get('distance_km') or 0) <= HUB_DISTANCE_KM:
            return None
        air = self.flight_svc.get_airport_data(nearest['iata'], dest_loc.get('country_code', 'IN').upper())
        city = (air.get('cityName') if air else None) or nearest.get('city')
        if city and city.strip().lower() != (dest_label or "").strip().lower():
            return city
        return None

    def _railhead_is_near(self, railhead: str, dest_loc: Dict, max_km: float = 250.0) -> bool:
        """
        True if a candidate railhead city geocodes to within ``max_km`` of the
        destination. Guards against name-collision railheads far from the
        destination (e.g. 'Butte' for Tawang, a state name resolving cross-state)
        that would otherwise produce a train to the wrong part of the country.
        """
        if dest_loc.get('lat') is None:
            return True
        try:
            rl = self.loc_svc.get_location_data(railhead, near=(dest_loc['lat'], dest_loc['lon']))
            if not rl:
                return False
            km = LocationService.haversine_km(dest_loc['lat'], dest_loc['lon'], rl['lat'], rl['lon'])
            return km <= max_km
        except Exception:
            return True

    def _geo_km(self, place: str, dest_loc: Dict) -> Optional[float]:
        """
        Road-transfer distance (rounded km) from a gateway city/railhead to the
        destination. Used to tell the traveller how far the last leg is when the
        train/flight only reaches a nearby hub (e.g. Pathankot -> Kangra ~64km).
        Returns None when it can't be measured.
        """
        if not place or dest_loc.get('lat') is None:
            return None
        try:
            pl = self.loc_svc.get_location_data(place, near=(dest_loc['lat'], dest_loc['lon']))
            if not pl or pl.get('lat') is None:
                return None
            km = LocationService.haversine_km(
                dest_loc['lat'], dest_loc['lon'], pl['lat'], pl['lon'])
            return round(km)
        except Exception:
            return None

    def _station_is_near_dest(self, station: str, dest_loc: Dict, max_km: float = 30.0) -> bool:
        """
        True if a direct-train destination station is within ``max_km`` of the
        actual destination (or can't be verified). Guards against fuzzy station
        matches for STATIONLESS places — 'Gangotri'/'Chopta' have no station and
        RailYatri fuzzy-matches an unrelated one, which would otherwise block the
        railhead fallback (Dehradun) + its cab.
        """
        if not station or dest_loc.get('lat') is None:
            return True
        try:
            sl = self.loc_svc.get_location_data(station, near=(dest_loc['lat'], dest_loc['lon']))
            if not sl or sl.get('lat') is None:
                return True
            km = LocationService.haversine_km(
                dest_loc['lat'], dest_loc['lon'], sl['lat'], sl['lon'])
            return km <= max_km
        except Exception:
            return True

    def _salvage_hub_flight(self, src_code, src_label, dest_loc, src_cc, dest_cc, date, rate):
        """
        Last-resort transport for a remote destination that yielded no flights,
        no trains and no railhead: fly to the nearest MAJOR gateway with service
        from the origin, so the trip is never empty (the last leg is an onward
        connection/road). Limited to the two nearest gateways — they are
        well-connected and answer fast, so this can't stall the job the way
        probing obscure regional airports (repeated 20s timeouts) would.
        Returns (flights, hub_city) or ([], None).
        """
        gateways = sorted(
            INDIAN_INTL_GATEWAYS,
            key=lambda g: LocationService.haversine_km(dest_loc['lat'], dest_loc['lon'], g['lat'], g['lon']),
        )
        for g in gateways[:2]:
            air = self.flight_svc.get_airport_data(g['iata'], dest_cc)
            if not air:
                continue
            fl = self.flight_svc.get_flight_details(src_code, air['code'], date, src_cc, dest_cc, rate)
            if fl:
                return fl, g['city']
        return [], None

    @staticmethod
    def _location_label(location: Optional[Dict]) -> str:
        """Builds a stable city-like label from geocoder results."""
        if not location:
            return ""
        return (
            location.get("city")
            or location.get("state")
            or location.get("county")
            or location.get("name")
            or location.get("address_line1")
            or location.get("formatted")
            or ""
        )

    def create_search_job(self, origin: str, destination: str, date: str, preferences: str,
                          language: str = "English", mode: str = "quickpick") -> str:
        """
        Starts a background search job and returns a unique Job ID for polling.

        :param origin: Textual origin. Ex: 'Mumbai'
        :param destination: Textual destination. Ex: 'Vidisha'
        :param date: Departure date. Format: 'YYYY-MM-DD'
        :param preferences: User persona. Format: 'Comfort' or 'Budget'
        :param language: Output language for AI content. Ex: 'Hindi'
        :param mode: 'quickpick' (one-shot full bundle) or 'manual' (progressive:
            flights first, hotels in the background, trains fetched on-demand per
            chosen flight via resolve_trains_for_flight).
        :return: A unique string job_id.
        """
        job_id = str(uuid.uuid4())
        job_doc = {
            "job_id": job_id,
            "status": "processing",
            "mode": mode,
            "stage": "starting",
            "progress": 0,
            "results": {},
            "created_at": datetime.datetime.now(datetime.timezone.utc)
        }
        self.jobs.insert_one(job_doc)

        target = self._run_manual_search if mode == "manual" else self._run_synchronized_search
        worker = threading.Thread(
            target=target,
            args=(job_id, origin, destination, date, preferences, language),
            daemon=True
        )
        worker.start()

        return job_id

    def _prepare_search(self, job_id, origin, destination, date, preferences, language):
        """
        Shared phase 1 for both search modes: resolve locations, currency, inbound
        flights and the AI itinerary. On failure it marks the job failed and
        returns (None, None). On success returns (results, ctx) where ``results``
        already holds source/destination/currency/flights/itinerary and ``ctx``
        carries everything the onward-train resolution needs.

        Fails the job when the destination is outside India (BharatBhraman plans
        trips within India only; the origin may be abroad — an inbound tourist),
        or when origin and destination are effectively the same place (spelled
        differently — 'Delhi'/'New Delhi' both resolve to New Delhi, or <8 km
        apart by geodistance).
        """
        src_loc = self._resolve_location(origin)
        dest_loc = self._resolve_location(destination)
        if not src_loc or not dest_loc:
            self.jobs.update_one({"job_id": job_id}, {"$set": {"status": "failed", "error": "Invalid locations"}})
            return None, None

        if (dest_loc.get('country_code') or '').upper() != "IN":
            where = self._location_label(dest_loc) or destination
            self.jobs.update_one({"job_id": job_id}, {"$set": {
                "status": "failed",
                "error_code": "DESTINATION_OUTSIDE_INDIA",
                "error": f"BharatBhraman only plans trips within India — '{where}' is outside India. "
                         f"Please choose a destination in India.",
            }})
            return None, None

        src_label = self._location_label(src_loc)
        dest_label = self._location_label(dest_loc)

        same = bool(src_label and src_label.strip().lower() == (dest_label or '').strip().lower())
        if not same and src_loc.get('lat') is not None and dest_loc.get('lat') is not None:
            try:
                same = LocationService.haversine_km(
                    src_loc['lat'], src_loc['lon'], dest_loc['lat'], dest_loc['lon']) < 8
            except Exception:
                same = False
        if same:
            self.jobs.update_one({"job_id": job_id}, {"$set": {
                "status": "failed", "error_code": "SAME_ORIGIN_DESTINATION",
                "error": "Origin and destination are the same place. Please choose a different destination.",
            }})
            return None, None

        curr_data = self.curr_svc.get_rate_info(src_loc.get('country_code', 'IN'))
        rate = curr_data['rate']
        src_cc = src_loc.get('country_code', 'IN').upper()
        dest_cc = dest_loc.get('country_code', 'IN').upper()

        src_hub_info = self.loc_svc.find_nearest_airport(src_loc['lon'], src_loc['lat'], src_label)
        src_query = src_hub_info['iata'] if src_hub_info and src_hub_info['iata'] else src_label
        src_airport = self.flight_svc.get_airport_data(src_query, src_cc)

        is_international = src_cc != dest_cc
        results = {"source": src_loc, "destination": dest_loc, "currency": curr_data['code']}

        itinerary_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        f_itinerary = itinerary_executor.submit(self.ai_svc.get_itinerary_content, dest_label, language)

        flights, dest_airport, is_dest_hub, hub_city = self._resolve_inbound_flights(
            src_airport, src_label, dest_loc, dest_label, src_cc, dest_cc, date, rate
        )
        results['flights' if not is_dest_hub else 'hub_flight_fallback'] = flights

        try:
            results['itinerary'] = f_itinerary.result()
        except Exception as exc:
            logger.warning("Itinerary generation failed for '%s': %s", dest_label, exc)
            results['itinerary'] = []
        finally:
            itinerary_executor.shutdown(wait=False)

        ctx = {
            "src_loc": src_loc, "dest_loc": dest_loc,
            "src_label": src_label, "dest_label": dest_label,
            "src_cc": src_cc, "dest_cc": dest_cc, "src_query": src_query,
            "is_international": is_international, "is_dest_hub": is_dest_hub,
            "hub_city": hub_city, "rate": rate, "preferences": preferences, "date": date,
        }
        return results, ctx

    @staticmethod
    def _hotel_dates(flight, date):
        """Check-in/out for the destination hotel, rolled to the flight's arrival day."""
        check_in = date
        if flight and flight.get('abs_arrival'):
            try:
                check_in = datetime.datetime.fromisoformat(flight['abs_arrival']).strftime('%Y-%m-%d')
            except Exception:
                pass
        check_out = (datetime.datetime.strptime(check_in, '%Y-%m-%d')
                     + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        return check_in, check_out

    def _resolve_onward_and_transfer(self, results, ctx, flight):
        """
        Resolve onward train(s) + cab transfer for a chosen flight and merge them
        into ``results``. Shared by the synchronized (quick-pick) worker — called
        with the best flight — and the on-demand manual endpoint — called with the
        user's chosen flight. Handles every source/destination/preference: direct
        trains, hub-flight onward trains, the railhead fallback, railless UTs and
        the salvage hub-flight. Mutates: trains, rail_hub, transfer, hub_city,
        flight_arrival_iso, and (on salvage) hub_flight_fallback.

        Key behaviours:
        - Train dates are sent to the providers as DD-MM-YYYY (converted here from
          the internal YYYY-MM-DD); the train search rolls to the flight's arrival
          day, and a late arrival (hour >= 20) triggers an extra next-day search.
        - Domestic trips ALWAYS try a direct origin->dest train first (Bhopal->
          Ujjain uses the direct train, not fly-to-Indore + onward). Only an
          INTERNATIONAL trip boards the onward train at the arrival gateway
          (onward_from_hub) — you can't rail in from abroad. This "fly THEN train"
          is the only genuine multimodal shape; domestically flight and train are
          alternatives, not legs, hence results['multimodal']. An international
          origin to a directly-flyable destination (Norway->Delhi) has NO train
          leg — searching from the foreign city returns garbage matches.
        - A fuzzy direct-train match to a station far from the destination
          (stationless places like Gangotri/Chopta) is dropped so the railhead
          fallback resolves the real railhead + cab instead. When the destination
          has no station, the railhead candidates include airport towns near it
          (which double as mainline railheads, e.g. Pathankot for Kangra, Kota for
          Bundi), each resolved via IRCTC for a trustworthy Indian city name, and
          an international trip boards its onward railhead train at the arrival
          gateway (e.g. London->Darjeeling: Kolkata->Bagdogra).
        - A final cab leg is added only when the train stops at a railhead in a
          different town, or when there's no train and the flight lands at an
          airport in a different city — not when the train/flight already reaches
          the destination's own station/airport.
        """
        dest_loc = ctx['dest_loc']; src_loc = ctx['src_loc']
        src_label = ctx['src_label']; dest_label = ctx['dest_label']
        dest_cc = ctx['dest_cc']; src_cc = ctx['src_cc']
        is_international = ctx['is_international']
        is_dest_hub = ctx.get('is_dest_hub', False)
        hub_city = ctx.get('hub_city')
        rate = ctx['rate']; preferences = ctx['preferences']; date = ctx['date']

        target_date_str = date
        search_next_day_trains = False
        if flight and flight.get('abs_arrival'):
            try:
                arrival_dt = datetime.datetime.fromisoformat(flight['abs_arrival'])
                target_date_str = arrival_dt.strftime('%Y-%m-%d')
                results['flight_arrival_iso'] = flight['abs_arrival']
                if arrival_dt.hour >= 20:
                    search_next_day_trains = True
            except Exception:
                pass

        onward_from_hub = bool(is_international and is_dest_hub and hub_city)
        if onward_from_hub:
            search_next_day_trains = True

        next_day_str = (datetime.datetime.strptime(target_date_str, '%Y-%m-%d')
                        + datetime.timedelta(days=1)).strftime('%Y-%m-%d')

        dest_railless = (dest_loc.get('state') or '').strip().lower() in RAILLESS_STATES
        trains = []
        if dest_cc == "IN" and not dest_railless and (src_cc == "IN" or onward_from_hub):
            train_src = hub_city if onward_from_hub else src_label
            dest_state = dest_loc.get('state')
            src_state = src_loc.get('state') if train_src == src_label else None
            d1 = target_date_str.split('-')
            ry_date1 = f"{d1[2]}-{d1[1]}-{d1[0]}"
            trains.extend(self.train_svc.get_train_details(
                train_src, dest_label, ry_date1, rate, preferences, src_state, dest_state) or [])
            if search_next_day_trains:
                d2 = next_day_str.split('-')
                ry_date2 = f"{d2[2]}-{d2[1]}-{d2[0]}"
                trains.extend(self.train_svc.get_train_details(
                    train_src, dest_label, ry_date2, rate, preferences, src_state, dest_state) or [])
        if (trains and dest_cc == "IN"
                and not self._station_is_near_dest(trains[0].get('destination'), dest_loc)):
            trains = []
        results['trains'] = trains

        if not results['trains'] and dest_cc == "IN" and not dest_railless:
            dl = (dest_label or "").strip().lower()
            d = target_date_str.split('-')
            ry = f"{d[2]}-{d[1]}-{d[0]}"
            dest_gateway = self._dest_gateway_city(dest_loc, dest_label)
            railhead_airport_towns = []
            try:
                for c in self.loc_svc.find_airport_candidates(dest_loc['lon'], dest_loc['lat']) or []:
                    dist = c.get('distance_km') or 0
                    if dist > 200 or not c.get('iata'):
                        continue
                    air = self.flight_svc.get_airport_data(c['iata'], dest_cc)
                    if air and (air.get('countryCode') or '').upper() == "IN" and air.get('cityName'):
                        railhead_airport_towns.append(air['cityName'])
            except Exception:
                pass
            dest_state = dest_loc.get('state')
            candidates = [dest_gateway, hub_city, *railhead_airport_towns, dest_state]

            rh_src = hub_city if (src_cc != "IN" and is_dest_hub and hub_city) else src_label
            if rh_src:
                rh_src_l = rh_src.strip().lower()
                src_hint = src_loc.get('state') if rh_src == src_label else None
                seen = set()
                for cand in candidates:
                    c = (cand or "").strip()
                    if not c or c.lower() == dl or c.lower() == rh_src_l or c.lower() in seen:
                        continue
                    seen.add(c.lower())
                    dest_hint = dest_state if c == dest_state else None
                    railhead = self.train_svc.get_train_details(
                        rh_src, c, ry, rate, preferences, src_hint, dest_hint)
                    if railhead and self._railhead_is_near(c, dest_loc):
                        results['trains'] = railhead
                        results['rail_hub'] = c
                        break

        if (dest_cc == "IN" and not results.get('flights')
                and not results.get('hub_flight_fallback') and not results['trains']):
            salv, gw_city = self._salvage_hub_flight(
                ctx['src_query'], src_label, dest_loc, src_cc, dest_cc, date, rate)
            if salv:
                results['hub_flight_fallback'] = salv
                is_dest_hub, hub_city = True, gw_city

        if is_dest_hub and hub_city and results.get('hub_flight_fallback'):
            results['hub_city'] = hub_city

        results['multimodal'] = bool(
            is_international and results.get('hub_flight_fallback')
            and results.get('trains'))

        if results['multimodal'] and results.get('flight_arrival_iso'):
            try:
                arr = datetime.datetime.fromisoformat(results['flight_arrival_iso']).replace(tzinfo=None)
                results['trains'].sort(key=lambda tr: 0 if _train_departs_after(tr, arr) else 1)
            except Exception:
                pass

        results.pop('transfer', None)
        if dest_cc == "IN":
            dest_label_now = self._location_label(dest_loc)
            arrival_city = None
            if results.get('rail_hub'):
                arrival_city = results['rail_hub']
            elif not results.get('trains') and flight:
                segs = flight.get('segments') or []
                arrival_city = ((segs[-1].get('destinationCity') if segs else '')
                                or results.get('hub_city') or '').strip()
            if arrival_city and arrival_city.strip().lower() != (dest_label_now or "").strip().lower():
                km = self._geo_km(arrival_city, dest_loc)
                if km and 5 < km <= TRANSFER_MAX_KM:
                    results['transfer'] = {
                        "mode": "cab", "from": arrival_city,
                        "to": dest_label_now, "distance_km": km,
                    }

    def _run_synchronized_search(self, job_id: str, origin: str, destination: str, date: str, preferences: str, language: str):
        """
        Quick-pick worker: one-shot synchronized search producing the complete
        auto-bundle (flights + trains + hotels + itinerary + transfer).
        """
        try:
            results, ctx = self._prepare_search(job_id, origin, destination, date, preferences, language)
            if results is None:
                return

            best_flight = (results.get('flights') or results.get('hub_flight_fallback') or [None])[0]
            check_in, check_out = self._hotel_dates(best_flight, date)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                f_hotels = executor.submit(self.hotel_svc.get_hotel_details,
                                           ctx['dest_label'], check_in, check_out, ctx['rate'])
                self._resolve_onward_and_transfer(results, ctx, best_flight)
                results['hotels'] = f_hotels.result()

            self.jobs.update_one(
                {"job_id": job_id},
                {"$set": {"status": "completed", "stage": "ready", "progress": 100, "results": results}}
            )
        except Exception as e:
            logger.exception("Travel search job %s failed", job_id)
            self.jobs.update_one({"job_id": job_id}, {"$set": {
                "status": "failed",
                "error_code": "SEARCH_FAILED",
                "error": "The trip search failed unexpectedly. Please try again.",
            }})

    def _run_manual_search(self, job_id: str, origin: str, destination: str, date: str, preferences: str, language: str):
        """
        Manual/progressive worker: publish flights as soon as they're resolved,
        then load hotels in the background. Trains are NOT searched here — the
        frontend fetches them per chosen flight via resolve_trains_for_flight,
        so they always connect to the flight the traveller actually picked.

        Exception: when there are NO flights at all (train-only destinations or
        the salvage case) there is no flight to defer behind, so onward trains +
        transfer are resolved here so the wizard still has something to show.
        """
        try:
            results, ctx = self._prepare_search(job_id, origin, destination, date, preferences, language)
            if results is None:
                return

            results['multimodal'] = bool(ctx.get('is_international') and ctx.get('is_dest_hub'))

            self.jobs.update_one(
                {"job_id": job_id},
                {"$set": {"status": "processing", "stage": "flights", "progress": 45, "results": results}}
            )

            best_flight = (results.get('flights') or results.get('hub_flight_fallback') or [None])[0]
            check_in, check_out = self._hotel_dates(best_flight, date)
            results['hotels'] = self.hotel_svc.get_hotel_details(
                ctx['dest_label'], check_in, check_out, ctx['rate'])
            self.jobs.update_one(
                {"job_id": job_id},
                {"$set": {"stage": "hotels", "progress": 80, "results": results}}
            )

            if not (results.get('flights') or results.get('hub_flight_fallback')):
                self._resolve_onward_and_transfer(results, ctx, None)

            self.jobs.update_one(
                {"job_id": job_id},
                {"$set": {"status": "completed", "stage": "ready", "progress": 100,
                          "results": results, "ctx": ctx}}
            )
        except Exception as e:
            logger.exception("Manual search job %s failed", job_id)
            self.jobs.update_one({"job_id": job_id}, {"$set": {
                "status": "failed",
                "error_code": "SEARCH_FAILED",
                "error": "The trip search failed unexpectedly. Please try again.",
            }})

    def resolve_trains_for_flight(self, job_id: str, flight: Dict) -> Optional[Dict]:
        """
        On-demand onward-train + transfer resolution for a manual-mode job, given
        the flight the user just chose. Returns {trains, rail_hub, transfer,
        flight_arrival_iso} or None if the job/context is unavailable.

        The on-demand trains + cab are also persisted back onto the job doc so
        /select (which rebuilds the saved trip from job results server-side)
        carries them — without this a saved manual trip lost its onward train +
        cab (e.g. Bhopal->Chopta: no cab from Dehradun after saving).
        """
        job = self.get_job_status(job_id)
        if not job or not job.get('ctx'):
            return None
        ctx = job['ctx']
        stored = job.get('results') or {}
        sub = {
            "flights": stored.get('flights'),
            "hub_flight_fallback": stored.get('hub_flight_fallback'),
        }
        self._resolve_onward_and_transfer(sub, ctx, flight)
        self.jobs.update_one({"job_id": job_id}, {"$set": {
            "results.trains": sub.get('trains', []),
            "results.rail_hub": sub.get('rail_hub'),
            "results.transfer": sub.get('transfer'),
            "results.hub_city": sub.get('hub_city'),
            "results.flight_arrival_iso": sub.get('flight_arrival_iso'),
            "results.multimodal": sub.get('multimodal', False),
        }})
        return {
            "trains": sub.get('trains', []),
            "rail_hub": sub.get('rail_hub'),
            "transfer": sub.get('transfer'),
            "flight_arrival_iso": sub.get('flight_arrival_iso'),
            "multimodal": sub.get('multimodal', False),
        }

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """
        Retrieves the current status and results of a search job.

        A job still 'processing' past STALE_JOB_SECONDS is treated as failed: the
        worker runs on a daemon thread that can be reaped on a serverless/gunicorn
        restart, which would otherwise leave the job (and the polling client)
        hanging forever.
        """
        job = self.jobs.find_one({"job_id": job_id}, {"_id": 0})
        if not job:
            return None
        if job.get("status") == "processing":
            created = job.get("created_at")
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=datetime.timezone.utc)
            if created and (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() > STALE_JOB_SECONDS:
                self.jobs.update_one({"job_id": job_id}, {"$set": {
                    "status": "failed",
                    "error_code": "SEARCH_TIMEOUT",
                    "error": "The trip search timed out. Please try again.",
                }})
                job["status"] = "failed"
                job["error_code"] = "SEARCH_TIMEOUT"
                job["error"] = "The trip search timed out. Please try again."
        return job
