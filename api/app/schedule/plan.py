"""The schedule's arithmetic (phases-and-timeline.md §4), pure: plain
dataclasses in, a PhasePlan out, no database, no date.today(). The
router assembles inputs in assemble.py; the client renders what comes
back and never re-derives a number.

Rounding: hours to two decimals (HALF_UP), days up to the whole day.
Working days are Monday to Friday; nothing here knows a holiday."""
import math
import uuid
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.schedule.copy import NO_CREW
from app.schedule.stages import STAGES

CENTS = Decimal("0.01")
FALLBACK_KEY = "*"


def q(x: Decimal) -> Decimal:
    return Decimal(x).quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ItemHours:
    item_id: uuid.UUID
    phase_id: uuid.UUID
    category: str
    adjusted_hours: Decimal


@dataclass(frozen=True)
class SplitRule:
    percents: dict[str, Decimal]
    firm_edited: bool


@dataclass(frozen=True)
class CrewRule:
    foreman: int
    journeyman: int
    apprentice: int
    productive_hours_per_day: Decimal
    productivity_factor: Decimal
    max_crew: int
    firm_edited: bool


@dataclass(frozen=True)
class StageOverride:
    foreman: int | None = None
    journeyman: int | None = None
    apprentice: int | None = None
    productive_hours_per_day: Decimal | None = None
    hours_override: Decimal | None = None
    start_date: date | None = None
    duration_days: int | None = None


@dataclass(frozen=True)
class PhaseInput:
    phase_id: uuid.UUID
    name: str
    sort_order: int
    start_date: date | None
    required_finish_date: date | None
    line_percents: list[tuple[uuid.UUID, str, Decimal, Decimal | None]]
    overrides: dict[str, StageOverride]


@dataclass
class StageBar:
    stage: str
    hours: Decimal
    foreman: int
    journeyman: int
    apprentice: int
    productive_hours_per_day: Decimal
    duration_days: int
    start: date | None
    end: date | None
    start_week: int
    end_week: int
    sources: dict[str, str]
    needed_crew: int | None = None
    over_max: bool = False
    note: str = ""

    @property
    def crew(self) -> int:
        return self.foreman + self.journeyman + self.apprentice


@dataclass
class PhaseLineOut:
    line_id: uuid.UUID
    label: str
    hours: Decimal
    source: str


@dataclass
class PhasePlan:
    phase_id: uuid.UUID
    name: str
    direct_hours: Decimal
    general_conditions_hours: Decimal
    lines: list[PhaseLineOut]
    bars: list[StageBar]
    start: date | None
    end: date | None
    end_week: int = 0


def split_hours(item: ItemHours, splits: dict[str, SplitRule]) -> tuple[dict[str, Decimal], bool]:
    key = (item.category or "").strip().casefold() or FALLBACK_KEY
    rule = splits.get(key)
    fallback = rule is None or key == FALLBACK_KEY
    if rule is None:
        rule = splits[FALLBACK_KEY]
    shares = {s: item.adjusted_hours * rule.percents.get(s, Decimal("0")) / Decimal("100") for s in STAGES}
    return shares, fallback


