"""The estimator-facing words for every assumption this feature writes.

Sibling of `app/market/copy.py`, and the same discipline: one register
for the whole document, held in one file, so a new generator cannot
quietly introduce a second voice. Nothing here names a model, a
confidence, a processing stage, or a percentage of trust. The reader is
a general contractor reading a budget number, and every line answers
"what did you assume, and what was that based on."

Sentence case. No exclamation marks, no "please", no "successfully".
"""
from __future__ import annotations

from decimal import Decimal


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def dollars(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"${value:,.0f}"


# --- labor -------------------------------------------------------------

FIRM_HOURS = {
    "title": "Installation hours",
    "found": "{items} carry installation hours from the firm's own labor-unit table.",
    "why": "Hours drive the labor cost and the schedule; the firm's table is its history on similar work, not this job's.",
    "where": "Company settings, labor adjustments",
}

ESTIMATED_HOURS = {
    "title": "Installation hours",
    "found": "{items} carry installation hours derived for this takeoff, with nothing in the firm's table to match them against.",
    "why": "Hours drive the labor cost and the schedule, and nothing on this job has confirmed these.",
    "where": "Labor pricing, hours column",
}

FIRM_RATE = {
    "title": "Labor rate",
    "found": "The crew rate is weighted from the firm's own role rates, with no rate entered for this project.",
    "why": "Every labor dollar in the estimate is this rate times the hours above.",
    "where": "Company settings, labor rates",
}

ESTIMATED_RATE = {
    "title": "Labor rate",
    "found": "The labor rate is derived for this takeoff, with no firm rate table and no rate entered for this project.",
    "why": "Every labor dollar in the estimate rests on it.",
    "where": "Labor pricing, rate column",
}

# --- takeoff -----------------------------------------------------------

BRANCH_WIRE = {
    "title": "Branch wire and conduit",
    # Deliberately does NOT claim that every priced line includes an
    # assembly. The engine prices a line it could not match to a catalog
    # item bare, with no rough-in at all, and nothing on the item records
    # which way it went -- so "N lines include branch wire" was a claim
    # this module cannot establish. What it can say is what rule was used
    # where one was, and that the rest are bare.
    "found": "Branch wire and conduit are included at a rule of {feet} ft per device wherever a line "
             "matched a catalog assembly. The drawings show homerun arrows, not routed runs. A line the "
             "takeoff could not match to an assembly is priced bare, with no rough-in.",
    "why": "Wire and conduit are a large share of material cost, and a run length is not in the drawings for anyone to read.",
    "where": "Company settings, and the homerun arrows on the power plans",
}

MISSING_SCALE = {
    "title": "Scale on {sheet}",
    "found": "{sheet} carries no single scale, and {items} on it were measured against an assumed one.",
    "why": "Every measured length on the sheet rests on the scale, so all of them move together if it is wrong.",
    "where": "{sheet} title block",
}

SCALED_LENGTHS = {
    "title": "Measured lengths",
    "found": "{items} were measured off the drawings rather than read from a written dimension.",
    "why": "A length measured off a drawing carries the drawing's own precision, not a dimension's.",
    "where": "Takeoff spreadsheet, measured lines",
}

INFERRED_NAMES = {
    "title": "Item names read from context",
    "found": "{items} were named from the surrounding schedule text rather than from a legend row that "
             "defines the symbol: {names}.",
    "why": "The quantity was counted from the drawings either way; what the item is was read rather than matched.",
    # Names the sheets, so the GC can find the symbols in question
    # rather than being told a count and left to guess.
    "where": "{sheets}, and the legend sheets in the set",
}

# --- material ----------------------------------------------------------

FIRM_PRICE = {
    "title": "Material prices from the firm's price list",
    "found": "{items} are priced from the firm's own price list rather than a quote for this job.",
    "why": "A price list records what the firm paid before, which is not what a supplier will quote today.",
    "where": "Company settings, material pricing",
}

CLASS_AVERAGE = {
    "title": "{name}",
    "found": "No quote and no price on file. Priced at what gear of this class costs.",
    "why": "This is not a supplier price, and gear like this is where a budget moves most.",
    # Names the sheet, not just the screen: a GC asking "which
    # switchboard" needs the drawing it was counted on.
    "where": "{sheet}, and Material pricing",
}
