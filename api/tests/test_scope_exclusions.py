"""Task 4 of docs/plans/rom-estimate.md -- scope exclusions remove items
from the ROM, and the dollars they removed are carried so the document
can state them.

This is the sharp edge of the whole feature. An exclusion the engine got
wrong does not make the number look broken: it makes it look smaller and
internally consistent, which is the one way this document can be
confidently wrong in a reader's favour. Hence `excluded_value` -- the
amount is stated, never merely subtracted.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.estimate.exclusions import excluded_item_ids, excluded_value
from app.takeoff.models import Assumption, Item, ReviewStatus, Sheet
from app.takeoff.totals import rom_totals


@pytest.fixture(autouse=True)
def _priced_basis(project):
    """See test_rom_totals -- resolution needs the project's own basis."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    return project


def _item(project, sheet, *, system="Power", cost="100", name="Item", **kw):
    return Item(
        project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=name,
        system=system, category="Devices", quantity=1, unit="EA",
        status=ReviewStatus.READY, x=100, y=100,
        material_cost=Decimal(cost), labor_cost=Decimal("0"), labor_hours=Decimal("0"),
        total_cost=Decimal(cost), **kw,
    )


def _exclusion(project, *, subject_kind="project", subject_id=None, subject_ref=None,
               title="Temporary power excluded"):
    return Assumption(
        project_id=project.id, section="scope", basis="standard_exclusion",
        subject_kind=subject_kind, subject_id=subject_id, subject_ref=subject_ref,
        title=title, found="Not addressed in any document",
        why="Whether it is in the price changes the number",
        where="Scope letter", source="engine",
    )


@pytest.fixture
def fire_alarm_project(db, project, sheet):
    """$400 of work, $100 of it fire alarm, excluded by scope."""
    for n in range(3):
        db.add(_item(project, sheet, name=f"Receptacle {n}"))
    db.add(_item(project, sheet, system="Fire alarm", name="FA device"))
    db.add(_exclusion(project, subject_kind="system", subject_ref="Fire alarm",
                      title="Fire alarm by others"))
    db.flush()
    return project


def test_excluded_items_leave_the_total(db, fire_alarm_project):
    p = fire_alarm_project
    totals = rom_totals(db, p, exclude=excluded_item_ids(db, p.id))
    assert totals.direct_cost == Decimal("300")


def test_excluded_value_is_carried_for_the_qualifications_block(db, fire_alarm_project):
    assert excluded_value(db, fire_alarm_project.id) == Decimal("100")


def test_a_project_scoped_exclusion_removes_no_counted_item(db, project, sheet):
    """Temporary power and trenching are not Division 26 lines the engine
    counts, so excluding them is a scope statement that moves no money.
    It must not sweep up the whole project."""
    db.add(_item(project, sheet))
    db.add(_exclusion(project))
    db.flush()
    assert excluded_item_ids(db, project.id) == set()
    assert excluded_value(db, project.id) == Decimal("0")


def test_a_sheet_scoped_exclusion_removes_that_sheet(db, project, sheet):
    other = Sheet(project_id=project.id, number="ES100", title="Site plan",
                  discipline="Electrical", revision="Rev 1", scale="1/8",
                  scale_options=[], plan="site")
    db.add(other)
    db.flush()
    keep = _item(project, sheet, name="Keep")
    drop = _item(project, other, name="Site lighting", cost="250")
    db.add_all([keep, drop])
    db.add(_exclusion(project, subject_kind="sheet", subject_id=other.id,
                      title="Site lighting by others"))
    db.flush()
    assert excluded_item_ids(db, project.id) == {drop.id}
    assert excluded_value(db, project.id) == Decimal("250")


def test_an_item_scoped_exclusion_removes_exactly_that_item(db, project, sheet):
    keep = _item(project, sheet, name="Keep")
    drop = _item(project, sheet, name="Drop")
    db.add_all([keep, drop])
    db.flush()
    db.add(_exclusion(project, subject_kind="item", subject_id=drop.id))
    db.flush()
    assert excluded_item_ids(db, project.id) == {drop.id}


