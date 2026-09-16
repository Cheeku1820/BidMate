"""merge_sheet: one sheet, one transaction, never a person's judgment.

The second half of this file (from `_seed` on) is the regression net
that used to live in test_reprocess.py against the /reprocess route.
The route is gone -- a re-run is a worker job now -- but the merge
semantics it proved are unchanged, so those cases run the same
scenarios through `merge_payload` directly, with the estimator's own
actions (approve, edit, delete, undo) still taken over HTTP."""
import base64

from sqlalchemy import select

from app.takeoff import merge
from app.takeoff.ingest import map_payload
from app.takeoff.models import (
    Item,
    ItemEvidenceImage,
    Project,
    ProjectLaborLine,
    ProjectMaterialPrice,
    ReviewStatus,
    Sheet,
    Warning,
)

SHEET = {"id": "0", "number": "E2.1", "takeoff_id": "doc-1", "page": 0, "width_pt": 2000, "height_pt": 1500,
         "unreadable": None, "kind": "plan", "title": "Power plan"}


_WARNING = {"reason": "legend", "title": "Symbol not in legend",
            "found": "E2.1 shows a symbol with no matching legend entry.",
            "why": "The count may include the wrong device type.",
            "fix": "Classify the symbol against the schedule.",
            "where": "E2.1 legend block"}


def _row(tag, name, status="ready", qty=10, warning=None, evidence_png_b64=None):
    return {"name": name, "system": "Power", "category": "Devices", "unit": "ea", "quantity": qty, "status": status,
            "sheet_id": "0", "symbol": "receptacle", "warning": warning, "x": 1000, "y": 750, "placements": [[1000, 750]],
            "tag": tag, "material_cost": 10.0, "labor_hours": 1.0, "labor_cost": 78.0, "total_cost": 88.0,
            "evidence_png_b64": evidence_png_b64}


def _merge(db, project, rows, ai_reading=None):
    mapped = map_payload({"sheets": [SHEET], "items": rows})
    sheets = merge.upsert_sheet_rows(db, project, mapped.sheets)
    return merge.merge_sheet(db, project=project, sheet=sheets["0"], rows=mapped.items, ai_reading=ai_reading)


def test_first_merge_inserts_everything(db, project):
    counts = _merge(db, project, [_row("R", "20A duplex receptacle"), _row("S", "Single-pole switch")])
    assert (counts.added, counts.removed, counts.preserved) == (2, 0, 0)
    assert len(list(db.scalars(select(Item).where(Item.project_id == project.id)))) == 2


def test_an_approved_item_is_never_touched(db, project, dana):
    _merge(db, project, [_row("R", "20A duplex receptacle", qty=14)])
    item = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    item.status = ReviewStatus.APPROVED; item.approved_by_user_id = dana.id; db.flush()
    version = item.version
    counts = _merge(db, project, [_row("R", "Isolated ground receptacle", qty=3)])
    db.refresh(item)
    assert (item.name, item.quantity, item.version) == ("20A duplex receptacle", 14, version)
    assert counts.preserved == 1 and counts.added == 0


def test_an_unapproved_match_is_updated_in_place(db, project):
    _merge(db, project, [_row("R", "20A duplex receptacle")])
    before = db.scalars(select(Item).where(Item.source_tag == "R")).one().id
    counts = _merge(db, project, [_row("R", "Isolated ground receptacle")])
    after = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    assert after.id == before and after.name == "Isolated ground receptacle"
    assert counts.reclassified == 1


def test_a_vanished_unapproved_item_is_removed_and_a_vanished_approved_one_stays(db, project, dana):
    _merge(db, project, [_row("R", "a"), _row("S", "b")])
    s = db.scalars(select(Item).where(Item.source_tag == "S")).one()
    s.status = ReviewStatus.APPROVED; s.approved_by_user_id = dana.id; db.flush()
    counts = _merge(db, project, [])
    left = {i.source_tag for i in db.scalars(select(Item).where(Item.project_id == project.id))}
    assert left == {"S"} and counts.removed == 1 and counts.preserved == 1


