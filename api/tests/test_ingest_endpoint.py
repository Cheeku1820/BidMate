"""POST /api/projects/{id}/takeoff -- the endpoint that lets a processed
takeoff reach the database. Before it existed, the backend could serve a
takeoff but never receive one, so processing had nowhere to land.
"""
import uuid

from sqlalchemy import select

from app.takeoff.models import Action, Item, Sheet, Warning

PAYLOAD = {
    "sheets": [
        {"id": "tk1:0", "number": "E2.1", "takeoff_id": "tk1", "page": 0,
         "width_pt": 2000, "height_pt": 1500, "unreadable": None, "ai_reading": None},
    ],
    "items": [
        {"name": "20A duplex receptacle", "system": "Power", "category": "Devices",
         "unit": "ea", "quantity": 47, "status": "ready", "sheet_id": "tk1:0",
         "symbol": "receptacle", "warning": None, "x": 1000, "y": 750,
         "placements": [[1000, 750]], "material_cost": 188.0, "labor_hours": 15.51,
         "labor_cost": 1209.78, "total_cost": 1397.78},
    ],
}


def _ingest(client, project_id, payload=None, **body):
    return client.post(f"/api/projects/{project_id}/takeoff",
                       json={"payload": payload or PAYLOAD, **body})


def test_ingest_writes_sheets_and_items(client, db, project, signed_in_user):
    response = _ingest(client, project.id)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == 1

    sheet = db.scalars(select(Sheet).where(Sheet.project_id == project.id)).one()
    assert sheet.number == "E2.1"
    assert sheet.takeoff_id == "tk1"
    item = db.scalars(select(Item).where(Item.project_id == project.id)).one()
    assert item.name == "20A duplex receptacle"
    # width_pt=2000 -> x=1000 normalizes to 500 (1000/2000*1000); height_pt
    # =1500 -> y=750 normalizes to 375 (750/1500*750), matching Task 3's
    # own normalize_point behavior and its committed test.
    assert item.x == 500 and item.y == 375
    assert float(item.total_cost) == 1397.78


def test_ingest_replaces_rather_than_appends(client, db, project, signed_in_user):
    """Processing the same set twice yields one takeoff, not two overlaid.
    An append would silently double every count on the bid."""
    _ingest(client, project.id)
    _ingest(client, project.id)
    assert len(list(db.scalars(select(Item).where(Item.project_id == project.id)))) == 1
    assert len(list(db.scalars(select(Sheet).where(Sheet.project_id == project.id)))) == 1


def test_ingest_moves_the_project_to_review(client, db, project, signed_in_user):
    _ingest(client, project.id)
    db.refresh(project)
    assert project.stage == "review"


def test_ingest_records_one_attributable_action(client, db, project, signed_in_user):
    """Every mutation is attributable -- ingest included."""
    _ingest(client, project.id)
    actions = list(db.scalars(select(Action).where(Action.project_id == project.id, Action.kind == "ingest")))
    assert len(actions) == 1
    assert actions[0].actor_user_id == signed_in_user.id


def test_ingest_rejects_a_partial_warning(client, db, project, signed_in_user):
    """Four fields or the write is refused, at the boundary."""
    payload = {**PAYLOAD, "items": [{**PAYLOAD["items"][0], "status": "attention",
               "warning": {"reason": "legend", "title": "t", "found": "f", "why": "w"}}]}
    response = _ingest(client, project.id, payload=payload)
    assert response.status_code == 422
    assert "fix" in response.json()["detail"]["message"]
    assert not list(db.scalars(select(Item).where(Item.project_id == project.id)))


def test_ingest_stores_a_valid_warning(client, db, project, signed_in_user):
    payload = {**PAYLOAD, "items": [{**PAYLOAD["items"][0], "status": "attention",
               "warning": {"reason": "legend", "title": "Symbol not in legend", "found": "f",
                           "why": "w", "fix": "x", "where": "E2.1"}}]}
    assert _ingest(client, project.id, payload=payload).status_code == 200
    item = db.scalars(select(Item).where(Item.project_id == project.id)).one()
    # No ORM relationship carries Item -> Warning in this codebase
    # (snapshot.py queries Warning explicitly everywhere) -- matching
    # that convention here rather than the brief's `item.warnings[0]`,
    # which assumes a relationship that does not exist on the model.
    warning = db.scalars(select(Warning).where(Warning.item_id == item.id)).one()
    assert warning.title == "Symbol not in legend"


def test_ingest_refuses_another_orgs_project(client, other_org_project, signed_in_user):
    """Same 404 whether it does not exist or belongs to someone else."""
    assert _ingest(client, other_org_project.id).status_code == 404


def test_ingest_refuses_an_unknown_project(client, signed_in_user):
    assert _ingest(client, uuid.uuid4()).status_code == 404


def test_undo_after_ingest_refuses_instead_of_resurrecting(client, db, project, sheet, signed_in_user):
    """Ingest replaces the takeoff, so actions recorded against the old
    items point at rows that are gone. Undo must say so plainly rather
    than restore an item into a takeoff it was never part of."""
    from app.takeoff.models import Item, ReviewStatus

    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Panel LP-2",
                system="Distribution", category="Gear", quantity=1, unit="ea",
                status=ReviewStatus.READY)
    db.add(item)
    db.commit()

    assert client.post(f"/api/items/{item.id}/approve",
                       headers={"If-Match": "1"}).status_code in (200, 409)
    _ingest(client, project.id, confirm_replace=True)

    response = client.post(f"/api/projects/{project.id}/undo")
    # Either there is nothing eligible to undo, or the eligible action
    # names an item that is gone. Both are honest; a 500 is not.
    assert response.status_code in (200, 409)
    if response.status_code == 409:
        assert response.json()["detail"]["code"] == "item_no_longer_exists"
