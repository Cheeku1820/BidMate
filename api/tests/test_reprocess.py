"""POST /api/projects/{id}/reprocess -- applying a note and re-running
the engine without discarding a person's judgment.
"""
from sqlalchemy import select

from app.takeoff.models import Action, Item, ReviewStatus

SHEET = {"id": "tk1:0", "number": "E2.1", "takeoff_id": "tk1", "page": 0,
         "width_pt": 2000, "height_pt": 1500, "unreadable": None, "ai_reading": None}


def _item(tag, name, status="ready", qty=10):
    return {"name": name, "system": "Power", "category": "Devices", "unit": "ea",
            "quantity": qty, "status": status, "sheet_id": "tk1:0", "symbol": "receptacle",
            "warning": None, "x": 1000, "y": 750, "placements": [[1000, 750]], "tag": tag,
            "material_cost": 10.0, "labor_hours": 1.0, "labor_cost": 78.0, "total_cost": 88.0}


def _payload(items):
    return {"sheets": [SHEET], "items": items}


def _seed(client, project, items):
    return client.post(f"/api/projects/{project.id}/takeoff",
                       json={"payload": _payload(items), "confirm_replace": True})


def test_reprocess_leaves_an_approved_item_untouched(client, db, project, signed_in_user):
    """The central guarantee. A note may not overwrite what a person
    approved -- their name is on it."""
    _seed(client, project, [_item("R", "20A duplex receptacle"), _item("S", "Single-pole switch")])
    approved = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    client.post(f"/api/items/{approved.id}/approve", headers={"If-Match": str(approved.version)})

    r = client.post(f"/api/projects/{project.id}/reprocess",
                    json={"payload": _payload([_item("R", "SOMETHING ELSE ENTIRELY"),
                                               _item("S", "Three-way switch")])})
    assert r.status_code == 200, r.text

    db.expire_all()
    kept = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    assert kept.name == "20A duplex receptacle"
    assert kept.status is ReviewStatus.APPROVED
    changed = db.scalars(select(Item).where(Item.source_tag == "S")).one()
    assert changed.name == "Three-way switch"


def test_reprocess_reports_what_it_did(client, db, project, signed_in_user):
    _seed(client, project, [_item("R", "20A duplex receptacle"), _item("S", "Single-pole switch")])
    approved = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    client.post(f"/api/items/{approved.id}/approve", headers={"If-Match": str(approved.version)})

    body = client.post(f"/api/projects/{project.id}/reprocess",
                       json={"payload": _payload([_item("R", "x"), _item("S", "y"), _item("P1", "Panel")])}).json()
    assert body["preserved"] == 1
    assert body["reclassified"] == 1
    assert body["added"] == 1


def test_reprocess_removes_an_unapproved_item_the_engine_no_longer_finds(client, db, project, signed_in_user):
    _seed(client, project, [_item("R", "receptacle"), _item("S", "switch")])
    client.post(f"/api/projects/{project.id}/reprocess", json={"payload": _payload([_item("R", "receptacle")])})
    db.expire_all()
    assert db.scalars(select(Item).where(Item.source_tag == "S")).one_or_none() is None


def test_reprocess_keeps_an_approved_item_the_engine_no_longer_finds(client, db, project, signed_in_user):
    """Removing an approved item because a re-run stopped seeing it would
    delete a decision without telling anyone."""
    _seed(client, project, [_item("R", "receptacle"), _item("S", "switch")])
    approved = db.scalars(select(Item).where(Item.source_tag == "S")).one()
    client.post(f"/api/items/{approved.id}/approve", headers={"If-Match": str(approved.version)})
    client.post(f"/api/projects/{project.id}/reprocess", json={"payload": _payload([_item("R", "receptacle")])})
    db.expire_all()
    assert db.scalars(select(Item).where(Item.source_tag == "S")).one() is not None


def test_reprocess_records_one_undoable_action(client, db, project, signed_in_user):
    _seed(client, project, [_item("R", "receptacle")])
    client.post(f"/api/projects/{project.id}/reprocess", json={"payload": _payload([_item("R", "x")])})
    rows = list(db.scalars(select(Action).where(Action.project_id == project.id, Action.kind == "note_apply")))
    assert len(rows) == 1
    assert rows[0].actor_user_id == signed_in_user.id


def test_reprocess_is_org_scoped(client, other_org_project, signed_in_user):
    r = client.post(f"/api/projects/{other_org_project.id}/reprocess", json={"payload": _payload([])})
    assert r.status_code == 404