def test_merge_touches_only_its_own_sheet(db, project):
    _merge(db, project, [_row("R", "a")])
    other = Sheet(project_id=project.id, number="E2.2", title="t", discipline="Electrical", revision="", scale="",
                  scale_options=[], plan="", takeoff_id="doc-1", page_index=1)
    db.add(other); db.flush()
    db.add(Item(project_id=project.id, sheet_id=other.id, symbol="s", name="on the other sheet", system="Power",
                category="Devices", quantity=1, unit="ea", status=ReviewStatus.READY, x=1, y=1, source_tag="R"))
    db.flush()
    _merge(db, project, [])
    assert db.scalars(select(Item).where(Item.sheet_id == other.id)).one().name == "on the other sheet"


def test_ai_reading_lands_on_the_sheet(db, project):
    _merge(db, project, [], ai_reading={"summary": "one plan", "devices": [{"name": "receptacle", "count": 3}]})
    sheet = db.scalars(select(Sheet).where(Sheet.project_id == project.id)).one()
    assert sheet.ai_reading and sheet.ai_reading["devices"][0]["name"] == "receptacle"


def test_upsert_keeps_a_sheets_id_and_scale_across_reads(db, project):
    first = merge.upsert_sheet_rows(db, project, map_payload({"sheets": [SHEET]}).sheets)["0"]
    first.scale = "1/4\" = 1'"; db.flush()
    again = merge.upsert_sheet_rows(db, project, map_payload({"sheets": [{**SHEET, "title": "Renamed"}]}).sheets)["0"]
    assert again.id == first.id and again.title == "Renamed" and again.scale == "1/4\" = 1'"


def test_two_takeoff_ids_with_the_same_number_are_two_distinct_sheets(db, project, dana):
    """The worker's real path, once the read job lands: takeoff_id is
    the document id, and two different documents can each contain a
    sheet numbered E2.1. merge_payload (and upsert_sheet_rows beneath
    it) must never fall back to matching by number when a row carries
    a non-empty takeoff_id -- the number fallback exists only for rows
    that carry no takeoff id at all (the CLI path), never as a way to
    reconcile two documents' same-numbered sheets, because merge.py
    cannot tell those apart by number alone."""
    payload1 = {"sheets": [{**SHEET, "takeoff_id": "doc-1"}], "items": [_row("R", "a")]}
    payload2 = {"sheets": [{**SHEET, "takeoff_id": "doc-2"}], "items": [_row("R", "b")]}
    merge.merge_payload(db, actor=dana, project=project, payload=payload1)
    merge.merge_payload(db, actor=dana, project=project, payload=payload2)

    sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id)))
    assert len(sheets) == 2
    assert {s.takeoff_id for s in sheets} == {"doc-1", "doc-2"}
    assert len(list(db.scalars(select(Item).where(Item.project_id == project.id)))) == 2


def test_a_deletion_on_a_different_sheet_sharing_a_number_is_not_consumed(db, project, dana):
    """merge_sheet's deleted-key lookup is scoped to {sheet.id:
    sheet.number} -- only this sheet's own id -- so a deletion recorded
    against a different Sheet row is never consumed by this sheet's
    merge, even when that other sheet happens to share the same number
    (two sheets sharing a number is a known latent case until revisions
    land, ROADMAP.md 2.2). Without this scoping, deleting an item on
    one physical sheet could silently suppress the same tag
    reappearing on a different sheet that happens to share its number.
    """
    from app.takeoff.review import delete_item

    a = merge.upsert_sheet_rows(db, project, map_payload({"sheets": [SHEET]}).sheets)["0"]
    b = Sheet(project_id=project.id, number=a.number, title="dup", discipline="Electrical", revision="",
              scale="", scale_options=[], plan="", takeoff_id="doc-2", page_index=1)
    db.add(b); db.flush()
    victim = Item(project_id=project.id, sheet_id=b.id, symbol="s", name="on sheet b", system="Power",
                  category="Devices", quantity=1, unit="ea", status=ReviewStatus.READY, x=1, y=1, source_tag="R")
    db.add(victim); db.flush()
    delete_item(db, dana, victim, victim.version)
    db.flush()

    counts = merge.merge_sheet(
        db, project=project, sheet=a,
        rows=map_payload({"sheets": [SHEET], "items": [_row("R", "a")]}).items,
        ai_reading=None,
    )
    assert (counts.added, counts.skipped_deleted) == (1, 0)


