"""Gathers what the pure module needs from the database and shapes its
answer (phases-and-timeline.md §4, §10).

This is the only place the schedule touches items, and it reads them
through `totals.countable_items` and `pricing.resolve_labor` -- the same
two functions the drawer totals and the Labor workspace read through -- so
a labor override typed on that screen moves a bar here, and no phase
filter ever reaches a totals query.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.schedule import copy as words
from app.schedule import plan
from app.schedule.defaults import load_company
from app.schedule.phases import first_phase, phase_of, phases_for
from app.schedule.schemas import (
    CrewOut,
    LeadOut,
    ManpowerWeekOut,
    PhaseLineOut,
    PhaseOut,
    ScheduleOut,
    StageBarOut,
)
from app.schedule.stages import STAGE_LABELS, STAGES, long_lead_class
from app.takeoff.models import (
    CompanyLaborHoursOverride,
    CompanyLaborRate,
    ItemLeadTime,
    PhaseLine,
    PhaseStagePlan,
    Project,
    ProjectLaborLine,
    Sheet,
)
from app.takeoff.pricing import resolve_labor
from app.takeoff.totals import countable_items


def _split_rules(tables) -> dict[str, plan.SplitRule]:
    return {
        key: plan.SplitRule({stage: getattr(row, stage) for stage in STAGES}, row.firm_edited)
        for key, row in tables.splits.items()
    }


def _crew_rules(tables) -> dict[str, plan.CrewRule]:
    return {
        stage: plan.CrewRule(
            row.foreman, row.journeyman, row.apprentice,
            row.productive_hours_per_day, row.productivity_factor, row.max_crew, row.firm_edited,
        )
        for stage, row in tables.crews.items()
    }


def _phase_inputs(db: DbSession, phases) -> tuple[list[plan.PhaseInput], dict[uuid.UUID, Decimal]]:
    """The pure module's view of each phase, plus each line's percent by
    line id (the wire shape reports it beside the resolved hours)."""
    inputs: list[plan.PhaseInput] = []
    percents: dict[uuid.UUID, Decimal] = {}
    for phase in phases:
        lines = list(db.scalars(
            select(PhaseLine).where(PhaseLine.phase_id == phase.id).order_by(PhaseLine.sort_order)
        ))
        plans = list(db.scalars(select(PhaseStagePlan).where(PhaseStagePlan.phase_id == phase.id)))
        for line in lines:
            percents[line.id] = line.percent_of_direct_hours
        inputs.append(plan.PhaseInput(
            phase_id=phase.id, name=phase.name, sort_order=phase.sort_order,
            start_date=phase.start_date, required_finish_date=phase.required_finish_date,
            line_percents=[(l.id, l.label, l.percent_of_direct_hours, l.hours_override) for l in lines],
            overrides={
                row.stage: plan.StageOverride(
                    row.foreman, row.journeyman, row.apprentice, row.productive_hours_per_day,
                    row.hours_override, row.start_date, row.duration_days,
                )
                for row in plans
            },
        ))
    return inputs, percents


def build_schedule_out(db: DbSession, project: Project, user: User, today: date) -> ScheduleOut:
    """The whole schedule for one project. Creates the implicit first
    phase and the org's seeded tables on first read -- the caller commits.
    """
    first = first_phase(db, project, create=True)
    phases = phases_for(db, project.id)
    by_id = {p.id: p for p in phases}
    tables = load_company(db, project.org_id)
    splits, crews = _split_rules(tables), _crew_rules(tables)

    rates = db.get(CompanyLaborRate, project.org_id)
    company_hours = {
        row.item_name: row
        for row in db.scalars(select(CompanyLaborHoursOverride).where(CompanyLaborHoursOverride.org_id == project.org_id))
    }

    items_hours: list[plan.ItemHours] = []
    leads_in: list[plan.LeadInput] = []
    item_status: dict[uuid.UUID, str] = {}
    material_by_phase: dict[uuid.UUID, Decimal] = {}
    moved_in: dict[uuid.UUID, int] = {}
    moved_out: dict[uuid.UUID, int] = {}
    unscheduled = 0
    default_split = 0

    rows = db.execute(countable_items(project.id).add_columns(Sheet)).all()
    for item, sheet in rows:
        phase_id = phase_of(item, sheet, first)
        item_status[item.id] = item.status.value
        material_by_phase[phase_id] = material_by_phase.get(phase_id, Decimal("0")) + (item.material_cost or Decimal("0"))

        home = sheet.phase_id or first.id
        if item.phase_id is not None and item.phase_id != home:
            moved_in[item.phase_id] = moved_in.get(item.phase_id, 0) + 1
            moved_out[home] = moved_out.get(home, 0) + 1

        labor = resolve_labor(
            item, project, db.get(ProjectLaborLine, item.id),
            company_rates=rates, company_hours=company_hours.get(item.name),
        )
        if labor.adjusted_hours is None:
            unscheduled += 1
        else:
            hours = plan.ItemHours(item.id, phase_id, item.category, labor.adjusted_hours)
            if plan.split_hours(hours, splits)[1]:
                default_split += 1
            items_hours.append(hours)

        lead_row = db.get(ItemLeadTime, item.id)
        item_class = long_lead_class(f"{item.name}\n{item.description}")
        flagged = lead_row.flagged if lead_row is not None else item_class is not None
        if not flagged:
            continue
        weeks = source = quoted = None
        label = ""
        if lead_row is not None and lead_row.lead_weeks is not None:
            weeks, source, label, quoted = lead_row.lead_weeks, lead_row.source, lead_row.source_label, lead_row.quoted_at
        elif item_class in tables.lead_times:
            # The firm's own table, resolved at read time and never
            # copied onto the item (§7.3), so refreshing it updates
            # every project at once.
            company_row = tables.lead_times[item_class]
            weeks, source, label, quoted = company_row.lead_weeks, "company", company_row.source_label, company_row.quoted_at
        leads_in.append(plan.LeadInput(
            item.id, item.name, phase_id, True, weeks, source, label or "", quoted,
            lead_row.needed_for_stage if lead_row is not None else "gear",
        ))

    inputs, percents = _phase_inputs(db, phases)
    schedule = plan.build_schedule(
        inputs, items_hours, splits, crews, leads_in,
        mobilization=project.mobilization_date, expected_award=project.expected_award_date,
        today=today, stale_days=tables.settings.lead_time_stale_days,
    )

    sheets_by_phase: dict[uuid.UUID, list[uuid.UUID]] = {}
    for sheet in db.scalars(
        select(Sheet).where(Sheet.project_id == project.id, Sheet.superseded_at.is_(None)).order_by(Sheet.sort_order)
    ):
        sheets_by_phase.setdefault(sheet.phase_id or first.id, []).append(sheet.id)

    phases_out = []
    for computed in schedule.phases:
        phase = by_id[computed.phase_id]
        phases_out.append(PhaseOut(
            id=phase.id, name=phase.name, sort_order=phase.sort_order,
            start_date=phase.start_date, required_finish_date=phase.required_finish_date, notes=phase.notes,
            sheet_ids=sheets_by_phase.get(phase.id, []),
            items_moved_in=moved_in.get(phase.id, 0), items_moved_out=moved_out.get(phase.id, 0),
            direct_hours=computed.direct_hours, general_conditions_hours=computed.general_conditions_hours,
            material_total=plan.q(material_by_phase.get(phase.id, Decimal("0"))),
            lines=[
                PhaseLineOut(id=line.line_id, label=line.label, hours=line.hours, source=line.source,
                             percent_of_direct_hours=percents.get(line.line_id, Decimal("0")))
                for line in computed.lines
            ],
            bars=[
                StageBarOut(
                    stage=bar.stage, label=STAGE_LABELS[bar.stage], hours=bar.hours,
                    crew=CrewOut(foreman=bar.foreman, journeyman=bar.journeyman, apprentice=bar.apprentice),
                    productive_hours_per_day=bar.productive_hours_per_day, duration_days=bar.duration_days,
                    start=bar.start, end=bar.end, start_week=bar.start_week, end_week=bar.end_week,
                    sources=bar.sources, needed_crew=bar.needed_crew, over_max=bar.over_max, note=bar.note,
                    over_max_note=(
                        words.over_max_crew(crews[bar.stage].max_crew, STAGE_LABELS[bar.stage], phase.required_finish_date)
                        if bar.over_max and phase.required_finish_date is not None else ""
                    ),
                )
                for bar in computed.bars
            ],
            start=computed.start, end=computed.end,
        ))

    leads_out = []
    for lead in schedule.leads:
        warning = None
        if lead.stale and lead.quoted_at is not None:
            warning = words.stale_lead_time_warning((today - lead.quoted_at).days, lead.source_label)
        leads_out.append(LeadOut(
            item_id=lead.item_id, item_name=lead.item_name, item_status=item_status[lead.item_id],
            phase_id=lead.phase_id, phase_name=by_id[lead.phase_id].name,
            lead_weeks=lead.lead_weeks, source=lead.source, source_label=lead.source_label, quoted_at=lead.quoted_at,
            needed_for_stage=lead.needed_for_stage, needed_by=lead.needed_by, order_by=lead.order_by,
            order_by_week=lead.order_by_week, passed=lead.passed, stale=lead.stale, note=lead.note, warning=warning,
        ))

    peak_week = next((w.week for w in schedule.manpower if w.crew == schedule.peak_crew), 0)
    return ScheduleOut(
        multi_phase=len(phases) > 1,
        relative=schedule.relative,
        phases=phases_out,
        manpower=[
            ManpowerWeekOut(week=w.week, start=w.start, foreman=w.foreman, journeyman=w.journeyman, apprentice=w.apprentice)
            for w in schedule.manpower
        ],
        peak_crew=schedule.peak_crew,
        peak_week=peak_week,
        average_crew=schedule.average_crew,
        leads=leads_out,
        unscheduled_count=unscheduled,
        unscheduled_note=words.unscheduled_items(unscheduled) if unscheduled else "",
        default_split_count=default_split,
        defaults_in_use={
            "splits": not any(row.firm_edited for row in tables.splits.values()),
            "crews": not any(row.firm_edited for row in tables.crews.values()),
        },
        expected_award_date=project.expected_award_date,
        mobilization_date=project.mobilization_date,
    )
