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


def _modifier_warning(tag: str, description: str, count: int, sheet_no: str) -> dict:
    return {
        "reason": "legend",
        "title": "Modifier, not a standalone device",
        "found": f"Tag {tag} appears {count} times on {sheet_no}.",
        "why": f"{tag} is listed in the abbreviations as {description.lower()}, so it labels another device rather than being counted as one.",
        "fix": "Trace each one to the device symbol it labels so it is not double counted, or reject it.",
        "where": f"{sheet_no} and the legend sheet.",
    }


def _ambiguous_tag_warning(tag: str, description: str, count: int, sheet_no: str) -> dict:
    return {
        "reason": "legend",
        "title": "Tag also appears in the legend",
        "found": f"Tag {tag} appears {count} times on {sheet_no}, and the legend also lists {tag} as {description.lower()}.",
        "why": "The same letter is used for a device and for a legend entry, so some of these placements may not be devices.",
        "fix": "Spot check a few against the plan to confirm they are devices, then approve or reject the ones that are not.",
        "where": f"{sheet_no} and the legend sheet.",
    }


def classify(clusters: list[DeviceCluster], sheets: list[DetectedSheet]) -> list[ClassifiedItem]:
    sheet_no = {s.page_index: (s.number or f"page {s.page_index + 1}") for s in sheets}
    abbrev = {
        e.symbol: e.description
        for s in sheets
        for e in s.legend
        if e.kind == "abbreviation"
    }
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
                items.append(_item(cat, c, "attention", _ambiguous_tag_warning(c.tag, abbrev[c.tag], c.count, no)))
            else:
                items.append(_item(cat, c, "ready", None))
        elif is_fixture_type(c.tag):
            cat = CATALOG["luminaire_generic"]
            cat = _rename(cat, f"Luminaire type {c.tag}")
            items.append(_item(cat, c, "attention", _fixture_warning(c.tag, c.count, no)))
        elif c.tag in abbrev:
            items.append(ClassifiedItem(
                catalog_id="unclassified", name=f"{c.tag} — {abbrev[c.tag].title()}",
                system="Unknown", category="Unclassified", unit="ea", symbol="generic",
                quantity=c.count, sheet_page_index=c.sheet_page_index, placements=c.placements,
                status="attention", warning=_modifier_warning(c.tag, abbrev[c.tag], c.count, no),
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