# --- Whole-payload merges: the cases test_reprocess.py used to prove ---


def _payload(items, sheet=None):
    return {"sheets": [sheet or SHEET], "items": items}


def _rerun(db, dana, project, items, sheet=None, **extra):
    """One whole-payload merge, flushed the way a caller's commit would
    leave it (the worker commits per sheet; the old route committed)."""
    counts = merge.merge_payload(db, actor=dana, project=project, payload={**_payload(items, sheet), **extra})
    db.flush()
    return counts


_seed = _rerun


def _item_count(db, project):
    return len(list(db.scalars(select(Item).where(Item.project_id == project.id))))


def _fresh_project(db, org_id, name):
    p = Project(org_id=org_id, name=name, revision_set_label="")
    db.add(p)
    db.flush()
    return p


def test_a_rerun_leaves_an_approved_item_untouched_in_every_field(client, db, project, signed_in_user):
    """The central guarantee, checked on every field a re-run could
    plausibly clobber, not just name and status: quantity, every cost
    figure, the optimistic-concurrency version, and the item's warning."""
    dana = signed_in_user
    _seed(db, dana, project, [_row("R", "20A duplex receptacle", qty=14, warning=_WARNING), _row("S", "Single-pole switch")])
    approved = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    version_before = approved.version
    client.post(f"/api/items/{approved.id}/approve", headers={"If-Match": str(approved.version)})
    db.expire_all()
    approved = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    version_after_approve = approved.version
    assert version_after_approve == version_before + 1
    warning_before = db.scalars(select(Warning).where(Warning.item_id == approved.id)).one()

    _rerun(db, dana, project, [_row("R", "SOMETHING ELSE ENTIRELY", qty=999), _row("S", "Three-way switch")])

    db.expire_all()
    kept = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    assert kept.id == approved.id
    assert (kept.name, kept.status, kept.quantity) == ("20A duplex receptacle", ReviewStatus.APPROVED, 14)
    assert (kept.material_cost, kept.labor_hours, kept.labor_cost, kept.total_cost) == (
        approved.material_cost, approved.labor_hours, approved.labor_cost, approved.total_cost)
    assert kept.version == version_after_approve, "a re-run must not bump an approved item's version"
    warning_after = db.scalars(select(Warning).where(Warning.item_id == kept.id)).one()
    assert (warning_after.id, warning_after.title, warning_after.reason) == (
        warning_before.id, warning_before.title, warning_before.reason)
    assert db.scalars(select(Item).where(Item.source_tag == "S")).one().name == "Three-way switch"


def test_a_rerun_matches_items_sharing_an_empty_tag_positionally(db, project, dana):
    """`source_tag` defaults to "", so every item on a pre-existing
    project collapses onto one merge key. Three untagged items re-run as
    two must end with two items, not four, and the counts must be
    truthful about what changed."""
    _seed(db, dana, project, [_row("", "A"), _row("", "B"), _row("", "C")])
    assert _item_count(db, project) == 3

    counts = _rerun(db, dana, project, [_row("", "X"), _row("", "Y")])
    assert (counts["added"], counts["preserved"], counts["reclassified"], counts["removed"]) == (0, 0, 2, 1)
    assert _item_count(db, project) == 2
    assert {i.name for i in db.scalars(select(Item).where(Item.project_id == project.id))} == {"X", "Y"}


