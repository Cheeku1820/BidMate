"""ingest.py -- maps the takeoff engine's payload into domain rows.

This mapping used to live in the client (src/lib/store/seed-ingest.js).
It belongs on the server: it is domain logic, and ROADMAP invariant 7
keeps processing internals behind the API boundary. Pure functions, no
database access, so the mapping is testable without Postgres.

Coordinates arrive as PDF points and are normalized into the canvas's
fixed 1000x750 sheet space against EACH SHEET'S OWN dimensions -- a
sheet's markers land wrongly if scaled by another sheet's page size.

Each axis is normalized independently against its own extent: x against
the page's width_pt onto SHEET_SPACE_W (1000), y against the page's
height_pt onto SHEET_SPACE_H (750). This is a port of the client's
existing seed-ingest.js normalization, which markers are rendered
against today.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from app.errors import DomainError
from app.takeoff.models import WarningReason

SHEET_SPACE_W = 1000
SHEET_SPACE_H = 750

WARNING_FIELDS = ("title", "found", "why", "fix", "where")
VALID_REASONS = {r.value for r in WarningReason}

# Mirrors app/engine/documents.py's SHEET_ID pattern -- ingest.py stays
# engine-agnostic, working off the payload contract only, so this is a
# deliberate small duplication rather than a cross-module import.
SHEET_ID = re.compile(r"\bE\d{1,2}\.\d{1,2}\b")

# A model-written warning must never carry this product's own forbidden
# framing (CLAUDE.md: no model names, no confidence numbers, no "I
# think," no processing internals). Matched case-insensitively on word
# boundaries, so a real word like "detail" or "explain" is never a false
# positive.
BANNED_PHRASES = (
    re.compile(r"\bclaude\b", re.I),
    re.compile(r"\bgpt\b", re.I),
    re.compile(r"\bchatgpt\b", re.I),
    re.compile(r"\bgemini\b", re.I),
    re.compile(r"\bllm\b", re.I),
    re.compile(r"\bai\b", re.I),
    re.compile(r"\bconfidence\b", re.I),
    re.compile(r"\bi think\b", re.I),
    re.compile(r"\bi believe\b", re.I),
    re.compile(r"\d+\s*%"),
)


def is_warning_grounded(warning: dict, valid_sheet_numbers: set[str]) -> bool:
    """Layer 1 of the grounded-classification-warnings design: a cheap,
    deterministic check that a model-written warning didn't fabricate a
    sheet reference or slip past this product's language rules. Runs on
    every warning regardless of origin -- a deterministic-path warning
    always passes trivially, since its `where` is always the item's own
    real sheet number, sourced the same way this check verifies against."""
    reference_text = " ".join(warning.get(f, "") for f in ("found", "where"))
    referenced = set(SHEET_ID.findall(reference_text))
    if referenced - valid_sheet_numbers:
        return False
    all_text = " ".join(warning.get(f, "") for f in ("title", "found", "why", "fix", "where"))
    return not any(p.search(all_text) for p in BANNED_PHRASES)


def fallback_warning(tag: str, count, sheet_number: str) -> dict:
    """The same generic-but-honest shape estimate.py's deterministic path
    already uses (`_unconfirmed_type_warning`), reconstructed here rather
    than imported -- ingest.py works off the payload contract only and
    does not import from app.engine. This is what a groundedness failure
    falls back to."""
    tag = tag or "?"
    sheet_number = sheet_number or "the sheet"
    return {
        "reason": "legend",
        "title": "Item type needs confirmation",
        "found": f"Type {tag} appears {count} time(s) on {sheet_number}, but its description could not be matched to a schedule with confidence.",
        "why": "The exact item and its price can't be confirmed until the type is matched to the schedule.",
        "fix": "Confirm the item type against the schedule, then approve.",
        "where": f"{sheet_number} and the project schedules.",
    }


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


def normalize_ai_reading(raw) -> dict | None:
    """Normalize a sheet's model-produced reading at the boundary rather
    than storing whatever shape it arrived in.

    `ai_reading` is unvalidated JSON a language model produced -- the
    same principle `validate_warning` applies to warnings applies here:
    extracted/model-produced content is data, and its shape is not to be
    trusted. Unlike a warning, one odd reading must never fail the whole
    ingest, so malformed entries are dropped rather than raising: a
    non-object reading becomes None, a missing or non-string `summary`
    becomes "", and each device entry is kept only if it has both a
    non-empty string `name` and a numeric `count` -- anything else is
    dropped rather than defaulted, since a fabricated count is worse
    than a missing one.
    """
    if not isinstance(raw, dict):
        return None
    summary = raw.get("summary")
    devices = []
    for d in raw.get("devices") or []:
        if not isinstance(d, dict):
            continue
        name = d.get("name")
        count = d.get("count")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(count, (int, float)) or isinstance(count, bool):
            continue
        devices.append({"name": name.strip(), "count": count})
    return {
        "summary": summary.strip() if isinstance(summary, str) else "",
        "devices": devices,
    }


def _grounded_or_fallback(raw_warning, sheet_number: str, valid_sheet_numbers: set[str], tag: str, quantity) -> dict | None:
    """The single point map_payload calls once an item's own sheet number
    and the document's full valid-sheet set are both known: validate the
    warning's shape, then swap in the deterministic fallback if Layer 1's
    groundedness check fails, otherwise keep the model's own text as-is."""
    if not raw_warning:
        return None
    warning = validate_warning(raw_warning)
    if is_warning_grounded(warning, valid_sheet_numbers):
        return warning
    return fallback_warning(tag, quantity, sheet_number)


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
            "ai_reading": normalize_ai_reading(raw.get("ai_reading")),
        })

    valid_sheet_numbers = {s["number"] for s in sheets}
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
        placements = [
            [normalize_point(p[0], width, SHEET_SPACE_W), normalize_point(p[1], height, SHEET_SPACE_H)]
            for p in (raw.get("placements") or [])
            if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
        n_places = len(placements) or 1
        png_b64 = raw.get("evidence_png_b64")
        sheet_number = next((s["number"] for s in sheets if s["key"] == key), "")
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
            "y": normalize_point(raw.get("y"), height, SHEET_SPACE_H),
            "placements": placements,
            "material_cost": raw.get("material_cost") or 0,
            "labor_hours": raw.get("labor_hours") or 0,
            "labor_cost": raw.get("labor_cost") or 0,
            "total_cost": raw.get("total_cost") or 0,
            "ai_confirmed": bool(raw.get("ai_confirmed")),
            # Counting's cluster tag ("R", "F2") -- the merge key a re-run
            # uses to recognise an item it already produced, so an
            # estimator's approval survives reprocessing. Not every engine
            # row carries one, so a missing tag maps to "" rather than
            # None or a KeyError.
            "source_tag": str(raw.get("tag") or ""),
            "warning": _grounded_or_fallback(warning, sheet_number, valid_sheet_numbers, str(raw.get("tag") or ""), raw.get("quantity") or 0),
            "evidence": {
                "detail": f"Counted from the drawing at {n_places} location{'s' if n_places != 1 else ''}",
                "sheet": sheet_number,
                "has_image": bool(png_b64),
            },
            "evidence_png": base64.b64decode(png_b64) if png_b64 else None,
        })

    return MappedTakeoff(sheets=sheets, items=items)
