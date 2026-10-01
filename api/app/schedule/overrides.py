"""The estimator's overrides on a phase (phases-and-timeline.md §3.2,
§3.5, §3.7): sparse rows, every field independent, null = computed.
Same shape as ProjectLaborLine, same snapshot discipline."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.schedule.stages import STAGE_LABELS, STAGES
from app.takeoff import actions
from app.takeoff.actions import encode_snapshot
from app.takeoff.models import Action, Item, ItemLeadTime, Phase, PhaseLine, PhaseStagePlan

PLAN_FIELDS = ("foreman", "journeyman", "apprentice", "productive_hours_per_day", "hours_override", "start_date",
               "duration_days", "updated_by_user_id")
LEAD_FIELDS = ("flagged", "lead_weeks", "source", "source_label", "quoted_at", "needed_for_stage", "updated_by_user_id")


def _snap(row, fields) -> dict | None:
    return None if row is None else encode_snapshot({f: getattr(row, f) for f in fields})


def set_line_hours(db: DbSession, *, actor: User, line: PhaseLine, hours: Decimal | None) -> PhaseLine:
    phase = db.get(Phase, line.phase_id)
    before = encode_snapshot({"hours_override": line.hours_override, "updated_by_user_id": line.updated_by_user_id})
    line.hours_override = hours
    line.updated_by_user_id = actor.id
    db.flush()
    db.refresh(line)
    label = f"Set {line.label} to {line.hours_override} hours on {phase.name}" if hours is not None else f"Reset {line.label} on {phase.name} to computed"
    after = encode_snapshot({"hours_override": line.hours_override, "updated_by_user_id": line.updated_by_user_id})
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="phase_line_edit", label=label,
                   before={"line_id": str(line.id), **before},
                   after={"line_id": str(line.id), **after})
    return line


def set_stage_plan(db: DbSession, *, actor: User, phase: Phase, stage: str, changes: dict) -> PhaseStagePlan:
    if stage not in STAGES:
        raise DomainError("unknown_stage", "That isn't one of the six stages.")
    editable = {k: v for k, v in changes.items() if k in PLAN_FIELDS and k != "updated_by_user_id"}
    if not editable:
        raise DomainError("no_changes_to_apply", "This update has no changes. Include at least one field, such as a crew count or a start date.")
    row = db.query(PhaseStagePlan).filter_by(phase_id=phase.id, stage=stage).one_or_none()
    before = _snap(row, PLAN_FIELDS)
    if row is None:
        row = PhaseStagePlan(phase_id=phase.id, stage=stage)
        db.add(row)
    for k, v in editable.items():
        setattr(row, k, v)
    row.updated_by_user_id = actor.id
    db.flush()
    db.refresh(row)
    cleared = [k for k, v in editable.items() if v is None]
    label = (f"Reset {STAGE_LABELS[stage].lower()} on {phase.name} to computed" if cleared and len(cleared) == len(editable)
             else f"Changed {STAGE_LABELS[stage].lower()} on {phase.name}")
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="stage_plan_edit", label=label,
                   before={"phase_id": str(phase.id), "stage": stage, "row": before},
                   after={"phase_id": str(phase.id), "stage": stage, "row": _snap(row, PLAN_FIELDS)})
    return row


def set_lead_time(db: DbSession, *, actor: User, item: Item, changes: dict, today: date) -> ItemLeadTime:
    changes = {k: v for k, v in changes.items() if k in ("flagged", "lead_weeks", "source_label", "quoted_at", "needed_for_stage")}
    if not changes:
        raise DomainError("no_changes_to_apply", "This update has no changes.")
    if "needed_for_stage" in changes and changes["needed_for_stage"] not in STAGES:
        raise DomainError("unknown_stage", "That isn't one of the six stages.")

    row = db.get(ItemLeadTime, item.id)
    before = _snap(row, LEAD_FIELDS)

    # A supplier label or a quoted date is only meaningful attached to a
    # number of weeks -- given without one (and none already on the
    # row), it has nothing to describe. Checked before any row is
    # created or mutated, so a doomed call never dirties the session.
    existing_weeks = row.lead_weeks if row is not None else None
    weeks_after = changes["lead_weeks"] if "lead_weeks" in changes else existing_weeks
    if ("source_label" in changes or "quoted_at" in changes) and not weeks_after:
        raise DomainError("lead_time_weeks_needed", "Enter the lead time in weeks along with who quoted it.")

    if row is None:
        row = ItemLeadTime(item_id=item.id, flagged=True)
        db.add(row)
    if "lead_weeks" in changes:
        if changes["lead_weeks"] is None:
            row.lead_weeks, row.source, row.source_label, row.quoted_at = None, None, "", None
        else:
            label = (changes.get("source_label") or row.source_label or "").strip()
            if not label:
                raise DomainError("lead_time_source_needed", "Say who quoted this lead time — a supplier, a rep, or a manufacturer.")
            row.lead_weeks, row.source, row.source_label = int(changes["lead_weeks"]), "estimator", label
            row.quoted_at = changes.get("quoted_at") or today
            row.flagged = True
    elif "source_label" in changes and row.lead_weeks is not None:
        row.source_label = (changes["source_label"] or "").strip()
    if "quoted_at" in changes and "lead_weeks" not in changes and row.lead_weeks is not None:
        row.quoted_at = changes["quoted_at"]
    if "flagged" in changes:
        row.flagged = bool(changes["flagged"])
    if "needed_for_stage" in changes:
        row.needed_for_stage = changes["needed_for_stage"]
    row.updated_by_user_id = actor.id

    after = _snap(row, LEAD_FIELDS)
    if before == after:
        # Nothing about the row actually changed -- put it back exactly
        # as it was (nothing has been flushed yet, so this is a pure
        # in-memory revert, never a db.rollback()) and refuse rather
        # than commit a vacuous action.
        _write(row, before, LEAD_FIELDS, dates=("quoted_at",), uuids=("updated_by_user_id",))
        raise DomainError("no_changes_to_apply", "This update has no changes.")

    db.flush()
    db.refresh(row)
    if "lead_weeks" in changes:
        label = f"Set lead time on {item.name} to {row.lead_weeks} weeks" if row.lead_weeks is not None else f"Cleared lead time on {item.name}"
    elif "flagged" in changes:
        label = f"{'Flagged' if row.flagged else 'Unflagged'} {item.name} as long-lead"
    else:
        label = f"Changed lead-time details on {item.name}"
    actions.commit(db, actor=actor, project_id=item.project_id, kind="lead_time_edit", label=label, item_id=item.id,
                   before={"row": before}, after={"row": after})
    return row


def _write(row, snap: dict | None, fields, decimals=(), dates=(), uuids=()):
    for f in fields:
        v = snap.get(f) if snap else None
        if v is not None and f in decimals:
            v = Decimal(v)
        if v is not None and f in dates:
            v = date.fromisoformat(v)
        if v is not None and f in uuids:
            v = uuid.UUID(v)
        setattr(row, f, v)


def apply_undo(db: DbSession, action: Action, direction: str) -> None:
    state = action.before if direction == "before" else action.after
    if action.kind == "phase_line_edit":
        # PhaseLine cascades with its phase (ON DELETE CASCADE, never
        # modeled as an ORM relationship) -- a real query, never
        # db.get(), so a row the DB has already dropped is never
        # mistaken for one the identity map merely hasn't been told
        # about yet.
        line = db.scalars(select(PhaseLine).where(PhaseLine.id == uuid.UUID(state["line_id"]))).one_or_none()
        if line is not None:
            line.hours_override = Decimal(state["hours_override"]) if state["hours_override"] is not None else None
            line.updated_by_user_id = uuid.UUID(state["updated_by_user_id"]) if state.get("updated_by_user_id") else None
    elif action.kind == "stage_plan_edit":
        row = db.query(PhaseStagePlan).filter_by(phase_id=uuid.UUID(state["phase_id"]), stage=state["stage"]).one_or_none()
        if state["row"] is None:
            if row is not None:
                db.delete(row)
        else:
            if row is None:
                row = PhaseStagePlan(phase_id=uuid.UUID(state["phase_id"]), stage=state["stage"])
                db.add(row)
            _write(row, state["row"], PLAN_FIELDS, decimals=("productive_hours_per_day", "hours_override"),
                   dates=("start_date",), uuids=("updated_by_user_id",))
    elif action.kind == "lead_time_edit":
        row = db.query(ItemLeadTime).filter_by(item_id=action.item_id).one_or_none()
        if state["row"] is None:
            if row is not None:
                db.delete(row)
        else:
            if row is None:
                row = ItemLeadTime(item_id=action.item_id)
                db.add(row)
            _write(row, state["row"], LEAD_FIELDS, dates=("quoted_at",), uuids=("updated_by_user_id",))
            if row.source_label is None:
                row.source_label = ""
    db.flush()
