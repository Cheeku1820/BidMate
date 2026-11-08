"""Scope routes (task-10-brief.md): the two routes an estimator uses to
settle a scope statement the worker's read job found in a spec or a
general note. `status` here is a note's own vocabulary, not the four
review labels -- ScopeStatement.__doc__ says so, and the wire shape
below is checked against never carrying anything that names how the
statement was produced."""

import json
import uuid

from sqlalchemy import select

from app.takeoff.models import Action, Document, Job, ScopeStatement


def _statement(db, project, dana, **over):
    d = Document(project_id=project.id, filename="scope.pdf", doc_type="Scope", content_type="application/pdf", size_bytes=1,
                 sha256=uuid.uuid4().hex * 2, storage_key="k", uploaded_by=dana.id, status="processed")
    db.add(d); db.flush()
    fields = dict(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=2, kind="excluded",
                  text="Site lighting and pole bases.", quote="- Site lighting and pole bases.", status="found", run_id=uuid.uuid4())
    fields.update(over)
    s = ScopeStatement(**fields)
    db.add(s); db.flush(); return s


def test_list_returns_the_wire_shape(client, db, project, dana, signed_in_user):
    s = _statement(db, project, dana)
    [row] = client.get(f"/api/projects/{project.id}/scope").json()
    assert row == {"id": str(s.id), "kind": "excluded", "text": "Site lighting and pole bases.", "edited_text": None, "status": "found",
                   "document_id": str(s.document_id), "document_filename": "scope.pdf", "page": 3, "quote": "- Site lighting and pole bases."}
    assert not any(w in json.dumps(row).lower() for w in ("source", "attempt", "llm", "confidence", "model"))


def test_confirm_dismiss_and_edit_are_audited(client, db, project, dana, signed_in_user):
    s = _statement(db, project, dana)
    assert client.patch(f"/api/scope/{s.id}", json={"status": "confirmed"}).json()["status"] == "confirmed"
    assert client.patch(f"/api/scope/{s.id}", json={"edited_text": "Site lighting excluded; pole bases by GC."}).json()["edited_text"].startswith("Site lighting excluded")
    assert client.patch(f"/api/scope/{s.id}", json={"status": "dismissed"}).json()["status"] == "dismissed"
    labels = [a.label for a in db.scalars(select(Action).where(Action.kind == "scope_decide").order_by(Action.seq))]
    assert labels == ["Confirmed: Site lighting and pole bases.", "Changed: Site lighting excluded; pole bases by GC.", "Dismissed: Site lighting excluded; pole bases by GC."]
    db.refresh(s)
    assert s.decided_by == dana.id and s.decided_at is not None


def test_invalid_status_and_empty_edit_are_422(client, db, project, dana, signed_in_user):
    s = _statement(db, project, dana)
    assert client.patch(f"/api/scope/{s.id}", json={"status": "approved"}).status_code == 422
    assert client.patch(f"/api/scope/{s.id}", json={"edited_text": "   "}).status_code == 422
    assert client.patch(f"/api/scope/{s.id}", json={}).status_code == 422


def test_reopen_is_allowed_and_labeled(client, db, project, dana, signed_in_user):
    s = _statement(db, project, dana, status="confirmed")
    response = client.patch(f"/api/scope/{s.id}", json={"status": "found"})
    assert response.status_code == 200
    assert response.json()["status"] == "found"
    [action] = db.scalars(select(Action).where(Action.kind == "scope_decide"))
    assert action.label == "Reopened: Site lighting and pole bases."


# --- what a decision sets in motion -----------------------------------


def test_a_scope_decision_requeues_the_rom_estimate(client, db, project, dana, signed_in_user):
    """A scope decision changes what the estimate covers, so the ROM's
    exclusions have to be worked out again (rom-estimate.md, "scope
    filters the number"). Without this, confirming that work the
    documents excluded is actually included left the stored exclusion
    subtracting money until somebody happened to start another takeoff.

    Queued rather than run inline: generation is a batch walk over every
    item on the project, and a PATCH should not wait on it.
    """
    s = _statement(db, project, dana)
    assert client.patch(f"/api/scope/{s.id}", json={"status": "dismissed"}).status_code == 200
    queued = db.scalars(select(Job).where(Job.project_id == project.id, Job.kind == "estimate")).all()
    assert len(queued) == 1
    assert queued[0].status == "queued"


