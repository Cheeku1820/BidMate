"""Counting is tested, not trained (CLAUDE.md): asserted counts on a
known synthetic sheet, no tuning. We build a PDF whose device tags we
placed ourselves and assert the Counting agent finds exactly those --
and that it ignores prose (a notes line) and the title-block strip.

Every page of a real E-size bid set is drawn portrait and displayed
landscape (/Rotate 90), and the two coordinate spaces are not the same
page. Everything a placement flows into works in the *displayed* space:
the sheet's own width_pt/height_pt, the rendered page image markers are
drawn over, and the clip render_evidence_crop cuts a crop with. Text
extraction is the one thing that reports unrotated coordinates, so
Counting converts at the point of extraction. The rotated fixture below
holds that line -- without it markers land somewhere else on the sheet
than the device they were counted from.
"""

import os

import pymupdf
import pytest

from app.engine import counting, documents
from app.engine.contracts import DetectedSheet


@pytest.fixture
def known_sheet(tmp_path):
    """A 1000x800 sheet: 5 'A' fixtures and 3 'R' receptacles isolated in
    the drawing area, one 'A' in the title-block strip (must be excluded),
    and a running-text notes line (must be ignored)."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)

    for i in range(5):  # five type-A fixtures, isolated, in the drawing area
        page.insert_text((100 + i * 60, 100 + i * 40), "A")
    for i in range(3):  # three receptacles
        page.insert_text((200 + i * 50, 400), "R")

    # A device tag inside the title-block strip (x > 820) — must NOT count.
    page.insert_text((900, 120), "A")
    # A general-notes sentence — every token is prose, must NOT count.
    page.insert_text((100, 700), "THESE A R E GENERAL NOTES AND SHALL APPLY")

    path = tmp_path / "known.pdf"
    doc.save(path)

    region = (1000 * 0.02, 800 * 0.02, 1000 * 0.82, 800 * 0.98)
    return str(path), DetectedSheet(
        page_index=0, number="E1.1", title="test", discipline="Electrical",
        scale="", width_pt=1000, height_pt=800, region=region,
    )


def test_counts_exactly_the_placed_tags(known_sheet):
    path, sheet = known_sheet
    clusters = {c.tag: c.count for c in counting.count_sheet(path, sheet)}
    assert clusters.get("A") == 5  # not 6 — the title-block 'A' is excluded
    assert clusters.get("R") == 3


def test_ignores_prose_and_title_block(known_sheet):
    path, sheet = known_sheet
    tags = {c.tag for c in counting.count_sheet(path, sheet)}
    # None of the sentence words survive as device clusters.
    for prose in ("THESE", "GENERAL", "NOTES", "SHALL", "APPLY"):
        assert prose not in tags


def test_placements_carry_coordinates(known_sheet):
    path, sheet = known_sheet
    a = next(c for c in counting.count_sheet(path, sheet) if c.tag == "A")
    assert len(a.placements) == 5
    assert all(isinstance(p.x, int) and isinstance(p.y, int) for p in a.placements)
    # every placement lies inside the declared drawing region
    x0, y0, x1, y1 = sheet.region
    assert all(x0 <= p.x <= x1 and y0 <= p.y <= y1 for p in a.placements)


def test_unreadable_sheet_counts_nothing(known_sheet):
    path, sheet = known_sheet
    sheet.unreadable_reason = "scanned"
    assert counting.count_sheet(path, sheet) == []


@pytest.fixture
def rotated_known_sheet(tmp_path):
    """The same known sheet, built the way a real set is: drawn on a
    portrait page and displayed landscape through /Rotate 90.

    Tags are placed by their *displayed* position -- the position an
    estimator sees them at and the position a marker has to land on --
    and written at the unrotated coordinate that displays there. For a
    90 degree rotation of an 800 x 1000 page, displayed (dx, dy) is
    written at unrotated (dy, 1000 - dx).
    """
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=1000)

    def at(dx, dy, text):
        page.insert_text((dy, 1000 - dx), text)

    displayed_a = [(100 + i * 60, 100 + i * 40) for i in range(5)]
    for dx, dy in displayed_a:
        at(dx, dy, "A")
    displayed_r = [(200 + i * 50, 400) for i in range(3)]
    for dx, dy in displayed_r:
        at(dx, dy, "R")

    # A device tag inside the displayed title-block strip -- must NOT count.
    at(900, 120, "A")
    # A general-notes sentence in the drawing area -- prose, must NOT count.
    at(50, 100, "THESE A R E GENERAL NOTES AND SHALL APPLY")

    # Rotate after writing, so the coordinates above stay the unrotated
    # ones `at` computed against.
    page.set_rotation(90)
    path = tmp_path / "rotated.pdf"
    doc.save(path)
    doc.close()

    # The displayed page is 1000 x 800, so the region is the same box the
    # unrotated fixture uses -- detect_sheets builds it from page.rect.
    region = (1000 * 0.02, 800 * 0.02, 1000 * 0.82, 800 * 0.98)
    sheet = DetectedSheet(
        page_index=0, number="E1.1", title="test", discipline="Electrical",
        scale="", width_pt=1000, height_pt=800, region=region,
    )
    return str(path), sheet, displayed_a, displayed_r


def test_counts_exactly_the_placed_tags_on_a_rotated_sheet(rotated_known_sheet):
    """The region is built from page.rect (displayed) but text extraction
    reports unrotated coordinates, so on a rotated sheet the region
    filter tests the wrong band of the page: it drops real devices and
    lets the title-block tag through."""
    path, sheet, _, _ = rotated_known_sheet
    clusters = {c.tag: c.count for c in counting.count_sheet(path, sheet)}
    assert clusters.get("A") == 5  # not 6 -- the title-block 'A' is excluded
    assert clusters.get("R") == 3


def test_placements_are_in_displayed_coordinates_on_a_rotated_sheet(rotated_known_sheet):
    """A placement is normalized into sheet space against the sheet's own
    width_pt/height_pt -- which are the displayed dimensions -- and is
    cropped from the page with a displayed-space clip. A placement in
    unrotated coordinates puts the marker somewhere else entirely."""
    path, sheet, displayed_a, displayed_r = rotated_known_sheet
    by_tag = {c.tag: c for c in counting.count_sheet(path, sheet)}

    for tag, expected in (("A", displayed_a), ("R", displayed_r)):
        found = sorted((p.x, p.y) for p in by_tag[tag].placements)
        for (want_x, want_y), (got_x, got_y) in zip(sorted(expected), found):
            # insert_text places a baseline, so the glyph's centre sits a
            # few points off the requested point; nowhere near the
            # hundreds of points an unrotated coordinate would be out by.
            assert abs(got_x - want_x) <= 12, f"{tag}: x {got_x} not near {want_x}"
            assert abs(got_y - want_y) <= 12, f"{tag}: y {got_y} not near {want_y}"


# The real bid set: point TAKEOFF_BID_SET_PDF at a copy to run this.
BID_SET_PDF = os.environ.get("TAKEOFF_BID_SET_PDF", "")


@pytest.mark.skipif(not os.path.exists(BID_SET_PDF), reason="TAKEOFF_BID_SET_PDF not available")
def test_real_bid_set_placements_reach_the_whole_displayed_sheet():
    """Devices on a real set are drawn right across the sheet, so some of
    them sit beyond the portrait page's width -- a place an unrotated
    coordinate cannot address at all. Under the bug every placement was
    squeezed into the left 65% of the sheet, because that is all a
    1584pt-wide text space can reach on a 2448pt-wide displayed page.

    The per-sheet bounds below hold trivially while the region filter
    does its job; they are here so a future change that loosens the
    filter still cannot put a marker off the page.
    """
    sheets = documents.detect_sheets(BID_SET_PDF)
    clusters = counting.count(BID_SET_PDF, sheets)
    assert clusters, "the real set should count something"

    by_page = {s.page_index: s for s in sheets}
    beyond_portrait = 0
    for cluster in clusters:
        sheet = by_page[cluster.sheet_page_index]
        x0, y0, x1, y1 = sheet.region
        # The unrotated text space is as wide as the displayed page is tall.
        portrait_width = sheet.height_pt
        for p in cluster.placements:
            assert 0 <= p.x <= sheet.width_pt, f"{cluster.tag}: x {p.x} off a {sheet.width_pt}pt page"
            assert 0 <= p.y <= sheet.height_pt, f"{cluster.tag}: y {p.y} off a {sheet.height_pt}pt page"
            assert x0 <= p.x <= x1 and y0 <= p.y <= y1, f"{cluster.tag}: ({p.x}, {p.y}) outside the drawing region"
            if p.x > portrait_width:
                beyond_portrait += 1
    assert beyond_portrait, "no placement past the portrait width -- coordinates are still unrotated"
