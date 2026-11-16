"""Tasks 6-9 of docs/plans/estimate-without-asking.md -- the completion
pass, which is the whole reason the ROM's number currently comes out too
small.

Every case writes the same thing: **one companion allowance line,
attached to a real sheet, carrying money the counted lines do not.** The
counted line is read and never rewritten -- it keeps saying exactly what
was counted, and the allowance sits beside it saying what the gap costs.

Two things these tests guard hardest, because both were design hazards
before they were tests:

- **Nothing counted means nothing guessed.** Every quantity here is
  relative to what this project itself counted. A project with nothing
  on it produces no completion lines at all, because a relative guess
  with no base is a fabricated building.
- **`Sheet.scale` is never written.** A stored scale is
  indistinguishable from a confirmed one, which would release every
  blocked item on the sheet and let the export through. Case 2 carries
  the money and leaves the scale alone.
"""
from decimal import Decimal

import pytest

from app.estimate.complete import completion_lines
from app.takeoff.models import Item, ReviewStatus, Sheet


@pytest.fixture(autouse=True)
def _engine_priced(project):
    """Resolution only trusts the engine's stored figures when the
    project was priced by the engine (`Project.pricing_source`) -- the
    same fixture `test_rom_totals.py` carries, for the same reason.
    Without it every counted line here would resolve unpriced, which is
    a different scenario than the one under test."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    return project


def _sheet(db, project, *, number="E-2.1", kind="plan", scale="", **kw):
    s = Sheet(project_id=project.id, number=number, title="Power plan", discipline="Electrical",
              revision="Rev 1", scale=scale, scale_options=[], plan="", kind=kind, **kw)
    db.add(s)
    db.flush()
    return s


def _item(db, project, sheet, *, quantity=47, cost="0", hours="0", system="Power",
          status=ReviewStatus.READY, unit="EA", name="Symbol A", **kw):
    i = Item(
        project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=name,
        system=system, category="Devices", quantity=Decimal(quantity), unit=unit,
        status=status, material_cost=Decimal(cost), labor_hours=Decimal(hours),
        labor_cost=Decimal("0"), total_cost=Decimal(cost), **kw,
    )
    db.add(i)
    db.flush()
    return i


def _case(lines, case):
    return [line for line in lines if line["case"] == case]


# --- Case 1: counted but never identified ---------------------------------

def test_a_counted_line_nothing_priced_gets_a_companion_allowance(db, project):
    sheet = _sheet(db, project)
    _item(db, project, sheet, quantity=47, cost="0", hours="0")
    # Something priced somewhere, or there is no class average to take.
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")

    [line] = _case(completion_lines(db, project), "unidentified")
    assert line["origin"] == "assumed"
    assert line["sheet_id"] == sheet.id
    assert line["confidence"] == 5
    assert line["basis"] == "class_average"
    assert line["total_cost"] > 0


def test_a_priced_counted_line_gets_no_companion(db, project):
    sheet = _sheet(db, project)
    _item(db, project, sheet, quantity=47, cost="564")
    assert _case(completion_lines(db, project), "unidentified") == []


def test_one_companion_per_sheet_not_per_cluster(db, project):
    """Forty unpriced clusters on one sheet is one problem with one fix,
    not forty allowances -- the grouping `generate_takeoff` already
    applies to a missing scale."""
    sheet = _sheet(db, project)
    for tag in ("A", "B", "C"):
        _item(db, project, sheet, source_tag=tag, cost="0", hours="0", name=f"Symbol {tag}")
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")
    assert len(_case(completion_lines(db, project), "unidentified")) == 1


def test_the_counted_line_itself_is_never_rewritten(db, project):
    """`merge.py` owns the counted line and would fight any write here on
    the next run. The allowance sits beside it instead."""
    sheet = _sheet(db, project)
    counted = _item(db, project, sheet, quantity=47, cost="0", hours="0")
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")

    completion_lines(db, project)
    db.refresh(counted)
    assert counted.material_cost == 0
    assert counted.origin == "counted"
    assert counted.confidence is None


def test_the_disclosure_names_the_sheet_and_the_device_count(db, project):
    sheet = _sheet(db, project, number="E-2.1")
    _item(db, project, sheet, quantity=47, cost="0", hours="0")
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")

    [line] = _case(completion_lines(db, project), "unidentified")
    assert all(line[field] for field in ("title", "found", "why", "fix", "where"))
    assert "47" in line["found"]
    assert "E-2.1" in line["found"]


def test_a_project_with_no_counted_items_completes_nothing(db, project):
    """Review focus 1: a relative guess with no base is a fabricated
    building."""
    assert completion_lines(db, project) == []


def test_a_project_where_nothing_priced_takes_no_class_average(db, project):
    """There is no "typical cost on this job" to be relative to, so case
    1 stands down rather than reaching for a constant."""
    sheet = _sheet(db, project)
    _item(db, project, sheet, quantity=47, cost="0", hours="0")
    assert _case(completion_lines(db, project), "unidentified") == []


def test_the_allowance_does_not_count_the_devices_a_second_time(db, project):
    """Case 1 is the one case where the quantity is solid. The counted
    line already says 47; the companion carries money only, or the
    spreadsheet would read as 94 devices."""
    sheet = _sheet(db, project)
    _item(db, project, sheet, quantity=47, cost="0", hours="0")
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")

    [line] = _case(completion_lines(db, project), "unidentified")
    assert line["quantity"] == 1
    assert line["unit"] == "ls"


def test_an_excluded_item_takes_its_companion_with_it(db, project):
    """Scope removed the work, so an allowance for its missing price
    would be money in the number for something that is out of scope."""
    sheet = _sheet(db, project)
    unpriced = _item(db, project, sheet, quantity=47, cost="0", hours="0")
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")

    assert _case(completion_lines(db, project, exclude={unpriced.id}), "unidentified") == []


def test_a_rejected_line_is_not_completed_for(db, project):
    """`countable_items` already drops it from every total, so an
    allowance covering it would be the only place it still counted."""
    from datetime import datetime, timezone

    sheet = _sheet(db, project)
    _item(db, project, sheet, quantity=47, cost="0", hours="0",
          rejected_at=datetime.now(timezone.utc))
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")
    assert _case(completion_lines(db, project), "unidentified") == []


def test_a_companion_never_arrives_approved(db, project):
    """CLAUDE.md: no code path writes *Estimator approved*. Approval is
    the one act that cannot be delegated."""
    sheet = _sheet(db, project)
    _item(db, project, sheet, quantity=47, cost="0", hours="0")
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")

    for line in completion_lines(db, project):
        assert line["status"] == "ready"


def test_every_completion_line_names_its_reasons(db, project):
    sheet = _sheet(db, project)
    _item(db, project, sheet, quantity=47, cost="0", hours="0")
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")

    for line in completion_lines(db, project):
        assert line["confidence_reasons"]
        assert 1 <= line["confidence"] <= 9


# --- Case 2: measured runs with no confirmed scale ------------------------

def test_measured_items_on_an_unscaled_sheet_get_an_allowance(db, project):
    sheet = _sheet(db, project, number="E-2.1", scale="")
    _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]],
          status=ReviewStatus.MISSING, name="3/4\" EMT homerun", cost="0")
    scaled = _sheet(db, project, number="E-1.0", scale='1/8" = 1\'-0"')
    _item(db, project, scaled, quantity=300, unit="ft", path=[[0, 0], [20, 20]],
          cost="900", name="3/4\" EMT homerun")

    [line] = _case(completion_lines(db, project), "unscaled")
    assert line["confidence"] == 4
    assert line["basis"] == "scaled"
    assert line["sheet_id"] == sheet.id
    assert line["total_cost"] > 0


def test_a_confirmed_scale_produces_no_allowance(db, project):
    sheet = _sheet(db, project, number="E-2.1", scale='1/8" = 1\'-0"')
    _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]], cost="720")
    assert _case(completion_lines(db, project), "unscaled") == []


def test_a_sheet_with_two_scale_labels_is_treated_as_unscaled(db, project):
    """The E2.1 case from the README walkthrough. "mixed" is the
    engine's own word for it, and the measurements rest on a choice
    nobody made either way."""
    sheet = _sheet(db, project, number="E-2.1", scale="mixed")
    _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]],
          status=ReviewStatus.MISSING, cost="0")
    scaled = _sheet(db, project, number="E-1.0", scale='1/8" = 1\'-0"')
    _item(db, project, scaled, quantity=300, unit="ft", path=[[0, 0], [20, 20]], cost="900")
    assert len(_case(completion_lines(db, project), "unscaled")) == 1


def test_the_sheets_scale_is_never_written(db, project):
    """The single most dangerous write in this design. A stored scale is
    indistinguishable from a confirmed one, and writing one would
    release every blocked item on the sheet and let the export through
    on a guess."""
    sheet = _sheet(db, project, number="E-2.1", scale="")
    _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]],
          status=ReviewStatus.MISSING, cost="0")
    scaled = _sheet(db, project, number="E-1.0", scale='1/8" = 1\'-0"')
    _item(db, project, scaled, quantity=300, unit="ft", path=[[0, 0], [20, 20]], cost="900")

    completion_lines(db, project)
    db.refresh(sheet)
    assert not sheet.scale


def test_the_measured_items_keep_missing_information(db, project):
    """The firewall stays shut: the export still blocks until a person
    sets the scale. Only the ROM stops being silently short."""
    sheet = _sheet(db, project, number="E-2.1", scale="")
    item = _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]],
                 status=ReviewStatus.MISSING, cost="0")
    scaled = _sheet(db, project, number="E-1.0", scale='1/8" = 1\'-0"')
    _item(db, project, scaled, quantity=300, unit="ft", path=[[0, 0], [20, 20]], cost="900")

    completion_lines(db, project)
    db.refresh(item)
    assert item.status is ReviewStatus.MISSING


def test_the_disclosure_says_which_sheet_lacks_a_scale(db, project):
    sheet = _sheet(db, project, number="E-2.1", scale="")
    _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]],
          status=ReviewStatus.MISSING, cost="0")
    scaled = _sheet(db, project, number="E-1.0", scale='1/8" = 1\'-0"')
    _item(db, project, scaled, quantity=300, unit="ft", path=[[0, 0], [20, 20]], cost="900")

    [line] = _case(completion_lines(db, project), "unscaled")
    assert "E-2.1" in line["found"]
    assert "scale" in line["why"].lower() or "scale" in line["found"].lower()


def test_an_unscaled_sheet_with_no_measured_items_gets_nothing(db, project):
    """A sheet with no scale and nothing measured on it has no problem
    to solve."""
    sheet = _sheet(db, project, number="E-2.1", scale="")
    _item(db, project, sheet, quantity=47, cost="564")
    assert _case(completion_lines(db, project), "unscaled") == []


def test_an_unscaled_sheet_with_nothing_measured_elsewhere_stands_down(db, project):
    """Nothing counted means nothing guessed, applied to case 2: with no
    measured run anywhere that priced, there is no footage-per-run on
    this job to be relative to."""
    sheet = _sheet(db, project, number="E-2.1", scale="")
    _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]],
          status=ReviewStatus.MISSING, cost="0")
    _item(db, project, sheet, quantity=47, cost="564")
    assert _case(completion_lines(db, project), "unscaled") == []
