"""The wire shapes for the schedule routes (phases-and-timeline.md §10).

`…Out` models are snake_case on the wire, as LaborRowOut is, because
the client's mapSchedule reads them that way. `…In` models are
camelCase-native through CAMEL_MODEL_CONFIG with `populate_by_name`, so
the browser's `afterPhaseId` and a test's `after_phase_id` both land.
"""
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.takeoff.schemas import CAMEL_MODEL_CONFIG, MODEL_CONFIG

IN_CONFIG = {**CAMEL_MODEL_CONFIG, "extra": "forbid"}


class CrewOut(BaseModel):
    foreman: int
    journeyman: int
    apprentice: int
    model_config = MODEL_CONFIG


class StageBarOut(BaseModel):
    stage: str
    label: str
    hours: Decimal
    crew: CrewOut
    productive_hours_per_day: Decimal
    duration_days: int
    start: date | None = None
    end: date | None = None
    start_week: int
    end_week: int
    sources: dict[str, str]
    needed_crew: int | None = None
    over_max: bool = False
    over_max_note: str = ""
    note: str = ""
    model_config = MODEL_CONFIG


class PhaseLineOut(BaseModel):
    id: uuid.UUID
    label: str
    hours: Decimal
    source: str
    percent_of_direct_hours: Decimal
    model_config = MODEL_CONFIG


