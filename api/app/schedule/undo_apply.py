"""Compensating writes for the schedule's action kinds. Called from
takeoff.undo_apply.apply() -- one branch per kind there, the work here,
so the takeoff module stays a dispatcher.

Same identity-map rule as that module: a PhaseLine or PhaseStagePlan
cascade-deleted with its phase is never told to the ORM, so whether a
row exists is always a real query (`_exists`), never `Session.get()`."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.takeoff.models import Action, Item, Phase, PhaseLine, PhaseStagePlan, Sheet
from app.takeoff.undo_apply import _ITEM_GONE_MESSAGE


def _uuid(v):
    return uuid.UUID(v) if v else None


def _date(v):
    return date.fromisoformat(v) if v else None


def _decimal(v):
    return Decimal(v) if v is not None else None


def _exists(db: DbSession, model: type, pk: uuid.UUID) -> bool:
    return db.execute(select(model.id).where(model.id == pk)).scalar_one_or_none() is not None


def _get_or_expunge(db: DbSession, model: type, pk: uuid.UUID):
    """The live row, or None with any stale identity-mapped instance for
    that id expunged so a fresh `db.add()` at the same identity is clean."""
    if _exists(db, model, pk):
        return db.get(model, pk)
    stale = db.get(model, pk)
    if stale is not None:
        db.expunge(stale)
    return None


def _restore_phase(db: DbSession, snap: dict, lines: list[dict], plans: list[dict]) -> Phase:
    phase = _get_or_expunge(db, Phase, _uuid(snap["id"]))
    if phase is None:
        phase = Phase(id=_uuid(snap["id"]), project_id=_uuid(snap["project_id"]))
        db.add(phase)
    phase.name, phase.sort_order, phase.notes = snap["name"], snap["sort_order"], snap.get("notes") or ""
    phase.start_date, phase.required_finish_date = _date(snap.get("start_date")), _date(snap.get("required_finish_date"))
    db.flush()
    for l in lines:
        if _get_or_expunge(db, PhaseLine, _uuid(l["id"])) is None:
            db.add(PhaseLine(id=_uuid(l["id"]), phase_id=phase.id, kind=l["kind"], label=l["label"],
                             percent_of_direct_hours=Decimal(l["percent_of_direct_hours"]),
                             hours_override=_decimal(l.get("hours_override")), sort_order=l["sort_order"],
                             updated_by_user_id=_uuid(l.get("updated_by_user_id"))))
    for p in plans:
        if _get_or_expunge(db, PhaseStagePlan, _uuid(p["id"])) is None:
            row = PhaseStagePlan(id=_uuid(p["id"]), phase_id=phase.id, stage=p["stage"])
            for k in ("foreman", "journeyman", "apprentice", "duration_days"):
                setattr(row, k, p.get(k))
            row.productive_hours_per_day = _decimal(p.get("productive_hours_per_day"))
            row.hours_override = _decimal(p.get("hours_override"))
            row.start_date = _date(p.get("start_date"))
            row.updated_by_user_id = _uuid(p.get("updated_by_user_id"))
            db.add(row)
    db.flush()
    return phase


def _delete_phase_if_present(db: DbSession, phase_id: uuid.UUID) -> None:
    phase = _get_or_expunge(db, Phase, phase_id)
    if phase is not None:
        db.delete(phase)
        db.flush()


def _rename_first(db: DbSession, state: dict) -> None:
    """A proposal may rename the implicit first phase rather than adding
    beside it (propose.py), so replaying one has to carry that name back
    and forth -- the phase itself is never created or deleted by it, so
    nothing else in the branch would."""
    name = state.get("first_name")
    order = state.get("order") or []
    if not name or not order:
        return
    phase = db.get(Phase, _uuid(order[0]))
    if phase is not None:
        phase.name = name
        db.flush()


def _apply_order(db: DbSession, order: list[str]) -> None:
    for i, pid in enumerate(order):
        phase = db.get(Phase, _uuid(pid))
        if phase is not None:
            phase.sort_order = i
    db.flush()


def _apply_refs(db: DbSession, sheets: dict, items: dict) -> None:
    for sid, pid in (sheets or {}).items():
        sheet = db.get(Sheet, _uuid(sid))
        if sheet is not None:
            sheet.phase_id = _uuid(pid)
    for iid, pid in (items or {}).items():
        item = db.get(Item, _uuid(iid))
        if item is not None:
            item.phase_id = _uuid(pid)
    db.flush()


def _set_item_phase(db: DbSession, item_id: uuid.UUID, phase_id: str | None) -> None:
    """One item's override, for `item_phase_set` -- the same 409 the
    other item-scoped kinds raise when the item was deleted since."""
    item = db.execute(
        select(Item).where(Item.id == item_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if item is None:
        raise DomainError("item_no_longer_exists", _ITEM_GONE_MESSAGE, status=409)
    item.phase_id = _uuid(phase_id)
    db.flush()


def apply(db: DbSession, action: Action, direction: str) -> None:
    state = action.before if direction == "before" else action.after
    kind = action.kind
    if kind == "phase_create":
        # The order is restored in both directions: creating in the
        # middle shifted the later phases, so undo and redo both have
        # to put every phase back on the sort_order it had.
        if direction == "before":
            _delete_phase_if_present(db, _uuid(action.after["phase"]["id"]))
        else:
            _restore_phase(db, action.after["phase"], action.after.get("lines", []), [])
        _apply_order(db, state.get("order", []))
    elif kind == "phase_edit":
        _restore_phase(db, state["phase"], [], [])
    elif kind == "phase_reorder":
        _apply_order(db, state["order"])
    elif kind == "phase_delete":
        if direction == "before":
            _restore_phase(db, action.before["phase"], action.before["lines"], action.before["plans"])
            _apply_order(db, action.before["order"])
            _apply_refs(db, action.before["sheets"], action.before["items"])
        else:
            _apply_refs(db, action.after["sheets"], action.after["items"])
            _delete_phase_if_present(db, _uuid(action.before["phase"]["id"]))
            _apply_order(db, action.after["order"])
    elif kind == "sheet_phase_set":
        _apply_refs(db, state["sheets"], {})
    elif kind == "item_phase_set":
        _set_item_phase(db, action.item_id, state["phase_id"])
    elif kind == "phase_propose_apply":
        if direction == "before":
            _apply_refs(db, action.before["sheets"], {})
            for snap in action.after["phases"]:
                _delete_phase_if_present(db, _uuid(snap["id"]))
            _apply_order(db, action.before["order"])
            _rename_first(db, action.before)
        else:
            for snap in action.after["phases"]:
                _restore_phase(db, snap, snap.get("lines", []), [])
            _apply_order(db, action.after["order"])
            _apply_refs(db, action.after["sheets"], {})
            _rename_first(db, action.after)
    else:  # phase_line_edit, stage_plan_edit, lead_time_edit -- Task 6
        from app.schedule import overrides
        overrides.apply_undo(db, action, direction)
