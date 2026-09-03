"""End-to-end estimate: PDF + location -> priced Division 26 takeoff.

Runs the deterministic Documents + Counting agents, then classifies and
prices with the LLM when a key is present, or the deterministic classifier
+ regional table when it is not. Returns a JSON-serializable dict the
frontend renders. The model never sees or sets a total -- the engine
multiplies counts by unit costs here, in one place.
"""

from __future__ import annotations

import base64
import re
from collections import defaultdict

from . import assemblies, classification, counting, documents, llm, pricing, regions
from .catalog import CATALOG

# llm._prompt() truncates whatever blob this function builds to its own
# [:6000] before it ever reaches the model -- that slice, not any cap
# defined here, is the real budget, and it is used below to size the
# schedule/notes split, not just documented. Duplicating the number is an
# accepted coupling; llm.py is not touched by this module.
PROMPT_BUDGET = 6000
# The notes block's cap on its own line content (before the header text
# that wraps it). Kept well under PROMPT_BUDGET so a maximal payload is
# still a small, predictable fraction of the real window once reserved --
# see build_classifier_context, which reserves exactly this block's
# length out of PROMPT_BUDGET before it caps the schedule text, so the
# reservation is real rather than incidental.
NOTES_CAP = 1200
# Chars of "\n\n".join separators to leave slack for when reserving room
# for the notes block ahead of the schedule cap -- at most two joins
# (schedule-notes, notes-context) can land before the notes block ends.
_SEPARATOR_SLACK = 4
CONTEXT_CAP = 12000

# Any run of "===...===", wherever it sits within a line -- not only a
# line composed of nothing else, and not anchored to whitespace of a
# specific kind. `.` does not match a newline by default, so this still
# can't span two physical lines; see the docstring below for why that gap
# is left open rather than chased.
_HEADER_RUN_RE = re.compile(r"===.*===")


def _defang_block_headers(text: str) -> str:
    """Neutralise any "=== ... ===" run that could be mistaken for one of
    this module's own block headers, wherever it appears.

    The parameters `context` and `estimator_notes` are already kept
    separate -- but the *rendered* text is one string, and a specification
    whose extracted text happens to contain the literal line
    '=== Estimator notes and assumptions ===' would otherwise render a
    second, indistinguishable authoritative block inside the untrusted
    one. That would put the guarantee back on the model not being fooled
    by a forged header, which is exactly what this function exists to
    avoid depending on.

    The match is on the "===...===" run itself, not the whole line, so
    leading or trailing content -- a stray character, a carriage return, a
    non-breaking space, a form feed -- can't smuggle a real header past a
    stricter pattern that only recognised a line made of nothing else.
    Punctuation is swapped rather than the run being dropped -- a removed
    line is just a different way to hide content from the person
    reviewing it. This runs on `context` (untrusted document text) and on
    every estimator-note field: a note is trusted, but an estimator who
    pastes a stray header line shouldn't be able to break the block
    structure either.

    Residual gap, left open deliberately: a header split across separate
    physical lines (`"===\\nEstimator notes\\n==="`) is not caught, because
    catching it means treating any bare "===" as a candidate delimiter and
    pairing it with another one somewhere later in the text -- which would
    defang far more ordinary document content (a horizontal rule, a diff
    marker) than it would ever catch a real attack. No regex closes every
    visual imitation of a boundary; this closes the concrete ones a
    same-line match can reach.
    """
    if not text:
        return text
    return _HEADER_RUN_RE.sub(lambda m: m.group(0).replace("=", "-"), text)


