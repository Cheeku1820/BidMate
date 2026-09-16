"""Scope routes (task-10-brief.md): the two routes an estimator uses to
settle a scope statement the worker's read job found in a spec or a
general note. `status` here is a note's own vocabulary, not the four
review labels -- ScopeStatement.__doc__ says so, and the wire shape
below is checked against never carrying anything that names how the
statement was produced."""

import json
import uuid

from sqlalchemy import select

from app.takeoff.models import Action, Document, ScopeStatement


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
