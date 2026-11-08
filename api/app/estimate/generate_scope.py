"""Scope assumptions: the exclusions nobody wrote down.

docs/specs/rom-estimate.md, "Scope filters the number". A scope document
usually exists -- that is the normal case, and `app.engine.scope`
extracts what it says with verbatim-quote validation. What a scope
letter almost never does is address every boundary an electrical sub
prices around. A bid that stays silent on temporary power has still
priced it one way or the other, and a ROM that does not say which way is
a number whose scope the reader has to guess at.

So: for each boundary below, if no extracted statement addresses it, the
estimate takes the position an electrical sub takes by default and says
so. This is the one place in the feature where the product makes a
commercial decision rather than a technical one, which is exactly why
every one of them is printed.

**The asymmetry is the point.** Boilerplate that no Division 26 takeoff
counts -- trenching, concrete pads -- is project-scoped: it removes no
money and is stated for the reader. An exclusion that CAN remove counted
work names the system it covers, so the dollars it took out are
traceable to the lines they came from
(`app.estimate.exclusions.excluded_value`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import Project, ScopeStatement


@dataclass(frozen=True)
class StandardExclusion:
    """One boundary this estimate takes a default position on.

    `keywords` is what counts as the documents having addressed it --
    matched against a statement's text, an estimator's edit of it, and
    the verbatim quote it was extracted from. Substring matching on
    construction nouns, deliberately: a scope letter saying "temporary
    power and lighting by the GC" and one saying "temp power is
    excluded" are the same fact, and requiring an exact phrase would
    mean assuming an exclusion a document already stated.

    `system` is set only where the takeoff could have counted the work.
    None means project-scoped -- stated, removing nothing.
    """

    title: str
    found: str
    why: str
    where: str
    keywords: tuple[str, ...]
    system: str | None = None


# Ordered the way the document prints them: the one that can move money
# first, then the boilerplate. Wording follows `app/plan/copy.py`'s
# four-field register, re-pointed from the plan's "state it here as an
# answer" to "this estimate assumed it" -- a ROM has already made the
# call, and the reader's question is which call, not what to supply.
STANDARD_EXCLUSIONS: tuple[StandardExclusion, ...] = (
    StandardExclusion(
        title="Fire alarm by others",
        found="No document addressed fire alarm, and this estimate excluded it.",
        why="Fire alarm devices appear on electrical plans and are often a separate contract, so counting them "
            "or not counting them changes the number by more than any other scope boundary.",
        where="Scope documents were read for fire alarm language; none was found.",
        keywords=("fire alarm", "fa system", "nac ", "notification appliance"),
        system="Fire alarm",
    ),
    StandardExclusion(
        title="Temporary power excluded",
        found="No document addressed temporary power, and this estimate excluded it.",
        why="Temporary power and construction lighting are commonly the general contractor's, and pricing them "
            "unasked would carry cost the bid may not be meant to include.",
        where="Scope documents were read for temporary power language; none was found.",
        keywords=("temporary power", "temp power", "temporary light", "construction power"),
    ),
    StandardExclusion(
        title="Trenching and backfill by others",
        found="No document addressed trenching or backfill, and this estimate excluded it.",
        why="Underground routing is shown on the site plan without saying who digs for it, and excavation is "
            "not electrical work.",
        where="Scope documents and the site plan were read for a responsibility note; none was found.",
        keywords=("trench", "backfill", "excavat"),
    ),
    StandardExclusion(
        title="Concrete pads and housekeeping pads by others",
        found="No document addressed concrete pads, and this estimate excluded it.",
        why="Pads under gear are usually in the concrete scope, and carrying them here would duplicate another "
            "trade's price.",
        where="Scope documents were read for pad language; none was found.",
        keywords=("concrete pad", "housekeeping pad", "equipment pad"),
    ),
    StandardExclusion(
        title="Access panels and patching by others",
        found="No document addressed access panels or patching, and this estimate excluded it.",
        why="Cutting and patching finished surfaces to reach electrical work is usually the general "
            "contractor's, and it is not priced here.",
        where="Scope documents were read for cutting and patching language; none was found.",
        keywords=("access panel", "cutting and patching", "patch"),
    ),
    StandardExclusion(
        title="Utility company work and fees by others",
        found="No document addressed utility company work or fees, and this estimate excluded it.",
        why="Service work on the utility's side of the meter, and the fees for it, are billed to the owner "
            "rather than carried by the electrical sub.",
        where="Scope documents were read for utility language; none was found.",
        keywords=("utility company", "utility fee", "service charge", "poco", "power company"),
    ),
)

# A person dismissed the statement, so it is no longer what the
# documents say about this job -- the boundary is open again. `found` and
# `confirmed` both count as addressed: one is the documents' own words,
# the other is those words settled by a person.
_ADDRESSING_STATUSES = ("found", "confirmed")


def _addressed(db: DbSession, project: Project) -> str:
    """Every scope statement on this project, folded into one haystack.

    The estimator's edit and the verbatim quote are both searched
    alongside the extracted text: an edit is what the statement now
    means, and the quote is what the document literally said, and a
    boundary addressed in either is addressed.
    """
    rows = db.scalars(
        select(ScopeStatement).where(
            ScopeStatement.project_id == project.id,
            ScopeStatement.status.in_(_ADDRESSING_STATUSES),
        )
    )
    parts = []
    for row in rows:
        parts.extend([row.text or "", row.edited_text or "", row.quote or ""])
    return " \n ".join(parts).lower()


def scope_assumptions(db: DbSession, project: Project) -> list[dict]:
    """One exclusion per boundary the documents left open."""
    haystack = _addressed(db, project)
    rows = []
    for exclusion in STANDARD_EXCLUSIONS:
        if any(keyword in haystack for keyword in exclusion.keywords):
            continue
        rows.append({
            "section": "scope",
            "subject_kind": "system" if exclusion.system else "project",
            "subject_ref": exclusion.system,
            "basis": "standard_exclusion",
            "title": exclusion.title,
            "found": exclusion.found,
            "why": exclusion.why,
            "where": exclusion.where,
            "source": "engine",
        })
    return rows
