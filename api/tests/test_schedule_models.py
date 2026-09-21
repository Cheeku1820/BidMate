import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.schedule.stages import LONG_LEAD_WORDS, STAGES, STAGE_LABELS, long_lead_class
from app.takeoff.models import (
    CompanyStageSplit, ItemLeadTime, Phase, PhaseLine, PhaseStagePlan, Sheet, Item,
)


def test_six_stages_in_order():
    assert STAGES == ("demolition", "rough_in", "wire_pull", "gear", "trim", "closeout")
    assert STAGE_LABELS["rough_in"] == "Rough-in"
    assert STAGE_LABELS["closeout"] == "Close-out"


@pytest.mark.parametrize("text,expected", [
    ("Switch Board MSBS", "switchboard"),
    ("Standby Generators 150kW", "generator"),
    ("Panelboard LP-2, 42 circuit", "panelboard"),
    ("Furnish & install new setup transformer", "transformer"),
    ("ATS-1 automatic transfer switch", "ats"),
    ("S.P.D (Surge Protective Device)", None),
    ("VFD for exhaust fan", None),
    ("20A duplex receptacle", None),
])
def test_long_lead_class(text, expected):
    assert long_lead_class(text) == expected


def test_spd_and_vfd_are_not_long_lead_words():
    assert "spd" not in LONG_LEAD_WORDS and "vfd" not in LONG_LEAD_WORDS


def test_phase_rows_and_columns(db, project, sheet, item):
    phase = Phase(project_id=project.id, name="Phase 1", sort_order=0)
    db.add(phase); db.flush()
    sheet.phase_id = phase.id
    item.phase_id = None
    db.add(PhaseLine(phase_id=phase.id, label="Final and daily cleanup", percent_of_direct_hours=Decimal("3"), sort_order=0))
    db.add(PhaseStagePlan(phase_id=phase.id, stage="rough_in", journeyman=3))
    db.add(ItemLeadTime(item_id=item.id, flagged=True))
    db.flush()
    assert db.get(ItemLeadTime, item.id).needed_for_stage == "gear"
    assert db.get(ItemLeadTime, item.id).lead_weeks is None


def test_stage_plan_rejects_unknown_stage(db, project):
    phase = Phase(project_id=project.id, name="Phase 1", sort_order=0)
    db.add(phase); db.flush()
    db.add(PhaseStagePlan(phase_id=phase.id, stage="painting"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_split_must_sum_to_100(db, org):
    db.add(CompanyStageSplit(org_id=org.id, category_key="devices", category_label="Devices",
                             demolition=0, rough_in=45, wire_pull=25, gear=0, trim=25, closeout=4))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_deleting_a_phase_nulls_sheet_and_item_references(db, project, sheet, item):
    phase = Phase(project_id=project.id, name="Phase 2", sort_order=1)
    db.add(phase); db.flush()
    sheet.phase_id = phase.id; item.phase_id = phase.id; db.flush()
    db.delete(phase); db.flush()
    db.refresh(sheet); db.refresh(item)
    assert sheet.phase_id is None and item.phase_id is None
