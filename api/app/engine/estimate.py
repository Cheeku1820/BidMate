"""End-to-end estimate: PDF + location -> priced Division 26 takeoff.

Runs the deterministic Documents + Counting agents, then classifies and
prices with the LLM when a key is present, or the deterministic classifier
+ regional table when it is not. Returns a JSON-serializable dict the
frontend renders. The model never sees or sets a total -- the engine
multiplies counts by unit costs here, in one place.
"""

from __future__ import annotations

import re
from collections import defaultdict

from . import classification, counting, documents, llm, regions
from .catalog import CATALOG

# llm._prompt() truncates whatever blob this function builds to its own
# [:6000] before it ever reaches the model -- that slice, not any cap
# defined here, is the real budget. Sizing NOTES_CAP or the assembly order
# against a bigger number would make every cap in this module a lie about
# what actually reaches the classifier. Duplicating the number is an
# accepted coupling; llm.py is not touched by this module.
PROMPT_BUDGET = 6000
# A person's notes get a modest, guaranteed slice of that budget -- big
# enough for real project notes, small enough that even a maximal payload
# cannot crowd the drawings' own schedule text out of the window the
# classifier actually reads.
NOTES_CAP = 1200
CONTEXT_CAP = 12000

# A line shaped exactly like one of this module's own block headers
# ("=== ... ==="). Matched per-line so multi-line untrusted text can't
# smuggle in a forged boundary anywhere inside it.
_HEADER_LINE_RE = re.compile(r"^[ \t]*===.*===[ \t]*$", re.MULTILINE)


def _defang_block_headers(text: str) -> str:
    """Neutralise any line that reads as one of this module's own
    "=== ... ===" block headers, wherever it appears.

    The parameters `context` and `estimator_notes` are already kept
    separate -- but the *rendered* text is one string, and a specification
    whose extracted text happens to contain the literal line
    '=== Estimator notes and assumptions ===' would otherwise render a
    second, indistinguishable authoritative block inside the untrusted
    one. That would put the guarantee back on the model not being fooled
    by a forged header, which is exactly what this function exists to
    avoid depending on.

    Punctuation is swapped rather than the line being dropped -- a removed
    line is just a different way to hide content from the person
    reviewing it. This runs on `context` (untrusted document text) and on
    every estimator-note field: a note is trusted, but an estimator who
    pastes a stray header line shouldn't be able to break the block
    structure either.
    """
    if not text:
        return text
    return _HEADER_LINE_RE.sub(lambda m: m.group(0).replace("=", "-"), text)


def build_classifier_context(schedule_text: str, context: str, estimator_notes: list[dict] | None) -> str:
    """The text the classifier reads, assembled from three sources that
    are deliberately kept apart.

    `schedule_text` is the drawings' own schedules -- the highest
    priority, listed first so it is the last thing truncation can reach.
    `context` is text lifted from other uploaded documents -- untrusted,
    because a drawing set arrives from outside and text inside it must be
    data rather than instruction -- listed last, since it is already the
    least-trusted block and the one already accustomed to being cut when
    space runs out. `estimator_notes` are typed records a person wrote and
    is accountable for, so they sit between the two: framed as something
    to act on, and capped small enough that they do not need the schedule
    to make room for them.

    Nothing writes document text into the notes block: the two arrive as
    separate parameters and are formatted separately here. Untrusted text
    also cannot forge a second copy of either block's own header (see
    `_defang_block_headers`), so the guarantee holds by shape rather than
    by wording or by trusting the model to see through a lookalike.
    """
    parts: list[str] = []

    schedule_text = _defang_block_headers(schedule_text or "")
    if schedule_text:
        parts.append(schedule_text)

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
            parts.append(
                "=== Estimator notes and assumptions ===\n"
                "Written by the estimator for this project. These take precedence "
                "over what the drawings appear to say.\n" + block
            )

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


def _sheet_no(sheets, page_index) -> str:
    for s in sheets:
        if s.page_index == page_index:
            return s.number or f"page {page_index + 1}"
    return "?"


def _compute(path: str, location: str, context: str = "", estimator_notes: list[dict] | None = None):
    """Shared pipeline: returns (per-cluster rows, sheets, meta). Each row
    carries coordinates and cost. `context` is extra text pulled from the
    other project documents (specs, addenda) -- untrusted -- so the
    classifier can read a fixture or panel schedule that lives outside the
    drawings. `estimator_notes` are typed records a person wrote for this
    project; they reach the classifier through their own labelled block,
    never merged into `context`, so document text can never be promoted
    into something framed as an instruction."""
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
                rows.append(_row_from_spec(spec, c, sheets, labor_rate, material_factor))
            used_llm = True
            source = "llm"
        except Exception as exc:  # noqa: BLE001 -- any failure falls back, demo must not break
            used_llm = False
            location_note += f"  (Automated pricing unavailable: {type(exc).__name__}; used regional table.)"

    if not used_llm:
        classified = classification.classify(clusters, sheets)
        for c, item in zip(clusters, classified):
            rows.append(_row_from_catalog(item, c, sheets, labor_rate, material_factor))

    meta = {
        "location": location,
        "location_note": location_note,
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
    rows, sheets, meta = _compute(path, location, context, estimator_notes)
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
    thing a warning exists to prevent."""
    return {
        "reason": "legend",
        "title": "Item type needs confirmation",
        "found": f"Type {tag} appears {count} times on {sheet_no}, but its description could not be matched to a schedule with confidence.",
        "why": "The exact item and its price can't be confirmed until the type is matched to the schedule.",
        "fix": "Confirm the item type against the schedule, then approve.",
        "where": f"{sheet_no} and the project schedules.",
    }


def _row_from_spec(spec: dict, cluster, sheets, labor_rate: float, material_factor: float) -> dict:
    qty = cluster.count
    unit_material = float(spec.get("material_cost", 0) or 0) * material_factor
    unit_hours = float(spec.get("labor_hours", 0) or 0)
    material = round(unit_material * qty, 2)
    hours = round(unit_hours * qty, 2)
    labor = round(hours * labor_rate, 2)
    status = "ready" if spec.get("confidence") == "high" else "attention"
    sheet_no = _sheet_no(sheets, cluster.sheet_page_index)
    warning = None if status == "ready" else _unconfirmed_type_warning(cluster.tag, qty, sheet_no)
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
    cat = CATALOG.get(item.catalog_id)
    qty = item.quantity
    unit_material = (cat.material_cost if cat else 0.0) * material_factor
    unit_hours = cat.labor_hours if cat else 0.0
    material = round(unit_material * qty, 2)
    hours = round(unit_hours * qty, 2)
    labor = round(hours * labor_rate, 2)
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
