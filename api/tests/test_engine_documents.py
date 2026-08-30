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
