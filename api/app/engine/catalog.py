"""Division 26 catalog, tag conventions, and a static price book.

This is the shared reference the Classification and Pricing agents read
from. It is deliberately small and explicit for v1 -- a hand-built map of
common electrical device tags to catalog items, plus rough material and
labor-unit costs. A production build replaces the price book with a real
pricing service and the tag map with the per-firm symbol library
(ROADMAP.md 2.1), but the *shape* -- a tag resolves to a catalog item,
a catalog item resolves to a cost -- is what the rest of the engine is
written against and does not change.

Prices are rough order-of-magnitude placeholders (material dollars and
labor hours per unit), enough to produce a defensible-shaped total direct
cost that an estimator reviews. They are not a quote.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogItem:
    catalog_id: str
    name: str
    system: str
    category: str
    unit: str
    symbol: str  # the glyph key the canvas draws (Symbols.jsx vocabulary)
    material_cost: float  # dollars per unit
    labor_hours: float  # crew hours per unit


# The v1 catalog: common Division 26 devices. `symbol` reuses the drawn
# glyph vocabulary the review canvas already knows (receptacle, switch,
# panel, highbay, data, junction, luminaire, generic).
CATALOG: dict[str, CatalogItem] = {
    "receptacle_20a": CatalogItem("receptacle_20a", "20A duplex receptacle", "Power", "Devices", "ea", "receptacle", 12.0, 0.5),
    "receptacle_gfci": CatalogItem("receptacle_gfci", "20A GFCI receptacle", "Power", "Devices", "ea", "receptacle", 28.0, 0.6),
    "switch_sp": CatalogItem("switch_sp", "Single-pole switch", "Power", "Devices", "ea", "switch", 9.0, 0.4),
    "junction_box": CatalogItem("junction_box", "Junction box", "Power", "Boxes", "ea", "junction", 6.0, 0.3),
    "data_outlet": CatalogItem("data_outlet", "Data outlet", "Low voltage", "Devices", "ea", "data", 14.0, 0.5),
    "panel": CatalogItem("panel", "Panelboard", "Distribution", "Equipment", "ea", "panel", 850.0, 6.0),
    "disconnect": CatalogItem("disconnect", "Disconnect switch", "Power", "Equipment", "ea", "panel", 140.0, 1.5),
    "luminaire_troffer": CatalogItem("luminaire_troffer", "2x4 LED troffer", "Lighting", "Fixtures", "ea", "luminaire", 95.0, 0.8),
    "luminaire_highbay": CatalogItem("luminaire_highbay", "LED high bay", "Lighting", "Fixtures", "ea", "highbay", 210.0, 1.0),
    "luminaire_generic": CatalogItem("luminaire_generic", "Luminaire", "Lighting", "Fixtures", "ea", "luminaire", 120.0, 0.9),
    "exit_sign": CatalogItem("exit_sign", "Exit sign", "Life safety", "Fixtures", "ea", "luminaire", 55.0, 0.6),
}


# Deterministic tag -> catalog map for v1. Fixture-type letters (A..H) are
# handled separately (they resolve to a luminaire, described by the
# schedule when one is found). Keys are matched case-sensitively against a
# device tag after normalization.
TAG_TO_CATALOG: dict[str, str] = {
    "R": "receptacle_20a",
    "GFI": "receptacle_gfci",
    "GFCI": "receptacle_gfci",
    "WP": "receptacle_gfci",
    "S": "switch_sp",
    "J": "junction_box",
    "T": "data_outlet",  # telecom/data outlet (convention varies; estimator confirms)
    "DP": "panel",
    "DS": "disconnect",
    "X": "exit_sign",
}

# Single-letter fixture type tags a drafter uses for luminaire schedules.
FIXTURE_TYPE_TAGS = set("ABCDEFGH")


def is_fixture_type(tag: str) -> bool:
    return tag in FIXTURE_TYPE_TAGS
