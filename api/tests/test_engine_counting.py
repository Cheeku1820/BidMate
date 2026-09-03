"""Counting is tested, not trained (CLAUDE.md): asserted counts on a
known synthetic sheet, no tuning. We build a PDF whose device tags we
placed ourselves and assert the Counting agent finds exactly those --
and that it ignores prose (a notes line) and the title-block strip.
"""

import os

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


def _rename_font(doc, page, basefont: str, new_name: str) -> None:
    """Rename a page's font resource in place (BaseFont in its xref
    object) so extracted text reports `new_name` as its font. Lets a test
    build a page with a genuinely condensed-named font without shipping a
    real font file -- `page.insert_text(..., fontname="cour")` draws with
    a built-in base-14 font, then this renames that font resource's
    BaseFont, which `get_text("dict")` spans report back as `span["font"]`.
    """
    for xref, ext, ftype, existing_basefont, name, enc in page.get_fonts():
        if existing_basefont == basefont:
            doc.xref_set_key(xref, "BaseFont", f"/{new_name}")


def test_seal_ring_removed_but_separated_real_tags_survive(tmp_path):
    """A stamp: a handful of identical single characters in a condensed
    font, clustered tightly in one corner -- like a seal's ring text --
    alongside real device tags in the ordinary font, spread across the
    rest of a sheet with enough other text that the ring is a small
    minority of it (as a real stamp is). The ring must be removed; the
    separated real tags must survive untouched."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)

    for i in range(5):  # five real type-A fixtures, ordinary font
        page.insert_text((100 + i * 60, 100 + i * 40), "A", fontname="helv")
    for i in range(3):  # three real receptacles, ordinary font
        page.insert_text((200 + i * 50, 400), "R", fontname="helv")

    # Padding text (not tag-shaped -- four letters, TAG only matches up to
    # three) so the ring below is a small share of the sheet's text, the
    # way a real stamp is a small share of a real sheet's.
    for i in range(20):
        page.insert_text((50 + (i % 5) * 150, 550 + (i // 5) * 20), "ROOM", fontname="helv")

    # The ring: four identical single characters, tag-shaped, clustered
    # tightly in one corner, standing alone on their own line -- same
    # shape a stamp's ring glyphs have. Renamed to a condensed font below.
    for i in range(4):
        page.insert_text((700 + i * 8, 700 + i * 8), "S", fontname="cour")
    _rename_font(doc, page, "Courier", "ArialNarrow")

    path = tmp_path / "ring.pdf"
    doc.save(path)

    region = (1000 * 0.02, 800 * 0.02, 1000 * 0.98, 800 * 0.98)
    sheet = DetectedSheet(
        page_index=0, number="E1.1", title="test", discipline="Electrical",
        scale="", width_pt=1000, height_pt=800, region=region,
    )
    clusters = {c.tag: c.count for c in counting.count_sheet(str(path), sheet)}
    assert clusters.get("A") == 5
    assert clusters.get("R") == 3
    assert "S" not in clusters, "the seal-like ring survived as a device cluster"


def test_narrow_font_device_tags_are_not_treated_as_a_stamp(tmp_path):
    """Pins the critical fix: if a firm's drafter sets ordinary device
    tags in a condensed font, that is not a stamp -- the condensed spans
    are the majority of the sheet's text and spread across it, not a
    small, localised minority the way a real seal's ring text is. Before
    the guards in `_stamp_points`, this returned no clusters at all,
    silently, with no warning and no `unreadable_reason`."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)

    for i in range(5):  # five real type-A fixtures, spread across the page
        page.insert_text((100 + i * 150, 100 + i * 40), "A", fontname="cour")
    for i in range(3):  # three real receptacles, spread across the page
        page.insert_text((150 + i * 200, 400), "R", fontname="cour")
    _rename_font(doc, page, "Courier", "ArialNarrow")

    path = tmp_path / "narrow_tags.pdf"
    doc.save(path)

    region = (1000 * 0.02, 800 * 0.02, 1000 * 0.98, 800 * 0.98)
    sheet = DetectedSheet(
        page_index=0, number="E1.1", title="test", discipline="Electrical",
        scale="", width_pt=1000, height_pt=800, region=region,
    )
    clusters = {c.tag: c.count for c in counting.count_sheet(str(path), sheet)}
    assert clusters.get("A") == 5, "a narrow-font device tag was wrongly treated as a stamp"
    assert clusters.get("R") == 3, "a narrow-font device tag was wrongly treated as a stamp"


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
def test_real_devices_survive_the_stamp_filter():
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
