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
noticing a discrepancy later. Already-approved items get their own
reason distinct from Needs attention / Missing information: "a
colleague already approved these nine" needs no action, while "these
nine need attention or are missing evidence" is work the estimator must
go do. Collapsing the two into one code would send someone to look at
items where nothing is wrong.

The whole batch is recorded as a single action, not one per item, so
Task 10's undo can reverse the batch in one step. `commit()`'s
`before`/`after` are a flat dict, so recording N items' prior and new
state needs a nesting convention -- this follows the one
`review._apply_delete()` already established for its nested warnings
list: nest under a key (`ITEMS_SNAPSHOT_KEY`), and pre-encode the nested
structure with `encode_snapshot()` before handing it to `commit()`,
since `commit()`'s own encoding is shallow and will not reach inside a
nested dict.

Each item's snapshot is a dict carrying its own `id` (a list, not a
dict keyed by item id) -- matching `scale.set_scale()`'s shape.
Earlier, this module nested per-item snapshots under a dict keyed by
item-id string while `scale.py` used a list of dicts each carrying its
own `id`, both under the same `ITEMS_SNAPSHOT_KEY` name -- same key,
divergent payload, exactly the kind of drift that produces a subtly
wrong undo for whichever of the two a future reader assumes the other
also uses. This module now matches `scale.py`'s form, which additionally
preserves the order items were approved in, something a dict keyed by
id cannot.

Approval itself is delegated to `review._apply_approve()` rather than
reimplemented here, so there is exactly one definition of what
approving an item means. `review.py` factored `_apply_approve()` out of
`approve_item()` specifically so a caller like this one could reuse the
mutate-and-snapshot step under its own commit() -- see that module's
docstring. Reusing it means a future change to what gets snapshotted on
approval (a fourth field, say) cannot drift between the single-item and
bulk paths, and it means both paths decode with the same type map
(`snapshots.ITEM_SNAPSHOT_TYPES`).
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.actions import CrossOrgActionError, commit, encode_snapshot
from app.takeoff.models import Action, Item, Project, ReviewStatus
from app.takeoff.review import _apply_approve
from app.takeoff.snapshots import ITEMS_SNAPSHOT_KEY

# Skip reason codes. Kept as module-level strings (not an enum) because
# they travel to the client as plain JSON dict values, the same way
# ReviewStatus values do once encoded -- an enum here would just be
# decoded back to .value at every boundary that touches it.
#
# NEEDS_ATTENTION and MISSING_INFORMATION are two codes, not the single
# `not_ready_to_review` this module originally reported (a review finding
# on Task 13's endpoint work) -- collapsing them lost exactly the
# distinction CLAUDE.md's status vocabulary exists to preserve: *Needs
# attention* is a judgment call the estimator can resolve and re-approve;
# *Missing information* is blocked with no override at all. An estimator
# reading "these nine need attention or are missing evidence" can't tell
# which of the nine need a decision versus which are waiting on evidence
# that doesn't exist yet, and bulk approval (screen G) is exactly the
# density at which that ambiguity costs the most time.
NOT_IN_PROJECT = "not_in_project"
REJECTED = "rejected"
ALREADY_APPROVED = "already_approved"
NEEDS_ATTENTION = "needs_attention"
MISSING_INFORMATION = "missing_information"

