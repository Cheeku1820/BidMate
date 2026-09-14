"""Locate a sheet's title block and read its number and title.

A title block is a strip along one edge of the visual page; which edge
varies by firm (Unalaska's is along the visual RIGHT once the page's
90-degree rotation is applied, with the number cell at the bottom-right
corner -- the plan that built this predicted the visual bottom, and the
rendered page proved it wrong: `get_pixmap` at 0.3 on page 87 shows the
strip on the right, and the number cell maps from unrotated (1495, 64)
to visual (2348, 1513)). It is the edge strip holding the page's
largest sheet-number-shaped token -- any discipline's, `ANY_SHEET_ID`
-- because the number cell is set in display type and everything else
shaped like a sheet number (a general-notes block saying SEE SHEET
E-501, a fan schedule's EF-1..EF-6, a cover's drawing index, an
equipment tag spilling in from the drawing) is set in body type. Ties,
which happen whenever the number cell sits in the corner two strips
share, break on how many distinct tokens and title-block labels a strip
holds. The sheet's own number is the largest sheet-number-shaped token
in that strip, then the one nearest the corner the strip ends at --
drafting convention puts the number cell there -- and the page is an
electrical sheet only when that token is in the E family (`SHEET_ID`).
A mechanical sheet numbered M1.01 with an EF-7 tag in its strip reads
as M1.01 and is not electrical; before the size rule it read as EF-7
and was (TSC Nutrition, 2026-09-14).

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

# Any discipline's sheet number: A6.01, G0.00, M1.01, T402, C101, P-401,
# and every SHEET_ID. Candidates for the number cell come from this
# shape, so a page whose corner cell reads M1.01 is read as M1.01 and
# then rejected as not electrical, rather than having its number taken
# from whatever family token happens to be in the strip.
ANY_SHEET_ID = re.compile(r"\b[A-Z]{1,3}-?\d{1,3}(?:\.\d{1,2})?\b")

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
    """Distinct family tokens plus label occurrences -- the tiebreak when
    the number cell sits in the corner two strips share. A token repeated
    across a strip is a callout pattern -- detail bubbles carrying the
    sheet's own number, a revision table -- and reads as one cell, not
    four; the labels are what make a strip a title block. Family tokens
    only: the any-discipline shape also matches circuit and equipment
    tags (BPW-3, UH-4, W1), and a plan's bottom strip holds dozens of
    those -- counting them moved United Utility's title block from the
    right edge to the bottom and cut the counting region on the wrong
    side."""
    tokens = {w.text for w in words if SHEET_ID.fullmatch(w.text)}
    labels = sum(1 for w in words if w.text.upper().strip(":") in LABELS)
    return len(tokens) + labels


def _size(w: Word) -> int:
    """A token's type size to the point -- what the strip and number-cell
    rules rank by. Whole points: two tokens set in one face are equal,
    float noise never orders them."""
    return round(_thickness(w))


def _largest_token(words: list[Word]) -> int:
    """The type size of the largest sheet-number-shaped token; 0 if none."""
    return max((_size(w) for w in words if ANY_SHEET_ID.fullmatch(w.text)), default=0)


def locate(words: list[Word], width: float, height: float) -> TitleBlock | None:
    """The edge strip that reads most like a title block: the one holding
    the largest sheet-number-shaped token, then -- the number cell sits
    in a corner two strips share -- the one with more distinct tokens and
    labels. None when no strip holds a token or a label, in which case
    the page is not detected as an electrical sheet (spec 2.2).

    Size first, because a strip full of body type can out-count a title
    block: Kittles Saxony's top-edge general notes hold five distinct
    "SEE SHEET E-xxx" tokens and four SHEET labels against the right
    strip's one number cell, and TSC Nutrition's fan schedules and
    equipment tags do the same. The number cell is display type; none of
    those are."""
    best: TitleBlock | None = None
    best_key = (0, 0)
    # Fixed iteration order (bottom, right, top, left): a tie between two
    # edges resolves the same way every run.
    for edge, strip in _strips(width, height).items():
        inside = [w for w in words if _inside(w, strip)]
        key = (_largest_token(inside), _score(inside))
        if key > best_key:
            best, best_key = TitleBlock(edge=edge, strip=strip, words=inside), key
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
    """The sheet-number-shaped token (any discipline) set largest in the
    strip; among those, nearest the strip's end corner; ties by frequency
    in the strip, then first appearance. None when the strip holds none.

    None, too, when two or more *distinct* tokens share the largest
    size: that is an index, not a number cell. A cover sheet's drawing
    index runs down an edge strip with every row in one face, and
    picking by corner from it is picking by row order -- Unalaska's and
    TSC Nutrition's covers both came out as whichever row sat last. A
    number cell is one number set larger than anything shaped like it;
    the same number repeated (a callout bubble set as large as the
    cell) is still one."""
    tokens = [w for w in tb.words if ANY_SHEET_ID.fullmatch(w.text)]
    if not tokens:
        return None
    largest = max(_size(w) for w in tokens)
    if len({w.text for w in tokens if _size(w) == largest}) > 1:
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
        key=lambda w: (
            -_size(w),
            round(((w.cx - cx) ** 2 + (w.cy - cy) ** 2) ** 0.5 / 40),
            -freq[w.text],
            first[w.text],
        ),
    )


def sheet_number(tb: TitleBlock) -> str:
    """The number cell's text when it is in the E family; "" when the
    strip holds no sheet-number-shaped token or its number cell belongs
    to another discipline (spec 2.5: no whole-page fallback, and no
    taking a family token from elsewhere in the strip either)."""
    cell = _number_cell(tb)
    return cell.text if cell and SHEET_ID.fullmatch(cell.text) else ""


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


def _is_value(text: str) -> bool:
    """A token that is more digits than letters: a project number
    (24108, 25-0107LE), a date (2025.01.31), a count. Never a title word
    -- but "1ST" and "2ND" are words."""
    return sum(c.isdigit() for c in text) > sum(c.isalpha() for c in text)


def _is_value_line(words: list[Word]) -> bool:
    """A line made only of values is another cell of the block -- the
    project-number cell, the date cell -- not a line of the title.
    Kittles Saxony sets CDG NO. 24108 above the title in a larger face;
    United Utility sets Project Number 25-0107LE on the row above in
    the same face. Left out of the cell; the title still reads. A value
    inside a line of words is a different case and still fails the
    whole cell (_passes)."""
    return all(_is_value(w.text) for w in words)


# An issue stamp -- RELEASED FOR CONSTRUCTION, NOT FOR CONSTRUCTION,
# ISSUED FOR BID, PRELIMINARY -- is stamped across the strip in display
# type, often rotated, and is not a cell of the block. Kittles Saxony's
# ran beside every number cell in a face larger than the title's, and
# every title read "Released for construction".
_STAMP_WORDS = {"RELEASED", "ISSUED", "PRELIMINARY"}
_STAMP_PHRASES = ("FOR CONSTRUCTION", "NOT FOR", "BID SET", "PERMIT SET", "PROGRESS SET")


def _is_stamp(words: list[Word]) -> bool:
    text = " ".join(w.text.upper() for w in words)
    return any(w.text.upper() in _STAMP_WORDS for w in words) or any(p in text for p in _STAMP_PHRASES)


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
    is admitted by its nearest word (_TITLE_REACH), value lines and
    issue stamps are left out as cells that are not the title
    (_is_value_line, _is_stamp), and the line(s) set in the largest type
    are the cell -- a multi-line title shares one size, an author's
    initials do not. The whole cell then passes the sanity check or the
    title is "".
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
        and not _is_value_line(ws) and not _is_stamp(ws)
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
