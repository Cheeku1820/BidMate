"""app/takeoff/models.py's Note -- a structured record of something the
drawings do not say, and the `usage` flag that decides whether it feeds
the engine or is documentation only.
"""
import uuid

import pytest
from sqlalchemy import select

from app.takeoff.models import Item, Note


def test_note_carries_its_scope_and_usage(db, project, dana):
    note = Note(
        project_id=project.id, scope="project", scope_ref=None,
        title="Low-voltage systems excluded from Division 26",
        body="Fire alarm, security, and structured cabling are excluded per the Turner scope letter.",
        category="exclusion", status="confirmed", rfi_needed=False,
        usage="context", source_ref="Turner scope letter", author_user_id=dana.id,
    )
    db.add(note)
    db.flush()
    assert note.scope == "project"
    assert note.usage == "context"
    assert note.applied_at is None
    assert note.created_at is not None


def test_note_defaults_are_documentation_not_context(db, project, dana):
    """A note is reference-only until someone deliberately says otherwise.
    Defaulting to context would let a stray note move the estimate."""
    note = Note(project_id=project.id, scope="project", title="t", body="b",
                category="existing_condition", author_user_id=dana.id)
    db.add(note)
    db.flush()
    assert note.usage == "reference"
    assert note.status == "open"
    assert note.rfi_needed is False


def test_note_can_anchor_to_a_sheet_or_an_item(db, project, sheet, dana):
    note = Note(project_id=project.id, scope="sheet", scope_ref=sheet.id,
                title="t", body="b", category="existing_condition", author_user_id=dana.id)
    db.add(note)
    db.flush()
    assert note.scope_ref == sheet.id


def test_item_carries_the_engine_cluster_tag(db, project, sheet):
    """The merge key for an approval-preserving re-run. Counting is
    deterministic, so the same file yields the same tag on the same sheet
    -- without it there is nothing stable to match a re-run against."""
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle",
                name="20A duplex receptacle", system="Power", category="Devices",
                quantity=12, unit="ea", source_tag="R")
    db.add(item)
    db.flush()
    assert item.source_tag == "R"


def test_item_source_tag_defaults_empty(db, project, sheet):
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="panel",
                name="Panel", system="Power", category="Gear", quantity=1, unit="ea")
    db.add(item)
    db.flush()
    assert item.source_tag == ""


NOTE_BODY = {
    "scope": "project",
    "title": "Low-voltage systems excluded from Division 26",
    "body": "Fire alarm, security, and structured cabling are excluded per the Turner scope letter.",
    "category": "exclusion",
    "status": "confirmed",
    "usage": "context",
    "source_ref": "Turner scope letter",
}


def test_create_note_returns_it(client, project, signed_in_user):
    r = client.post(f"/api/projects/{project.id}/notes", json=NOTE_BODY)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == NOTE_BODY["title"]
    assert body["usage"] == "context"
    assert body["author_name"] == signed_in_user.name


def test_create_note_records_an_attributable_action(client, db, project, signed_in_user):
    from app.takeoff.models import Action
    from sqlalchemy import select
    client.post(f"/api/projects/{project.id}/notes", json=NOTE_BODY)
    actions = list(db.scalars(select(Action).where(Action.project_id == project.id, Action.kind == "note_add")))
    assert len(actions) == 1
    assert actions[0].actor_user_id == signed_in_user.id


def test_list_notes_returns_newest_first(client, project, signed_in_user):
    client.post(f"/api/projects/{project.id}/notes", json={**NOTE_BODY, "title": "first"})
    client.post(f"/api/projects/{project.id}/notes", json={**NOTE_BODY, "title": "second"})
    rows = client.get(f"/api/projects/{project.id}/notes").json()
    assert [n["title"] for n in rows] == ["second", "first"]


def test_update_note_toggles_usage(client, project, signed_in_user):
    nid = client.post(f"/api/projects/{project.id}/notes", json=NOTE_BODY).json()["id"]
    r = client.patch(f"/api/notes/{nid}", json={"usage": "reference"})
    assert r.status_code == 200
    assert r.json()["usage"] == "reference"


def test_delete_note_removes_it(client, project, signed_in_user):
    nid = client.post(f"/api/projects/{project.id}/notes", json=NOTE_BODY).json()["id"]
    assert client.delete(f"/api/notes/{nid}").status_code == 204
    assert client.get(f"/api/projects/{project.id}/notes").json() == []


def test_note_rejects_an_unknown_usage(client, project, signed_in_user):
    """usage decides whether a note moves the estimate. A typo must be
    refused, never silently stored as something the engine ignores."""
    r = client.post(f"/api/projects/{project.id}/notes", json={**NOTE_BODY, "usage": "maybe"})
    assert r.status_code == 422


def test_note_rejects_an_unknown_category(client, project, signed_in_user):
    r = client.post(f"/api/projects/{project.id}/notes", json={**NOTE_BODY, "category": "vibes"})
    assert r.status_code == 422


def test_notes_are_org_scoped(client, other_org_project, signed_in_user):
    assert client.post(f"/api/projects/{other_org_project.id}/notes", json=NOTE_BODY).status_code == 404
    assert client.get(f"/api/projects/{other_org_project.id}/notes").status_code == 404