def test_a_rerun_preserves_an_approved_item_sharing_an_empty_tag_with_unapproved_ones(client, db, project, signed_in_user):
    """A re-run that stops reporting the shared empty key at all must
    still keep the approved one and only remove the unapproved one."""
    dana = signed_in_user
    _seed(db, dana, project, [_row("", "Keep me"), _row("", "Drop me")])
    keeper = db.scalars(select(Item).where(Item.name == "Keep me")).one()
    client.post(f"/api/items/{keeper.id}/approve", headers={"If-Match": str(keeper.version)})

    counts = _rerun(db, dana, project, [])
    assert (counts["preserved"], counts["removed"]) == (1, 1)

    db.expire_all()
    remaining = list(db.scalars(select(Item).where(Item.project_id == project.id)))
    assert [(i.id, i.name, i.status) for i in remaining] == [(keeper.id, "Keep me", ReviewStatus.APPROVED)]


def test_a_rerun_matches_the_engine_row_to_the_unapproved_sibling_not_the_approved_one(client, db, project, signed_in_user):
    """A bucket can hold both an approved item and an un-approved one
    sharing an empty tag. Popping whichever sorted first by raw id let
    the approved item consume (and discard) the engine's one incoming
    row -- a silent under-count that turned on a random UUID. Run
    across several fresh projects (fresh ids every time) and require
    the identical outcome every run."""
    dana = signed_in_user
    for n in range(8):
        proj = project if n == 0 else _fresh_project(db, project.org_id, f"Fresh {n}")
        _seed(db, dana, proj, [_row("", "A"), _row("", "B")])
        approved_item = db.scalars(select(Item).where(Item.project_id == proj.id, Item.name == "A")).one()
        approve = client.post(f"/api/items/{approved_item.id}/approve", headers={"If-Match": str(approved_item.version)})
        assert approve.status_code == 200, approve.text

        counts = _rerun(db, dana, proj, [_row("", "ENGINE ROW")])
        assert counts == {"reclassified": 1, "preserved": 1, "added": 0, "removed": 0, "skipped_deleted": 0}, f"run {n}: {counts}"

        db.expire_all()
        rows = list(db.scalars(select(Item).where(Item.project_id == proj.id)))
        assert {i.name for i in rows} == {"A", "ENGINE ROW"}, f"run {n}: {[i.name for i in rows]}"
        kept = next(i for i in rows if i.name == "A")
        assert kept.id == approved_item.id and kept.status is ReviewStatus.APPROVED


def test_a_rerun_lands_every_incoming_row_before_touching_the_approved_one(client, db, project, signed_in_user):
    """Five items share an empty tag, one approved. Three incoming rows
    must all land on the four un-approved siblings, and the approved
    item must survive untouched regardless."""
    dana = signed_in_user
    for n in range(6):
        proj = project if n == 0 else _fresh_project(db, project.org_id, f"Fresh {n}")
        _seed(db, dana, proj, [_row("", "A"), _row("", "B"), _row("", "C"), _row("", "D"), _row("", "E")])
        approved_item = db.scalars(select(Item).where(Item.project_id == proj.id, Item.name == "A")).one()
        client.post(f"/api/items/{approved_item.id}/approve", headers={"If-Match": str(approved_item.version)})

        counts = _rerun(db, dana, proj, [_row("", "X"), _row("", "Y"), _row("", "Z")])
        assert counts == {"reclassified": 3, "preserved": 1, "added": 0, "removed": 1, "skipped_deleted": 0}, f"run {n}: {counts}"

        db.expire_all()
        rows = list(db.scalars(select(Item).where(Item.project_id == proj.id)))
        names = {i.name for i in rows}
        assert {"X", "Y", "Z", "A"} <= names and len(rows) == 4, f"run {n}: {names}"
        kept = next(i for i in rows if i.name == "A")
        assert kept.id == approved_item.id and kept.status is ReviewStatus.APPROVED


