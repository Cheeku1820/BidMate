"""The Documents agent on synthetic pages. The corpus is test_corpus_sheets.py."""

import pymupdf

from app.engine import documents
from app.engine.contracts import DetectedSheet


def _sheet(tmp_path, own_number, refs=(), title_lines=(), rotation=0, drawings=600, scale=True, tags=()):
    """A 1000x800 page with a right-edge title block (SHEET/DRAWN labels,
    optional title lines, the number cell at the bottom corner), a body
    that references other sheets, optional device tags at unrotated
    (x, y) positions, and enough vector paths to be a plan."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((900, 60), "SHEET")
    page.insert_text((900, 85), "DRAWN")
    for i, line in enumerate(title_lines):
        page.insert_text((870, 700 + i * 22), line)
    page.insert_text((900, 770), own_number)
    for i, ref in enumerate(refs):
        page.insert_text((200, 200 + i * 40), f"SEE {ref}")
    for text, x, y in tags:
        page.insert_text((x, y), text)
    if scale:
        page.insert_text((200, 600), 'SCALE: 1/8" = 1\'-0"')
    for i in range(drawings):
        page.draw_line((50 + (i % 40) * 15, 100 + (i // 40) * 12), (55 + (i % 40) * 15, 105 + (i // 40) * 12))
    if rotation:
        page.set_rotation(rotation)
    path = tmp_path / "s.pdf"
    doc.save(path)
    return str(path)


def test_sheet_number_comes_from_the_title_block(tmp_path):
    path = _sheet(tmp_path, "E2.1", refs=("E5.1", "E5.1", "E5.1"))
    (s,) = documents.detect_sheets(path)
    assert s.number == "E2.1"


def test_a_page_with_no_title_block_is_not_a_sheet(tmp_path):
    """No whole-page fallback: an architectural page that says SEE E-101
    three times is not an electrical sheet."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    for i in range(3):
        page.insert_text((200, 200 + i * 40), "SEE E-101")
    for i in range(600):
        page.draw_line((50 + (i % 40) * 15, 100 + (i // 40) * 12), (55 + (i % 40) * 15, 105 + (i // 40) * 12))
    path = tmp_path / "arch.pdf"
    doc.save(path)
    assert documents.detect_sheets(str(path)) == []


def test_rotated_page_reads_the_same(tmp_path):
    path = _sheet(tmp_path, "E-101", title_lines=("FIRST FLOOR", "POWER PLAN"), rotation=90)
    (s,) = documents.detect_sheets(path)
    assert s.number == "E-101"
    assert s.title == "First floor power plan"
    assert s.kind == "plan"
    assert (s.width_pt, s.height_pt) == (800, 1000)
    x0, y0, x1, y1 = s.region
    assert 0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1000
    # The title block is along the visual bottom on a 90-degree page.
    assert y1 < 1000 * 0.85


def _glyph_under(path, page_index, x, y, half=12):
    """The text a viewer would see in a small square around a visual
    point -- rendered from the page's own frame, read back through the
    derotated clip get_textbox needs (page_frame.to_unrotated)."""
    from app.engine import page_frame

    page = pymupdf.open(path)[page_index]
    clip = page_frame.to_unrotated(pymupdf.Rect(x - half, y - half, x + half, y + half), page)
    return page.get_textbox(clip).strip()


_TAGS = [("R1", 300, 300), ("R1", 500, 300), ("R1", 300, 500), ("R1", 500, 500)]


def test_a_180_degree_page_reads_the_same_and_its_markers_sit_on_the_glyphs(tmp_path):
    """Spec 3.3. The unrotated right-edge block is along the visual LEFT
    of a 180-degree page, with the number cell at the top-left corner.
    Number, title and kind read the same; the counting region gives up
    the left strip, not the right; and every placement Counting emits,
    read back through the derotated clip, is the tag itself -- markers
    land on the drawing, not off it."""
    from app.engine import counting

    path = _sheet(tmp_path, "E-101", title_lines=("FIRST FLOOR", "POWER PLAN"), rotation=180, tags=_TAGS)
    (s,) = documents.detect_sheets(path)
    assert (s.number, s.title, s.kind) == ("E-101", "First floor power plan", "plan")
    assert (s.width_pt, s.height_pt) == (1000, 800)
    x0, y0, x1, y1 = s.region
    assert x0 >= 1000 * 0.18 - 0.5       # left strip located and excluded
    assert x1 > 1000 * 0.9               # nothing taken off the right
    assert y0 < 800 * 0.1 and y1 > 800 * 0.9
    (cluster,) = counting.count_sheet(path, s)
    assert cluster.tag == "R1" and cluster.count == 4
    for pl in cluster.placements:
        assert 0 <= pl.x <= s.width_pt and 0 <= pl.y <= s.height_pt
        assert _glyph_under(path, 0, pl.x, pl.y) == "R1", pl


def test_a_270_degree_page_reads_the_same_and_its_markers_sit_on_the_glyphs(tmp_path):
    """Spec 3.3, the corpus's own 270-degree case: TSC Nutrition's
    electrical pages are 270 but carry no words at all (text outlined to
    paths), so the corpus cannot supply this readback and this synthetic
    page stands in. The right-edge block is along the visual TOP; the
    region gives up the top strip; every placement reads back as its
    tag."""
    from app.engine import counting

    path = _sheet(tmp_path, "E-101", title_lines=("FIRST FLOOR", "POWER PLAN"), rotation=270, tags=_TAGS)
    (s,) = documents.detect_sheets(path)
    assert (s.number, s.title, s.kind) == ("E-101", "First floor power plan", "plan")
    assert (s.width_pt, s.height_pt) == (800, 1000)
    x0, y0, x1, y1 = s.region
    assert y0 >= 1000 * 0.18 - 0.5       # top strip located and excluded
    assert y1 > 1000 * 0.9               # nothing taken off the bottom
    assert x0 < 800 * 0.1 and x1 > 800 * 0.9
    (cluster,) = counting.count_sheet(path, s)
    assert cluster.tag == "R1" and cluster.count == 4
    for pl in cluster.placements:
        assert 0 <= pl.x <= s.width_pt and 0 <= pl.y <= s.height_pt
        assert _glyph_under(path, 0, pl.x, pl.y) == "R1", pl


def test_region_excludes_the_located_strip_not_a_fixed_right_strip(tmp_path):
    path = _sheet(tmp_path, "E1.1")
    (s,) = documents.detect_sheets(path)
    x0, y0, x1, y1 = s.region
    assert x1 <= 1000 * (1 - 0.18) + 0.5  # right strip located and excluded
    assert y1 > 800 * 0.9                 # nothing taken off the bottom


def test_kind_from_the_title(tmp_path):
    path = _sheet(tmp_path, "E0.3", title_lines=("PANEL", "SCHEDULES"), scale=False)
    (s,) = documents.detect_sheets(path)
    assert s.kind == "schedule"
    assert s.title == "Panel schedules"


def test_title_falls_back_to_the_kind_label(tmp_path):
    path = _sheet(tmp_path, "E0.1", title_lines=("3909 ARCTIC BOULEVARD, SUITE 103",), scale=False)
    (s,) = documents.detect_sheets(path)
    assert s.title == "Electrical plan"


def test_a_sparse_riser_diagram_is_still_a_sheet(tmp_path):
    """Pulte Sagebriar E-700 is a riser diagram drawn with 323 vector
    paths. A page whose title-block number cell holds a family token is
    an electrical sheet whatever its path count; the old 500-path
    "text-only page" gate dropped it silently."""
    path = _sheet(tmp_path, "E-700", title_lines=("ELECTRICAL RISER", "DIAGRAM"), drawings=300, scale=False)
    (s,) = documents.detect_sheets(path)
    assert s.number == "E-700"
    assert s.kind == "diagram"


def test_a_text_only_page_is_not_a_sheet(tmp_path):
    """A sheet is a drawing. A project-manual page with SHEET / E7.1 /
    DATE in its left column has a strip that reads like a title block
    and no drawing paths and no images; it is not a plan, a schedule or
    a legend drawing. This is not the old 500-path gate -- Pulte's
    323-path riser still detects -- it is zero paths and zero images."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((40, 100), "SHEET")
    page.insert_text((40, 130), "E7.1")
    page.insert_text((40, 160), "DATE")
    for i in range(30):
        page.insert_text((300, 100 + i * 20), "SECTION 26 05 19 LOW-VOLTAGE CONDUCTORS AND CABLES")
    path = tmp_path / "manual.pdf"
    doc.save(path)
    assert documents.detect_sheets(str(path)) == []


def _scan(tmp_path, bands, width=612, height=792, text=""):
    """A scanned page: one or more image bands and nothing else. FedEx
    and Gerber split each scan into two bands, neither covering more
    than half the page."""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    img = pymupdf.open()
    ip = img.new_page(width=200, height=100)
    ip.draw_rect(pymupdf.Rect(10, 10, 190, 90), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    pix = ip.get_pixmap()
    for y0, y1 in bands:
        page.insert_image(pymupdf.Rect(0, y0, width, y1), pixmap=pix)
    if text:
        page.insert_text((300, 700), text)
    path = tmp_path / "scan.pdf"
    doc.save(path)
    return str(path)


def test_a_scanned_page_is_detected_and_unreadable(tmp_path):
    """No text, no title block, only pixels: the page is still emitted,
    with no number and an unreadable reason. Silence would read as
    "nothing electrical here" (CLAUDE.md)."""
    path = _scan(tmp_path, bands=[(0, 792)])
    (s,) = documents.detect_sheets(path)
    assert s.number == ""
    assert s.title == "Scanned sheet"
    assert s.kind == "other"
    assert s.unreadable_reason


def test_a_scan_split_into_two_bands_is_still_a_scan(tmp_path):
    """FedEx's letter-portrait pages carry a landscape scan as two bands
    covering 55 % of the page between them and never more than 29 % each.
    Coverage is summed over every image, not taken from the largest."""
    path = _scan(tmp_path, bands=[(177, 405), (405, 615)])
    (s,) = documents.detect_sheets(path)
    assert s.unreadable_reason


def test_a_scan_with_a_typed_number_cell_is_still_a_scanned_sheet(tmp_path):
    """A scan whose title block is text -- a number cell typed over the
    image after scanning -- keeps its number, and nothing else: the
    same "Scanned sheet" / other outcome as an unnumbered scan. It used
    to come out titled "Electrical" and kind plan, which claimed a
    reading of a page nobody read."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    img = pymupdf.open()
    ip = img.new_page(width=200, height=100)
    ip.draw_rect(pymupdf.Rect(10, 10, 190, 90), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    page.insert_image(pymupdf.Rect(0, 0, 1000, 800), pixmap=ip.get_pixmap())
    page.insert_text((900, 60), "SHEET")
    page.insert_text((900, 770), "E2.1")
    path = tmp_path / "typed-scan.pdf"
    doc.save(path)
    (s,) = documents.detect_sheets(str(path))
    assert s.number == "E2.1"
    assert s.title == "Scanned sheet"
    assert s.kind == "other"
    assert s.unreadable_reason == documents.SCANNED_REASON


def test_unreadable_reasons_read_as_estimator_copy():
    """The reason is shown on the canvas banner, so it follows the copy
    rules: a sentence in plain drafting words, no file internals
    (CLAUDE.md), sentence case, one period at the end for the banner to
    strip."""
    for reason in (documents.SCANNED_REASON, documents.OUTLINED_REASON):
        low = reason.lower()
        for internal in ("vector", "path", "pdf", "raster", "layer", "font", "ocr"):
            assert internal not in low.split() and f" {internal}s" not in low, (reason, internal)
        for banned in ("!", "please", "successfully", "isn't available"):
            assert banned not in low, (reason, banned)
        assert reason[0].isupper() and reason.endswith(".") and not reason.endswith("..")
        assert "not counted" in low


def test_a_page_of_outlined_text_is_detected_and_unreadable(tmp_path):
    """TSC Nutrition's fourteen electrical pages carry no text layer --
    the text was outlined to drawing paths when the PDF was made. Five
    thousand paths and not one word. Like a scan, the page is emitted
    as a sheet nobody can read, with its own reason, rather than
    dropped: fourteen pages of silence would read as completeness."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    for i in range(500):
        page.draw_line((50 + (i % 40) * 20, 100 + (i // 40) * 30), (60 + (i % 40) * 20, 110 + (i // 40) * 30))
    path = tmp_path / "outlined.pdf"
    doc.save(path)
    (s,) = documents.detect_sheets(str(path))
    assert s.number == ""
    assert s.title == "Sheet with outlined text"
    assert s.kind == "other"
    assert s.unreadable_reason == documents.OUTLINED_REASON


def test_a_wordless_page_with_an_image_and_a_few_paths_is_still_unreadable(tmp_path):
    """The ruling is "no words and (enough paths or any image)". A page
    with one image and a hundred paths is too many paths for _is_raster
    and too few for the outlined threshold; it must not fall between
    the two and vanish."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    img = pymupdf.open()
    ip = img.new_page(width=200, height=100)
    ip.draw_rect(pymupdf.Rect(10, 10, 190, 90), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    page.insert_image(pymupdf.Rect(100, 100, 500, 300), pixmap=ip.get_pixmap())
    for i in range(100):
        page.draw_line((50 + i * 9, 500), (55 + i * 9, 700))
    path = tmp_path / "mixed.pdf"
    doc.save(path)
    (s,) = documents.detect_sheets(str(path))
    assert s.number == ""
    assert s.kind == "other"
    assert s.unreadable_reason


def test_a_few_stray_paths_and_no_text_is_not_a_sheet(tmp_path):
    """A border rule and a logo box with no words is nothing; the
    outlined-text rule wants substantial drawing content."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    for i in range(documents.OUTLINED_MIN_DRAWINGS - 1):
        page.draw_line((50 + i, 100), (50 + i, 700))
    path = tmp_path / "stray.pdf"
    doc.save(path)
    assert documents.detect_sheets(str(path)) == []


def test_a_blank_page_is_not_a_scan(tmp_path):
    """No image, no text, no drawing: nothing to flag."""
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    path = tmp_path / "blank.pdf"
    doc.save(path)
    assert documents.detect_sheets(str(path)) == []


def _one_page_pdf(tmp_path, width=1000, height=800):
    doc = pymupdf.open()
    doc.new_page(width=width, height=height)
    path = tmp_path / "page.pdf"
    doc.save(path)
    doc.close()
    return str(path)


def test_evidence_crop_returns_a_valid_png_for_a_point_item(tmp_path):
    path = _one_page_pdf(tmp_path)
    png = documents.render_evidence_crop(path, 0, 1000, 800, [(500, 400)])
    assert png is not None
    doc = pymupdf.open(stream=png, filetype="png")
    assert doc[0].rect.width > 0 and doc[0].rect.height > 0


def test_evidence_crop_covers_every_placement_in_a_cluster(tmp_path):
    """A crop for a scattered cluster must not silently drop the ones
    farthest from the centroid -- render at a bounding box that contains
    every placement, even if that means a lower zoom."""
    path = _one_page_pdf(tmp_path)
    placements = [(50, 50), (900, 700)]
    png = documents.render_evidence_crop(path, 0, 1000, 800, placements)
    assert png is not None

    # The bounding box (with EVIDENCE_CLUSTER_MARGIN_PT margin, clamped
    # to the page) is 930 x 730 points, wider than it is tall, so the
    # oversized-bbox zoom-down path picks zoom = EVIDENCE_MAX_PX / 930
    # rather than the unclamped default -- confirm the returned PNG's
    # *pixel* dimensions actually reflect that, not just that a PNG
    # came back. Decoding straight into a Pixmap (rather than opening
    # the bytes as a one-page document and calling get_pixmap() on it)
    # reads the image's real pixel grid; going through a re-opened
    # page instead reports page.rect in points at 72 DPI, which is the
    # pixel size scaled by 0.75 -- not what we want to assert against.
    bbox_w, bbox_h = 930.0, 730.0
    expected_zoom = documents.EVIDENCE_MAX_PX / max(bbox_w, bbox_h)
    expected_zoom = max(documents.EVIDENCE_MIN_ZOOM, min(documents.EVIDENCE_MAX_ZOOM, expected_zoom))
    expected_w = round(bbox_w * expected_zoom)
    expected_h = round(bbox_h * expected_zoom)

    # A tolerance of a couple pixels absorbs mupdf's own rounding of a
    # fractional-pixel rect; it is nowhere near loose enough to pass if
    # the zoom formula regressed (e.g. reverting to EVIDENCE_MAX_ZOOM
    # unconditionally would be off by hundreds of pixels here).
    pix = pymupdf.Pixmap(png)
    assert abs(pix.width - expected_w) <= 2
    assert abs(pix.height - expected_h) <= 2
    # And the crop is not simply rendered at EVIDENCE_MAX_ZOOM -- the
    # whole point of the oversized-bbox path is zooming *down* to fit
    # the full cluster in frame.
    assert pix.width <= documents.EVIDENCE_MAX_PX + 1


def test_evidence_crop_clamps_to_the_page_at_a_corner(tmp_path):
    """A point right at the page edge must not ask pymupdf for a clip
    rect that extends past the page (a Rect with a negative or
    out-of-bounds coordinate is legal in pymupdf but must not be handed
    a nonsensical crop for a corner device)."""
    path = _one_page_pdf(tmp_path)
    png = documents.render_evidence_crop(path, 0, 1000, 800, [(2, 2)])
    assert png is not None


def test_evidence_crop_returns_none_for_a_bad_page_index(tmp_path):
    path = _one_page_pdf(tmp_path)
    assert documents.render_evidence_crop(path, 7, 1000, 800, [(500, 400)]) is None


def test_evidence_crop_returns_none_with_no_placements(tmp_path):
    path = _one_page_pdf(tmp_path)
    assert documents.render_evidence_crop(path, 0, 1000, 800, []) is None


def test_evidence_crop_returns_none_with_unmeasured_page_dims(tmp_path):
    """A sheet the Documents agent couldn't measure (width/height 0) must
    not crash the takeoff by dividing by zero when computing zoom."""
    path = _one_page_pdf(tmp_path)
    assert documents.render_evidence_crop(path, 0, 0, 0, [(500, 400)]) is None


# --- _drawing_scope_pages ----------------------------------------------
#
# Driven directly against hand-built DetectedSheets rather than through
# detect_sheets end-to-end: detect_sheets decides kind and schedule_text
# from a real title block and SCHEDULE_KEYWORDS match, which is already
# covered by the tests above and by test_corpus_sheets.py. What matters
# here is _drawing_scope_pages' own contract given a sheet list -- schedule
# text vs. the lazy page-text fallback, the plan filter, and the shared
# character budget -- so it is faster and clearer to construct the sheets
# directly than to engineer a synthetic PDF that would make detect_sheets
# produce them.

def _drawing_sheet(page_index, kind="other", schedule_text="", **kw):
    defaults = dict(
        number="", title="", discipline="Electrical", scale="",
        width_pt=1000.0, height_pt=800.0, region=(0.0, 0.0, 1000.0, 800.0),
    )
    defaults.update(kw)
    return DetectedSheet(page_index=page_index, kind=kind, schedule_text=schedule_text, **defaults)


def test_drawing_scope_pages_uses_schedule_text_when_present():
    """A schedule/legend sheet already carries its text from detect_sheets
    -- no need to reopen the file for it, and its page_index rides along
    unchanged."""
    sheet = _drawing_sheet(page_index=5, kind="schedule", schedule_text="EXCLUSIONS\n- Site lighting and pole bases.\n")
    pages = documents._drawing_scope_pages("unused.pdf", [sheet])
    assert pages == [(5, "EXCLUSIONS\n- Site lighting and pole bases.\n")]


def test_drawing_scope_pages_falls_back_to_the_page_text_when_schedule_text_is_empty(tmp_path):
    """A general-notes sheet (kind != plan, but its text didn't match
    SCHEDULE_KEYWORDS so detect_sheets left schedule_text "") is read
    fresh here, from the real page."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((72, 72), "BY OTHERS")
    page.insert_text((72, 96), "- Temporary power during construction.")
    path = tmp_path / "notes.pdf"
    doc.save(path)

    sheet = _drawing_sheet(page_index=0, kind="other", schedule_text="")
    pages = documents._drawing_scope_pages(str(path), [sheet])

    assert len(pages) == 1
    page_index, text = pages[0]
    assert page_index == 0
    assert "BY OTHERS" in text
    assert "Temporary power during construction." in text


def test_drawing_scope_pages_skips_plan_sheets():
    sheets = [
        _drawing_sheet(page_index=0, kind="plan", schedule_text="EXCLUSIONS\n- A plan sheet must never contribute scope text.\n"),
        _drawing_sheet(page_index=1, kind="schedule", schedule_text="EXCLUSIONS\n- Site lighting and pole bases.\n"),
    ]
    pages = documents._drawing_scope_pages("unused.pdf", sheets)
    assert [page_index for page_index, _ in pages] == [1]


def test_drawing_scope_pages_returns_nothing_when_every_sheet_is_a_plan():
    sheets = [_drawing_sheet(page_index=0, kind="plan", schedule_text="EXCLUSIONS\n- Ignored.\n")]
    assert documents._drawing_scope_pages("unused.pdf", sheets) == []


def test_drawing_scope_pages_caps_the_shared_budget_across_several_sheets():
    """Three non-plan sheets whose combined text exceeds SCOPE_MAX_CHARS:
    the first two are kept whole, the third is truncated to what's left
    of the shared budget, not dropped or read past the cap."""
    sheets = [
        _drawing_sheet(page_index=0, kind="schedule", schedule_text="A" * 5000),
        _drawing_sheet(page_index=1, kind="schedule", schedule_text="B" * 5000),
        _drawing_sheet(page_index=2, kind="schedule", schedule_text="C" * 5000),
    ]
    pages = documents._drawing_scope_pages("unused.pdf", sheets)
    assert [page_index for page_index, _ in pages] == [0, 1, 2]
    assert len(pages[0][1]) == 5000
    assert len(pages[1][1]) == 5000
    assert len(pages[2][1]) == documents.SCOPE_MAX_CHARS - 10000
