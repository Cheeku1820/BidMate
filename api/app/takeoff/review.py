"""Review mutations: approve, reject, unreject, edit, delete.

Every public function here is the *only* way its corresponding change
happens to an item -- each one records exactly one attributed action via
`actions.commit()`, so there is no path that changes an item without
leaving an audit trail. Routers call these; they never touch `Item`
columns directly and never decide the rules themselves.

The rule that matters: a *Missing information* item cannot be approved.
Not "should not" -- the server refuses, with no override and no
acknowledgment path. A *Needs attention* item can be approved; that one is
a judgment call the estimator is allowed to make. Getting this pair
backwards inverts the product's safety model.

Each public function is a thin `commit()` wrapper around a private
`_apply_*` step that mutates and returns a `(before, after)` pair without
recording anything -- so Task 9's compound scale confirmation (one action
covering a sheet plus every item it re-derives) can call the `_apply_*`
steps directly under one `commit()`, instead of duplicating this
mutate-then-snapshot pattern outside the module.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.takeoff.actions import commit, encode_snapshot
from app.takeoff.models import Action, Item, ReviewStatus, Warning

# The only fields a generic edit may touch. Status changes go through
# approve/reject/unreject instead, so "status" is deliberately absent --
# a caller trying to smuggle a status change through edit_item() gets
# refused here rather than silently bypassing the approval rule.
EDITABLE_FIELDS = {"system", "category", "quantity", "notes", "symbol"}

# Fields that must be non-empty, non-null text -- an empty string is not
# a real value for any of these, and letting one through would (for
# category, concretely) satisfy the "no longer unclassified" check below
# and silently promote a Needs attention item to Ready to review.
REQUIRED_TEXT_FIELDS = {"system", "category", "symbol"}

# Field -> Python type for every value in an Item snapshot (delete_item's
# full-column snapshot plus its nested "warnings" list), so a future
# decoder -- Task 10's undo -- can call
# `actions.decode_snapshot(fields, ITEM_SNAPSHOT_TYPES)` instead of
# reverse-engineering ~20 columns' types from JSONB, which carries none.
# "warnings" decodes to `list` (left alone); decode each element with
# WARNING_SNAPSHOT_TYPES below -- they're already individually encoded.
ITEM_SNAPSHOT_TYPES: dict[str, type] = {
    "id": uuid.UUID,
    "project_id": uuid.UUID,
    "sheet_id": uuid.UUID,
    "symbol": str,
    "name": str,
    "description": str,
    "system": str,
    "category": str,
    "quantity": Decimal,
    "unit": str,
    "status": ReviewStatus,
    "approved_by_user_id": uuid.UUID,
    "approved_at": datetime,
    "rejected_by_user_id": uuid.UUID,
    "rejected_at": datetime,
    "x": int,
    "y": int,
    "path": list,
    "notes": str,
    "evidence": dict,
    "updated_at": datetime,
    "warnings": list,
}

# Counterpart for decoding one element of the nested "warnings" list.
# Keyed by Python attribute name ("where_"), not the "where" database
# column name -- see _column_snapshot()'s docstring for why that
# distinction matters here.
WARNING_SNAPSHOT_TYPES: dict[str, type] = {
    "id": uuid.UUID,
    "item_id": uuid.UUID,
    "sheet_id": uuid.UUID,
    "title": str,
    "found": str,
    "why": str,
    "fix": str,
    "where_": str,
}


def _column_snapshot(obj) -> dict:
    """Snapshot every mapped column of `obj`, keyed by Python attribute
    name, not database column name. They match for `Item`, but
    `Warning.where_` sits on the db column `"where"` (a reserved word) --
    keying by db column name would produce a `"where"` entry that
    neither `getattr`/`setattr` on the ORM object can use.
    """
    mapper = sa_inspect(type(obj))
    return {attr.key: getattr(obj, attr.key) for attr in mapper.column_attrs}


def _validate_edit(changes: dict) -> None:
    """Rules a field's JSON type alone can't express, so they live here
    rather than at the API boundary. An empty category is semantically
    "no category," not a valid one, and a Pydantic string field can't
    know that distinction -- it has to be a service-level rule.
    """
    for field in REQUIRED_TEXT_FIELDS & changes.keys():
        value = changes[field]
        if not isinstance(value, str) or not value.strip():
            raise DomainError(
                "field_cannot_be_empty",
                f"{field.capitalize()} cannot be blank. Enter a value before saving this edit.",
            )

    if "notes" in changes and changes["notes"] is None:
        raise DomainError(
            "field_cannot_be_empty",
            "Notes cannot be removed entirely. Send an empty value instead of no value, to clear it.",
        )

    if "quantity" in changes:
        try:
            parsed = Decimal(str(changes["quantity"]))
        except (InvalidOperation, ValueError, TypeError):
            raise DomainError(
                "invalid_quantity",
                "Quantity must be a number, such as 14 or 3.5. Correct it and save the edit again.",
            )
        # Decimal("NaN") / Decimal("Infinity") / Decimal("-Infinity") all
        # parse without raising, and Postgres numeric happily stores NaN
        # -- one edit like that poisons every SUM downstream, which is
        # exactly the drawer total and export figure a contractor bids
        # off. is_finite() rejects NaN and both infinities in one check.
        # A quantity is also a count or a measured length, and there is
        # no such thing as a negative one, so that is refused here too
        # rather than accepted as a value nobody would legitimately enter.
        if not parsed.is_finite() or parsed < 0:
            raise DomainError(
                "invalid_quantity",
                "Quantity must be a positive number, such as 14 or 3.5. Correct it and save the edit again.",
            )


def _apply_approve(db: DbSession, actor: User, item: Item) -> tuple[dict, dict]:
    """Mutate `item` into an approved state and return its before/after
    pair, without recording an action.

    Re-reads the row under `FOR UPDATE` with `populate_existing=True`
    before checking status, so the Missing information check runs
    against the database's current state rather than whatever the
    caller's session happened to load earlier. Concurrent review is a
    first-class feature of this product: reviewer A can load an item at
    Ready to review, reviewer B can flip it to Missing information and
    commit, and without this re-read A's approval would act on a stale
    in-memory value and let a Missing information item through.

    That same re-read can also come back empty: a concurrent reviewer
    may have deleted the row entirely while this lock request was
    waiting for it. `.scalar_one()` would raise `NoResultFound` in that
    case -- an unhandled 500 with no recovery copy -- so the empty
    result is checked explicitly and turned into a `DomainError` naming
    what happened, the same way every other refusal in this module does.
    """
    locked = db.execute(
        select(Item).where(Item.id == item.id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()

    if locked is None:
        raise DomainError(
            "item_no_longer_exists",
            "This item was deleted by another reviewer. Refresh the sheet to see its current items.",
            status=409,
        )

    if item.status is ReviewStatus.MISSING:
        raise DomainError(
            "missing_information_blocks_approval",
            "This item is missing information it needs, such as a scale or "
            "a legend entry. Resolve the warning on its sheet before approving it.",
            status=409,
        )
    if item.rejected_at is not None:
        raise DomainError(
            "rejected_item_cannot_be_approved",
            "This item was rejected, so it cannot be approved as-is. Restore it, then approve it.",
            status=409,
        )

    before = {
        "status": item.status,
        "approved_by_user_id": item.approved_by_user_id,
        "approved_at": item.approved_at,
    }
    item.status = ReviewStatus.APPROVED
    item.approved_by_user_id = actor.id
    item.approved_at = datetime.now(timezone.utc)
    after = {
        "status": item.status,
        "approved_by_user_id": item.approved_by_user_id,
        "approved_at": item.approved_at,
    }
    return before, after


def approve_item(db: DbSession, actor: User, item: Item) -> Action:
    before, after = _apply_approve(db, actor, item)
    return commit(
        db, actor=actor, project_id=item.project_id, kind="approve",
        label=f"Approved {item.name}", before=before, after=after, item_id=item.id,
    )


def _apply_reject(item: Item, actor: User) -> tuple[dict, dict]:
    """Record a rejection without touching review status.

    Rejection is tracked separately (`rejected_at` / `rejected_by_user_id`)
    from review status by design, so that `_apply_unreject()` can restore
    the item exactly as it was rather than having to guess what status it
    used to carry.
    """
    before = {"rejected_at": item.rejected_at, "rejected_by_user_id": item.rejected_by_user_id}
    item.rejected_at = datetime.now(timezone.utc)
    item.rejected_by_user_id = actor.id
    after = {"rejected_at": item.rejected_at, "rejected_by_user_id": item.rejected_by_user_id}
    return before, after


def reject_item(db: DbSession, actor: User, item: Item) -> Action:
    before, after = _apply_reject(item, actor)
    return commit(
        db, actor=actor, project_id=item.project_id, kind="reject",
        label=f"Rejected {item.name}", before=before, after=after, item_id=item.id,
    )


def _apply_unreject(item: Item) -> tuple[dict, dict]:
    """Clear a rejection. Review status is untouched because
    `_apply_reject()` never changed it."""
    before = {"rejected_at": item.rejected_at, "rejected_by_user_id": item.rejected_by_user_id}
    item.rejected_at = None
    item.rejected_by_user_id = None
    after = {"rejected_at": None, "rejected_by_user_id": None}
    return before, after


def unreject_item(db: DbSession, actor: User, item: Item) -> Action:
    before, after = _apply_unreject(item)
    return commit(
        db, actor=actor, project_id=item.project_id, kind="unreject",
        label=f"Restored {item.name}", before=before, after=after, item_id=item.id,
    )


def _apply_edit(item: Item, changes: dict) -> tuple[dict, dict]:
    """Apply a set of field edits. Only EDITABLE_FIELDS are accepted --
    status is not among them, since status changes go through approve/
    reject/unreject rather than a generic edit.

    An item stuck at Needs attention only because its category was never
    classified moves to Ready to review the moment a real category is
    supplied, since the thing that made it uncertain no longer exists.
    """
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise DomainError(
            "field_not_editable",
            f"These fields cannot be changed here: {', '.join(sorted(unknown))}. "
            f"Edit one of: {', '.join(sorted(EDITABLE_FIELDS))}.",
        )

    _validate_edit(changes)

    before = {key: getattr(item, key) for key in changes}
    for key, value in changes.items():
        setattr(item, key, Decimal(str(value)) if key == "quantity" else value)

    was_unclassified = item.status is ReviewStatus.ATTENTION and before.get("category") == "Unclassified"
    still_unclassified = item.category == "Unclassified"
    if was_unclassified and not still_unclassified:
        before["status"] = item.status
        item.status = ReviewStatus.READY

    after = {key: getattr(item, key) for key in before}
    return before, after


def edit_item(db: DbSession, actor: User, item: Item, changes: dict) -> Action:
    before, after = _apply_edit(item, changes)
    return commit(
        db, actor=actor, project_id=item.project_id, kind="edit",
        label=f"Edited {item.name}", before=before, after=after, item_id=item.id,
    )


def _apply_delete(db: DbSession, item: Item) -> tuple[dict, dict]:
    """Snapshot every column of `item`, plus its warning rows, then
    delete it. Warnings are snapshotted explicitly because
    `Warning.item_id` cascades on delete -- `db.delete(item)` removes
    them via `ON DELETE CASCADE`, and they're exactly the evidence that
    made the item Needs attention or Missing information. Without this,
    a future undo would restore the item's columns but not the warning
    that explains its status.
    """
    warnings = db.execute(select(Warning).where(Warning.item_id == item.id)).scalars().all()
    before = {
        **_column_snapshot(item),
        "warnings": [encode_snapshot(_column_snapshot(w)) for w in warnings],
    }
    db.delete(item)
    return before, {}


def delete_item(db: DbSession, actor: User, item: Item) -> Action:
    before, after = _apply_delete(db, item)
    # Action.item_id (models.py) is deliberately a bare UUID column, not
    # a foreign key to items.id -- that's what makes referencing item.id
    # here safe even though _apply_delete() above already called
    # db.delete(item). A real FK would risk an integrity error or a
    # cascade against the action's own reference once the item row is
    # actually removed at flush.
    return commit(
        db, actor=actor, project_id=item.project_id, kind="delete",
        label=f"Deleted {item.name}", before=before, after=after, item_id=item.id,
    )
