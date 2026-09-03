"""End to end: Documents -> Counting -> Classification -> Pricing, against
the real bid set. Asserted facts, not tuned thresholds."""

import os
import pytest

BID = ("/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/"
       "21_1001_unalaska_library_cd_biddrawings.pdf")

pytestmark = pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")


def test_pipeline_runs_end_to_end_on_a_real_set():
    from app.engine import pipeline

    result = pipeline.run(BID, labor_rate=68.0)
    assert len(result.sheets) == 14, "the Unalaska set has 14 electrical sheets"
    assert result.items, "the pipeline produced no items"
    assert result.total_direct_cost > 0


def test_every_priced_device_carries_its_assembly():
    from app.engine import pipeline

    result = pipeline.run(BID, labor_rate=68.0)
    priced = [p for p in result.items if p.total_direct_cost > 0]
    assert priced, "no item was priced at all"
    assert all(p.assembly is not None for p in priced)


def test_wire_and_conduit_reach_the_total():
    """The material an electrical estimator most needs and the engine
    previously omitted entirely."""
    from app.engine import pipeline

    result = pipeline.run(BID, labor_rate=68.0)
    ids = {l.catalog_id for p in result.items if p.assembly for l in p.assembly.lines}
    assert "thhn_12" in ids or "thhn_10" in ids, "no branch wire in the takeoff"
    assert "emt_1_2" in ids, "no conduit in the takeoff"


def test_the_seal_is_gone_from_the_whole_set():
    """Measured against the real Unalaska set, the rotation filter removes
    509 placements across the 14 sheets -- about 36 per sheet on average
    (509 / 14), mostly the engineer's-seal glyph (design spec 11.2's
    earlier estimate of 41 candidates per sheet was Task 3's starting
    figure, not the measured removed count). Before the filter, the raw
    count across the set was 812; with it applied, 303. The threshold is
    tightened to a measured fact rather than a loose bound: 800 would
    tolerate restoring 496 of the 509 removed placements and still pass.
    400 leaves headroom for sheet-layout variance while still catching a
    real regression in the filter."""
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    total = sum(c.count for c in counting.count(BID, sheets))
    assert total < 400, f"expected the rotation filter's ~509 removed placements to hold (812 -> 303), got {total}"


def test_the_takeoff_prices_the_devices_it_counted():
    """total_direct_cost > 0 was true at $1,643 while 43 of 45 items were
    silently zeroed, so it pins nothing. Junction box is the check: 55
    placements across the set, counted independently, and it is a plain
    device tag that must never lose to a parsed legend entry."""
    from app.engine import pipeline

    result = pipeline.run(BID, labor_rate=68.0)
    jb = [p for p in result.items if p.item.catalog_id == "junction_box"]
    assert sum(p.item.quantity for p in jb) == 55
    assert all(p.total_direct_cost > 0 for p in jb)
    assert result.total_direct_cost > 20_000
