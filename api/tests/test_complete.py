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


def _sheet(db, project, *, number="E-2.1", kind="plan", scale="", title="Power plan", **kw):
    s = Sheet(project_id=project.id, number=number, title=title, discipline="Electrical",
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


# --- Cases 3 and 4: thin or empty against the siblings --------------------
# Built together because they share one calculation -- the shortfall
# against the sibling median. An empty sheet is the thin case at zero.

def _siblings(db, project, counts, cost="120"):
    """Plan sheets that each counted something and priced, so there is a
    base and a class average to be relative to."""
    for number, quantity in counts:
        sheet = _sheet(db, project, number=number)
        if quantity:
            _item(db, project, sheet, quantity=quantity, cost=cost,
                  name="20A duplex receptacle")
    return None


def test_a_sheet_counted_well_below_its_siblings_is_topped_up(db, project):
    _siblings(db, project, [("E-1.0", 60), ("E-1.1", 60)])
    thin = _sheet(db, project, number="E-1.2")
    _item(db, project, thin, quantity=5, cost="60", name="20A duplex receptacle")

    [line] = _case(completion_lines(db, project), "thin")
    assert line["sheet_id"] == thin.id
    assert line["quantity"] == 55
    assert line["confidence"] == 3
    assert line["basis"] == "class_average"
    assert line["total_cost"] > 0


def test_a_sheet_in_line_with_its_siblings_is_left_alone(db, project):
    _siblings(db, project, [("E-1.0", 60), ("E-1.1", 60), ("E-1.2", 55)])
    assert _case(completion_lines(db, project), "thin") == []
    assert _case(completion_lines(db, project), "empty") == []


def test_a_sheet_that_counted_nothing_is_guessed_from_its_siblings(db, project):
    _siblings(db, project, [("E-1.0", 60), ("E-1.1", 60)])
    _sheet(db, project, number="E-1.2")

    [line] = _case(completion_lines(db, project), "empty")
    assert line["quantity"] == 60
    assert line["confidence"] == 3


def test_a_sheet_that_failed_to_render_is_scored_lower(db, project):
    """The page read only partly, which is a named adjustment on the
    confidence scale rather than a separate kind of guess."""
    _siblings(db, project, [("E-1.0", 60), ("E-1.1", 60)])
    _sheet(db, project, number="E-1.2", render_status="failed")

    [line] = _case(completion_lines(db, project), "empty")
    assert line["confidence"] == 2
    assert "partly" in " ".join(line["confidence_reasons"]).lower()


def test_a_single_sheet_project_guesses_nothing(db, project):
    """Review focus 2: no siblings, no comparison, no guess. A sheet
    cannot be thin against itself."""
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=5, cost="60", name="20A duplex receptacle")
    lines = completion_lines(db, project)
    assert _case(lines, "thin") == []
    assert _case(lines, "empty") == []


def test_two_sheets_one_empty_still_stands_down(db, project):
    """`MIN_SAMPLE` is 2, and one sibling is an anecdote rather than a
    distribution."""
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=60, cost="720", name="20A duplex receptacle")
    _sheet(db, project, number="E-1.1")
    assert _case(completion_lines(db, project), "empty") == []


def test_the_disclosure_names_the_sheets_the_median_came_from(db, project):
    _siblings(db, project, [("E-1.0", 60), ("E-1.1", 60)])
    _sheet(db, project, number="E-1.2")

    [line] = _case(completion_lines(db, project), "empty")
    assert "E-1.0" in line["where"]
    assert "E-1.1" in line["where"]


def test_a_schedule_sheet_is_never_called_thin(db, project):
    """A luminaire schedule is not a plan sheet and has no business
    being compared to one."""
    _siblings(db, project, [("E-1.0", 60), ("E-1.1", 60)])
    _sheet(db, project, number="E-501", kind="schedule")
    lines = completion_lines(db, project)
    assert not [line for line in lines if line["sheet_number"] == "E-501"]


def test_a_sheet_gets_a_thin_allowance_or_an_empty_one_never_both(db, project):
    _siblings(db, project, [("E-1.0", 60), ("E-1.1", 60)])
    _sheet(db, project, number="E-1.2")
    lines = completion_lines(db, project)
    per_sheet = [line["sheet_number"] for line in lines if line["case"] in ("thin", "empty")]
    assert len(per_sheet) == len(set(per_sheet))


# --- Case 5: a system the job should have and nothing found ---------------

