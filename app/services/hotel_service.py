import logging
import os
from typing import List, Dict, Optional

import requests

from .location_service import LocationService
from ..utils.ssl_adapter import build_legacy_session

logger = logging.getLogger(__name__)


class HotelService:
    """
    Provides hotel search capabilities using the IRCTC Hotels API.
    Handles city-to-ID resolution and real-time hotel discovery with a Geoapify-based fallback for niche locations.

    IRCTC Hotels rejects modern TLS, so requests go through a legacy-SSL session
    (build_legacy_session).
    """

    def __init__(self):
        """Initializes the hotel service with legacy SSL adapters and coordination services."""
        self.session = build_legacy_session()
        self.loc_svc = LocationService()
        self.base_url = "https://www.hotels.irctc.co.in/tourismUser/tourism/hotel"
        self.geo_apiKey = os.environ.get('LOCATION')
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        }

    def _get_city_meta(self, city_name: str) -> Optional[Dict]:
        """
        Resolves a city name to its IRCTC destination ID and metadata. Keeps the
        full multi-word city name (e.g. "New Delhi", "Navi Mumbai") and only
        strips a trailing ", State, Country" qualifier — truncating to the first
        word mis-resolves multi-word cities.

        :param city_name: Textual name of the city. Ex: 'Mumbai'
        :return: Dictionary containing 'ID', 'NAME', and 'TYPE', or None.
        """
        clean_name = city_name.split(',')[0].strip()
        url = f"{self.base_url}/autocomplete?key={clean_name}"
        try:
            resp = self.session.get(url, headers=self.headers, verify=False, timeout=15).json()
            items = resp.get('data', [])
            if items:
                for item in items:
                    if item.get('TYPE') == 'City' and clean_name.lower() in item.get('NAME', '').lower():
                        return item
                for item in items:
                    if item.get('TYPE') == 'City':
                        return item
                return items[0]
            return None
        except Exception as exc:
            logger.warning("Hotel city lookup failed for '%s': %s", city_name, exc)
            return None

    def get_hotel_details(self, city_query: str, checkin: str, checkout: str, currency_rate: float = 1.0,
                          adults: int = 2) -> List[Dict]:
        """
        Fetches real-time hotel data from IRCTC or falls back to Geoapify proximity search.

        :param city_query: Name of the target city. Ex: 'Vidisha'
        :param checkin: Check-in date. Format: 'YYYY-MM-DD'
        :param checkout: Check-out date. Format: 'YYYY-MM-DD'
        :param currency_rate: Local currency multiplier. Ex: 0.012
        :param adults: Number of adult guests. Default: 2
        :return: List of hotel dictionaries with name, location, price, and image.
        """
        meta = self._get_city_meta(city_query)
        raw_hotels = []
        if meta:
            payload = {
                "id": str(meta.get('ID', "-1")),
                "checkInDate": checkin,
                "checkOutDate": checkout,
                "noOfRoom": "1",
                "noOfAdt": str(adults),
                "noOfPax": str(adults),
                "noOfChd": "0",
                "type": meta.get('TYPE', "City"),
                "affilId": "",
                "name": meta.get('NAME', city_query),
                "fullName": meta.get('FNAME', city_query),
                "src": "web"
            }
            url = f"{self.base_url}/searchhotel"
            try:
                resp_raw = self.session.post(url, json=payload, headers=self.headers, verify=False, timeout=90)
                if resp_raw.status_code == 200:
                    data = resp_raw.json()
                    raw_hotels = (data.get('data') or {}).get('hotelDetailsSummary', [])
                else:
                    logger.warning("IRCTC hotel search returned status %s for '%s'", resp_raw.status_code, city_query)
            except Exception as exc:
                logger.warning("IRCTC hotel search failed for '%s': %s", city_query, exc)

        if raw_hotels:
            return self._process_irctc_results(raw_hotels, currency_rate)
        return self._get_geoapify_hotels(city_query, currency_rate)

    def _process_irctc_results(self, raw_hotels: List[Dict], currency_rate: float) -> List[Dict]:
        """Processes and localizes raw hotel data from the IRCTC API."""
        processed = []
        for h in raw_hotels:
            p_info = h.get('hotelPrice') or {}
            try:
                total_inr = float(p_info.get('total', 0))
            except Exception:
                total_inr = 0.0

            converted_price = round(total_inr * currency_rate, 2)
            img_url = (h.get('hotelGallery') or {}).get(
                'url') or "https://cf.bstatic.com/xdata/images/hotel/square60/827171850.jpg"

            processed.append({
                "name": h.get('hotelName'),
                "location": h.get('landmark') or h.get('city'),
                "rating": h.get('userRating') or h.get('starRating') or 3,
                "price": f"{converted_price:,}",
                "image": img_url,
                "url": f"https://www.hotels.irctc.co.in/hotels/hotel-details?hotelCode={h.get('hotelCode')}",
                "stars": h.get('starRating') or 3
            })
        return processed

    def _get_geoapify_hotels(self, city_name: str, rate: float) -> List[Dict]:
        """Provides a coordinate-based hotel fallback using the Geoapify Places API."""
        loc_data = self.loc_svc.get_location_data(city_name)
        if not loc_data:
            return []

        url = "https://api.geoapify.com/v2/places"
        params = {
            "categories": "accommodation.hotel",
            "filter": f"circle:{loc_data['lon']},{loc_data['lat']},15000",
            "limit": 15,
            "apiKey": self.geo_apiKey
        }

        try:
            resp = requests.get(url, params=params, timeout=10).json()
            features = resp.get('features', [])
            processed = []

            for f in features:
                props = f.get('properties', {})
                stars = (props.get('accommodation') or {}).get('stars') or (
                            props.get('datasource', {}).get('raw') or {}).get('stars') or 3
                try:
                    stars = int(stars)
                except Exception:
                    stars = 3

                base_price = {5: 6000, 4: 4000, 3: 2500, 2: 1500}.get(stars, 2000)
                converted_price = round(base_price * rate, 2)

                processed.append({
                    "name": props.get('name'),
                    "location": props.get('suburb') or props.get('city') or "City Center",
                    "rating": stars,
                    "price": f"{converted_price:,}",
                    "image": "https://cf.bstatic.com/xdata/images/hotel/max1024x768/306716075.jpg",
                    "url": "#",
                    "stars": stars
                })
            return processed
        except Exception as exc:
            logger.warning("Geoapify hotel fallback failed for '%s': %s", city_name, exc)
            return []
