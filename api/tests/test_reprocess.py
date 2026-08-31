"""POST /api/projects/{id}/reprocess -- applying a note and re-running
the engine without discarding a person's judgment.
"""
import base64

from sqlalchemy import select

from app.takeoff.models import Action, Item, ItemEvidenceImage, Note, Project, ReviewStatus, Warning

SHEET = {"id": "tk1:0", "number": "E2.1", "takeoff_id": "tk1", "page": 0,
         "width_pt": 2000, "height_pt": 1500, "unreadable": None, "ai_reading": None}

_WARNING = {"reason": "legend", "title": "Symbol not in legend",
            "found": "E2.1 shows a symbol with no matching legend entry.",
            "why": "The count may include the wrong device type.",
            "fix": "Classify the symbol against the schedule.",
            "where": "E2.1 legend block"}


def _item(tag, name, status="ready", qty=10, warning=None, evidence_png_b64=None):
    return {"name": name, "system": "Power", "category": "Devices", "unit": "ea",
            "quantity": qty, "status": status, "sheet_id": "tk1:0", "symbol": "receptacle",
            "warning": warning, "x": 1000, "y": 750, "placements": [[1000, 750]], "tag": tag,
            "material_cost": 10.0, "labor_hours": 1.0, "labor_cost": 78.0, "total_cost": 88.0,
            "evidence_png_b64": evidence_png_b64}


def _payload(items):
    return {"sheets": [SHEET], "items": items}


def _seed(client, project, items):
    return client.post(f"/api/projects/{project.id}/takeoff",
                       json={"payload": _payload(items), "confirm_replace": True})


def _item_count(db, project):
    return len(list(db.scalars(select(Item).where(Item.project_id == project.id))))


def test_reprocess_leaves_an_approved_item_untouched(client, db, project, signed_in_user):
    """The central guarantee. A note may not overwrite what a person
    approved -- their name is on it. Checks every field a re-run could
    plausibly clobber, not just name and status: quantity, every cost
    figure, the optimistic-concurrency version, and the item's warning."""
    _seed(client, project, [_item("R", "20A duplex receptacle", qty=14, warning=_WARNING),
                            _item("S", "Single-pole switch")])
    approved = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    approved_version_before = approved.version
    client.post(f"/api/items/{approved.id}/approve", headers={"If-Match": str(approved.version)})
    db.expire_all()
    approved = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    version_after_approve = approved.version
    assert version_after_approve == approved_version_before + 1
    warning_before = db.scalars(select(Warning).where(Warning.item_id == approved.id)).one()

    r = client.post(f"/api/projects/{project.id}/reprocess",
                    json={"payload": _payload([_item("R", "SOMETHING ELSE ENTIRELY", qty=999),
                                               _item("S", "Three-way switch")])})
    assert r.status_code == 200, r.text

    db.expire_all()
    kept = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    assert kept.id == approved.id
    assert kept.name == "20A duplex receptacle"
    assert kept.status is ReviewStatus.APPROVED
    assert kept.quantity == 14
    assert kept.material_cost == approved.material_cost
    assert kept.labor_hours == approved.labor_hours
    assert kept.labor_cost == approved.labor_cost
    assert kept.total_cost == approved.total_cost
    assert kept.version == version_after_approve, "a re-run must not bump an approved item's version"

    warning_after = db.scalars(select(Warning).where(Warning.item_id == kept.id)).one()
    assert warning_after.id == warning_before.id
    assert warning_after.title == warning_before.title
    assert warning_after.reason == warning_before.reason

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
    r = client.post(f"/api/projects/{project.id}/reprocess", json={"payload": _payload([_item("R", "receptacle")])})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["removed"] == 1
    db.expire_all()
    assert db.scalars(select(Item).where(Item.source_tag == "S")).one_or_none() is None
    assert _item_count(db, project) == 1


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


