from decimal import Decimal

import pytest
from sqlalchemy.exc import DataError, IntegrityError

from app.takeoff.models import Item, Project, ReviewStatus, Sheet, Warning, WarningReason


def test_review_status_has_exactly_four_members():
    assert [s.value for s in ReviewStatus] == ["ready", "attention", "missing", "approved"]


def test_an_invented_status_is_rejected_by_the_database(db, project, sheet):
    # Session.execute() runs a Core insert() against the connection
    # immediately rather than deferring it to flush(), so the invalid-enum
    # error surfaces right here — the insert itself must be inside
    # pytest.raises, not just the flush that follows it.
    with pytest.raises((DataError, IntegrityError)):
        db.execute(
            Item.__table__.insert().values(
                project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="x",
                system="Power", category="Devices", quantity=1, unit="EA", status="in_review",
            )
        )
        db.flush()


def test_a_warning_cannot_be_written_with_a_missing_field(db, project, sheet, item):
    db.add(Warning(item_id=item.id, reason=WarningReason.SCALE, title="Scale needs confirmation",
                   found="two labels", why="lengths may be wrong", fix="select the scale", where_=None))
    with pytest.raises(IntegrityError):
        db.flush()


def test_rejection_is_a_field_not_a_status(db, item):
    assert item.rejected_at is None
    assert hasattr(item, "rejected_by_user_id")


def test_sheet_carries_engine_page_metadata(db, project):
    """The canvas fetches a page image by takeoff_id + page_index, and
    normalizes marker coordinates against the page's point dimensions.
    Without these the ingested sheet renders no image and no markers."""
    sheet = Sheet(
        project_id=project.id, number="E2.1", title="Power plan",
        discipline="Electrical", revision="3", scale="", plan="",
        takeoff_id="tk-abc", page_index=2, width_pt=3024, height_pt=2160,
        unreadable_reason="", ai_reading={"summary": "reads as a power plan"},
    )
    db.add(sheet)
    db.flush()
    assert sheet.takeoff_id == "tk-abc"
    assert sheet.page_index == 2
    assert sheet.width_pt == 3024
    assert sheet.height_pt == 2160
    assert sheet.ai_reading == {"summary": "reads as a power plan"}


def test_sheet_engine_metadata_defaults_are_safe(db, project):
    """A sheet created without engine metadata (any pre-ingest path) is
    still valid -- the migration adds no required column."""
    sheet = Sheet(
        project_id=project.id, number="E1.1", title="Lighting",
        discipline="Electrical", revision="1", scale="", plan="",
    )
    db.add(sheet)
    db.flush()
    assert sheet.takeoff_id == ""
    assert sheet.page_index == 0
    assert sheet.ai_reading is None


def test_item_carries_cost_and_placements(db, project, sheet):
    """The spreadsheet's cost columns and the canvas's multi-placement
    markers both read these. The engine stops at total direct cost --
    there is deliberately no markup column here."""
    item = Item(
        project_id=project.id, sheet_id=sheet.id, symbol="receptacle",
        name="20A duplex receptacle", system="Power", category="Devices",
        quantity=47, unit="ea", status=ReviewStatus.READY,
        material_cost=Decimal("188.00"), labor_hours=Decimal("15.51"),
        labor_cost=Decimal("1209.78"), total_cost=Decimal("1397.78"),
        placements=[[120, 340], [180, 340]], ai_confirmed=True,
    )
    db.add(item)
    db.flush()
    assert item.material_cost == Decimal("188.00")
    assert item.total_cost == Decimal("1397.78")
    assert item.placements == [[120, 340], [180, 340]]
    assert item.ai_confirmed is True


def test_item_evidence_image_cascades_on_item_delete(db, item):
    """The image is a cache of what the drawing showed at that item's
    location, not reviewable state -- deleting the item deletes the
    image with it, same as Warning already does. `item` is the shared
    conftest.py fixture (a real, already-flushed Item row)."""
    from app.takeoff.models import ItemEvidenceImage

    db.add(ItemEvidenceImage(item_id=item.id, png=b"fake-png-bytes"))
    db.commit()

    db.delete(item)
    db.commit()

    assert db.get(ItemEvidenceImage, item.id) is None


def test_item_evidence_image_is_not_in_the_undo_snapshot_types():
    """The undo/snapshot machinery (snapshots._column_snapshot) walks
    every mapped column of Item automatically -- this table must stay
    outside that entirely, or a delete's full-row snapshot would need to
    JSON-encode raw PNG bytes. Nothing about an evidence image is ever
    undone, so it has no business in ITEM_SNAPSHOT_TYPES."""
    from app.takeoff.snapshots import ITEM_SNAPSHOT_TYPES

    assert "evidence_image" not in ITEM_SNAPSHOT_TYPES
    assert "png" not in ITEM_SNAPSHOT_TYPES


def test_project_labor_line_cascades_on_item_delete(db, item):
    from app.takeoff.models import ProjectLaborLine

    db.add(ProjectLaborLine(item_id=item.id, hours_override=1.5))
    db.commit()
    db.delete(item)
    db.commit()
    assert db.get(ProjectLaborLine, item.id) is None


def test_project_material_price_cascades_on_item_delete(db, item):
    from app.takeoff.models import ProjectMaterialPrice

    db.add(ProjectMaterialPrice(item_id=item.id, price_override=12.5, source="project_price"))
    db.commit()
    db.delete(item)
    db.commit()
    assert db.get(ProjectMaterialPrice, item.id) is None


def test_company_material_price_unique_per_org_and_item_name(db, org):
    from sqlalchemy.exc import IntegrityError

    from app.takeoff.models import CompanyMaterialPrice

    db.add(CompanyMaterialPrice(org_id=org.id, item_name="20A duplex receptacle", unit_price=12.0, effective_date="2026-08-01"))
    db.commit()
    db.add(CompanyMaterialPrice(org_id=org.id, item_name="20A duplex receptacle", unit_price=13.0, effective_date="2026-08-15"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_pricing_tables_are_not_in_the_undo_snapshot_types():
    """These are sparse override rows a separate task's own mutation
    endpoints and undo dispatch manage directly (Tasks 4-5) -- they must
    stay outside Item's own delete-undo snapshot the same way
    ItemEvidenceImage does."""
    from app.takeoff.snapshots import ITEM_SNAPSHOT_TYPES

    for leaked in ("hours_override", "crew_journeyman", "price_override", "journeyman_rate"):
        assert leaked not in ITEM_SNAPSHOT_TYPES
