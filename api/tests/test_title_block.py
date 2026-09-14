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


def test_the_largest_number_shaped_token_is_the_cell(tmp_path):
    """A revision table in the strip repeats another sheet's number three
    times, in body type; the number cell, in display type, is the cell
    -- size decides, not frequency. (Set all four at one size and the
    strip is an index -- see
    test_a_drawing_index_in_the_strip_is_not_a_number_cell -- which is
    the layout no real title block has.)"""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    for y in (200, 230, 260):
        page.insert_text((900, y), "E1.0", fontsize=9)     # references, mid-strip
    page.insert_text((900, 770), "E2.1", fontsize=20)      # the number cell, at the corner
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.sheet_number(title_block.locate(words, w, h)) == "E2.1"


def test_two_numbers_at_the_largest_size_are_an_index_not_a_tie(tmp_path):
    """Two different tokens in the strip's largest face, equidistant from
    the corner: there is no tiebreak to reach for, because a number cell
    is one number and two is an index. Frequency and reading order still
    order the *instances* of one number (a callout bubble set as large
    as the cell), never hash order -- see
    test_the_number_cell_may_repeat_but_not_be_two_numbers."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((960, 740), "E3.1")
    page.insert_text((940, 760), "E3.2")
    page.insert_text((900, 300), "E3.2")
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.sheet_number(title_block.locate(words, w, h)) == ""


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
    """A digits-only token inside the title line fails the whole cell
    rather than being silently dropped from it."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((880, 725), "POWER PLAN 103")
    page.insert_text((900, 770), "E2.1")
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E2.1") == ""


def test_a_number_on_its_own_line_is_a_value_cell_not_a_title_word(tmp_path):
    """A line made only of numbers beside the title is another cell of
    the block -- Kittles Saxony's CDG NO. 24108 sits above every title,
    set larger than it; United Utility's Project Number 25-0107LE sits
    on the row above, set the same. Neither is part of the title, so
    the line is left out and the title still reads. Contrast the test
    above: a number *inside* the title line still fails the cell."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((880, 660), "CDG NO.", fontsize=8)
    page.insert_text((880, 690), "24108", fontsize=18)
    page.insert_text((880, 715), "FIRST FLOOR", fontsize=13)
    page.insert_text((880, 735), "LIGHTING PLAN", fontsize=13)
    page.insert_text((880, 785), "EL101", fontsize=36)
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "EL101") == "First floor lighting plan"


def test_a_project_number_on_the_row_above_is_not_part_of_the_title(tmp_path):
    """United Utility: a label cell and its value share the row above
    the title, and the value is set in the title's own type. It came out
    as "Electrical - lighting plan 25-0107le" on every one of the nine
    sheets."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((860, 690), "Project Number", fontsize=7)
    page.insert_text((930, 690), "25-0107LE", fontsize=12)
    page.insert_text((870, 712), "ELECTRICAL -", fontsize=12)
    page.insert_text((870, 730), "LIGHTING PLAN", fontsize=12)
    page.insert_text((870, 785), "E-101", fontsize=36)
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E-101") == "Electrical - lighting plan"


def test_a_release_stamp_beside_the_number_cell_is_not_the_title(tmp_path):
    """Kittles Saxony: a rotated RELEASED FOR CONSTRUCTION stamp runs up
    the outer edge of the strip in a face larger than the title's. It is
    an issue stamp, not a cell of the block; the actual title line wins."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((880, 715), "FIRST FLOOR", fontsize=13)
    page.insert_text((880, 735), "LIGHTING PLAN", fontsize=13)
    page.insert_text((880, 785), "EL101", fontsize=36)
    page.insert_text((985, 790), "RELEASED FOR CONSTRUCTION", fontsize=20, rotate=90)
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.sheet_number(tb) == "EL101"
    assert title_block.title(tb, "EL101") == "First floor lighting plan"


def test_title_reads_in_order_on_a_rotated_page(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((880, 700), "FIRST FLOOR")
    page.insert_text((880, 725), "POWER PLAN")
    page.insert_text((900, 770), "E2.1")
    words, w, h = _words(doc, page, tmp_path, rotation=90)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E2.1") == "First floor power plan"


def test_a_details_row_does_not_outscore_the_title_block(tmp_path):
    """A details sheet repeats its own number in every detail callout
    along the bottom, each with a SCALE: label under it. Those are drawing
    labels, not title-block labels, and a repeated token is one cell, not
    four: the right-edge title block still wins. Measured on Unalaska
    E6.1 / E6.2 (pages 91, 92), where the bottom strip scored 8-10 to the
    real title block's 7 and the counting region came out wrong."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "DRAWN")
    page.insert_text((900, 160), "CHECKED")
    page.insert_text((900, 770), "E6.2")               # the number cell
    for x in (150, 450, 750):                           # three detail callouts
        page.insert_text((x, 740), "E6.2")
        page.insert_text((x + 40, 740), "SCALE: NONE")
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert tb is not None and tb.edge == "right"
    assert title_block.sheet_number(tb) == "E6.2"


