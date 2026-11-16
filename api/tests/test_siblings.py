"""Task 5 of docs/plans/estimate-without-asking.md -- the base every
guess is relative to.

The spec's hardest rule about guessing: **every guessed quantity is
relative to what this project itself counted, never an absolute
constant.** One number cannot serve both a single-line diagram and a
40,000 sf floor plan, and a constant degrades dishonestly -- a project
where nothing counted would still produce a number. The relative form
degrades correctly: nothing counted means nothing guessed.

`sibling_stats` is pure and database-free, in the shape of
`schedule/plan.py`, so the whole rule is testable on plain data.
"""
from decimal import Decimal

from app.estimate.siblings import MIN_SAMPLE, plan_sheet_counts, sibling_stats
from app.takeoff.models import Item, ReviewStatus, Sheet


def _sheet(db, project, *, number, kind="plan", superseded_at=None):
    s = Sheet(project_id=project.id, number=number, title="Power plan", discipline="Electrical",
              revision="Rev 1", scale="", scale_options=[], plan="", kind=kind,
              superseded_at=superseded_at)
    db.add(s)
    db.flush()
    return s


def _item(db, project, sheet, *, quantity=10, status=ReviewStatus.READY, unit="EA", **kw):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle",
             name="20A duplex receptacle", system="Power", category="Devices",
             quantity=Decimal(quantity), unit=unit, status=status, **kw)
    db.add(i)
    db.flush()
    return i


# --- the pure rule ---------------------------------------------------------

def test_the_median_of_three_siblings():
    assert sibling_stats([("E-1.0", 40), ("E-1.1", 60), ("E-1.2", 50)]).median == 50


def test_an_even_sample_takes_the_lower_middle():
    """Deliberate: an estimate that rounds down is the safer error when
    the number is a guess being handed to a GC."""
    assert sibling_stats([("A", 40), ("B", 60)]).median == 40


def test_too_small_a_sample_is_no_basis_at_all():
    """Review focus 2: a single-sheet project has no siblings, so cases 3
    and 4 must stand down rather than compare a sheet to itself."""
    assert sibling_stats([("E-1.0", 40)]) is None
    assert sibling_stats([]) is None


def test_sheets_that_counted_nothing_are_excluded_from_the_base():
    """A sheet that failed is what we are guessing FOR; letting it into
    the median drags every guess toward zero -- and toward zero is the
    direction that reads as "this job is smaller than it is"."""
    stats = sibling_stats([("A", 40), ("B", 60), ("C", 50), ("D", 0)])
    assert stats.median == 50
    assert stats.sample == 3


def test_a_project_where_nothing_counted_has_no_base():
    """Review focus 1. The whole licence to guess rests on having
    counted something to be relative to."""
    assert sibling_stats([("A", 0), ("B", 0)]) is None


def test_the_stats_name_the_sheets_they_came_from():
    """An assumption whose evidence is "the drawings" cannot be checked,
    which `basis.validate_assumption` treats as worse than none."""
    assert sibling_stats([("A", 40), ("B", 60)]).sheet_numbers == ("A", "B")


def test_the_minimum_sample_is_one_named_number():
    assert MIN_SAMPLE >= 2


# --- reading the counts out of the project ---------------------------------

def test_plan_sheet_counts_ignores_schedules_and_legends(db, project):
    """A luminaire schedule is not a sibling of a floor plan. Comparing
    one to the other would call every plan sheet thin."""
    _item(db, project, _sheet(db, project, number="E-501", kind="schedule"), quantity=4)
    _item(db, project, _sheet(db, project, number="E-1.0", kind="plan"), quantity=40)
    assert [n for n, _ in plan_sheet_counts(db, project)] == ["E-1.0"]


def test_plan_sheet_counts_totals_the_devices_on_each_sheet(db, project):
    sheet = _sheet(db, project, number="E-1.0", kind="plan")
    _item(db, project, sheet, quantity=40)
    _item(db, project, sheet, quantity=20)
    assert plan_sheet_counts(db, project) == [("E-1.0", 60)]


def test_a_plan_sheet_with_no_items_is_reported_at_zero(db, project):
    """Case 4 needs to see it. A sheet absent from this list entirely
    could not be guessed for."""
    _sheet(db, project, number="E-1.0", kind="plan")
    assert plan_sheet_counts(db, project) == [("E-1.0", 0)]


def test_a_superseded_sheet_is_not_a_sibling(db, project):
    """ROADMAP invariant 2, enforced by going through
    `countable_items()` rather than by remembering to filter."""
    from datetime import datetime, timezone

    old = _sheet(db, project, number="E-0.9", kind="plan",
                 superseded_at=datetime.now(timezone.utc))
    _item(db, project, old, quantity=500)
    _item(db, project, _sheet(db, project, number="E-1.0", kind="plan"), quantity=40)
    assert plan_sheet_counts(db, project) == [("E-1.0", 40)]


def test_a_measured_line_is_not_counted_as_a_device(db, project):
    """Feet and devices are different units. Adding 240 ft of conduit to
    a device count would make a sheet look dense because somebody
    measured a long run on it."""
    sheet = _sheet(db, project, number="E-1.0", kind="plan")
    _item(db, project, sheet, quantity=40)
    _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]])
    assert plan_sheet_counts(db, project) == [("E-1.0", 40)]


def test_the_counts_are_sorted_by_sheet_number(db, project):
    for number in ("E-1.2", "E-1.0", "E-1.1"):
        _item(db, project, _sheet(db, project, number=number, kind="plan"), quantity=40)
    assert [n for n, _ in plan_sheet_counts(db, project)] == ["E-1.0", "E-1.1", "E-1.2"]
