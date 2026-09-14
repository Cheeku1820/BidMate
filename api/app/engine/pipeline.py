"""The takeoff pipeline: runs the agents in order and returns a priced
TakeoffResult. Each stage consumes the previous stage's typed records
only -- no agent reads another's prose.

    Documents -> Counting -> Classification -> Pricing

This is the seam the async job queue plugs into later (ROADMAP.md 2.5);
for now it runs synchronously so the whole thing can be exercised from a
CLI against a real drawing set.
"""

from __future__ import annotations

from . import classification, counting, documents, pricing
from .contracts import TakeoffResult
from .pricing import DEFAULT_LABOR_RATE


def run(path: str, labor_rate: float = DEFAULT_LABOR_RATE) -> TakeoffResult:
    sheets = documents.detect_sheets(path)
    clusters = counting.count(path, sheets)
    classified = classification.classify(clusters, sheets)
    priced = pricing.price(classified, labor_rate)
    return TakeoffResult(sheets=sheets, items=priced, labor_rate=labor_rate)