def build_classifier_context(schedule_text: str, context: str, estimator_notes: list[dict] | None) -> str:
    """The text the classifier reads, assembled from three sources that
    are deliberately kept apart.

    `schedule_text` is the drawings' own schedules -- the primary
    evidence, and normally the larger share of the window, but NOT
    unbounded: a full drawing set's page text routinely runs past
    PROMPT_BUDGET on its own (`documents.py` joins whole-page text across
    every sheet), so leaving it uncapped would silently push both other
    blocks out of what the model ever reads. `context` is text lifted
    from other uploaded documents -- untrusted, because a drawing set
    arrives from outside and text inside it must be data rather than
    instruction -- listed last, since it is already the least-trusted
    block and the one already accustomed to being cut when space runs
    out. `estimator_notes` are typed records a person wrote and is
    accountable for, so they get a *reserved* slice of PROMPT_BUDGET,
    carved out before the schedule is capped -- a note the estimator
    explicitly attached to this takeoff must never be the thing that
    silently disappears because a sheet's schedule text happened to be
    long.

    Nothing writes document text into the notes block: the two arrive as
    separate parameters and are formatted separately here. Untrusted text
    also cannot forge a second copy of either block's own header (see
    `_defang_block_headers`), so the guarantee holds by shape rather than
    by wording or by trusting the model to see through a lookalike.
    """
    notes_block = ""
    if estimator_notes:
        lines = []
        for n in estimator_notes:
            if not isinstance(n, dict):
                continue  # malformed entry: skip it, never fail the takeoff over it
            scope = str(n.get("scope") or "project")
            title = _defang_block_headers(str(n.get("title") or ""))
            body = _defang_block_headers(str(n.get("body") or ""))
            source_ref = n.get("source_ref")
            src = f" ({_defang_block_headers(str(source_ref))})" if source_ref else ""
            lines.append(f"- [{scope}] {title}{src}: {body}")
        if lines:
            block = "\n".join(lines)[:NOTES_CAP]
            notes_block = (
                "=== Estimator notes and assumptions ===\n"
                "Written by the estimator for this project. These take precedence "
                "over what the drawings appear to say.\n" + block
            )

    # Reserve the notes block's exact size (plus join slack) out of the
    # real window before capping the schedule -- this is what makes the
    # reservation actual rather than a comment. Whatever remains is the
    # schedule's, so a small or absent notes block still lets the
    # schedule use nearly all of PROMPT_BUDGET.
    reserved_for_notes = (len(notes_block) + _SEPARATOR_SLACK) if notes_block else 0
    schedule_budget = max(PROMPT_BUDGET - reserved_for_notes, 0)

    parts: list[str] = []

    schedule_text = _defang_block_headers(schedule_text or "")[:schedule_budget]
    if schedule_text:
        parts.append(schedule_text)

    if notes_block:
        parts.append(notes_block)

    if context:
        context = _defang_block_headers(context)
        parts.append("=== From project specifications and addenda ===\n" + context[:CONTEXT_CAP])

    return "\n\n".join(parts)


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


