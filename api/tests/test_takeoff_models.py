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