def _unalaska_style_block(page):
    """The layout measured on the real set: a horizontal number cell at
    the strip's end corner, the title set in a larger rotated face in a
    column beside it, and the author / date label cells (smaller, rotated,
    ending in a colon) stacked between the two. The title's far words run
    well past a square reach around the number cell; the label cells sit
    inside it."""
    page.insert_text((900, 100), "SHEET")
    page.insert_text((930, 780), "E2.1", fontsize=20)                          # number cell
    page.insert_text((905, 760), "FLOOR PLAN - LIGHTING", fontsize=12, rotate=90)
    page.insert_text((925, 760), "AUTHOR:", fontsize=8, rotate=90)
    page.insert_text((925, 700), "TRC", fontsize=8, rotate=90)                # author initials
    page.insert_text((945, 760), "ISSUE DATE:", fontsize=8, rotate=90)
    page.insert_text((945, 690), "10/01/2021", fontsize=8, rotate=90)


def test_title_reads_a_rotated_column_beside_the_number_cell(tmp_path):
    doc, page = _page(tmp_path)
    _unalaska_style_block(page)
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.sheet_number(tb) == "E2.1"
    assert title_block.title(tb, "E2.1") == "Floor plan - lighting"


def test_title_reads_the_same_column_on_a_rotated_page(tmp_path):
    doc, page = _page(tmp_path)
    _unalaska_style_block(page)
    words, w, h = _words(doc, page, tmp_path, rotation=90)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E2.1") == "Floor plan - lighting"


def _notes_block(page, x, y, lines, fontsize=8):
    for i, line in enumerate(lines):
        page.insert_text((x, y + i * 11), line, fontsize=fontsize)


def test_a_general_notes_block_in_another_strip_does_not_outscore_the_number_cell(tmp_path):
    """Kittles Saxony EP102 (page 5): general notes along the top edge
    say SEE SHEET E-000 / E-501 / E-502 / E-601 AND E-602 -- five
    distinct family tokens and four SHEET labels, against the right
    strip's one number cell. The number cell is set at 48pt and the
    notes at 9pt: the strip holding the largest sheet-number-shaped
    token is the title block, and the page came out as E-602 instead."""
    doc, page = _page(tmp_path)
    _notes_block(page, 300, 30, (
        "A. SEE SHEET E-000 FOR SYMBOLS AND ABBREVIATIONS.",
        "B. SEE SHEET E-501 FOR MECHANICAL EQUIPMENT POWER SCHEDULE.",
        "C. SEE SHEET E-502 FOR PANEL SCHEDULES.",
        "D. SEE SHEETS E-601 AND E-602 FOR ELECTRICAL DETAILS.",
    ))
    page.insert_text((900, 400), "REVISION", fontsize=8)     # the revision table's heading
    page.insert_text((900, 680), "CDG NO.", fontsize=8)
    page.insert_text((880, 720), "ROOF POWER PLAN", fontsize=13)
    page.insert_text((880, 785), "EP102", fontsize=36)
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert tb.edge == "right"
    assert title_block.sheet_number(tb) == "EP102"
    assert title_block.title(tb, "EP102") == "Roof power plan"


