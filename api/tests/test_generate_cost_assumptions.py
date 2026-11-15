"""Task 5 of docs/plans/rom-estimate.md -- labor and material
assumptions, read off the bases the existing resolvers already report
rather than recomputed.

The line this file draws: a number is **counted** when it came from this
job -- a supplier's quote for this item, a price an estimator typed, a
market lookup for this item -- and **assumed** when it was derived from
the firm's tables, a class average, or a rule. A market estimate is
therefore counted and still widens the budget range, because the origin
tag and the basis spread answer two different questions.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.estimate.basis import validate_assumption
from app.estimate.generate_cost import cost_exposures, labor_assumptions, material_assumptions
from app.takeoff.models import (
    CompanyLaborHoursOverride,
    CompanyLaborRate,
    CompanyMaterialPrice,
    Item,
    ItemMarketPrice,
    ProjectLaborLine,
    ProjectMaterialPrice,
    ReviewStatus,
)


def _item(project, sheet, *, name="20A duplex receptacle", system="Power",
          material="100", labor_cost="40", labor_hours="2", qty="1"):
    return Item(
        project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=name,
        system=system, category="Devices", quantity=Decimal(qty), unit="EA",
        status=ReviewStatus.READY, x=100, y=100,
        material_cost=Decimal(material), labor_cost=Decimal(labor_cost),
        labor_hours=Decimal(labor_hours),
        total_cost=Decimal(material) + Decimal(labor_cost),
    )


def one(rows, *, title_contains):
    matches = [r for r in rows if title_contains.lower() in r["title"].lower()]
    assert len(matches) == 1, f"expected exactly one {title_contains!r}, got {[r['title'] for r in rows]}"
    return matches[0]


@pytest.fixture
def estimated_project(db, project, sheet):
    """The common case: the engine priced it, nothing in the firm's
    tables or a supplier's quote touched it."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    db.add(_item(project, sheet))
    db.flush()
    return project


# --- labor -------------------------------------------------------------


def test_firm_hours_table_becomes_an_assumption(db, estimated_project, sheet, org):
    db.add(CompanyLaborHoursOverride(org_id=org.id, item_name="20A duplex receptacle",
                                     hours_per_unit=Decimal("0.5")))
    db.flush()
    a = one(labor_assumptions(db, estimated_project), title_contains="hours")
    assert a["basis"] == "firm_default"
    assert a["section"] == "labor"


def test_firm_default_rate_becomes_an_assumption(db, estimated_project, sheet, org):
    """A crew rate weighted off the firm's own role rates is the firm's
    history, not a rate quoted for this job."""
    db.add(CompanyLaborRate(org_id=org.id, journeyman_rate=Decimal("68"),
                            foreman_rate=Decimal("82"), apprentice_rate=Decimal("41")))
    item = db.query(Item).first()
    db.add(ProjectLaborLine(item_id=item.id, crew_journeyman=2, crew_foreman=1))
    db.flush()
    a = one(labor_assumptions(db, estimated_project), title_contains="rate")
    assert a["basis"] == "firm_default"


def test_project_rate_override_produces_no_assumption(db, estimated_project, org):
    item = db.query(Item).first()
    db.add(ProjectLaborLine(item_id=item.id, rate_override=Decimal("74.50")))
    db.flush()
    assert not any("rate" in a["title"].lower() for a in labor_assumptions(db, estimated_project))


def test_estimated_hours_take_a_class_average(db, estimated_project):
    """Hours the engine derived, with nothing from the firm, are not the
    firm's own history -- a wider basis, stated as such."""
    a = one(labor_assumptions(db, estimated_project), title_contains="hours")
    assert a["basis"] == "class_average"


def test_labor_that_does_not_resolve_produces_no_assumption(db, project, sheet):
    """No number was assumed, so there is nothing to disclose. The line
    renders as not priced instead (Task 8)."""
    project.pricing_source = "deterministic"
    db.add(_item(project, sheet, labor_cost="0", labor_hours="0"))
    db.flush()
    assert labor_assumptions(db, project) == []


