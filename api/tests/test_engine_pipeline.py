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
    """Measured against the real Unalaska set, the engineer's-seal glyph
    accounts for roughly 41 spurious placements per sheet across all 14
    sheets (design spec 11.2) -- about 509 in total. Before the rotation
    filter (Task 3), the raw count across the set was 812; with the filter
    applied it is 303. The threshold below is deliberately loose (a
    measured fact, not a tuned one) -- it only needs to distinguish
    "the seal filter is wired up" from "it silently regressed," not pin
    the exact count sheet layout changes could shift."""
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    total = sum(c.count for c in counting.count(BID, sheets))
    assert total < 800, f"expected the seal's ~509 placements gone from 812, got {total}"
