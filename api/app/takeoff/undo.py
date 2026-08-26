"""Undo and redo, derived entirely from the append-only action log.

Nothing here ever deletes or rewrites a row -- a Postgres trigger
(`actions.ACTION_LOG_GUARD_DDL`) refuses it outright. Undoing action `A`
appends a new action of kind `"undo"` whose `undoes_action_id` is `A.id`;
redoing appends a `"redo"` pointing at that undo. The log is the only
state: whether an action is "currently in effect" is computed by walking
it (`_live()`), never stored as a flag anywhere.

`undo_head()` is the most recent live action `undo()` would target
(`UNDO_ELIGIBLE`); `redo_head()` is the most recent live `"undo"`. Both
order by `Action.seq` -- a real Postgres identity sequence -- never
`created_at`, which is the *transaction* timestamp and is identical for
every row a single compound action (scale confirmation, bulk approval)
writes in one transaction.

`UNDO_ELIGIBLE` is `REVERSIBLE` (the real mutation kinds) plus `"redo"`,
deliberately -- and this is the fix for a bug a first version of this
module shipped with. A live `"redo"` row is a legitimate undo target:
undoing it means reversing the redo, landing back in the undone state.
Without `"redo"` in the filter, a second undo (after one undo and one
redo) skips past the live redo row -- since its kind doesn't match -- and
keeps walking back to the *original* root action, which `_live()`'s own
two-hop parity computes as "live again" at that point (nothing *live*
targets it, because the thing that does, the first undo, is itself now
dead, superseded by the redo). That second undo then tries to record
`undoes_action_id = root.id`, but the first undo already claims that
value under the partial unique index -- a unique-violation at flush, and
every undo after that fails identically, because the root never stops
being (wrongly) selected. Scanning newest-first and including `"redo"`
means the actually-current tip of the chain is always found before the
scan ever reaches the stale-but-technically-live root.

Whatever `undo_head()`/`redo_head()` actually return -- root, or an
intermediate `"redo"`/`"undo"` several alternations deep -- reversing it
correctly needs the *original* mutating action's kind and payload shape,
never the compensating row's own `"undo"`/`"redo"` kind. `_root_action()`
walks back to it. `undo()`/`redo()` then build every new compensating
row's `before`/`after` directly from that root's own `before`/`after`
(never from whatever intermediate they targeted), so this invariant
holds no matter how many times a chain alternates: every row in it
always carries exactly root.before or root.after, and `undo_apply.apply()`
never has to guess which shape it's holding.

Authorization is checked in all four public functions -- `undo_head()`
and `redo_head()` included, not just the two that mutate. They return
`Action.label`, business-sensitive text ("Approved 40 items", "Set scale
on E2.1 -- 14 measured items recalculated") that must never reach a
caller outside the project's org, which is why they take `actor` rather
than being pure unauthenticated peeks. `commit()`'s own check remains as
defence in depth on the write path.

Two reviewers can both resolve the same undo/redo target before either
writes -- nothing serializes `undo_head()`/`redo_head()` against a
concurrent call. The partial unique index on `undoes_action_id` is what
actually prevents the double-application; `_flush_or_translate_conflict()`
catches that one specific constraint and turns it into a 409 naming a
recovery action, matching this codebase's convention that a concurrent-
reviewer collision is never a bare 500.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.takeoff.actions import CrossOrgActionError, commit
from app.takeoff.models import Action, Project
from app.takeoff.undo_apply import apply as _apply

# Kinds that represent an original business mutation. The only kinds
# `_root_action()` ever stops walking at.
REVERSIBLE = {"approve", "reject", "unreject", "edit", "delete", "bulk_approve", "scale"}

# What undo_head() targets: a root mutation, or a live "redo" -- see the
# module docstring for why "redo" has to be included.
UNDO_ELIGIBLE = REVERSIBLE | {"redo"}

_COMPENSATING_KINDS = {"undo", "redo"}

# The unique index name actions.py's guard installs -- the one integrity
# error _flush_or_translate_conflict() treats as "someone else already
# did this," never any other constraint violation.
_UNDO_COLLISION_CONSTRAINT = "uq_actions_undoes_action_id"


def _authorize(db: DbSession, actor: User, project_id: uuid.UUID) -> None:
    project = db.get(Project, project_id)
    if project is None or project.org_id != actor.org_id:
        raise CrossOrgActionError(f"actor {actor.id} is not authorized to act on actions for project {project_id}")


def _action_summaries(db: DbSession, project_id: uuid.UUID):
    """`(id, kind, undoes_action_id)` for every action in the project,
    oldest first by `seq` -- deliberately not the full row.

    Computing liveness and scanning for a head needs only these three
    columns. Loading `before`/`after` JSONB for every action just to
    answer "is there anything to undo" means materializing a 400-item
    bulk approval's entire nested snapshot on every call, for the N-1
    rows that were never going to be the answer -- wasteful on its own,
    and doubly so for an endpoint polling to keep an undo button's
    enabled state live.
    """
    return db.execute(
        select(Action.id, Action.kind, Action.undoes_action_id)
        .where(Action.project_id == project_id)
        .order_by(Action.seq)
    ).all()


def _live(rows) -> dict[uuid.UUID, bool]:
    """An action is live when no live action targets it. `undoes_action_id`
    always points at a strictly earlier action, so this is a DAG in
    practice -- but the walk still guards against a cycle with an
    explicit in-progress set, rather than trusting that invariant blindly.
    """
    targeted_by: dict[uuid.UUID, list[uuid.UUID]] = {}
    for row in rows:
        if row.undoes_action_id is not None:
            targeted_by.setdefault(row.undoes_action_id, []).append(row.id)

    memo: dict[uuid.UUID, bool] = {}
    in_progress: set[uuid.UUID] = set()

    def resolve(action_id: uuid.UUID) -> bool:
        if action_id in memo:
            return memo[action_id]
        if action_id in in_progress:
            return False  # guard only -- should be unreachable, see docstring
        in_progress.add(action_id)
        result = not any(resolve(target_id) for target_id in targeted_by.get(action_id, []))
        in_progress.discard(action_id)
        memo[action_id] = result
        return result

    for row in rows:
        resolve(row.id)
    return memo


def undo_head(db: DbSession, actor: User, project_id: uuid.UUID) -> Action | None:
    """The action `undo()` would reverse next, or `None` if there is
    nothing left to undo."""
    _authorize(db, actor, project_id)
    rows = _action_summaries(db, project_id)
    live = _live(rows)
    for row in reversed(rows):
        if row.kind in UNDO_ELIGIBLE and live[row.id]:
            return db.get(Action, row.id)
    return None


def redo_head(db: DbSession, actor: User, project_id: uuid.UUID) -> Action | None:
    """The `"undo"` action `redo()` would reverse next, or `None` if
    there is nothing left to redo."""
    _authorize(db, actor, project_id)
    rows = _action_summaries(db, project_id)
    live = _live(rows)
    for row in reversed(rows):
        if row.kind == "undo" and live[row.id]:
            return db.get(Action, row.id)
    return None


def _root_action(db: DbSession, action: Action) -> Action:
    """Walk `undoes_action_id` back through any `"undo"`/`"redo"` rows to
    the original mutating action, however many alternations sit in
    between. A compensating row's own kind never determines how to
    reverse it, or what shape its snapshot carries -- the action it
    ultimately traces back to does.
    """
    while action.kind in _COMPENSATING_KINDS:
        next_action = db.get(Action, action.undoes_action_id)
        if next_action is None:
            raise ValueError(
                f"action {action.id} points at a nonexistent undoes_action_id -- the action log is corrupt"
            )
        action = next_action
    return action


def _flush_or_translate_conflict(db: DbSession, code: str, message: str) -> None:
    """Flush the newly staged compensating action, translating the one
    failure mode that matters here into a 409 rather than a bare 500: two
    reviewers both resolved the same target before either wrote. Any
    other integrity error re-raises unchanged -- this only ever claims
    the one constraint it names.
    """
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _UNDO_COLLISION_CONSTRAINT not in str(exc.orig):
            raise
        raise DomainError(code, message, status=409) from exc


def undo(db: DbSession, actor: User, project_id: uuid.UUID) -> Action | None:
    """Reverse the most recent live action `undo_head()` names, recording
    the reversal as a new `"undo"` action rather than touching the one it
    reverses. Returns `None`, with nothing changed, when there is nothing
    to undo.
    """
    target = undo_head(db, actor, project_id)
    if target is None:
        return None

    root = _root_action(db, target)
    if root.project_id != project_id:
        raise ValueError(f"resolved action {root.id} outside project {project_id} -- the action log is corrupt")

    _apply(db, root, "before")
    action = commit(
        db, actor=actor, project_id=project_id, kind="undo",
        label=f"Undid: {root.label}",
        before=root.after, after=root.before,
        item_id=root.item_id, sheet_id=root.sheet_id,
        undoes_action_id=target.id,
    )
    _flush_or_translate_conflict(
        db, "undo_already_applied",
        "Another reviewer already undid this action. Refresh the sheet to see its current state.",
    )
    return action


def redo(db: DbSession, actor: User, project_id: uuid.UUID) -> Action | None:
    """Reapply the most recent live `"undo"` `redo_head()` names,
    recording the reapplication as a new `"redo"` action. Returns `None`,
    with nothing changed, when there is nothing to redo.
    """
    target = redo_head(db, actor, project_id)
    if target is None:
        return None

    root = _root_action(db, target)
    if root.project_id != project_id:
        raise ValueError(f"resolved action {root.id} outside project {project_id} -- the action log is corrupt")

    _apply(db, root, "after")
    action = commit(
        db, actor=actor, project_id=project_id, kind="redo",
        label=f"Redid: {root.label}",
        before=root.before, after=root.after,
        item_id=root.item_id, sheet_id=root.sheet_id,
        undoes_action_id=target.id,
    )
    _flush_or_translate_conflict(
        db, "redo_already_applied",
        "Another reviewer already redid this action. Refresh the sheet to see its current state.",
    )
    return action
