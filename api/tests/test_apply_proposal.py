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
    """A two-row cluster, no count stated: both rows renamed and approved
    in one action, each keeping its own count (14 + 1), and the label
    names the device count -- 15 -- not the row count."""
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION
    db.add(Warning(item_id=item.id, reason=WarningReason.LEGEND, title="Fixture type needs confirmation",
                   found="f", why="w", fix="x", where_="E-501"))
    twin = _twin(db, item); db.commit()
    r = client.post(f"/api/items/{item.id}/apply-proposal",
                    json={"proposal": _proposal([item, twin]), "approve": True, "note": "type F per E-501"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "Approved 15 × 2x4 LED troffer, 4000K — type F"
    assert body["also_matching"] == {"count": 0, "sheet_numbers": []}
    db.expire_all()
    for it, qty in ((item, 14), (twin, 1)):
        fresh = db.get(Item, it.id)
        assert fresh.name == "2x4 LED troffer, 4000K — type F" and float(fresh.quantity) == qty
        assert fresh.status is ReviewStatus.APPROVED and fresh.resolve_note == "type F per E-501"
    assert db.scalars(select(Warning).where(Warning.item_id == item.id)).first() is None
    actions = db.scalars(select(Action).where(Action.project_id == item.project_id)).all()
    assert [a.kind for a in actions] == ["resolve"]
    assert len(actions[0].before["items"]) == 2 and actions[0].note == "type F per E-501"


def test_a_stated_count_lands_on_a_one_row_cluster_and_names_the_label(client, db, item, signed_in_user):
    """The engine's shape: one row per (sheet, tag) with quantity = the
    placement count. "28 of these" corrects that one row's count, and
    the label says 28 -- the figure the card and the statement show."""
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION; item.quantity = 30; db.commit()
    r = client.post(f"/api/items/{item.id}/apply-proposal",
                    json={"proposal": _proposal([item], quantity=28), "approve": True, "note": "28 of these, type F"})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Approved 28 × 2x4 LED troffer, 4000K — type F"
    db.expire_all()
    fresh = db.get(Item, item.id)
    assert float(fresh.quantity) == 28 and fresh.status is ReviewStatus.APPROVED


def test_a_stated_count_is_refused_on_a_multi_row_cluster(client, db, item, signed_in_user):
    """Writing one count to every row would multiply it (28 on two rows
    is 56 in the drawer). Refused with the row count and where to fix
    it; nothing written."""
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION
    twin = _twin(db, item); db.commit()
    r = client.post(f"/api/items/{item.id}/apply-proposal",
                    json={"proposal": _proposal([item, twin], quantity=28), "approve": True, "note": "28 of these"})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == {"code": "quantity_needs_one_row",
                                  "message": "This tag is counted as 2 rows on this sheet — correct the count on each row."}
    db.expire_all()
    for it, qty in ((item, 14), (twin, 1)):
        fresh = db.get(Item, it.id)
        assert float(fresh.quantity) == qty and fresh.status is not ReviewStatus.APPROVED
        assert fresh.name != "2x4 LED troffer, 4000K — type F"
    assert db.scalars(select(Action)).first() is None


def test_confirm_without_approve_leaves_status_alone(client, db, item, signed_in_user):
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION; db.commit()
    client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": _proposal([item]), "approve": False, "note": "x"})
    db.expire_all()
    assert db.get(Item, item.id).status is not ReviewStatus.APPROVED


def test_exclude_rejects_with_the_reason(client, db, item, signed_in_user):
    p = _proposal([item], intent="exclude", reject_reason="not a device", name=item.name)
    r = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": p, "approve": False, "note": "not a device"})
    assert r.status_code == 200, r.text
    # The device count (the fixture's quantity), not the row count.
    assert r.json()["label"] == "Rejected 14 — not a device"
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


def test_a_scale_warning_on_the_anchor_survives_an_apply_and_its_undo_redo(client, db, item, signed_in_user):
    """Naming the item resolves the classifier's warnings (legend,
    schedule conflict), never the sheet's scale warning -- deleting that
    would leave a Missing information row with nothing explaining why.
    Undo puts the legend warning back without duplicating the scale
    one; redo removes only the legend warning again."""
    item.source_tag = "F"; item.status = ReviewStatus.MISSING
    db.add(Warning(item_id=item.id, reason=WarningReason.SCALE, title="Scale needs confirmation",
                   found="f", why="w", fix="x", where_="E2.1"))
    db.add(Warning(item_id=item.id, reason=WarningReason.LEGEND, title="Symbol not in legend",
                   found="f", why="w", fix="x", where_="E-501"))
    db.commit()

    def reasons():
        db.expire_all()
        return sorted(w.reason.value for w in db.scalars(select(Warning).where(Warning.item_id == item.id)))

    r = client.post(f"/api/items/{item.id}/apply-proposal",
                    json={"proposal": _proposal([item], catalog_id="luminaire_troffer"), "approve": False, "note": "type F"})
    assert r.status_code == 200, r.text
    assert reasons() == ["scale"]
    assert db.get(Item, item.id).status is ReviewStatus.MISSING

    client.post(f"/api/projects/{item.project_id}/undo")
    assert reasons() == ["legend", "scale"]

    client.post(f"/api/projects/{item.project_id}/redo")
    assert reasons() == ["scale"]


@pytest.mark.parametrize("over, code", [
    ({"name": "   "}, "field_cannot_be_empty"),
    ({"system": ""}, "field_cannot_be_empty"),
    ({"category": " "}, "field_cannot_be_empty"),
    ({"quantity": -3}, "invalid_quantity"),
    ({"quantity": 10**12}, "invalid_quantity"),
    ({"system": "Plumbing"}, "invalid_system"),
    ({"category": "Receptacles"}, "invalid_category"),
])
def test_apply_refuses_what_an_edit_would_refuse(client, db, item, signed_in_user, over, code):
    """The same rules PATCH /items/{id} applies, with a code and message
    the panel's error banner shows -- this route writes the same
    columns from a client-supplied body, so it is not a way around them."""
    item.source_tag = "F"; db.commit()
    r = client.post(f"/api/items/{item.id}/apply-proposal",
                    json={"proposal": _proposal([item], **over), "approve": True, "note": "x"})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == code and detail["message"]
    db.expire_all()
    fresh = db.get(Item, item.id)
    assert fresh.name == "20A duplex receptacle" and fresh.status is ReviewStatus.READY
    assert db.scalars(select(Action)).first() is None


def test_apply_refuses_a_name_wider_than_its_column(client, db, item, signed_in_user):
    r = client.post(f"/api/items/{item.id}/apply-proposal",
                    json={"proposal": _proposal([item], name="x" * 301), "approve": False, "note": "x"})
    assert r.status_code == 422


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


def test_a_typed_reading_clears_the_legend_warning_and_undo_restores_it(client, db, item, signed_in_user):
    """"Symbol not in legend -- assign a classification" is answered by
    any reading, key or no key: the estimator has just assigned one in
    their own words. The item moves to Ready to review; undo puts the
    warning and the status back; redo clears it again."""
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION
    db.add(Warning(item_id=item.id, reason=WarningReason.LEGEND, title="Symbol not in legend",
                   found="f", why="w", fix="x", where_="E-501"))
    db.commit()
    p = _proposal([item], schedule_match=None, catalog_id=None, source="typed", name="patient headwall")
    r = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": p, "approve": False, "note": "patient headwall"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.scalars(select(Warning).where(Warning.item_id == item.id)).first() is None
    assert db.get(Item, item.id).status is ReviewStatus.READY

    client.post(f"/api/projects/{item.project_id}/undo")
    db.expire_all()
    restored = db.scalars(select(Warning).where(Warning.item_id == item.id)).all()
    assert [w.reason for w in restored] == [WarningReason.LEGEND]
    assert db.get(Item, item.id).status is ReviewStatus.ATTENTION

    client.post(f"/api/projects/{item.project_id}/redo")
    db.expire_all()
    assert db.scalars(select(Warning).where(Warning.item_id == item.id)).first() is None
    assert db.get(Item, item.id).status is ReviewStatus.READY


def test_a_typed_reading_keeps_a_schedule_conflict_and_needs_attention(client, db, item, signed_in_user):
    """A schedule conflict is not answered by words alone -- it clears
    only once the reading is matched to the schedule or the catalog, so
    a typed reading leaves it, and the item, at Needs attention."""
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION
    db.add(Warning(item_id=item.id, reason=WarningReason.LEGEND, title="l", found="f", why="w", fix="x", where_="E-501"))
    db.add(Warning(item_id=item.id, reason=WarningReason.SCHEDULE_CONFLICT, title="s", found="f", why="w", fix="x", where_="E-501"))
    db.commit()
    p = _proposal([item], schedule_match=None, catalog_id=None, source="typed")
    r = client.post(f"/api/items/{item.id}/apply-proposal", json={"proposal": p, "approve": False, "note": "x"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert [w.reason for w in db.scalars(select(Warning).where(Warning.item_id == item.id))] == [WarningReason.SCHEDULE_CONFLICT]
    assert db.get(Item, item.id).status is ReviewStatus.ATTENTION


def test_targets_outside_the_anchors_cluster_are_refused(client, db, item, project, signed_in_user):
    """`target_item_ids` is verified against the cluster the server
    computes for the anchor now: the same tag on another sheet, or
    another tag on this sheet, is refused before anything is locked --
    nothing written, no action recorded."""
    other = Sheet(project_id=project.id, number="EL101", title="Lighting", discipline="Electrical", revision="",
                  scale="", scale_options=[], plan="", takeoff_id="d", page_index=7)
    db.add(other); db.flush()
    item.source_tag = "F"; item.status = ReviewStatus.ATTENTION
    elsewhere = _twin(db, item, sheet_id=other.id)          # same tag, another sheet
    other_tag = _twin(db, item, tag="G")                     # another tag, this sheet
    db.commit()
    for stranger in (elsewhere, other_tag):
        r = client.post(f"/api/items/{item.id}/apply-proposal",
                        json={"proposal": _proposal([item, stranger]), "approve": True, "note": "x"})
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == {"code": "targets_not_in_cluster",
                                      "message": "Those items aren't the same symbol on this sheet — reload and try again."}
    db.expire_all()
    for it in (item, elsewhere, other_tag):
        fresh = db.get(Item, it.id)
        assert fresh.name != "2x4 LED troffer, 4000K — type F" and fresh.status is not ReviewStatus.APPROVED
    assert db.scalars(select(Action)).first() is None


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