def test_a_rerun_keeps_undo_working_for_an_edit_made_before_it(client, db, project, signed_in_user):
    """Updating a matched row in place keeps its id alive, so an earlier
    edit's undo still finds the row it names. `note_apply` is not itself
    reversible, so undo skips past it to that edit."""
    dana = signed_in_user
    _seed(db, dana, project, [_row("R", "20A duplex receptacle")])
    item = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    edit = client.patch(f"/api/items/{item.id}", json={"notes": "check with GC"}, headers={"If-Match": str(item.version)})
    assert edit.status_code == 200, edit.text

    counts = _rerun(db, dana, project, [_row("R", "renamed by the engine")])
    assert counts["reclassified"] == 1
    db.expire_all()
    assert db.scalars(select(Item).where(Item.source_tag == "R")).one().id == item.id

    undo = client.post(f"/api/projects/{project.id}/undo")
    assert undo.status_code == 200 and undo.json()["performed"] is True, undo.text
    db.expire_all()
    assert db.scalars(select(Item).where(Item.source_tag == "R")).one().notes == ""


def test_a_rerun_reports_nothing_reclassified_when_nothing_changed(db, project, dana):
    items = [_row("R", "20A duplex receptacle"), _row("S", "Single-pole switch")]
    _seed(db, dana, project, items)
    counts = _rerun(db, dana, project, items)
    assert (counts["reclassified"], counts["added"], counts["removed"], counts["preserved"]) == (0, 0, 0, 0)


def test_a_rerun_counts_only_the_rows_whose_visible_fields_changed(db, project, dana):
    """One of two matched rows changes name; the other is re-sent with
    only its coordinates moved, which is the geometry agent being
    deterministic rather than a reclassification."""
    _seed(db, dana, project, [_row("R", "20A duplex receptacle"), _row("S", "Single-pole switch")])
    moved = _row("S", "Single-pole switch")
    moved["x"], moved["y"] = 1200, 900
    assert _rerun(db, dana, project, [_row("R", "20A quad receptacle"), moved])["reclassified"] == 1


def test_a_rerun_does_not_resurrect_an_item_the_estimator_deleted(client, db, project, signed_in_user):
    """A deletion is a judgment about the drawing and survives the
    engine seeing the same shape again, exactly as an approval does."""
    dana = signed_in_user
    _seed(db, dana, project, [_row("R", "receptacle"), _row("S", "switch")])
    gone = db.scalars(select(Item).where(Item.source_tag == "S")).one()
    r = client.delete(f"/api/items/{gone.id}", headers={"If-Match": str(gone.version)})
    assert r.status_code == 200, r.text

    counts = _rerun(db, dana, project, [_row("R", "receptacle"), _row("S", "switch")])
    assert (counts["added"], counts["skipped_deleted"]) == (0, 1)
    db.expire_all()
    assert _item_count(db, project) == 1
    assert db.scalars(select(Item).where(Item.source_tag == "S")).one_or_none() is None


def test_delete_then_rerun_then_undo_leaves_exactly_one_item(client, db, project, signed_in_user):
    """The undo after a re-run targets the earlier `delete` and restores
    the original row. Had the merge also re-added the cluster, one
    cluster would end up as two items, both counted in the bid total."""
    dana = signed_in_user
    _seed(db, dana, project, [_row("R", "receptacle"), _row("S", "switch")])
    gone = db.scalars(select(Item).where(Item.source_tag == "S")).one()
    client.delete(f"/api/items/{gone.id}", headers={"If-Match": str(gone.version)})

    _rerun(db, dana, project, [_row("R", "receptacle"), _row("S", "switch")])
    r = client.post(f"/api/projects/{project.id}/undo")
    assert r.status_code == 200 and r.json()["performed"] is True, r.text

    db.expire_all()
    assert len(list(db.scalars(select(Item).where(Item.source_tag == "S")))) == 1
    assert _item_count(db, project) == 2


