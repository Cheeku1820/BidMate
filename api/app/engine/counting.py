"""Counting agent (v1, tag-based).

Emits unlabelled DeviceCluster records: repeated device tags within a
sheet's drawing region, each with exact coordinates read from the text
layer (not a model's guess -- the tag sits on the device). Counting does
not know what any cluster is; Classification names it.

This is the deterministic core the architecture insists on: it is tested
against known counts (test_engine_counting.py), never tuned. v1 reads the
text tags a drafter wrote; a later version adds Tier-B geometry clustering
for untagged symbols behind this same DeviceCluster output.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

import pymupdf

from .contracts import DetectedSheet, DeviceCluster, Placement

# A device tag: a short uppercase code (fixture type, receptacle, switch,
# junction, panel/circuit designator). Compound tokens ("D,O") and mixed
# case words (names, notes) are not device tags.
TAG = re.compile(r"^[A-Z]{1,3}\d{0,2}$")

# Tokens that match the tag shape but are drafting/annotation noise, never
# devices. Kept explicit so the exclusion is auditable. Includes the short
# all-caps English words a general-notes block throws off.
NOISE = {
    "TYP", "NO", "TO", "OF", "AT", "UP", "DN", "FT", "IN", "EX", "SC", "GC", "EC",
    "ON", "PF", "NIC", "AFF", "GND", "MIN", "MAX", "REF", "SIM", "EQ", "OC",
    "AND", "THE", "FOR", "OR", "AS", "NEW", "ALL", "SEE", "PER", "ARE", "BE",
    "IS", "IT", "AN", "I",  # "A" is NOT here: it is a valid fixture type, and
    # the prose-line filter below drops the article "a" when it appears in a
    # sentence rather than isolated near a symbol.
}

# A cluster needs at least this many placements to count as a real device
# type rather than a stray label. Below it, the token is left for review
# rather than asserted as a quantity.
MIN_PLACEMENTS = 3

# A device tag stands alone (or nearly) near its symbol. A token sitting in
# a line of running text is prose -- a note, a title, a sentence -- not a
# device. Reject any candidate whose text line carries more than this many
# words.
MAX_LINE_WORDS = 3


def _in_region(x: float, y: float, region: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = region
    return x0 <= x <= x1 and y0 <= y <= y1


# A condensed/narrow font is the typographic choice a title-block stamp
# uses to fit ring text around a seal -- an ordinary device tag is set in
# the sheet's regular annotation font. See `_stamp_points` for why this
# replaced a rotation check.
_CONDENSED_FONT = "narrow"

# A professional engineer's seal draws its ring text in two concentric
# passes -- one in the condensed font, one in the sheet's regular font --
# so a lone condensed-font check leaves the inner ring's glyphs still
# tag-shaped and still counted. Every stamp glyph measured on the real set
# sat within 71pt of its nearest condensed-font neighbour; every real
# device tag measured sat over 500pt away. 100pt sits in the middle of
# that gap with wide margin either side (identical results from 75pt to
# 150pt -- see `_stamp_points`), so it is a threshold, not a tuning.
_STAMP_RADIUS = 100.0


def _stamp_points(page) -> set[tuple[int, int]]:
    """Centres of every text span that belongs to a title-block seal or
    stamp, not to a device tag. (Function name kept as the brief's
    `_rotated_points` would suggest a rotation check; see the deviation
    note below for why this checks font and proximity instead.)

    Original design (brief task-3): a drafter sets a device tag
    horizontally, so text on a curve -- the perimeter of a professional
    engineer's seal, a north arrow -- should be identifiable from
    `line["dir"]` in `get_text("dict")`. Two problems surfaced verifying
    that against the real set (spec 11.2's "87 placements across 14
    sheets"):

    1. `line["dir"]` is reported in the page's *unrotated* content-stream
       space, but this set is 90 degrees rotated (`page.rotation == 90`)
       and `get_text("words")` bboxes -- what a `dir`-based filter would
       get matched against -- are already in display (rotated) space.
       Testing `abs(dy) <= 0.01` against the raw `dir` flagged 330 of 482
       words on E1.1 as "rotated," including its ordinary horizontal
       tags, and emptied the sheet outright. Transforming `dir` through
       `page.rotation_matrix` fixes that specific symptom.

    2. That fix is not sufficient by itself. `line["dir"]` for a line
       holding a single character -- which is what every tag-shaped
       candidate is, real device tag or seal glyph alike, per the
       brief's own description of the seal ("each letter... stands alone
       on its own text line") -- is unreliable on this document even
       after the rotation-matrix correction: the same upright,
       correctly-placed letter reports different `dir` values in
       different instances (e.g. "F" was seen at (0.707, -0.707),
       (0.0, -1.0), and (-0.707, -0.707) across its six real placements
       on sheet E4.1), and a verified real "F" device tag next to a
       demolition symbol at (696, 1287) on that sheet -- confirmed
       upright by rendering the page -- reports a raw `dir` of exactly
       45 degrees. Applied document-wide, the rotation-matrix-corrected
       filter removed 499 of 812 placements (61%), not the ~87 (11%) the
       brief's design spec measured, taking real devices with it. This
       is most likely MuPDF's line-grouping conflating nearby, unrelated
       single-character spans on a dense CAD sheet -- not evidence that
       these tags are genuinely rotated.

    Rotation was therefore replaced with font: the seal's outer ring is
    set in `ArialNarrow` at a consistent ~8.26pt, confined to an
    identical 43x104pt bounding box (x: 956-999, y: 47-151) repeated
    verbatim on every one of the 14 electrical sheets (32 `ArialNarrow`
    spans/sheet, 448 total -- a single reused stamp graphic, not
    scattered devices). Every sampled real device tag, including the "F"
    above, is set in plain `Arial`. `ArialNarrow` is the *only* condensed
    font anywhere in the document (`Arial`, `Arial,Bold`, `CenturyGothic`,
    `CenturyGothic,Bold`, `Calibri,Bold`, `Helvetica-Bold`, `Symbol`,
    `RomanS` are the rest), so this is not tuned to one coordinate
    window; it is the seal's actual typographic signature.

    Font alone still left 4 of the seal's inner-ring characters in plain
    `Arial` -- e.g. an "A" at (909, 53) -- passing every other filter, so
    a sheet with the seal still failed the zero-glyphs assertion. Those
    residual glyphs sit within `_STAMP_RADIUS` of the confirmed
    `ArialNarrow` ring (58-71pt away); every real device tag checked sits
    over 500pt from it. This is a text-layer proximity check against a
    signature the filter already found on the page, not a check against
    drawn vector geometry, so it does not revive the rejected "adjacent
    vector geometry" filter (spec 11.2), and it does not change how
    placements are found -- still the text layer, not shape clustering --
    so it does not cross into Tier-B geometry counting either.

    Measured impact of the combined font-and-proximity filter across the
    real set: 574 of 812 raw tag-shaped candidates removed, identically
    41 per sheet across all 14 sheets regardless of each sheet's actual
    floor-plan content -- strong evidence the filter is isolating one
    reused stamp graphic and nothing sheet-specific. This is a materially
    larger removal than the brief's ~87 estimate; see the task report for
    the full accounting.

    Positions are rounded to whole points so they can be matched against
    the word list, which reports the same coordinates.
    """
    condensed: list[tuple[float, float]] = []
    spans: list[tuple[float, float]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                x0, y0, x1, y1 = span["bbox"]
                centre = ((x0 + x1) / 2, (y0 + y1) / 2)
                spans.append(centre)
                if _CONDENSED_FONT in span["font"].lower():
                    condensed.append(centre)

    out: set[tuple[int, int]] = set()
    for cx, cy in spans:
        if any(math.hypot(cx - nx, cy - ny) <= _STAMP_RADIUS for nx, ny in condensed):
            out.add((round(cx), round(cy)))
    return out


def count_sheet(path: str, sheet: DetectedSheet) -> list[DeviceCluster]:
    if sheet.unreadable_reason:
        return []
    doc = pymupdf.open(path)
    page = doc[sheet.page_index]
    words = page.get_text("words")  # (x0,y0,x1,y1, word, block_no, line_no, word_no)
    stamp = _stamp_points(page)

    # How many words share each text line, so a candidate sitting in a
    # sentence (a note, a title) can be told from one standing alone by a
    # symbol.
    line_len: Counter = Counter((w[5], w[6]) for w in words)

    by_tag: dict[str, list[Placement]] = defaultdict(list)
    for x0, y0, x1, y1, word, block_no, line_no, *_ in words:
        t = word.strip()
        if not TAG.match(t) or t in NOISE:
            continue
        if line_len[(block_no, line_no)] > MAX_LINE_WORDS:
            continue  # prose, not a device tag
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if (round(cx), round(cy)) in stamp:
            continue  # title-block seal/stamp text is never a device tag
        if not _in_region(cx, cy, sheet.region):
            continue
        by_tag[t].append(Placement(int(cx), int(cy)))
    clusters = [
        DeviceCluster(tag=tag, sheet_page_index=sheet.page_index, placements=places)
        for tag, places in by_tag.items()
        if len(places) >= MIN_PLACEMENTS
    ]
    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters


def count(path: str, sheets: list[DetectedSheet]) -> list[DeviceCluster]:
    out: list[DeviceCluster] = []
    for sheet in sheets:
        out.extend(count_sheet(path, sheet))
    return out
