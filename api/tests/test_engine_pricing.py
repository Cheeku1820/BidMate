"""Pricing agent: device cost plus the assembly behind it."""

from app.engine.assemblies import expand
from app.engine.contracts import ClassifiedItem, Placement
from app.engine.pricing import price_item


def _item(catalog_id="receptacle_20a", qty=10):
    return ClassifiedItem(
        catalog_id=catalog_id, name="20A duplex receptacle", system="Power",
        category="Devices", unit="ea", symbol="receptacle", quantity=qty,
        sheet_page_index=0, placements=[Placement(1, 1)] * qty,
        status="ready", warning=None, source_tag="R",
    )


def test_priced_item_includes_its_assembly_material():
    """A bare receptacle is a few dollars; with box, plate, wire and
    conduit behind it the real installed material is far higher. Pricing
    the device alone is the understatement this task removes."""
    from app.engine.catalog import CATALOG

    priced = price_item(_item(), labor_rate=68.0)
    bare = CATALOG["receptacle_20a"].material_cost * 10
    assert priced.material_cost > bare * 2, "assembly material is missing from the total"


def test_assembly_is_attached_for_inspection():
    priced = price_item(_item(), labor_rate=68.0)
    assert priced.assembly is not None
    assert any(l.catalog_id == "thhn_12" for l in priced.assembly.lines)


def test_total_equals_material_plus_labor():
    priced = price_item(_item(), labor_rate=68.0)
    assert priced.total_direct_cost == round(priced.material_cost + priced.labor_cost, 2)


def test_labor_hours_include_assembly_hours():
    from app.engine.catalog import CATALOG

    priced = price_item(_item(), labor_rate=68.0)
    device_only = CATALOG["receptacle_20a"].labor_hours * 10
    assert priced.labor_hours > device_only


def test_material_matches_the_assembly_it_reports():
    from app.engine.catalog import CATALOG

    priced = price_item(_item(), labor_rate=68.0)
    expected = round(CATALOG["receptacle_20a"].material_cost * 10 + expand("receptacle_20a", 10).material_cost, 2)
    assert priced.material_cost == expected


def test_an_unclassified_item_is_still_unpriced():
    priced = price_item(_item(catalog_id="unclassified", qty=5), labor_rate=68.0)
    assert priced.material_cost == 0.0
    assert priced.total_direct_cost == 0.0
    # An unpriced item carries no assembly at all -- not an empty one.
    # That distinction is the shape that would have caught fixtures being
    # priced bare: a catalog item with no ASSEMBLIES entry expands to an
    # Assembly with zero lines, which is not None and passed every
    # `assembly is not None` assertion in the suite.
    assert priced.assembly is None
