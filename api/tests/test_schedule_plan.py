import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.schedule.copy import NO_CREW
from app.schedule.plan import (
    CrewRule, ItemHours, LeadInput, PhaseInput, SplitRule, StageOverride,
    build_phase, build_schedule, needed_crew, next_working_day, split_hours, working_days_after,
)
from app.schedule.copy import DEFAULT_SPLIT_NOTE, order_date_passed, stale_lead_time_warning
from app.schedule.stages import STAGES

D = Decimal
PID = uuid.uuid4()


def rule(*pcts, edited=False):
    return SplitRule(percents=dict(zip(STAGES, (D(p) for p in pcts))), firm_edited=edited)


SPLITS = {"devices": rule(0, 45, 25, 0, 25, 5), "*": rule(0, 0, 0, 0, 95, 5)}
CREWS = {s: CrewRule(1, 2, 2, D("6"), D("1"), 6, False) for s in STAGES}


def phase(**kw):
    base = dict(phase_id=PID, name="Phase 1", sort_order=0, start_date=None, required_finish_date=None,
                line_percents=[], overrides={})
    base.update(kw)
    return PhaseInput(**base)


def test_split_devices_item():
    shares, fallback = split_hours(ItemHours(uuid.uuid4(), PID, "Devices", D("10")), SPLITS)
    assert shares == {"demolition": D("0"), "rough_in": D("4.5"), "wire_pull": D("2.5"), "gear": D("0"), "trim": D("2.5"), "closeout": D("0.5")}
    assert fallback is False


def test_split_unlisted_category_uses_fallback():
    shares, fallback = split_hours(ItemHours(uuid.uuid4(), PID, "Nurse call", D("10")), SPLITS)
    assert shares["trim"] == D("9.5") and shares["closeout"] == D("0.5") and fallback is True


def test_split_matches_case_insensitively():
    shares, fallback = split_hours(ItemHours(uuid.uuid4(), PID, "DEVICES", D("10")), SPLITS)
    assert fallback is False and shares["rough_in"] == D("4.5")


def test_split_empty_category_is_a_fallback():
    _, fallback = split_hours(ItemHours(uuid.uuid4(), PID, "", D("10")), SPLITS)
    assert fallback is True


def test_working_days_skip_weekends():
    assert next_working_day(date(2026, 9, 26)) == date(2026, 9, 28)   # Sat -> Mon; a weekday is returned unchanged
    assert next_working_day(date(2026, 9, 28)) == date(2026, 9, 28)
    assert working_days_after(date(2026, 9, 24), 2) == date(2026, 9, 28)  # Thu + 2 -> Mon


def test_duration_rounds_up_and_zero_hours_has_no_bar():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("80"))]   # rough-in 36 h, crew 5 x 6 = 30/day -> 2 days
    plan = build_phase(phase(), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert "demolition" not in by and "gear" not in by
    assert by["rough_in"].hours == D("36.00") and by["rough_in"].duration_days == 2
    assert by["closeout"].hours == D("4.00") and by["closeout"].duration_days == 1
    assert by["rough_in"].sources["duration_days"] == "computed"


def test_general_conditions_add_to_bars_in_proportion():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("100"))]
    line = (uuid.uuid4(), "Final and daily cleanup", D("7"), None)
    plan = build_phase(phase(line_percents=[line]), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    assert plan.direct_hours == D("100.00") and plan.general_conditions_hours == D("7.00")
    assert plan.lines[0].hours == D("7.00") and plan.lines[0].source == "computed"
    assert {b.stage: b.hours for b in plan.bars}["rough_in"] == D("48.15")   # 45 + 7 * 0.45


def test_typed_general_conditions_win():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("100"))]
    line = (uuid.uuid4(), "Final and daily cleanup", D("7"), D("12"))
    plan = build_phase(phase(line_percents=[line]), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    assert plan.lines[0].hours == D("12.00") and plan.lines[0].source == "estimator"


def test_stages_chain_across_a_weekend_from_mobilization():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300"))]   # rough 135h -> 5 days; pull 75h -> 3; trim 75 -> 3; close 15 -> 1
    plan = build_phase(phase(), items, SPLITS, CREWS, phase_start=date(2026, 10, 5), relative_week_start=1)  # a Monday
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].start == date(2026, 10, 5) and by["rough_in"].end == date(2026, 10, 9)
    assert by["wire_pull"].start == date(2026, 10, 12) and by["wire_pull"].end == date(2026, 10, 14)
    assert by["trim"].start == date(2026, 10, 15) and by["trim"].end == date(2026, 10, 19)
    assert plan.end == date(2026, 10, 20)


def test_no_dates_means_relative_weeks():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300"))]   # rough 135h -> 5d; pull 75h -> 3d; trim 75h -> 3d; close 15h -> 1d
    plan = build_phase(phase(), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].start is None and by["rough_in"].start_week == 1 and by["rough_in"].end_week == 1
    assert by["wire_pull"].start_week == 2 and by["wire_pull"].end_week == 2
    assert by["trim"].start_week == 2 and by["trim"].end_week == 3
    assert by["closeout"].start_week == 3 and by["closeout"].end_week == 3
    assert plan.start is None


