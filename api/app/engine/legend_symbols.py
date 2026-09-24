"""The legend, read as rows (B3c spec §3).

Every set carries a legend sheet that names its own symbols. This module
cuts that sheet into (glyph, modifier, description) rows and renders each
glyph to a small ink-fraction silhouette, so a cluster found on a plan
can be ranked against the drafter's own words for it.

Silhouettes, not paths: a plan symbol is drawn at about half the legend's
size with slightly different segment counts (measured on the corpus,
spec §1.1), which is exactly what glyphs.same_shape is built not to
tolerate. Ink-fraction pooling is what survives the scale change -- a
binary silhouette is dominated by relative stroke weight, and that is the
thing that differs.

Nothing here decides anything: it ranks, and a person picks (spec §1.1).
"""
from __future__ import annotations

import numpy as np
import pymupdf

from app.engine import glyphs
from app.engine.contracts import SymbolTemplate
from app.engine.page_frame import Word

# A subscript touching the glyph ("3", "D") distinguishes a switch
# variant that shares one drawn symbol.
MODIFIER_PT = 2.0
MAX_MODIFIER_CHARS = 2
# How far right of a glyph its description can run before the words
# belong to another column.
DESCRIPTION_REACH_PT = 240.0
# The silhouette grid, and the render it is pooled from.
SIL = 32
SPAN = 96
INK_THRESHOLD = 128


def silhouette(page, rect) -> bytes:
    """The glyph inside `rect`, as SIL x SIL ink fractions (one byte each,
    row-major). The clip is rendered so its long side spans SPAN px, ink
    is `pixel < INK_THRESHOLD`, and the result is area-pooled to SIL --
    the pooling is what makes a 5 pt plan glyph comparable to an 18 pt
    legend glyph."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return bytes(SIL * SIL)
    zoom = SPAN / max(w, h)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                          clip=pymupdf.Rect(x0, y0, x1, y1), colorspace=pymupdf.csGRAY)
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    ink = (grey < INK_THRESHOLD).astype(np.float32)[:SPAN, :SPAN]
    square = np.zeros((SPAN, SPAN), dtype=np.float32)
    oy, ox = (SPAN - ink.shape[0]) // 2, (SPAN - ink.shape[1]) // 2
    square[oy:oy + ink.shape[0], ox:ox + ink.shape[1]] = ink
    cell = SPAN // SIL
    pooled = square.reshape(SIL, cell, SIL, cell).mean(axis=(1, 3))
    return bytes(np.clip(pooled * 255.0, 0, 255).astype(np.uint8).ravel())


def _near(rect, word: Word, gap: float) -> bool:
    x0, y0, x1, y1 = rect
    return word.x0 <= x1 + gap and word.x1 >= x0 - gap and word.y0 <= y1 + gap and word.y1 >= y0 - gap


def sentence_case(text: str) -> str:
    """Legend words as an item name. An acronym of four letters or fewer
    keeps its case ("GFI", "NEMA"); everything else reads as a sentence."""
    words = (text or "").split()
    out = []
    for i, w in enumerate(words):
        if w.isupper() and len(w) <= 4 and any(c.isalpha() for c in w):
            out.append(w)
        elif i == 0:
            out.append(w.capitalize())
        else:
            out.append(w.lower())
    return " ".join(out)


def templates_on(page, words: list[Word], sheet_number: str = "") -> list[SymbolTemplate]:
    """Every legend row on this page, in reading order. A glyph with no
    description beside it is a stray drawing, not a row."""
    found = glyphs.glyphs_on(page, (0, 0, page.rect.width, page.rect.height), words)
    found.sort(key=lambda g: (round(g.rect[1]), g.rect[0]))
    out: list[SymbolTemplate] = []
    for g in found:
        x0, y0, x1, y1 = g.rect
        cy, height = (y0 + y1) / 2, y1 - y0
        band = [w for w in words if abs(w.cy - cy) <= max(height, 6.0)]
        modifier = ""
        for w in band:
            text = w.text.strip()
            if len(text) <= MAX_MODIFIER_CHARS and text and _near(g.rect, w, MODIFIER_PT):
                modifier = text
                break
        right = [w for w in band if w.x0 >= x1 - 1 and w.x0 <= x1 + DESCRIPTION_REACH_PT
                 and w.text.strip() != modifier]
        right.sort(key=lambda w: (round(w.cy), w.x0))
        description = " ".join(w.text.strip() for w in right if w.text.strip())
        if not description:
            continue
        out.append(SymbolTemplate(description=description, modifier=modifier, rect=g.rect,
                                  silhouette=silhouette(page, g.rect), sheet_number=sheet_number))
    return out
