"""Every row full_takeoff() produces carries a real evidence crop of the
source page, generated while the PDF is still open -- the only point in
the request lifecycle it's available."""
import base64

import pymupdf

from app.engine import estimate as estimate_mod


def _known_sheet_pdf(tmp_path):
    """Same shape as test_engine_counting.py's known_sheet fixture: a
    1000x800 sheet with 5 isolated 'A' tags and 3 isolated 'R' tags in
    the drawing area. Includes enough vector drawings so detect_sheets
    recognizes it as a drawing sheet (requires >= 500 drawings)."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    # Add sheet number and scale so detect_sheets recognizes it as electrical
    page.insert_text((100, 50), "E1.1 - Test Plan")
    page.insert_text((800, 50), "Scale: 1/8\" = 1'-0\"")

    # Add enough vector drawings (rects forming a grid) so detect_sheets sees it as a drawing
    # (requires >= 500 drawings per detect_sheets logic)
    for x in range(0, 1000, 20):
        for y in range(50, 800, 20):
            page.draw_rect((x, y, x + 15, y + 15))

    for i in range(5):
        page.insert_text((100 + i * 60, 100 + i * 40), "A")
    for i in range(3):
        page.insert_text((200 + i * 50, 400), "R")
    path = tmp_path / "known.pdf"
    doc.save(path)
    doc.close()
    return str(path)


def test_full_takeoff_rows_carry_a_decodable_evidence_crop(tmp_path):
    path = _known_sheet_pdf(tmp_path)
    result = estimate_mod.full_takeoff(path, location="")
    assert result["items"], "expected at least one counted row"
    with_crops = [r for r in result["items"] if r.get("evidence_png_b64")]
    assert with_crops, "expected at least one row to carry a crop"
    png_bytes = base64.b64decode(with_crops[0]["evidence_png_b64"])
    doc = pymupdf.open(stream=png_bytes, filetype="png")
    assert doc[0].rect.width > 0


def test_estimate_summary_rows_do_not_carry_crops(tmp_path):
    """The consolidated Instant-estimate summary (estimate(), not
    full_takeoff()) has no canvas and no per-item panel -- it must not
    pay the cost of generating crops it never shows."""
    path = _known_sheet_pdf(tmp_path)
    result = estimate_mod.estimate(path, location="")
    assert result["items"]
    assert all("evidence_png_b64" not in r for r in result["items"])
