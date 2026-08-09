"""Bulk approval, restricted to Ready to review items.

This is a deliberately separate module from `review.py`, not another
function inside it. Bulk approval is a materially different act from
`review.approve_item()`: single-item approval allows a Needs attention
item through, because that is a judgment call an estimator makes while
looking at that item's evidence. Approving a hundred items in one click
is not the same judgment call made a hundred times -- it is a different,
coarser act, and this module holds it to a stricter rule. Only Ready to
review items ever move. Needs attention and Missing information items
are always skipped, no matter how convenient it would be to let them
through, and a rejected item is skipped even if its stored status still
reads Ready to review, because rejection is tracked independently of
status (see `review._apply_reject()`).

Every skip is reported with a reason code rather than dropped silently.
An estimator who clicks "approve 40" and gets back 31 approved needs to
know which nine did not move and why, in the same response -- not by
noticing a discrepancy later.

The whole batch is recorded as a single action, not one per item, so
Task 10's undo can reverse the batch in one step. `commit()`'s
`before`/`after` are a flat dict, so recording N items' prior and new
state needs a nesting convention -- this follows the one
`review._apply_delete()` already established for its nested warnings
list: nest under a key, and pre-encode the nested structure with
`encode_snapshot()` before handing it to `commit()`, since `commit()`'s
own encoding is shallow and will not reach inside a nested dict.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.actions import commit, encode_snapshot
from app.takeoff.models import Action, Item, ReviewStatus

# Skip reason codes. Kept as module-level strings (not an enum) because
# they travel to the client as plain JSON dict values, the same way
# ReviewStatus values do once encoded -- an enum here would just be
# decoded back to .value at every boundary that touches it.
NOT_IN_PROJECT = "not_in_project"
REJECTED = "rejected"
NOT_READY_TO_REVIEW = "not_ready_to_review"


@dataclass
class BulkApproveResult:
    approved: list[uuid.UUID] = field(default_factory=list)
    skipped: dict[uuid.UUID, str] = field(default_factory=dict)
    action: Action | None = None


def bulk_approve(
    db: DbSession, actor: User, project_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> BulkApproveResult:
    """Approve every Ready to review item named in `item_ids` that
    belongs to `project_id`; skip everything else with a reason.

    Concurrency: every candidate row is locked with `SELECT ... FOR
    UPDATE` before any status is read, the same re-read discipline
    `review._apply_approve()` uses for a single item -- without it, this
    function could act on whatever status this session happened to load
    earlier rather than what is true in the database right now, and the
    window during which that could go stale is longer here than for a
    single approval because a batch touches many rows.

    The lock is acquired in a fixed order -- ascending item id, not the
    order `item_ids` was supplied in -- because two reviewers
    bulk-approving overlapping sets is an ordinary occurrence, not an
    edge case, on a shared review workspace. If reviewer A's batch locks
    item 1 then item 2 while reviewer B's batch (listing the same two
    items in the opposite order) locks item 2 then item 1, the two
    transactions deadlock. Locking in one order that does not depend on
    caller input, id order, removes that possibility regardless of which
    order either reviewer's client happened to list the items in.
    """
    result = BulkApproveResult()
    if not item_ids:
        return result

    locked_rows = db.scalars(
        select(Item)
        .where(Item.id.in_(item_ids))
        .order_by(Item.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    items_by_id = {row.id: row for row in locked_rows}

    per_item_before: dict[str, dict] = {}
    per_item_after: dict[str, dict] = {}

    for item_id in item_ids:
        item = items_by_id.get(item_id)
        if item is None or item.project_id != project_id:
            result.skipped[item_id] = NOT_IN_PROJECT
        elif item.rejected_at is not None:
            result.skipped[item_id] = REJECTED
        elif item.status is not ReviewStatus.READY:
            result.skipped[item_id] = NOT_READY_TO_REVIEW
        else:
            before_fields = {
                "status": item.status,
                "approved_by_user_id": item.approved_by_user_id,
                "approved_at": item.approved_at,
            }
            item.status = ReviewStatus.APPROVED
            item.approved_by_user_id = actor.id
            item.approved_at = datetime.now(timezone.utc)
            after_fields = {
                "status": item.status,
                "approved_by_user_id": item.approved_by_user_id,
                "approved_at": item.approved_at,
            }
            per_item_before[str(item_id)] = encode_snapshot(before_fields)
            per_item_after[str(item_id)] = encode_snapshot(after_fields)
            result.approved.append(item_id)

    if result.approved:
        count = len(result.approved)
        result.action = commit(
            db, actor=actor, project_id=project_id, kind="bulk_approve",
            label=f"Approved {count} item{'s' if count != 1 else ''}",
            before={"items": per_item_before},
            after={"items": per_item_after},
        )
    return result
