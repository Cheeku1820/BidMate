"""Locate a sheet's title block and read its number and title.

A title block is a strip along one edge of the visual page; which edge
varies by firm (Unalaska's is along the visual bottom once the page's
90-degree rotation is applied). It is found by scoring each of the four
edge strips on how many sheet-number-family tokens and title-block
labels it holds. The sheet's own number is the family token nearest the
corner the strip ends at -- drafting convention puts the number cell
there -- which is what lets a revision table that repeats another
sheet's number three times lose to the one number cell.

Deterministic by construction: ties break by frequency in the strip,
then by first appearance in reading order. Nothing here iterates a set.
The previous implementation did (`max(set(ids), key=ids.count)`), and
the same page resolved to three different numbers across three
processes. Spec section 2.3.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .page_frame import Word

# The sheet-number family across the corpus: E2.1, E-101, E101, EP-1,
# EL101, EF-1, EX10, ED-101, EQ101. Two optional discipline letters, an
# optional hyphen, one to three digits, an optional decimal. The
# three-digit cap keeps a licence number like EE-12624 out. Broad enough
# to match a device tag ("E1"), so it is NEVER applied to whole-page
# text to decide whether a page is electrical -- only to the strip.
SHEET_ID = re.compile(r"\bE[A-Z]{0,2}-?\d{1,3}(?:\.\d{1,2})?\b")

# Labels a title block carries. Uppercase, compared against the word.
# SCALE is deliberately absent: a details sheet prints "SCALE: NONE" under
# every detail along one edge, and counting it let a row of detail
# callouts outscore the real title block (Unalaska E6.1, E6.2).
LABELS = {"SHEET", "DRAWN", "CHECKED", "DATE", "PROJECT", "REVISION", "REV", "TITLE"}

# The outer fraction of the page an edge strip covers.
STRIP = 0.18


@dataclass(frozen=True)
class TitleBlock:
    edge: str  # "bottom" | "right" | "top" | "left"
    strip: tuple[float, float, float, float]  # visual frame
    words: list[Word]  # every word inside the strip, reading order


def _strips(width: float, height: float) -> dict[str, tuple[float, float, float, float]]:
    return {
        "bottom": (0, height * (1 - STRIP), width, height),
        "right": (width * (1 - STRIP), 0, width, height),
        "top": (0, 0, width, height * STRIP),
        "left": (0, 0, width * STRIP, height),
    }


def _inside(w: Word, r: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = r
    return x0 <= w.cx <= x1 and y0 <= w.cy <= y1


def _score(words: list[Word]) -> int:
    """Distinct family tokens plus label occurrences. A token repeated
    across a strip is a callout pattern -- detail bubbles carrying the
    sheet's own number, a revision table -- and reads as one cell, not
    four; the labels are what make a strip a title block."""
    tokens = {w.text for w in words if SHEET_ID.fullmatch(w.text)}
    labels = sum(1 for w in words if w.text.upper().strip(":") in LABELS)
    return len(tokens) + labels


def locate(words: list[Word], width: float, height: float) -> TitleBlock | None:
    """The edge strip that reads most like a title block, or None when no
    strip holds a single family token or label -- in which case the page
    is not detected as an electrical sheet (spec 2.2)."""
    best: TitleBlock | None = None
    best_score = 0
    # Fixed iteration order (bottom, right, top, left): a tie between two
    # edges resolves the same way every run.
    for edge, strip in _strips(width, height).items():
        inside = [w for w in words if _inside(w, strip)]
        s = _score(inside)
        if s > best_score:
            best, best_score = TitleBlock(edge=edge, strip=strip, words=inside), s
    return best


def _corner(tb: TitleBlock) -> tuple[float, float]:
    x0, y0, x1, y1 = tb.strip
    return {
        "bottom": (x1, y1),
        "right": (x1, y1),
        "top": (x1, y0),
        "left": (x0, y1),
    }[tb.edge]


def _number_cell(tb: TitleBlock) -> Word | None:
    """The family token nearest the strip's end corner; ties by frequency
    in the strip, then first appearance. None when the strip holds none."""
    tokens = [w for w in tb.words if SHEET_ID.fullmatch(w.text)]
    if not tokens:
        return None
    cx, cy = _corner(tb)
    freq = Counter(w.text for w in tokens)
    first = {}
    for i, w in enumerate(tokens):
        first.setdefault(w.text, i)
    # Distance bands of 40pt: two tokens in the same cell are "equally
    # near"; the tiebreakers then decide, never float noise.
    return min(
        tokens,
        key=lambda w: (round(((w.cx - cx) ** 2 + (w.cy - cy) ** 2) ** 0.5 / 40), -freq[w.text], first[w.text]),
    )


def sheet_number(tb: TitleBlock) -> str:
    """The number cell's text; "" when the strip holds no family token."""
    cell = _number_cell(tb)
    return cell.text if cell else ""


