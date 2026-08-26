from datetime import datetime, timezone
from decimal import Decimal

from app.takeoff.models import Item, ReviewStatus
from app.takeoff.totals import approved_totals


def _item(project, sheet, **kw):
    base = dict(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="x",
                system="Power", category="Devices", quantity=Decimal("10"), unit="EA",
                status=ReviewStatus.APPROVED)
    base.update(kw)
    return Item(**base)


def test_totals_count_only_approved_items(db, project, sheet):
    db.add(_item(project, sheet))
    db.add(_item(project, sheet, status=ReviewStatus.READY))
    db.flush()

    result = approved_totals(db, project.id)

    assert result.approved_units == Decimal("10")
    assert result.approved_count == 1
    assert result.remaining_count == 1


def test_superseded_sheets_never_contribute(db, project, sheet):
    db.add(_item(project, sheet))
    db.flush()
    sheet.superseded_at = datetime.now(timezone.utc)
    db.flush()

    assert approved_totals(db, project.id).approved_units == Decimal("0")


def test_rejected_items_never_contribute(db, project, sheet, dana):
    db.add(_item(project, sheet, rejected_at=datetime.now(timezone.utc), rejected_by_user_id=dana.id))
    db.flush()

    assert approved_totals(db, project.id).approved_units == Decimal("0")


def test_totals_group_by_system(db, project, sheet):
    db.add(_item(project, sheet, system="Power", quantity=Decimal("14")))
    db.add(_item(project, sheet, system="Lighting", quantity=Decimal("38")))
    db.flush()

    by_system = approved_totals(db, project.id).by_system

    assert by_system == {"Power": Decimal("14"), "Lighting": Decimal("38")}


def test_fractional_quantity_survives_aggregation_as_decimal(db, project, sheet):
    # 10.33 is not exactly representable in binary floating point, unlike
    # the whole-number quantities the other tests use (Decimal("14") == 14.0
    # is True, so those tests can't tell a Decimal from a float). Equality
    # alone isn't enough either -- a float that happened to compare equal
    # would still be the wrong type to hand to something that prices the
    # number -- so this asserts both the exact value and the type.
    db.add(_item(project, sheet, system="Power", quantity=Decimal("10.33")))
    db.flush()

    result = approved_totals(db, project.id)

    assert result.approved_units == Decimal("10.33")
    assert isinstance(result.approved_units, Decimal)
    assert result.by_system["Power"] == Decimal("10.33")
    assert isinstance(result.by_system["Power"], Decimal)
