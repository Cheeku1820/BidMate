"""The typed records the five agents hand to each other. Pure dataclasses,
no I/O -- these run without a database or an API key."""

from app.engine.contracts import Assembly, AssemblyLine, LegendEntry, Proposal


def test_legend_entry_carries_symbol_description_and_kind():
    e = LegendEntry(symbol="WP", description="WEATHERPROOF", kind="abbreviation")
    assert e.symbol == "WP"
    assert e.kind == "abbreviation"


def test_assembly_sums_its_lines():
    a = Assembly(parent_catalog_id="receptacle_20a", lines=[
        AssemblyLine("box_4sq", "4in square box", 1, "ea", 3.10, 0.15),
        AssemblyLine("thhn_12", "#12 THHN", 30, "ft", 0.18, 0.004),
    ])
    assert a.material_cost == round(3.10 * 1 + 0.18 * 30, 2)
    assert a.labor_hours == round(0.15 * 1 + 0.004 * 30, 3)


def test_assembly_with_no_lines_is_zero_not_an_error():
    a = Assembly(parent_catalog_id="unclassified", lines=[])
    assert a.material_cost == 0.0
    assert a.labor_hours == 0.0


def test_proposal_carries_targets_and_never_a_write():
    p = Proposal(intent="reclassify", target_item_ids=["a", "b"], field="name",
                 value="2x4 LED troffer", summary="Set 2 items to 2x4 LED troffer")
    assert len(p.target_item_ids) == 2
    assert p.field == "name"


def test_assembly_rounding_is_load_bearing():
    """Values chosen to produce real floating-point residue, so this fails
    if material_cost stops rounding to 2 places or labor_hours to 3. The
    simple case above passes at any precision, which makes it readable but
    not a guard -- assemblies feed every material total, so the contract
    needs one test that actually holds it."""
    a = Assembly(parent_catalog_id="receptacle_20a", lines=[
        AssemblyLine("thhn_12", "#12 THHN", 3, "ft", 0.1, 0.0013),
        AssemblyLine("wirenut", "Wire connector", 7, "ea", 0.1, 0.0013),
    ])
    # raw material sum is 0.1*3 + 0.1*7 = 1.0000000000000002 in float
    assert a.material_cost == 1.0
    # raw hours sum is 0.0013*3 + 0.0013*7 = 0.013000000000000001 -> 0.013 at 3 places
    assert a.labor_hours == 0.013


def test_assembly_labor_hours_keeps_three_decimals_not_two():
    """A labor line is thousandths of an hour per foot of wire. Rounding
    hours to 2 places would collapse a real quantity to zero, so the third
    decimal is a requirement, not a preference."""
    a = Assembly(parent_catalog_id="x", lines=[
        AssemblyLine("thhn_12", "#12 THHN", 1, "ft", 0.0, 0.004),
    ])
    assert a.labor_hours == 0.004, "hours must keep 3 decimals; 2 would round this to 0.0"