def test_labor_assumptions_are_grouped_not_one_per_item(db, project, sheet, org):
    """Forty receptacles on the firm's hours table is one qualification,
    not forty. A page of identical lines is a page nobody reads."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    for n in range(40):
        db.add(_item(project, sheet, name="20A duplex receptacle"))
    db.flush()
    hours = [a for a in labor_assumptions(db, project) if "hours" in a["title"].lower()]
    assert len(hours) == 1
    assert "40" in hours[0]["found"]


# --- material ----------------------------------------------------------


def test_unquoted_gear_takes_class_average(db, project, sheet):
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    db.add(_item(project, sheet, name="Switchboard SB-1, 1200A",
                 system="Service and distribution", material="48900"))
    db.flush()
    a = one(material_assumptions(db, project), title_contains="Switchboard")
    assert a["basis"] == "class_average"
    assert a["section"] == "material"
    # Named individually, because a GC needs to know which piece of gear
    # carries a price nobody quoted.
    assert a["subject_kind"] == "item"


def test_supplier_quote_produces_no_assumption(db, estimated_project):
    item = db.query(Item).first()
    db.add(ProjectMaterialPrice(item_id=item.id, price_override=Decimal("92"),
                                source="supplier_quote", supplier_name="Codale",
                                quote_date=date(2026, 9, 18)))
    db.flush()
    assert material_assumptions(db, estimated_project) == []


def test_an_estimator_typed_price_produces_no_assumption(db, estimated_project):
    item = db.query(Item).first()
    db.add(ProjectMaterialPrice(item_id=item.id, price_override=Decimal("92"), source="project_price"))
    db.flush()
    assert material_assumptions(db, estimated_project) == []


def test_a_market_estimate_produces_no_assumption(db, estimated_project):
    """A lookup for this item, in this ZIP, on a date -- counted. It
    still widens the range; see the exposure test below."""
    item = db.query(Item).first()
    db.add(ItemMarketPrice(item_id=item.id, outcome="priced", unit_price=Decimal("92"),
                           location_label="ZIP 46032", fetched_at=datetime.now(timezone.utc)))
    db.flush()
    assert material_assumptions(db, estimated_project) == []


def test_a_company_price_is_assumed_and_grouped(db, project, sheet, org):
    """The firm's own price list is their history, not a quote for this
    job -- the same reading the labor rate gets, so the two sections
    cannot disagree about what the firm's tables are."""
    project.pricing_source = "llm"
    for n in range(5):
        db.add(_item(project, sheet, name="20A duplex receptacle"))
    db.add(CompanyMaterialPrice(org_id=org.id, item_name="20A duplex receptacle",
                                unit_price=Decimal("12.40"), effective_date=date.today()))
    db.flush()
    rows = material_assumptions(db, project)
    assert len(rows) == 1
    assert rows[0]["basis"] == "firm_default"
    assert "5" in rows[0]["found"]


def test_material_that_does_not_resolve_produces_no_assumption(db, project, sheet):
    project.pricing_source = "deterministic"
    db.add(_item(project, sheet, name="Unclassified symbol", material="0", labor_cost="0"))
    db.flush()
    assert material_assumptions(db, project) == []


def test_an_excluded_item_is_not_disclosed_as_an_assumption(db, project, sheet):
    """Scope already removed it from the number, so disclosing its price
    basis would describe money that is not in the total."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    item = _item(project, sheet, name="Switchboard SB-1, 1200A", material="48900")
    db.add(item)
    db.flush()
    assert material_assumptions(db, project, exclude={item.id}) == []


# --- exposure ----------------------------------------------------------


def test_market_priced_dollars_widen_the_range_without_being_assumed(db, estimated_project):
    item = db.query(Item).first()
    db.add(ItemMarketPrice(item_id=item.id, outcome="priced", unit_price=Decimal("100"),
                           location_label="ZIP 46032", fetched_at=datetime.now(timezone.utc)))
    db.flush()
    bases = {e.basis for e in cost_exposures(db, estimated_project)}
    assert "market_estimate" in bases


def test_quoted_material_dollars_are_not_reported_under_a_wider_basis(db, project, sheet):
    """A quoted price must not widen the range. The assertion that
    matters is not that `supplier_quote` appears -- its spread is zero
    either way -- but that those dollars never show up as a class
    average, which would widen the range on a price somebody stood
    behind."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    item = _item(project, sheet, material="48900", labor_cost="0", labor_hours="0")
    db.add(item)
    db.flush()
    db.add(ProjectMaterialPrice(item_id=item.id, price_override=Decimal("48900"),
                                source="supplier_quote", supplier_name="Codale"))
    db.flush()
    wide = [e for e in cost_exposures(db, project) if e.basis == "class_average"]
    assert sum((e.dollars for e in wide), Decimal("0")) == Decimal("0")


def test_exposure_is_dollars_not_a_count(db, project, sheet):
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    db.add(_item(project, sheet, name="Switchboard SB-1", material="48900", labor_cost="0", labor_hours="0"))
    db.flush()
    material = [e for e in cost_exposures(db, project) if e.basis == "class_average"]
    assert sum(e.dollars for e in material) == Decimal("48900")


def test_exposures_are_empty_for_a_project_with_no_items(db, project):
    assert cost_exposures(db, project) == []


