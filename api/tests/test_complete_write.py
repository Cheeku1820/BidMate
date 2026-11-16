"""Task 10 of docs/plans/estimate-without-asking.md -- writing the
companion allowances, and surviving a re-run.

The rule this file exists to hold: **the engine never discards a
person's judgment** (CLAUDE.md). A completion pass is engine output, so
it gets the same two protections `merge.py` gives a counted row and
`write.py` gives an overridden assumption --

- a companion an estimator approved, edited, or rejected is left exactly
  as it is, never overwritten and never duplicated beside itself;
- a companion an estimator deleted is not resurrected, because deleting
  it is a judgment about the drawing ("that work genuinely isn't there")
  and it survives the engine running again.

Deliberately NOT routed through `merge_sheet`: its merge key is
`(sheet_number, source_tag)`, and a synthetic tag there would fabricate
a symbol cluster that `resolve_apply.py` would then offer to apply
across the whole set.
"""
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.estimate.complete import completion_assumptions, completion_lines, write_completion
from app.estimate.write import generate, regenerate
from app.takeoff.models import Assumption, Item, ReviewStatus, Sheet
from app.takeoff.totals import rom_totals


@pytest.fixture(autouse=True)
def _engine_priced(project):
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    return project


def _sheet(db, project, *, number, kind="plan", scale="", title="Power plan"):
    s = Sheet(project_id=project.id, number=number, title=title, discipline="Electrical",
              revision="Rev 1", scale=scale, scale_options=[], plan="", kind=kind)
    db.add(s)
    db.flush()
    return s


def _item(db, project, sheet, *, quantity=47, cost="0", name="Symbol A", **kw):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=name,
             system="Power", category="Devices", quantity=Decimal(quantity), unit="EA",
             status=ReviewStatus.READY, material_cost=Decimal(cost),
             labor_hours=Decimal("0"), labor_cost=Decimal("0"), total_cost=Decimal(cost), **kw)
    db.add(i)
    db.flush()
    return i


@pytest.fixture
def one_gap(db, project):
    """One unidentified cluster and one priced line to be relative to --
    the smallest project that produces exactly one companion."""
    sheet = _sheet(db, project, number="E-2.1")
    _item(db, project, sheet, quantity=47, cost="0")
    _item(db, project, sheet, quantity=10, cost="120", name="20A duplex receptacle")
    return sheet


def _assumed(db):
    return list(db.scalars(select(Item).where(Item.origin == "assumed")))


def _assumed_count(db):
    return db.scalar(
        select(func.count()).select_from(Item).where(Item.origin == "assumed"))


# --- writing ---------------------------------------------------------------

def test_a_companion_is_written_as_a_real_item(db, project, one_gap):
    assert write_completion(db, project) == 1
    db.commit()
    [item] = _assumed(db)
    assert item.sheet_id == one_gap.id
    assert item.origin == "assumed"
    assert item.confidence == 5
    assert item.confidence_reasons


def test_a_companion_never_arrives_approved(db, project, one_gap):
    write_completion(db, project)
    db.commit()
    [item] = _assumed(db)
    assert item.status is ReviewStatus.READY
    assert item.approved_by_user_id is None


def test_a_companion_moves_the_rom_total(db, project, one_gap):
    """The whole point. Before this slice an unidentified cluster
    contributed zero dollars and the estimate read as if that part of
    the sheet were free."""
    before = rom_totals(db, project).direct_cost
    write_completion(db, project)
    db.commit()
    assert rom_totals(db, project).direct_cost > before


def test_a_companion_has_no_position_on_the_page(db, project, one_gap):
    """Nothing was read, so there is no coordinate and no evidence crop.
    The row shows why the work is believed to be there instead."""
    write_completion(db, project)
    db.commit()
    [item] = _assumed(db)
    assert item.x is None and item.y is None
    assert item.path is None


def test_a_companion_carries_no_symbol_tag(db, project, one_gap):
    """`source_tag` drives cluster identity and "find every one like
    this". A synthetic value there would fabricate a symbol cluster."""
    write_completion(db, project)
    db.commit()
    assert _assumed(db)[0].source_tag == ""


# --- surviving a re-run ----------------------------------------------------

def test_a_rerun_does_not_duplicate_a_companion_line(db, project, one_gap):
    write_completion(db, project)
    db.commit()
    write_completion(db, project)
    db.commit()
    assert _assumed_count(db) == 1


def test_an_approved_companion_survives_a_rerun_untouched(db, project, one_gap, dana):
    """Review focus 3."""
    write_completion(db, project)
    db.commit()
    item = _assumed(db)[0]
    item.status = ReviewStatus.APPROVED
    item.approved_by_user_id = dana.id
    item.quantity = Decimal("61")
    db.commit()

    write_completion(db, project)
    db.commit()
    db.refresh(item)
    assert item.status is ReviewStatus.APPROVED
    assert item.quantity == Decimal("61")
    assert _assumed_count(db) == 1


