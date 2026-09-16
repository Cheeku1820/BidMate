"""One priced row per counted cluster, in the shape the review store
ingests.

Two builders, one per classification source: `_row_from_spec` prices a
model-classified cluster (the device's own cost is the model's, its
rough-in the price book's), `_row_from_catalog` prices a
deterministically classified one through the Pricing agent. Both emit
the same dict, so nothing downstream knows which path a row took.
`sheet.py` and `estimate.py` both import from here, which is what keeps
the two of them from importing each other.
"""

from __future__ import annotations

from . import assemblies, pricing
from .catalog import CATALOG


def _sheet_no(sheets, page_index) -> str:
    for s in sheets:
        if s.page_index == page_index:
            return s.number or f"page {page_index + 1}"
    return "?"


def _unconfirmed_type_warning(tag: str, count: int, sheet_no: str) -> dict:
    """The four-field shape for an item the classifier could not place
    confidently. An attention item with no warning tells the estimator
    something is wrong but not what to do about it, which is the one
    thing a warning exists to prevent.

    Deliberately duplicated as ingest.py's fallback_warning() across the
    engine/API module boundary -- the two must stay word for word
    identical, which test_ingest_mapping.py asserts, since nothing in the
    import graph ties them together."""
    return {
        "reason": "legend",
        "title": "Item type needs confirmation",
        "found": f"Type {tag} appears {count} time(s) on {sheet_no}, but its description could not be matched to a schedule.",
        "why": "The exact item and its price can't be confirmed until the type is matched to the schedule.",
        "fix": "Confirm the item type against the schedule, then approve.",
        "where": f"{sheet_no} and the project schedules.",
    }


def _model_warning(raw: dict | None, tag: str, count: int, sheet_no: str) -> dict:
    """The model was asked to write its own warning alongside the
    classification, in the same call (grounded-classification-warnings-
    design.md) -- but it only ever sees the DOCUMENT-WIDE count for a tag
    (_compute() aggregates tag_counts across every sheet before the call),
    never a specific cluster's own count or sheet, and it isn't given a
    sheet number to write "where" from at all. Trusting it for found/where
    would mean the same warning -- including a count and a sheet that may
    not match -- gets attached to every same-tag cluster across every
    sheet in the document.

    So found/where are never taken from the model, even when it returned
    something complete: they're always synthesized from THIS cluster's own
    real tag/count/sheet, the one thing that's actually true about the row
    being built. title/why/fix are the model's reasoning about *why* the
    classification is uncertain -- legitimately the same regardless of
    which sheet instance triggered it -- so those are trusted when present
    and complete. Falls back to the fully deterministic template if the
    model omitted "warning" or any of those three fields.

    Completeness is checked on title/why/fix only, not on all five: the
    prompt no longer asks for found/where at all (llm.py's _prompt()), so
    requiring them here would make every well-formed model warning fall
    back and the model's reasoning would never reach an estimator."""
    template = _unconfirmed_type_warning(tag, count, sheet_no)
    fields = ("title", "why", "fix")
    if not (isinstance(raw, dict) and all(str(raw.get(f) or "").strip() for f in fields)):
        return template
    return {
        "reason": "legend",
        "title": str(raw["title"]).strip(),
        "found": template["found"],
        "why": str(raw["why"]).strip(),
        "fix": str(raw["fix"]).strip(),
        "where": template["where"],
    }