def test_relative_weeks_count_working_days_not_stage_count():
    def solo(stage):
        return rule(*[100 if s == stage else 0 for s in STAGES])

    splits = {
        "a": solo("demolition"), "b": solo("rough_in"), "c": solo("wire_pull"),
        "*": rule(0, 0, 0, 0, 0, 100),
    }
    items = [
        ItemHours(uuid.uuid4(), PID, "a", D("75")),   # each -> ceil(75/30) = 3 working days
        ItemHours(uuid.uuid4(), PID, "b", D("75")),
        ItemHours(uuid.uuid4(), PID, "c", D("75")),
    ]
    plan = build_phase(phase(), items, splits, CREWS, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert (by["demolition"].start_week, by["demolition"].end_week) == (1, 1)
    assert (by["rough_in"].start_week, by["rough_in"].end_week) == (1, 2)
    assert (by["wire_pull"].start_week, by["wire_pull"].end_week) == (2, 2)


def test_pinned_start_shifts_later_stages_and_overrides_are_marked():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300"))]
    ov = {"wire_pull": StageOverride(start_date=date(2026, 10, 19), journeyman=4, duration_days=4)}
    plan = build_phase(phase(overrides=ov), items, SPLITS, CREWS, phase_start=date(2026, 10, 5), relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["wire_pull"].start == date(2026, 10, 19) and by["wire_pull"].journeyman == 4 and by["wire_pull"].duration_days == 4
    assert by["wire_pull"].sources["start"] == "estimator" and by["wire_pull"].sources["journeyman"] == "estimator"
    assert by["wire_pull"].sources["foreman"] == "computed"
    assert by["trim"].start == date(2026, 10, 23)


def test_hours_override_replaces_computed_hours():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("80"))]
    ov = {"rough_in": StageOverride(hours_override=D("60"))}
    plan = build_phase(phase(overrides=ov), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].hours == D("60.00") and by["rough_in"].sources["hours"] == "estimator"


def test_productivity_factor_scales_stage_hours():
    crews = dict(CREWS); crews["trim"] = CrewRule(0, 2, 2, D("6"), D("1.2"), 6, True)
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("100"))]
    plan = build_phase(phase(), items, SPLITS, crews, phase_start=None, relative_week_start=1)
    assert {b.stage: b.hours for b in plan.bars}["trim"] == D("30.00")


def test_zero_crew_sizes_nothing_and_leaves_later_stages_unaffected():
    crews = dict(CREWS); crews["rough_in"] = CrewRule(0, 0, 0, D("6"), D("1"), 6, True)
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("80"))]
    plan = build_phase(phase(), items, SPLITS, crews, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].duration_days == 0
    assert by["rough_in"].start is None and by["rough_in"].end is None
    assert by["rough_in"].note == NO_CREW
    assert by["wire_pull"].start_week == 1   # rough_in consumed no time, so wire_pull isn't pushed out


def test_zero_crew_with_a_duration_override_still_schedules():
    crews = dict(CREWS); crews["rough_in"] = CrewRule(0, 0, 0, D("6"), D("1"), 6, True)
    ov = {"rough_in": StageOverride(duration_days=3)}
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("80"))]
    plan = build_phase(phase(overrides=ov), items, SPLITS, crews, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].duration_days == 3
    assert by["rough_in"].note == ""


def test_pinned_stage_with_no_phase_start_anchors_the_phase():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300"))]   # rough 135h -> 5d; pull 75h -> 3d
    ov = {"wire_pull": StageOverride(start_date=date(2026, 10, 19))}   # a Monday
    plan = build_phase(phase(overrides=ov), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].start == date(2026, 10, 12)
    assert by["wire_pull"].start == date(2026, 10, 19)
    assert plan.start == date(2026, 10, 12)
    assert all(b.start is not None and b.end is not None for b in plan.bars)


def test_pinned_zero_crew_stage_keeps_its_date_and_moves_the_cursor():
    crews = dict(CREWS); crews["wire_pull"] = CrewRule(0, 0, 0, D("6"), D("1"), 6, True)
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300"))]
    ov = {"wire_pull": StageOverride(start_date=date(2026, 11, 2))}   # a Monday
    plan = build_phase(phase(overrides=ov), items, SPLITS, crews, phase_start=date(2026, 10, 5), relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["wire_pull"].start == date(2026, 11, 2) and by["wire_pull"].end is None
    assert by["wire_pull"].note == NO_CREW
    assert by["wire_pull"].sources["start"] == "estimator"
    assert by["trim"].start == date(2026, 11, 2)


P2 = uuid.uuid4()


def two_phases(items_a=D("300"), items_b=D("120"), **kw):
    phases = [phase(), phase(phase_id=P2, name="Phase 2", sort_order=1, **kw)]
    items = [ItemHours(uuid.uuid4(), PID, "Devices", items_a), ItemHours(uuid.uuid4(), P2, "Devices", items_b)]
    return phases, items


def test_needed_crew():
    assert needed_crew(D("120"), 4, D("6")) == 5
    assert needed_crew(D("120"), 2, D("6")) == 10


def test_reverse_solve_marks_over_max_and_writes_nothing():
    phases, items = two_phases(required_finish_date=date(2026, 11, 6))
    sched = build_schedule(phases, items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5),
                           expected_award=None, today=date(2026, 9, 21), stale_days=60)
    p2 = sched.phases[1]
    assert all(b.needed_crew is not None for b in p2.bars)
    assert sched.phases[0].bars[0].needed_crew is None      # no window on phase 1
    tight = build_schedule([phases[0], phase(phase_id=P2, name="Phase 2", sort_order=1, required_finish_date=date(2026, 10, 22))],
                           items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5), expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert any(b.over_max for b in tight.phases[1].bars)


