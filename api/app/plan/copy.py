"""The words for each open question the plan can ask. Four fields each
-- what was found, why it matters, what to check, where -- the warning
shape CLAUDE.md requires. An estimator's words: no file internals, no
mention of how the reading was done."""

from __future__ import annotations


def scanned(filename: str, unreadable: int, total: int) -> dict:
    pages = "page" if total == 1 else "pages"
    return {
        "title": "Pages that could not be read",
        "found": f"{unreadable} of {total} {pages} in {filename} are scanned images with no readable text.",
        "why": "Nothing on those pages was read, so the takeoff will count nothing on them and no scope, schedule, or phasing was taken from them.",
        "fix": "Upload a version exported from the drafting software, or state the scope and phasing here as answers.",
        "where": f"{filename}, every page that could not be read.",
    }


def no_specs() -> dict:
    return {
        "title": "No specification was uploaded",
        "found": "The documents include drawings but no specification.",
        "why": "Fixture types, wiring methods, and what is by others are usually stated in Division 26 of the specification, not on the drawings.",
        "fix": "Upload the project manual or the Division 26, 27, and 28 sections, or state here that the drawings are the whole bid set.",
        "where": "Documents.",
    }


def no_scope() -> dict:
    return {
        "title": "No scope language was found",
        "found": "None of the uploaded documents state what the electrical work includes, excludes, or leaves to others.",
        "why": "Without a scope statement the takeoff counts everything electrical on every sheet, including work that may be by others.",
        "fix": "Upload the scope letter or bid instructions if there is one, or state the scope here as an answer.",
        "where": "Every uploaded document was read for scope language.",
    }


def no_scale(sheet_number: str, title: str) -> dict:
    return {
        "title": f"No scale on {sheet_number}",
        "found": f"{sheet_number} ({title}) has no scale in its title block.",
        "why": "Measured runs on this sheet cannot be given a length until a scale is set, and will show as missing information in review.",
        "fix": "Set the scale on the blueprint from the title block, or calibrate against a known dimension.",
        "where": f"{sheet_number}, title block.",
    }


def no_phasing() -> dict:
    return {
        "title": "No phasing was stated",
        "found": "The documents do not name any phase.",
        "why": "A phased job is priced as one estimate per phase, each with its own general conditions and demolition.",
        "fix": "If the bid instructions or the owner split the work into phases, add them here. Otherwise answer that the job is one phase.",
        "where": "Sheet titles, general notes, and the specification were read for phase names.",
    }


def no_schedule() -> dict:
    return {
        "title": "No schedule or legend was found",
        "found": "No sheet in the set is a luminaire, panel, or equipment schedule, and no legend sheet was found.",
        "why": "Without a schedule, fixture and panel types on the plans cannot be matched to a description, and every one will need attention in review.",
        "fix": "Check whether the schedules are on a sheet that was not uploaded, or in the specification, and upload it.",
        "where": "Every sheet in the drawing set.",
    }