def test_a_rerun_re_adds_a_deletion_the_estimator_has_undone(client, db, project, signed_in_user):
    """Suppression follows liveness: a deletion that was undone no longer
    says anything about the drawing."""
    dana = signed_in_user
    _seed(db, dana, project, [_row("R", "receptacle"), _row("S", "switch")])
    gone = db.scalars(select(Item).where(Item.source_tag == "S")).one()
    client.delete(f"/api/items/{gone.id}", headers={"If-Match": str(gone.version)})
    client.post(f"/api/projects/{project.id}/undo")

    db.expire_all()
    counts = _rerun(db, dana, project, [_row("R", "receptacle"), _row("S", "switch")])
    assert counts["added"] == 0, "the restored item should be matched, not re-added"
    db.expire_all()
    assert _item_count(db, project) == 2


def test_a_rerun_suppresses_one_row_per_deletion_sharing_a_key(client, db, project, signed_in_user):
    """Deleting one of three untagged items must silence exactly one
    incoming row, not all three."""
    dana = signed_in_user
    _seed(db, dana, project, [_row("", "A"), _row("", "B"), _row("", "C")])
    gone = db.scalars(select(Item).where(Item.name == "B")).one()
    client.delete(f"/api/items/{gone.id}", headers={"If-Match": str(gone.version)})

    _rerun(db, dana, project, [_row("", "A"), _row("", "B"), _row("", "C")])
    db.expire_all()
    assert _item_count(db, project) == 2


def test_a_rerun_sets_evidence_image_on_a_newly_inserted_item(db, project, dana):
    png_b64 = base64.b64encode(b"new-item-png").decode("ascii")
    _seed(db, dana, project, [])
    _rerun(db, dana, project, [_row("R", "20A duplex receptacle", evidence_png_b64=png_b64)])
    item = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    image = db.get(ItemEvidenceImage, item.id)
    assert image is not None and image.png == b"new-item-png"


def test_a_rerun_replaces_evidence_image_on_a_matched_unapproved_item(db, project, dana):
    first_png = base64.b64encode(b"first-run-png").decode("ascii")
    second_png = base64.b64encode(b"second-run-png").decode("ascii")
    _seed(db, dana, project, [_row("R", "20A duplex receptacle", evidence_png_b64=first_png)])
    item_id = db.scalars(select(Item).where(Item.source_tag == "R")).one().id
    _rerun(db, dana, project, [_row("R", "20A duplex receptacle", evidence_png_b64=second_png)])
    image = db.get(ItemEvidenceImage, item_id)
    assert image is not None and image.png == b"second-run-png"


def test_a_rerun_clears_evidence_image_when_the_crop_fails(db, project, dana):
    """A re-run whose crop failed this time must not leave the previous
    run's image standing in for a takeoff it no longer matches."""
    first_png = base64.b64encode(b"first-run-png").decode("ascii")
    _seed(db, dana, project, [_row("R", "20A duplex receptacle", evidence_png_b64=first_png)])
    item_id = db.scalars(select(Item).where(Item.source_tag == "R")).one().id
    _rerun(db, dana, project, [_row("R", "20A duplex receptacle")])
    assert db.get(ItemEvidenceImage, item_id) is None


def test_a_rerun_updates_a_matched_sheets_kind_and_title_but_not_its_scale(db, project, dana):
    """Kind and title are the engine's fields; scale is a person's."""
    _rerun(db, dana, project, [_row("R", "20A duplex receptacle")], sheet={**SHEET, "title": "Electrical", "kind": "plan"})
    sheet = db.scalars(select(Sheet).where(Sheet.project_id == project.id)).one()
    assert (sheet.kind, sheet.title) == ("plan", "Electrical")
    sheet.scale = '1/8" = 1\'-0"'   # as scale.set_scale would leave it
    db.flush()

    _rerun(db, dana, project, [], sheet={**SHEET, "title": "Panel schedules", "kind": "schedule"})
    db.expire_all()
    rows = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id)))
    assert len(rows) == 1, "matched: one row, not a second sheet beside the first"
    assert (rows[0].kind, rows[0].title, rows[0].scale) == ("schedule", "Panel schedules", '1/8" = 1\'-0"')


