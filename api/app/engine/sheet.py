"""The per-sheet half of the pipeline: price one sheet's clusters from
the run's classification, crop the evidence, read the sheet with vision.
Everything after this is a store write, which is the worker's job."""

from __future__ import annotations

import base64
import logging
import re

from . import assemblies, classification as classification_mod, documents, llm
from .contracts import Classification, DetectedSheet, DeviceCluster, SheetResult
from .rows import _row_from_catalog, _row_from_spec, resolve_assembly_parent

logger = logging.getLogger(__name__)


def rows_for(
    sheet: DetectedSheet,
    clusters: list[DeviceCluster],
    classification: Classification,
    sheets: list[DetectedSheet],
) -> tuple[list[dict], bool, set[str]]:
    """Returns (rows, assembly_applied, bare_names) -- the last two feed
    the wiring and unmatched notes, which are folded up across sheets by
    whoever runs the whole set.

    A cluster whose tag the run never classified yields no row on either
    path: the run's classification decides what is priced, and a tag it
    has no answer for is not quietly named here.
    """
    rows: list[dict] = []
    # Item names priced without their assembly -- see resolve_assembly_parent.
    bare: set[str] = set()
    applied = False
    if classification.source == "llm":
        for c in clusters:
            spec = classification.specs_by_tag.get(c.tag)
            if not spec:
                continue
            parent = resolve_assembly_parent(spec)
            if parent and assemblies.expand(parent, 1).lines:
                applied = True
            row = _row_from_spec(spec, c, sheets, classification.labor_rate, classification.material_factor, parent)
            # A priced row whose classification matched no catalog item
            # carries no rough-in. That understates it, so it is counted
            # here and disclosed on the project rather than left to be
            # noticed as a low number.
            if row["total_cost"] > 0 and not parent:
                bare.add(row["name"])
            rows.append(row)
    else:
        known = classification.catalog_items or {}
        for c in clusters:
            if c.tag not in known:
                continue
            # `catalog_items` is keyed by tag and a tag can be counted on
            # several sheets, each its own cluster with its own count. The
            # run-level entry says the tag was classified; the row is
            # priced from this cluster's own classification so its
            # quantity, placements and warning text are this sheet's.
            item = classification_mod.classify_cluster(c, sheets)
            if assemblies.expand(item.catalog_id, 1).lines:
                applied = True
            rows.append(_row_from_catalog(item, c, sheets, classification.labor_rate, classification.material_factor))
    return rows, applied, bare


_TAG_IN_NAME = re.compile(r"\btype\s+([A-Z]\d?)\b|\(([A-Z]{1,2}\d?)\)", re.I)


def _tag_of(device_name: str) -> str | None:
    m = _TAG_IN_NAME.search(device_name or "")
    if not m:
        return None
    return (m.group(1) or m.group(2)).upper()


def reconcile_vision(ai_reading: dict, rows: list[dict]) -> None:
    """Feed one sheet's vision reading back into its counted rows: where
    the reading identified the fixture behind a counted tag (e.g. it read
    "Type A recessed luminaire" for the sheet's A tags), adopt that richer
    name and, since the drawing itself confirmed the type, move the row
    from Needs attention to Ready and clear its fixture-needs-confirmation
    warning. The count and position stay exactly as the deterministic
    reader found them -- vision resolves *what* it is, not *how many*."""
    for row in rows:
        tag = (row.get("tag") or "").upper()
        if not tag:
            continue
        for dev in ai_reading.get("devices", []):
            if _tag_of(dev.get("name", "")) == tag:
                row["ai_confirmed"] = True  # the reading saw this device on the drawing
                # Only let vision RENAME + resolve a row the counter was
                # unsure about (a fixture awaiting its schedule). A row the
                # deterministic classifier was already confident about
                # keeps its name -- vision can misread a symbol, and it
                # should not overwrite a good classification, only rescue
                # an uncertain one.
                if row.get("status") == "attention":
                    row["name"] = dev["name"]
                    row["status"] = "ready"
                    row["warning"] = None
                break


def finish(
    path: str,
    sheet: DetectedSheet,
    clusters: list[DeviceCluster],
    classification: Classification,
    sheets: list[DetectedSheet],
) -> SheetResult:
    """One sheet, priced and evidenced: rows in the review store's shape,
    each carrying a crop of the source page around its placements, and
    the vision reading when a key is present."""
    rows, applied, bare = rows_for(sheet, clusters, classification, sheets)
    for row in rows:
        placements = row["placements"] or [(row["x"], row["y"])]
        png = documents.render_evidence_crop(path, sheet.page_index, sheet.width_pt, sheet.height_pt, placements)
        row["evidence_png_b64"] = base64.b64encode(png).decode("ascii") if png else None
    ai_reading = None
    if llm.available() and not sheet.unreadable_reason:
        try:
            with open(path, "rb") as fh:
                png = documents.render_vision_png_bytes(fh.read(), sheet.page_index)
            res = llm.read_sheet_image(png, sheet.number or f"page {sheet.page_index + 1}")
            ai_reading = res if res.get("devices") else None
        except Exception as exc:  # noqa: BLE001 -- vision is enrichment; the sheet still lands
            logger.warning("vision read failed (%s)", type(exc).__name__)
    if ai_reading:
        reconcile_vision(ai_reading, rows)
    return SheetResult(rows=rows, ai_reading=ai_reading, assembly_applied=applied, bare_names=bare)
