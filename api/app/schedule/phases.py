"""Phase records and their mutations (phases-and-timeline.md §3.1).
A phase groups sheets and items that already exist; nothing here reads
or writes a quantity or a status. Every mutation records one action
through actions.commit(); db.commit() is the router's."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.schedule.defaults import load_company
from app.takeoff import actions
from app.takeoff.actions import encode_snapshot
from app.takeoff.models import Item, Phase, PhaseLine, PhaseStagePlan, Project, Sheet

PHASE_FIELDS = ("name", "sort_order", "start_date", "required_finish_date", "notes")
EDITABLE = ("name", "start_date", "required_finish_date", "notes")


def phases_for(db: DbSession, project_id: uuid.UUID) -> list[Phase]:
    return list(db.scalars(select(Phase).where(Phase.project_id == project_id).order_by(Phase.sort_order)))


def _snapshot_phase(phase: Phase) -> dict:
    return encode_snapshot({f: getattr(phase, f) for f in PHASE_FIELDS} | {"id": phase.id, "project_id": phase.project_id})


def _lines_snapshot(db: DbSession, phase_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(select(PhaseLine).where(PhaseLine.phase_id == phase_id).order_by(PhaseLine.sort_order))
    return [encode_snapshot({"id": r.id, "kind": r.kind, "label": r.label, "percent_of_direct_hours": r.percent_of_direct_hours,
                             "hours_override": r.hours_override, "sort_order": r.sort_order}) for r in rows]


def _plans_snapshot(db: DbSession, phase_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(select(PhaseStagePlan).where(PhaseStagePlan.phase_id == phase_id))
    return [encode_snapshot({c.name: getattr(r, c.name) for c in PhaseStagePlan.__table__.columns}) for r in rows]


def _add_template_lines(db: DbSession, org_id: uuid.UUID, phase: Phase) -> None:
    for t in load_company(db, org_id).templates:
        db.add(PhaseLine(phase_id=phase.id, label=t.label, percent_of_direct_hours=t.percent_of_direct_hours, sort_order=t.sort_order))


def first_phase(db: DbSession, project: Project, *, create: bool = False) -> Phase | None:
    """The implicit first phase. Created on demand -- never by a
    migration, never as a side effect of a read that did not ask."""
    existing = phases_for(db, project.id)
    if existing:
        return existing[0]
    if not create:
        return None
    phase = Phase(project_id=project.id, name="Phase 1", sort_order=0)
    db.add(phase)
    db.flush()
    _add_template_lines(db, project.org_id, phase)
    db.flush()
    return phase


def phase_of(item: Item, sheet: Sheet, first: Phase | None) -> uuid.UUID | None:
    """The one resolution: item override, else the sheet's, else the
    first phase. Callers never re-derive this."""
    if item.phase_id is not None:
        return item.phase_id
    if sheet.phase_id is not None:
        return sheet.phase_id
    return first.id if first else None


def create_phase(db: DbSession, *, actor: User, project: Project, name: str, after_phase_id: uuid.UUID | None) -> Phase:
    ordered = phases_for(db, project.id)
    if not ordered:
        first_phase(db, project, create=True)
        ordered = phases_for(db, project.id)
    position = len(ordered)
    if after_phase_id is not None:
        idx = next((i for i, p in enumerate(ordered) if p.id == after_phase_id), None)
        if idx is None:
            raise DomainError("phase_not_found", "That phase isn't on this project.")
        position = idx + 1
    for p in ordered[position:]:
        p.sort_order += 1
    phase = Phase(project_id=project.id, name=name.strip() or f"Phase {position + 1}", sort_order=position)
    db.add(phase)
    db.flush()
    _add_template_lines(db, project.org_id, phase)
    db.flush()
    actions.commit(db, actor=actor, project_id=project.id, kind="phase_create", label=f"Added {phase.name}",
                   before={}, after={"phase": _snapshot_phase(phase), "lines": _lines_snapshot(db, phase.id)})
    return phase


def edit_phase(db: DbSession, *, actor: User, phase: Phase, changes: dict) -> Phase:
    changes = {k: v for k, v in changes.items() if k in EDITABLE}
    if not changes:
        raise DomainError("no_changes_to_apply", "This update has no changes. Include at least one field, such as the name or a date.")
    before = _snapshot_phase(phase)
    for k, v in changes.items():
        if k == "name":
            v = (v or "").strip()
        elif k == "notes":
            v = v if v is not None else ""
        setattr(phase, k, v)
    db.flush()
    label = f"Renamed {before['name']} to {phase.name}" if "name" in changes else f"Changed dates on {phase.name}"
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="phase_edit", label=label,
                   before={"phase": before}, after={"phase": _snapshot_phase(phase)})
    return phase


rename_phase = edit_phase


def reorder_phase(db: DbSession, *, actor: User, phase: Phase, sort_order: int) -> Phase:
    ordered = phases_for(db, phase.project_id)
    before = {"order": [str(p.id) for p in ordered]}
    ordered.remove(phase)
    ordered.insert(max(0, min(sort_order, len(ordered))), phase)
    for i, p in enumerate(ordered):
        p.sort_order = i
    db.flush()
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="phase_reorder", label=f"Moved {phase.name}",
                   before=before, after={"order": [str(p.id) for p in ordered]})
    return phase


def delete_phase(db: DbSession, *, actor: User, phase: Phase) -> None:
    ordered = phases_for(db, phase.project_id)
    if len(ordered) <= 1:
        raise DomainError("last_phase", "A project keeps at least one phase. Rename this one instead.", status=409)
    project_id, phase_id, name = phase.project_id, phase.id, phase.name
    idx = ordered.index(phase)
    target = ordered[idx - 1] if idx > 0 else ordered[1]
    sheets = list(db.scalars(select(Sheet).where(Sheet.phase_id == phase_id)))
    items = list(db.scalars(select(Item).where(Item.phase_id == phase_id)))
    before = {
        "phase": _snapshot_phase(phase), "lines": _lines_snapshot(db, phase_id), "plans": _plans_snapshot(db, phase_id),
        "sheets": {str(s.id): str(phase_id) for s in sheets}, "items": {str(i.id): str(phase_id) for i in items},
        "order": [str(p.id) for p in ordered],
    }
    # A sheet on the removed phase moves to its neighbour, named
    # explicitly. An item on it was an override of its sheet's phase;
    # the override clears, so the item follows its sheet again rather
    # than being pinned to a phase nobody chose for it.
    for s in sheets:
        s.phase_id = target.id
    for i in items:
        i.phase_id = None
    db.delete(phase)
    db.flush()
    remaining = phases_for(db, project_id)
    for n, p in enumerate(remaining):
        p.sort_order = n
    db.flush()
    after = {"sheets": {str(s.id): str(target.id) for s in sheets},
             "items": {str(i.id): None for i in items},
             "order": [str(p.id) for p in remaining]}
    actions.commit(db, actor=actor, project_id=project_id, kind="phase_delete",
                   label=f"Removed {name} — its sheets moved to {target.name}", before=before, after=after)


def assign_sheets(db: DbSession, *, actor: User, phase: Phase, sheet_ids: list[uuid.UUID]) -> Phase:
    """`sheet_ids` is the full set the phase should own: sheets not in
    it that are currently on this phase move back to the first phase."""
    wanted = set(sheet_ids)
    project_sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == phase.project_id)))
    unknown = wanted - {s.id for s in project_sheets}
    if unknown:
        raise DomainError("sheet_not_found", "One of those sheets isn't on this project.")
    before, after = {}, {}
    for s in project_sheets:
        current = s.phase_id
        if s.id in wanted and current != phase.id:
            before[str(s.id)] = str(current) if current else None
            s.phase_id = phase.id
            after[str(s.id)] = str(phase.id)
        elif s.id not in wanted and current == phase.id:
            before[str(s.id)] = str(current)
            s.phase_id = None
            after[str(s.id)] = None
    if not before:
        raise DomainError("no_changes_to_apply", "Those sheets are already where you put them.")
    db.flush()
    n = len(before)
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="sheet_phase_set",
                   label=f"Moved {n} sheet{'s' if n != 1 else ''} on {phase.name}",
                   before={"sheets": before}, after={"sheets": after})
    return phase


def set_item_phase(db: DbSession, *, actor: User, item: Item, phase_id: uuid.UUID | None) -> Item:
    if phase_id is not None:
        phase = db.get(Phase, phase_id)
        if phase is None or phase.project_id != item.project_id:
            raise DomainError("phase_not_found", "That phase isn't on this project.")
        label = f"Moved {item.name} to {phase.name}"
    else:
        label = f"Returned {item.name} to its sheet's phase"
    before = {"phase_id": str(item.phase_id) if item.phase_id else None}
    item.phase_id = phase_id
    db.flush()
    actions.commit(db, actor=actor, project_id=item.project_id, kind="item_phase_set", label=label, item_id=item.id,
                   before=before, after={"phase_id": str(phase_id) if phase_id else None})
    return item
