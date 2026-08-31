"""Deterministic location pricing -- the fallback when the LLM estimator
isn't available (no API key or a transient error).

A small city-cost-index style table: a loaded electrician labor rate and a
material cost factor by state/metro, with a national default. Rough by
design -- enough that entering a location visibly, honestly changes the
number, without pretending to be a live pricing feed. The LLM path
supersedes this when a key is present.
"""

from __future__ import annotations

# (labor_rate $/hr loaded, material_factor vs national). Keyed by an
# uppercase substring matched against the location string.
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

NATIONAL = (78.0, 1.00)


def lookup(location: str) -> tuple[float, float, str]:
    """Returns (labor_rate, material_factor, note) for a location string."""
    up = (location or "").upper()
    for key, (rate, factor) in _TABLE.items():
        if key in up:
            return rate, factor, f"Rate based on {location} area cost data."
    return (*NATIONAL, "National average rate (no local data matched).")
