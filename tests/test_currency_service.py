"""Currency conversion must never mislabel an INR amount as a foreign currency."""
from app.services.currency_service import CurrencyService


def _service_with_rates(rates):
    svc = CurrencyService()
    svc.rates_cache = rates
    svc.last_updated = float("inf")  # skip the network rate refresh
    # Preload the country->currency map so no network call is made.
    svc.cc_loaded = True
    svc.country_currency = {"US": "USD", "GB": "GBP", "IT": "EUR"}
    return svc


def test_domestic_returns_inr():
    svc = CurrencyService()
    assert svc.get_rate_info("IN") == {"code": "INR", "rate": 1.0}


def test_foreign_with_known_rate_converts():
    svc = _service_with_rates({"USD": 0.012})
    info = svc.get_rate_info("US")
    assert info["code"] == "USD"
    assert info["rate"] == 0.012


def test_foreign_with_missing_rate_falls_back_to_inr_consistently():
    # Rate table lacks the target currency: must NOT return {code: USD, rate: 1.0}.
    svc = _service_with_rates({"EUR": 0.011})
    info = svc.get_rate_info("US")
    assert info == {"code": "INR", "rate": 1.0}


def test_rate_fetch_failure_falls_back_to_inr(monkeypatch):
    import app.services.currency_service as mod

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(mod.requests, "get", boom)
    svc = CurrencyService()
    svc.cc_loaded = True
    svc.country_currency = {"US": "USD"}
    svc.last_updated = 0  # force rate refresh attempt
    assert svc.get_rate_info("US") == {"code": "INR", "rate": 1.0}
