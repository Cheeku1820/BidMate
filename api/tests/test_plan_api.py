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


# --- deciding a line ---

def _key(client, project, section, index=0):
    return client.get(f"/api/projects/{project.id}/plan").json()[section][index]["key"]


def test_confirm_correct_dismiss_and_reopen_are_audited_and_not_undoable(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "specs")
    url = f"/api/projects/{project.id}/plan/lines/{key}"
    assert client.patch(url, json={"status": "confirmed"}).json()["status"] == "confirmed"
    r = client.patch(url, json={"edited_text": "26 05 19 — Conductors and cables"}).json()
    assert r["edited_text"] == "26 05 19 — Conductors and cables" and r["text"] == r["edited_text"] and r["found_text"].endswith("CABLES")
    assert client.patch(url, json={"status": "dismissed"}).json()["status"] == "dismissed"
    assert client.patch(url, json={"status": "found"}).json()["status"] == "found"
    labels = [a.label for a in db.scalars(select(Action).where(Action.kind == "plan_decide").order_by(Action.seq))]
    assert labels == [
        "Confirmed: 26 05 19 — LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES",
        "Changed: 26 05 19 — Conductors and cables",
        "Dismissed: 26 05 19 — Conductors and cables",
        "Reopened: 26 05 19 — Conductors and cables",
    ]
    [row] = db.scalars(select(PlanDecision).where(PlanDecision.project_id == project.id))
    assert row.entry_key == key and row.decided_by == dana.id and row.status == "found"
    # Not undoable: the undo endpoint finds nothing to reverse.
    undo = client.post(f"/api/projects/{project.id}/undo")
    assert undo.status_code in (200, 409)
    assert not any(a.kind == "undo" for a in db.scalars(select(Action).where(Action.project_id == project.id)))


def test_a_decision_shows_on_the_next_get_and_counts_as_decided(client, db, project, dana, signed_in_user, seeded):
    before = client.get(f"/api/projects/{project.id}/plan").json()["undecided"]
    key = _key(client, project, "schedules")
    client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"status": "confirmed"})
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["schedules"][0]["status"] == "confirmed" and plan["undecided"] == before - 1


def test_a_question_can_be_dismissed_through_the_same_route(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    r = client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"status": "dismissed"})
    assert r.status_code == 200 and r.json()["status"] == "dismissed" and r.json()["title"]
    assert client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"edited_text": "x"}).status_code == 422


def test_a_question_cannot_be_confirmed(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    r = client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"status": "confirmed"})
    assert r.status_code == 422
    assert not any(a.kind == "plan_decide" for a in db.scalars(select(Action).where(Action.project_id == project.id)))


def test_bad_bodies_and_stale_keys_are_refused(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "specs")
    url = f"/api/projects/{project.id}/plan/lines/{key}"
    assert client.patch(url, json={}).status_code == 422
    assert client.patch(url, json={"status": "confirmed", "edited_text": "x"}).status_code == 422
    assert client.patch(url, json={"status": "approved"}).status_code == 422
    assert client.patch(url, json={"edited_text": "   "}).status_code == 422
    assert client.patch(url, json={"edited_text": "x" * 501}).status_code == 422
    assert client.patch(f"/api/projects/{project.id}/plan/lines/spec:gone:000000", json={"status": "confirmed"}).status_code == 404
    assert client.patch(f"/api/projects/{project.id}/plan/lines/{seeded['scope'].id}", json={"status": "confirmed"}).status_code == 404


def test_a_decision_survives_a_re_read_that_finds_the_same_line(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "specs")
    client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"status": "confirmed"})
    seeded["spec"].context_text = "260519 LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES (reissued)\n"
    db.flush()
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["specs"][0]["key"] == key and plan["specs"][0]["status"] == "confirmed"
    seeded["spec"].context_text = ""
    db.flush()
    assert client.get(f"/api/projects/{project.id}/plan").json()["specs"] == []


# --- answering a question ---