def test_a_rerun_clears_an_unreadable_reason_the_engine_no_longer_reports(db, project, dana):
    _rerun(db, dana, project, [], sheet={**SHEET, "title": "Scanned sheet", "kind": "other",
                                         "unreadable": "The sheet is a scanned image with no readable text, so it was not counted."})
    _rerun(db, dana, project, [], sheet={**SHEET, "title": "Floor plan - lighting", "kind": "plan"})
    db.expire_all()
    row = db.scalars(select(Sheet).where(Sheet.project_id == project.id)).one()
    assert (row.kind, row.title, row.unreadable_reason) == ("plan", "Floor plan - lighting", "")


def test_a_rerun_updates_pricing_source_and_note(db, project, dana):
    _seed(db, dana, project, [_row("R", "20A duplex receptacle")])
    _rerun(db, dana, project, [_row("R", "20A duplex receptacle")], source="deterministic",
           location_note="National average rate (no local data matched).")
    db.refresh(project)
    assert project.pricing_source == "deterministic"
    assert project.pricing_note == "National average rate (no local data matched)."


def test_a_rerun_drops_pricing_when_it_reclassifies_an_item(client, db, project, signed_in_user):
    """A price belongs to the item as it was classified when someone
    priced it. The pricing rows are keyed on item_id, which survives an
    in-place reclassification, so without this the old money would ride
    along under the new name."""
    dana = signed_in_user
    _seed(db, dana, project, [_row("R", "20A duplex receptacle")])
    item = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    client.patch(f"/api/items/{item.id}/material-price", json={"priceOverride": 15.5, "source": "project_price"})
    assert db.get(ProjectLaborLine, item.id) is not None and db.get(ProjectMaterialPrice, item.id) is not None

    _rerun(db, dana, project, [_row("R", "Isolated ground receptacle")])

    db.expire_all()
    same_item = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    assert same_item.id == item.id and same_item.name == "Isolated ground receptacle"
    assert db.get(ProjectLaborLine, item.id) is None and db.get(ProjectMaterialPrice, item.id) is None


def test_a_rerun_keeps_pricing_when_the_classification_is_unchanged(client, db, project, signed_in_user):
    dana = signed_in_user
    _seed(db, dana, project, [_row("R", "20A duplex receptacle")])
    item = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    client.patch(f"/api/items/{item.id}/material-price", json={"priceOverride": 15.5, "source": "project_price"})

    _rerun(db, dana, project, [_row("R", "20A duplex receptacle", qty=12)])

    db.expire_all()
    assert float(db.get(ProjectLaborLine, item.id).hours_override) == 0.75
    assert float(db.get(ProjectMaterialPrice, item.id).price_override) == 15.5


def test_a_rerun_without_a_source_keeps_the_one_the_project_already_had(db, project, dana):
    """A payload that says nothing about pricing has not repriced
    anything; clearing the flag would flip every labor and material row
    to Missing information without a single figure changing."""
    _seed(db, dana, project, [_row("R", "20A duplex receptacle")])
    _rerun(db, dana, project, [_row("R", "20A duplex receptacle")], source="llm",
           location_note="Rate based on Sacramento, CA area cost data.")
    db.refresh(project)
    assert project.pricing_source == "llm"
    _rerun(db, dana, project, [_row("R", "20A duplex receptacle")])   # no "source"
    db.refresh(project)
    assert project.pricing_source == "llm"


def test_a_rerun_records_one_action_attributed_to_the_actor(db, project, dana):
    """The `note_apply` entry is `merge_payload`'s own, not the old
    route's: one per whole-payload merge, with the actor's name on it."""
    from app.takeoff.models import Action

    _seed(db, dana, project, [_row("R", "receptacle")])
    _rerun(db, dana, project, [_row("R", "x")])
    rows = list(db.scalars(select(Action).where(Action.project_id == project.id, Action.kind == "note_apply")))
    assert len(rows) == 2 and {r.actor_user_id for r in rows} == {dana.id}
