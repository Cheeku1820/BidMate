"""Review mutations: approve, reject, unreject, edit, delete.

Every function here is the *only* way its corresponding change happens to
an item -- each one records exactly one attributed action via
`actions.commit()`, so there is no path that changes an item without
leaving an audit trail. Routers call these; they never touch `Item`
columns directly and never decide the rules themselves.

The rule that matters: a *Missing information* item cannot be approved.
Not "should not" -- the server refuses, with no override and no
acknowledgment path. A *Needs attention* item can be approved; that one is
a judgment call the estimator is allowed to make. Getting this pair
backwards inverts the product's safety model.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.takeoff.actions import commit
from app.takeoff.models import Action, Item, ReviewStatus

# The only fields a generic edit may touch. Status changes go through
# approve/reject/unreject instead, so "status" is deliberately absent --
# a caller trying to smuggle a status change through edit_item() gets
# refused here rather than silently bypassing the approval rule.
EDITABLE_FIELDS = {"system", "category", "quantity", "notes", "symbol"}


def approve_item(db: DbSession, actor: User, item: Item) -> Action:
    """Approve an item. Refuses when required evidence is absent.

    Missing information blocks approval unconditionally -- there is no
    override and no acknowledgment path for it. A Needs attention item,
    by contrast, is allowed through: that one is a judgment call the
    estimator gets to make.
    """
    if item.status is ReviewStatus.MISSING:
        raise DomainError(
            "missing_information_blocks_approval",
            "This item is missing information it needs, such as a scale or "
            "a legend entry. Resolve the warning on its sheet before approving it.",
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

    return commit(
        db, actor=actor, project_id=item.project_id, kind="approve",
        label=f"Approved {item.name}", before=before, after=after, item_id=item.id,
    )


def reject_item(db: DbSession, actor: User, item: Item) -> Action:
    """Reject an item without touching its review status.

    Rejection is tracked separately (`rejected_at` / `rejected_by_user_id`)
    from review status by design, so that unreject_item() can restore the
    item exactly as it was rather than having to guess what status it used
    to carry.
    """
    before = {"rejected_at": item.rejected_at, "rejected_by_user_id": item.rejected_by_user_id}
    item.rejected_at = datetime.now(timezone.utc)
    item.rejected_by_user_id = actor.id
    after = {"rejected_at": item.rejected_at, "rejected_by_user_id": item.rejected_by_user_id}

    return commit(
        db, actor=actor, project_id=item.project_id, kind="reject",
        label=f"Rejected {item.name}", before=before, after=after, item_id=item.id,
    )


def unreject_item(db: DbSession, actor: User, item: Item) -> Action:
    """Clear a rejection. The review status is untouched -- it was never
    changed by reject_item(), so there is nothing here to restore."""
    before = {"rejected_at": item.rejected_at, "rejected_by_user_id": item.rejected_by_user_id}
    item.rejected_at = None
    item.rejected_by_user_id = None
    after = {"rejected_at": None, "rejected_by_user_id": None}

    return commit(
        db, actor=actor, project_id=item.project_id, kind="unreject",
        label=f"Restored {item.name}", before=before, after=after, item_id=item.id,
    )


def edit_item(db: DbSession, actor: User, item: Item, changes: dict) -> Action:
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
            f"These fields cannot be changed here: {', '.join(sorted(unknown))}.",
        )

    before = {key: getattr(item, key) for key in changes}
    for key, value in changes.items():
        setattr(item, key, Decimal(str(value)) if key == "quantity" else value)

    was_unclassified = item.status is ReviewStatus.ATTENTION and before.get("category") == "Unclassified"
    still_unclassified = item.category == "Unclassified"
    if was_unclassified and not still_unclassified:
        before["status"] = item.status
        item.status = ReviewStatus.READY

    after = {key: getattr(item, key) for key in before}
    return commit(
        db, actor=actor, project_id=item.project_id, kind="edit",
        label=f"Edited {item.name}", before=before, after=after, item_id=item.id,
    )


def delete_item(db: DbSession, actor: User, item: Item) -> Action:
    """Delete an item, recording a full column snapshot first.

    The snapshot is taken before the delete so undo has something to
    restore from -- once db.delete() runs there is no item left to read
    columns off of.
    """
    snapshot = {column.name: getattr(item, column.name) for column in Item.__table__.columns}
    action = commit(
        db, actor=actor, project_id=item.project_id, kind="delete",
        label=f"Deleted {item.name}", before=snapshot, after={}, item_id=item.id,
    )
    db.delete(item)
    return action
