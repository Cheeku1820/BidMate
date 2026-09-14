"""End to end: Documents -> Counting -> Classification -> Pricing, against
the real bid set. Asserted facts, not tuned thresholds."""

import os
import pytest

from tests.bid_set import BID

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
    """Measured against the real Unalaska set, the seal filter removes
    509 placements across the 14 sheets -- about 36 per sheet on average
    (509 / 14), mostly the engineer's-seal glyph (design spec 11.2's
    earlier estimate of 41 candidates per sheet was Task 3's starting
    figure, not the measured removed count). What ships is a font-and-
    proximity filter -- a condensed face is the seal ring's typographic
    signature, and the inner ring is caught by nearness to a confirmed
    condensed-font glyph -- not the rotation filter these docstrings used
    to name; see counting.py's _stamp_centres. Before the filter, the raw
    count across the set was 812; with it applied, 303. The threshold is
    tightened to a measured fact rather than a loose bound: 800 would
    tolerate restoring 496 of the 509 removed placements and still pass.
    400 leaves headroom for sheet-layout variance while still catching a
    real regression in the filter."""
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    total = sum(c.count for c in counting.count(BID, sheets))
    assert total < 400, f"expected the seal filter's ~509 removed placements to hold (812 -> 303), got {total}"


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
    silently zeroed, so it pins nothing. Junction box is the check: 64
    placements across the set, counted independently, and it is a plain
    device tag that must never lose to a parsed legend entry.

    64, not the 55 the mis-framed region left: the correct visual-frame
    region admits 7 J tags in the left third of the plan sheets the old
    region silently cut, and every one of the 64 was checked against a
    rendered crop of its glyph (2026-09-14). Some of E2.1's are set
    beside 1L-9 circuit labels and may be luminaire type J rather than
    boxes -- a Classification question; Counting found isolated J tags
    at exact coordinates, which is its whole job."""
    from app.engine import pipeline

    result = pipeline.run(BID, labor_rate=68.0)
    jb = [p for p in result.items if p.item.catalog_id == "junction_box"]
    assert sum(p.item.quantity for p in jb) == 64
    assert all(p.total_direct_cost > 0 for p in jb)
    assert result.total_direct_cost > 20_000

    # WP is what the precedence fix alone gates. J is protected by the
    # legend parser's _WORDY rule independently -- "J" no longer pairs with
    # "1" -- so the junction-box assertions above pass even under the
    # broken precedence, leaving the aggregate bound as the only guard. WP
    # is in TAG_TO_CATALOG as a GFCI receptacle *and* in the legend as
    # WEATHERPROOF, so it is the tag that must keep its catalog device
    # identity rather than being demoted to an unpriced modifier.
    wp = [p for p in result.items if p.item.source_tag == "WP"]
    assert wp, "WP should still be counted on this set"
    assert all(p.item.catalog_id == "receptacle_gfci" for p in wp), \
        "WP must keep its catalog device identity, not become a modifier"
    assert all(p.total_direct_cost > 0 for p in wp)


def test_the_app_path_counts_the_same_material_as_the_cli():
    """ROADMAP invariant 1: totals are computed in exactly one place. Two
    existed -- the CLI ran the Pricing agent and the app did its own
    catalog arithmetic, so the product's number was missing every box,
    plate, wire and connector on the set.

    They may still differ by the location adjustments the app applies and
    the CLI does not: material scales by the project's material_factor,
    labour by its rate. Nothing else may differ, and in particular the
    hours must match exactly -- a location changes what an hour costs,
    not how many of them the work takes."""
    from app.engine import estimate, pipeline

    cli = pipeline.run(BID, labor_rate=68.0)
    app = estimate.estimate(BID, "Unalaska, AK")
    factor = app["material_factor"]
    rate = app["labor_rate"]

    assert app["totals"]["labor_hours"] == pytest.approx(cli.labor_hours_total, abs=0.05)
    assert app["totals"]["material"] == pytest.approx(cli.material_total * factor, abs=0.5)
    assert app["totals"]["labor_cost"] == pytest.approx(cli.labor_hours_total * rate, abs=0.5)


def test_the_app_path_prices_no_item_bare():
    """The app path returns rows, not PricedItems, so it cannot assert on
    an Assembly object the way test_no_priced_item_is_missing_its_assembly
    does. The equivalent check is arithmetic: every priced row must cost
    more than its device alone, since every catalog item has an assembly.

    Resolution is by TAG, not by item name. Matching `row["name"]` against
    catalog names skipped every fixture row -- classification renames
    those to "Luminaire type A".."H", so none of them matches a catalog
    name -- which left 16 of 27 priced rows unchecked behind a `continue`
    whose comment said it would check them by tag and then did not.
    Deleting all four luminaire assemblies left that version green.

    The count assertion is the part that keeps it honest: a future skip
    cannot quietly shrink the coverage without failing here."""
    from app.engine import estimate
    from app.engine.assemblies import expand
    from app.engine.catalog import CATALOG, TAG_TO_CATALOG, is_fixture_type

    def catalog_for(row):
        """The same resolution classification.py itself uses, so a renamed
        fixture row still resolves to the item it was priced from."""
        tag = row.get("tag") or ""
        if tag in TAG_TO_CATALOG:
            return CATALOG[TAG_TO_CATALOG[tag]]
        if is_fixture_type(tag):
            return CATALOG["luminaire_generic"]
        return None

    rows, _sheets, meta = estimate._compute(BID, "Unalaska, AK")
    priced = [r for r in rows if r["total_cost"] > 0]
    assert priced, "no row was priced at all"

    checked = 0
    for row in priced:
        cat = catalog_for(row)
        assert cat is not None, f"{row['name']} (tag {row['tag']!r}) was priced but resolves to no catalog item"
        checked += 1
        bare = cat.material_cost * row["quantity"] * meta["material_factor"]
        assert row["material_cost"] > bare, f"{row['name']} is priced as a bare device"

    assert checked == len(priced), "some priced row was skipped rather than checked"
    assert checked >= 20, f"only {checked} rows checked; this guard is meant to cover the whole set"


def test_unalaska_sheet_numbers_are_distinct_and_deterministic():
    """14 pages, 14 numbers, identical across three processes with
    different hash seeds. The old code resolved page 89 to E7.1, E6.2
    and E4.1 on three consecutive runs."""
    import json, os, subprocess, sys

    code = (
        "import json,sys; sys.path.insert(0,'.');"
        "from app.engine import documents; from tests.bid_set import BID;"
        "print(json.dumps([(s.page_index,s.number,s.kind,s.title) for s in documents.detect_sheets(BID)]))"
    )
    runs = []
    for seed in ("0", "1", "2"):
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env={**os.environ, "PYTHONHASHSEED": seed}, check=True)
        runs.append(json.loads(out.stdout.strip().splitlines()[-1]))
    assert runs[0] == runs[1] == runs[2]
    numbers = [r[1] for r in runs[0]]
    assert len(numbers) == 14
    assert len(set(numbers)) == 14, sorted(numbers)


def test_unalaska_non_plans_contribute_no_devices():
    """The six non-plan pages, per the set's own electrical drawing index
    on E0.1 (page 80): E0.1 Abbreviations and legend, E0.2 Schedules,
    E0.3 Panel schedules, E6.1 and E6.2 Details and diagrams, E7.1
    One-line diagrams. E1.0 Site plan and E5.1 Enlarged floor plans
    (pages 83 and 90) are plans carrying devices; the earlier findings
    document listed them as a one-line and an equipment schedule while
    its sheet numbers were still nondeterministic."""
    from app.engine import counting, documents

    sheets = {s.page_index: s for s in documents.detect_sheets(BID)}
    for page in (80, 81, 82, 91, 92, 93):
        assert sheets[page].kind != "plan", (page, sheets[page].kind, sheets[page].title)
        assert counting.count_sheet(BID, sheets[page]) == []
    assert sheets[80].legend, "the legend sheet must still feed classification"


def test_unalaska_plan_placements_are_in_range_and_in_frame():
    """Lower bound: what the mis-framed region left. Upper bound: the seal
    and the schedules stay out.

    Measured 2026-09-14 at 322 across the eight plan pages E1.0-E5.1,
    every placement checked against a rendered crop of its glyph (the
    site plan's 8 are circled-J boxes at pole bases). The design spec's
    320 was written for seven plan pages; the site plan is the eighth.
    330 leaves 8 of headroom, and the smallest thing this guards against
    -- the legend page's 14 placements coming back, or one seal ring's
    ~36 -- still trips it."""
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    plans = [s for s in sheets if s.kind == "plan"]
    total = 0
    for s in plans:
        for c in counting.count_sheet(BID, s):
            for p in c.placements:
                assert 0 <= p.x <= s.width_pt and 0 <= p.y <= s.height_pt, (s.number, p)
                total += 1
    assert 197 <= total <= 330, total


def test_a_placement_sits_on_its_glyph_in_the_rotated_render():
    """The marker test. Page 87 (rotation 90): take the first 'J' placement;
    the rendered rotated pixmap, clipped to a square around it, must
    contain a 'J' when the same square is read back as text."""
    import pymupdf
    from app.engine import counting, documents, page_frame

    sheets = {s.page_index: s for s in documents.detect_sheets(BID)}
    j = next(c for c in counting.count_sheet(BID, sheets[87]) if c.tag == "J")
    p = j.placements[0]
    page = pymupdf.open(BID)[87]
    assert page.rotation == 90
    square = pymupdf.Rect(p.x - 12, p.y - 12, p.x + 12, p.y + 12)
    assert "J" in page.get_textbox(page_frame.to_unrotated(square, page))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(4, 4), clip=square)
    ink = sum(1 for i in range(0, len(pix.samples), pix.n) if pix.samples[i] < 128)
    assert ink > 0, "the visual clip rendered blank"
