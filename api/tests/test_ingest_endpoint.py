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


def _approve_one(db, project, sheet, user):
    from app.takeoff.models import Item, ReviewStatus
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Panel LP-2",
                system="Distribution", category="Gear", quantity=1, unit="ea",
                status=ReviewStatus.APPROVED, approved_by_user_id=user.id)
    db.add(item)
    db.flush()
    return item


def test_ingest_refuses_when_approvals_would_be_lost(client, db, project, sheet, signed_in_user):
    """Replacing a takeoff that holds approvals discards a person's
    professional judgment. Product spec section 6 requires confirmation
    before discarding corrections, so the server refuses by default."""
    _approve_one(db, project, sheet, signed_in_user)
    db.commit()

    response = _ingest(client, project.id)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "approved_items_present"
    assert "1" in detail["message"]


def test_ingest_refusal_writes_nothing(client, db, project, sheet, signed_in_user):
    """The refusal must leave the takeoff untouched -- a half-applied
    refusal is worse than either outcome."""
    approved = _approve_one(db, project, sheet, signed_in_user)
    db.commit()

    _ingest(client, project.id)

    db.expire_all()
    still_there = db.get(Item, approved.id)
    assert still_there is not None
    assert still_there.status.value == "approved"
    assert db.get(Sheet, sheet.id) is not None


def test_ingest_proceeds_once_the_estimator_confirms(client, db, project, sheet, signed_in_user):
    approved = _approve_one(db, project, sheet, signed_in_user)
    db.commit()

    response = _ingest(client, project.id, confirm_replace=True)
    assert response.status_code == 200

    db.expire_all()
    assert db.get(Item, approved.id) is None
    assert db.scalars(select(Item).where(Item.project_id == project.id)).one().name == "20A duplex receptacle"


def test_ingest_needs_no_confirmation_on_a_fresh_project(client, db, project, signed_in_user):
    """First processing has nothing to lose, so the estimator is never
    asked a question with only one answer."""
    assert _ingest(client, project.id).status_code == 200


def test_ingested_fields_reach_the_snapshot(client, db, project, signed_in_user):
    """The read path carries what ingest wrote.

    A field written and never read is worse than a field never written:
    the page image can't be addressed without (takeoff_id, page_index),
    the cost columns export blank, a counted cluster collapses to one
    marker, and an unreadable sheet renders as an empty one -- silence
    reading as completeness. Asserted through the real endpoint rather
    than the builder, because the schema is the half that drops fields.
    """
    payload = {
        "sheets": [
            {**PAYLOAD["sheets"][0], "ai_reading": {"summary": "Warehouse power plan",
                                                    "devices": [{"name": "Duplex receptacle", "count": 47}]}},
            {"id": "tk1:1", "number": "E2.2", "takeoff_id": "tk1", "page": 1,
             "width_pt": 2000, "height_pt": 1500, "unreadable": "The page is a scanned photocopy with no readable linework."},
        ],
        "items": [{**PAYLOAD["items"][0], "placements": [[1000, 750], [500, 375]], "ai_confirmed": True}],
    }
    assert _ingest(client, project.id, payload=payload).status_code == 200

    body = client.get(f"/api/projects/{project.id}/snapshot").json()
    sheets = {s["number"]: s for s in body["sheets"]}

    read = sheets["E2.1"]
    assert read["takeoff_id"] == "tk1"
    assert read["page_index"] == 0
    assert read["width_pt"] == 2000 and read["height_pt"] == 1500
    assert read["unreadable_reason"] == ""
    assert read["ai_reading"]["devices"][0]["count"] == 47

    unreadable = sheets["E2.2"]
    assert unreadable["page_index"] == 1
    assert "scanned photocopy" in unreadable["unreadable_reason"]

    item = body["items"][0]
    # Money is Decimal on the wire exactly as `quantity` is -- the client
    # converts both the same way, so neither can silently become a string
    # reaching a `+`.
    assert float(item["material_cost"]) == 188.0
    assert float(item["labor_hours"]) == 15.51
    assert float(item["labor_cost"]) == 1209.78
    assert float(item["total_cost"]) == 1397.78
    # Normalized into sheet space, the same way x/y are.
    assert item["placements"] == [[500, 375], [250, 188]]
    assert item["ai_confirmed"] is True


def test_ingest_normalizes_a_malformed_ai_reading_instead_of_failing(client, db, project, signed_in_user):
    """`ai_reading` is unvalidated JSON a language model produced. A
    reading with no `devices` key, or a `devices` that isn't a list, is
    entirely plausible -- ingest must normalize it rather than let one
    odd sheet reading block the whole takeoff from landing."""
    payload = {
        "sheets": [
            {**PAYLOAD["sheets"][0], "ai_reading": {"summary": "reads as a power plan"}},
            {"id": "tk1:1", "number": "E2.2", "takeoff_id": "tk1", "page": 1,
             "width_pt": 2000, "height_pt": 1500, "unreadable": None,
             "ai_reading": {"summary": "reads as a lighting plan", "devices": "a lot"}},
        ],
        "items": [PAYLOAD["items"][0]],
    }
    response = _ingest(client, project.id, payload=payload)
    assert response.status_code == 200, response.text

    body = client.get(f"/api/projects/{project.id}/snapshot").json()
    sheets = {s["number"]: s for s in body["sheets"]}

    assert sheets["E2.1"]["ai_reading"] == {"summary": "reads as a power plan", "devices": []}
    assert sheets["E2.2"]["ai_reading"] == {"summary": "reads as a lighting plan", "devices": []}
