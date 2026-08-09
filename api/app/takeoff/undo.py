"""Undo and redo, derived entirely from the append-only action log.

Nothing here ever deletes or rewrites a row -- a Postgres trigger
(`actions.ACTION_LOG_GUARD_DDL`) refuses it outright. Undoing action `A`
appends a new action of kind `"undo"` whose `undoes_action_id` is `A.id`;
redoing appends a `"redo"` pointing at that undo. The log is the only
state: whether an action is "currently in effect" is computed by walking
it (`_live()`), never stored as a flag anywhere.

`undo_head()` is the most recent live action of a kind that actually
changes domain state (`REVERSIBLE`); `redo_head()` is the most recent
live `"undo"`. Both order by `Action.seq` -- a real Postgres identity
sequence -- never `created_at`, which is the *transaction* timestamp and
is identical for every row a single compound action (scale confirmation,
bulk approval) writes in one transaction. `"undo"`/`"redo"` rows are
deliberately absent from `REVERSIBLE`: undoing an undo is what `redo()`
already means, and a second path to the same state would let the two
drift out of step for no benefit.

Actually reversing state -- the per-kind snapshot handling for
`approve`/`reject`/`unreject`/`edit`, `delete`, `bulk_approve`, and
`scale` -- lives in `undo_apply.py`, split out for the same reason
`bulk.py` and `scale.py` were split out of `review.py`: a materially
different concern that would otherwise push this module well past the
project's line-count guideline. See that module's docstring for how
each kind's snapshot is shaped and restored.

Authorization runs first, before any row is read, locked, or mutated --
the actor's org must own `project_id`, checked here before `undo_apply`
touches anything, with `commit()`'s own check as defence in depth.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.actions import CrossOrgActionError, commit
from app.takeoff.models import Action, Project
from app.takeoff.undo_apply import apply as _apply

# Every action kind that actually changes domain state, and so can be the
# target of an undo. "undo" and "redo" are deliberately absent -- see the
# module docstring.
REVERSIBLE = {"approve", "reject", "unreject", "edit", "delete", "bulk_approve", "scale"}


def _actions(db: DbSession, project_id: uuid.UUID) -> list[Action]:
    """Every action recorded for a project, oldest first, ordered by
    `seq` -- never `created_at` (see module docstring).

    Evaluated in Python over the whole project's action list, which is
    honest at this scale and documented here as a future indexing
    concern, not a correctness one: a project with an extraordinarily
    long history would want this pushed into SQL (a recursive CTE, or a
    materialized "live" flag) instead of walked on every call.
    """
    return list(db.scalars(select(Action).where(Action.project_id == project_id).order_by(Action.seq)))


def _live(actions: list[Action]) -> dict[uuid.UUID, bool]:
    """An action is live when no live action targets it. `undoes_action_id`
    always points at a strictly earlier action, so this is a DAG in
    practice -- but the walk still guards against a cycle with an
    explicit in-progress set, rather than trusting that invariant blindly.
    """
    targeted_by: dict[uuid.UUID, list[uuid.UUID]] = {}
    for a in actions:
        if a.undoes_action_id is not None:
            targeted_by.setdefault(a.undoes_action_id, []).append(a.id)

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

    for a in actions:
        resolve(a.id)
    return memo


def undo_head(db: DbSession, project_id: uuid.UUID) -> Action | None:
    """The action `undo()` would reverse next, or `None` if there is
    nothing left to undo."""
    actions = _actions(db, project_id)
    live = _live(actions)
    for action in reversed(actions):
        if action.kind in REVERSIBLE and live[action.id]:
            return action
    return None


def redo_head(db: DbSession, project_id: uuid.UUID) -> Action | None:
    """The `"undo"` action `redo()` would reverse next, or `None` if
    there is nothing left to redo."""
    actions = _actions(db, project_id)
    live = _live(actions)
    for action in reversed(actions):
        if action.kind == "undo" and live[action.id]:
            return action
    return None


def undo(db: DbSession, actor: User, project_id: uuid.UUID) -> Action | None:
    """Reverse the most recent live reversible action for `project_id`,
    recording the reversal as a new `"undo"` action rather than touching
    the one it reverses. Returns `None`, with nothing changed, when there
    is nothing to undo.
    """
    project = db.get(Project, project_id)
    if project is None or project.org_id != actor.org_id:
        raise CrossOrgActionError(f"actor {actor.id} is not authorized to undo actions for project {project_id}")

    target = undo_head(db, project_id)
    if target is None:
        return None

    _apply(db, target, "before")
    return commit(
        db, actor=actor, project_id=project_id, kind="undo",
        label=f"Undid: {target.label}",
        before=target.after, after=target.before,
        item_id=target.item_id, sheet_id=target.sheet_id,
        undoes_action_id=target.id,
    )


def redo(db: DbSession, actor: User, project_id: uuid.UUID) -> Action | None:
    """Reapply the most recently undone action for `project_id`,
    recording the reapplication as a new `"redo"` action. Returns `None`,
    with nothing changed, when there is nothing to redo.
    """
    project = db.get(Project, project_id)
    if project is None or project.org_id != actor.org_id:
        raise CrossOrgActionError(f"actor {actor.id} is not authorized to redo actions for project {project_id}")

    undone = redo_head(db, project_id)
    if undone is None:
        return None

    original = db.get(Action, undone.undoes_action_id)
    _apply(db, original, "after")
    return commit(
        db, actor=actor, project_id=project_id, kind="redo",
        label=f"Redid: {original.label}",
        before=original.before, after=original.after,
        item_id=original.item_id, sheet_id=original.sheet_id,
        undoes_action_id=undone.id,
    )