def test_reprocess_is_org_scoped(client, db, other_org_project, signed_in_user):
    r = client.post(f"/api/projects/{other_org_project.id}/reprocess", json={"payload": _payload([])})
    assert r.status_code == 404
    # A rival-org 404 must leave the other org's project exactly as it
    # was, not just refuse to answer -- confirmed against the database,
    # not the fixture's in-session belief about it.
    assert _item_count(db, other_org_project) == 0
    assert list(db.scalars(select(Action).where(Action.project_id == other_org_project.id))) == []


def test_reprocess_matches_items_sharing_an_empty_tag_positionally(client, db, project, signed_in_user):
    """The central fix in this round. `source_tag` defaults to "", so
    every item on a pre-existing project collapses onto one merge key.
    Three untagged items re-run as two must end with two items, not
    four, and the reported counts must be truthful about what changed."""
    _seed(client, project, [_item("", "A"), _item("", "B"), _item("", "C")])
    assert _item_count(db, project) == 3

    r = client.post(f"/api/projects/{project.id}/reprocess",
                    json={"payload": _payload([_item("", "X"), _item("", "Y")])})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == 0
    assert body["preserved"] == 0
    assert body["reclassified"] == 2
    assert body["removed"] == 1

    db.expire_all()
    assert _item_count(db, project) == 2
    names = {i.name for i in db.scalars(select(Item).where(Item.project_id == project.id))}
    assert names == {"X", "Y"}


def test_reprocess_preserves_an_approved_item_sharing_an_empty_tag_with_unapproved_ones(
    client, db, project, signed_in_user
):
    """An approved and an unapproved item can collapse onto the same
    empty-tag key. A re-run that stops reporting that key at all must
    still keep the approved one and only remove the unapproved one."""
    _seed(client, project, [_item("", "Keep me"), _item("", "Drop me")])
    items = list(db.scalars(select(Item).where(Item.project_id == project.id)))
    keeper, dropped = items[0], items[1]
    client.post(f"/api/items/{keeper.id}/approve", headers={"If-Match": str(keeper.version)})

    body = client.post(f"/api/projects/{project.id}/reprocess", json={"payload": _payload([])}).json()
    assert body["preserved"] == 1
    assert body["removed"] == 1

    db.expire_all()
    remaining = list(db.scalars(select(Item).where(Item.project_id == project.id)))
    assert len(remaining) == 1
    assert remaining[0].id == keeper.id
    assert remaining[0].name == "Keep me"
    assert remaining[0].status is ReviewStatus.APPROVED


def _fresh_project(db, org_id, name):
    p = Project(org_id=org_id, name=name, revision_set_label="")
    db.add(p)
    db.flush()
    return p


def test_reprocess_matches_the_engine_row_to_the_unapproved_sibling_not_the_approved_one(
    client, db, project, signed_in_user
):
    """Round 2's finding. A bucket can hold both an approved item and an
    un-approved one sharing an empty tag. Popping whichever sorts first
    by raw `Item.id` meant the approved item could randomly consume the
    engine's one incoming row, discarding it, instead of it landing on
    the un-approved sibling that could actually accept it -- a silent
    under-count that depended on nothing but a random UUID.

    Run across several fresh projects (fresh random ids every time) and
    require the identical outcome every run, so a reintroduced ordering
    bug fails the suite instead of passing on whichever half of the
    coin flips its way.
    """
    for n in range(8):
        proj = project if n == 0 else _fresh_project(db, project.org_id, f"Fresh {n}")
        _seed(client, proj, [_item("", "A"), _item("", "B")])
        seeded = list(db.scalars(select(Item).where(Item.project_id == proj.id)))
        approved_item = next(i for i in seeded if i.name == "A")
        approve = client.post(f"/api/items/{approved_item.id}/approve",
                              headers={"If-Match": str(approved_item.version)})
        assert approve.status_code == 200, approve.text

        r = client.post(f"/api/projects/{proj.id}/reprocess",
                        json={"payload": _payload([_item("", "ENGINE ROW")])})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"reclassified": 1, "preserved": 1, "added": 0, "removed": 0}, f"run {n}: {body}"

        db.expire_all()
        rows = list(db.scalars(select(Item).where(Item.project_id == proj.id)))
        assert {i.name for i in rows} == {"A", "ENGINE ROW"}, f"run {n}: {[i.name for i in rows]}"
        kept = next(i for i in rows if i.name == "A")
        assert kept.id == approved_item.id
        assert kept.status is ReviewStatus.APPROVED


