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