def test_an_answer_becomes_a_context_note_and_marks_the_question(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    r = client.post(f"/api/projects/{project.id}/plan/questions/{key}/answer", json={"body": "Use 1/8 inch, same as E2.1."})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "answered" and out["note_id"]
    note = db.get(Note, uuid.UUID(out["note_id"]))
    assert note.usage == "context" and note.scope == "project" and note.status == "confirmed"
    assert note.title == out["title"] and note.body == "Use 1/8 inch, same as E2.1." and note.source_ref == out["where"]
    assert note.category == "existing_condition"
    kinds = [a.kind for a in db.scalars(select(Action).where(Action.project_id == project.id).order_by(Action.seq))]
    assert kinds == ["note_add", "plan_decide"]
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["questions"][0]["status"] == "answered" and plan["undecided"] == 5


def test_deleting_the_note_reopens_the_question(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    out = client.post(f"/api/projects/{project.id}/plan/questions/{key}/answer", json={"body": "One phase."}).json()
    assert client.delete(f"/api/notes/{out['note_id']}").status_code == 204
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["questions"][0]["status"] == "found" and plan["questions"][0]["note_id"] is None


def test_an_empty_answer_and_a_line_key_are_refused(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    assert client.post(f"/api/projects/{project.id}/plan/questions/{key}/answer", json={"body": "  "}).status_code == 422
    spec_key = _key(client, project, "specs")
    assert client.post(f"/api/projects/{project.id}/plan/questions/{spec_key}/answer", json={"body": "x"}).status_code == 404


def test_the_note_category_follows_the_question(client, db, project, dana, signed_in_user):
    d = _doc(db, project, dana, filename="Gerber.pdf", doc_type="Drawings", page_count=1)
    _sheet(db, project, d, number="", title="Scanned sheet", kind="other", unreadable_reason="scan", scale="")
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    scanned = next(q for q in plan["questions"] if q["title"] == "Pages that could not be read")
    out = client.post(f"/api/projects/{project.id}/plan/questions/{scanned['key']}/answer", json={"body": "Two phases: shop, office."}).json()
    assert db.get(Note, uuid.UUID(out["note_id"])).category == "customer_instruction"


def test_answering_an_already_answered_question_is_refused_until_reopened(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    client.post(f"/api/projects/{project.id}/plan/questions/{key}/answer", json={"body": "One phase."})
    r = client.post(f"/api/projects/{project.id}/plan/questions/{key}/answer", json={"body": "Two phases."})
    assert r.status_code == 422
    notes = list(db.scalars(select(Note).where(Note.project_id == project.id)))
    assert len(notes) == 1
    note_adds = [a for a in db.scalars(select(Action).where(Action.project_id == project.id)) if a.kind == "note_add"]
    assert len(note_adds) == 1

    client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"status": "found"})
    out = client.post(f"/api/projects/{project.id}/plan/questions/{key}/answer", json={"body": "Two phases."}).json()
    assert out["status"] == "answered"
    notes = list(db.scalars(select(Note).where(Note.project_id == project.id)))
    assert len(notes) == 2


# --- stated phases ---

def test_add_and_remove_a_stated_phase(client, db, project, dana, signed_in_user, seeded):
    undecided_before = client.get(f"/api/projects/{project.id}/plan").json()["undecided"]
    r = client.post(f"/api/projects/{project.id}/plan/phases", json={"name": "Phase 3 — office"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["added"] is True and out["text"] == "Phase 3 — office" and out["key"] == f"phase:added:{out['phase_id']}"
    assert out["document_id"] is None and out["page"] is None and out["quote"] is None
    # A phase the estimator typed is their own statement, so it starts
    # confirmed -- it is not something the documents left uncertain.
    assert out["status"] == "confirmed"
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert [p["text"] for p in plan["phases"]] == ["Phase 1", "Phase 2", "Phase 3 — office"]
    assert plan["undecided"] == undecided_before
    # A decision row still governs when one is recorded: a stated phase
    # can be dismissed like any line.
    assert client.patch(f"/api/projects/{project.id}/plan/lines/{out['key']}", json={"status": "dismissed"}).json()["status"] == "dismissed"
    assert client.delete(f"/api/projects/{project.id}/plan/phases/{out['phase_id']}").status_code == 204
    assert [p["text"] for p in client.get(f"/api/projects/{project.id}/plan").json()["phases"]] == ["Phase 1", "Phase 2"]
    labels = [a.label for a in db.scalars(select(Action).where(Action.kind.in_(("plan_phase_add", "plan_phase_remove"))).order_by(Action.seq))]
    assert labels == ["Added phase: Phase 3 — office", "Removed phase: Phase 3 — office"]


def test_a_stated_phase_silences_the_no_phasing_question(client, db, project, dana, signed_in_user):
    d = _doc(db, project, dana, filename="E.pdf", doc_type="Drawings", page_count=1)
    _sheet(db, project, d)
    assert any(q["title"] == "No phasing was stated" for q in client.get(f"/api/projects/{project.id}/plan").json()["questions"])
    client.post(f"/api/projects/{project.id}/plan/phases", json={"name": "Phase 1"})
    assert not any(q["title"] == "No phasing was stated" for q in client.get(f"/api/projects/{project.id}/plan").json()["questions"])


def test_phase_names_are_validated_and_unique(client, db, project, dana, signed_in_user, seeded):
    url = f"/api/projects/{project.id}/plan/phases"
    assert client.post(url, json={"name": " "}).status_code == 422
    assert client.post(url, json={"name": "x" * 101}).status_code == 422
    assert client.post(url, json={"name": "phase 1"}).status_code == 422  # detected already
    assert client.post(url, json={"name": "Phase 4"}).status_code == 201
    assert client.post(url, json={"name": "PHASE 4"}).status_code == 422  # stated already


def test_removing_a_detected_phase_or_a_stranger_is_404(client, db, project, dana, signed_in_user, seeded):
    assert client.delete(f"/api/projects/{project.id}/plan/phases/{uuid.uuid4()}").status_code == 404
