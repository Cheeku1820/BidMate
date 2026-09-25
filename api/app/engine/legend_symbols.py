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
# One character only. Every genuine switch-variant subscript measured on
# the corpus is a single character (Unalaska E0.1: "3", "4", "D", "K").
# Two-character words that satisfy the same touching-proximity rule turn
# out to be circuit numbers beside a receptacle ("43", "31" on Kittles
# Saxony EP101, B3c task 6 round 2) -- not a device variant, and with no
# legend row to rank against (rank_templates would never find one), so
# every instance a two-digit "modifier" split off landed with no
# suggestion. Capping at 1 char means a genuine two-character subscript
# (none seen yet) is missed and its instances simply fold into the plain
# cluster -- counted, just not split out -- which is the safe direction:
# silence never drops a device, it only under-splits one. Shared with the
# counting side (engine/counting.py's modifier split) deliberately: a
# legend row's own subscript is single-character too.
MAX_MODIFIER_CHARS = 1
# How far right of a glyph its description can run before the words
# belong to another column.
DESCRIPTION_REACH_PT = 240.0
# The longest description a row may carry. The row band is vertical
# only (spec §11.7), so a tall glyph beside a dense text column sweeps
# an 80 pt strip and collects every line inside the reach above -- the
# reviewer measured a plausible row at 329 characters. Two consumers
# refuse that: `SymbolMatch.suggested_name` is String(300) and raises on
# flush, failing the whole symbol search; and `edit_validation` refuses a
# name over 300, so the suggestion is unacceptable by clicking it.
# Capped here, at the one place the join happens, for the same reason
# `actions.commit()` caps `Action.label` at its own column width rather
# than at each call site that builds one. 240 is well above the corpus
# worst case (111 characters over 416 templates, spec §11.7), so no real
# legend row is touched; a row long enough to reach it is already a bad
# description, and a shortened suggestion beats a hard failure.
MAX_DESCRIPTION_CHARS = 240
# The silhouette grid, and the render it is pooled from.
SIL = 32
SPAN = 96
INK_THRESHOLD = 128


def renderer(page):
    """A page's display list -- what to hand `silhouette` when clipping
    more than one glyph out of the same page.

    `Page.get_pixmap` re-interprets the page's whole content stream on
    every call, and does not amortise that across clips: on the densest
    corpus sheet (Pulte Sagebriar E-210, 1.6 M paths) each of 16 clips
    cost about 1.35 s, 18.2 s added to a sheet job that otherwise runs
    in 36 s. The display list is that interpretation, done once and
    replayed per clip: the same 16 clips take 0.78 s to build plus
    0.42 s to draw. The pixels are identical -- same matrix, same clip
    rect, same colourspace, and `get_displaylist()` includes annotations
    exactly as `get_pixmap` does by default.
    """
    return page.get_displaylist()


