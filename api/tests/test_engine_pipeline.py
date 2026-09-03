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


def test_no_priced_item_is_missing_its_assembly():
    """A priced item with no assembly is a device costed bare -- no box, no
    wire, no conduit. Every fixture on this set was priced that way because
    luminaire_generic had no assembly entry and the coverage test whitelisted
    it. `test_every_priced_device_carries_its_assembly` did not catch it:
    an item with no assembly lines still carries a non-None Assembly."""
    from app.engine import pipeline

    result = pipeline.run(BID, labor_rate=68.0)
    bare = [p for p in result.items
            if p.total_direct_cost > 0 and (p.assembly is None or not p.assembly.lines)]
    assert bare == [], f"{len(bare)} priced items carry no assembly"


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


def test_no_parsed_legend_text_reaches_an_item_name_or_a_warning():
    """The abbreviations block is a line-pair heuristic over messy sheet
    text, and on this set it mis-pairs badly: R -> "Aaron S. Jordan" (the
    engineer of record, off a seal block), C -> "(c)2020 ECI, Inc.", G ->
    "STACKS/ADULT" (a room name), M -> "TOTAL NEC AMPS: 39 A".

    A warning's `found` is contractually what was found, so a fabricated
    pairing stated in the estimator's own words is worse than no warning --
    they go looking for a legend row that is not there. And an item's name
    must come from the catalog taxonomy: interpolating the expansion is how
    "AMP — Pole Va - Phase A" reached the CLI as an item name.

    Scanned against the *distinctive* parsed descriptions only -- those
    carrying a space, digit or punctuation. A description that is one plain
    English word cannot be told apart from ordinary template copy by
    substring: this set parses "DESCRIPTION" (a legend column header) as an
    expansion, and the fixture warning legitimately says "its description
    wasn't read from a schedule". The single-word cases that matter
    (WEATHERPROOF, CIRCUIT) are pinned exactly in test_engine_classify.py
    instead, where the legend is a fixture rather than 124 parsed rows.
    """
    import re

    from app.engine import classification, counting, documents

    sheets = documents.detect_sheets(BID)
    descriptions = {e.description for s in sheets for e in s.legend
                    if e.kind == "abbreviation" and len(e.description) > 3
                    and re.search(r"[\s\d./(),]", e.description)}
    assert descriptions, "no legend rows parsed -- this test would be vacuous"

    items = classification.classify(counting.count(BID, sheets), sheets)
    for it in items:
        for d in descriptions:
            assert d.lower() not in it.name.lower(), \
                f"item name {it.name!r} carries parsed legend text {d!r}"
            if it.warning:
                for field in ("found", "why", "fix", "where"):
                    assert d.lower() not in it.warning[field].lower(), \
                        f"warning {field} carries parsed legend text {d!r}"


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