# Every code this module can report, for `mutations.py` to assert its
# copy table is total against -- see that module's `_SKIP_COPY` and the
# assertion next to it.
SKIP_CODES = frozenset({NOT_IN_PROJECT, REJECTED, ALREADY_APPROVED, NEEDS_ATTENTION, MISSING_INFORMATION})


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

    Authorization runs first, before any row is read or locked. Without
    this, a caller whose org does not own `project_id` could still learn
    something: pass any project id and any item ids, and the per-item
    skip reasons in the result (`not_in_project` vs `rejected` vs
    `needs_attention` vs `missing_information` vs `already_approved`)
    disclose whether each item exists, which project it belongs to, and
    its review state -- cross-tenant visibility into another firm's bid,
    which is exactly what this product's tenancy model exists to
    prevent. Resolving the project and checking its org here, before the
    locking query, also means correctness for the "nothing qualifies"
    path never depended on
    a caller happening to call `commit()` -- previously the only
    authorization check ran inside `commit()`, which is skipped entirely
    when `result.approved` ends up empty, and rows were locked and
    mutated before that check ran at all for the case where something
    *did* qualify.

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
    order either reviewer's client happened to list the items in. This
    is a repo-wide convention, not a fact private to this function --
    see the note next to `commit()` in `actions.py`, which every
    mutation path already imports, so a future caller that locks more
    than one row (Task 9's compound scale confirmation, for one) finds
    it there rather than re-discovering it the hard way.

    `item_ids` may contain duplicates; each id is processed once, in its
    first-seen position, so the same id can never appear in both
    `approved` and `skipped`, and a repeated id in the request can never
    inflate the approved count.
    """
    result = BulkApproveResult()

    project = db.get(Project, project_id)
    if project is None or project.org_id != actor.org_id:
        raise CrossOrgActionError(
            f"actor {actor.id} is not authorized to bulk-approve items for project {project_id}"
        )

    if not item_ids:
        return result

    deduped_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for item_id in item_ids:
        if item_id not in seen:
            seen.add(item_id)
            deduped_ids.append(item_id)

    locked_rows = db.scalars(
        select(Item)
        .where(Item.id.in_(deduped_ids))
        .order_by(Item.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    items_by_id = {row.id: row for row in locked_rows}

    items_before: list[dict] = []
    items_after: list[dict] = []

    for item_id in deduped_ids:
        item = items_by_id.get(item_id)
        if item is None or item.project_id != project_id:
            result.skipped[item_id] = NOT_IN_PROJECT
        elif item.rejected_at is not None:
            result.skipped[item_id] = REJECTED
        elif item.status is ReviewStatus.APPROVED:
            result.skipped[item_id] = ALREADY_APPROVED
        elif item.status is ReviewStatus.ATTENTION:
            result.skipped[item_id] = NEEDS_ATTENTION
        elif item.status is ReviewStatus.MISSING:
            result.skipped[item_id] = MISSING_INFORMATION
        elif item.status is ReviewStatus.READY:
            # expected_version=None: bulk approval is deliberately out of
            # scope for the per-item optimistic-concurrency contract
            # (task-13b-brief.md -- a version per id is a clumsy contract
            # for a batch, and already_approved already covers the
            # common collision honestly). _apply_approve() still bumps
            # Item.version for every row it touches regardless, so the
            # counter a later single-item mutation checks against is
            # never wrong just because a batch moved the row instead.
            before_fields, after_fields = _apply_approve(db, actor, item, None)
            items_before.append(encode_snapshot({"id": item.id, **before_fields}))
            items_after.append(encode_snapshot({"id": item.id, **after_fields}))
            result.approved.append(item_id)
        else:
            # ReviewStatus has exactly four members and every one of
            # them is handled above -- this is unreachable today. Kept
            # as an explicit branch rather than a trailing `else:
            # approve it anyway` (what the previous `elif item.status is
            # not ReviewStatus.READY` shape effectively was), so a fifth
            # status added later fails loudly here instead of silently
            # being bulk-approved as if it were Ready to review.
            raise AssertionError(f"bulk_approve: unhandled ReviewStatus {item.status!r}")

    if result.approved:
        count = len(result.approved)
        result.action = commit(
            db, actor=actor, project_id=project_id, kind="bulk_approve",
            label=f"Approved {count} item{'s' if count != 1 else ''}",
            before={ITEMS_SNAPSHOT_KEY: items_before},
            after={ITEMS_SNAPSHOT_KEY: items_after},
        )
    return result
