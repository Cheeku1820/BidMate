"""The two clients, against canned responses. No network: `fetch` is
injected. Trimming is asserted because the stored result is what the
row's evidence shows (estimate-first-pricing §7)."""
from decimal import Decimal

import pytest

from app.worker.market_sources import OneBuildSource, ShoppingSource, SourceError, get_sources

ONEBUILD = {"data": {"sources": {"nodes": [
    {"name": "Duplex receptacle, 20A, commercial grade", "uom": "EA", "materialRateUsdCents": 1240, "laborRateUsdCents": 2250,
     "calculatedUnitRateUsdCents": 3490, "sourceType": "MATERIAL", "id": "abc", "extra": "dropped"},
    {"name": "Receptacle branch circuit", "uom": "LF", "materialRateUsdCents": 310, "laborRateUsdCents": 900},
]}}}

SHOPPING = {"shopping_results": [
    {"title": "Columbia CVT8-LSCS-MV 8ft Vaportite", "price": "$156.75", "extracted_price": 156.75, "source": "LBC Lighting", "link": "https://www.lbclightingpro.com/x", "thumbnail": "dropped"},
    {"title": "CVT8-LSCS-MV", "price": "$169.95", "extracted_price": 169.95, "source": "Codale", "link": "https://www.codale.com/y"},
    {"title": "CVT8-LSCS-MV", "price": "$303.33", "extracted_price": 303.33, "source": "Cooper", "link": "http://insecure.example/z"},
    {"title": "no price", "source": "X", "link": "https://x.example"},
]}


class P:
    def __init__(self, location="Austin, TX", postal_code="78701"):
        self.location, self.postal_code = location, postal_code


def test_onebuild_picks_first_unit_match_and_trims():
    calls = []
    src = OneBuildSource("k", fetch=lambda url, headers, body: (calls.append((url, headers, body)) or ONEBUILD))
    r = src.lookup("20A duplex receptacle", "EA", "78701")
    assert r.status == "priced" and r.unit_price == Decimal("12.40") and r.labor_rate == Decimal("22.50")
    assert r.low == r.high == Decimal("12.40") and r.uom == "EA"
    assert r.result == {"matched": {"name": "Duplex receptacle, 20A, commercial grade", "uom": "EA",
                                    "materialRateUsdCents": 1240, "laborRateUsdCents": 2250}}
    assert calls[0][1]["1build-api-key"] == "k" and "78701" in calls[0][2]["variables"]["zip"]


def test_onebuild_no_unit_match_is_no_match():
    r = OneBuildSource("k", fetch=lambda *a: ONEBUILD).lookup("wire", "SF", "78701")
    assert r.status == "no_match" and r.unit_price is None


def test_onebuild_network_failure_raises_source_error():
    def boom(*a):
        raise OSError("timeout")
    with pytest.raises(SourceError):
        OneBuildSource("k", fetch=boom).lookup("x", "EA", "78701")


def test_shopping_low_median_high_and_https_only():
    r = ShoppingSource("k", fetch=lambda url, params: SHOPPING).lookup("Current CVT8-LSCS-MV", "EA", "Austin, TX")
    assert r.status == "priced"
    assert (r.low, r.unit_price, r.high) == (Decimal("156.75"), Decimal("169.95"), Decimal("303.33"))
    sellers = r.result["sellers"]
    assert [s["seller"] for s in sellers] == ["LBC Lighting", "Codale", "Cooper"]
    assert sellers[2]["link"] is None and "thumbnail" not in sellers[0]


def test_shopping_one_listing_is_no_match():
    one = {"shopping_results": SHOPPING["shopping_results"][:1]}
    assert ShoppingSource("k", fetch=lambda u, p: one).lookup("q", "EA", "Austin, TX").status == "no_match"


def test_location_keys():
    assert OneBuildSource("k").location_key(P()) == "78701"
    assert OneBuildSource("k").location_key(P(postal_code=None)) is None
    assert ShoppingSource("k").location_key(P()) == "Austin, TX"
    assert ShoppingSource("k").location_key(P(location="", postal_code="78701")) == "78701"


def test_get_sources_only_returns_configured(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "onebuild_api_key", "a")
    monkeypatch.setattr(config.settings, "serpapi_key", "")
    assert set(get_sources()) == {"onebuild"}