def test_a_body_tag_spilling_into_the_strip_loses_to_the_real_number_cell(tmp_path):
    """TSC Nutrition M1.01 (page 42): an exhaust-fan tag EF-7 sits in the
    drawing where it overlaps the right strip. The page's own number
    cell reads M1.01 -- a sheet number, just not an electrical one. The
    number cell is the largest sheet-number-shaped token whatever its
    discipline; only then is the family test applied. The page came out
    as electrical sheet EF-7."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "DATE")
    page.insert_text((840, 400), "EF-7", fontsize=8)
    page.insert_text((880, 785), "M1.01", fontsize=30)
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert tb.edge == "right"
    assert title_block.sheet_number(tb) == ""


def test_a_fan_schedule_along_the_top_does_not_become_the_title_block(tmp_path):
    """TSC Nutrition M6.01 (page 46): a fan schedule with six EF- rows
    runs along the top edge; the title block is on the right with M6.01.
    The page came out as electrical sheet EF-6 with the schedule's
    heading as its title."""
    doc, page = _page(tmp_path)
    for i in range(6):
        page.insert_text((300 + i * 90, 60), f"EF-{i + 1}", fontsize=9)
        page.insert_text((300 + i * 90, 75), "TOILET RM", fontsize=9)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "DATE")
    page.insert_text((880, 785), "M6.01", fontsize=30)
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert tb.edge == "right"
    assert title_block.sheet_number(tb) == ""


_INDEX_ROWS = (
    "G0.00 COVER SHEET", "C101 DEMOLITION PLAN", "A1.01 FLOOR PLAN", "M1.01 MECHANICAL PLAN",
    "ES100 ELECTRICAL SITE PLAN", "E700 LIGHTING DETAILS", "T001 DEMOLITION PLAN", "T402 SECURITY DETAILS",
)


@pytest.mark.parametrize("rows", [
    _INDEX_ROWS,                                   # electrical rows mid-list
    _INDEX_ROWS[:4] + _INDEX_ROWS[6:] + _INDEX_ROWS[4:6],   # electrical rows last, nearest the corner
    _INDEX_ROWS[4:6] + _INDEX_ROWS[:4] + _INDEX_ROWS[6:],   # electrical rows first
], ids=["mid", "last", "first"])
def test_a_drawing_index_in_the_strip_is_not_a_number_cell(tmp_path, rows):
    """TSC Nutrition's and Unalaska's covers: the drawing index runs down
    an edge strip, one sheet number per row, all in one face. A number
    cell is one token set larger than anything else shaped like it; two
    or more distinct tokens sharing the largest size is an index, and
    a page whose strip holds an index has no number cell -- whichever
    rows happen to sit nearest the corner. The first version of this
    rule passed only because a telecom row was last; reordering the
    rows made the cover ES100."""
    doc, page = _page(tmp_path)
    _notes_block(page, 860, 300, rows, fontsize=8)
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.sheet_number(tb) == ""


def test_the_number_cell_may_repeat_but_not_be_two_numbers(tmp_path):
    """The same number twice at the largest size (a callout bubble set
    as large as the cell) is still one number cell; two different ones
    are an index."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((880, 700), "E2.1", fontsize=24)
    page.insert_text((880, 785), "E2.1", fontsize=24)
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.sheet_number(title_block.locate(words, w, h)) == "E2.1"


@pytest.mark.parametrize("token,ok", [
    ("A6.01", True), ("G0.00", True), ("M1.01", True), ("T402", True), ("C101", True), ("P-401", True),
    ("E-101", True), ("EQ020", True),
    ("NO.", False), ("RM", False), ("12x7", False), ("146", False), ("EE-12624", False),
])
def test_any_sheet_id_shape(token, ok):
    assert bool(title_block.ANY_SHEET_ID.fullmatch(token)) is ok


def test_circuit_tags_along_the_bottom_do_not_move_the_title_block(tmp_path):
    """United Utility E-101: the number cell sits in the corner the
    bottom and right strips share, so the strips tie on size and the
    tiebreak decides the edge. The plan's bottom strip carries dozens of
    circuit and equipment tags (BPW-3, UH-4, W1) that match the
    any-discipline sheet-number shape; counting those moved the title
    block to the bottom and cut the counting region on the wrong side.
    The tiebreak counts family tokens and labels only."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "DATE")
    for i, tag in enumerate(("BPW-3", "BPW-14", "UH-4", "UH-5", "W1", "X1", "C100", "HB1")):
        page.insert_text((60 + i * 90, 740), tag, fontsize=8)
    page.insert_text((880, 785), "E-101", fontsize=36)
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert tb.edge == "right"
    assert title_block.sheet_number(tb) == "E-101"
