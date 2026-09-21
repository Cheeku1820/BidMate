"""The project plan: derived lines with the decisions a person made on
them. build_plan is the one place the plan is assembled; every write
goes through actions.commit() and none is undoable (docs/specs/
project-plan-screen.md, "Audited, not undoable")."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.plan import detect
from app.plan.models import PlanDecision, PlanPhase
from app.plan.schemas import PlaceOut, PlanLineOut, PlanOut, QuestionOut
from app.scope import service as scope_service
from app.scope.router import _out as scope_out
from app.takeoff import actions
from app.takeoff.models import Document, Note, Project, Sheet
from app.takeoff.router import not_found

_MAX_TEXT = 500
_MAX_PHASE = 100


def _inputs(db: DbSession, project: Project) -> tuple[list[detect.DocIn], list[detect.SheetIn], list[Document]]:
    docs = list(db.scalars(select(Document).where(Document.project_id == project.id).order_by(Document.created_at)))
    doc_in = [detect.DocIn(id=str(d.id), filename=d.filename, doc_type=d.doc_type, status=d.status,
                           context_text=d.context_text or "", page_count=d.page_count) for d in docs]
    sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id, Sheet.superseded_at.is_(None))
                             .order_by(Sheet.sort_order, Sheet.page_index)))
    sheet_in = [detect.SheetIn(id=str(s.id), document_id=s.takeoff_id, number=s.number, title=s.title, kind=s.kind,
                               page_index=s.page_index, scale=s.scale or "", scale_options=tuple(s.scale_options or ()),
                               unreadable_reason=s.unreadable_reason or "", schedule_text=s.schedule_text or "")
                for s in sheets]
    return doc_in, sheet_in, docs


def _decisions(db: DbSession, project: Project) -> dict[str, PlanDecision]:
    return {d.entry_key: d for d in db.scalars(select(PlanDecision).where(PlanDecision.project_id == project.id))}


def _uuid_or_none(value: str) -> uuid.UUID | None:
    """A sheet's takeoff_id is the document id as text; a sheet created
    outside the read job (a fixture, an older row) may carry none."""
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


def _line_out(line: detect.Line, decision: PlanDecision | None) -> PlanLineOut:
    status = decision.status if decision and decision.status in ("found", "confirmed", "dismissed") else "found"
    edited = decision.edited_text if decision else None
    return PlanLineOut(
        key=line.key, kind=line.kind, text=edited or line.text, found_text=line.text, edited_text=edited, status=status,
        document_id=_uuid_or_none(line.place.document_id), document_filename=line.place.document_filename,
        page=line.place.page, quote=line.place.quote, division=line.division, sheet_number=line.sheet_number,
        places=[PlaceOut(document_id=_uuid_or_none(p.document_id), document_filename=p.document_filename, page=p.page, quote=p.quote)
                for p in line.places],
    )


def _added_phase_out(phase: PlanPhase, decision: PlanDecision | None) -> PlanLineOut:
    status = decision.status if decision and decision.status in ("found", "confirmed", "dismissed") else "found"
    edited = decision.edited_text if decision else None
    return PlanLineOut(key=f"phase:added:{phase.id}", kind="phase", text=edited or phase.name, found_text=phase.name,
                       edited_text=edited, status=status, document_id=None, document_filename=None, page=None, quote=None,
                       added=True, phase_id=phase.id)


def _question_out(q: detect.Question, decision: PlanDecision | None, filenames: dict[str, str]) -> QuestionOut:
    status = "found"
    note_id = None
    if decision:
        if decision.status == "answered" and decision.note_id is not None:
            status, note_id = "answered", decision.note_id
        elif decision.status == "dismissed":
            status = "dismissed"
    return QuestionOut(key=q.key, status=status, title=q.title, found=q.found, why=q.why, fix=q.fix, where=q.where,
                       document_id=_uuid_or_none(q.document_id) if q.document_id else None,
                       document_filename=filenames.get(q.document_id) if q.document_id else None, note_id=note_id)


def derive(db: DbSession, project: Project):
    """Everything derived, before decisions are applied. Shared by
    build_plan and the write paths, which need to know whether a key
    still exists."""
    doc_in, sheet_in, docs = _inputs(db, project)
    scope = scope_service.list_statements(db, project)
    specs = detect.spec_sections(doc_in)
    scheds = detect.schedules(sheet_in, doc_in)
    phase_lines = detect.phases(sheet_in, doc_in)
    added = list(db.scalars(select(PlanPhase).where(PlanPhase.project_id == project.id).order_by(PlanPhase.created_at)))
    qs = detect.questions(sheet_in, doc_in, scope_count=len(scope), phase_count=len(phase_lines) + len(added),
                          schedule_count=len(scheds))
    return docs, scope, specs, scheds, phase_lines, added, qs


def build_plan(db: DbSession, project: Project) -> PlanOut:
    docs, scope, specs, scheds, phase_lines, added, qs = derive(db, project)
    decisions = _decisions(db, project)
    filenames = {str(d.id): d.filename for d in docs}

    drawings = [d for d in docs if d.doc_type == "Drawings"]
    reading = any(d.status in ("uploaded", "processing") for d in drawings)
    processed = [d for d in docs if d.status == "processed"]
    read_at = max((d.created_at for d in processed), default=None)

    out = PlanOut(
        read_at=read_at, reading=reading, has_drawings=bool(drawings), undecided=0,
        scope=[scope_out(s, filenames.get(str(s.document_id), "")) for s in scope],
        specs=[_line_out(l, decisions.get(l.key)) for l in specs],
        schedules=[_line_out(l, decisions.get(l.key)) for l in scheds],
        phases=[_line_out(l, decisions.get(l.key)) for l in phase_lines]
               + [_added_phase_out(p, decisions.get(f"phase:added:{p.id}")) for p in added],
        questions=[_question_out(q, decisions.get(q.key), filenames) for q in qs],
    )
    out.undecided = (sum(1 for s in out.scope if s.status == "found")
                     + sum(1 for l in out.specs + out.schedules + out.phases if l.status == "found")
                     + sum(1 for q in out.questions if q.status == "found"))

    # The stage moves forward once, here, because this is the one place
    # that knows the project has reached the plan. Never backward: the
    # WHERE clause is the only source of truth on the current stage --
    # not `project.stage` on the in-session object, which can be stale
    # if the worker (a different process, no lock) advanced the row to
    # "processing" between this object's load and this write.
    if drawings and not reading and any(d.status == "processed" for d in drawings):
        db.execute(
            update(Project)
            .where(Project.id == project.id, Project.stage.in_(("setup", "documents")))
            .values(stage="plan")
        )
        db.flush()
        db.expire(project, ["stage"])
    return out


def _find_line(db: DbSession, project: Project, key: str):
    """The derived line or question behind a key, or not_found(). A
    scope statement id is not a key: scope has its own write path."""
    docs, _scope, specs, scheds, phase_lines, added, qs = derive(db, project)
    for line in specs + scheds + phase_lines:
        if line.key == key:
            return "line", line, docs
    for phase in added:
        if f"phase:added:{phase.id}" == key:
            return "added", phase, docs
    for q in qs:
        if q.key == key:
            return "question", q, docs
    raise not_found()


def _decision_row(db: DbSession, project: Project, key: str) -> PlanDecision:
    row = db.scalar(select(PlanDecision).where(PlanDecision.project_id == project.id, PlanDecision.entry_key == key))
    if row is None:
        row = PlanDecision(project_id=project.id, entry_key=key, status="found")
        db.add(row)
    return row


def _snapshot(row: PlanDecision) -> dict:
    return {"status": row.status, "edited_text": row.edited_text, "note_id": str(row.note_id) if row.note_id else None}


def decide(db: DbSession, *, actor: User, project: Project, key: str, status: str | None = None,
           edited_text: str | None = None):
    if (status is None) == (edited_text is None):
        raise DomainError("invalid_plan_decision", "Send either a status or a corrected line, not both and not neither.", status=422)
    what, target, docs = _find_line(db, project, key)
    if what == "question" and edited_text is not None:
        raise DomainError("invalid_plan_decision", "A question can be answered or dismissed, not reworded.", status=422)
    if status is not None and status not in ("found", "confirmed", "dismissed"):
        raise DomainError("invalid_plan_status", "Status must be one of found, confirmed, dismissed.", status=422)

    row = _decision_row(db, project, key)
    before = _snapshot(row)
    if what == "question":
        shown = target.title
    else:
        found_text = target.name if what == "added" else target.text
        shown = row.edited_text or found_text

    if status is not None:
        row.status = status
        if what == "question":
            row.note_id = None
        label = {"confirmed": f"Confirmed: {shown}", "dismissed": f"Dismissed: {shown}", "found": f"Reopened: {shown}"}[status]
    else:
        cleaned = edited_text.strip()
        if not cleaned or len(cleaned) > _MAX_TEXT:
            raise DomainError("invalid_plan_text", f"The corrected line can't be empty and must be {_MAX_TEXT} characters or fewer.", status=422)
        row.edited_text = cleaned
        label = f"Changed: {cleaned}"

    row.decided_by = actor.id
    row.decided_at = datetime.now(timezone.utc)
    db.flush()
    actions.commit(db, actor=actor, project_id=project.id, kind="plan_decide", label=label, before=before, after=_snapshot(row))

    filenames = {str(d.id): d.filename for d in docs}
    if what == "question":
        return _question_out(target, row, filenames)
    if what == "added":
        return _added_phase_out(target, row)
    return _line_out(target, row)
