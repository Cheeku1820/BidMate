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


def count_sheet(path: str, sheet: DetectedSheet) -> list[DeviceCluster]:
    if sheet.unreadable_reason:
        return []
    doc = pymupdf.open(path)
    page = doc[sheet.page_index]
    words = page.get_text("words")  # (x0,y0,x1,y1, word, block_no, line_no, word_no)

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
