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


def _exclusions(db: DbSession, project_id: uuid.UUID) -> list[Assumption]:
    """Scope assumptions whose basis is `standard_exclusion`.

    Both halves of that predicate matter. A `scope` assumption on some
    other basis describes the scope boundary the estimate was read
    against and must not shrink it; a `standard_exclusion` filed under
    some other section is a generator bug, and silently honouring it
    would let a takeoff-section mistake remove money.
    """
    return list(
        db.execute(
            select(Assumption).where(
                Assumption.project_id == project_id,
                Assumption.section == "scope",
                Assumption.basis == "standard_exclusion",
            )
        ).scalars()
    )


def _resolve(db: DbSession, project_id: uuid.UUID, rows: list[Assumption]) -> set[uuid.UUID]:
    """One query per exclusion kind, all of them off `countable_items()`.

    A `project`-scoped exclusion resolves to nothing on purpose. Most
    standard exclusions -- temporary power, trenching, concrete pads --
    name work the engine never counted as a Division 26 item, so there
    is nothing to remove and the assumption is a scope statement that
    moves no money. Treating `project` as "everything" would make a
    boilerplate exclusion zero out the whole estimate.
    """
    sheet_ids = {r.subject_id for r in rows if r.subject_kind == "sheet" and r.subject_id}
    item_ids = {r.subject_id for r in rows if r.subject_kind == "item" and r.subject_id}
    systems = {r.subject_ref for r in rows if r.subject_kind == "system" and r.subject_ref}

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
    return _resolve(db, project_id, _exclusions(db, project_id))


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
