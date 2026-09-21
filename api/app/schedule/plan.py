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

from app.schedule.copy import NO_CREW, order_date_passed
from app.schedule.stages import STAGE_LABELS, STAGES

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
    start_day: int | None = None
    end_day: int | None = None

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

        start_day = end_day = None
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
                # Working-day offsets from the shared schedule origin (not
                # the calendar-week bucket above), 0-based -- what
                # build_schedule sums manpower by, day by day, so a bar
                # that spans a weekend into the next week bucket never
                # gets double-counted against the bar that follows it.
                start_day = _working_days_between(origin, start) - 1
                end_day = _working_days_between(origin, end) - 1
                cursor = working_days_after(end, 1)
            else:
                start = end = None
                start_week = day_cursor // 5 + 1
                end_week = (day_cursor + duration - 1) // 5 + 1
                start_day = day_cursor
                end_day = day_cursor + duration - 1
                day_cursor += duration
        bars.append(StageBar(stage, q(hours), foreman, journeyman, apprentice, per_day, duration,
                             start, end, start_week, end_week, sources, note=note,
                             start_day=start_day, end_day=end_day))

    return PhasePlan(
        phase_id=phase.phase_id, name=phase.name, direct_hours=q(direct), general_conditions_hours=q(gc_total),
        lines=lines, bars=bars,
        start=bars[0].start if bars else None,
        end=bars[-1].end if bars else None,
        end_week=bars[-1].end_week if bars else relative_week_start,
    )


@dataclass(frozen=True)
class LeadInput:
    item_id: uuid.UUID
    item_name: str
    phase_id: uuid.UUID
    flagged: bool
    lead_weeks: int | None
    source: str | None
    source_label: str
    quoted_at: date | None
    needed_for_stage: str


@dataclass
class LeadOut:
    item_id: uuid.UUID
    item_name: str
    phase_id: uuid.UUID
    lead_weeks: int | None
    source: str | None
    source_label: str
    quoted_at: date | None
    needed_for_stage: str
    needed_by: date | None
    order_by: date | None
    order_by_week: int | None
    passed: bool
    stale: bool
    note: str


@dataclass
class ManpowerWeek:
    week: int
    start: date | None
    foreman: int
    journeyman: int
    apprentice: int

    @property
    def crew(self) -> int:
        return self.foreman + self.journeyman + self.apprentice


@dataclass
class Schedule:
    phases: list[PhasePlan]
    manpower: list[ManpowerWeek]
    peak_crew: int
    average_crew: Decimal
    leads: list[LeadOut]
    relative: bool


def needed_crew(hours: Decimal, days_available: int, per_day: Decimal) -> int:
    if days_available <= 0 or per_day <= 0:
        return 0
    return math.ceil(hours / (Decimal(days_available) * per_day))


