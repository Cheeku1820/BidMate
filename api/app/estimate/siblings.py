"""What this project's own sheets counted -- the base every guess is
relative to.

docs/specs/estimate-without-asking.md. The spec's hardest rule about
guessing, and the reason this module exists at all:

    Every guessed quantity is relative to what this project itself
    counted, never an absolute constant.

An invented constant is a placeholder wearing an estimate's clothes. One
number cannot serve both a single-line diagram and a 40,000 sf floor
plan, and it degrades dishonestly: a project where nothing counted would
still produce a number. The relative form degrades correctly -- nothing
counted means nothing guessed, which is what `sibling_stats` returning
None enforces for every caller at once.

Split in two on purpose, the same way `schedule/plan.py` is: the rule is
pure and database-free so it can be tested on plain data, and the
reading of the counts is a thin query over `countable_items()` so
ROADMAP invariant 2 (a superseded sheet contributes to nothing) is
enforced where every other total enforces it rather than here.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import Project, Sheet
from app.takeoff.totals import countable_items

# How many sheets have to have counted something before their median
# means anything.
#
# Two, which is the smallest number for which "the others" is a real
# phrase. One sibling is not a distribution, it is an anecdote -- and
# the failure it produces is specific: on a two-sheet set where one
# sheet counted 40 and the other counted nothing, a sample of one would
# top the empty sheet up to 40 on the strength of a single observation.
#
# **Expected to move once a real bid set has been through it** (see the
# plan's "Not in this plan"). One named number, deliberately, so that is
# a one-line change a person can read rather than a literal buried in a
# branch.
MIN_SAMPLE = 2

# Units that mean a length rather than a count. A measured run and a
# device count are not the same quantity and must not be summed: adding
# 240 ft of conduit to a device count makes a sheet look dense because
# somebody measured a long run on it. Mirrors
# `generate_takeoff.MEASURED_UNITS`, which exists for the same reason.
_MEASURED_UNITS = ("ft", "lf", "feet")


@dataclass(frozen=True)
class SiblingStats:
    """The typical device count across the sheets that counted
    something, and which sheets those were."""

    median: int
    sample: int
    sheet_numbers: tuple[str, ...]


def sibling_stats(counts: Sequence[tuple[str, int]]) -> SiblingStats | None:
    """The median device count over sheets that counted something.

    Returns None when fewer than `MIN_SAMPLE` sheets counted anything,
    which is the single guard every completion case that compares sheets
    relies on -- review focus 1 (nothing counted) and review focus 2 (a
    single-sheet project) are both this returning None.

    Zero counts are dropped before the median is taken. A sheet that
    counted nothing is precisely what the caller is guessing *for*;
    leaving it in the sample drags every guess toward zero, which is the
    direction that reads as "this job is smaller than it is" -- the
    failure this whole slice exists to stop.
    """
    sampled = sorted((number, count) for number, count in counts if count > 0)
    if len(sampled) < MIN_SAMPLE:
        return None

    values = sorted(count for _, count in sampled)
    # The lower middle on an even sample, not the mean of the two.
    # Deliberate: this number is a guess about to be handed to a GC, and
    # rounding down is the safer error.
    median = values[(len(values) - 1) // 2]
    return SiblingStats(
        median=median,
        sample=len(sampled),
        sheet_numbers=tuple(number for number, _ in sampled),
    )


def plan_sheet_counts(db: DbSession, project: Project) -> list[tuple[str, int]]:
    """`(sheet_number, counted_device_quantity)` for every plan sheet.

    Plan sheets only. A luminaire schedule is not a sibling of a floor
    plan, and comparing one to the other would report every plan sheet
    as implausibly thin.

    A plan sheet that counted nothing appears here at zero rather than
    being absent -- case 4 (a sheet that produced no items at all) needs
    to see it, and a sheet missing from this list entirely could not be
    guessed for.

    Reads items through `countable_items()`, so a superseded sheet's
    items are excluded by the same predicate every other total uses
    (ROADMAP invariant 2, enforced once rather than restated here).
    """
    # Superseded sheets are left out on both sides: their items are
    # excluded by `countable_items`, and the sheet itself is not a
    # sibling either -- an old revision's thinness is not this
    # revision's problem.
    rows = db.execute(
        select(Sheet.id, Sheet.number).where(
            Sheet.project_id == project.id,
            Sheet.kind == "plan",
            Sheet.superseded_at.is_(None),
        )
    ).all()
    sheets = {sheet_id: number for sheet_id, number in rows}

    totals = {sheet_id: 0 for sheet_id in sheets}
    for item in db.scalars(countable_items(project.id)):
        if item.sheet_id not in totals:
            continue
        if item.path or (item.unit or "").strip().lower() in _MEASURED_UNITS:
            continue
        # Counted lines only. A companion allowance written by the last
        # run is a guess, and letting it into the base means the next
        # run guesses from the previous run's guesses -- which compounds
        # silently every time the estimate regenerates, and the number
        # drifts away from anything on the drawings.
        if item.origin != "counted":
            continue
        totals[item.sheet_id] += int(item.quantity or 0)

    return sorted((sheets[sheet_id], count) for sheet_id, count in totals.items())


def sheets_with_items(db: DbSession, project: Project) -> set[str]:
    """Sheet numbers carrying at least one counted item of any kind.

    Separate from `plan_sheet_counts`, which counts *devices*, because
    the two answer different questions and a caller needs both. A riser
    or single-line sheet can carry real counted work -- measured
    footage, a feeder run -- and zero devices; it reads as a zero in the
    device counts and is emphatically not an empty sheet.

    Case 4's own definition is "produced no items at all": read failed,
    render failed, or counting returned nothing. Topping a correctly-read
    riser sheet up to its siblings' device median would invent devices on
    a sheet that has none, which is the fabrication this whole slice is
    built to avoid.
    """
    numbers = dict(db.execute(
        select(Sheet.id, Sheet.number).where(
            Sheet.project_id == project.id, Sheet.superseded_at.is_(None)
        )
    ).all())
    found: set[str] = set()
    for item in db.scalars(countable_items(project.id)):
        if item.origin != "counted":
            continue
        number = numbers.get(item.sheet_id)
        if number:
            found.add(number)
    return found
