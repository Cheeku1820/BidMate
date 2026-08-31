"""Documents agent -- sheet-number detection must read the title block,
not whichever E-number happens to repeat most in the page's body text. A
callout bubble referencing another sheet can otherwise outvote the title
block's own number (found against a real drawing set: a page whose title
block read E1.2 was labelled E5.1 because a referenced-sheet callout on
the page said E5.1 four times).
"""
import pymupdf

from app.engine import documents


def _page_with_callouts(tmp_path, own_number: str, referenced_number: str, referenced_repeats: int):
    """A 1000x800 landscape sheet whose title block (right-hand strip,
    matching documents.RIGHT_STRIP) carries `own_number`, and whose body
    carries `referenced_number` repeated `referenced_repeats` times --
    enough to outvote a title block that only appears once if the bug is
    present."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    tb_x = 1000 * documents.RIGHT_STRIP + 20
    page.insert_text((tb_x, 700), own_number)
    for i in range(referenced_repeats):
        page.insert_text((100 + i * 40, 100 + i * 20), referenced_number)
    path = tmp_path / "sheet.pdf"
    doc.save(path)
    doc.close()
    return str(path)


def test_sheet_number_prefers_the_title_block(tmp_path):
    path = _page_with_callouts(tmp_path, own_number="E1.2", referenced_number="E5.1", referenced_repeats=4)
    doc = pymupdf.open(path)
    page = doc[0]
    text = page.get_text("text")
    assert documents._sheet_number(page, text) == "E1.2"


def test_sheet_number_falls_back_to_whole_page_when_title_block_is_silent(tmp_path):
    """A page whose title-block strip has no machine-readable E-number
    (some scanned or oddly-drafted sets) still gets *a* number rather
    than an empty one, from whatever the page carries."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((100, 100), "E3.1")
    path = tmp_path / "sheet.pdf"
    doc.save(path)
    doc.close()
    doc = pymupdf.open(path)
    page = doc[0]
    assert documents._sheet_number(page, page.get_text("text")) == "E3.1"


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
