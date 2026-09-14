"""Coordinate frames for a PDF page.

PyMuPDF mixes two frames on a rotated page. `page.rect` and
`page.get_pixmap()` (including its `clip`) are in the VISUAL frame --
what a viewer shows. `page.get_text()`, `page.get_textbox()` and
`page.get_drawings()` are in the UNROTATED mediabox frame. On a page
with rotation 90 the two differ by a transpose and a flip, so a clip
built in one and applied in the other silently selects the wrong
region. That is how the counting region came to exclude the visual
right third of every Unalaska sheet, and how markers came to sit off
the drawing. Measured 2026-09-14, spec section 1.1.

Everything the engine reasons about is in the visual frame, and this
module is the only place the transform happens. No other module calls
`page.get_text("words")` or `page.get_text("dict")`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf


@dataclass(frozen=True)
class Word:
    """One whitespace-delimited token, visual frame."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int
    line: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def to_visual(rect, page: pymupdf.Page) -> pymupdf.Rect:
    """Unrotated-frame rect -> visual-frame rect."""
    return pymupdf.Rect(rect) * page.rotation_matrix


def to_unrotated(rect, page: pymupdf.Page) -> pymupdf.Rect:
    """Visual-frame rect -> unrotated-frame rect (what get_textbox wants)."""
    return pymupdf.Rect(rect) * page.derotation_matrix


def visual_words(page: pymupdf.Page) -> list[Word]:
    m = page.rotation_matrix
    out: list[Word] = []
    for x0, y0, x1, y1, text, block, line, _word in page.get_text("words"):
        r = pymupdf.Rect(x0, y0, x1, y1) * m
        out.append(Word(r.x0, r.y0, r.x1, r.y1, text, block, line))
    return out


def visual_spans(page: pymupdf.Page) -> list[tuple[float, float, str]]:
    """(centre x, centre y, font name) for every text span, visual frame.
    The seal filter in counting.py keys on the font."""
    m = page.rotation_matrix
    out: list[tuple[float, float, str]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                r = pymupdf.Rect(span["bbox"]) * m
                out.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, span["font"]))
    return out
