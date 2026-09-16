"""merge_sheet: one sheet, one transaction, never a person's judgment."""
from sqlalchemy import select

from app.takeoff import merge
from app.takeoff.ingest import map_payload
from app.takeoff.models import Item, ReviewStatus, Sheet, Warning

SHEET = {"id": "0", "number": "E2.1", "takeoff_id": "doc-1", "page": 0, "width_pt": 2000, "height_pt": 1500,
         "unreadable": None, "kind": "plan", "title": "Power plan"}


def _row(tag, name, status="ready", qty=10):
    return {"name": name, "system": "Power", "category": "Devices", "unit": "ea", "quantity": qty, "status": status,
            "sheet_id": "0", "symbol": "receptacle", "warning": None, "x": 1000, "y": 750, "placements": [[1000, 750]],
            "tag": tag, "material_cost": 10.0, "labor_hours": 1.0, "labor_cost": 78.0, "total_cost": 88.0}


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
    a non-empty takeoff_id -- a number fallback lives only in the
    interim /reprocess bridge (reprocess.py's _strip_takeoff_id), never
    in merge.py itself, precisely because merge.py cannot tell two
    documents' same-numbered sheets apart by number alone."""
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
