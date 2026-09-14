"""Title-block location and the deterministic sheet number. Synthetic
pages only; the corpus is Task 6's job."""

import pymupdf
import pytest

from app.engine import page_frame, title_block


def _page(tmp_path, width=1000, height=800, rotation=0):
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    return doc, page


def _words(doc, page, tmp_path, rotation=0):
    if rotation:
        page.set_rotation(rotation)
    path = tmp_path / "p.pdf"
    doc.save(path)
    p = pymupdf.open(path)[0]
    return page_frame.visual_words(p), p.rect.width, p.rect.height


def test_locates_a_right_strip(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "DRAWN")
    page.insert_text((900, 760), "E2.1")       # number cell, bottom of the strip
    page.insert_text((300, 400), "SEE E5.1")   # a reference in the drawing
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert tb is not None and tb.edge == "right"
    assert title_block.sheet_number(tb) == "E2.1"


def test_locates_a_bottom_strip_on_a_rotated_page(tmp_path):
    """Unrotated right strip + 90-degree rotation = visual bottom strip."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "CHECKED")
    page.insert_text((900, 760), "E-101")
    words, w, h = _words(doc, page, tmp_path, rotation=90)
    tb = title_block.locate(words, w, h)
    assert tb is not None and tb.edge == "bottom"
    assert title_block.sheet_number(tb) == "E-101"


def test_no_strip_means_none(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((300, 400), "SEE E5.1 FOR DETAILS")
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.locate(words, w, h) is None


def test_number_prefers_the_corner_over_frequency(tmp_path):
    """A revision table in the strip repeats another sheet's number three
    times; the number cell at the corner still wins."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    for y in (200, 230, 260):
        page.insert_text((900, y), "E1.0")     # references, mid-strip
    page.insert_text((900, 770), "E2.1")       # the number cell, at the corner
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.sheet_number(title_block.locate(words, w, h)) == "E2.1"


def test_ties_break_by_frequency_then_first_seen(tmp_path):
    """Two tokens equidistant from the corner: the more frequent wins;
    still tied, the first in reading order wins. Never hash order."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    # Corner of the right strip is (1000, 800). Both tokens sit ~72pt from
    # it -- (40, 60) and (60, 40) away -- so distance cannot separate them.
    page.insert_text((960, 740), "E3.1")
    page.insert_text((940, 760), "E3.2")
    page.insert_text((900, 300), "E3.2")       # E3.2 appears twice overall
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.sheet_number(title_block.locate(words, w, h)) == "E3.2"


def test_ties_at_equal_frequency_take_the_first_in_reading_order(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((940, 760), "E3.1")       # inserted first
    page.insert_text((960, 740), "E3.2")
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.sheet_number(title_block.locate(words, w, h)) == "E3.1"


def test_strip_with_no_family_token_yields_empty(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "DRAWN")
    page.insert_text((900, 760), "A-101")      # an architectural number
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert tb is not None
    assert title_block.sheet_number(tb) == ""


@pytest.mark.parametrize("token,ok", [
    ("E2.1", True), ("E-101", True), ("E101", True), ("EP-1", True), ("EL101", True),
    ("EF-1", True), ("EX10", True), ("ED-101", True), ("EQ101", True),
    ("A-101", False), ("M2.1", False), ("E", False), ("SEE", False), ("EE-12624", False),
])
def test_sheet_id_family(token, ok):
    assert bool(title_block.SHEET_ID.fullmatch(token)) is ok


def test_title_reads_the_cell_next_to_the_number(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((880, 700), "FIRST FLOOR")
    page.insert_text((880, 725), "POWER PLAN")
    page.insert_text((900, 770), "E2.1")
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E2.1") == "First floor power plan"


def test_title_rejects_address_and_seal_lines(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((860, 700), "3909 ARCTIC BOULEVARD, SUITE 103")
    page.insert_text((860, 725), "REGISTERED PROFESSIONAL ENGINEER")
    page.insert_text((900, 770), "E2.1")
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E2.1") == ""


def test_title_rejects_a_cell_with_a_bare_number(tmp_path):
    """A digits-only token in the title cell (a sheet count, a suite
    number) fails the sanity check rather than being silently dropped."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((880, 700), "POWER PLAN")
    page.insert_text((880, 725), "103")
    page.insert_text((900, 770), "E2.1")
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E2.1") == ""


def test_title_reads_in_order_on_a_rotated_page(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((880, 700), "FIRST FLOOR")
    page.insert_text((880, 725), "POWER PLAN")
    page.insert_text((900, 770), "E2.1")
    words, w, h = _words(doc, page, tmp_path, rotation=90)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E2.1") == "First floor power plan"
