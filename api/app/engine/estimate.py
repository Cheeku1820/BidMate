"""End-to-end estimate: PDF + location -> priced Division 26 takeoff.

Runs the deterministic Documents + Counting agents, then classifies and
prices with the LLM when a key is present, or the deterministic classifier
+ regional table when it is not. Returns a JSON-serializable dict the
frontend renders. The model never sees or sets a total -- the engine
multiplies counts by unit costs here, in one place.
"""

from __future__ import annotations

from collections import defaultdict

from . import classification, counting, documents, llm, regions
from .catalog import CATALOG


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


def _compute(path: str, location: str, context: str = ""):
    """Shared pipeline: returns (per-cluster rows, sheets, meta). Each row
    carries coordinates and cost. `context` is extra text pulled from the
    other project documents (specs, addenda) so the classifier can read a
    fixture or panel schedule that lives outside the drawings."""
    sheets = documents.detect_sheets(path)
    clusters = counting.count(path, sheets)

    # Aggregate tag counts across sheets for the classifier, and gather the
    # schedule text the LLM interprets fixture types from -- the drawings'
    # own schedule text plus whatever the other documents contributed.
    tag_counts: dict[str, int] = defaultdict(int)
    for c in clusters:
        tag_counts[c.tag] += c.count
    tags = [{"tag": t, "count": n} for t, n in sorted(tag_counts.items(), key=lambda kv: -kv[1])]
    schedule_text = "\n\n".join(s.schedule_text for s in sheets if s.schedule_text)
    if context:
        schedule_text = (schedule_text + "\n\n=== From project specifications and addenda ===\n\n" + context)[:16000]

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


def full_takeoff(path: str, location: str, context: str = "") -> dict:
    """Per-cluster takeoff with coordinates and page dimensions, for
    injecting into the review store (one reviewable item per device
    group, positioned on its sheet). Each sheet carries an `id` (unique
    within this file, by page) that items reference, so a merge across
    several drawing files can keep sheet references unambiguous."""
    rows, sheets, meta = _compute(path, location, context)
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


def _row_from_spec(spec: dict, cluster, sheets, labor_rate: float, material_factor: float) -> dict:
    qty = cluster.count
    unit_material = float(spec.get("material_cost", 0) or 0) * material_factor
    unit_hours = float(spec.get("labor_hours", 0) or 0)
    material = round(unit_material * qty, 2)
    hours = round(unit_hours * qty, 2)
    labor = round(hours * labor_rate, 2)
    status = "ready" if spec.get("confidence") == "high" else "attention"
    return {
        "name": spec.get("name", f"Symbol {cluster.tag}"),
        "system": spec.get("system", "Unknown"),
        "category": spec.get("category", "Devices"),
        "unit": spec.get("unit", "ea"),
        "quantity": qty,
        "status": status,
        "sheet": _sheet_no(sheets, cluster.sheet_page_index),
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
    }
