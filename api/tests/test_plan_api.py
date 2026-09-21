"""The plan routes. The plan is derived on every GET from what the read
job stored; only decisions and stated phases persist. Nothing on the
wire names how a line was produced."""

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from app.plan.models import PlanDecision, PlanPhase
from app.takeoff.models import Action, Document, Note, ScopeStatement, Sheet


SPEC_TEXT = "SECTION 26 05 19 - LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES\nPhase 2 work follows.\n"


def _doc(db, project, dana, filename="Spec.pdf", doc_type="Specifications", status="processed", context_text="", page_count=4):
    d = Document(project_id=project.id, filename=filename, doc_type=doc_type, content_type="application/pdf", size_bytes=1,
                 sha256=uuid.uuid4().hex * 2, storage_key="k", uploaded_by=dana.id, status=status,
                 context_text=context_text, page_count=page_count)
    db.add(d); db.flush(); return d


def _sheet(db, project, doc, **over):
    fields = dict(project_id=project.id, number="E2.1", title="Power plan", discipline="Electrical", revision="",
                  scale='1/8" = 1\'-0"', scale_options=[], plan="", takeoff_id=str(doc.id), page_index=0, kind="plan",
                  unreadable_reason="", schedule_text="")
    fields.update(over)
    s = Sheet(**fields)
    db.add(s); db.flush(); return s


def _scope(db, project, doc, **over):
    fields = dict(org_id=project.org_id, project_id=project.id, document_id=doc.id, page_index=1, kind="excluded",
                  text="Site lighting.", quote="- Site lighting.", status="found", run_id=uuid.uuid4())
    fields.update(over)
    s = ScopeStatement(**fields)
    db.add(s); db.flush(); return s


@pytest.fixture
def seeded(db, project, dana):
    """A project with one spec, one drawing set of three sheets (a
    schedule, a plan with a phase in its title, a plan with no scale),
    and one scope statement."""
    spec = _doc(db, project, dana, context_text=SPEC_TEXT)
    drawings = _doc(db, project, dana, filename="E-set.pdf", doc_type="Drawings", page_count=3)
    sched = _sheet(db, project, drawings, number="E0.1", title="Luminaire schedule", kind="schedule", page_index=0, scale="")
    p1 = _sheet(db, project, drawings, number="E2.1", title="Phase 1 power plan", page_index=1)
    p2 = _sheet(db, project, drawings, number="E2.2", title="Lighting plan", page_index=2, scale="")
    scope = _scope(db, project, drawings)
    return dict(spec=spec, drawings=drawings, sched=sched, p1=p1, p2=p2, scope=scope)


def test_get_assembles_every_section(client, db, project, dana, signed_in_user, seeded):
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["reading"] is False and plan["has_drawings"] is True and plan["read_at"] is not None
    assert [s["text"] for s in plan["scope"]] == ["Site lighting."]
    assert [s["text"] for s in plan["specs"]] == ["26 05 19 — LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES"]
    assert plan["specs"][0]["page"] is None and plan["specs"][0]["document_filename"] == "Spec.pdf"
    assert [s["text"] for s in plan["schedules"]] == ["Luminaire schedule"]
    assert plan["schedules"][0]["page"] == 1 and plan["schedules"][0]["sheet_number"] == "E0.1"
    assert [p["text"] for p in plan["phases"]] == ["Phase 1", "Phase 2"]
    assert plan["phases"][0]["places"][0]["quote"] == "Phase 1 power plan"
    assert [q["key"] for q in plan["questions"]] == [f"question:no_scale:{seeded['p2'].id}"]
    assert plan["undecided"] == 1 + 1 + 1 + 2 + 1  # scope + spec + schedule + phases + question
    for line in plan["specs"] + plan["schedules"] + plan["phases"]:
        assert line["status"] == "found" and line["edited_text"] is None and line["found_text"] == line["text"]
    assert not any(w in json.dumps(plan).lower() for w in ("attempt", "llm", "confidence", "model", "run_id", "rule"))


def test_get_on_a_scanned_set_is_one_question_per_document(client, db, project, dana, signed_in_user):
    d = _doc(db, project, dana, filename="Gerber.pdf", doc_type="Drawings", page_count=2)
    _sheet(db, project, d, number="", title="Scanned sheet", kind="other", page_index=0, unreadable_reason="scan", scale="")
    _sheet(db, project, d, number="", title="Scanned sheet", kind="other", page_index=1, unreadable_reason="scan", scale="")
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["specs"] == [] and plan["schedules"] == [] and plan["phases"] == []
    rules = [q["title"] for q in plan["questions"]]
    assert rules[0] == "Pages that could not be read"
    assert plan["questions"][0]["found"].startswith("2 of 2 pages in Gerber.pdf")
    for q in plan["questions"]:
        assert q["title"] and q["found"] and q["why"] and q["fix"] and q["where"]


def test_get_reports_reading_while_a_drawing_set_is_still_being_read(client, db, project, dana, signed_in_user):
    _doc(db, project, dana, filename="E.pdf", doc_type="Drawings", status="processing")
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["reading"] is True and plan["has_drawings"] is True


def test_get_moves_the_stage_to_plan_once_and_never_backward(client, db, project, dana, signed_in_user, seeded):
    assert project.stage == "setup"
    client.get(f"/api/projects/{project.id}/plan")
    db.refresh(project)
    assert project.stage == "plan"
    project.stage = "review"; db.flush()
    client.get(f"/api/projects/{project.id}/plan")
    db.refresh(project)
    assert project.stage == "review"


def test_get_does_not_move_the_stage_while_drawings_are_reading(client, db, project, dana, signed_in_user):
    _doc(db, project, dana, filename="E.pdf", doc_type="Drawings", status="processing")
    client.get(f"/api/projects/{project.id}/plan")
    db.refresh(project)
    assert project.stage == "setup"


def test_get_does_not_move_the_stage_backward_when_the_row_moved_underneath_it(client, db, project, dana, signed_in_user, seeded):
    """The in-session `project` object was loaded (and is still "setup"
    in Python) when another process -- the worker, with no lock --
    advances the row itself to "processing". The GET must not clobber
    that forward progress back to "plan": the conditional UPDATE's WHERE
    clause, not the stale in-session attribute, is what decides."""
    assert project.stage == "setup"
    db.execute(text("update projects set stage = 'processing' where id = :id"), {"id": str(project.id)})
    db.flush()
    client.get(f"/api/projects/{project.id}/plan")
    db.refresh(project)
    assert project.stage == "processing"
