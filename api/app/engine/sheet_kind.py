"""What kind of sheet a page is: the one field that stops a panel
schedule being counted as a floor plan.

A closed set. Decided from the title-block title first, content markers
second, and when nothing decides, `plan` -- over-counting is visible in
review, omission is silent (spec 2.4). This is a property of a sheet on
its own axis; it is never one of the four review labels and is never
rendered with a status component.

`PLAN` is checked first in `_TITLE_RULES`, ahead of `SCHEDULE`, `LEGEND`
and the rest -- a title containing "plan" is a plan, whatever else it
contains. A sheet titled "Lighting plan and schedules" carries an
embedded schedule block, but the schedule is the residue the spec defers,
not the sheet's identity; counting has to run on it or the whole sheet's
devices go uncounted. The asymmetry is deliberate: a plan misclassified
as a schedule drops every device on it silently, while a schedule
misclassified as a plan just leaves an extra sheet for counting to find
nothing on. Silent omission is the failure mode this ordering exists to
prevent.
"""

from __future__ import annotations

import re

KINDS = ("plan", "schedule", "legend", "diagram", "other")

_TITLE_RULES = (
    ("plan", ("PLAN",)),
    ("schedule", ("SCHEDULE",)),
    ("legend", ("LEGEND", "SYMBOLS", "ABBREVIATIONS")),
    ("diagram", ("ONE-LINE", "ONE LINE", "RISER", "DIAGRAM", "DETAILS", "CONTROLS")),
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