def _scope(db, project, dana, text):
    import uuid as _uuid

    from app.takeoff.models import Document, ScopeStatement
    doc = Document(project_id=project.id, filename="spec.pdf", doc_type="specifications",
                   content_type="application/pdf", size_bytes=1, sha256="b" * 64,
                   storage_key="k2", uploaded_by=dana.id)
    db.add(doc)
    db.flush()
    s = ScopeStatement(project_id=project.id, org_id=project.org_id, document_id=doc.id,
                       page_index=0, kind="included", text=text, quote=text,
                       run_id=_uuid.uuid4())
    db.add(s)
    db.flush()
    return s


def test_a_school_with_no_fire_alarm_gets_a_share_of_the_counted_work(db, project):
    project.building_type, project.building_type_source = "school", "estimator"
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")

    [line] = [l for l in completion_lines(db, project) if l["system"] == "Fire alarm"]
    assert line["case"] == "system"
    assert line["confidence"] == 2
    assert line["basis"] == "class_average"
    assert line["total_cost"] > 0


def test_a_system_already_counted_is_not_guessed(db, project):
    project.building_type, project.building_type_source = "school", "estimator"
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")
    _item(db, project, sheet, quantity=4, cost="400", system="Fire alarm",
          name="Smoke detector")

    assert not [l for l in completion_lines(db, project)
                if l["case"] == "system" and l["system"] == "Fire alarm"]


def test_an_unknown_building_type_skips_system_completion(db, project):
    """Review focus: never invent a baseline for an unknown building. A
    system allowance sized with no sense of the job is the fabricated
    number this product exists to prevent."""
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")
    assert _case(completion_lines(db, project), "system") == []


def test_nothing_counted_means_no_share_to_take(db, project):
    """Review focus 1 again: a share of zero is zero, never a constant."""
    project.building_type, project.building_type_source = "school", "estimator"
    _sheet(db, project, number="E-1.0")
    assert _case(completion_lines(db, project), "system") == []


def test_a_system_line_still_points_at_a_real_sheet(db, project):
    """`Item.sheet_id` is NOT NULL, so there is no such thing as a line
    without a sheet. The copy has to say the location is nominal rather
    than let it read as a place the work was found."""
    project.building_type, project.building_type_source = "school", "estimator"
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")

    line = _case(completion_lines(db, project), "system")[0]
    assert line["sheet_id"] is not None
    assert "nominal" in line["where"].lower()


def test_a_building_type_only_guess_says_it_is_the_weakest_basis(db, project):
    project.building_type, project.building_type_source = "school", "estimator"
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")

    line = _case(completion_lines(db, project), "system")[0]
    assert "weakest" in line["where"].lower()


def test_a_spec_section_naming_the_work_is_quoted_as_the_evidence(db, project, dana):
    """The strongest of the three kinds of evidence: a real quote on a
    real page, which stands on its own without a building type."""
    _scope(db, project, dana, "Division 28 fire alarm devices by this contractor.")
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")

    line = [l for l in completion_lines(db, project) if l["system"] == "Fire alarm"][0]
    assert "Division 28" in line["found"]
    assert "weakest" not in line["where"].lower()


def test_an_inferred_building_type_is_enough_to_run_the_case(db, project):
    """The spec: infer it, disclose it, ask about it, never block on it."""
    _sheet(db, project, number="E-1.0", title="Classroom wing power plan")
    sheet = _sheet(db, project, number="E-1.1", title="Classroom wing lighting plan")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")

    assert _case(completion_lines(db, project), "system")


# --- Whole-branch review findings 4, 5, 6 ---------------------------------

def test_a_long_measured_run_does_not_collapse_the_per_device_average(db, project):
    """Review finding 4. `_ClassAverage`'s denominator must count devices
    only. Feet and devices are not the same quantity, and mixing them
    makes 10,000 ft of conduit divide the per-device cost by a hundred --
    an empty-sheet allowance that should be $6,000 came out at $130."""
    for number in ("E-1.0", "E-1.1"):
        _item(db, project, _sheet(db, project, number=number), quantity=60, cost="6000",
              name="20A duplex receptacle")
    _sheet(db, project, number="E-1.2")

    [before] = _case(completion_lines(db, project), "empty")

    scaled = _sheet(db, project, number="E-1.3", scale='1/8" = 1\'-0"')
    _item(db, project, scaled, quantity=10000, unit="ft", path=[[0, 0], [99, 99]],
          cost="10000", name="3/4\" EMT")

    [after] = _case(completion_lines(db, project), "empty")
    assert after["material_cost"] == before["material_cost"]