# --- the boundary ------------------------------------------------------


def test_every_generated_assumption_validates(db, estimated_project, org):
    db.add(CompanyLaborRate(org_id=org.id, journeyman_rate=Decimal("68"),
                            foreman_rate=Decimal("82"), apprentice_rate=Decimal("41")))
    item = db.query(Item).first()
    db.add(ProjectLaborLine(item_id=item.id, crew_journeyman=2))
    db.flush()
    rows = labor_assumptions(db, estimated_project) + material_assumptions(db, estimated_project)
    assert rows
    for a in rows:
        validate_assumption(a)  # raises if basis or where is missing


def test_no_generated_copy_names_a_model_or_a_confidence(db, estimated_project, org):
    db.add(CompanyLaborHoursOverride(org_id=org.id, item_name="20A duplex receptacle",
                                     hours_per_unit=Decimal("0.5")))
    db.flush()
    rows = labor_assumptions(db, estimated_project) + material_assumptions(db, estimated_project)
    blob = " ".join(f"{a['title']} {a['found']} {a['why']} {a['where']}" for a in rows).lower()
    for forbidden in ("model", "confidence", "claude", "gpt", "token", "prompt", "llm", "%"):
        assert forbidden not in blob, forbidden


# --- the review's findings, pinned -------------------------------------


def test_labor_exposure_reports_both_the_hours_and_the_rate_basis(db, project, sheet, org):
    """Codex review, finding 8. The cost is hours times rate, so a line
    whose hours came from the firm's table (10%) and whose rate was
    derived (20%) is loose on both counts. An earlier version took one
    basis `or` the other and silently discarded the second, narrowing
    the range on an assumption nobody had checked."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    db.add(CompanyLaborHoursOverride(org_id=org.id, item_name="20A duplex receptacle",
                                     hours_per_unit=Decimal("2")))
    db.add(_item(project, sheet, labor_cost="1000", labor_hours="2"))
    db.flush()
    bases = {e.basis for e in cost_exposures(db, project)}
    assert "firm_default" in bases     # the hours
    assert "class_average" in bases    # the rate


def test_an_inferred_identity_widens_the_range_even_when_quoted(db, project, sheet):
    """Codex review, finding 5. A quoted price for the wrong item is not
    a reliable number, so the inference carries its own exposure on top
    of whatever priced it."""
    item = _item(project, sheet, name="Switchboard", material="48900", labor_cost="0", labor_hours="0")
    item.classification_basis = "inferred"
    db.add(item)
    db.flush()
    db.add(ProjectMaterialPrice(item_id=item.id, price_override=Decimal("48900"),
                                source="supplier_quote", supplier_name="Codale"))
    db.flush()
    inferred = [e for e in cost_exposures(db, project) if e.basis == "inferred"]
    assert inferred
    assert inferred[0].dollars == Decimal("48900")


def test_a_class_average_discloses_the_resolved_price_not_the_stored_column(db, project, sheet):
    """Codex review, finding 1, applied to the disclosure: the value
    printed beside a line has to be the number the estimate carried."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    db.add(_item(project, sheet, name="Switchboard SB-1", material="48900",
                 labor_cost="0", labor_hours="0"))
    db.flush()
    a = one(material_assumptions(db, project), title_contains="Switchboard")
    assert "48,900" in a["value"]


def test_a_class_average_names_the_sheet_it_was_counted_on(db, project, sheet):
    """Codex review, finding 12. "Material pricing" alone does not let a
    GC find which switchboard."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    db.add(_item(project, sheet, name="Switchboard SB-1", material="48900",
                 labor_cost="0", labor_hours="0"))
    db.flush()
    a = one(material_assumptions(db, project), title_contains="Switchboard")
    assert sheet.number in a["where"]


def test_two_labor_disclosures_in_one_section_have_distinct_identities(db, project, sheet, org):
    """Codex review, finding 9. The firm-table and derived hours
    disclosures share the title "Installation hours" -- it is the right
    words for both -- so the title cannot be the identity."""
    project.pricing_source = "llm"
    project.pricing_note = "Indiana regional basis"
    db.add(CompanyLaborRate(org_id=org.id, journeyman_rate=Decimal("68"),
                            foreman_rate=Decimal("82"), apprentice_rate=Decimal("41")))
    item = _item(project, sheet)
    db.add(item)
    db.flush()
    db.add(ProjectLaborLine(item_id=item.id, crew_journeyman=2))
    db.flush()
    rows = labor_assumptions(db, project)
    refs = [a["subject_ref"] for a in rows]
    assert len(set(refs)) == len(refs)