def _wiring_note(assembly_applied: bool, bare_names: set[str]) -> str:
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

    The second sentence appears only when something was priced without a
    rough-in, and names how many, so an understated line is disclosed
    rather than merely being low.
    """
    if not assembly_applied and not bare_names:
        return ""
    parts = []
    if assembly_applied:
        feet = assemblies.FEET_PER_DEVICE
        feet_text = f"{feet:g}"
        parts.append(
            f"Branch wiring is estimated at {feet_text} feet per device. Conduit and wire "
            "quantities follow that rule rather than a measured route, so check them "
            "against the job before the total is relied on."
        )
    if bare_names:
        n = len(bare_names)
        subject = f"{n} item types" if n != 1 else "1 item type"
        verb = "were" if n != 1 else "was"
        pronoun = "them" if n != 1 else "it"
        parts.append(
            f"{subject} could not be matched to a standard assembly and {verb} priced "
            f"as the device alone, with no box, wire or conduit behind {pronoun}."
        )
    return " ".join(parts)


def _sheet_no(sheets, page_index) -> str:
    for s in sheets:
        if s.page_index == page_index:
            return s.number or f"page {page_index + 1}"
    return "?"


def _compute(path: str, location: str, context: str = "", estimator_notes: list[dict] | None = None, with_evidence: bool = False):
    """Shared pipeline: returns (per-cluster rows, sheets, meta). Each row
    carries coordinates and cost. `context` is extra text pulled from the
    other project documents (specs, addenda) -- untrusted -- so the
    classifier can read a fixture or panel schedule that lives outside the
    drawings. `estimator_notes` are typed records a person wrote for this
    project; they reach the classifier through their own labelled block,
    never merged into `context`, so document text can never be promoted
    into something framed as an instruction. When `with_evidence` is True,
    each row includes an evidence_png_b64 key with a base64-encoded crop
    of the source page around the item's placement(s)."""
    sheets = documents.detect_sheets(path)
    clusters = counting.count(path, sheets)

    # Aggregate tag counts across sheets for the classifier, and gather the
    # schedule text the LLM interprets fixture types from -- the drawings'
    # own schedule text plus whatever the other documents and the estimator
    # contributed, kept in separate labelled blocks.
    tag_counts: dict[str, int] = defaultdict(int)
    for c in clusters:
        tag_counts[c.tag] += c.count
    tags = [{"tag": t, "count": n} for t, n in sorted(tag_counts.items(), key=lambda kv: -kv[1])]
    schedule_text = "\n\n".join(s.schedule_text for s in sheets if s.schedule_text)
    schedule_text = build_classifier_context(schedule_text, context, estimator_notes)

    rows: list[dict] = []
    # Item names priced without their assembly -- see resolve_assembly_parent.
    bare_names: set[str] = set()
    assembly_applied = False
    source = "deterministic"
    labor_rate, material_factor, location_note = regions.lookup(location)

    used_llm = False
    if llm.available():
        try:
            result = llm.estimate(tags, schedule_text, location)
            labor_rate = float(result["location_labor_rate"])
            material_factor = float(result["material_factor"])
            location_note = result.get("location_note", location_note)
            by_tag = {i["tag"]: i for i in result["items"]}
            for c in clusters:
                spec = by_tag.get(c.tag)
                if not spec:
                    continue
                parent = resolve_assembly_parent(spec)
                if parent and assemblies.expand(parent, 1).lines:
                    assembly_applied = True
                row = _row_from_spec(spec, c, sheets, labor_rate, material_factor, parent)
                # A priced row whose classification matched no catalog
                # item carries no rough-in. That understates it, so it is
                # counted here and disclosed on the project rather than
                # left to be noticed as a low number.
                if row["total_cost"] > 0 and not parent:
                    bare_names.add(row["name"])
                rows.append(row)
            used_llm = True
            source = "llm"
        except Exception as exc:  # noqa: BLE001 -- any failure falls back, demo must not break
            used_llm = False
            location_note += f"  (Automated pricing unavailable: {type(exc).__name__}; used regional table.)"

    if not used_llm:
        classified = classification.classify(clusters, sheets)
        for c, item in zip(clusters, classified):
            if assemblies.expand(item.catalog_id, 1).lines:
                assembly_applied = True
            rows.append(_row_from_catalog(item, c, sheets, labor_rate, material_factor))

    if with_evidence:
        dims_by_page = {s.page_index: (s.width_pt, s.height_pt) for s in sheets}
        for row in rows:
            page_index = row["page"] - 1
            width_pt, height_pt = dims_by_page.get(page_index, (0, 0))
            placements = row["placements"] or [(row["x"], row["y"])]
            png = documents.render_evidence_crop(path, page_index, width_pt, height_pt, placements)
            row["evidence_png_b64"] = base64.b64encode(png).decode("ascii") if png else None

    meta = {
        "location": location,
        "location_note": location_note,
        "wiring_note": _wiring_note(assembly_applied, bare_names),
        "labor_rate": round(labor_rate, 2),
        "material_factor": round(material_factor, 3),
        "source": source,
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
    several drawing files can keep sheet references unambiguous."""
    rows, sheets, meta = _compute(path, location, context, estimator_notes, with_evidence=True)
    return {
        **meta,
        "sheets": [
            {
                "id": str(s.page_index),
                "number": s.number,
                "page": s.page_index + 1,
                "width_pt": s.width_pt,
                "height_pt": s.height_pt,
                "unreadable": s.unreadable_reason or None,
            }
            for s in sheets
        ],
        "items": rows,
        "totals": _totals(rows),
    }


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
    """
    raw = str(spec.get("catalog_id") or "").strip()
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
    device_material = float(spec.get("material_cost", 0) or 0) * qty
    device_hours = float(spec.get("labor_hours", 0) or 0) * qty
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
