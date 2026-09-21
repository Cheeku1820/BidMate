"""Which market source prices an item, and with what query. Pure and
deterministic (estimate-first-pricing §3): a lump sum or engineered gear
is "quote required" and spends nothing; a manufacturer model number goes
to shopping; everything else goes to 1build by name. Match on whole
words, never substrings -- regions.py's docstring records why."""
from __future__ import annotations

import re
from typing import NamedTuple


class Lookup(NamedTuple):
    source: str | None      # "onebuild" | "shopping" | None
    query: str
    reason: str             # "quote_required" | "model" | "name"


# Whole-word (or whole-phrase) markers of gear that is priced by quote.
# Every entry is matched with \b on both sides, case-insensitively. A
# one-word entry also matches its plural ("Standby Generators 150kW",
# "Switchboards MSB-1") -- a schedule line names the set as often as
# the unit, and a plural that slipped through went to the catalog
# source and came back priced from an accessory. Phrases are matched
# as written.
QUOTE_REQUIRED_WORDS: tuple[str, ...] = (
    "switchboard", "switch board", "switchgear", "mcc", "motor control center",
    "transformer", "spd", "surge protective", "surge protection", "generator", "ats",
    "automatic transfer", "bus duct", "busway", "vfd", "variable frequency",
    "furnish and install", "furnish & install", "connection to", "provide power for", "lump sum",
)


def _quote_pattern(word: str) -> str:
    return re.escape(word) + (r"s?" if " " not in word else "")


_QUOTE_RE = re.compile(r"\b(" + "|".join(_quote_pattern(w) for w in QUOTE_REQUIRED_WORDS) + r")\b", re.IGNORECASE)

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\s*(?:USA?)?\s*$", re.IGNORECASE)
_MODEL_LINE_RE = re.compile(r"^\s*model\s*(?:no\.?|#|number)?\s*[:#]?\s*#?\s*(\S+)", re.IGNORECASE | re.MULTILINE)
_MANUF_LINE_RE = re.compile(r"^\s*manufacturer\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
# A model token: 6+ chars, at least one letter and one digit, only
# letters, digits, hyphens, slashes, dots. "LED" and "2x4" are not models.
_MODEL_TOKEN_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9./-]{6,}$")

_UOM_ALIASES = {
    "ea": {"ea", "each"},
    "ft": {"ft", "lf", "feet", "foot"},
    "sf": {"sf", "sqft"},
}


def parse_zip(location: str) -> str | None:
    m = _ZIP_RE.search(location or "")
    return m.group(1) if m else None


def extract_model(description: str) -> tuple[str, str] | None:
    m = _MODEL_LINE_RE.search(description or "")
    if not m:
        return None
    token = m.group(1).strip().rstrip(",;")
    if not _MODEL_TOKEN_RE.match(token):
        return None
    mf = _MANUF_LINE_RE.search(description or "")
    manufacturer = mf.group(1).strip().rstrip(".") if mf else ""
    return manufacturer, token


def classify_for_lookup(name: str, description: str, unit: str) -> Lookup:
    text = f"{name}\n{description or ''}"
    if (unit or "").strip().upper() == "LS" or _QUOTE_RE.search(text):
        return Lookup(None, "", "quote_required")
    model = extract_model(description or "")
    if model is not None:
        manufacturer, token = model
        return Lookup("shopping", f"{manufacturer} {token}".strip(), "model")
    return Lookup("onebuild", (name or "").strip(), "name")


def _canon(unit: str) -> str | None:
    u = (unit or "").strip().lower()
    for canon, aliases in _UOM_ALIASES.items():
        if u in aliases:
            return canon
    return None


def unit_matches(source_uom: str, item_unit: str) -> bool:
    a, b = _canon(source_uom), _canon(item_unit)
    return a is not None and a == b


def lookup_key(query: str) -> str:
    return " ".join((query or "").lower().split())
