"""Scope exclusions: the assumptions that take money out of the number.

docs/specs/rom-estimate.md, "Scope filters the number". Every other
assumption in this feature explains a number. These change it, and they
change it downward -- which makes them the one place a wrong assumption
produces a smaller, internally consistent, confidently wrong estimate
rather than a visibly broken one.

Two rules keep that honest, and both are enforced here rather than
trusted to the caller:

**The resolution runs through `countable_items()`.** An exclusion names
a system, a sheet, or an item; what it resolves to is always a subset of
what the ROM would otherwise have counted. A separate query with its own
filters would eventually disagree about a rejected item or a superseded
sheet, and the disagreement would show up as money -- ROADMAP invariant
1 and 2, applied to subtraction instead of addition.

**The dollars removed are returned, not just the ids.** A total that
quietly shrank is indistinguishable from a job that is smaller.
`excluded_value` is what lets the document say "and $12,400 of counted
work was excluded, here is which."
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import Assumption, Item
from app.takeoff.totals import countable_items


# What an exclusion points at, independent of whether it has been
# stored yet: (subject_kind, subject_id, subject_ref). The generator
# needs to resolve exclusions it has only just produced -- scope decides
# what is in before the other sections price it -- and writing rows to
# the database purely to be able to read them back would make the
# cascade depend on a transaction that has not been decided to commit.
Subject = tuple[str, uuid.UUID | None, str | None]


def _subject(row) -> Subject:
    """Accepts a stored `Assumption` or a validated assumption dict."""
    if isinstance(row, dict):
        return (row.get("subject_kind") or "project", row.get("subject_id"), row.get("subject_ref"))
    return (row.subject_kind, row.subject_id, row.subject_ref)


def is_exclusion(row) -> bool:
    """A `scope` assumption whose basis is `standard_exclusion`.

    Both halves of that predicate matter. A `scope` assumption on some
    other basis describes the scope boundary the estimate was read
    against and must not shrink it; a `standard_exclusion` filed under
    some other section is a generator bug, and silently honouring it
    would let a takeoff-section mistake remove money.
    """
    if isinstance(row, dict):
        return row.get("section") == "scope" and row.get("basis") == "standard_exclusion"
    return row.section == "scope" and row.basis == "standard_exclusion"


def _exclusions(db: DbSession, project_id: uuid.UUID) -> list[Assumption]:
    return list(
        db.execute(
            select(Assumption).where(
                Assumption.project_id == project_id,
                Assumption.section == "scope",
                Assumption.basis == "standard_exclusion",
            )
        ).scalars()
    )


def resolve_subjects(db: DbSession, project_id: uuid.UUID,
                     subjects: list[Subject]) -> set[uuid.UUID]:
    """One query per exclusion kind, all of them off `countable_items()`.

    A `project`-scoped exclusion resolves to nothing on purpose. Most
    standard exclusions -- temporary power, trenching, concrete pads --
    name work the engine never counted as a Division 26 item, so there
    is nothing to remove and the assumption is a scope statement that
    moves no money. Treating `project` as "everything" would make a
    boilerplate exclusion zero out the whole estimate.
    """
    sheet_ids = {sid for kind, sid, _ in subjects if kind == "sheet" and sid}
    item_ids = {sid for kind, sid, _ in subjects if kind == "item" and sid}
    systems = {ref for kind, _, ref in subjects if kind == "system" and ref}

    if not (sheet_ids or item_ids or systems):
        return set()

    clauses = []
    if sheet_ids:
        clauses.append(Item.sheet_id.in_(sheet_ids))
    if item_ids:
        clauses.append(Item.id.in_(item_ids))
    if systems:
        clauses.append(Item.system.in_(systems))

    resolved = db.execute(
        countable_items(project_id)
        .with_only_columns(Item.id)
        .where(or_(*clauses))
    ).scalars()
    # A set, so an item covered by two overlapping exclusions is one
    # removal worth one line's dollars, not two.
    return set(resolved)


def excluded_item_ids(db: DbSession, project_id: uuid.UUID) -> set[uuid.UUID]:
    """Items a scope exclusion removes from this project's ROM.

    Pass straight into `rom_totals(..., exclude=...)`. An orphan -- an
    assumption whose subject was rejected or whose sheet was superseded
    after it was written -- resolves to nothing, because the resolution
    goes through `countable_items()` and that item is already gone.
    """
    return resolve_subjects(db, project_id, [_subject(r) for r in _exclusions(db, project_id)])


def excluded_from_rows(db: DbSession, project_id: uuid.UUID, rows: list[dict]) -> set[uuid.UUID]:
    """The same resolution, over assumptions not yet written.

    What `app.estimate.write.generate` uses so the cascade -- scope
    decides what is in, then the other sections price what is left --
    can run in one pass without the generator depending on rows being
    committed first.
    """
    return resolve_subjects(
        db, project_id, [_subject(r) for r in rows if is_exclusion(r)]
    )


def excluded_value_by_assumption(db: DbSession, project_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    """Dollars each individual exclusion removed, keyed by assumption id.

    Resolved one exclusion at a time rather than by dividing the total,
    so the figure printed beside "fire alarm by others" is the fire
    alarm work and not a share of something. Two exclusions covering the
    same item will each report that item's dollars -- the overlap is
    real, both statements removed it, and the project total
    (`excluded_value`) is what dedupes. A reader adding the per-line
    figures and getting more than the total is reading two overlapping
    exclusions correctly; a reader seeing half the fire alarm value
    beside the fire alarm line would be reading a fiction.
    """
    rows = _exclusions(db, project_id)
    if not rows:
        return {}

    costs = {
        item_id: cost
        for item_id, cost in db.execute(
            countable_items(project_id).with_only_columns(Item.id, Item.total_cost)
        ).all()
    }

    out: dict[uuid.UUID, Decimal] = {}
    for row in rows:
        ids = resolve_subjects(db, project_id, [_subject(row)])
        out[row.id] = sum((costs.get(i, Decimal("0")) for i in ids), Decimal("0"))
    return out


def excluded_value(db: DbSession, project_id: uuid.UUID) -> Decimal:
    """Dollars of otherwise-countable work the exclusions removed.

    Stated on the document beside the exclusions that caused it. Zero is
    a real and common answer: it means the exclusions named work nothing
    had counted, which is the normal case for boilerplate.
    """
    ids = excluded_item_ids(db, project_id)
    if not ids:
        return Decimal("0")
    rows = db.execute(
        countable_items(project_id)
        .with_only_columns(Item.total_cost)
        .where(Item.id.in_(ids))
    ).scalars()
    return sum(rows, Decimal("0"))
