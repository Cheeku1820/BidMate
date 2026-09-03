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
