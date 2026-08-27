"""ingest.py -- maps the takeoff engine's payload into domain rows.

This mapping used to live in the client (src/lib/store/seed-ingest.js).
It belongs on the server: it is domain logic, and ROADMAP invariant 7
keeps processing internals behind the API boundary. Pure functions, no
database access, so the mapping is testable without Postgres.

Coordinates arrive as PDF points and are normalized into the canvas's
fixed 1000x750 sheet space against EACH SHEET'S OWN dimensions -- a
sheet's markers land wrongly if scaled by another sheet's page size.

Both axes are scaled by the SAME factor -- the page's width extent
mapped onto SHEET_SPACE_W -- rather than x scaled independently by
width and y by height. A single uniform factor preserves the source
page's aspect ratio; scaling width into 1000 and height into 750
independently would squash any page that is not exactly 4:3.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.errors import DomainError
from app.takeoff.models import WarningReason

SHEET_SPACE_W = 1000
SHEET_SPACE_H = 750

WARNING_FIELDS = ("title", "found", "why", "fix", "where")
VALID_REASONS = {r.value for r in WarningReason}


@dataclass
class MappedTakeoff:
    sheets: list[dict]
    items: list[dict]


def normalize_point(value, extent: int, target: int) -> int:
    """Scale a PDF point into sheet space. An unmeasured page (extent 0)
    yields 0 rather than dividing by zero and failing the whole ingest."""
    if not extent:
        return 0
    return round((float(value or 0) / float(extent)) * target)


def infer_symbol(name: str, system: str) -> str:
    """Fallback glyph choice for a row that carries no symbol of its own.
    The classifier's symbol is preferred wherever it exists."""
    n = (name or "").lower()
    sys = (system or "").lower()
    if "gfci" in n or "receptacle" in n or ("outlet" in n and "data" not in n):
        return "receptacle"
    if "switch" in n:
        return "switch"
    if "disconnect" in n:
        return "disconnect"
    if "panel" in n or "board" in n:
        return "panel"
    if "junction" in n or "box" in n:
        return "junction"
    if "data" in n or "telecom" in n or "outlet" in n or "low voltage" in sys:
        return "data"
    if "exit" in n:
        return "exit"
    if "high bay" in n or "highbay" in n:
        return "highbay"
    if any(w in n for w in ("troffer", "downlight", "luminaire", "fixture", "light")) or sys == "lighting":
        return "troffer"
    return "junction"


def validate_warning(raw: dict) -> dict:
    """Four fields plus a typed reason, or the write is refused.

    A warning that skips one leaves the estimator without an answer to
    'what do I do about this', which is the whole reason the shape is
    enforced here rather than trusted from the pipeline.
    """
    if not isinstance(raw, dict):
        raise DomainError("invalid_warning", "A warning must be an object with reason, title, found, why, fix, and where.", status=422)
    missing = [f for f in WARNING_FIELDS if not str(raw.get(f) or "").strip()]
    if missing:
        raise DomainError(
            "invalid_warning",
            f"A warning is missing required field(s): {', '.join(missing)}. Every warning states what was found, why it matters, what to check, and where the evidence is.",
            status=422,
        )
    reason = str(raw.get("reason") or "").strip()
    if reason not in VALID_REASONS:
        raise DomainError(
            "invalid_warning",
            f"A warning carries an unrecognized reason {reason!r}. Recognized reasons are: {', '.join(sorted(VALID_REASONS))}.",
            status=422,
        )
    return {
        "reason": reason,
        "title": str(raw["title"]).strip(),
        "found": str(raw["found"]).strip(),
        "why": str(raw["why"]).strip(),
        "fix": str(raw["fix"]).strip(),
        "where": str(raw["where"]).strip(),
    }


def map_payload(payload: dict) -> MappedTakeoff:
    """Engine payload -> domain rows, keyed by the engine's sheet ids.

    `sheet_key` on each item names the sheet dict's `key`; the service
    layer resolves those to real database ids after inserting sheets.
    """
    sheets: list[dict] = []
    dims: dict[str, tuple[int, int]] = {}

    for index, raw in enumerate(payload.get("sheets") or []):
        key = str(raw.get("id") or f"sheet-{index}")
        width = int(raw.get("width_pt") or 0)
        height = int(raw.get("height_pt") or 0)
        dims[key] = (width, height)
        sheets.append({
            "key": key,
            "number": str(raw.get("number") or f"E{index + 1}"),
            "title": str(raw.get("title") or "Electrical plan"),
            "discipline": "Electrical",
            "revision": str(raw.get("revision") or ""),
            "scale": str(raw.get("scale") or ""),
            "plan": "",
            "sort_order": index,
            "takeoff_id": str(raw.get("takeoff_id") or payload.get("takeoff_id") or ""),
            "page_index": int(raw.get("page") or 0),
            "width_pt": width,
            "height_pt": height,
            "unreadable_reason": str(raw.get("unreadable") or ""),
            "ai_reading": raw.get("ai_reading"),
        })

    fallback = sheets[0]["key"] if sheets else None
    items: list[dict] = []

    for raw in payload.get("items") or []:
        key = str(raw.get("sheet_id") or fallback or "")
        if key not in dims:
            raise DomainError(
                "invalid_takeoff",
                f"An item references sheet {key!r}, which is not in the processed set.",
                status=422,
            )
        width, height = dims[key]
        name = str(raw.get("name") or "Unclassified item")
        system = str(raw.get("system") or "Unknown")
        warning = raw.get("warning")
        items.append({
            "sheet_key": key,
            "symbol": str(raw.get("symbol") or "") or infer_symbol(name, system),
            "name": name,
            "description": str(raw.get("description") or ""),
            "system": system,
            "category": str(raw.get("category") or ""),
            "quantity": raw.get("quantity") or 0,
            "unit": str(raw.get("unit") or "ea"),
            "status": str(raw.get("status") or "ready"),
            "x": normalize_point(raw.get("x"), width, SHEET_SPACE_W),
            "y": normalize_point(raw.get("y"), height, SHEET_SPACE_W),
            "placements": [
                [normalize_point(p[0], width, SHEET_SPACE_W), normalize_point(p[1], height, SHEET_SPACE_W)]
                for p in (raw.get("placements") or [])
                if isinstance(p, (list, tuple)) and len(p) >= 2
            ],
            "material_cost": raw.get("material_cost") or 0,
            "labor_hours": raw.get("labor_hours") or 0,
            "labor_cost": raw.get("labor_cost") or 0,
            "total_cost": raw.get("total_cost") or 0,
            "ai_confirmed": bool(raw.get("ai_confirmed")),
            "warning": validate_warning(warning) if warning else None,
        })

    return MappedTakeoff(sheets=sheets, items=items)