def _num(value) -> float:
    """A model-supplied number, or 0.0. Model output is data: a string, a
    null, or a nonsense value must not raise out of the middle of a
    takeoff, and reading it as zero fails toward "unpriced", which is the
    direction pricing.py already refuses to guess in."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def resolve_assembly_parent(spec: dict) -> str | None:
    """Which catalog item's assembly belongs to a model-classified row --
    the box, plate, wire and conduit it drags along -- or None.

    Assemblies are keyed by catalog id and this path had none, so with an
    API key configured (the normal case for a real project) every device
    was priced bare while the CLI counted its rough-in. The key has to
    come from somewhere, and there are only three candidates:

    - **The `symbol` field.** Rejected. The classifier is not asked for
      one, so it never returns one -- `spec["symbol"]` is always absent
      today. Worse, the symbol vocabulary does not separate the items
      whose assemblies differ: `panel` covers both the panelboard
      ($147.70 of #4 feeder and conduit per unit) and the disconnect
      ($21.50 of #10), so whichever way that one cell is written, one of
      them is wrong by about seven times. A mapping that is right six
      times and badly wrong the seventh is the fabricated mapping this
      decision exists to avoid.
    - **The cluster's tag, through TAG_TO_CATALOG.** Rejected. It resolves
      cleanly, but it is a *second* classifier running beside the model
      and disagreeing with it silently: if the model reads tag DS off the
      schedule as a panelboard, the tag map still says disconnect, and the
      row would be named one thing and roughed in as another. The
      assembly must follow the classification that produced the item.
    - **Asking the classifier for the catalog id.** Taken. Assemblies are
      keyed by catalog id, so the classifier is asked for a catalog id,
      from the closed list enumerated out of CATALOG itself (llm.py's
      `_prompt`), with "none" available and recommended whenever nothing
      on the list is genuinely the same kind of item.

    Whatever comes back is validated against CATALOG rather than trusted:
    model output is data. An exact catalog *name* is accepted as a second
    resolver, so a response that omits the id but names a real catalog
    item still gets its rough-in; the match is exact against a closed set,
    so it cannot resolve to something the model did not name.

    Failure mode, and it is deliberate: an item that resolves to neither
    is priced as the bare device -- material and hours for the device
    only, no box, no wire, no conduit -- which *understates* it. That is
    the direction to fail in: a visibly low line an estimator corrects
    beats a confident total carrying rough-in for the wrong item. It is
    not left silent either. `_compute` counts these and the project's
    basis note says how many were priced that way.

    The opposite direction is refused outright. The prompt tells the model
    two separate things about a non-device tag -- report it Unclassified
    with no material and no hours, *and* pick catalog_id "none" -- and
    obeying the first without the second turned a $0 row into a full
    receptacle rough-in. On the real set 18 of 45 clusters are exactly
    those tags (VA, CKT, AMP, USB, NOT, OFF), so this is the common case
    rather than an edge one. A row the classifier itself declined to
    price gets no assembly: pricing.py's principle is that an unpriced
    visible item is recoverable and a fabricated price in a submitted bid
    is not, and an `attention` status riding along is a mitigation, not a
    guard.
    """
    # Checked before any resolution, because the question "which assembly"
    # does not arise for an item the classifier did not treat as a device.
    if str(spec.get("category") or "").strip().casefold() == "unclassified":
        return None
    if _num(spec.get("material_cost")) <= 0 and _num(spec.get("labor_hours")) <= 0:
        return None

    raw = str(spec.get("catalog_id") or "").strip().casefold()
    # An explicit opt-out is an answer, not a gap: the name resolver must
    # not overturn it. Without this, a model that correctly declined to
    # pick an id had its decision reversed by its own item name.
    if raw == "none":
        return None
    if raw in CATALOG:
        return raw
    name = str(spec.get("name") or "").strip().casefold()
    if name:
        for catalog_id, cat in CATALOG.items():
            if cat.name.casefold() == name:
                return catalog_id
    return None


def _row_from_spec(spec: dict, cluster, sheets, labor_rate: float, material_factor: float,
                   assembly_parent: str | None = None) -> dict:
    qty = cluster.count
    # The device's own cost is the model's; its rough-in is the price
    # book's. material_factor applies once, to the whole figure -- a reel
    # of #12 costs 45% more in Unalaska exactly as the receptacle does.
    asm = assemblies.expand(assembly_parent, qty) if assembly_parent else None
    device_material = _num(spec.get("material_cost")) * qty
    device_hours = _num(spec.get("labor_hours")) * qty
    material = round((device_material + (asm.material_cost if asm else 0.0)) * material_factor, 2)
    hours = round(device_hours + (asm.labor_hours if asm else 0.0), 2)
    labor = round(hours * labor_rate, 2)
    status = "ready" if spec.get("confidence") == "high" else "attention"
    sheet_no = _sheet_no(sheets, cluster.sheet_page_index)
    warning = None if status == "ready" else _model_warning(spec.get("warning"), cluster.tag, qty, sheet_no)
    return {
        "name": spec.get("name", f"Symbol {cluster.tag}"),
        "system": spec.get("system", "Unknown"),
        "category": spec.get("category", "Devices"),
        "unit": spec.get("unit", "ea"),
        "quantity": qty,
        "status": status,
        "sheet": sheet_no,
        "page": cluster.sheet_page_index + 1,
        "sheet_id": str(cluster.sheet_page_index),
        "tag": cluster.tag,
        "x": cluster.placements[0].x if cluster.placements else 0,
        "y": cluster.placements[0].y if cluster.placements else 0,
        "placements": [[p.x, p.y] for p in cluster.placements],
        "material_cost": material,
        "labor_hours": hours,
        "labor_cost": labor,
        "total_cost": round(material + labor, 2),
        "symbol": spec.get("symbol", ""),
        "warning": warning,
    }


def _row_from_catalog(item, cluster, sheets, labor_rate: float, material_factor: float) -> dict:
    """Price one classified cluster through the Pricing agent.

    The cost arithmetic is `pricing.price_item`'s, not this module's, so
    the app and the CLI count the same material: the device *and* its
    assembly -- box, plate, wire, conduit, connectors. Pricing a bare
    device understates the job, and it understated it here for as long
    as this function did the multiplication itself.

    `material_factor` is the caller's, because `price_item` does not know
    about locations. It is applied once, to the whole material figure:
    material costs 45% more in Unalaska for a box and a reel of #12
    exactly as much as for the receptacle they land on. Labour is already
    at the caller's location rate -- `labor_rate` is passed into
    `price_item`, not left at its national default -- and a location does
    not change how many hours an install takes, so no factor applies to
    it."""
    priced = pricing.price_item(item, labor_rate)
    qty = item.quantity
    material = round(priced.material_cost * material_factor, 2)
    hours = priced.labor_hours
    labor = priced.labor_cost
    return {
        "name": item.name,
        "system": item.system,
        "category": item.category,
        "unit": item.unit,
        "quantity": qty,
        "status": item.status,
        "sheet": _sheet_no(sheets, cluster.sheet_page_index),
        "page": cluster.sheet_page_index + 1,
        "sheet_id": str(cluster.sheet_page_index),
        "tag": item.source_tag,
        "x": cluster.placements[0].x if cluster.placements else 0,
        "y": cluster.placements[0].y if cluster.placements else 0,
        "placements": [[p.x, p.y] for p in cluster.placements],
        "material_cost": material,
        "labor_hours": hours,
        "labor_cost": labor,
        "total_cost": round(material + labor, 2),
        "symbol": item.symbol,
        "warning": item.warning,
    }
