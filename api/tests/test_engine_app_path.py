"""app/engine/estimate.py -- the path the API and the review workspace
actually run.

`pipeline.py` is the CLI's path and has its own end-to-end tests. This
module is the other one, and for a while the two priced different things:
`estimate.py` did its own catalog arithmetic and never called the Pricing
agent, so the product shipped every device bare -- no box, no plate, no
wire, no conduit -- while the CLI counted all of it. These tests pin the
two together.

Everything here except the last two cases runs without the real bid set,
so the guard holds in a container that has no drawings.
"""

import pytest

from app.engine import estimate
from app.engine.catalog import CATALOG
from app.engine.contracts import ClassifiedItem, DetectedSheet, DeviceCluster, Placement

SHEET = DetectedSheet(
    page_index=0, number="E2.1", title="Power plan", discipline="Electrical",
    scale='1/8" = 1\'-0"', width_pt=2448, height_pt=1584, region=(0, 0, 2448, 1584),
)


def _cluster(tag="R", n=10):
    return DeviceCluster(tag=tag, sheet_page_index=0, placements=[Placement(100, 100)] * n)


def _item(catalog_id="receptacle_20a", quantity=10):
    cat = CATALOG[catalog_id]
    return ClassifiedItem(
        catalog_id=catalog_id, name=cat.name, system=cat.system, category=cat.category,
        unit=cat.unit, symbol=cat.symbol, quantity=quantity, sheet_page_index=0,
        placements=[Placement(100, 100)] * quantity, status="ready", warning=None,
        source_tag="R",
    )


def test_the_deterministic_row_carries_its_assembly_material():
    """The regression this module exists for. A row priced at the bare
    catalog price is a receptacle with no box, no plate, and no branch
    wire behind it, and that is what the running product shipped."""
    row = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    bare = CATALOG["receptacle_20a"].material_cost * 10
    assert row["material_cost"] > bare * 2, "assembly material is missing from the row"


def test_the_deterministic_row_carries_its_assembly_hours():
    row = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    assert row["labor_hours"] > CATALOG["receptacle_20a"].labor_hours * 10


def test_material_factor_applies_to_the_assembly_too_and_only_once():
    """A box and a reel of #12 cost 45% more in Unalaska for the same
    reason the receptacle does. Applying the factor to the device half
    alone understates the job; applying it twice to that half overstates
    it. Both are caught by comparing against the unfactored row."""
    plain = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    local = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.45)
    assert local["material_cost"] == pytest.approx(plain["material_cost"] * 1.45, abs=0.02)


def test_a_location_does_not_change_how_long_an_install_takes():
    plain = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    local = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.45)
    assert local["labor_hours"] == plain["labor_hours"]


def test_labor_cost_uses_the_caller_rate_not_the_pricing_default():
    """`pricing.DEFAULT_LABOR_RATE` is a national placeholder. The app has
    already resolved the project's own rate by this point, and pricing a
    $98/hr job at $68 is a 30% error in the larger half of the total."""
    from app.engine.pricing import DEFAULT_LABOR_RATE

    row = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=98.0, material_factor=1.0)
    assert row["labor_cost"] == pytest.approx(row["labor_hours"] * 98.0, abs=0.02)
    assert row["labor_cost"] != pytest.approx(row["labor_hours"] * DEFAULT_LABOR_RATE, abs=0.02)


def test_an_unclassified_item_is_priced_at_zero_not_guessed():
    """Unchanged behaviour, pinned because it now runs through
    pricing.price_item: an item with no catalog entry contributes nothing
    rather than being invented a cost."""
    item = ClassifiedItem(
        catalog_id="unclassified", name="Unclassified symbol (VA)", system="Unknown",
        category="Unclassified", unit="ea", symbol="generic", quantity=12,
        sheet_page_index=0, placements=[Placement(1, 1)] * 12, status="attention",
        warning=None, source_tag="VA",
    )
    row = estimate._row_from_catalog(item, _cluster("VA", 12), [SHEET], labor_rate=98.0, material_factor=1.45)
    assert row["material_cost"] == 0
    assert row["labor_hours"] == 0
    assert row["total_cost"] == 0


def test_the_row_keys_are_unchanged():
    """ingest.py reads these by name. Adding to the row is safe; renaming
    or dropping one silently zeroes a column in the review workspace."""
    row = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    required = {
        "name", "system", "category", "unit", "quantity", "status", "sheet", "page",
        "sheet_id", "tag", "x", "y", "placements", "material_cost", "labor_hours",
        "labor_cost", "total_cost", "symbol", "warning",
    }
    assert required <= set(row)
