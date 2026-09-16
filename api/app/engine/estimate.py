"""End-to-end estimate: PDF + location -> priced Division 26 takeoff.

Composes the three job-shaped entry points -- `documents.read`,
`classification.classify_run`, `sheet.finish` -- into the whole-document
run the CLI and the corpus tests exercise, so there is one code path
whether the engine runs here in one pass or behind the API as three job
kinds. Returns a JSON-serializable dict the frontend renders. The model
never sees or sets a total -- the engine multiplies counts by unit costs,
in one place (`rows.py`).
"""

from __future__ import annotations

from collections import defaultdict

from . import assemblies, classification, counting, documents, sheet
from .context import build_classifier_context  # noqa: F401 -- re-exported for callers that import it from here
from .rows import (  # noqa: F401 -- re-exported: the row builders and their helpers moved to rows.py
    _model_warning,
    _row_from_catalog,
    _row_from_spec,
    _unconfirmed_type_warning,
    resolve_assembly_parent,
)

# How many unmatched item names the basis note lists before summarising
# the rest -- enough to act on, not enough to become a list.
_NAMED_IN_NOTE = 3


def _consolidate(rows: list[dict]) -> list[dict]:
    """Group per-sheet clusters into one row per catalog item, summing
    quantity and cost and collecting the sheets it appears on."""
    by_name: dict[str, dict] = {}
    for r in rows:
        key = r["name"]
        agg = by_name.get(key)
        if agg is None:
            agg = by_name[key] = {**r, "sheets": set()}
        else:
            for f in ("quantity", "material_cost", "labor_hours", "labor_cost", "total_cost"):
                agg[f] = round(agg[f] + r[f], 2)
            if r["status"] == "attention":
                agg["status"] = "attention"
        if r.get("sheet"):
            agg["sheets"].add(r["sheet"])
    out = []
    for agg in by_name.values():
        agg["sheets"] = sorted(agg["sheets"])
        out.append(agg)
    out.sort(key=lambda r: r["total_cost"], reverse=True)
    return out


def _wiring_note(assembly_applied: bool) -> str:
    """The project-level disclosure that branch wiring was assumed rather
    than measured.

    `assemblies.FEET_PER_DEVICE` drives most of the assembly material and
    labour on a set, and it is a rule of thumb: the drawing shows a
    homerun arrow, not a route, so the length is judgment from ceiling
    height and building geometry and is not in the file for anyone to
    read (ROADMAP 2.1). Producing that quantity without saying so is
    exactly the silent guess this product exists to prevent.

    It is said once, on the project, and not as a per-item warning. A
    warning is tied to non-`ready` status, so warning every item that
    carries wire would move essentially the whole takeoff to *Needs
    attention* and empty the review queue of meaning -- the four labels
    would still be four, but one of them would no longer separate
    anything.

    Every character of this sentence is written here. It carries no
    model output at all, which is what lets it survive the language
    check at the API boundary independently of the note beside it --
    see `_unmatched_note`.
    """
    if not assembly_applied:
        return ""
    feet_text = f"{assemblies.FEET_PER_DEVICE:g}"
    return (
        f"Branch wiring is estimated at {feet_text} feet per device. Conduit and wire "
        "quantities follow that rule rather than a measured route, so check them "
        "against the job before the total is relied on."
    )


def _unmatched_note(bare_names: set[str]) -> str:
    """What was priced without a rough-in, and which items those were.

    A separate field from `_wiring_note`, deliberately, and this is the
    whole reason: item names on the model-classified path are model
    output, they are interpolated here, and `ingest.basis_note` drops any
    note that fails the product language rules. Joined into one string, a
    single item named with a percentage or the word "confidence" would
    take the feet-per-device disclosure down with it -- silencing the
    exact sentence that exists to stop a quantity being assumed in
    silence. Two individually correct rules, coupled through one field.

    Split, the blast radius of a bad item name is this sentence alone.
    The engine's own disclosure is unaffected by anything a model wrote.

    Naming beats counting: "2 item types" tells an estimator a correction
    is needed but not where to make it. Capped at `_NAMED_IN_NOTE` so a
    bad set cannot turn the basis note into a list.
    """
    if not bare_names:
        return ""
    n = len(bare_names)
    subject = f"{n} item types" if n != 1 else "1 item type"
    verb = "were" if n != 1 else "was"
    pronoun = "them" if n != 1 else "it"
    shown = sorted(bare_names)[:_NAMED_IN_NOTE]
    listed = ", ".join(shown)
    remaining = n - len(shown)
    if remaining:
        listed += f" and {remaining} other{'s' if remaining != 1 else ''}"
    return (
        f"{subject} ({listed}) could not be matched to a standard assembly and {verb} "
        f"priced as the device alone, with no box, wire or conduit behind {pronoun}."
    )



