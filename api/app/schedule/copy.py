"""Estimator-facing copy for the schedule (phases-and-timeline.md). Kept
separate from plan.py's arithmetic so a wording change never touches the
derivation. Task 4 adds manpower and order-by copy here."""
from datetime import date

NO_CREW = "No crew on this stage — set a crew in Company settings or on the bar to size it"
DEFAULT_SPLIT_NOTE = "Default split — set yours in Company settings"
DEFAULT_CREW_NOTE = "Default crew — set yours in Company settings"
NOT_YET_QUOTED = "Not yet quoted"
NOTHING_TO_SCHEDULE = "Nothing to schedule yet. Labor hours come from the Labor workspace."
NO_DEMOLITION = "No demolition items yet"


def _mon_d(d: date) -> str:
    return f"{d:%b} {d.day}"


def order_date_passed(lead_weeks: int, stage_label: str, stage_start: date) -> str:
    return f"Order date has passed — {lead_weeks} weeks lead, {stage_label.lower()} starts {_mon_d(stage_start)}"


def over_max_crew(max_crew: int, stage_label: str, finish: date) -> str:
    return f"More than {max_crew} on {stage_label.lower()} to finish by {_mon_d(finish)} — the window is tighter than one crew can meet"


def stale_lead_time_warning(days: int, source_label: str) -> dict:
    who = source_label or "the supplier"
    return {
        "title": "Lead time may be out of date",
        "found": f"The lead time on this item was quoted {days} days ago by {who}.",
        "why": "Order dates on the timeline are counted from it, and gear lead times are moving.",
        "fix": "Ask the supplier for a current lead time, or upload their price sheet with the lead-time column filled.",
        "where": "Phases and schedule, long-lead items; the item's detail panel",
    }


def unscheduled_items(count: int) -> str:
    noun = "item isn't" if count == 1 else "items aren't"
    return f"{count} {noun} in the schedule yet — they need labor hours"


NO_PHASING_FOUND = "No phasing found in the sheet numbers. Add phases by hand, or assign sheets to one."


def proposal_note(phase_count: int, sheet_count: int) -> str:
    return (f"{phase_count} phases from {sheet_count} sheets. Nothing changes until you confirm."
            if phase_count != 1 else f"1 phase from {sheet_count} sheets. Nothing changes until you confirm.")
