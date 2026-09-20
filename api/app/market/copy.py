"""The market lookup's outcomes and the estimator-facing words for each
(estimate-first-pricing §5). Pure data; the worker writes the outcome,
the pricing router turns it into the warning. Nothing here names a
vendor, a model, or a number -- the row's evidence carries the place,
the date, and the sellers."""
from __future__ import annotations

OUTCOMES = ("priced", "no_match", "quote_required", "location_needed", "unavailable", "over_budget", "failed")

_COPY = {
    "quote_required": (
        "Quote required",
        "This item is engineered equipment or a lump sum, which is priced by quote rather than from a catalog.",
        "Enter the supplier's price, or upload their price sheet.",
    ),
    "no_match": (
        "No market price found",
        "No catalog item matched closely enough to price it.",
        "Enter a price, add a company price for this item, or upload a supplier price sheet.",
    ),
    "location_needed": (
        "Project location needed",
        "A market estimate is priced for a place, and this project has no ZIP code.",
        "Add the project ZIP code in project settings, then refresh market estimates.",
    ),
    "unavailable": (
        "Market estimates aren't set up",
        "This workspace has no market pricing source configured.",
        "Enter a price, or ask an administrator to set up market estimates.",
    ),
    "over_budget": (
        "Market estimates paused this month",
        "This month's market lookups have been used.",
        "Enter a price, or upload a supplier price sheet.",
    ),
    "failed": (
        "Market estimate didn't complete",
        "The lookup for this item did not finish.",
        "Refresh market estimates. If it happens again, enter a price.",
    ),
}


def _dollars(value) -> str:
    return f"${value:,.2f}"


def wide_range_warning(*, low, high, location_label: str, fetched_note: str) -> dict:
    """The four-field warning behind a Market estimate that resolves
    *Needs attention* (pricing.py's WIDE_RANGE_RATIO): the sellers
    disagree by more than half, and the row has to say so, or the
    amber pill is a status with no reason. `where` is the same place
    and date the row's basis note names."""
    return {
        "title": "Wide price range",
        "found": f"Sellers quoted between {_dollars(low)} and {_dollars(high)}.",
        "why": "The market price for this item is uncertain by more than half.",
        "fix": "Check the sellers listed under the item, then enter a price or upload a supplier price sheet.",
        "where": ", ".join(part for part in (location_label, fetched_note) if part),
    }


def warning_for(outcome: str, *, query: str, sheet_number: str, description: str) -> dict | None:
    """The four-field warning for an unpriced outcome, or None for
    "priced". `found` says what was asked; `where` says where the item's
    own description lives, which is the evidence a person checks."""
    if outcome == "priced":
        return None
    title, why, fix = _COPY[outcome]
    return {
        "title": title,
        "found": f"Looked for \"{query}\"." if query else "No lookup was made for this item.",
        "why": why,
        "fix": fix,
        "where": f"{sheet_number}, item description: {description[:120]}" if description else sheet_number,
    }