def test_a_measured_run_that_already_priced_gets_no_unscaled_allowance(db, project):
    """Review finding 5. A row on an unscaled sheet that nonetheless
    resolved a price is already in `rom_totals` -- `missing` status does
    not keep it out. An allowance covering it bills the same footage
    twice."""
    sheet = _sheet(db, project, number="E-2.1", scale="")
    _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]],
          status=ReviewStatus.MISSING, cost="720", name="3/4\" EMT")
    scaled = _sheet(db, project, number="E-1.0", scale='1/8" = 1\'-0"')
    _item(db, project, scaled, quantity=300, unit="ft", path=[[0, 0], [20, 20]],
          cost="900", name="3/4\" EMT")

    assert _case(completion_lines(db, project), "unscaled") == []


def test_an_unpriced_run_on_the_same_unscaled_sheet_still_gets_one(db, project):
    """The other half of finding 5: narrowing to unpriced rows must not
    turn case 2 off."""
    sheet = _sheet(db, project, number="E-2.1", scale="")
    _item(db, project, sheet, quantity=240, unit="ft", path=[[0, 0], [10, 10]],
          status=ReviewStatus.MISSING, cost="0", name="3/4\" EMT")
    scaled = _sheet(db, project, number="E-1.0", scale='1/8" = 1\'-0"')
    _item(db, project, scaled, quantity=300, unit="ft", path=[[0, 0], [20, 20]],
          cost="900", name="3/4\" EMT")

    assert len(_case(completion_lines(db, project), "unscaled")) == 1


def test_counted_fire_alarm_devices_suppress_the_fire_alarm_allowance(db, project):
    """Review finding 6, and the worst of them. The classifier has no
    "Fire alarm" system -- `engine.contracts.RESOLVE_SYSTEMS` puts a
    smoke detector under "Life safety" -- so comparing system strings
    meant case 5 claimed no fire alarm work was found on EVERY project,
    including ones carrying counted smoke detectors.

    This is the same trap `generate_scope.StandardExclusion.vocabulary`
    already documents: "a counted fire-alarm device may classify as
    'Life safety', but so do exit signs". The absence check has to read
    the item's own name, not only its system."""
    project.building_type, project.building_type_source = "school", "estimator"
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")
    _item(db, project, sheet, quantity=8, cost="1000", system="Life safety",
          name="Smoke detector")

    assert not [l for l in completion_lines(db, project)
                if l["case"] == "system" and l["system"] == "Fire alarm"]


def test_an_exit_sign_does_not_pass_for_fire_alarm_work(db, project):
    """The inverse. Exit signs classify as Life safety too, and they ARE
    Division 26 work this estimate includes -- but they are not fire
    alarm devices, so they must not suppress that allowance."""
    project.building_type, project.building_type_source = "school", "estimator"
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")
    _item(db, project, sheet, quantity=12, cost="900", system="Life safety",
          name="Exit sign")

    assert [l for l in completion_lines(db, project)
            if l["case"] == "system" and l["system"] == "Fire alarm"]


def test_counted_life_safety_work_suppresses_its_own_allowance(db, project):
    project.building_type, project.building_type_source = "school", "estimator"
    sheet = _sheet(db, project, number="E-1.0")
    _item(db, project, sheet, quantity=100, cost="10000", name="20A duplex receptacle")
    _item(db, project, sheet, quantity=12, cost="900", system="Life safety",
          name="Exit sign")

    assert not [l for l in completion_lines(db, project)
                if l["case"] == "system" and l["system"] == "Life safety"]


def test_a_sheet_carrying_only_measured_runs_is_not_an_empty_sheet(db, project):
    """Found while fixing review finding 4. A riser or single-line sheet
    can carry real counted work and zero *devices*, and case 4's own
    definition is "produced no items at all" -- read failed, render
    failed, or counting returned nothing. Topping such a sheet up to its
    siblings' device median invents devices on a sheet that was read
    correctly and has none."""
    for number in ("E-1.0", "E-1.1"):
        _item(db, project, _sheet(db, project, number=number), quantity=60, cost="6000",
              name="20A duplex receptacle")
    riser = _sheet(db, project, number="E-1.3", scale='1/8" = 1\'-0"')
    _item(db, project, riser, quantity=10000, unit="ft", path=[[0, 0], [99, 99]],
          cost="10000", name="3/4\" EMT")

    assert not [l for l in completion_lines(db, project)
                if l["case"] in ("thin", "empty") and l["sheet_number"] == "E-1.3"]