def test_a_second_decision_does_not_queue_a_second_estimate(client, db, project, dana, signed_in_user):
    """One in flight at a time -- the body replaces the whole generated
    set, so two racing writers would be two writers of one set."""
    s = _statement(db, project, dana)
    client.patch(f"/api/scope/{s.id}", json={"status": "dismissed"})
    client.patch(f"/api/scope/{s.id}", json={"status": "confirmed"})
    queued = db.scalars(select(Job).where(
        Job.project_id == project.id, Job.kind == "estimate")).all()
    assert len(queued) == 1


# --- direction (second Codex review, finding 1) ------------------------


def test_the_direction_can_be_corrected(client, db, project, dana, signed_in_user):
    """The money bug. An estimator who saw "Fire alarm by others" read
    wrong could reword the sentence -- which the ROM's keyword match
    does see -- but not the direction the ROM acts on, so the estimate
    kept subtracting the fire alarm work and cited the corrected,
    inclusive sentence as its reason.

    Direction is a fact to set, not a sentence to be parsed: parsing it
    would be a second classifier beside app.engine.scope.
    """
    s = _statement(db, project, dana, kind="by_others", text="Fire alarm by others.")
    response = client.patch(f"/api/scope/{s.id}", json={"kind": "included"})
    assert response.status_code == 200
    assert response.json()["kind"] == "included"
    db.refresh(s)
    assert s.kind == "included"


def test_a_direction_change_is_audited_in_construction_words(client, db, project, dana, signed_in_user):
    s = _statement(db, project, dana, kind="by_others", text="Fire alarm by others.")
    client.patch(f"/api/scope/{s.id}", json={"kind": "included"})
    [action] = db.scalars(select(Action).where(Action.kind == "scope_decide"))
    assert action.label == "Set to included in this price: Fire alarm by others."
    assert "by_others" not in action.label


def test_an_unrecognized_direction_is_422(client, db, project, dana, signed_in_user):
    s = _statement(db, project, dana)
    assert client.patch(f"/api/scope/{s.id}", json={"kind": "maybe"}).status_code == 422


def test_a_direction_and_a_status_in_one_request_are_refused(client, db, project, dana, signed_in_user):
    """One change per request, each its own audited action -- the same
    contract status and edited_text already had."""
    s = _statement(db, project, dana)
    response = client.patch(f"/api/scope/{s.id}", json={"kind": "included", "status": "confirmed"})
    assert response.status_code == 422


def test_a_direction_change_requeues_the_rom_estimate(client, db, project, dana, signed_in_user):
    """It changes what the estimate covers, so it has to reach the ROM
    the same way confirming and dismissing do."""
    s = _statement(db, project, dana, kind="by_others")
    client.patch(f"/api/scope/{s.id}", json={"kind": "included"})
    queued = db.scalars(select(Job).where(
        Job.project_id == project.id, Job.kind == "estimate")).all()
    assert len(queued) == 1


def test_a_direction_change_the_rom_then_honours(client, db, project, dana, signed_in_user):
    """End to end, because this is the finding and not its mechanism:
    the generator must stop excluding the work once the direction says
    it is in."""
    from app.estimate.generate_scope import scope_assumptions

    s = _statement(db, project, dana, kind="by_others", text="Fire alarm by others.")
    db.commit()
    assert any("Fire alarm" in a["title"] for a in scope_assumptions(db, project))

    client.patch(f"/api/scope/{s.id}", json={"kind": "included"})
    db.expire_all()
    assert not any("Fire alarm" in a["title"] for a in scope_assumptions(db, project))
