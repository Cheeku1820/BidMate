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
LABELS = {"SHEET", "DRAWN", "CHECKED", "DATE", "PROJECT", "REVISION", "REV", "SCALE", "TITLE"}

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
    return sum(1 for w in words if SHEET_ID.fullmatch(w.text) or w.text.upper().strip(":") in LABELS)


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


def sheet_number(tb: TitleBlock) -> str:
    """The family token nearest the strip's end corner; ties by frequency
    in the strip, then first appearance. "" when the strip holds none."""
    tokens = [w for w in tb.words if SHEET_ID.fullmatch(w.text)]
    if not tokens:
        return ""
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
    ).text


# Words that mark an address, a signature line or a seal -- never a title.
_NOT_TITLE = {
    "SUITE", "BOULEVARD", "STREET", "AVENUE", "PHONE", "FAX", "CHECKED", "DRAWN",
    "DATE", "REGISTERED", "PROFESSIONAL", "ENGINEER", "SHEET", "PROJECT", "NO.",
}
# How far from the number cell the title cell may sit, in points.
_TITLE_REACH = 120.0


def title(tb: TitleBlock, number: str) -> str:
    """The title cell: uppercase lines within _TITLE_REACH of the number
    cell, joined, sentence-cased. "" when nothing passes the sanity check
    (2-10 words, no digits-only tokens, none of _NOT_TITLE)."""
    cell = next((w for w in tb.words if w.text == number), None)
    if cell is None:
        return ""
    near = [
        w for w in tb.words
        if w.text != number
        and abs(w.cx - cell.cx) <= _TITLE_REACH
        and abs(w.cy - cell.cy) <= _TITLE_REACH
        and w.text.isupper()
    ]
    # Group by text line, keep reading order.
    lines: dict[tuple[int, int], list[str]] = {}
    for w in near:
        lines.setdefault((w.block, w.line), []).append(w.text)
    words: list[str] = [t for _, ts in sorted(lines.items()) for t in ts]
    if not 2 <= len(words) <= 10:
        return ""
    if any(t.isdigit() for t in words):
        return ""
    if any(t.strip(",.:") in _NOT_TITLE for t in words):
        return ""
    text = " ".join(words).strip(" ,.")
    return text[:1].upper() + text[1:].lower()