def test_reprocess_lands_every_incoming_row_before_touching_the_approved_one(
    client, db, project, signed_in_user
):
    """Five items share an empty tag, one of them approved. Three
    incoming rows must all land on the four un-approved siblings --
    none discarded because the approved item happened to sort first --
    and the approved item must survive untouched regardless."""
    for n in range(6):
        proj = project if n == 0 else _fresh_project(db, project.org_id, f"Fresh {n}")
        _seed(client, proj, [_item("", "A"), _item("", "B"), _item("", "C"),
                             _item("", "D"), _item("", "E")])
        seeded = list(db.scalars(select(Item).where(Item.project_id == proj.id)))
        approved_item = next(i for i in seeded if i.name == "A")
        client.post(f"/api/items/{approved_item.id}/approve",
                   headers={"If-Match": str(approved_item.version)})

        r = client.post(f"/api/projects/{proj.id}/reprocess",
                        json={"payload": _payload([_item("", "X"), _item("", "Y"), _item("", "Z")])})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"reclassified": 3, "preserved": 1, "added": 0, "removed": 1}, f"run {n}: {body}"

        db.expire_all()
        rows = list(db.scalars(select(Item).where(Item.project_id == proj.id)))
        names = {i.name for i in rows}
        assert {"X", "Y", "Z"} <= names, f"run {n}: engine rows did not all land: {names}"
        assert "A" in names, f"run {n}: the approved item disappeared: {names}"
        kept = next(i for i in rows if i.name == "A")
        assert kept.id == approved_item.id
        assert kept.status is ReviewStatus.APPROVED
        assert len(rows) == 4


def test_reprocess_keeps_undo_working_for_an_edit_made_before_it(client, db, project, signed_in_user):
    """The second fix in this round. Deleting and re-inserting a matched
    item under a new id orphaned any earlier action naming the old id --
    `note_apply` is not itself reversible, so undo skips past it to that
    earlier edit, which then 409s forever because the id it names is
    gone. Updating the row in place keeps the id alive."""
    _seed(client, project, [_item("R", "20A duplex receptacle")])
    item = db.scalars(select(Item).where(Item.source_tag == "R")).one()

    edit = client.patch(f"/api/items/{item.id}", json={"notes": "check with GC"},
                        headers={"If-Match": str(item.version)})
    assert edit.status_code == 200, edit.text

    r = client.post(f"/api/projects/{project.id}/reprocess",
                    json={"payload": _payload([_item("R", "renamed by the engine")])})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reclassified"] == 1

    db.expire_all()
    reclassified = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    assert reclassified.id == item.id, "the item's id must survive an in-place update"

    undo = client.post(f"/api/projects/{project.id}/undo")
    assert undo.status_code == 200, undo.text
    assert undo.json()["performed"] is True

    db.expire_all()
    restored = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    assert restored.notes == "", "undo should reverse the edit, not 409 on a vanished id"


