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
# the sheet's regular annotation font.
_CONDENSED_FONT = "narrow"

# A professional engineer's seal draws its ring text in two concentric
# passes -- one in the condensed font, one in the sheet's regular font --
# so a lone condensed-font check leaves the inner ring's glyphs still
# tag-shaped and still counted. Measured on the real set: the farthest a
# removed seal glyph sat from its nearest condensed-font neighbour was
# 71.1pt; the nearest a real, correctly-kept device tag sat was 212.3pt
# ("ASJ" on E0.2). 100pt sits in that empty band with wide margin on both
# sides -- identical results from 75pt to 150pt -- so it is a separator
# between two well-apart clusters, not a fitted number.
_STAMP_RADIUS = 100.0

# A conservative safety valve, not a measured separator like
# `_STAMP_RADIUS`. Across the 14 real sheets the seal's condensed spans
# are 4.2-12.5% of a sheet's total spans on 13 of them, and 23.9% on the
# 14th (page_index 83, 32 condensed spans against only 134 total -- one
# outlier driven by that sheet being sparse overall, not by the seal being
# larger there). That is one data point near the 25% line, not a gap with
# margin on both sides, so this constant is deliberately biased toward the
# safe failure: when it trips, the seal filter switches off for that sheet
# only, ~41 phantom seal-glyph candidates appear as ordinary (wrong)
# device placements, and a reviewer sees and rejects them at review --
# exactly the trade this guard exists to make. The Critical this guards
# against (a whole sheet's real tags deleted silently, no cluster, no
# warning, no `unreadable_reason`) does not return at any share value, so
# getting this constant's exact number wrong costs visible false
# positives, never silent data loss.
_MAX_STAMP_SHARE = 0.25

# ...and a small part of the page, not scattered across it. Measured: the
# seal's condensed spans span 43x104pt, identical on all 14 sheets, on a
# 2448x1584pt page -- genuine headroom, unlike the share guard above. This
# takes max-min over every condensed-font span on the page, so one stray
# narrow-font note in a far corner (unrelated to any stamp) would inflate
# the extent and disable the seal filter for that whole sheet. Same safe
# failure direction as the share guard, and not observed on the real set.
_MAX_STAMP_EXTENT = 400.0


def _stamp_points(page) -> set[tuple[int, int]]:
    """Centres of every text span that belongs to a title-block seal or
    stamp, not to a device tag.

    Signal: font (a condensed face is the seal ring's typographic
    signature -- see `_CONDENSED_FONT`) plus proximity (a small inner ring
    is set in the ordinary font, caught by nearness to a confirmed
    condensed-font glyph -- see `_STAMP_RADIUS`). This replaced an
    earlier design based on `line["dir"]` from `get_text("dict")` --
    rejecting text whose line isn't horizontal -- which proved unreliable
    for isolated single-character spans on this document (a verified,
    upright real device tag reported a raw `dir` of 45 degrees) and
    removed real devices along with the seal. Full chronicle of that
    investigation, with measurements, is in task-3-report.md rather than
    here, since it documents a path not taken rather than the mechanism
    that shipped.

    Guarded against the opposite failure: if the condensed-font spans are
    most of a sheet's text, or spread widely across it, there is no stamp
    -- the sheet simply uses a condensed face for its ordinary annotation,
    and returning anything here would silently delete every device tag on
    it with no cluster, no warning, no `unreadable_reason`. An unfiltered
    seal is recoverable (a reviewer sees phantom devices and rejects
    them); a deleted sheet is not, and silence reads as completeness
    (BUILD-STAGES stage 1). See `_MAX_STAMP_SHARE` and
    `_MAX_STAMP_EXTENT`.

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

    total_spans = len(spans)

    # A stamp is a small, localised minority of a sheet's text. If the
    # condensed spans are most of the page, or spread across it, then the
    # sheet simply uses a narrow face for its ordinary annotation and
    # there is no stamp here -- return nothing rather than deleting the
    # drawing. Getting this wrong in the other direction is recoverable:
    # an unfiltered seal shows up as phantom devices a reviewer can see
    # and reject. Deleting real tags is silent, and silence reads as
    # completeness (BUILD-STAGES stage 1).
    if not condensed or len(condensed) > total_spans * _MAX_STAMP_SHARE:
        return set()
    xs = [p[0] for p in condensed]
    ys = [p[1] for p in condensed]
    if (max(xs) - min(xs)) > _MAX_STAMP_EXTENT or (max(ys) - min(ys)) > _MAX_STAMP_EXTENT:
        return set()

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
