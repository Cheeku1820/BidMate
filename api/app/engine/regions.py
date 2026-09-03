"""Deterministic location pricing -- the fallback when the LLM estimator
isn't available (no API key or a transient error).

A small city-cost-index style table: a loaded electrician labor rate and a
material cost factor by state/metro, with a national default. Rough by
design -- enough that entering a location visibly, honestly changes the
number, without pretending to be a live pricing feed. The LLM path
supersedes this when a key is present.

A hazard worth naming before you add a row: **match tokens, not
substrings.** Every key here is a substring of some innocent location
string -- "NC" sits inside CONCORD, "CO" inside COLUMBUS and COCOA,
"ALASKA" inside UNALASKA -- and a substring scan silently priced a New
Hampshire job against North Carolina. This is the third time this bug
class has landed in this engine: `conversation.py` matched "is a" inside
"this area", and `classification.py` read SWITCHBOARD as confirming a
switch. All three were substring matching where token matching was
meant, and all three failed quietly rather than loudly. `lookup` below
matches a state code only as the location's trailing token and every
other key on word boundaries; keep any new key inside that rule.
"""

from __future__ import annotations

import re

# (labor_rate $/hr loaded, material_factor vs national). Keyed uppercase:
# two-letter state codes, matched against the location's trailing token,
# and city or metro names, matched on word boundaries. See lookup().
_TABLE: dict[str, tuple[float, float]] = {
    "AK": (98.0, 1.35), "ALASKA": (98.0, 1.35), "ANCHORAGE": (98.0, 1.32), "UNALASKA": (110.0, 1.45),
    "HI": (95.0, 1.30), "HAWAII": (95.0, 1.30), "HONOLULU": (95.0, 1.28),
    "NY": (105.0, 1.20), "NEW YORK": (108.0, 1.22), "MANHATTAN": (115.0, 1.25),
    "CA": (92.0, 1.12), "SAN FRANCISCO": (110.0, 1.20), "LOS ANGELES": (95.0, 1.12),
    "WA": (88.0, 1.08), "SEATTLE": (92.0, 1.10),
    "IL": (95.0, 1.10), "CHICAGO": (98.0, 1.12),
    "MA": (98.0, 1.15), "BOSTON": (100.0, 1.16),
    "TX": (72.0, 0.98), "HOUSTON": (72.0, 0.98), "DALLAS": (74.0, 0.99),
    "FL": (68.0, 0.97), "GA": (68.0, 0.96), "NC": (66.0, 0.95),
    "OH": (74.0, 0.98), "MI": (76.0, 0.99), "AZ": (72.0, 0.99), "CO": (82.0, 1.04),
}

# Two-letter keys are state codes and are matched as a trailing token
# rather than as a substring. No name in the table is this length.
_STATE_CODE_LEN = 2

NATIONAL = (78.0, 1.00)


def lookup(location: str) -> tuple[float, float, str]:
    """Returns (labor_rate, material_factor, note) for a location string."""
    up = (location or "").upper()
    # Alpha runs, so a zip code or a stray period cannot become the
    # trailing token: "Unalaska, AK 99685" still ends on AK.
    tokens = re.findall(r"[A-Z]+", up)
    trailing = tokens[-1] if tokens else ""

    # A state code is a trailing token ("Concord, NH"), never a substring:
    # scanning for "NC" anywhere matched inside CONCORD and priced a New
    # Hampshire job against North Carolina, silently, since NH is not in
    # the table and would otherwise have fallen to the national default.
    # City and state names match on word boundaries for the same reason --
    # ALASKA must not match inside UNALASKA.
    #
    # Longest match still wins, so UNALASKA beats ALASKA when a location
    # names both, and any name beats the state code it sits above. Every
    # two-letter key in this table is a state code and no name is two
    # characters, which is what makes the length test below the right
    # discriminator; keep it that way when adding a row.
    matches = []
    for key, value in _TABLE.items():
        if len(key) == _STATE_CODE_LEN:
            if key == trailing:
                matches.append((key, value))
        elif re.search(rf"\b{re.escape(key)}\b", up):
            matches.append((key, value))

    if matches:
        _key, (rate, factor) = max(matches, key=lambda kv: len(kv[0]))
        return rate, factor, f"Rate based on {location} area cost data."
    return (*NATIONAL, "National average rate (no local data matched).")