def test_an_edited_companion_survives_a_rerun_untouched(db, project, one_gap):
    """An edit bumps `version`, which is how a touched row is told from
    one the engine still owns."""
    write_completion(db, project)
    db.commit()
    item = _assumed(db)[0]
    item.quantity = Decimal("12")
    item.version += 1
    db.commit()

    write_completion(db, project)
    db.commit()
    db.refresh(item)
    assert item.quantity == Decimal("12")
    assert _assumed_count(db) == 1


def test_a_rejected_companion_is_not_rewritten(db, project, one_gap):
    from datetime import datetime, timezone

    write_completion(db, project)
    db.commit()
    item = _assumed(db)[0]
    item.rejected_at = datetime.now(timezone.utc)
    db.commit()

    write_completion(db, project)
    db.commit()
    assert _assumed_count(db) == 1


def test_a_deleted_companion_is_not_resurrected(db, project, one_gap, dana):
    """Review focus 4. Deleting it is a judgment about the drawing and it
    survives the engine seeing the same gap again -- exactly as an
    approval survives reprocessing."""
    from app.takeoff.review import delete_item

    write_completion(db, project)
    db.commit()
    item = _assumed(db)[0]
    delete_item(db, actor=dana, item=item, expected_version=item.version)
    db.commit()

    write_completion(db, project)
    db.commit()
    assert _assumed_count(db) == 0


def test_a_stale_companion_whose_gap_closed_is_removed(db, project, one_gap):
    """The gap is gone, so the allowance for it must go too -- otherwise
    classifying a symbol adds its real price and leaves the guess in the
    number beside it."""
    write_completion(db, project)
    db.commit()
    assert _assumed_count(db) == 1

    unpriced = db.scalars(
        select(Item).where(Item.origin == "counted", Item.name == "Symbol A")).one()
    unpriced.material_cost = Decimal("564")
    unpriced.total_cost = Decimal("564")
    db.commit()

    write_completion(db, project)
    db.commit()
    assert _assumed_count(db) == 0


# --- the paired disclosure -------------------------------------------------

def test_each_companion_has_a_paired_disclosure(db, project, one_gap):
    regenerate(db, project)
    db.commit()
    assumed = _assumed(db)
    rows = list(db.scalars(
        select(Assumption).where(Assumption.project_id == project.id,
                                 Assumption.section == "takeoff")))
    assert len(assumed) > 0
    assert len(rows) >= len(assumed)


def test_the_disclosure_answers_all_four_questions(db, project, one_gap):
    [row] = completion_assumptions(db, project)
    for field in ("section", "title", "found", "why", "basis", "where"):
        assert str(row[field]).strip()
    assert row["origin"] == "assumed"
    assert row["section"] == "takeoff"


def test_an_excluded_companion_is_not_disclosed(db, project, one_gap):
    """Scope removed it, so its basis would describe money that is not in
    the number -- the same argument the other generators make."""
    ids = {line["sheet_id"] for line in completion_lines(db, project)}
    unpriced = db.scalars(
        select(Item).where(Item.origin == "counted", Item.name == "Symbol A")).one()
    assert ids
    assert completion_assumptions(db, project, exclude={unpriced.id}) == []


def test_generate_includes_the_completion_disclosures(db, project, one_gap):
    """They have to reach `generate`'s own validated list, or the ROM
    carries guessed money with no disclosure beside it -- which is the
    anti-goal the spec names first."""
    write_completion(db, project)
    db.flush()
    titles = [row["title"] for row in generate(db, project)]
    assert any("E-2.1" in title for title in titles)


def test_regenerate_writes_the_items_before_the_disclosures(db, project, one_gap):
    """Ordering matters: the disclosures describe the items, so the items
    have to exist when they are built."""
    written = regenerate(db, project)
    db.commit()
    assert _assumed_count(db) == 1
    assert written > 0


# --- Whole-branch review findings 2, 3, 7 ---------------------------------

def test_a_takeoff_rerun_does_not_delete_a_companion(db, project, one_gap):
    """Review finding 2, and the worst of the judgment-loss bugs.

    `merge_sheet` loaded every item on the sheet, companions included.
    Companions carry no symbol tag, so they sat unmatched in the merge
    key's bucket and the leftover sweep deleted every unapproved one --
    a plain re-run of the takeoff silently destroyed an estimator's
    edited or rejected allowance, and the next completion pass recreated
    it as if nothing had happened. Invariant 4.
    """
    from app.takeoff import merge
    from app.takeoff.ingest import map_payload

    write_completion(db, project)
    db.commit()
    companion = _assumed(db)[0]
    companion.quantity = Decimal("99")
    companion.version += 1
    db.commit()

    payload = {
        "sheets": [{"id": "0", "number": one_gap.number, "takeoff_id": "", "page": 0,
                    "width_pt": 2000, "height_pt": 1500, "unreadable": None,
                    "kind": "plan", "title": "Power plan"}],
        "items": [],
    }
    mapped = map_payload(payload)
    sheets = merge.upsert_sheet_rows(db, project, mapped.sheets)
    merge.merge_sheet(db, project=project, sheet=sheets["0"], rows=[], ai_reading=None)
    db.commit()

    db.refresh(companion)
    assert companion.quantity == Decimal("99")
    assert _assumed_count(db) == 1


