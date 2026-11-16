"""What kind of building this is, read off what the read job stored.

docs/specs/estimate-without-asking.md, "The building type". One
completion case needs it and no other does: a system absent from the
whole job is sized as a share of the electrical work actually counted,
and that share is wildly different for a hospital and a warehouse. The
spec's answer is to **infer it, disclose it, ask about it, and never
block on it** -- a project with no building type runs every other
completion case and says so.

**Deliberately not a language call.** This product has one classifier
(CLAUDE.md: "two paths to a classification means two classifiers that
will drift"), and the honest behaviour under conflicting evidence here
is to return nothing. A model asked to break a tie will break it; a
keyword table that finds a classroom wing and a patient room on the
same set correctly declines, because a system allowance sized from a
fabricated building type is exactly the confidently-wrong number this
product exists to prevent.

**Reads only stored text**, so it opens no file and is safe in the API
process: `Sheet.number`, `Sheet.title`, `Sheet.schedule_text`, and
`ScopeStatement`'s text and quote. That text came out of an uploaded
PDF and is therefore untrusted input (ROADMAP invariant 11) -- which is
another argument for substring matching over a prompt: a drawing cannot
steer a `str.find`.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import Project, ScopeStatement, Sheet

# The building types this product is willing to name, and the words that
# name them. A closed set, in the shape of
# `generate_scope.StandardExclusion.vocabulary`: lowercase substrings,
# matched against lowercased stored text.
#
# Substring matching is deliberate for the same reason it is deliberate
# there -- "classroom wing power plan" and "classrooms 101-118" are the
# same fact, and requiring an exact phrase would mean declining to infer
# a building type the documents plainly state.
#
# Words were chosen to be *distinctive of the occupancy*, not merely
# present in it. "Lighting" appears on every set ever drawn; "patient
# headwall" appears on exactly one kind of job. A word that fires on two
# occupancies is worse than no word at all, because it manufactures the
# tie this module exists to report honestly.
TYPE_VOCABULARY: dict[str, tuple[str, ...]] = {
    "school": (
        "classroom", "class room", "gymnasium", "gym ", "cafeteria", "auditorium",
        "lecture hall", "library media", "elementary school", "middle school",
        "high school", "university", "campus", "locker room",
    ),
    "healthcare": (
        "patient room", "patient head", "headwall", "nurse call", "nurses station",
        "nurse station", "exam room", "operating room", "surgery", "imaging suite",
        "radiology", "isolated power", "medical gas", "hospital", "clinic",
        "emergency department", "icu",
    ),
    "warehouse": (
        "warehouse", "distribution center", "distribution centre", "loading dock",
        "high bay", "highbay", "racking", "fulfillment", "cold storage",
    ),
    "office": (
        "open office", "private office", "conference room", "cubicle", "workstation",
        "tenant improvement", "office building", "reception desk", "break room",
    ),
    "multifamily": (
        "apartment", "dwelling unit", "unit type", "multifamily", "multi-family",
        "residential tower", "condominium", "leasing office", "in-unit",
    ),
    "retail": (
        "retail", "sales floor", "storefront", "checkout", "point of sale",
        "merchandise", "shopping center", "shopping centre", "restaurant",
    ),
    "industrial": (
        "manufacturing", "production floor", "process equipment", "plant floor",
        "machine shop", "motor control center", "mcc ", "assembly line",
    ),
}

TYPES: tuple[str, ...] = tuple(TYPE_VOCABULARY)


def _hits(haystack: str) -> dict[str, int]:
    """How many distinct words of each type's vocabulary appear.

    Distinct words, not occurrences: a sheet titled "Classroom power
    plan" repeated across fourteen sheets is one kind of evidence
    fourteen times, and counting occurrences would let one word said
    often outvote three different words said once.
    """
    found: dict[str, int] = {}
    for kind, words in TYPE_VOCABULARY.items():
        matched = sum(1 for word in words if word in haystack)
        if matched:
            found[kind] = matched
    return found


def infer_building_type(db: DbSession, project: Project) -> tuple[str, str] | None:
    """`(building_type, evidence_sentence)`, or None.

    Returns None in four cases, all of them deliberate:

    - The estimator has already said what this is. A person's judgment
      outranks an inference, always -- the same rule `merge.py` applies
      to an approved item. (A *previous inference* is reconsidered: the
      engine is allowed to correct its own last guess.)
    - Nothing in the stored text matches any vocabulary.
    - Two or more types tie at the top. A tie is a real answer.
    - Nothing readable was stored at all.
    """
    if project.building_type_source == "estimator":
        return None

    # Superseded sheets are excluded for the reason ROADMAP invariant 2
    # gives: they contribute to nothing. An old revision naming a
    # classroom wing the current set no longer carries must not size
    # this job's fire alarm allowance.
    sheets = list(db.scalars(
        select(Sheet)
        .where(Sheet.project_id == project.id, Sheet.superseded_at.is_(None))
        .order_by(Sheet.number)
    ))
    statements = list(db.scalars(
        select(ScopeStatement).where(ScopeStatement.project_id == project.id)
    ))

    # Per source, so the evidence sentence can say where a match came
    # from. An inference whose evidence is "the drawings" is a
    # disclosure nobody can check, which the ROM treats as worse than
    # none at all (`basis.validate_assumption`).
    scored: dict[str, int] = {}
    witnesses: dict[str, list[str]] = {}

    def observe(label: str, text: str) -> None:
        if not text.strip():
            return
        for kind, count in _hits(text.lower()).items():
            scored[kind] = scored.get(kind, 0) + count
            if label not in witnesses.setdefault(kind, []):
                witnesses[kind].append(label)

    for sheet in sheets:
        observe(sheet.number or "an unnumbered sheet",
                " ".join([sheet.number or "", sheet.title or "", sheet.schedule_text or ""]))
    for statement in statements:
        observe("the scope documents",
                " ".join([statement.text or "", statement.edited_text or "", statement.quote or ""]))

    if not scored:
        return None

    ranked = sorted(scored.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None

    kind = ranked[0][0]
    return kind, _evidence(kind, witnesses.get(kind, []))


_WITNESS_MAX = 4


def _evidence(kind: str, witnesses: list[str]) -> str:
    """Where the call came from, in the register the ROM's other
    disclosures use: a sentence an estimator can act on, naming the
    sheets to look at."""
    if not witnesses:
        return f"Read as a {kind} job from the drawing set."
    if len(witnesses) > _WITNESS_MAX:
        shown = witnesses[:_WITNESS_MAX]
        listed = f"{', '.join(shown)} and {len(witnesses) - _WITNESS_MAX} more"
    elif len(witnesses) == 1:
        listed = witnesses[0]
    else:
        listed = f"{', '.join(witnesses[:-1])} and {witnesses[-1]}"
    return f"Read as a {kind} job from wording on {listed}."
