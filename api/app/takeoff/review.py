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

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.takeoff.actions import commit, encode_snapshot
from app.takeoff.concurrency import check_version, lock_item
from app.takeoff.edit_validation import EDITABLE_FIELDS, validate_edit
from app.takeoff.models import Action, Item, ReviewStatus, Warning
from app.takeoff.snapshots import _column_snapshot


def _apply_approve(db: DbSession, actor: User, item: Item, expected_version: int | None) -> tuple[dict, dict]:
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

    `expected_version` is the client-supplied optimistic-concurrency
    check, run against the just-locked row before the missing-
    information/rejected rules: a stale view is the more fundamental
    problem, since approving unseen data undermines what *Estimator
    approved* exists to guarantee. `None` skips the check --
    `bulk.bulk_approve()` reuses this function but is out of scope for
    the per-item contract (task-13b-report.md); it still gets the
    version bump below, so the counter never lies to a later caller.
    """
    locked = lock_item(db, item.id)

    if expected_version is not None:
        check_version(db, locked, expected_version)

    if locked.status is ReviewStatus.MISSING:
        raise DomainError(
            "missing_information_blocks_approval",
            "This item is missing information it needs, such as a scale or "
            "a legend entry. Resolve the warning on its sheet before approving it.",
            status=409,
        )
    if locked.rejected_at is not None:
        raise DomainError(
            "rejected_item_cannot_be_approved",
            "This item was rejected, so it cannot be approved as-is. Restore it, then approve it.",
            status=409,
        )

    before = {
        "status": locked.status,
        "approved_by_user_id": locked.approved_by_user_id,
        "approved_at": locked.approved_at,
    }
    locked.status = ReviewStatus.APPROVED
    locked.approved_by_user_id = actor.id
    locked.approved_at = datetime.now(timezone.utc)
    after = {
        "status": locked.status,
        "approved_by_user_id": locked.approved_by_user_id,
        "approved_at": locked.approved_at,
    }
    # Bumped here, not carried in before/after -- see concurrency.py's
    # module docstring for why the counter is deliberately absent from
    # every recorded snapshot.
    locked.version += 1
    return before, after


def approve_item(db: DbSession, actor: User, item: Item, expected_version: int) -> Action:
    before, after = _apply_approve(db, actor, item, expected_version)
    return commit(
        db, actor=actor, project_id=item.project_id, kind="approve",
        label=f"Approved {item.name}", before=before, after=after, item_id=item.id,
    )


def _apply_reject(db: DbSession, item: Item, actor: User, expected_version: int) -> tuple[dict, dict]:
    """Record a rejection without touching review status.

    Rejection is tracked separately (`rejected_at` / `rejected_by_user_id`)
    from review status by design, so that `_apply_unreject()` can restore
    the item exactly as it was rather than having to guess what status it
    used to carry.
    """
    locked = lock_item(db, item.id)
    check_version(db, locked, expected_version)

    before = {"rejected_at": locked.rejected_at, "rejected_by_user_id": locked.rejected_by_user_id}
    locked.rejected_at = datetime.now(timezone.utc)
    locked.rejected_by_user_id = actor.id
    after = {"rejected_at": locked.rejected_at, "rejected_by_user_id": locked.rejected_by_user_id}
    locked.version += 1
    return before, after


def reject_item(db: DbSession, actor: User, item: Item, expected_version: int) -> Action:
    before, after = _apply_reject(db, item, actor, expected_version)
    return commit(
        db, actor=actor, project_id=item.project_id, kind="reject",
        label=f"Rejected {item.name}", before=before, after=after, item_id=item.id,
    )


def _apply_unreject(db: DbSession, item: Item, expected_version: int) -> tuple[dict, dict]:
    """Clear a rejection. Review status is untouched because
    `_apply_reject()` never changed it."""
    locked = lock_item(db, item.id)
    check_version(db, locked, expected_version)

    before = {"rejected_at": locked.rejected_at, "rejected_by_user_id": locked.rejected_by_user_id}
    locked.rejected_at = None
    locked.rejected_by_user_id = None
    after = {"rejected_at": None, "rejected_by_user_id": None}
    locked.version += 1
    return before, after


def unreject_item(db: DbSession, actor: User, item: Item, expected_version: int) -> Action:
    before, after = _apply_unreject(db, item, expected_version)
    return commit(
        db, actor=actor, project_id=item.project_id, kind="unreject",
        label=f"Restored {item.name}", before=before, after=after, item_id=item.id,
    )


def _apply_edit(db: DbSession, item: Item, changes: dict, expected_version: int) -> tuple[dict, dict]:
    """Apply a set of field edits. Only EDITABLE_FIELDS are accepted --
    status is not among them, since status changes go through approve/
    reject/unreject rather than a generic edit.

    An item stuck at Needs attention only because its category was never
    classified moves to Ready to review the moment a real category is
    supplied, since the thing that made it uncertain no longer exists.

    Input-shape validation (unknown fields, `_validate_edit()`) runs
    before the row is locked -- it needs nothing from the database, and
    there is no reason to hold a `FOR UPDATE` lock while checking a
    request body's shape. The version check, in contrast, has to run
    against the locked row (task-13b-brief.md: "after the FOR UPDATE
    re-read, not before"), so it comes after `lock_item()`.
    """
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise DomainError(
            "field_not_editable",
            f"These fields cannot be changed here: {', '.join(sorted(unknown))}. "
            f"Edit one of: {', '.join(sorted(EDITABLE_FIELDS))}.",
        )

    validate_edit(changes)

    locked = lock_item(db, item.id)
    check_version(db, locked, expected_version)

    before = {key: getattr(locked, key) for key in changes}
    for key, value in changes.items():
        setattr(locked, key, Decimal(str(value)) if key == "quantity" else value)

    was_unclassified = locked.status is ReviewStatus.ATTENTION and before.get("category") == "Unclassified"
    still_unclassified = locked.category == "Unclassified"
    if was_unclassified and not still_unclassified:
        before["status"] = locked.status
        locked.status = ReviewStatus.READY

    after = {key: getattr(locked, key) for key in before}
    locked.version += 1
    return before, after


def edit_item(db: DbSession, actor: User, item: Item, changes: dict, expected_version: int) -> Action:
    before, after = _apply_edit(db, item, changes, expected_version)
    return commit(
        db, actor=actor, project_id=item.project_id, kind="edit",
        label=f"Edited {item.name}", before=before, after=after, item_id=item.id,
    )


def _apply_delete(db: DbSession, item: Item, expected_version: int) -> tuple[dict, dict]:
    """Snapshot every column of `item`, plus its warning rows, then
    delete it. Warnings are snapshotted explicitly because
    `Warning.item_id` cascades on delete -- `db.delete(item)` removes
    them via `ON DELETE CASCADE`, and they're exactly the evidence that
    made the item Needs attention or Missing information. Without this,
    a future undo would restore the item's columns but not the warning
    that explains its status.

    `_column_snapshot()` walks every mapped column, which now includes
    `version` -- popped immediately, so a future undo reconstructs the
    row without it and gets the ordinary column default (1) rather than
    resurrecting a pre-delete counter value (concurrency.py: nothing
    ever restores this field, only bumps it forward).

    The version bump right before `db.delete()` is symbolic -- no row
    survives to read it from -- but keeps this function's discipline
    identical to its four siblings, and is what a service-level test can
    assert directly against the in-memory object before flush.
    """
    locked = lock_item(db, item.id)
    check_version(db, locked, expected_version)

    warnings = db.execute(select(Warning).where(Warning.item_id == locked.id)).scalars().all()
    snapshot = _column_snapshot(locked)
    snapshot.pop("version", None)
    before = {
        **snapshot,
        "warnings": [encode_snapshot(_column_snapshot(w)) for w in warnings],
    }
    locked.version += 1
    db.delete(locked)
    return before, {}


def delete_item(db: DbSession, actor: User, item: Item, expected_version: int) -> Action:
    before, after = _apply_delete(db, item, expected_version)
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
