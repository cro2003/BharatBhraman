import logging
import requests
import time
from typing import Dict

logger = logging.getLogger(__name__)

INR_FALLBACK = {"code": "INR", "rate": 1.0}

COUNTRY_CURRENCY_FALLBACK = {
    "IN": "INR", "US": "USD", "GB": "GBP", "AE": "AED", "SG": "SGD",
    "JP": "JPY", "AU": "AUD", "CA": "CAD", "CH": "CHF", "CN": "CNY",
    "TH": "THB", "MY": "MYR", "ID": "IDR", "VN": "VND", "LK": "LKR",
    "NP": "NPR", "BD": "BDT", "PK": "PKR", "BT": "BTN", "MV": "MVR",
    "SA": "SAR", "QA": "QAR", "KW": "KWD", "BH": "BHD", "OM": "OMR",
    "HK": "HKD", "KR": "KRW", "NZ": "NZD", "ZA": "ZAR", "RU": "RUB",
    "TR": "TRY", "EG": "EGP", "BR": "BRL", "MX": "MXN",
    "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "NL": "EUR",
    "BE": "EUR", "AT": "EUR", "PT": "EUR", "IE": "EUR", "GR": "EUR",
    "FI": "EUR",
}


class CurrencyService:
    """
    Handles dynamic currency resolution and live exchange rate fetching.
    Maps source countries to their local currencies (primary source: country.io,
    fetched and cached at runtime; COUNTRY_CURRENCY_FALLBACK is used only when
    that service is unreachable) and applies live market rates.

    On any failure to resolve a valid foreign rate it returns INR_FALLBACK
    (code and rate kept together) so the UI never shows an INR amount mislabelled
    under a foreign currency.
    """
    def __init__(self):
        """Initializes the service with rate providers and internal cache."""
        self.rate_url = "https://api.exchangerate-api.com/v4/latest/INR"
        self.country_currency_url = "https://country.io/currency.json"
        self.rates_cache = {}
        self.country_currency = {}
        self.cc_loaded = False
        self.last_updated = 0
        self.cache_duration = 3600

    def _load_country_currency(self):
        """Loads and caches the country->currency map from country.io (once)."""
        if self.cc_loaded:
            return
        try:
            resp = requests.get(self.country_currency_url, timeout=8).json()
            if isinstance(resp, dict) and resp:
                self.country_currency = resp
        except Exception as exc:
            logger.warning("country->currency fetch failed, using fallback table: %s", exc)
        self.cc_loaded = True

    def get_currency_for_country(self, country_code: str) -> str:
        """
        Resolves an ISO 3166-1 alpha-2 country code to its primary currency code,
        preferring the live country.io map and falling back to the built-in table.

        :param country_code: Two-letter country code. Ex: 'US' or 'GB'
        :return: Three-letter currency code. Ex: 'USD' (defaults to INR if unknown).
        """
        code = (country_code or "").upper()
        self._load_country_currency()
        return self.country_currency.get(code) or COUNTRY_CURRENCY_FALLBACK.get(code, "INR")

    def get_rate_info(self, country_code: str) -> Dict:
        """
        Retrieves the local currency code and current exchange rate from INR.

        :param country_code: Two-letter source country code. Ex: 'US'
        :return: Dictionary with 'code' and 'rate' (1 INR = X local). Ex: {'code': 'USD', 'rate': 0.012}
        """
        target_currency = self.get_currency_for_country(country_code)

        if target_currency == "INR":
            return dict(INR_FALLBACK)

        if time.time() - self.last_updated > self.cache_duration:
            try:
                resp = requests.get(self.rate_url, timeout=10).json()
                self.rates_cache = resp.get('rates', {})
                self.last_updated = time.time()
            except Exception as exc:
                logger.warning("Exchange-rate fetch failed; falling back to INR: %s", exc)
                return dict(INR_FALLBACK)

        if target_currency not in self.rates_cache:
            logger.warning("No exchange rate available for %s; falling back to INR", target_currency)
            return dict(INR_FALLBACK)

        return {"code": target_currency, "rate": float(self.rates_cache[target_currency])}
