"""Task 2 of docs/plans/rom-estimate.md -- the ROM aggregation sits next
to the approved one over the same exclusion predicate, and applies no
status filter.

The two numbers are different on purpose. `approved_totals` answers
"what has a person stood behind"; `rom_totals` answers "what would this
job cost if the drawings are read as they stand". Presenting either as
the other is the failure this whole file guards.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.takeoff.models import Item, ItemMarketPrice, ProjectMaterialPrice, ReviewStatus, Sheet
from app.takeoff.totals import approved_totals, countable_items, rom_totals


def _item(project, sheet, *, status=ReviewStatus.READY, cost="100", name="20A duplex receptacle", **kw):
    return Item(
        project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=name,
        system="Power", category="Devices", quantity=1, unit="EA", status=status,
        x=100, y=100, material_cost=Decimal(cost), labor_cost=Decimal("0"),
        labor_hours=Decimal("0"), total_cost=Decimal(cost), **kw,
    )


@pytest.fixture
def mixed_statuses(db, project, sheet):
    """One item in each of the four review labels, all priced $100."""
    for status in (ReviewStatus.READY, ReviewStatus.ATTENTION, ReviewStatus.MISSING, ReviewStatus.APPROVED):
        db.add(_item(project, sheet, status=status, name=f"Item {status.value}"))
    db.flush()
    return project


def test_rom_totals_includes_unapproved_items(db, mixed_statuses):
    assert rom_totals(db, mixed_statuses.id).direct_cost == Decimal("400")


def test_approved_totals_is_unchanged_by_rom_totals(db, mixed_statuses):
    assert approved_totals(db, mixed_statuses.id).approved_count == 1


def test_the_two_aggregations_disagree_on_purpose(db, mixed_statuses):
    """Not a tautology: it is the assertion that nothing has quietly
    made the ROM a view of approved work."""
    assert rom_totals(db, mixed_statuses.id).item_count == 4
    assert approved_totals(db, mixed_statuses.id).approved_count == 1


def test_rom_totals_excludes_rejected(db, project, sheet):
    db.add(_item(project, sheet, rejected_at=datetime.now(timezone.utc)))
    db.flush()
    assert rom_totals(db, project.id).direct_cost == Decimal("0")
    assert rom_totals(db, project.id).item_count == 0


def test_rom_totals_excludes_superseded_sheet(db, project):
    """Review Focus 4 -- an item on a superseded sheet stays out,
    because `countable_items()` excludes it (ROADMAP invariant 2). An
    assumption attached to it changes nothing about that.
    """
    dead = Sheet(project_id=project.id, number="E2.0", title="Power plan — superseded",
                 discipline="Electrical", revision="Rev 1", scale="1/8", scale_options=[], plan="warehouse",
                 superseded_at=datetime.now(timezone.utc))
    db.add(dead)
    db.flush()
    db.add(_item(project, dead))
    db.flush()
    assert rom_totals(db, project.id).direct_cost == Decimal("0")


def test_rom_totals_splits_cost_by_system(db, project, sheet):
    db.add(_item(project, sheet, name="Receptacle"))
    lighting = _item(project, sheet, name="Troffer", cost="250")
    lighting.system = "Lighting"
    db.add(lighting)
    db.flush()
    costs = rom_totals(db, project.id).cost_by_system
    assert costs == {"Power": Decimal("100"), "Lighting": Decimal("250")}


def test_rom_totals_carries_labor_hours_and_the_two_cost_halves(db, project, sheet):
    row = _item(project, sheet, cost="0")
    row.material_cost = Decimal("60")
    row.labor_cost = Decimal("40")
    row.labor_hours = Decimal("1.5")
    row.total_cost = Decimal("100")
    db.add(row)
    db.flush()
    t = rom_totals(db, project.id)
    assert (t.material_cost, t.labor_cost, t.labor_hours, t.direct_cost) == (
        Decimal("60"), Decimal("40"), Decimal("1.5"), Decimal("100"))


def test_rom_totals_counts_unpriced_separately(db, project, sheet):
    db.add(_item(project, sheet, cost="0", name="Unclassified symbol"))
    db.flush()
    t = rom_totals(db, project.id)
    assert t.unpriced_count == 1
    assert t.direct_cost == Decimal("0")


def test_an_item_priced_at_zero_is_not_unpriced(db, project, sheet):
    """A deliberate zero -- an estimator's allowance of nothing, work by
    others -- is a price. Reporting it as unpriced would put "not priced"
    on a line somebody decided, which is the opposite of the truth."""
    row = _item(project, sheet, cost="0", name="Fire alarm rough-in by others")
    db.add(row)
    db.flush()
    db.add(ProjectMaterialPrice(item_id=row.id, price_override=Decimal("0"), source="allowance"))
    db.flush()
    assert rom_totals(db, project.id).unpriced_count == 0


def test_a_market_priced_item_is_not_unpriced(db, project, sheet):
    row = _item(project, sheet, cost="0", name="Troffer")
    db.add(row)
    db.flush()
    db.add(ItemMarketPrice(item_id=row.id, outcome="priced", unit_price=Decimal("0"),
                           fetched_at=datetime.now(timezone.utc)))
    db.flush()
    assert rom_totals(db, project.id).unpriced_count == 0


def test_a_market_lookup_that_found_nothing_leaves_the_item_unpriced(db, project, sheet):
    row = _item(project, sheet, cost="0", name="Switchboard SB-1")
    db.add(row)
    db.flush()
    db.add(ItemMarketPrice(item_id=row.id, outcome="no_match"))
    db.flush()
    assert rom_totals(db, project.id).unpriced_count == 1


def test_rom_totals_is_empty_for_a_project_with_no_items(db, project):
    """Review Focus 1 -- the aggregation itself must not need a row to
    exist. The stated reason is Task 8's job; not dividing by zero is
    this one's."""
    t = rom_totals(db, project.id)
    assert (t.direct_cost, t.item_count, t.unpriced_count) == (Decimal("0"), 0, 0)
    assert t.cost_by_system == {}


def test_rom_totals_honours_an_exclusion_set(db, mixed_statuses, sheet):
    """Task 4 passes scope exclusions in here; the keyword exists from
    the start so there is never a second predicate for it."""
    victim = db.execute(countable_items(mixed_statuses.id)).scalars().first()
    t = rom_totals(db, mixed_statuses.id, exclude={victim.id})
    assert t.direct_cost == Decimal("300")
    assert t.item_count == 3


def test_an_empty_exclusion_set_excludes_nothing(db, mixed_statuses):
    assert rom_totals(db, mixed_statuses.id, exclude=set()).direct_cost == Decimal("400")
