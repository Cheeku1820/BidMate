"""The matches API (B3b task 9): draw a box, poll, name or 'not sure' the
result into one item, discard. See task-9-brief.md for the design."""
import uuid

from sqlalchemy import select

from app.takeoff.models import Action, Item, Job, Sheet, SymbolMatch, Warning


def _readable(db, sheet):
    """Give the fixture sheet real point dimensions -- `conftest.py`'s
    `sheet` fixture never sets `width_pt`/`height_pt` (they default to 0),
    so `matches.service.create()`'s "still reading" check would otherwise
    409 every POST in this file before the box check is ever reached."""
    sheet.width_pt = 2000
    sheet.height_pt = 1500
    db.commit()


def _box():
    return {"x": 500, "y": 375, "w": 12, "h": 12}


def test_post_creates_a_pending_match_and_queues_a_job(client, signed_in_user, db, project, sheet):
    _readable(db, sheet)

    r = client.post(f"/api/sheets/{sheet.id}/matches", json=_box())

    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"id", "sheet_id", "box", "status", "count", "matches", "error"}
    assert body["status"] == "pending" and body["count"] == 0 and body["matches"] == []
    assert db.scalar(select(Job).where(Job.kind == "match", Job.symbol_match_id == uuid.UUID(body["id"]))) is not None


def test_a_second_box_while_one_is_pending_is_refused(client, signed_in_user, db, project, sheet):
    _readable(db, sheet)

    assert client.post(f"/api/sheets/{sheet.id}/matches", json=_box()).status_code == 201
    r = client.post(f"/api/sheets/{sheet.id}/matches", json=_box())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "match_in_progress"


def test_a_box_outside_the_sheet_or_too_small_is_refused(client, signed_in_user, db, sheet):
    _readable(db, sheet)

    assert client.post(f"/api/sheets/{sheet.id}/matches", json={"x": 1200, "y": 10, "w": 10, "h": 10}).status_code == 422
    assert client.post(f"/api/sheets/{sheet.id}/matches", json={"x": 100, "y": 10, "w": 2, "h": 10}).status_code == 422


def _found(db, project, sheet, user_id, n=3):
    m = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id, box=[500, 375, 12, 12],
                    status="found", matches=[[100 * i + 100, 375, 12, 12] for i in range(n)], created_by=user_id)
    db.add(m); db.commit()
    return m


def test_get_returns_the_result_without_internals(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    body = client.get(f"/api/symbol-matches/{m.id}").json()
    assert body["status"] == "found" and body["count"] == 3 and len(body["matches"]) == 3
    assert not any(k in body for k in ("score", "threshold", "dpi", "method", "job_id"))


def test_naming_the_result_adds_one_ready_item_as_one_action(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    r = client.post(f"/api/symbol-matches/{m.id}/items", json={"name": "Duplex receptacle", "symbol": "receptacle", "system": "Power"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["label"] == "Added 3 duplex receptacles from a drawn symbol"
    item = db.get(Item, uuid.UUID(body["item"]["id"]))
    assert item.quantity == 3 and item.status.value == "ready" and item.source_tag == f"match:{m.id}"
    assert item.placements == m.matches and (item.x, item.y) == (500, 375)
    actions = list(db.scalars(select(Action).where(Action.project_id == project.id, Action.kind == "add")))
    assert len(actions) == 1
    db.refresh(m)
    assert m.resolved_at is not None


def test_not_sure_adds_an_unclassified_item_needing_attention(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    r = client.post(f"/api/symbol-matches/{m.id}/items", json={"not_sure": True})
    assert r.status_code == 201, r.text
    item = db.get(Item, uuid.UUID(r.json()["item"]["id"]))
    assert item.name == "Unclassified symbol" and item.status.value == "attention"
    w = db.scalar(select(Warning).where(Warning.item_id == item.id))
    assert w.title == "Symbol not in legend" and w.found == f"A symbol appears 3 times on {sheet.number} but isn't in the legend."


def test_a_resolved_or_pending_match_cannot_be_accepted(client, signed_in_user, db, project, sheet):
    _readable(db, sheet)

    m = _found(db, project, sheet, signed_in_user.id)
    assert client.post(f"/api/symbol-matches/{m.id}/items", json={"not_sure": True}).status_code == 201
    r = client.post(f"/api/symbol-matches/{m.id}/items", json={"not_sure": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "match_resolved"
    p = client.post(f"/api/sheets/{sheet.id}/matches", json=_box()).json()
    r = client.post(f"/api/symbol-matches/{p['id']}/items", json={"not_sure": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "match_not_ready"


def test_discard_removes_the_match_and_no_item(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    assert client.delete(f"/api/symbol-matches/{m.id}").status_code == 204
    assert db.get(SymbolMatch, m.id) is None
    assert db.scalar(select(Item).where(Item.source_tag == f"match:{m.id}")) is None


def test_another_orgs_match_is_a_404(client, signed_in_user, db, other_org_project):
    other_sheet = Sheet(project_id=other_org_project.id, number="E2.1", title="Power plan",
                         discipline="Electrical", revision="Rev 1", scale="1/4\" = 1'-0\"", scale_options=[],
                         plan="office", width_pt=2000, height_pt=1500)
    db.add(other_sheet)
    db.commit()

    r = client.post(f"/api/sheets/{other_sheet.id}/matches", json=_box())
    assert r.status_code == 404