def test_orphan_assumption_drops_out(db, project, sheet):
    """Review Focus 2 -- the subject item was rejected after the
    assumption was written. The exclusion must stop applying rather than
    cite a line that is no longer there."""
    gone = _item(project, sheet, name="Rejected", rejected_at=datetime.now(timezone.utc))
    db.add(gone)
    db.flush()
    db.add(_exclusion(project, subject_kind="item", subject_id=gone.id))
    db.flush()
    assert excluded_item_ids(db, project.id) == set()
    assert excluded_value(db, project.id) == Decimal("0")


def test_an_exclusion_on_a_superseded_sheet_drops_out(db, project):
    dead = Sheet(project_id=project.id, number="E2.0", title="Superseded",
                 discipline="Electrical", revision="Rev 1", scale="1/8",
                 scale_options=[], plan="warehouse",
                 superseded_at=datetime.now(timezone.utc))
    db.add(dead)
    db.flush()
    db.add(_item(project, dead, name="On a dead sheet"))
    db.add(_exclusion(project, subject_kind="sheet", subject_id=dead.id))
    db.flush()
    assert excluded_item_ids(db, project.id) == set()


def test_everything_excluded_is_distinguishable_from_nothing_counted(db, project, sheet):
    """Review Focus 3 -- zero, but for a stated reason. A bare $0 and a
    $0 that says "scope removed all of it" are different documents."""
    db.add(_item(project, sheet, system="Fire alarm", name="FA device", cost="400"))
    db.add(_exclusion(project, subject_kind="system", subject_ref="Fire alarm",
                      title="Fire alarm by others"))
    db.flush()
    totals = rom_totals(db, project, exclude=excluded_item_ids(db, project.id))
    assert totals.direct_cost == Decimal("0")
    assert excluded_value(db, project.id) > Decimal("0")


def test_overlapping_exclusions_do_not_double_count_the_value(db, project, sheet):
    """One item covered by both a system exclusion and an item exclusion
    is $100 of removed scope, not $200."""
    row = _item(project, sheet, system="Fire alarm", name="FA device")
    db.add(row)
    db.flush()
    db.add(_exclusion(project, subject_kind="system", subject_ref="Fire alarm"))
    db.add(_exclusion(project, subject_kind="item", subject_id=row.id))
    db.flush()
    assert excluded_item_ids(db, project.id) == {row.id}
    assert excluded_value(db, project.id) == Decimal("100")


def test_only_standard_exclusion_assumptions_exclude(db, project, sheet):
    """A scope assumption that is not an exclusion -- an inferred scope
    boundary, say -- describes the number; it must not shrink it."""
    row = _item(project, sheet, name="Kept")
    db.add(row)
    db.flush()
    db.add(Assumption(
        project_id=project.id, section="scope", basis="inferred",
        subject_kind="item", subject_id=row.id, title="Read as in scope",
        found="Scope letter does not list it", why="It is in the drawings",
        where="EL101", source="engine",
    ))
    db.flush()
    assert excluded_item_ids(db, project.id) == set()


def test_a_takeoff_assumption_never_excludes(db, project, sheet):
    row = _item(project, sheet, name="Kept")
    db.add(row)
    db.flush()
    db.add(Assumption(
        project_id=project.id, section="takeoff", basis="standard_exclusion",
        subject_kind="item", subject_id=row.id, title="Mislabelled",
        found="f", why="w", where="EL101", source="engine",
    ))
    db.flush()
    assert excluded_item_ids(db, project.id) == set()


def test_exclusions_are_project_scoped(db, project, sheet, org):
    """Another project's exclusion must not reach into this one."""
    from app.takeoff.models import Project

    other = Project(org_id=org.id, name="Other job", revision_set_label="")
    db.add(other)
    db.flush()
    row = _item(project, sheet, system="Fire alarm", name="FA device")
    db.add(row)
    db.add(_exclusion(other, subject_kind="system", subject_ref="Fire alarm"))
    db.flush()
    assert excluded_item_ids(db, project.id) == set()


def test_a_system_exclusion_naming_nothing_present_removes_nothing(db, project, sheet):
    db.add(_item(project, sheet))
    db.add(_exclusion(project, subject_kind="system", subject_ref="Nurse call"))
    db.flush()
    assert excluded_item_ids(db, project.id) == set()