def test_reprocess_only_stamps_context_notes_as_applied(client, db, project, signed_in_user):
    """`mark_applied` must only touch notes the engine actually consumed.
    A reference note is documentation an estimator wrote for themselves;
    stamping it applied would claim it changed something it never fed
    into the run."""
    _seed(client, project, [_item("R", "receptacle")])

    reference = client.post(f"/api/projects/{project.id}/notes",
                            json={"title": "FYI", "body": "Existing panel to remain",
                                  "category": "existing_condition", "usage": "reference"}).json()
    context = client.post(f"/api/projects/{project.id}/notes",
                          json={"title": "Type F everywhere", "body": "All fixtures in this wing are type F",
                                "category": "existing_condition", "usage": "context"}).json()

    client.post(f"/api/projects/{project.id}/reprocess", json={"payload": _payload([_item("R", "x")])})

    notes = {n["id"]: n for n in client.get(f"/api/projects/{project.id}/notes").json()}
    assert notes[reference["id"]]["applied_at"] is None
    assert notes[context["id"]]["applied_at"] is not None


def test_reprocess_reports_nothing_reclassified_when_nothing_changed(client, db, project, signed_in_user):
    """`reclassified` counts rows that changed, not rows that were
    touched. In the documented dev mode (no `ANTHROPIC_API_KEY`) notes
    cannot affect classification at all, so a re-run there is a no-op --
    and reporting "300 items reclassified" for it is a lie about the
    only number this screen exists to state."""
    items = [_item("R", "20A duplex receptacle"), _item("S", "Single-pole switch")]
    _seed(client, project, items)

    body = client.post(f"/api/projects/{project.id}/reprocess", json={"payload": _payload(items)}).json()
    assert body["reclassified"] == 0
    assert body["added"] == 0
    assert body["removed"] == 0
    assert body["preserved"] == 0


def test_reprocess_counts_only_the_rows_whose_visible_fields_changed(client, db, project, signed_in_user):
    """One of two matched rows changes name; the other is re-sent
    identically except for coordinates, which is the geometry agent
    being deterministic rather than a reclassification."""
    _seed(client, project, [_item("R", "20A duplex receptacle"), _item("S", "Single-pole switch")])

    moved = _item("S", "Single-pole switch")
    moved["x"], moved["y"] = 1200, 900
    body = client.post(
        f"/api/projects/{project.id}/reprocess",
        json={"payload": _payload([_item("R", "20A quad receptacle"), moved])},
    ).json()
    assert body["reclassified"] == 1


def test_reprocess_does_not_resurrect_an_item_the_estimator_deleted(client, db, project, signed_in_user):
    """A deletion is a judgment about the drawing -- "that device is
    existing to remain" -- and survives the engine seeing the same shape
    again, exactly as an approval does."""
    _seed(client, project, [_item("R", "receptacle"), _item("S", "switch")])
    gone = db.scalars(select(Item).where(Item.source_tag == "S")).one()
    r = client.delete(f"/api/items/{gone.id}", headers={"If-Match": str(gone.version)})
    assert r.status_code == 200, r.text

    body = client.post(f"/api/projects/{project.id}/reprocess",
                       json={"payload": _payload([_item("R", "receptacle"), _item("S", "switch")])}).json()
    assert body["added"] == 0
    db.expire_all()
    assert _item_count(db, project) == 1
    assert db.scalars(select(Item).where(Item.source_tag == "S")).one_or_none() is None


def test_delete_then_reprocess_then_undo_leaves_exactly_one_item(client, db, project, signed_in_user):
    """The duplicate-count bug. `note_apply` is not undoable, so the undo
    after a re-run targets the earlier `delete` and restores the original
    row unconditionally. If the merge had also re-added the cluster, one
    cluster would end up as two items -- both counted in the bid total,
    with nothing on screen saying why."""
    _seed(client, project, [_item("R", "receptacle"), _item("S", "switch")])
    gone = db.scalars(select(Item).where(Item.source_tag == "S")).one()
    client.delete(f"/api/items/{gone.id}", headers={"If-Match": str(gone.version)})

    client.post(f"/api/projects/{project.id}/reprocess",
                json={"payload": _payload([_item("R", "receptacle"), _item("S", "switch")])})
    r = client.post(f"/api/projects/{project.id}/undo")
    assert r.status_code == 200, r.text
    assert r.json()["performed"] is True

    db.expire_all()
    assert len(list(db.scalars(select(Item).where(Item.source_tag == "S")))) == 1
    assert _item_count(db, project) == 2


