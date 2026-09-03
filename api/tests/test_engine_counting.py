"""Counting is tested, not trained (CLAUDE.md): asserted counts on a
known synthetic sheet, no tuning. We build a PDF whose device tags we
placed ourselves and assert the Counting agent finds exactly those --
and that it ignores prose (a notes line) and the title-block strip.
"""

import pymupdf
import pytest

from app.engine import counting
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


import os
import pytest

BID = ("/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/"
       "21_1001_unalaska_library_cd_biddrawings.pdf")


@pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")
def test_engineers_seal_is_not_counted_as_devices():
    """E1.1 (page index 84) carries a professional engineer's seal whose
    perimeter text is 50 rotated single-character glyphs near (960, 100),
    spelling STATE OF ALASKA / REGISTERED PROFESSIONAL ENGINEER. Each
    letter matches the device-tag shape and stands alone on its own text
    line, so before this filter they were counted as devices on every
    sheet -- A as a luminaire type, S as a switch, T as a data outlet.

    Asserted count, not a tuned threshold: Counting is tested, not
    trained (CLAUDE.md)."""
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    sheet = next(s for s in sheets if s.page_index == 84)
    clusters = counting.count_sheet(BID, sheet)

    seal = [p for c in clusters for p in c.placements
            if 850 < p.x < 1010 and 40 < p.y < 160]
    assert seal == [], f"{len(seal)} seal glyphs still counted as devices"


@pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")
def test_real_devices_survive_the_rotation_filter():
    """The filter must not empty a sheet outright -- it should remove the
    seal and leave real devices behind.

    Deviation from the brief: this originally asserted non-empty clusters
    on E1.1 (page_index 84), the same sheet the seal was documented on.
    Verified against the real set, E1.1 has zero device tags that repeat
    3+ times once the seal's ~41 tag-shaped candidates/sheet are correctly
    excluded -- every surviving token on that sheet (the legend row A
    through G, "MEN", "AA", "TRC"...) is a real, non-seal annotation, but
    each occurs exactly once there, so none clears MIN_PLACEMENTS. That is
    a property of E1.1's content (it reads as a legend/cover-heavy sheet),
    not a filter bug -- confirmed by manually walking every tag-shaped
    candidate on that sheet and its distance to the nearest confirmed seal
    glyph (see task-3-report.md).

    E6.1 (page_index 87) carries the identical reused seal (same 32
    ArialNarrow spans, same position) plus a genuinely busy floor plan, so
    it is the sheet that actually exercises "the filter removes the seal
    without emptying a normal sheet" -- 114 device placements survive
    there (J: 24, XA: 24, B: 11, D: 10, C: 10, A: 8, M2: 6, O: 4, ...) with
    zero placements landing inside the seal's coordinate window.
    """
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    sheet = next(s for s in sheets if s.page_index == 87)
    clusters = counting.count_sheet(BID, sheet)
    assert clusters, "the filter removed every cluster on a sheet that has real devices"

    seal = [p for c in clusters for p in c.placements
            if 850 < p.x < 1010 and 40 < p.y < 160]
    assert seal == [], f"{len(seal)} seal glyphs still counted as devices on E6.1"
