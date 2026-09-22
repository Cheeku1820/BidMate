"""The schedule routes (phases-and-timeline.md §10).

Tenancy goes through `load_project` / `load_item` like every neighbour,
so another org's phase answers 404 rather than 403. Every project-scoped
write goes through a service function that records one `actions.commit()`
and is undoable; every company-scoped write goes through
`record_company_action`, which is not. The read returns the whole
schedule after any write, because a crew change moves every later bar.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.schedule import overrides, phases as svc
from app.schedule.assemble import build_schedule_out
from app.schedule.defaults import category_key, load_company
from app.schedule.propose import apply_proposal, detect_from_sheet_numbers, preview_proposal
from app.schedule.schemas import (
    CompanyLeadTimeIn,
    CompanyLeadTimeOut,
    ItemPhaseIn,
    LeadTimeIn,
    LineIn,
    PhaseCreateIn,
    PhaseEditIn,
    PhaseLineTemplateIn,
    PhaseLineTemplateOut,
    ProjectDatesIn,
    ProposeIn,
    ProposeOut,
    ScheduleOut,
    ScheduleSettingsIn,
    ScheduleSettingsOut,
    SheetsIn,
    StageCrewIn,
    StageCrewOut,
    StagePlanIn,
    StageSplitIn,
    StageSplitOut,
)
from app.schedule.stages import LONG_LEAD_WORDS, STAGE_LABELS, STAGES
from app.takeoff.models import (
    CompanyLeadTime,
    CompanyPhaseLineTemplate,
    CompanyScheduleSettings,
    CompanyStageCrew,
    CompanyStageSplit,
    Phase,
    PhaseLine,
    Project,
)
from app.takeoff import actions
from app.takeoff.actions import encode_snapshot
from app.takeoff.pricing_router import _snapshot, record_company_action
from app.takeoff.router import load_item, load_project, not_found
from app.takeoff.schemas import ItemOut
from app.takeoff.snapshot import item_out

router = APIRouter(prefix="/api", tags=["schedule"])


def load_phase(phase_id: uuid.UUID, db: DbSession, user: User) -> Phase:
    """The tenancy gate for every phase-scoped route: 404 for a phase
    that does not exist and for one in another org alike, decided by
    `load_project` rather than a second org check here."""
    phase = db.get(Phase, phase_id)
    if phase is None:
        raise not_found()
    load_project(phase.project_id, db, user)
    return phase


def _out(db: DbSession, project: Project, user: User) -> ScheduleOut:
    return build_schedule_out(db, project, user, date.today())


def _project_of(db: DbSession, phase: Phase) -> Project:
    return db.get(Project, phase.project_id)


@router.get("/projects/{project_id}/schedule", response_model=ScheduleOut)
def get_schedule(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    out = _out(db, project, user)
    # The read creates the implicit first phase and the org's seeded
    # tables the first time it runs; nothing else here writes.
    db.commit()
    return out


@router.post("/projects/{project_id}/phases", response_model=ScheduleOut, status_code=201)
def create_phase(project_id: uuid.UUID, body: PhaseCreateIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    svc.create_phase(db, actor=user, project=project, name=body.name, after_phase_id=body.after_phase_id)
    db.commit()
    return _out(db, project, user)


@router.patch("/phases/{phase_id}", response_model=ScheduleOut)
def edit_phase(phase_id: uuid.UUID, body: PhaseEditIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    sort_order = changes.pop("sort_order", None)
    if sort_order is not None:
        svc.reorder_phase(db, actor=user, phase=phase, sort_order=sort_order)
    if changes:
        svc.edit_phase(db, actor=user, phase=phase, changes=changes)
    db.commit()
    return _out(db, _project_of(db, phase), user)


@router.delete("/phases/{phase_id}", response_model=ScheduleOut)
def delete_phase(phase_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    project = _project_of(db, phase)
    svc.delete_phase(db, actor=user, phase=phase)
    db.commit()
    return _out(db, project, user)


@router.put("/phases/{phase_id}/sheets", response_model=ScheduleOut)
def put_sheets(phase_id: uuid.UUID, body: SheetsIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    svc.assign_sheets(db, actor=user, phase=phase, sheet_ids=body.sheet_ids)
    db.commit()
    return _out(db, _project_of(db, phase), user)


@router.patch("/items/{item_id}/phase", response_model=ItemOut)
def patch_item_phase(item_id: uuid.UUID, body: ItemPhaseIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    item = load_item(item_id, db, user)
    svc.set_item_phase(db, actor=user, item=item, phase_id=body.phase_id)
    db.commit()
    return item_out(db, item)


@router.patch("/phases/{phase_id}/lines/{line_id}", response_model=ScheduleOut)
def patch_line(phase_id: uuid.UUID, line_id: uuid.UUID, body: LineIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    line = db.get(PhaseLine, line_id)
    if line is None or line.phase_id != phase.id:
        raise not_found()
    overrides.set_line_hours(db, actor=user, line=line, hours=body.hours)
    db.commit()
    return _out(db, _project_of(db, phase), user)


@router.put("/phases/{phase_id}/stages/{stage}", response_model=ScheduleOut)
def put_stage_plan(phase_id: uuid.UUID, stage: str, body: StagePlanIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    overrides.set_stage_plan(db, actor=user, phase=phase, stage=stage, changes=changes)
    db.commit()
    return _out(db, _project_of(db, phase), user)


@router.patch("/items/{item_id}/lead-time", response_model=ScheduleOut)
def patch_lead_time(item_id: uuid.UUID, body: LeadTimeIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    item = load_item(item_id, db, user)
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    overrides.set_lead_time(db, actor=user, item=item, changes=changes, today=date.today())
    db.commit()
    return _out(db, db.get(Project, item.project_id), user)


@router.patch("/projects/{project_id}/schedule-dates", response_model=ScheduleOut)
def patch_schedule_dates(
    project_id: uuid.UUID, body: ProjectDatesIn, user: User = Depends(current_user), db: DbSession = Depends(get_db),
):
    """Expected award and mobilization. Audited like the project ZIP and
    for the same reason not undoable: these are settings the estimator
    types, not a takeoff mutation."""
    project = load_project(project_id, db, user)
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    if not changes:
        raise DomainError("no_changes_to_apply", "This update has no changes. Include a date.")
    before = {field: project.__dict__.get(field) for field in changes}
    if all(before[field] == value for field, value in changes.items()):
        raise DomainError("no_changes_to_apply", "This update has no changes.")
    for field, value in changes.items():
        setattr(project, field, value)
    db.flush()
    actions.commit(
        db, actor=user, project_id=project.id, kind="project_edit", label="Changed the project schedule dates",
        before=encode_snapshot(before), after=encode_snapshot({f: getattr(project, f) for f in changes}),
    )
    db.commit()
    return _out(db, project, user)


@router.post("/projects/{project_id}/phases/propose", response_model=ProposeOut)
def propose(project_id: uuid.UUID, body: ProposeIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    proposed = body.phases if body.phases is not None else detect_from_sheet_numbers(db, project)
    return preview_proposal(db, project, proposed)


@router.post("/projects/{project_id}/phases/propose/apply", response_model=ScheduleOut)
def propose_apply(project_id: uuid.UUID, body: ProposeOut, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    apply_proposal(db, actor=user, project=project, phases=body.phases)
    db.commit()
    return _out(db, project, user)


# ---- Company tables -------------------------------------------------
#
# Org-level, so they record a CompanyAction and are deliberately not
# undoable -- the same split labor rates and material prices already
# make (pricing_router.record_company_action's docstring).


def _splits(db: DbSession, org_id: uuid.UUID) -> list[CompanyStageSplit]:
    load_company(db, org_id)  # seeds on first read
    return list(db.scalars(
        select(CompanyStageSplit).where(CompanyStageSplit.org_id == org_id).order_by(CompanyStageSplit.category_label)
    ))


@router.get("/company/stage-splits", response_model=list[StageSplitOut])
def get_stage_splits(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    rows = _splits(db, user.org_id)
    db.commit()
    return rows


@router.put("/company/stage-splits/{key}", response_model=StageSplitOut)
def put_stage_split(key: str, body: StageSplitIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    total = body.demolition + body.rough_in + body.wire_pull + body.gear + body.trim + body.closeout
    # Checked here rather than left to the table's CHECK constraint, so
    # the estimator gets the rule in words instead of a 500.
    if total != 100:
        raise DomainError("split_must_total_100", "The six stages have to add up to 100 percent.")
    load_company(db, user.org_id)
    normalized = category_key(key)
    row = db.scalars(select(CompanyStageSplit).where(
        CompanyStageSplit.org_id == user.org_id, CompanyStageSplit.category_key == normalized
    )).one_or_none()
    before = _snapshot(CompanyStageSplit, row.id, db) if row is not None else None
    if row is None:
        row = CompanyStageSplit(org_id=user.org_id, category_key=normalized, category_label=body.category_label)
        db.add(row)
    for stage in STAGES:
        setattr(row, stage, getattr(body, stage))
    row.category_label = body.category_label
    row.firm_edited = True
    row.updated_by_user_id = user.id
    db.flush()
    db.refresh(row)
    record_company_action(
        db, actor=user, kind="stage_split_edit", label=f"Changed the stage split for {row.category_label}",
        before=before or {}, after=_snapshot(CompanyStageSplit, row.id, db),
    )
    db.commit()
    db.refresh(row)
    return row


@router.delete("/company/stage-splits/{key}", status_code=204)
def delete_stage_split(key: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    normalized = category_key(key)
    if normalized == "*":
        raise DomainError("fallback_split_required", "The fallback split is what an unlisted category uses. Change it instead of removing it.")
    row = db.scalars(select(CompanyStageSplit).where(
        CompanyStageSplit.org_id == user.org_id, CompanyStageSplit.category_key == normalized
    )).one_or_none()
    if row is None:
        raise not_found()
    before = _snapshot(CompanyStageSplit, row.id, db)
    label = row.category_label
    db.delete(row)
    db.flush()
    record_company_action(
        db, actor=user, kind="stage_split_edit", label=f"Removed the stage split for {label}",
        before=before or {}, after={},
    )
    db.commit()


@router.get("/company/stage-crews", response_model=list[StageCrewOut])
def get_stage_crews(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    tables = load_company(db, user.org_id)
    rows = [
        StageCrewOut(
            stage=stage, label=STAGE_LABELS[stage], foreman=row.foreman, journeyman=row.journeyman,
            apprentice=row.apprentice, productive_hours_per_day=row.productive_hours_per_day,
            productivity_factor=row.productivity_factor, max_crew=row.max_crew, firm_edited=row.firm_edited,
        )
        for stage, row in ((s, tables.crews[s]) for s in STAGES if s in tables.crews)
    ]
    db.commit()
    return rows


@router.put("/company/stage-crews/{stage}", response_model=StageCrewOut)
def put_stage_crew(stage: str, body: StageCrewIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if stage not in STAGES:
        raise not_found()
    load_company(db, user.org_id)
    row = db.scalars(select(CompanyStageCrew).where(
        CompanyStageCrew.org_id == user.org_id, CompanyStageCrew.stage == stage
    )).one()
    before = _snapshot(CompanyStageCrew, row.id, db)
    for field in ("foreman", "journeyman", "apprentice", "productive_hours_per_day", "productivity_factor", "max_crew"):
        setattr(row, field, getattr(body, field))
    row.firm_edited = True
    row.updated_by_user_id = user.id
    db.flush()
    db.refresh(row)
    record_company_action(
        db, actor=user, kind="stage_crew_edit", label=f"Changed the crew for {STAGE_LABELS[stage].lower()}",
        before=before or {}, after=_snapshot(CompanyStageCrew, row.id, db),
    )
    db.commit()
    db.refresh(row)
    return StageCrewOut(
        stage=row.stage, label=STAGE_LABELS[row.stage], foreman=row.foreman, journeyman=row.journeyman,
        apprentice=row.apprentice, productive_hours_per_day=row.productive_hours_per_day,
        productivity_factor=row.productivity_factor, max_crew=row.max_crew, firm_edited=row.firm_edited,
    )


@router.get("/company/schedule-settings", response_model=ScheduleSettingsOut)
def get_schedule_settings(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    tables = load_company(db, user.org_id)
    out = ScheduleSettingsOut(lead_time_stale_days=tables.settings.lead_time_stale_days)
    db.commit()
    return out


@router.put("/company/schedule-settings", response_model=ScheduleSettingsOut)
def put_schedule_settings(body: ScheduleSettingsIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    load_company(db, user.org_id)
    row = db.get(CompanyScheduleSettings, user.org_id)
    before = _snapshot(CompanyScheduleSettings, user.org_id, db)
    row.lead_time_stale_days = body.lead_time_stale_days
    row.updated_by_user_id = user.id
    db.flush()
    db.refresh(row)
    record_company_action(
        db, actor=user, kind="schedule_settings_edit",
        label=f"Lead times count as out of date after {row.lead_time_stale_days} days",
        before=before or {}, after=_snapshot(CompanyScheduleSettings, user.org_id, db),
    )
    db.commit()
    db.refresh(row)
    return ScheduleSettingsOut(lead_time_stale_days=row.lead_time_stale_days)


@router.get("/company/phase-line-templates", response_model=list[PhaseLineTemplateOut])
def get_phase_line_templates(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    tables = load_company(db, user.org_id)
    rows = list(tables.templates)
    db.commit()
    return rows


@router.put("/company/phase-line-templates/{template_id}", response_model=PhaseLineTemplateOut)
def put_phase_line_template(
    template_id: str, body: PhaseLineTemplateIn, user: User = Depends(current_user), db: DbSession = Depends(get_db),
):
    """`template_id` of "new" adds a line; any other value edits that
    row. A template change applies to phases created afterwards and to
    lines still computed, never to hours an estimator typed."""
    load_company(db, user.org_id)
    if template_id == "new":
        row = CompanyPhaseLineTemplate(org_id=user.org_id, label=body.label,
                                       percent_of_direct_hours=body.percent_of_direct_hours, sort_order=body.sort_order)
        db.add(row)
        db.flush()
        before = None
    else:
        try:
            parsed = uuid.UUID(template_id)
        except ValueError:
            raise not_found()
        row = db.get(CompanyPhaseLineTemplate, parsed)
        if row is None or row.org_id != user.org_id:
            raise not_found()
        before = _snapshot(CompanyPhaseLineTemplate, row.id, db)
        row.label, row.percent_of_direct_hours, row.sort_order = body.label, body.percent_of_direct_hours, body.sort_order
    row.updated_by_user_id = user.id
    db.flush()
    db.refresh(row)
    record_company_action(
        db, actor=user, kind="phase_line_template_edit", label=f"Changed the general conditions line {row.label}",
        before=before or {}, after=_snapshot(CompanyPhaseLineTemplate, row.id, db),
    )
    db.commit()
    db.refresh(row)
    return row


@router.delete("/company/phase-line-templates/{template_id}", status_code=204)
def delete_phase_line_template(template_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.get(CompanyPhaseLineTemplate, template_id)
    if row is None or row.org_id != user.org_id:
        raise not_found()
    before = _snapshot(CompanyPhaseLineTemplate, row.id, db)
    label = row.label
    db.delete(row)
    db.flush()
    record_company_action(
        db, actor=user, kind="phase_line_template_edit", label=f"Removed the general conditions line {label}",
        before=before or {}, after={},
    )
    db.commit()


@router.get("/company/lead-times", response_model=list[CompanyLeadTimeOut])
def get_company_lead_times(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return list(db.scalars(
        select(CompanyLeadTime).where(CompanyLeadTime.org_id == user.org_id).order_by(CompanyLeadTime.item_class)
    ))


@router.put("/company/lead-times/{item_class}", response_model=CompanyLeadTimeOut)
def put_company_lead_time(
    item_class: str, body: CompanyLeadTimeIn, user: User = Depends(current_user), db: DbSession = Depends(get_db),
):
    if item_class not in LONG_LEAD_WORDS:
        raise not_found()
    row = db.scalars(select(CompanyLeadTime).where(
        CompanyLeadTime.org_id == user.org_id, CompanyLeadTime.item_class == item_class
    )).one_or_none()
    before = _snapshot(CompanyLeadTime, row.id, db) if row is not None else None
    if row is None:
        row = CompanyLeadTime(org_id=user.org_id, item_class=item_class, lead_weeks=body.lead_weeks,
                              source_label=body.source_label, quoted_at=body.quoted_at)
        db.add(row)
    else:
        row.lead_weeks, row.source_label, row.quoted_at = body.lead_weeks, body.source_label, body.quoted_at
    row.updated_by_user_id = user.id
    db.flush()
    db.refresh(row)
    record_company_action(
        db, actor=user, kind="company_lead_time_edit",
        label=f"Set the {item_class} lead time to {row.lead_weeks} weeks, from {row.source_label}",
        before=before or {}, after=_snapshot(CompanyLeadTime, row.id, db),
    )
    db.commit()
    db.refresh(row)
    return row


@router.delete("/company/lead-times/{item_class}", status_code=204)
def delete_company_lead_time(item_class: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyLeadTime).where(
        CompanyLeadTime.org_id == user.org_id, CompanyLeadTime.item_class == item_class
    )).one_or_none()
    if row is None:
        raise not_found()
    before = _snapshot(CompanyLeadTime, row.id, db)
    db.delete(row)
    db.flush()
    record_company_action(
        db, actor=user, kind="company_lead_time_edit", label=f"Removed the {item_class} lead time",
        before=before or {}, after={},
    )
    db.commit()
