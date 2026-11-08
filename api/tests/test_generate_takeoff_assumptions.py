"""Task 6 of docs/plans/rom-estimate.md -- the quantities that were
derived rather than counted.

Counting is not touched by any of this. It reads placements out of the
file and is tested against asserted counts; nothing here second-guesses
it. What these assumptions cover is the quantities Counting cannot
produce because they are not in the file: a run length behind a homerun
arrow, a length measured off a sheet whose scale nobody confirmed.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.estimate.basis import validate_assumption
from app.estimate.generate_takeoff import FEET_PER_DEVICE, takeoff_assumptions
from app.takeoff.models import Item, ReviewStatus, Sheet


def _sheet(project, *, number="EL101", scale="1/8\" = 1'-0\"", **kw):
    return Sheet(project_id=project.id, number=number, title="Lighting plan",
                 discipline="Electrical", revision="Rev 2", scale=scale,
                 scale_options=[], plan="showroom", **kw)


def _device(project, sheet, *, name="20A duplex receptacle", material="100", qty="1"):
    return Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=name,
                system="Power", category="Devices", quantity=Decimal(qty), unit="ea",
                status=ReviewStatus.READY, x=100, y=100,
                material_cost=Decimal(material), labor_cost=Decimal("40"),
                labor_hours=Decimal("2"), total_cost=Decimal(material) + 40)


def _measured(project, sheet, *, name="Panel SB-1 feeder", qty="185", unit="ft"):
    return Item(project_id=project.id, sheet_id=sheet.id, symbol="conduit", name=name,
                system="Service and distribution", category="Raceway",
                quantity=Decimal(qty), unit=unit, status=ReviewStatus.READY,
                x=100, y=100, path=[[10, 10], [90, 90]],
                material_cost=Decimal("250"), labor_cost=Decimal("0"),
                labor_hours=Decimal("0"), total_cost=Decimal("250"))


def one(rows, *, title_contains):
    matches = [r for r in rows if title_contains.lower() in r["title"].lower()]
    assert len(matches) == 1, f"expected exactly one {title_contains!r}, got {[r['title'] for r in rows]}"
    return matches[0]


# --- branch wire and conduit -------------------------------------------


def test_branch_footage_uses_the_firm_rule(db, project, sheet):
    db.add(_device(project, sheet))
    db.flush()
    a = one(takeoff_assumptions(db, project), title_contains="conduit")
    assert a["basis"] == "rule_of_thumb"
    assert a["section"] == "takeoff"
    assert a["unit"] == "ft per device"
    # Printed as the document prints it -- "30", not "30.0" -- and the
    # same string the copy interpolates, so the value and the sentence
    # cannot disagree.
    assert a["value"] == "30"
    assert float(a["value"]) == FEET_PER_DEVICE
    assert f"{a['value']} ft per device" in a["found"]


def test_the_branch_footage_assumption_says_the_drawing_shows_no_route(db, project, sheet):
    """The reason this is a rule and not a measurement has to be on the
    page: the drawing shows a homerun arrow, not a route."""
    db.add(_device(project, sheet))
    db.flush()
    a = one(takeoff_assumptions(db, project), title_contains="conduit")
    assert "route" in a["found"].lower() or "arrow" in a["found"].lower()


def test_branch_footage_is_one_project_line_not_one_per_device(db, project, sheet):
    for n in range(40):
        db.add(_device(project, sheet, name=f"Receptacle {n}"))
    db.flush()
    rows = [a for a in takeoff_assumptions(db, project) if a["basis"] == "rule_of_thumb"]
    assert len(rows) == 1
    assert rows[0]["subject_kind"] == "project"
    # Deliberately does NOT claim a line count. The engine prices a line
    # it could not match to a catalog item bare, with no assembly, and
    # nothing on the item records which way it went -- so "40 lines
    # include branch wire" was a claim this module cannot establish.
    assert "priced bare" in rows[0]["found"]


def test_a_project_with_no_priced_devices_has_no_footage_assumption(db, project, sheet):
    db.add(_device(project, sheet, material="0"))
    db.flush()
    assert not any(a["basis"] == "rule_of_thumb" for a in takeoff_assumptions(db, project))


# --- missing scale -----------------------------------------------------


@pytest.fixture
def unscaled_sheet_with_forty_measured_items(db, project):
    s = _sheet(project, number="E1.1", scale="")
    db.add(s)
    db.flush()
    for n in range(40):
        db.add(_measured(project, s, name=f"Conduit run {n}"))
    db.flush()
    return s


def test_missing_scale_is_one_sheet_level_assumption_not_one_per_item(
        db, project, unscaled_sheet_with_forty_measured_items):
    scale = [a for a in takeoff_assumptions(db, project) if "scale" in a["title"].lower()]
    assert len(scale) == 1
    assert scale[0]["subject_kind"] == "sheet"
    assert scale[0]["subject_id"] == unscaled_sheet_with_forty_measured_items.id


def test_missing_scale_assumption_names_what_it_affects(
        db, project, unscaled_sheet_with_forty_measured_items):
    a = one(takeoff_assumptions(db, project), title_contains="scale")
    assert "40" in a["found"]


def test_missing_scale_assumption_names_the_sheet_in_where(
        db, project, unscaled_sheet_with_forty_measured_items):
    a = one(takeoff_assumptions(db, project), title_contains="scale")
    assert "E1.1" in a["where"]


def test_sheet_with_a_scale_produces_no_scale_assumption(db, project):
    s = _sheet(project)
    db.add(s)
    db.flush()
    db.add(_measured(project, s))
    db.flush()
    assert not any("scale" in a["title"].lower() for a in takeoff_assumptions(db, project))


def test_an_unscaled_sheet_with_no_measured_items_produces_nothing(db, project):
    """A missing scale on a sheet carrying only counted devices changed
    no number -- disclosing it would be noise on a page whose whole job
    is to be read."""
    s = _sheet(project, number="E1.1", scale="")
    db.add(s)
    db.flush()
    db.add(_device(project, s))
    db.flush()
    assert not any("scale" in a["title"].lower() for a in takeoff_assumptions(db, project))


def test_two_unscaled_sheets_produce_two_assumptions(db, project):
    for number in ("E1.1", "E1.2"):
        s = _sheet(project, number=number, scale="")
        db.add(s)
        db.flush()
        db.add(_measured(project, s))
    db.flush()
    scale = [a for a in takeoff_assumptions(db, project) if "scale" in a["title"].lower()]
    assert len(scale) == 2
    assert {a["subject_kind"] for a in scale} == {"sheet"}


def test_a_superseded_unscaled_sheet_produces_nothing(db, project):
    s = _sheet(project, number="E1.0", scale="", superseded_at=datetime.now(timezone.utc))
    db.add(s)
    db.flush()
    db.add(_measured(project, s))
    db.flush()
    assert not any("scale" in a["title"].lower() for a in takeoff_assumptions(db, project))


def test_a_mixed_scale_sheet_is_assumed_too(db, project):
    """Two scale labels on one sheet is not a scale -- the measurements
    rest on a choice nobody made."""
    s = _sheet(project, number="E2.1", scale="mixed")
    db.add(s)
    db.flush()
    db.add(_measured(project, s))
    db.flush()
    assert any("scale" in a["title"].lower() for a in takeoff_assumptions(db, project))


# --- scaled lengths ----------------------------------------------------


def test_measured_lengths_on_a_scaled_sheet_are_still_scaled_not_dimensioned(db, project):
    """A length taken off the drawing at its stated scale is a real
    measurement and still not a dimension somebody wrote down."""
    s = _sheet(project)
    db.add(s)
    db.flush()
    db.add(_measured(project, s))
    db.flush()
    rows = [a for a in takeoff_assumptions(db, project)
            if a["basis"] == "scaled" and a["subject_kind"] == "project"]
    assert len(rows) == 1
    assert "1" in rows[0]["found"]


def test_a_project_with_no_measured_items_has_no_scaled_assumption(db, project, sheet):
    db.add(_device(project, sheet))
    db.flush()
    assert not any(a["basis"] == "scaled" for a in takeoff_assumptions(db, project))


# --- shape -------------------------------------------------------------


def test_excluded_items_produce_no_takeoff_assumption(db, project):
    s = _sheet(project, number="E1.1", scale="")
    db.add(s)
    db.flush()
    row = _measured(project, s)
    db.add(row)
    db.flush()
    assert takeoff_assumptions(db, project, exclude={row.id}) == []


def test_every_generated_assumption_validates(db, project):
    s = _sheet(project, number="E1.1", scale="")
    db.add(s)
    db.flush()
    db.add(_device(project, s))
    db.add(_measured(project, s))
    db.flush()
    rows = takeoff_assumptions(db, project)
    assert rows
    for a in rows:
        validate_assumption(a)


def test_an_empty_project_produces_nothing(db, project):
    assert takeoff_assumptions(db, project) == []


def test_no_generated_copy_names_a_model_or_a_confidence(db, project):
    s = _sheet(project, number="E1.1", scale="")
    db.add(s)
    db.flush()
    db.add(_device(project, s))
    db.add(_measured(project, s))
    db.flush()
    rows = takeoff_assumptions(db, project)
    blob = " ".join(f"{a['title']} {a['found']} {a['why']} {a['where']}" for a in rows).lower()
    for forbidden in ("model", "confidence", "claude", "token", "prompt", "llm"):
        assert forbidden not in blob, forbidden


def test_the_feet_per_device_rule_mirrors_the_engine():
    """`app.estimate.generate_takeoff.FEET_PER_DEVICE` is a deliberate
    copy, because `app.engine.assemblies` is banned from the API process
    (test_api_import_boundary.py). This is what keeps the copy from
    drifting -- the same discipline test_ingest_mapping.py's
    sheet-kinds mirror test applies. A test may import the engine; the
    API process may not.

    If this fails, the engine changed the rule and the document is now
    disclosing a number the estimate was not priced with.
    """
    from app.engine.assemblies import FEET_PER_DEVICE as ENGINE_RULE

    assert FEET_PER_DEVICE == ENGINE_RULE