# Words that mark an address, a signature line or a seal -- never a title.
_NOT_TITLE = {
    "SUITE", "BOULEVARD", "STREET", "AVENUE", "PHONE", "FAX", "CHECKED", "DRAWN",
    "DATE", "REGISTERED", "PROFESSIONAL", "ENGINEER", "SHEET", "PROJECT", "NO.",
}
# How far from the number cell a title line may start, in points --
# the gap between the line's nearest word and the cell, so a title that
# runs away from the cell along the strip (a rotated column) is admitted
# by its first word and read to its last.
_TITLE_REACH = 120.0


def _gap(w: Word, cell: Word) -> float:
    """Distance between two word boxes; 0 when they touch or overlap."""
    return max(0.0, w.x0 - cell.x1, cell.x0 - w.x1, w.y0 - cell.y1, cell.y0 - w.y1)


def _thickness(w: Word) -> float:
    """A word's extent across its reading direction -- its type size,
    whichever way it runs -- for a word of more than one character."""
    return min(w.x1 - w.x0, w.y1 - w.y0)


def _passes(words: list[str]) -> bool:
    """The sanity check, over the whole cell: 2-10 uppercase words (bare
    punctuation allowed), no digits-only or mixed-case token, none of
    _NOT_TITLE, and no label -- a cell label ends in a colon ("AUTHOR:",
    "ISSUE DATE:") and a title never does. Any miss fails the whole cell
    rather than dropping the offending word: a cell with "103" in it is
    not a title with a number silently removed, it is not the title."""
    if not 2 <= len(words) <= 10:
        return False
    for t in words:
        if t.endswith(":"):
            return False
        if not t.isupper() and any(c.isalnum() for c in t):
            return False
        if t.strip(",.:") in _NOT_TITLE:
            return False
    return True


def title(tb: TitleBlock, number: str) -> str:
    """The title cell: the largest-set text lines beside the number
    cell, joined, sentence-cased. "" when the cell fails _passes.

    Measured on the real set: the title is one rotated line in a bigger
    face beside a horizontal number cell, with the author / date / project
    cells (smaller, colon-terminated) stacked between the two. So a line
    is admitted by its nearest word (_TITLE_REACH), and the line(s) set
    in the largest type are the cell -- a multi-line title shares one
    size, an author's initials do not. The whole cell then passes the
    sanity check or the title is "".
    """
    cell = _number_cell(tb)
    if cell is None or cell.text != number:
        cell = next((w for w in tb.words if w.text == number), None)
    if cell is None:
        return ""
    lines: dict[tuple[int, int], list[Word]] = {}
    for w in tb.words:
        if w is not cell:
            lines.setdefault((w.block, w.line), []).append(w)
    # Reading order by (block, line); words within a line as extracted.
    near = [
        (key, ws) for key, ws in sorted(lines.items())
        if any(_gap(w, cell) <= _TITLE_REACH for w in ws)
    ]
    if not near:
        return ""
    size = {key: round(max(_thickness(w) for w in ws)) for key, ws in near}
    largest = max(size.values())
    words = [w.text for key, ws in near if size[key] == largest for w in ws]
    if not _passes(words):
        return ""
    text = " ".join(words).strip(" ,.")
    return text[:1].upper() + text[1:].lower()
