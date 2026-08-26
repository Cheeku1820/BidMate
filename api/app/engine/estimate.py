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


def estimate(path: str, location: str) -> dict:
    sheets = documents.detect_sheets(path)
    clusters = counting.count(path, sheets)

    # Aggregate tag counts across sheets for the classifier, and gather the
    # schedule text the LLM interprets fixture types from.
    tag_counts: dict[str, int] = defaultdict(int)
    for c in clusters:
        tag_counts[c.tag] += c.count
    tags = [{"tag": t, "count": n} for t, n in sorted(tag_counts.items(), key=lambda kv: -kv[1])]
    schedule_text = "\n\n".join(s.schedule_text for s in sheets if s.schedule_text)

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

    items = _consolidate(rows)
    material_total = round(sum(r["material_cost"] for r in items), 2)
    labor_hours_total = round(sum(r["labor_hours"] for r in items), 2)
    labor_cost_total = round(sum(r["labor_cost"] for r in items), 2)
    total = round(material_total + labor_cost_total, 2)

    return {
        "location": location,
        "location_note": location_note,
        "labor_rate": round(labor_rate, 2),
        "material_factor": round(material_factor, 3),
        "source": source,
        "sheets": [
            {"number": s.number, "page": s.page_index + 1, "unreadable": s.unreadable_reason or None}
            for s in sheets
        ],
        "items": items,
        "totals": {
            "material": material_total,
            "labor_hours": labor_hours_total,
            "labor_cost": labor_cost_total,
            "total_direct_cost": total,
            "item_count": len(items),
            "attention_count": sum(1 for r in items if r["status"] == "attention"),
        },
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
        "unit": spec.get("unit", "ea"),
        "quantity": qty,
        "status": status,
        "sheet": _sheet_no(sheets, cluster.sheet_page_index),
        "tag": cluster.tag,
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
        "unit": item.unit,
        "quantity": qty,
        "status": item.status,
        "sheet": _sheet_no(sheets, cluster.sheet_page_index),
        "tag": item.source_tag,
        "material_cost": material,
        "labor_hours": hours,
        "labor_cost": labor,
        "total_cost": round(material + labor, 2),
    }
