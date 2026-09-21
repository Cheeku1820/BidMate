"""The estimator's overrides on a phase (phases-and-timeline.md §3.2,
§3.5, §3.7): sparse rows, every field independent, null = computed.
Same shape as ProjectLaborLine, same snapshot discipline."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.schedule.stages import STAGE_LABELS, STAGES
from app.takeoff import actions
from app.takeoff.actions import encode_snapshot
from app.takeoff.models import Action, Item, ItemLeadTime, Phase, PhaseLine, PhaseStagePlan

PLAN_FIELDS = ("foreman", "journeyman", "apprentice", "productive_hours_per_day", "hours_override", "start_date", "duration_days")
LEAD_FIELDS = ("flagged", "lead_weeks", "source", "source_label", "quoted_at", "needed_for_stage")


def _snap(row, fields) -> dict | None:
    return None if row is None else encode_snapshot({f: getattr(row, f) for f in fields})


def set_line_hours(db: DbSession, *, actor: User, line: PhaseLine, hours: Decimal | None) -> PhaseLine:
    phase = db.get(Phase, line.phase_id)
    before = {"hours_override": encode_snapshot({"v": line.hours_override})["v"]}
    line.hours_override = hours
    line.updated_by_user_id = actor.id
    db.flush()
    db.refresh(line)
    label = f"Set {line.label} to {line.hours_override} hours on {phase.name}" if hours is not None else f"Reset {line.label} on {phase.name} to computed"
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="phase_line_edit", label=label,
                   before={"line_id": str(line.id), **before},
                   after={"line_id": str(line.id), "hours_override": encode_snapshot({"v": line.hours_override})["v"]})
    return line


def set_stage_plan(db: DbSession, *, actor: User, phase: Phase, stage: str, changes: dict) -> PhaseStagePlan:
    if stage not in STAGES:
        raise DomainError("unknown_stage", "That isn't one of the six stages.")
    changes = {k: v for k, v in changes.items() if k in PLAN_FIELDS}
    if not changes:
        raise DomainError("no_changes_to_apply", "This update has no changes. Include at least one field, such as a crew count or a start date.")
    row = db.query(PhaseStagePlan).filter_by(phase_id=phase.id, stage=stage).one_or_none()
    before = _snap(row, PLAN_FIELDS)
    if row is None:
        row = PhaseStagePlan(phase_id=phase.id, stage=stage)
        db.add(row)
    for k, v in changes.items():
        setattr(row, k, v)
    row.updated_by_user_id = actor.id
    db.flush()
    db.refresh(row)
    cleared = [k for k, v in changes.items() if v is None]
    label = (f"Reset {STAGE_LABELS[stage].lower()} on {phase.name} to computed" if cleared and len(cleared) == len(changes)
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
    db.flush()
    db.refresh(row)
    if "lead_weeks" in changes:
        label = f"Set lead time on {item.name} to {row.lead_weeks} weeks" if row.lead_weeks is not None else f"Cleared lead time on {item.name}"
    elif "flagged" in changes:
        label = f"{'Flagged' if row.flagged else 'Unflagged'} {item.name} as long-lead"
    else:
        label = f"Changed lead-time details on {item.name}"
    actions.commit(db, actor=actor, project_id=item.project_id, kind="lead_time_edit", label=label, item_id=item.id,
                   before={"row": before}, after={"row": _snap(row, LEAD_FIELDS)})
    return row


def _write(row, snap: dict | None, fields, decimals=(), dates=()):
    for f in fields:
        v = snap.get(f) if snap else None
        if v is not None and f in decimals:
            v = Decimal(v)
        if v is not None and f in dates:
            v = date.fromisoformat(v)
        setattr(row, f, v)


def apply_undo(db: DbSession, action: Action, direction: str) -> None:
    state = action.before if direction == "before" else action.after
    if action.kind == "phase_line_edit":
        line = db.get(PhaseLine, uuid.UUID(state["line_id"]))
        if line is not None:
            line.hours_override = Decimal(state["hours_override"]) if state["hours_override"] is not None else None
    elif action.kind == "stage_plan_edit":
        row = db.query(PhaseStagePlan).filter_by(phase_id=uuid.UUID(state["phase_id"]), stage=state["stage"]).one_or_none()
        if state["row"] is None:
            if row is not None:
                db.delete(row)
        else:
            if row is None:
                row = PhaseStagePlan(phase_id=uuid.UUID(state["phase_id"]), stage=state["stage"])
                db.add(row)
            _write(row, state["row"], PLAN_FIELDS, decimals=("productive_hours_per_day", "hours_override"), dates=("start_date",))
    elif action.kind == "lead_time_edit":
        row = db.query(ItemLeadTime).filter_by(item_id=action.item_id).one_or_none()
        if state["row"] is None:
            if row is not None:
                db.delete(row)
        else:
            if row is None:
                row = ItemLeadTime(item_id=action.item_id)
                db.add(row)
            _write(row, state["row"], LEAD_FIELDS, dates=("quoted_at",))
            if row.source_label is None:
                row.source_label = ""
    db.flush()
