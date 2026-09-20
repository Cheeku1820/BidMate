"""POST /api/items/{id}/apply-proposal -- one undoable action for the cluster."""
import pytest
from sqlalchemy import select

from app.takeoff.models import Action, Item, ReviewStatus, Sheet, SymbolResolution, Warning, WarningReason


def _twin(db, item, sheet_id=None, tag="F"):
    t = Item(project_id=item.project_id, sheet_id=sheet_id or item.sheet_id, symbol="luminaire",
             name="Luminaire type F", system="Lighting", category="Fixtures", quantity=1, unit="EA",
             status=ReviewStatus.ATTENTION, x=5, y=5, source_tag=tag)
    db.add(t); db.flush(); return t


def _proposal(items, **over):
    base = {"intent": "reclassify", "target_item_ids": [str(i.id) for i in items],
            "name": "2x4 LED troffer, 4000K — type F", "system": "Lighting", "category": "Fixtures", "unit": "ea",
            "catalog_id": None, "schedule_match": {"sheet": "E-501", "line": "F"}, "quantity": None,
            "reject_reason": None, "summary": "Applies to all", "source": "read",
            "versions": {str(i.id): i.version for i in items}}
    base.update(over)
    return base


def test_apply_renames_the_cluster_approves_and_records_one_action(client, db, item, signed_in_user):
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION
    db.add(Warning(item_id=item.id, reason=WarningReason.LEGEND, title="Fixture type needs confirmation",
                   found="f", why="w", fix="x", where_="E-501"))
    twin = _twin(db, item); db.commit()
    r = client.post(f"/api/items/{item.id}/apply-proposal",
                    json={"proposal": _proposal([item, twin], quantity=28), "approve": True, "note": "type F per E-501"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "Approved 2 × 2x4 LED troffer, 4000K — type F"
    assert body["also_matching"] == {"count": 0, "sheet_numbers": []}
    db.expire_all()
    for it in (item, twin):
        fresh = db.get(Item, it.id)
        assert fresh.name == "2x4 LED troffer, 4000K — type F" and float(fresh.quantity) == 28
        assert fresh.status is ReviewStatus.APPROVED and fresh.resolve_note == "type F per E-501"
    assert db.scalars(select(Warning).where(Warning.item_id == item.id)).first() is None
    actions = db.scalars(select(Action).where(Action.project_id == item.project_id)).all()
    assert [a.kind for a in actions] == ["resolve"]
    assert len(actions[0].before["items"]) == 2 and actions[0].note == "type F per E-501"


def test_confirm_without_approve_leaves_status_alone(client, db, item, signed_in_user):
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION; db.commit()
    client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": _proposal([item]), "approve": False, "note": "x"})
    db.expire_all()
    assert db.get(Item, item.id).status is not ReviewStatus.APPROVED


def test_exclude_rejects_with_the_reason(client, db, item, signed_in_user):
    p = _proposal([item], intent="exclude", reject_reason="not a device", name=item.name)
    r = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": p, "approve": False, "note": "not a device"})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Rejected 1 — not a device"
    db.expire_all()
    fresh = db.get(Item, item.id)
    assert fresh.rejected_at is not None and fresh.reject_reason == "not a device"


def test_missing_information_refuses_the_whole_apply(client, db, item, signed_in_user):
    item.source_tag = "F"; twin = _twin(db, item)
    twin.status = ReviewStatus.MISSING; db.commit()
    r = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": _proposal([item, twin]), "approve": True, "note": "x"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "missing_information_blocks_approval"
    db.expire_all()
    assert db.get(Item, item.id).name != "2x4 LED troffer, 4000K — type F"


def test_stale_version_refuses(client, db, item, signed_in_user):
    p = _proposal([item]); p["versions"][str(item.id)] = item.version + 5
    r = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": p, "approve": True, "note": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale_item_version"
    db.expire_all()
    assert db.get(Item, item.id).name != "2x4 LED troffer, 4000K — type F"


def test_missing_version_for_a_target_refuses_the_whole_apply(client, db, item, signed_in_user):
    p = _proposal([item]); p["versions"] = {}
    r = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": p, "approve": True, "note": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale_item_version"
    db.expire_all()
    assert db.get(Item, item.id).name != "2x4 LED troffer, 4000K — type F"


def test_library_row_written_on_apply_and_upserted(client, db, item, org, signed_in_user):
    item.source_tag = "F"; db.commit()
    client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": _proposal([item]), "approve": False, "note": "x"})
    client.post(f"/api/items/{item.id}/apply-proposal",
                json={"proposal": _proposal([item], name="2x4 LED troffer — type F (rev)", versions={str(item.id): item.version}), "approve": False, "note": "y"})
    rows = db.scalars(select(SymbolResolution).where(SymbolResolution.project_id == item.project_id)).all()
    assert len(rows) == 1 and rows[0].tag == "F" and rows[0].name == "2x4 LED troffer — type F (rev)"


def test_also_matching_counts_the_same_tag_on_other_sheets(client, db, item, project, signed_in_user):
    other = Sheet(project_id=project.id, number="EL101", title="Lighting", discipline="Electrical", revision="",
                  scale="", scale_options=[], plan="", takeoff_id="d", page_index=7)
    db.add(other); db.flush()
    item.source_tag = "F"; _twin(db, item, sheet_id=other.id); _twin(db, item, sheet_id=other.id); db.commit()
    body = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": _proposal([item]), "approve": True, "note": "x"}).json()
    assert body["also_matching"] == {"count": 2, "sheet_numbers": ["EL101"]}


def test_undo_restores_every_item_the_warning_and_removes_the_library_row(client, db, item, signed_in_user):
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION
    db.add(Warning(item_id=item.id, reason=WarningReason.LEGEND, title="t", found="f", why="w", fix="x", where_="E-501"))
    twin = _twin(db, item); db.commit()
    client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": _proposal([item, twin]), "approve": True, "note": "x"})
    client.post(f"/api/projects/{item.project_id}/undo")
    db.expire_all()
    assert db.get(Item, item.id).name == "20A duplex receptacle" and db.get(Item, item.id).status is ReviewStatus.ATTENTION
    assert db.get(Item, twin.id).name == "Luminaire type F"
    assert db.scalars(select(Warning).where(Warning.item_id == item.id)).first() is not None
    assert db.scalars(select(SymbolResolution)).first() is None
    client.post(f"/api/projects/{item.project_id}/redo")
    db.expire_all()
    assert db.get(Item, item.id).status is ReviewStatus.APPROVED
    assert db.scalars(select(SymbolResolution)).first() is not None


def test_undo_reverses_an_exclude(client, db, item, signed_in_user):
    p = _proposal([item], intent="exclude", reject_reason="not a device", name=item.name)
    client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": p, "approve": False, "note": "not a device"})
    client.post(f"/api/projects/{item.project_id}/undo")
    db.expire_all()
    fresh = db.get(Item, item.id)
    assert fresh.rejected_at is None and fresh.reject_reason is None


def test_redo_does_not_delete_a_warning_the_apply_never_cleared(client, db, item, signed_in_user):
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION
    db.add(Warning(item_id=item.id, reason=WarningReason.SCHEDULE_CONFLICT, title="t", found="f", why="w", fix="x", where_="E-501"))
    db.commit()
    p = _proposal([item], schedule_match=None, catalog_id=None, source="typed")
    r = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": p, "approve": False, "note": "x"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Item, item.id).status is ReviewStatus.ATTENTION
    assert db.scalars(select(Warning).where(Warning.item_id == item.id)).first() is not None

    client.post(f"/api/projects/{item.project_id}/undo")
    db.expire_all()
    assert db.scalars(select(Warning).where(Warning.item_id == item.id)).first() is not None

    client.post(f"/api/projects/{item.project_id}/redo")
    db.expire_all()
    assert db.get(Item, item.id).status is ReviewStatus.ATTENTION
    assert db.scalars(select(Warning).where(Warning.item_id == item.id)).first() is not None


def test_redo_after_reapplying_the_same_tag_merges_onto_the_live_row(client, db, item, signed_in_user):
    item.source_tag = "F"; db.commit()
    r1 = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": _proposal([item]), "approve": False, "note": "x"})
    assert r1.status_code == 200, r1.text

    client.post(f"/api/projects/{item.project_id}/undo")
    db.expire_all()
    item = db.get(Item, item.id)
    assert db.scalars(select(SymbolResolution)).first() is None

    r2 = client.post(f"/api/items/{item.id}/apply-proposal",
                      json={"proposal": _proposal([item], name="2x4 LED troffer — type F (again)",
                                                    versions={str(item.id): item.version}),
                            "approve": False, "note": "z"})
    assert r2.status_code == 200, r2.text

    r3 = client.post(f"/api/projects/{item.project_id}/redo")
    assert r3.status_code == 200, r3.text
    rows = db.scalars(select(SymbolResolution).where(SymbolResolution.project_id == item.project_id)).all()
    assert len(rows) == 1
