"""What kind of sheet a page is: the one field that stops a panel
schedule being counted as a floor plan.

A closed set. Decided from the title-block title first, content markers
second, and when nothing decides, `plan` -- over-counting is visible in
review, omission is silent (spec 2.4). This is a property of a sheet on
its own axis; it is never one of the four review labels and is never
rendered with a status component.
"""

from __future__ import annotations

import re

KINDS = ("plan", "schedule", "legend", "diagram", "other")

_TITLE_RULES = (
    ("schedule", ("SCHEDULE",)),
    ("legend", ("LEGEND", "SYMBOLS", "ABBREVIATIONS")),
    ("diagram", ("ONE-LINE", "ONE LINE", "RISER", "DIAGRAM", "DETAILS", "CONTROLS")),
    ("plan", ("PLAN",)),
    ("other", ("COVER", "INDEX", "NOTES")),
)

_SCHEDULE_HEADERS = (
    "PANEL SCHEDULE", "LUMINAIRE SCHEDULE", "FIXTURE SCHEDULE",
    "EQUIPMENT SCHEDULE", "MECHANICAL SCHEDULE",
)
_ON_OFF = re.compile(r"\bON\s*/\s*OFF\b")

_LABELS = {
    "plan": "Electrical plan",
    "schedule": "Schedule",
    "legend": "Legend",
    "diagram": "Diagram",
    "other": "Sheet",
}


def classify(title: str, page_text: str, has_scale: bool) -> str:
    t = title.upper()
    for kind, needles in _TITLE_RULES:
        if any(n in t for n in needles):
            return kind
    if has_scale:
        return "plan"
    text = page_text.upper()
    headers = sum(1 for h in _SCHEDULE_HEADERS if h in text)
    if headers >= 2:
        return "schedule"
    if len(_ON_OFF.findall(text)) >= 4:
        return "diagram"
    return "plan"


def label(kind: str) -> str:
    return _LABELS.get(kind, _LABELS["plan"])