def silhouette(source, rect) -> bytes:
    """The glyph inside `rect`, as SIL x SIL ink fractions (one byte each,
    row-major). The clip is rendered so its long side spans SPAN px, ink
    is `pixel < INK_THRESHOLD`, and the result is area-pooled to SIL --
    the pooling is what makes a 5 pt plan glyph comparable to an 18 pt
    legend glyph.

    `source` is a `Page` or that page's `renderer()`. One clip off a page
    is as cheap either way; several off the same page want the display
    list (see `renderer`)."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return bytes(SIL * SIL)
    zoom = SPAN / max(w, h)
    pix = source.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                            clip=pymupdf.Rect(x0, y0, x1, y1), colorspace=pymupdf.csGRAY)
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    ink = (grey < INK_THRESHOLD).astype(np.float32)[:SPAN, :SPAN]
    square = np.zeros((SPAN, SPAN), dtype=np.float32)
    oy, ox = (SPAN - ink.shape[0]) // 2, (SPAN - ink.shape[1]) // 2
    square[oy:oy + ink.shape[0], ox:ox + ink.shape[1]] = ink
    cell = SPAN // SIL
    pooled = square.reshape(SIL, cell, SIL, cell).mean(axis=(1, 3))
    return bytes(np.clip(pooled * 255.0, 0, 255).astype(np.uint8).ravel())


def _capped(description: str) -> str:
    """`description`, no longer than MAX_DESCRIPTION_CHARS, cut on a word
    boundary. The ellipsis is the same one `actions.commit()` uses on an
    over-long label: a shortened name should read as shortened, not as a
    word someone mistyped."""
    if len(description) <= MAX_DESCRIPTION_CHARS:
        return description
    head = description[:MAX_DESCRIPTION_CHARS - 1]
    whole = head.rsplit(" ", 1)[0] if " " in head else head
    return whole.rstrip() + "…"


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
    # One interpretation of the page for every row on it -- a legend
    # sheet carries 80 to 126 of them across the corpus.
    draw = renderer(page)
    out: list[SymbolTemplate] = []
    for g in found:
        x0, y0, x1, y1 = g.rect
        cy, height = (y0 + y1) / 2, y1 - y0
        band = [w for w in words if abs(w.cy - cy) <= max(height, 6.0)]
        modifier = ""
        modifier_word: Word | None = None
        for w in band:
            text = w.text.strip()
            if len(text) <= MAX_MODIFIER_CHARS and text and _near(g.rect, w, MODIFIER_PT):
                modifier = text
                modifier_word = w
                break
        # Exclude the modifier by identity, not text: a description word
        # that happens to share the modifier's text ("TYPE 3 OUTLET" beside
        # a "3" modifier) is still part of the description.
        right = [w for w in band if w.x0 >= x1 - 1 and w.x0 <= x1 + DESCRIPTION_REACH_PT
                 and w is not modifier_word]
        # Most legend columns read left-to-right, but a row drawn with its
        # words to the left of the glyph is still a row, not a stray
        # drawing. Only fall back to the left when the right side found
        # nothing, so a normal right-hand column never loses to it.
        chosen = right if right else [
            w for w in band if w.x1 <= x0 + 1 and w.x1 >= x0 - DESCRIPTION_REACH_PT
            and w is not modifier_word]
        chosen.sort(key=lambda w: (round(w.cy), w.x0))
        description = _capped(" ".join(w.text.strip() for w in chosen if w.text.strip()))
        if not description:
            continue
        out.append(SymbolTemplate(description=description, modifier=modifier, rect=g.rect,
                                  silhouette=silhouette(draw, g.rect), sheet_number=sheet_number))
    return out


# Below this correlation a template is unrelated, not a worse guess. A
# floor, never a decision: the measurement that killed thresholded
# naming is in spec section 1.1 -- true matches run 0.5 to 0.88 and two
# near-identical legend rows score 0.86 against each other, so the
# ranking is offered and a person picks.
SUGGESTION_FLOOR = 0.30
MAX_SUGGESTIONS = 4


def _grid(sil: bytes) -> np.ndarray:
    return np.frombuffer(sil, dtype=np.uint8).reshape(SIL, SIL).astype(np.float32)


def _unit(a: np.ndarray) -> np.ndarray:
    x = a - a.mean()
    n = float(np.sqrt((x * x).sum()))
    return x / n if n else x


def match_score(a: bytes, b: bytes) -> float:
    """The best zero-mean normalised correlation of two ink-fraction
    grids over the eight dihedral transforms -- a symbol drawn rotated or
    mirrored is the same symbol (glyphs._forms enumerates the same
    eight)."""
    if len(a) != SIL * SIL or len(b) != SIL * SIL:
        return 0.0
    ga, gb = _unit(_grid(a)), _grid(b)
    best = 0.0
    for k in range(4):
        rot = np.rot90(gb, k)
        for candidate in (rot, np.fliplr(rot)):
            best = max(best, float((ga * _unit(candidate)).sum()))
    return best


def rank_templates(sil: bytes, modifier: str, templates, limit: int = MAX_SUGGESTIONS):
    """The legend rows this silhouette looks most like, best first. Only
    rows with the same modifier are eligible; the score orders the list
    and never leaves this module."""
    scored = [(match_score(sil, t.silhouette), i, t)
              for i, t in enumerate(templates) if (t.modifier or "") == (modifier or "")]
    scored = [s for s in scored if s[0] >= SUGGESTION_FLOOR]
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [t for _score, _i, t in scored[:limit]]