def next_working_day(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def previous_working_day(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def working_days_after(start: date, days: int) -> date:
    d = next_working_day(start)
    for _ in range(days):
        d = next_working_day(d + timedelta(days=1))
    return d


def working_days_before(d: date, days: int) -> date:
    """The mirror of working_days_after: the date `days` working days
    before `d` (days=0 -> d, rolled to the nearest working day)."""
    d = previous_working_day(d)
    for _ in range(days):
        d = previous_working_day(d - timedelta(days=1))
    return d


def _week_of(d: date, origin: date) -> int:
    return (d - origin).days // 7 + 1


def _strip_pins(overrides: dict[str, StageOverride]) -> dict[str, StageOverride]:
    return {
        stage: (replace(ov, start_date=None) if ov.start_date is not None else ov)
        for stage, ov in overrides.items()
    }


def _anchor_for_pinned_stage(
    phase: PhaseInput,
    items: list[ItemHours],
    splits: dict[str, SplitRule],
    crews: dict[str, CrewRule],
    relative_week_start: int,
) -> date:
    """`phase_start` is None but some stage is pinned to a calendar date.
    Run once with the pins ignored to learn how many working days the
    stages ahead of the first pinned one occupy, then walk the pinned
    date back that many working days -- that becomes the phase's
    calendar start, so every bar in the phase ends up dated."""
    first_pinned = next(s for s in STAGES if phase.overrides.get(s) and phase.overrides[s].start_date is not None)
    dry_phase = replace(phase, overrides=_strip_pins(phase.overrides))
    dry_plan = build_phase(dry_phase, items, splits, crews, phase_start=None, relative_week_start=relative_week_start)
    pinned_index = STAGES.index(first_pinned)
    days_before = sum(b.duration_days for b in dry_plan.bars if STAGES.index(b.stage) < pinned_index)
    pinned_date = phase.overrides[first_pinned].start_date
    return working_days_before(pinned_date, days_before)


def build_phase(
    phase: PhaseInput,
    items: list[ItemHours],
    splits: dict[str, SplitRule],
    crews: dict[str, CrewRule],
    *,
    phase_start: date | None,
    relative_week_start: int,
    week_origin: date | None = None,
) -> PhasePlan:
    """One phase's bars. `phase_start` is the resolved calendar start
    (the phase's own date, else the caller's -- previous phase end or
    mobilization) or None for relative weeks. `week_origin` is the
    project's first calendar day, for week numbering across phases."""
    if phase_start is None and any(ov.start_date is not None for ov in phase.overrides.values()):
        phase_start = _anchor_for_pinned_stage(phase, items, splits, crews, relative_week_start)

    stage_hours = {s: Decimal("0") for s in STAGES}
    for item in items:
        shares, _ = split_hours(item, splits)
        for s in STAGES:
            stage_hours[s] += shares[s]
    direct = sum(stage_hours.values(), Decimal("0"))

    lines: list[PhaseLineOut] = []
    gc_total = Decimal("0")
    for line_id, label, percent, override in phase.line_percents:
        hours = override if override is not None else direct * percent / Decimal("100")
        lines.append(PhaseLineOut(line_id, label, q(hours), "estimator" if override is not None else "computed"))
        gc_total += hours

    bars: list[StageBar] = []
    cursor = next_working_day(phase_start) if phase_start else None
    day_cursor = (relative_week_start - 1) * 5
    origin = week_origin or phase_start
    for stage in STAGES:
        crew_rule = crews[stage]
        ov = phase.overrides.get(stage, StageOverride())
        base = stage_hours[stage]
        if direct > 0:
            base += gc_total * (stage_hours[stage] / direct)
        hours = base * crew_rule.productivity_factor
        sources = {k: "computed" for k in ("hours", "foreman", "journeyman", "apprentice", "productive_hours_per_day", "start", "duration_days")}
        if ov.hours_override is not None:
            hours, sources["hours"] = ov.hours_override, "estimator"
        if hours <= 0:
            continue
        foreman = crew_rule.foreman if ov.foreman is None else ov.foreman
        journeyman = crew_rule.journeyman if ov.journeyman is None else ov.journeyman
        apprentice = crew_rule.apprentice if ov.apprentice is None else ov.apprentice
        per_day = crew_rule.productive_hours_per_day if ov.productive_hours_per_day is None else ov.productive_hours_per_day
        for name, val in (("foreman", ov.foreman), ("journeyman", ov.journeyman), ("apprentice", ov.apprentice), ("productive_hours_per_day", ov.productive_hours_per_day)):
            if val is not None:
                sources[name] = "estimator"
        crew = foreman + journeyman + apprentice
        capacity = Decimal(crew) * per_day

        no_crew = capacity <= 0 and ov.duration_days is None
        if no_crew:
            duration = 0
            note = NO_CREW
        else:
            duration = max(1, math.ceil(hours / capacity)) if capacity > 0 else 1
            if ov.duration_days is not None:
                duration, sources["duration_days"] = ov.duration_days, "estimator"
            note = ""

        pinned_here = ov.start_date is not None
        if pinned_here:
            cursor, sources["start"] = next_working_day(ov.start_date), "estimator"
            if origin is None:
                origin = cursor

        if no_crew:
            # No crew means nothing is scheduled on this stage: no
            # duration, and the timeline cursor holds so later stages
            # are unaffected -- unless the estimator pinned this stage
            # to a date, in which case that date still shows (it's what
            # they typed) and the cursor moves there for what follows.
            if pinned_here:
                start, end = cursor, None
                start_week = end_week = _week_of(start, origin)
            else:
                start = end = None
                if cursor is not None:
                    start_week = end_week = _week_of(cursor, origin)
                else:
                    start_week = end_week = day_cursor // 5 + 1
        else:
            if cursor is not None:
                start = cursor
                end = working_days_after(start, duration - 1)
                start_week = _week_of(start, origin)
                end_week = _week_of(end, origin)
                cursor = working_days_after(end, 1)
            else:
                start = end = None
                start_week = day_cursor // 5 + 1
                end_week = (day_cursor + duration - 1) // 5 + 1
                day_cursor += duration
        bars.append(StageBar(stage, q(hours), foreman, journeyman, apprentice, per_day, duration,
                             start, end, start_week, end_week, sources, note=note))

    return PhasePlan(
        phase_id=phase.phase_id, name=phase.name, direct_hours=q(direct), general_conditions_hours=q(gc_total),
        lines=lines, bars=bars,
        start=bars[0].start if bars else None,
        end=bars[-1].end if bars else None,
        end_week=bars[-1].end_week if bars else relative_week_start,
    )