def test_second_phase_follows_first_unless_dated():
    phases, items = two_phases()
    sched = build_schedule(phases, items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5), expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert sched.phases[1].start == date(2026, 10, 21)
    dated = build_schedule([phases[0], phase(phase_id=P2, name="Phase 2", sort_order=1, start_date=date(2026, 11, 2))],
                           items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5), expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert dated.phases[1].start == date(2026, 11, 2)


def test_manpower_sums_overlapping_phases_by_role():
    phases = [phase(), phase(phase_id=P2, name="Phase 2", sort_order=1, start_date=date(2026, 10, 5))]
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300")), ItemHours(uuid.uuid4(), P2, "Devices", D("300"))]
    sched = build_schedule(phases, items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5), expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    week1 = sched.manpower[0]
    assert (week1.foreman, week1.journeyman, week1.apprentice) == (2, 4, 4)
    assert sched.peak_crew == 10 and sched.relative is False


def test_relative_schedule_when_nothing_is_dated():
    phases, items = two_phases()
    sched = build_schedule(phases, items, SPLITS, CREWS, [], mobilization=None, expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert sched.relative is True and sched.manpower[0].start is None and sched.manpower[0].week == 1


def test_only_second_phase_dated_stays_relative():
    phases, items = two_phases(start_date=date(2026, 11, 2))
    sched = build_schedule(phases, items, SPLITS, CREWS, [], mobilization=None, expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert sched.relative is True


def lead(**kw):
    base = dict(item_id=uuid.uuid4(), item_name="Switchboard MSB-1", phase_id=PID, flagged=True, lead_weeks=40,
                source="supplier_quote", source_label="Graybar", quoted_at=date(2026, 9, 12), needed_for_stage="gear")
    base.update(kw)
    return LeadInput(**base)


def gear_items():
    return [ItemHours(uuid.uuid4(), PID, "Distribution", D("100"))]   # gear bar exists


def test_order_by_counts_back_from_the_stage_it_is_needed_for():
    sched = build_schedule([phase(start_date=date(2027, 2, 22))], gear_items(), SPLITS | {"distribution": rule(0, 20, 10, 60, 5, 5)},
                           CREWS, [lead()], mobilization=None, expected_award=date(2026, 9, 1), today=date(2026, 9, 21), stale_days=60)
    out = sched.leads[0]
    gear_start = {b.stage: b for b in sched.phases[0].bars}["gear"].start
    assert out.needed_by == gear_start
    assert out.order_by == gear_start - timedelta(weeks=40)
    assert out.passed is True and "Order date has passed" in out.note and "40 weeks" in out.note


def test_order_by_without_award_compares_to_today():
    sched = build_schedule([phase(start_date=date(2027, 9, 6))], gear_items(), SPLITS | {"distribution": rule(0, 20, 10, 60, 5, 5)},
                           CREWS, [lead(lead_weeks=10)], mobilization=None, expected_award=None, today=date(2026, 9, 21), stale_days=60)
    assert sched.leads[0].passed is False and sched.leads[0].note == ""


def test_no_weeks_means_no_date():
    sched = build_schedule([phase(start_date=date(2027, 2, 22))], gear_items(), SPLITS | {"distribution": rule(0, 20, 10, 60, 5, 5)},
                           CREWS, [lead(lead_weeks=None, source=None, source_label="", quoted_at=None)],
                           mobilization=None, expected_award=None, today=date(2026, 9, 21), stale_days=60)
    out = sched.leads[0]
    assert out.order_by is None and out.needed_by is not None and out.passed is False and out.stale is False


def test_stale_lead_time():
    sched = build_schedule([phase(start_date=date(2027, 2, 22))], gear_items(), SPLITS | {"distribution": rule(0, 20, 10, 60, 5, 5)},
                           CREWS, [lead(quoted_at=date(2026, 7, 1))], mobilization=None, expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert sched.leads[0].stale is True
    w = stale_lead_time_warning(82, "Graybar")
    assert set(w) == {"title", "found", "why", "fix", "where"} and "82 days" in w["found"] and "Graybar" in w["found"]


def test_copy_is_sentence_case_and_carries_no_bare_week_number():
    assert order_date_passed(40, "Gear", date(2027, 2, 22)).startswith("Order date has passed")
    assert DEFAULT_SPLIT_NOTE[0].isupper() and "!" not in DEFAULT_SPLIT_NOTE and "recommended" not in DEFAULT_SPLIT_NOTE.lower()
