"""Documents agent -- sheet-number detection must read the title block,
not whichever E-number happens to repeat most in the page's body text. A
callout bubble referencing another sheet can otherwise outvote the title
block's own number (found against a real drawing set: a page whose title
block read E1.2 was labelled E5.1 because a referenced-sheet callout on
the page said E5.1 four times).

Two things make that title-block read hard on a real set, and both have
tests below:

  * Every page of an E-size set is drawn portrait and displayed
    landscape (/Rotate 90). `page.rect` is the *displayed* rect, but
    extracted text carries *unrotated* coordinates, so a clip computed
    from `page.rect` misses the title block entirely -- and the read
    silently falls through to the whole page on every single sheet.
  * The number box is the largest type on the sheet. Within the title
    block that is a far better signal than frequency, which is the
    signal that picked up the callouts in the first place.
"""
import os
import subprocess
import sys

import pymupdf
import pytest

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


def _rotated_sheet(tmp_path, own_number, own_size=36, extras=()):
    """A sheet built the way a real E-size bid set is: drawn on a
    portrait page and displayed landscape through /Rotate 90.

    Text is written in unrotated coordinates, so the title block -- the
    right-hand strip of the *displayed* sheet -- is the top band of the
    page as drawn. Displayed x = 1000 - y here, so the strip
    (displayed x >= 1000 * RIGHT_STRIP) is y <= 1000 * (1 - RIGHT_STRIP),
    i.e. y <= 180.

    `extras` is a list of (text, x, y, size) written in the same
    unrotated space, for callouts and references.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=1000)
    page.insert_text((400, 100), own_number, fontsize=own_size)
    for text, x, y, size in extras:
        page.insert_text((x, y), text, fontsize=size)
    # Rotate after writing, so the inserted coordinates stay the
    # unrotated ones the assertions above reason about.
    page.set_rotation(90)
    path = tmp_path / "rotated.pdf"
    doc.save(path)
    doc.close()
    return str(path)


def _number_of(path):
    doc = pymupdf.open(path)
    page = doc[0]
    return documents._sheet_number(page, page.get_text("text"))


def test_sheet_number_reads_the_title_block_on_a_rotated_page(tmp_path):
    """The regression that mislabelled a real bid set. `page.rect` is the
    displayed rect (landscape) while extracted text is in the unrotated
    portrait space, so a title-block clip taken from `page.rect` lands
    off the page and matches nothing -- on every sheet, not just this
    one. The read then falls back to the whole page and the callouts
    win."""
    path = _rotated_sheet(
        tmp_path,
        own_number="E1.2",
        extras=[("IAW SHEET E5.1", 200, 400 + i * 40, 9) for i in range(4)],
    )
    assert _number_of(path) == "E1.2"


def test_sheet_number_prefers_the_largest_type_in_the_title_block(tmp_path):
    """Title blocks carry references too -- a revision note or a
    'see also' line sits in the same strip as the number box. The number
    box is set several times larger than anything around it, so within
    the strip the type size decides, not the count."""
    path = _rotated_sheet(
        tmp_path,
        own_number="E3.1",
        extras=[
            ("SUPERSEDES E5.1", 400, 150, 8),
            ("SEE E5.1", 400, 170, 8),
        ],
    )
    assert _number_of(path) == "E3.1"


def test_sheet_number_is_stable_across_hash_seeds(tmp_path):
    """Two E-numbers with nothing to separate them -- same type size,
    same count, neither in a title block -- must still resolve the same
    way on every run. Ranking through a set (`max(set(ids), ...)`) makes
    the tie depend on PYTHONHASHSEED, which turns a sheet's identity into
    something that changes between processes reading the same file."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((100, 100), "E3.1")
    page.insert_text((100, 200), "E5.1")
    path = tmp_path / "tie.pdf"
    doc.save(path)
    doc.close()

    script = (
        "import pymupdf, sys;"
        "sys.path.insert(0, sys.argv[2]);"
        "from app.engine import documents;"
        "d = pymupdf.open(sys.argv[1]); p = d[0];"
        'print(documents._sheet_number(p, p.get_text("text")))'
    )
    # .../api/app/engine/documents.py -> .../api, the root `app` imports from
    api_dir = os.path.abspath(os.path.join(os.path.dirname(documents.__file__), "..", ".."))
    results = set()
    for seed in ("0", "1", "42", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(
            [sys.executable, "-c", script, str(path), api_dir],
            capture_output=True, text=True, check=True, env=env,
        )
        results.add(out.stdout.strip())
    assert results == {"E3.1"}, f"tie-break varied by hash seed: {results}"


# The real bid set this was found on. It is a 94-page drawing set that
# does not live in the repo, so the check runs only where it is present:
# point TAKEOFF_BID_SET_PDF at a copy to run it.
BID_SET_PDF = os.environ.get("TAKEOFF_BID_SET_PDF", "")

# What the set's own drawing index (its cover sheet and E0.1) lists,
# in page order -- fourteen electrical sheets, fourteen distinct numbers.
BID_SET_SHEETS = {
    80: "E0.1", 81: "E0.2", 82: "E0.3", 83: "E1.0", 84: "E1.1",
    85: "E1.2", 86: "E1.3", 87: "E2.1", 88: "E3.1", 89: "E4.1",
    90: "E5.1", 91: "E6.1", 92: "E6.2", 93: "E7.1",
}


@pytest.mark.skipif(not os.path.exists(BID_SET_PDF), reason="TAKEOFF_BID_SET_PDF not available")
def test_real_bid_set_pages_get_their_own_distinct_sheet_numbers():
    """The pass condition from the field: every electrical page in a real
    set resolves to the number its own title block reads, and no two
    pages claim the same one. Sheet number is what an estimator clicks
    through to and cites in the audit trail, so two pages sharing one is
    a correctness failure, not a cosmetic one."""
    sheets = documents.detect_sheets(BID_SET_PDF)
    found = {s.page_index: s.number for s in sheets}
    assert found == BID_SET_SHEETS
    assert len(set(found.values())) == len(found)


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