def test_a_takeoff_rerun_does_not_overwrite_a_companion_as_a_counted_row(db, project, one_gap):
    """The other half of finding 2: an incoming engine row with no tag
    shares the companion's merge key, so the merge could have matched the
    two and rewritten a guessed allowance as a counted device."""
    from app.takeoff import merge
    from app.takeoff.ingest import map_payload

    write_completion(db, project)
    db.commit()

    untagged = {"name": "Untagged device", "system": "Power", "category": "Devices",
                "unit": "ea", "quantity": 3, "status": "ready", "sheet_id": "0",
                "symbol": "receptacle", "warning": None, "x": 10, "y": 10,
                "placements": [[10, 10]], "tag": "", "material_cost": 30.0,
                "labor_hours": 1.0, "labor_cost": 78.0, "total_cost": 108.0}
    payload = {
        "sheets": [{"id": "0", "number": one_gap.number, "takeoff_id": "", "page": 0,
                    "width_pt": 2000, "height_pt": 1500, "unreadable": None,
                    "kind": "plan", "title": "Power plan"}],
        "items": [untagged],
    }
    mapped = map_payload(payload)
    sheets = merge.upsert_sheet_rows(db, project, mapped.sheets)
    merge.merge_sheet(db, project=project, sheet=sheets["0"], rows=mapped.items, ai_reading=None)
    db.commit()

    [companion] = _assumed(db)
    assert companion.name != "Untagged device"
    assert companion.origin == "assumed"


def test_editing_a_companions_system_does_not_split_it_in_two(db, project, one_gap):
    """Review finding 3. Identity included the mutable `system` column,
    so moving a Power allowance to Lighting made the next run's Power
    identity unmatched -- and it wrote a second row beside the
    estimator's."""
    write_completion(db, project)
    db.commit()
    item = _assumed(db)[0]
    item.system = "Lighting"
    item.version += 1
    db.commit()

    write_completion(db, project)
    db.commit()
    assert _assumed_count(db) == 1
    assert _assumed(db)[0].system == "Lighting"


def test_deleting_a_companion_whose_system_was_edited_still_suppresses_it(db, project, one_gap, dana):
    """The sharper half of finding 3: the deletion snapshot recorded the
    edited system, so the identity it suppressed was not the identity the
    next run proposed, and the allowance came back from the dead."""
    from app.takeoff.review import delete_item

    write_completion(db, project)
    db.commit()
    item = _assumed(db)[0]
    item.system = "Lighting"
    item.version += 1
    db.commit()
    delete_item(db, actor=dana, item=item, expected_version=item.version)
    db.commit()

    write_completion(db, project)
    db.commit()
    assert _assumed_count(db) == 0


def test_repricing_a_companion_bumps_its_version(db, project, one_gap):
    """Review finding 7. Every other write path bumps `version` so a
    client holding a stale one is refused (`app.takeoff.concurrency`).
    Without it a reviewer could approve a $564 allowance while looking
    at the $100 one, and get no stale-version refusal."""
    write_completion(db, project)
    db.commit()
    item = _assumed(db)[0]
    before = item.version
    first_cost = item.material_cost

    unpriced = db.scalars(
        select(Item).where(Item.origin == "counted", Item.name == "Symbol A")).one()
    priced = db.scalars(
        select(Item).where(Item.name == "20A duplex receptacle")).one()
    priced.material_cost = Decimal("1200")
    priced.total_cost = Decimal("1200")
    db.commit()

    write_completion(db, project)
    db.commit()
    db.refresh(item)
    assert item.material_cost != first_cost
    assert item.version > before
    assert unpriced.origin == "counted"


def test_a_reprice_still_leaves_the_row_engine_owned(db, project, one_gap):
    """The trap the version bump creates: if "untouched" meant
    `version == 1`, the first reprice would make the engine's own row
    look like a person's and freeze it forever. The engine records the
    version it wrote, so its own writes stay its own."""
    write_completion(db, project)
    db.commit()
    write_completion(db, project)
    db.commit()
    write_completion(db, project)
    db.commit()
    assert _assumed_count(db) == 1

    # And it is still removable when the gap closes.
    unpriced = db.scalars(
        select(Item).where(Item.origin == "counted", Item.name == "Symbol A")).one()
    unpriced.material_cost = Decimal("564")
    unpriced.total_cost = Decimal("564")
    db.commit()
    write_completion(db, project)
    db.commit()
    assert _assumed_count(db) == 0