def _compute(path: str, location: str, context: str = "", estimator_notes: list[dict] | None = None, with_evidence: bool = False):
    """Shared pipeline: returns (per-cluster rows, sheets, meta). Each row
    carries coordinates and cost. `context` is extra text pulled from the
    other project documents (specs, addenda) -- untrusted -- so the
    classifier can read a fixture or panel schedule that lives outside the
    drawings. `estimator_notes` are typed records a person wrote for this
    project; they reach the classifier through their own labelled block,
    never merged into `context`, so document text can never be promoted
    into something framed as an instruction. When `with_evidence` is True,
    each sheet goes through `sheet.finish`, so every row includes an
    evidence_png_b64 key with a base64-encoded crop of the source page
    around the item's placement(s) and a sheet read by vision carries its
    reading in `meta["readings"]`, keyed by page index."""
    reading = documents.read(path, "Drawings")
    sheets = reading.sheets
    clusters = counting.count(path, sheets)
    schedule_text = "\n\n".join(s.schedule_text for s in sheets if s.schedule_text)
    cls = classification.classify_run(clusters, sheets, schedule_text, context, estimator_notes, location)

    by_page: dict[int, list] = defaultdict(list)
    for c in clusters:
        by_page[c.sheet_page_index].append(c)

    rows: list[dict] = []
    bare_names: set[str] = set()
    assembly_applied = False
    readings: dict[int, dict] = {}
    for s in sheets:
        sheet_clusters = by_page.get(s.page_index)
        if not sheet_clusters:
            continue
        if with_evidence:
            result = sheet.finish(path, s, sheet_clusters, cls, sheets)
            sheet_rows, applied, bare = result.rows, result.assembly_applied, result.bare_names
            if result.ai_reading:
                readings[s.page_index] = result.ai_reading
        else:
            sheet_rows, applied, bare = sheet.rows_for(sheet_clusters, cls, sheets)
        rows.extend(sheet_rows)
        assembly_applied = assembly_applied or applied
        bare_names |= bare

    meta = {
        "location": location,
        "location_note": cls.location_note,
        "wiring_note": _wiring_note(assembly_applied),
        "unmatched_note": _unmatched_note(bare_names),
        "labor_rate": round(cls.labor_rate, 2),
        "material_factor": round(cls.material_factor, 3),
        "source": cls.source,
        "readings": readings,
    }
    return rows, sheets, meta


def _totals(rows: list[dict]) -> dict:
    material = round(sum(r["material_cost"] for r in rows), 2)
    hours = round(sum(r["labor_hours"] for r in rows), 2)
    labor = round(sum(r["labor_cost"] for r in rows), 2)
    return {
        "material": material,
        "labor_hours": hours,
        "labor_cost": labor,
        "total_direct_cost": round(material + labor, 2),
        "item_count": len(rows),
        "attention_count": sum(1 for r in rows if r["status"] == "attention"),
    }


def estimate(path: str, location: str) -> dict:
    """Consolidated estimate (one row per catalog item) for /estimate."""
    rows, sheets, meta = _compute(path, location)
    meta.pop("readings")
    items = _consolidate(rows)
    return {
        **meta,
        "sheets": [
            {"number": s.number, "page": s.page_index + 1, "unreadable": s.unreadable_reason or None}
            for s in sheets
        ],
        "items": items,
        "totals": _totals(items),
    }


def full_takeoff(path: str, location: str, context: str = "", estimator_notes: list[dict] | None = None) -> dict:
    """Per-cluster takeoff with coordinates and page dimensions, for
    injecting into the review store (one reviewable item per device
    group, positioned on its sheet). Each sheet carries an `id` (unique
    within this file, by page) that items reference, so a merge across
    several drawing files can keep sheet references unambiguous. A sheet
    the vision pass read carries its reading as `ai_reading`."""
    rows, sheets, meta = _compute(path, location, context, estimator_notes, with_evidence=True)
    readings = meta.pop("readings")
    payload_sheets = []
    for s in sheets:
        entry = documents.sheet_to_payload(s)
        if s.page_index in readings:
            entry["ai_reading"] = readings[s.page_index]
        payload_sheets.append(entry)
    return {
        **meta,
        "sheets": payload_sheets,
        "items": rows,
        "totals": _totals(rows),
    }
