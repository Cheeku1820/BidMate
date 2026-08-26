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


def classify(clusters: list[DeviceCluster], sheets: list[DetectedSheet]) -> list[ClassifiedItem]:
    sheet_no = {s.page_index: (s.number or f"page {s.page_index + 1}") for s in sheets}
    items: list[ClassifiedItem] = []
    for c in clusters:
        no = sheet_no.get(c.sheet_page_index, "?")
        if c.tag in TAG_TO_CATALOG:
            cat = CATALOG[TAG_TO_CATALOG[c.tag]]
            items.append(_item(cat, c, "ready", None))
        elif is_fixture_type(c.tag):
            cat = CATALOG["luminaire_generic"]
            cat = _rename(cat, f"Luminaire type {c.tag}")
            items.append(_item(cat, c, "attention", _fixture_warning(c.tag, c.count, no)))
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