def test_reprocess_re_adds_a_deletion_the_estimator_has_undone(client, db, project, signed_in_user):
    """Suppression follows liveness, not the mere existence of a delete
    action: an estimator who deleted an item and then undid that has
    said the item belongs, so a later re-run must treat the cluster
    normally again."""
    _seed(client, project, [_item("R", "receptacle"), _item("S", "switch")])
    gone = db.scalars(select(Item).where(Item.source_tag == "S")).one()
    client.delete(f"/api/items/{gone.id}", headers={"If-Match": str(gone.version)})
    client.post(f"/api/projects/{project.id}/undo")

    db.expire_all()
    body = client.post(f"/api/projects/{project.id}/reprocess",
                       json={"payload": _payload([_item("R", "receptacle"), _item("S", "switch")])}).json()
    assert body["added"] == 0, "the restored item should be matched, not re-added"
    db.expire_all()
    assert _item_count(db, project) == 2


def test_reprocess_suppresses_one_row_per_deletion_sharing_a_key(client, db, project, signed_in_user):
    """Merge keys are not unique -- every item ingested before migration
    0012 carries an empty `source_tag`. Deleting one of three untagged
    items on a sheet must silence exactly one incoming row, not all
    three."""
    _seed(client, project, [_item("", "A"), _item("", "B"), _item("", "C")])
    gone = db.scalars(select(Item).where(Item.name == "B")).one()
    client.delete(f"/api/items/{gone.id}", headers={"If-Match": str(gone.version)})

    client.post(f"/api/projects/{project.id}/reprocess",
                json={"payload": _payload([_item("", "A"), _item("", "B"), _item("", "C")])})
    db.expire_all()
    assert _item_count(db, project) == 2


def test_reprocess_sets_evidence_image_on_a_newly_inserted_item(client, db, project, signed_in_user):
    png_b64 = base64.b64encode(b"new-item-png").decode("ascii")
    _seed(client, project, [])
    client.post(f"/api/projects/{project.id}/reprocess",
                json={"payload": _payload([_item("R", "20A duplex receptacle", evidence_png_b64=png_b64)])})
    item = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    image = db.get(ItemEvidenceImage, item.id)
    assert image is not None and image.png == b"new-item-png"


def test_reprocess_replaces_evidence_image_on_a_matched_unapproved_item(client, db, project, signed_in_user):
    first_png = base64.b64encode(b"first-run-png").decode("ascii")
    second_png = base64.b64encode(b"second-run-png").decode("ascii")
    _seed(client, project, [_item("R", "20A duplex receptacle", evidence_png_b64=first_png)])
    item_before = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    item_id = item_before.id

    client.post(f"/api/projects/{project.id}/reprocess",
                json={"payload": _payload([_item("R", "20A duplex receptacle", evidence_png_b64=second_png)])})

    image = db.get(ItemEvidenceImage, item_id)
    assert image is not None and image.png == b"second-run-png"


def test_reprocess_clears_evidence_image_when_a_rerun_crop_fails(client, db, project, signed_in_user):
    """A re-run whose crop generation failed this time must not leave the
    previous run's image standing in for a takeoff it no longer matches."""
    first_png = base64.b64encode(b"first-run-png").decode("ascii")
    _seed(client, project, [_item("R", "20A duplex receptacle", evidence_png_b64=first_png)])
    item_before = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    item_id = item_before.id

    client.post(f"/api/projects/{project.id}/reprocess",
                json={"payload": _payload([_item("R", "20A duplex receptacle")])})  # no evidence_png_b64

    assert db.get(ItemEvidenceImage, item_id) is None
