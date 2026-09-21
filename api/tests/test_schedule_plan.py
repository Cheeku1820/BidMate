import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.schedule.plan import (
    CrewRule, ItemHours, PhaseInput, SplitRule, StageOverride,
    build_phase, next_working_day, split_hours, working_days_after,
)
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
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300"))]
    plan = build_phase(phase(), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].start is None and by["rough_in"].start_week == 1 and by["rough_in"].end_week == 1
    assert by["wire_pull"].start_week == 2
    assert plan.start is None


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
