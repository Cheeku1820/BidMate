"""Classification agent (v1, deterministic).

Names each unlabelled DeviceCluster: maps a device tag to a Division 26
catalog item and assigns a review status. This is the one language step in
the pipeline, and even here it only *proposes* -- a person approves. It
never sets status APPROVED.

v1 uses the deterministic tag map in catalog.py. A recognized device
(receptacle, switch, junction) is Ready to review. A fixture-type letter
whose description was not read from a schedule is Needs attention -- its
exact fixture is a decision, not a guess. An unrecognized tag stays a
visible, unpriced Needs-attention item rather than being dropped
(CLAUDE.md: unfamiliar symbols remain in the review queue).

The signature (clusters + sheets -> items) is what a real LLM classifier
would also satisfy, reading the schedule text on the sheet; swapping it in
does not change anything downstream.
"""

from __future__ import annotations

from .catalog import CATALOG, TAG_TO_CATALOG, is_fixture_type
from .contracts import ClassifiedItem, DetectedSheet, DeviceCluster


def _fixture_warning(tag: str, count: int, sheet_no: str) -> dict:
    return {
        "reason": "legend",
        "title": "Fixture type needs confirmation",
        "found": f"Type {tag} appears {count} times on {sheet_no}, but its description wasn't read from a schedule.",
        "why": "The exact fixture and its price can't be confirmed until the type is matched to the luminaire schedule.",
        "fix": "Confirm the fixture type against the luminaire schedule, then approve.",
        "where": f"{sheet_no} and the luminaire schedule.",
    }


def _unknown_warning(tag: str, count: int, sheet_no: str) -> dict:
    return {
        "reason": "legend",
        "title": "Symbol not in legend",
        "found": f"Tag {tag} appears {count} times on {sheet_no} but isn't a recognized device.",
        "why": "An unclassified symbol has no catalog item, so it isn't counted or priced yet.",
        "fix": "Assign a classification, or reject it if it isn't a device.",
        "where": f"{sheet_no}.",
    }


# Neither warning below quotes the parsed description, and neither takes
# it as an argument -- you cannot interpolate what you were not given.
#
# The abbreviations block is read off messy sheet text by a line-pair
# heuristic, and on a real set it mis-pairs: this set yields R -> "Aaron
# S. Jordan" (the engineer of record, lifted off a seal block), C ->
# "(c)2020 ECI, Inc.", G -> "STACKS/ADULT" (a room name), M -> "TOTAL NEC
# AMPS: 39 A". A warning's `found` is contractually *what was found*, so
# stating one of those pairings in the estimator's own words is worse than
# saying nothing: they will go looking for a legend row that is not there.
# Naming the legend without quoting it costs the estimator one glance at a
# sheet they can already open, and cannot be wrong.
def _modifier_warning(tag: str, count: int, sheet_no: str) -> dict:
    return {
        "reason": "legend",
        "title": "Modifier, not a standalone device",
        "found": f"Tag {tag} appears {count} times on {sheet_no}, and {tag} is also defined in the legend's abbreviations block.",
        "why": f"{tag} reads as an abbreviation here, so it most likely labels another device rather than being one itself.",
        "fix": "Trace each one to the device symbol it labels so it is not double counted, or reject it.",
        "where": f"{sheet_no} and the legend sheet.",
    }


def _ambiguous_tag_warning(tag: str, count: int, sheet_no: str) -> dict:
    return {
        "reason": "legend",
        "title": "Tag also appears in the legend",
        "found": f"Tag {tag} appears {count} times on {sheet_no}, and {tag} is also defined in the legend.",
        "why": f"{tag} is used both for a device and for a legend entry, so some of these placements may be a label rather than a device.",
        "fix": "Spot check a few against the plan; correct the quantity if some are not devices, then approve.",
        "where": f"{sheet_no} and the legend sheet.",
    }


def classify(clusters: list[DeviceCluster], sheets: list[DetectedSheet]) -> list[ClassifiedItem]:
    sheet_no = {s.page_index: (s.number or f"page {s.page_index + 1}") for s in sheets}
    # First definition wins, matching parse_legend's own policy: a legend
    # sheet carries the real definitions, and a later sheet's mis-paired
    # callout must not overwrite one. A dict comprehension here would be
    # last-wins, which put 'SEE ENLARGED' over 'WEATHERPROOF' for WP.
    abbrev: dict[str, str] = {}
    for sheet in sheets:
        for entry in sheet.legend:
            if entry.kind == "abbreviation":
                abbrev.setdefault(entry.symbol, entry.description)
    items: list[ClassifiedItem] = []
    for c in clusters:
        no = sheet_no.get(c.sheet_page_index, "?")
        # Curated Division 26 knowledge outranks a parsed abbreviation: a
        # tag in TAG_TO_CATALOG or the fixture-letter range is hand-built
        # device knowledge, while a legend abbreviation is a heuristic read
        # off messy sheet text. The curated reading wins the classification
        # and the price, but a genuine collision still surfaces so the
        # estimator can spot check it rather than the tag being silently
        # zeroed out as a modifier.
        if c.tag in TAG_TO_CATALOG:
            cat = CATALOG[TAG_TO_CATALOG[c.tag]]
            if c.tag in abbrev:
                items.append(_item(cat, c, "attention", _ambiguous_tag_warning(c.tag, c.count, no)))
            else:
                items.append(_item(cat, c, "ready", None))
        elif is_fixture_type(c.tag):
            cat = CATALOG["luminaire_generic"]
            cat = _rename(cat, f"Luminaire type {c.tag}")
            items.append(_item(cat, c, "attention", _fixture_warning(c.tag, c.count, no)))
        elif c.tag in abbrev:
            # The name comes from the catalog taxonomy, never from parsed
            # sheet text -- interpolating the abbreviation's expansion is
            # how "AMP — Pole Va - Phase A" reached the CLI as an item
            # name. Same name the sibling unclassified branch uses; the
            # warning is what distinguishes the two readings.
            items.append(ClassifiedItem(
                catalog_id="unclassified", name=f"Unclassified symbol ({c.tag})",
                system="Unknown", category="Unclassified", unit="ea", symbol="generic",
                quantity=c.count, sheet_page_index=c.sheet_page_index, placements=c.placements,
                status="attention", warning=_modifier_warning(c.tag, c.count, no),
                source_tag=c.tag,
            ))
        else:
            items.append(
                ClassifiedItem(
                    catalog_id="unclassified", name=f"Unclassified symbol ({c.tag})",
                    system="Unknown", category="Unclassified", unit="ea", symbol="generic",
                    quantity=c.count, sheet_page_index=c.sheet_page_index, placements=c.placements,
                    status="attention", warning=_unknown_warning(c.tag, c.count, no), source_tag=c.tag,
                )
            )
    return items


def _item(cat, cluster: DeviceCluster, status: str, warning: dict | None) -> ClassifiedItem:
    return ClassifiedItem(
        catalog_id=cat.catalog_id, name=cat.name, system=cat.system, category=cat.category,
        unit=cat.unit, symbol=cat.symbol, quantity=cluster.count,
        sheet_page_index=cluster.sheet_page_index, placements=cluster.placements,
        status=status, warning=warning, source_tag=cluster.tag,
    )


def _rename(cat, name: str):
    from dataclasses import replace

    return replace(cat, name=name)
