"""The two market sources, as small HTTP clients. Worker only -- the
API never imports this module (test_api_import_boundary.py). `fetch` is
injectable so the clients are tested against canned responses; the
default fetchers use urllib with a 20 s timeout.

Both `lookup`s return a SourceResult whose `result` is already trimmed
to what the row's evidence shows (estimate-first-pricing §7). Titles
and seller names are seller-written text: stored and displayed as text,
never interpreted."""
from __future__ import annotations

import json
import math
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Callable, NamedTuple

from app.config import settings
from app.market.classify import unit_matches

_TIMEOUT = 20
_ONEBUILD_URL = "https://gateway-external.1build.com/"
_SERPAPI_URL = "https://serpapi.com/search.json"
_ONEBUILD_QUERY = """
query Sources($term: String!, $zip: String!) {
  sources(input: {searchTerm: $term, zip: $zip, pageSize: 5}) {
    nodes { name uom materialRateUsdCents laborRateUsdCents }
  }
}"""


class SourceError(Exception):
    """The source could not be reached or answered with an error."""


class SourceResult(NamedTuple):
    status: str                       # "priced" | "no_match" | "failed"
    unit_price: Decimal | None
    low: Decimal | None
    high: Decimal | None
    labor_rate: Decimal | None
    uom: str
    location_label: str
    result: dict


def _post_json(url: str, headers: dict, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _get_json(url: str, params: dict) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _cents(v) -> Decimal | None:
    """Cents -> dollars, rounded to the nearest cent. `v` is a vendor
    field (a JSON number, or occasionally a string): anything that does
    not convert to a finite Decimal is treated as absent, not raised."""
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not d.is_finite():
        return None
    return (d / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _call(fn, *args):
    """Run a fetcher, mapping network/parse failures to SourceError.
    Vendor field parsing happens after this, deliberately outside it --
    a malformed field should degrade that one row, not fail the job."""
    try:
        return fn(*args)
    except (OSError, urllib.error.URLError, ValueError) as e:
        raise SourceError(str(e)) from e


class OneBuildSource:
    name = "onebuild"

    def __init__(self, api_key: str, fetch: Callable[[str, dict, dict], dict] = _post_json):
        self._key, self._fetch = api_key, fetch

    def location_key(self, project) -> str | None:
        return project.postal_code or None

    def lookup(self, query: str, item_unit: str, location_key: str) -> SourceResult:
        data = _call(self._fetch, _ONEBUILD_URL, {"1build-api-key": self._key},
                     {"query": _ONEBUILD_QUERY, "variables": {"term": query, "zip": location_key}})
        if "errors" in data:
            raise SourceError(str(data["errors"])[:300])
        nodes = (((data.get("data") or {}).get("sources") or {}).get("nodes")) or []
        label = f"ZIP {location_key}"
        for n in nodes:
            if not unit_matches(n.get("uom") or "", item_unit):
                continue
            price = _cents(n.get("materialRateUsdCents"))
            if not price:  # None (absent/unparseable), or zero -- neither is a usable candidate
                continue
            trimmed = {k: n.get(k) for k in ("name", "uom", "materialRateUsdCents", "laborRateUsdCents")}
            return SourceResult("priced", price, price, price, _cents(n.get("laborRateUsdCents")),
                                n["uom"], label, {"matched": trimmed})
        return SourceResult("no_match", None, None, None, None, "", label, {"candidates": len(nodes)})


class ShoppingSource:
    name = "shopping"

    def __init__(self, api_key: str, fetch: Callable[[str, dict], dict] = _get_json):
        self._key, self._fetch = api_key, fetch

    def location_key(self, project) -> str | None:
        m = re.search(r"([A-Za-z .'-]+),\s*([A-Z]{2})\b", project.location or "")
        if m:
            return f"{m.group(1).strip()}, {m.group(2)}"
        return project.postal_code or None

    def lookup(self, query: str, item_unit: str, location_key: str) -> SourceResult:
        data = _call(self._fetch, _SERPAPI_URL, {"engine": "google_shopping", "q": query, "location": location_key,
                                                  "hl": "en", "gl": "us", "api_key": self._key})
        if data.get("error"):
            raise SourceError(str(data["error"])[:300])
        sellers = []
        for r in data.get("shopping_results") or []:
            try:
                price = float(r.get("extracted_price"))
            except (TypeError, ValueError):
                continue  # e.g. SerpApi's "call for price" listings -- skip, don't crash the job
            if not math.isfinite(price):
                continue
            link = r.get("link") or ""
            sellers.append({"title": str(r.get("title", ""))[:200], "seller": str(r.get("source", ""))[:100],
                            "price": price, "link": link if link.startswith("https://") else None})
        if len(sellers) < 2:
            return SourceResult("no_match", None, None, None, None, "", location_key, {"sellers": sellers})
        prices = sorted(Decimal(str(s["price"])) for s in sellers)
        median = Decimal(str(statistics.median(prices))).quantize(Decimal("0.01"))
        return SourceResult("priced", median, prices[0], prices[-1], None, "EA", location_key, {"sellers": sellers})


def get_sources() -> dict[str, OneBuildSource | ShoppingSource]:
    out: dict = {}
    if settings.onebuild_api_key:
        out["onebuild"] = OneBuildSource(settings.onebuild_api_key)
    if settings.serpapi_key:
        out["shopping"] = ShoppingSource(settings.serpapi_key)
    return out
