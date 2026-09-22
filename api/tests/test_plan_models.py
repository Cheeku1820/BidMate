"""plan_decisions and plan_phases: one row per decision a person made on
the plan, one per phase they stated. Nothing derived is stored here."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.plan.models import PlanDecision, PlanPhase


def test_a_decision_is_unique_per_project_and_key(db, project, dana):
    db.add(PlanDecision(project_id=project.id, entry_key="spec:x:260519", status="confirmed",
                        decided_by=dana.id, decided_at=datetime.now(timezone.utc)))
    db.flush()
    db.add(PlanDecision(project_id=project.id, entry_key="spec:x:260519", status="dismissed",
                        decided_by=dana.id, decided_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        db.flush()


def test_status_is_a_closed_set(db, project, dana):
    db.add(PlanDecision(project_id=project.id, entry_key="k", status="approved",
                        decided_by=dana.id, decided_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        db.flush()


def test_an_added_phase_belongs_to_its_project(db, project, dana):
    p = PlanPhase(project_id=project.id, name="Phase 2", created_by=dana.id)
    db.add(p); db.flush()
    row = db.execute(text("select name from plan_phases where id = :id"), {"id": str(p.id)}).scalar_one()
    assert row == "Phase 2"
