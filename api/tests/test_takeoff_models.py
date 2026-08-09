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