class PhaseOut(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int
    start_date: date | None = None
    required_finish_date: date | None = None
    notes: str = ""
    sheet_ids: list[uuid.UUID] = []
    items_moved_in: int = 0
    items_moved_out: int = 0
    direct_hours: Decimal
    general_conditions_hours: Decimal
    material_total: Decimal
    lines: list[PhaseLineOut] = []
    bars: list[StageBarOut] = []
    start: date | None = None
    end: date | None = None
    model_config = MODEL_CONFIG


class ManpowerWeekOut(BaseModel):
    week: int
    start: date | None = None
    foreman: int
    journeyman: int
    apprentice: int
    model_config = MODEL_CONFIG


class LeadOut(BaseModel):
    item_id: uuid.UUID
    item_name: str
    item_status: str
    phase_id: uuid.UUID
    phase_name: str
    lead_weeks: int | None = None
    # "supplier_quote" | "estimator" | "company" | None. "company" is a
    # read-time resolution from the firm's table -- it is never stored
    # on the item (phases-and-timeline.md §7.3).
    source: str | None = None
    source_label: str = ""
    quoted_at: date | None = None
    needed_for_stage: str
    needed_by: date | None = None
    order_by: date | None = None
    order_by_week: int | None = None
    passed: bool = False
    stale: bool = False
    note: str = ""
    warning: dict | None = None
    model_config = MODEL_CONFIG


class ScheduleOut(BaseModel):
    multi_phase: bool
    relative: bool
    phases: list[PhaseOut] = []
    manpower: list[ManpowerWeekOut] = []
    peak_crew: int = 0
    peak_week: int = 0
    average_crew: Decimal
    leads: list[LeadOut] = []
    unscheduled_count: int = 0
    unscheduled_note: str = ""
    default_split_count: int = 0
    defaults_in_use: dict[str, bool] = {}
    expected_award_date: date | None = None
    mobilization_date: date | None = None
    model_config = MODEL_CONFIG


class PhaseCreateIn(BaseModel):
    name: str = Field(default="", max_length=200)
    after_phase_id: uuid.UUID | None = None
    model_config = IN_CONFIG


class PhaseEditIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    required_finish_date: date | None = None
    notes: str | None = None
    sort_order: int | None = Field(default=None, ge=0)
    model_config = IN_CONFIG


class SheetsIn(BaseModel):
    sheet_ids: list[uuid.UUID]
    model_config = IN_CONFIG


class ItemPhaseIn(BaseModel):
    phase_id: uuid.UUID | None = None
    model_config = IN_CONFIG


class LineIn(BaseModel):
    # None clears the override and the line goes back to computed.
    hours: Decimal | None = Field(default=None, ge=0)
    model_config = IN_CONFIG


class StagePlanIn(BaseModel):
    foreman: int | None = Field(default=None, ge=0, le=99)
    journeyman: int | None = Field(default=None, ge=0, le=99)
    apprentice: int | None = Field(default=None, ge=0, le=99)
    productive_hours_per_day: Decimal | None = Field(default=None, gt=0, le=24)
    hours_override: Decimal | None = Field(default=None, ge=0)
    start_date: date | None = None
    duration_days: int | None = Field(default=None, ge=1, le=999)
    model_config = IN_CONFIG


class LeadTimeIn(BaseModel):
    flagged: bool | None = None
    lead_weeks: int | None = Field(default=None, ge=0, le=999)
    source_label: str | None = Field(default=None, max_length=200)
    quoted_at: date | None = None
    needed_for_stage: str | None = None
    model_config = IN_CONFIG


class ProposedPhase(BaseModel):
    name: str = Field(max_length=200)
    sheet_numbers: list[str] = []
    sheet_ids: list[uuid.UUID] = []
    evidence: dict | None = None
    model_config = IN_CONFIG


class ProposeIn(BaseModel):
    # None means "detect from the sheet numbers"; a list is the plan
    # screen's own proposal (stream F), or the estimator's edit of one.
    phases: list[ProposedPhase] | None = None
    model_config = IN_CONFIG


class ProposeOut(BaseModel):
    phases: list[ProposedPhase] = []
    note: str = ""
    model_config = IN_CONFIG


class StageSplitOut(BaseModel):
    category_key: str
    category_label: str
    demolition: Decimal
    rough_in: Decimal
    wire_pull: Decimal
    gear: Decimal
    trim: Decimal
    closeout: Decimal
    firm_edited: bool
    model_config = MODEL_CONFIG


class StageSplitIn(BaseModel):
    category_label: str = Field(max_length=100)
    demolition: Decimal = Field(ge=0, le=100)
    rough_in: Decimal = Field(ge=0, le=100)
    wire_pull: Decimal = Field(ge=0, le=100)
    gear: Decimal = Field(ge=0, le=100)
    trim: Decimal = Field(ge=0, le=100)
    closeout: Decimal = Field(ge=0, le=100)
    model_config = IN_CONFIG


class StageCrewOut(BaseModel):
    stage: str
    label: str
    foreman: int
    journeyman: int
    apprentice: int
    productive_hours_per_day: Decimal
    productivity_factor: Decimal
    max_crew: int
    firm_edited: bool
    model_config = MODEL_CONFIG


class StageCrewIn(BaseModel):
    foreman: int = Field(ge=0, le=99)
    journeyman: int = Field(ge=0, le=99)
    apprentice: int = Field(ge=0, le=99)
    productive_hours_per_day: Decimal = Field(gt=0, le=24)
    productivity_factor: Decimal = Field(gt=0, le=10)
    max_crew: int = Field(ge=1, le=99)
    model_config = IN_CONFIG


class ScheduleSettingsOut(BaseModel):
    lead_time_stale_days: int
    model_config = MODEL_CONFIG


class ScheduleSettingsIn(BaseModel):
    lead_time_stale_days: int = Field(ge=1, le=3650)
    model_config = IN_CONFIG


class PhaseLineTemplateOut(BaseModel):
    id: uuid.UUID
    label: str
    percent_of_direct_hours: Decimal
    sort_order: int
    model_config = MODEL_CONFIG


class PhaseLineTemplateIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    percent_of_direct_hours: Decimal = Field(ge=0, le=100)
    sort_order: int = Field(default=0, ge=0)
    model_config = IN_CONFIG


class CompanyLeadTimeOut(BaseModel):
    item_class: str
    lead_weeks: int
    source_label: str
    quoted_at: date
    model_config = MODEL_CONFIG


class CompanyLeadTimeIn(BaseModel):
    lead_weeks: int = Field(ge=0, le=999)
    source_label: str = Field(min_length=1, max_length=200)
    quoted_at: date
    model_config = IN_CONFIG


class ProjectDatesIn(BaseModel):
    """The two dates the whole timeline hangs from (§3.6). Both
    optional, both clearable, neither derived."""

    expected_award_date: date | None = None
    mobilization_date: date | None = None
    model_config = IN_CONFIG
