"""Optimistic concurrency for the five single-item mutations (task-13b-
brief.md): approve, reject, unreject, edit, delete.

Two reviewers editing the same item is last-write-wins today (Task 13's
report recorded this as a known limitation, not a hidden one). The
decision: refuse the stale write. The client sends the `Item.version` it
last saw; if the row has moved since, the server refuses with a 409
naming a recovery action rather than silently clobbering whatever the
other reviewer wrote.

Split out rather than folded into `review.py` -- review.py was already at
this project's ~300-line guideline before this task, and task-13b-brief.md
says explicitly to split rather than push it further, the same call
`bulk.py`/`scale.py`/`undo_apply.py` made for the same reason.

Deliberately item-scoped only. `bulk_approve` and `set_scale` are out of
scope for the CLIENT-SUPPLIED check by product decision (see
task-13b-report.md): a version per id is a clumsy contract for a batch,
and a sheet-scoped action needs sheet versioning, not this. Neither calls
into this module for that reason. Both still increment `Item.version`
themselves wherever they mutate a row (bulk.py reuses `review._apply_approve`,
which does the increment; scale.py bumps directly) -- so the counter this
module checks against is never wrong just because the item moved through
one of the out-of-scope paths instead.

`Item.version` is deliberately never carried in an `Action`'s `before`/
`after` snapshot. Those snapshots exist so undo/redo can replay a
mutation's semantic fields; the concurrency counter is bookkeeping about
those fields, not one of them. Undo and redo bump the version forward
themselves (see `undo_apply.py`), on the theory that reversing a change
is itself a change -- a client holding a stale version must not be able
to write again just because the row's fields happened to move back to
values that version once described.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.takeoff.models import Action, Item

# The one message this module and undo_apply.py both use for "the row
# this action targets was deleted by someone else since" -- kept as a
# single literal in each rather than importing across modules whose only
# relationship is coincidence of wording, matching the existing
# convention next to undo_apply.py's own copy of this string.
ITEM_GONE_MESSAGE = "This item was deleted by another reviewer. Refresh the sheet to see its current items."


def lock_item(db: DbSession, item_id: uuid.UUID) -> Item:
    """Re-read `item_id` under `FOR UPDATE` with a fresh view of the row.

    Every rule that depends on current state -- the missing-information
    check, the rejected check, and (as of this task) the version check --
    has to run against what the database holds right now, not whatever
    the caller's session loaded before this function was ever called.
    Concurrent review is a first-class feature of this product: reviewer
    A can load an item, reviewer B can change it and commit, and without
    this re-read A's action would act on a stale in-memory value.

    A concurrently deleted row surfaces here as a `DomainError` naming
    what happened, not `NoResultFound` as a bare 500 -- the fix Task 7
    made for `approve_item` alone, generalized here so all five
    single-item mutations get it, not just approval.
    """
    locked = db.execute(
        select(Item).where(Item.id == item_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if locked is None:
        raise DomainError("item_no_longer_exists", ITEM_GONE_MESSAGE, status=409)
    return locked


def check_version(db: DbSession, item: Item, expected_version: int) -> None:
    """Refuse a stale write.

    `expected_version` is what the client last saw; `item.version`
    (already re-read under lock by `lock_item()`, by the time any caller
    reaches this function) is what the row actually holds right now.
    Must run after the locked re-read, never before -- checking an
    unlocked read reintroduces exactly the race the lock exists to
    close.
    """
    if item.version == expected_version:
        return
    raise DomainError("stale_item_version", _stale_version_message(db, item), status=409)


def _stale_version_message(db: DbSession, item: Item) -> str:
    """Name the reviewer whose change landed first, when the action log
    has one -- one extra query, run only on this refusal path, never the
    success path (task-13b-brief.md, "The refusal"). Falls back to copy
    that still works when the lookup finds nobody: no prior action on
    this item at all, or the actor's row is gone.
    """
    last_action = db.execute(
        select(Action).where(Action.item_id == item.id).order_by(Action.seq.desc()).limit(1)
    ).scalar_one_or_none()

    actor_name = None
    if last_action is not None:
        actor = db.get(User, last_action.actor_user_id)
        actor_name = actor.name if actor is not None else None

    if actor_name:
        return (
            f"{actor_name} changed this item after you loaded it. Refresh the sheet "
            "to see the current value, then try again."
        )
    return "This item changed after you loaded it. Refresh the sheet to see the current value, then try again."
