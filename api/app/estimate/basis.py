"""The basis vocabulary: where an assumed number came from.

docs/specs/rom-estimate.md. A ROM line is either `counted` -- read out
of the drawings -- or `assumed`, and an assumed line is worthless
without a basis a reader can check. The keys below are the closed set of
ways this product is willing to produce a number nobody counted, plus
the two that mean somebody stood behind it.

**`counted`/`assumed` is a different axis from the four review labels.**
Those describe an item's evidence and govern approval. This describes
where a ROM line's number came from, on a document that has no approval
step at all. Rendering one with the other's components is how the four
labels quietly become five -- the same trap `Note.status` carries its
own vocabulary to avoid.

The `spread` is **not** a confidence score (ROADMAP.md invariant 7: no
confidence number ever reaches the interface). It is a stated property
of the *method*: a supplier's quoted price is a price, and a number
derived from a feet-per-device rule is a number derived from a
feet-per-device rule. Both of those facts are true before anything is
run, they are the same for every project, and an estimator can read the
table and say why the range is what it is. A per-line score computed at
runtime would be none of those things.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.errors import DomainError


@dataclass(frozen=True)
class BasisSpec:
    """One way a number got into the estimate, and what that method's
    own looseness is worth in the budget range."""

    label: str
    spread: Decimal


# Mirrors the table in docs/specs/rom-estimate.md. Keep the two in step:
# the spec is what an estimator reads, this is what the range computes
# from, and a silent divergence makes the document's own explanation of
# its range wrong.
BASIS: dict[str, BasisSpec] = {
    # A price somebody stood behind. Zero spread: it is not an estimate.
    "supplier_quote": BasisSpec("Supplier quote", Decimal("0")),
    # The firm's own seeded table -- their rates, their labor units,
    # their feet-per-device rule. Their history, not an industry range.
    "firm_default": BasisSpec("Firm default", Decimal("0.10")),
    # A market estimate by ZIP. Catalog and shopping prices, which is
    # not contractor net pricing -- hence wider than the firm's own.
    "market_estimate": BasisSpec("Market estimate", Decimal("0.15")),
    # No price for this line at all; priced from what gear of its class
    # costs. The honest description is "not a supplier price".
    "class_average": BasisSpec("Class average", Decimal("0.20")),
    # Named from surrounding context rather than matched to a legend row
    # or a schedule line.
    "inferred": BasisSpec("Inferred from context", Decimal("0.25")),
    # A quantity derived from a rule rather than counted -- branch
    # footage from feet per device, where the drawing shows an arrow and
    # not a route.
    "rule_of_thumb": BasisSpec("Rule of thumb", Decimal("0.25")),
    # Measured off the drawing at its stated or assumed scale, rather
    # than read from a dimension.
    "scaled": BasisSpec("Scaled from the drawing", Decimal("0.20")),
    # Work this estimate does not include, where no document said either
    # way. Zero spread: it moves the number by removing scope, and the
    # amount it removed is stated instead.
    "standard_exclusion": BasisSpec("Standard exclusion", Decimal("0")),
    # A number the estimator typed over an assumption
    # (`app.estimate.override`). Zero spread, for the same reason
    # `supplier_quote` has none: somebody stood behind it, so it is not
    # an estimate. Its own key rather than reusing `supplier_quote`,
    # because "Supplier quote" is the wrong sentence to print beside a
    # ceiling height somebody measured -- and a closed vocabulary that
    # cannot say the one thing an estimator does on this screen is an
    # incomplete vocabulary, not a vocabulary worth bending.
    "estimator_entered": BasisSpec("Entered by the estimator", Decimal("0")),
}

# The four sections of the document, in the order they are rendered --
# which is also the order the assumptions cascade in: scope decides what
# is in, the takeoff counts it, labor and material price it.
SECTIONS: tuple[str, ...] = ("scope", "takeoff", "labor", "material")

# What an assumption is attached to. `project` is the default: a firm
# labor rate, or an exclusion of work nobody counted, belongs to no
# single row. `system` carries its subject in `subject_ref` rather than
# `subject_id`, because a system is a name and not a row -- it is what
# "fire alarm by others" has to be able to point at.
# `name_like` carries a keyword in `subject_ref` and matches item names
# case-insensitively. It exists because a system is too coarse for some
# real exclusions: a counted fire-alarm device may classify as "Life
# safety", but so do exit signs, which ARE Division 26 work this
# estimate includes -- excluding the whole system to catch the first
# would silently remove the second.
SUBJECT_KINDS: tuple[str, ...] = ("project", "sheet", "item", "system", "name_like")

# Who put it there. The engine's own rows are deleted and rewritten on
# every run; an estimator's are not (CLAUDE.md: "the engine never
# discards a person's judgment").
SOURCES: tuple[str, ...] = ("engine", "estimator")

# Where the number came from -- the ROM's one axis, and the whole of it.
# Deliberately separate from SOURCES, which says who wrote the row: the
# two disagree for an exclusion the documents stated, which the engine
# writes and which is nonetheless `counted`, because the spec defines
# counted as including "a scope statement extracted with a verbatim
# quote". Defaulting to `assumed` is the safe direction: a row that
# forgot to say reads as less certain than it is, never as more.
ORIGINS: tuple[str, ...] = ("assumed", "counted")

# The four questions an assumption answers, plus where it came from and
# where to look. `found`/`why`/`where` are the warning schema's own
# three; `basis` is this record's addition, and it is the one that makes
# an assumed number checkable rather than merely disclosed.
ASSUMPTION_FIELDS: tuple[str, ...] = ("section", "title", "found", "why", "basis", "where")


def validate_assumption(raw: dict) -> dict:
    """Six fields and two closed sets, or the write is refused.

    The same boundary discipline `ingest.validate_warning` applies for
    the same reason: an assumption that does not say what its basis was,
    or where to look, is a disclosure that cannot be checked -- which is
    worse than no disclosure, because it reads as one. A generator that
    cannot fill all six fields must emit nothing.
    """
    if not isinstance(raw, dict):
        raise DomainError(
            "invalid_assumption",
            "An assumption must be an object with section, title, found, why, basis, and where.",
            status=422,
        )

    missing = [f for f in ASSUMPTION_FIELDS if not str(raw.get(f) or "").strip()]
    if missing:
        raise DomainError(
            "invalid_assumption",
            f"An assumption is missing required field(s): {', '.join(missing)}. "
            "Every assumption states what was found, why it mattered, what it was based on, and where to look.",
            status=422,
        )

    section = str(raw["section"]).strip()
    if section not in SECTIONS:
        raise DomainError(
            "invalid_assumption",
            f"An assumption names an unrecognized section {section!r}. Sections are: {', '.join(SECTIONS)}.",
            status=422,
        )

    basis = str(raw["basis"]).strip()
    if basis not in BASIS:
        raise DomainError(
            "invalid_assumption",
            f"An assumption carries an unrecognized basis {basis!r}. Recognized bases are: {', '.join(sorted(BASIS))}.",
            status=422,
        )

    subject_kind = str(raw.get("subject_kind") or "project").strip()
    if subject_kind not in SUBJECT_KINDS:
        raise DomainError(
            "invalid_assumption",
            f"An assumption names an unrecognized subject {subject_kind!r}. "
            f"An assumption attaches to one of: {', '.join(SUBJECT_KINDS)}.",
            status=422,
        )

    source = str(raw.get("source") or "engine").strip()
    if source not in SOURCES:
        raise DomainError(
            "invalid_assumption",
            f"An assumption carries an unrecognized source {source!r}. Sources are: {', '.join(SOURCES)}.",
            status=422,
        )

    origin = str(raw.get("origin") or "assumed").strip()
    if origin not in ORIGINS:
        raise DomainError(
            "invalid_assumption",
            f"An assumption carries an unrecognized origin {origin!r}. "
            f"A ROM line's number is one of: {', '.join(ORIGINS)}.",
            status=422,
        )

    def opt(field: str) -> str | None:
        value = str(raw.get(field) or "").strip()
        return value or None

    if subject_kind in ("system", "name_like") and not str(raw.get("subject_ref") or "").strip():
        raise DomainError(
            "invalid_assumption",
            f"An assumption scoped to a {subject_kind} must name it in subject_ref. "
            "Without it the exclusion covers nothing and silently removes no money, "
            "which reads as applied and is not.",
            status=422,
        )

    return {
        "section": section,
        "subject_kind": subject_kind,
        "subject_id": raw.get("subject_id"),
        "subject_ref": opt("subject_ref"),
        "title": str(raw["title"]).strip(),
        "found": str(raw["found"]).strip(),
        "why": str(raw["why"]).strip(),
        "where": str(raw["where"]).strip(),
        "basis": basis,
        "value": opt("value"),
        "unit": opt("unit"),
        "excluded_value": raw.get("excluded_value"),
        "source": source,
        "origin": origin,
    }
