# api/app/assistant/context.py
"""What each screen puts in view (docs/specs/conversation-panel.md, "What
each screen puts in view").

Reads through the API's existing read paths -- snapshot.build,
approved_totals, build_processing, list_statements, list_documents,
list_notes -- so the panel sees exactly the records the screens see, in
the same shapes. Nothing here writes. Nothing here imports app.engine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.assistant.schemas import ScreenIn
from app.documents.service import list_documents
from app.identity.models import User
from app.jobs.status import build_processing
from app.scope.service import list_statements
from app.takeoff import snapshot
from app.takeoff.models import Classification, Document, Project, Sheet
from app.takeoff.notes import list_notes
from app.takeoff.totals import approved_totals

ITEM_CAP = 400
TEXT_CAP = 12_000

STATUS_LABELS = {
    "ready": "Ready to review",
    "attention": "Needs attention",
    "missing": "Missing information",
    "approved": "Estimator approved",
}

# Which sections each screen gets on top of the base three (project,
# scope statements, notes). Adding a screen is one row here and one in
# screenContext.js.
_SECTIONS = {
    "overview": ("counts", "documents"),
    "documents": ("documents",),
    "confirm": ("documents", "sheets", "document_texts"),
    "processing": ("processing",),
    "takeoff": ("sheets", "items", "totals", "sheet_text"),
    "spreadsheet": ("sheets", "items", "totals", "sheet_text"),
    "notes": ("sheets",),
    "labor": ("pricing", "items", "totals"),
    "pricing": ("pricing", "items", "totals"),
    "export": ("totals", "blocking"),
    "settings": (),
}

# Documents whose extracted text is the kind an estimator asks about --
# scope letters and specifications. A drawing set's text is reached
# through its sheets (schedule_text, legend), never dumped whole.
_TEXT_DOC_TYPES = ("Specifications", "Scope", "Addendum", "Other")


@dataclass
class ContextBundle:
    screen: ScreenIn
    project: dict
    scope: list[dict]
    notes: list[dict]
    counts: dict | None = None
    documents: list[dict] | None = None
    document_texts: list[dict] | None = None
    sheets: list[dict] | None = None
    items: list[dict] | None = None
    other_sheets: list[dict] | None = None
    item_overflow: dict | None = None
    totals: dict | None = None
    processing: dict | None = None
    pricing: dict | None = None
    sheet_text: dict | None = None
    blocking: list[dict] | None = None
    allowances: list[dict] | None = None
    view_note: str | None = None
    with_costs: bool = False


def clip_text(text: str, cap: int = TEXT_CAP) -> tuple[str, int]:
    """Cut at the last paragraph break under `cap`, else the last line
    break, else `cap` -- never silently mid-sentence. Returns the kept
    text and how many characters were left out."""
    text = text or ""
    if len(text) <= cap:
        return text, 0
    head = text[:cap]
    cut = head.rfind("\n\n")
    if cut <= 0:
        cut = head.rfind("\n")
    if cut <= 0:
        cut = cap
    kept = head[:cut].rstrip()
    return kept, len(text) - len(kept)


def _project(project: Project) -> dict:
    return {
        "name": project.name, "number": project.number, "customer": project.customer,
        "location": project.location,
        "bid_due_date": project.bid_due_date.isoformat() if project.bid_due_date else None,
        "stage": project.stage, "revision_set_label": project.revision_set_label,
        "pricing_source": project.pricing_source, "pricing_note": project.pricing_note,
    }


def _scope(db: DbSession, project: Project) -> list[dict]:
    filenames = {d.id: d.filename for d in db.scalars(select(Document).where(Document.project_id == project.id))}
    return [{
        "kind": s.kind, "status": s.status, "text": s.edited_text or s.text, "quote": s.quote,
        "filename": filenames.get(s.document_id, ""), "page": s.page_index + 1,
    } for s in list_statements(db, project)]


def _notes(db: DbSession, project: Project) -> list[dict]:
    return [{
        "title": n.title, "body": n.body, "category": n.category, "status": n.status, "usage": n.usage,
        "scope": n.scope, "source_ref": n.source_ref, "rfi_needed": n.rfi_needed,
        "applied": n.applied_at is not None,
    } for n in list_notes(db, project.id)]


def _documents(db: DbSession, project: Project) -> list[dict]:
    return [{
        "filename": d.filename, "doc_type": d.doc_type, "status": d.status, "error": d.error,
        "page_count": d.page_count,
    } for d in list_documents(db, project)]


def _document_texts(db: DbSession, project: Project) -> list[dict]:
    out = []
    for d in list_documents(db, project):
        if d.doc_type in _TEXT_DOC_TYPES and d.context_text:
            text, omitted = clip_text(d.context_text)
            out.append({"filename": d.filename, "text": text, "omitted": omitted})
    return out


def _sheet(s) -> dict:
    return {
        "id": str(s.id), "number": s.number, "title": s.title, "discipline": s.discipline,
        "revision": s.revision, "scale": s.scale, "scale_options": s.scale_options, "kind": s.kind,
        "superseded": s.superseded, "unreadable_reason": s.unreadable_reason,
    }


def _item(i, sheet_numbers: dict, *, selected: bool, with_costs: bool) -> dict:
    row = {
        "id": str(i.id), "name": i.name, "description": i.description, "system": i.system,
        "category": i.category, "quantity": str(i.quantity), "unit": i.unit,
        "status": STATUS_LABELS.get(i.status, i.status), "rejected": i.rejected,
        "sheet": sheet_numbers.get(str(i.sheet_id), ""), "notes": i.notes, "selected": selected,
        "warnings": [{"title": w.title, "found": w.found, "why": w.why, "fix": w.fix, "where": w.where}
                     for w in i.warnings],
    }
    if with_costs:
        row["material_cost"] = str(i.material_cost)
        row["labor_hours"] = str(i.labor_hours)
        row["labor_cost"] = str(i.labor_cost)
        row["total_cost"] = str(i.total_cost)
    return row


def _totals(db: DbSession, project: Project) -> dict:
    t = approved_totals(db, project.id)
    return {
        "approved_by_system": {k: str(v) for k, v in sorted(t.by_system.items())},
        "approved_units": str(t.approved_units),
        "counts": {"approved": t.approved_count, "remaining": t.remaining_count,
                   "attention": t.attention_count, "missing": t.missing_count},
    }


def _pricing(db: DbSession, project: Project) -> dict:
    latest = db.scalars(select(Classification).where(Classification.project_id == project.id)
                        .order_by(Classification.created_at.desc())).first()
    return {
        "pricing_source": project.pricing_source, "pricing_note": project.pricing_note,
        "labor_rate": str(latest.labor_rate) if latest else None,
        "material_factor": str(latest.material_factor) if latest else None,
        "location_note": latest.location_note if latest else "",
    }


def _sheet_text(db: DbSession, sheet_id: uuid.UUID | None, project: Project) -> dict | None:
    if sheet_id is None:
        return None
    s = db.get(Sheet, sheet_id)
    if s is None or s.project_id != project.id:
        return None
    schedule, omitted = clip_text(s.schedule_text)
    return {"number": s.number, "schedule_text": schedule, "omitted": omitted, "legend": s.legend or []}


def build(db: DbSession, actor: User, project: Project, screen: ScreenIn) -> ContextBundle:
    bundle = ContextBundle(screen=screen, project=_project(project), scope=_scope(db, project),
                           notes=_notes(db, project))
    sections = _SECTIONS[screen.name]
    bundle.with_costs = "pricing" in sections

    if "documents" in sections:
        bundle.documents = _documents(db, project)
    if "document_texts" in sections:
        bundle.document_texts = _document_texts(db, project)
    if "processing" in sections:
        bundle.processing = build_processing(db, project)
    if "pricing" in sections:
        bundle.pricing = _pricing(db, project)
    if "totals" in sections or "counts" in sections:
        bundle.totals = _totals(db, project)
        if "counts" in sections:
            bundle.counts = bundle.totals["counts"]

    needs_snapshot = any(s in sections for s in ("sheets", "items", "blocking"))
    if needs_snapshot:
        snap = snapshot.build(db, actor, project.id, version="")
        sheet_numbers = {str(s.id): s.number for s in snap.sheets}
        if "sheets" in sections:
            bundle.sheets = [_sheet(s) for s in snap.sheets]
        if "items" in sections:
            _items(bundle, snap, sheet_numbers)
        if "blocking" in sections:
            live = [i for i in snap.items if not i.rejected]
            bundle.blocking = [_item(i, sheet_numbers, selected=False, with_costs=False)
                               for i in live if i.status == "missing"]
            bundle.allowances = [_item(i, sheet_numbers, selected=False, with_costs=False)
                                 for i in live if i.status == "attention"]
    if "sheet_text" in sections:
        bundle.sheet_text = _sheet_text(db, screen.sheet_id, project)
    return bundle


def _items(bundle: ContextBundle, snap, sheet_numbers: dict) -> None:
    screen = bundle.screen
    live = [i for i in snap.items if not i.rejected]
    if screen.sheet_id is not None:
        on_sheet = [i for i in live if i.sheet_id == screen.sheet_id]
        elsewhere = [i for i in live if i.sheet_id != screen.sheet_id]
        bundle.other_sheets = _per_sheet_counts(elsewhere, sheet_numbers)
        live = on_sheet
    if screen.item_id is not None:
        live.sort(key=lambda i: 0 if i.id == screen.item_id else 1)
    shown, overflow = live[:ITEM_CAP], live[ITEM_CAP:]
    bundle.items = [_item(i, sheet_numbers, selected=(i.id == screen.item_id), with_costs=bundle.with_costs)
                    for i in shown]
    if overflow:
        per_sheet = {row["number"]: row["counts"] for row in _per_sheet_counts(overflow, sheet_numbers)}
        bundle.item_overflow = {"omitted": len(overflow), "per_sheet": per_sheet}
    bundle.view_note = _view_note(screen, [i for i in snap.items if not i.rejected])


def _per_sheet_counts(items, sheet_numbers: dict) -> list[dict]:
    by_sheet: dict[str, dict[str, int]] = {}
    for i in items:
        number = sheet_numbers.get(str(i.sheet_id), "")
        counts = by_sheet.setdefault(number, {})
        counts[i.status] = counts.get(i.status, 0) + 1
    return [{"number": n, "counts": c} for n, c in sorted(by_sheet.items())]


def _view_note(screen: ScreenIn, live) -> str | None:
    if screen.view is None:
        return None
    parts = []
    if screen.view.filter:
        matching = sum(1 for i in live if i.status == screen.view.filter)
        parts.append(f"The estimator has the {screen.name} filtered to {STATUS_LABELS[screen.view.filter]}; "
                     f"{matching} of {len(live)} items match.")
    if screen.view.search:
        parts.append(f"The estimator has searched for '{screen.view.search}'.")
    return " ".join(parts) or None
