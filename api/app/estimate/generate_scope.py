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

    `systems` and `item_names` are set only where the takeoff could have
    counted the work. Both are tuples, and the split matters:

    - `systems` excludes a whole system. Safe only where every item in
      it is out of scope.
    - `item_names` excludes by item name, within any system. This is
      what fire alarm needs: a counted fire-alarm device classifies as
      "Life safety", but so do exit signs, which ARE Division 26 work
      this estimate includes. Excluding the system to catch the first
      would silently remove the second -- a smaller, internally
      consistent, confidently wrong number.

    Both empty means project-scoped: stated, removing nothing.
    """

    title: str
    found: str
    why: str
    where: str
    keywords: tuple[str, ...]
    systems: tuple[str, ...] = ()
    item_names: tuple[str, ...] = ()

    @property
    def vocabulary(self) -> tuple[str, ...]:
        """Every phrase that counts as the documents addressing this
        boundary: the explicit keywords plus every equipment name the
        exclusion would remove.

        The two lists used to be read separately, and the gap between
        them moved money in both directions. "Smoke detectors are
        included" matched none of the fire alarm keywords, so the
        boundary read as unaddressed, the default exclusion was assumed,
        and the smoke detector the documents had just put IN the price
        was removed from it. The rule is now structural rather than
        remembered: anything this exclusion can delete is also something
        a document can mention to take the decision away from it.
        """
        # Lowercased, because `_text_of` lowercases the haystack and a
        # system name is capitalised the way the classifier writes it.
        return tuple(dict.fromkeys(
            k.lower() for k in self.keywords + self.item_names + self.systems
        ))


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
        keywords=("fire alarm", "fa system", "nac ", "facp"),
        # "Fire alarm" as a system is unambiguous where a row carries it.
        systems=("Fire alarm",),
        # And by name, for the rows the classifier files under "Life
        # safety" alongside exit signs. Every keyword here names fire
        # alarm equipment and nothing else -- deliberately not "horn" or
        # "bell" alone, which appear in other contexts.
        #
        # The list has to cover the equipment a real set carries, not a
        # sample of it: "fire alarm by others" that left `Heat detector`
        # and `Horn strobe` in the price is an exclusion the document
        # states and the number does not honour. Both punctuations of
        # horn/strobe are here because a classifier writes whichever the
        # legend used.
        item_names=("fire alarm", "pull station", "notification appliance",
                    "smoke detector", "duct detector", "heat detector",
                    "beam detector", "horn/strobe", "horn strobe",
                    "notification strobe", "annunciator"),
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


def _direction(statement: ScopeStatement) -> str:
    """Whether a statement puts the work in or out.

    `ScopeStatement.kind` is the engine's own four-value vocabulary:
    `included`, `excluded`, `by_others`, `alternate`. The first means
    the work is in the price, the next two mean it is not, and
    `alternate` means it is priced separately -- which for a ROM's
    purposes is "not in this number".

    Read off `kind` and nothing else, on purpose. The keyword match
    above searches the estimator's edit as well as the extracted text,
    because an edit is what the statement now says -- but direction is
    not inferred from those words. Inferring it would be a second
    classifier beside `app.engine.scope`, and two paths to one
    classification drift (CLAUDE.md: "Conversation routes; it does not
    answer"). `kind` is instead settable directly, through the same
    PATCH that confirms and dismisses, so an estimator who sees the
    direction read wrong corrects the fact rather than rewording the
    sentence and hoping.
    """
    return "in" if statement.kind == "included" else "out"


def _statements(db: DbSession, project: Project) -> list[ScopeStatement]:
    return list(db.scalars(
        select(ScopeStatement).where(
            ScopeStatement.project_id == project.id,
            ScopeStatement.status.in_(_ADDRESSING_STATUSES),
        )
    ))


def _text_of(statement: ScopeStatement) -> str:
    return " \n ".join([
        statement.text or "", statement.edited_text or "", statement.quote or "",
    ]).lower()


def scope_assumptions(db: DbSession, project: Project) -> list[dict]:
    """What this estimate decided about each scope boundary.

    Two outcomes per boundary, not one:

    - **No document addressed it.** The estimate takes the default
      position and discloses it as a `standard_exclusion` -- an
      assumption, because nobody said.
    - **A document excluded it.** That is not an assumption; it is what
      the documents say. But it still has to *remove the work from the
      number*, which is the whole of "scope filters the number", so it
      is emitted as a `standard_exclusion` carrying the statement's own
      words and marked as stated rather than assumed.

    The bug this shape fixes: matching a keyword used to suppress the
    default assumption regardless of direction, and a stated exclusion
    produced no exclusion record at all. A scope letter saying "fire
    alarm by others" therefore silenced the disclosure AND left the fire
    alarm work in the price -- the exact inverse of what the sentence
    asked for.
    """
    statements = _statements(db, project)
    rows = []

    for exclusion in STANDARD_EXCLUSIONS:
        matched = [s for s in statements
                   if any(keyword in _text_of(s) for keyword in exclusion.vocabulary)]

        if not matched:
            # Nobody said. The estimate decides, and discloses that it did.
            for kind, subject_ref in _subjects(exclusion):
                rows.append(_exclusion_row(exclusion, kind, subject_ref, stated=None))
            continue

        # A document addressed it. Honour what it said -- and only
        # remove work when the statement actually puts it out of scope.
        # An "included" statement means the work is in the price, so
        # nothing is excluded and nothing is assumed.
        out = [s for s in matched if _direction(s) == "out"]
        if not out:
            continue
        for kind, subject_ref in _subjects(exclusion):
            rows.append(_exclusion_row(exclusion, kind, subject_ref, stated=out[0]))

    return rows


def _subjects(exclusion: StandardExclusion) -> list[tuple[str, str | None]]:
    """What this exclusion points at, one row per subject.

    An exclusion naming neither a system nor an item name resolves to
    nothing and is stated for the reader -- the boilerplate case.
    """
    subjects = [("system", s) for s in exclusion.systems]
    subjects += [("name_like", n) for n in exclusion.item_names]
    return subjects or [("project", None)]


def _exclusion_row(exclusion: StandardExclusion, subject_kind: str, subject_ref: str | None,
                   *, stated: ScopeStatement | None) -> dict:
    """One exclusion, either assumed or quoted from the documents.

    `basis` is `standard_exclusion` either way, because what the row
    *does* is identical -- it removes work from the number, and
    `exclusions.py` resolves both the same. What differs is `found` and
    `where`: a stated exclusion quotes the document, so the reader can
    see the estimate followed the scope letter rather than guessing at
    it.
    """
    if stated is None:
        return {
            "section": "scope",
            "subject_kind": subject_kind,
            "subject_ref": subject_ref,
            "basis": "standard_exclusion",
            "title": exclusion.title,
            "found": exclusion.found,
            "why": exclusion.why,
            "where": exclusion.where,
            "source": "engine",
            # Nobody said, so the estimate decided. That is the
            # definition of assumed.
            "origin": "assumed",
        }
    quoted = (stated.edited_text or stated.text or "").strip()
    return {
        "section": "scope",
        "subject_kind": subject_kind,
        "subject_ref": subject_ref,
        "basis": "standard_exclusion",
        "title": exclusion.title,
        "found": f"The documents state it: \u201c{quoted}\u201d",
        "why": exclusion.why,
        "where": "Scope, as read from the documents",
        "source": "engine",
        # Counted: the spec's own definition includes "a scope statement
        # extracted with a verbatim quote", and this row is one. Tagging
        # it assumed told the reader the estimate had guessed at a
        # boundary the scope letter spelled out, and inflated the
        # assumed tally by one row per subject the exclusion covers.
        # It stays in the qualifications block regardless -- it moved
        # money, and that is what the block is for.
        "origin": "counted",
    }