def _working_days_between(a: date, b: date) -> int:
    """Working days from a to b inclusive; 0 when b < a."""
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def build_schedule(
    phases: list[PhaseInput],
    items: list[ItemHours],
    splits: dict[str, SplitRule],
    crews: dict[str, CrewRule],
    leads: list[LeadInput],
    *,
    mobilization: date | None,
    expected_award: date | None,
    today: date,
    stale_days: int,
) -> Schedule:
    """The whole project's schedule: one PhasePlan per phase chained in
    sort order, the weekly manpower sum across every active bar, and the
    long-lead order-by dates counted back from the stage that installs
    each item.

    Calendar vs. relative is decided once, by the first phase only: the
    schedule is in calendar mode iff mobilization is set, or the first
    phase (lowest sort_order) has a start_date, or the first phase has a
    pinned-stage override -- never by a later phase's date alone, so
    relative and calendar week numbers never mix in one schedule."""
    by_phase: dict[uuid.UUID, list[ItemHours]] = {}
    for it in items:
        by_phase.setdefault(it.phase_id, []).append(it)

    ordered = sorted(phases, key=lambda p: p.sort_order)
    first = ordered[0] if ordered else None
    calendar_mode = mobilization is not None or (
        first is not None
        and (first.start_date is not None or any(o.start_date is not None for o in first.overrides.values()))
    )
    origin = mobilization or (first.start_date if first else None)

    plans: list[PhasePlan] = []
    cursor_date = mobilization
    cursor_week = 1
    for p in ordered:
        if calendar_mode:
            start = p.start_date or cursor_date
            phase_for_build = p
        else:
            # Relative mode is decided by the first phase alone (see
            # above); a later phase's own start_date is already ignored
            # via `start = None` below, but build_phase would still
            # anchor a phase to a calendar date on its own if any of its
            # stages carries a pinned override -- strip those pins too,
            # so a fully relative schedule never grows a calendar-dated
            # island (and never seeds `origin` from one).
            start = None
            phase_for_build = replace(p, overrides=_strip_pins(p.overrides))
        plan = build_phase(phase_for_build, by_phase.get(p.phase_id, []), splits, crews,
                           phase_start=start, relative_week_start=cursor_week, week_origin=origin)
        if calendar_mode and origin is None and plan.start is not None:
            origin = plan.start

        if p.required_finish_date is not None and plan.bars:
            finish = p.required_finish_date
            phase_start = plan.start or start
            if phase_start is not None:
                days_available = _working_days_between(phase_start, finish)
                if days_available > 0:
                    total = sum(b.hours for b in plan.bars)
                    for b in plan.bars:
                        share_days = max(1, math.floor(days_available * (b.hours / total))) if total > 0 else 0
                        b.needed_crew = needed_crew(b.hours, share_days, b.productive_hours_per_day)
                        b.over_max = b.needed_crew > crews[b.stage].max_crew
                # days_available == 0: the required finish is already
                # behind the phase's start. There's no window to solve
                # for, so every bar keeps its default needed_crew=None,
                # over_max=False rather than reporting a crew nobody asked for.

        plans.append(plan)
        if plan.end is not None:
            cursor_date = working_days_after(plan.end, 1)
        cursor_week = plan.end_week + 1

    # Manpower: one row per week the schedule spans, built from the
    # actual working-day totals rather than per-bar week ranges. A
    # phase's own bars never truly overlap in time (build_phase chains
    # them on one cursor), but two *different* bars can each touch the
    # same calendar-week bucket without ever sharing a day -- e.g. a bar
    # that runs across a weekend into the next stage's first day. Summing
    # by week bucket double-counts that; summing by actual working day,
    # across every phase, does not. A week's row is the busiest single
    # day within it, since that's the real peak headcount that week --
    # not the sum of two stages that never ran at once.
    active_bars = [b for p in plans for b in p.bars if b.duration_days > 0 and b.start_day is not None]
    day_totals: dict[int, tuple[int, int, int]] = {}
    for b in active_bars:
        for d in range(b.start_day, b.end_day + 1):
            f, j, a = day_totals.get(d, (0, 0, 0))
            day_totals[d] = (f + b.foreman, j + b.journeyman, a + b.apprentice)
    last_week = (max(b.end_day for b in active_bars) // 5 + 1) if active_bars else 0
    weeks: list[ManpowerWeek] = []
    for w in range(1, last_week + 1):
        day_lo, day_hi = (w - 1) * 5, w * 5 - 1
        best = (0, 0, 0)
        for d in range(day_lo, day_hi + 1):
            tot = day_totals.get(d)
            if tot is not None and sum(tot) > sum(best):
                best = tot
        row = ManpowerWeek(w, (origin + timedelta(weeks=w - 1)) if (calendar_mode and origin) else None, *best)
        weeks.append(row)
    peak = max((r.crew for r in weeks), default=0)
    average = q(Decimal(sum(r.crew for r in weeks)) / Decimal(len(weeks))) if weeks else Decimal("0")

    # Long-lead: order-by counted back from the stage bar that installs it.
    bars_by_phase = {p.phase_id: {b.stage: b for b in p.bars} for p in plans}
    leads_out: list[LeadOut] = []
    for L in leads:
        if not L.flagged:
            continue
        bar = bars_by_phase.get(L.phase_id, {}).get(L.needed_for_stage)
        needed_by = bar.start if bar else None
        order_by = order_by_week = None
        passed = False
        note = ""
        if L.lead_weeks is not None and needed_by is not None:
            order_by = needed_by - timedelta(weeks=L.lead_weeks)
            order_by_week = _week_of(order_by, origin) if origin else None
            threshold = expected_award or today
            passed = order_by < threshold
            if passed:
                note = order_date_passed(L.lead_weeks, STAGE_LABELS[L.needed_for_stage], needed_by)
        stale = L.lead_weeks is not None and L.quoted_at is not None and (today - L.quoted_at).days > stale_days
        leads_out.append(LeadOut(L.item_id, L.item_name, L.phase_id, L.lead_weeks, L.source, L.source_label, L.quoted_at,
                                 L.needed_for_stage, needed_by, order_by, order_by_week, passed, stale, note))

    return Schedule(plans, weeks, peak, average, leads_out, relative=not calendar_mode)
