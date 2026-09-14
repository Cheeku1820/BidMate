"""Per-kind state reversal for `undo.py`, split out for the same reason
`bulk.py` and `scale.py` were split out of `review.py`: a materially
different concern (reversing four distinct snapshot shapes, each with
its own locking and staleness handling) that would otherwise push
`undo.py` well past this project's line-count guideline.

`apply()` is the only export. It always receives the *root* mutating
action -- `undo.py`'s `_root_action()` walks back through any `"undo"`/
`"redo"` rows before calling here, because a compensating row's own kind
never determines how to reverse it. Dispatch is on `Action.kind`, since
each kind's `before`/`after` shape differs (see `review.py`, `bulk.py`,
`scale.py` for how each is written):

- `approve` / `reject` / `unreject` / `edit` -- a flat dict of changed
  `Item` columns, restored with one `decode_snapshot()` call against
  `snapshots.ITEM_SNAPSHOT_TYPES`.
- `delete` -- `before` is a full `Item` column snapshot plus a nested
  `"warnings"` list (both destroyed by the cascade); `after` is `{}`.
  Undo reconstructs the row and its warnings; redo deletes it again.
- `bulk_approve` / `scale` -- both nest a list of per-item dicts, each
  carrying its own `"id"`, under `snapshots.ITEMS_SNAPSHOT_KEY`. `scale`
  also carries the sheet's prior `"scale"` and, per released item, the
  scale-reason `"warnings"` `set_scale()` deleted. Undo has to restore
  the sheet's scale, every item's status, *and* those warnings together,
  or it quietly destroys the evidence it exists to protect; redo has to
  delete those same warnings a second time, or an item ends up both
  Ready to review and still carrying the warning that explained why it
  wasn't -- see `_apply_scale()`.

Identity-map discipline, one rule throughout: never trust `Session.get()`
to say whether a row exists (`_row_exists()` always issues a real query
instead -- a `Warning` cascade-deleted alongside its parent `Item` is
never told to the ORM, so `Session.get()` can report it as still present
long after the row is gone), and never delete through a possibly-stale
ORM object (`_apply_scale()`'s redo branch uses a Core-level scoped
`DELETE`, not `Session.delete()`, so a warning already gone via some
other path -- its item having been deleted in between -- can't raise
`StaleDataError` for matching zero rows).

Locking follows the convention next to `actions.commit()`: multiple
`Item` rows lock in ascending `Item.id` order; a `Sheet` locks before its
items. Authorization is `undo.py`'s job, checked before this module is
ever called.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.takeoff.actions import decode_snapshot
from app.takeoff.models import Action, Item, ProjectLaborLine, ProjectMaterialPrice, Sheet, Warning
from app.takeoff.snapshots import (
    ITEM_SNAPSHOT_TYPES,
    ITEMS_SNAPSHOT_KEY,
    LABOR_LINE_SNAPSHOT_TYPES,
    MATERIAL_PRICE_SNAPSHOT_TYPES,
    WARNING_SNAPSHOT_TYPES,
)

# The one message this module and review.py._apply_approve() both use
# for "the row this action targets was deleted by someone else since" --
# kept as a single literal here rather than two independently-worded
# copies of the same fact.
_ITEM_GONE_MESSAGE = "This item was deleted by another reviewer. Refresh the sheet to see its current items."


def apply(db: DbSession, action: Action, direction: str) -> None:
    """Mutate domain rows to match `action`'s `before` snapshot
    (`direction="before"`, an undo) or `after` snapshot
    (`direction="after"`, a redo). `action` must be a root mutating
    action -- see module docstring.
    """
    state = action.before if direction == "before" else action.after

    if action.kind == "scale":
        _apply_scale(db, action, direction)
    elif action.kind == "bulk_approve":
        _apply_bulk_approve(db, state)
    elif action.kind == "delete":
        _apply_delete(db, action, direction)
    elif action.kind == "labor_edit":
        _apply_sparse_pricing_row(db, ProjectLaborLine, action.item_id, LABOR_LINE_SNAPSHOT_TYPES, state)
    elif action.kind == "material_price_edit":
        _apply_sparse_pricing_row(db, ProjectMaterialPrice, action.item_id, MATERIAL_PRICE_SNAPSHOT_TYPES, state)
    else:  # approve, reject, unreject, edit
        _apply_item_state(db, action.item_id, state)


def _row_exists(db: DbSession, model: type, pk: uuid.UUID) -> bool:
    """Whether a row exists, checked with a direct query rather than
    `Session.get()`'s identity-map fast path.

    A `Warning` row removed purely by `ON DELETE CASCADE` when its parent
    `Item` was deleted is never told to the ORM (`review._apply_delete()`
    only calls `db.delete(item)`, never `db.delete(warning)`), so its
    identity-mapped Python object stays "persistent" even though the row
    is gone. `Session.get()` against that id would report the row as
    still present and skip restoring it -- silently dropping the very
    evidence undo exists to bring back. A `select()` always executes
    against the database, so it can't be fooled by identity-map state a
    cascade left stale.
    """
    return db.execute(select(model.id).where(model.id == pk)).scalar_one_or_none() is not None


def _expunge_stale(db: DbSession, model: type, pk: uuid.UUID) -> None:
    """Drop a stale identity-mapped object for `pk`, if one is present.
    Called after confirming (via `_row_exists()`) that the database has
    no such row, so a `Session.get()` hit here is exactly a stale
    instance left behind by a cascade or a Core-level statement, never a
    real one. Left in place, `db.add()`-ing a fresh object at the same
    identity produces an `SAWarning` from SQLAlchemy's own conflict
    detector -- correctly, since two live objects claiming one identity
    is how a later silent overwrite happens.
    """
    stale = db.get(model, pk)
    if stale is not None:
        db.expunge(stale)


def _restore_row_if_missing(db: DbSession, model: type, fields: dict) -> None:
    """Insert a row from a decoded snapshot if (and only if) no row with
    that id currently exists -- the one rule this module uses everywhere
    it might be restoring something that already came back through some
    other path (a prior undo, a redo that never got this far).
    """
    if not _row_exists(db, model, fields["id"]):
        _expunge_stale(db, model, fields["id"])
        db.add(model(**fields))


def _delete_row_if_present(db: DbSession, model: type, pk: uuid.UUID) -> None:
    """Delete a row by a scoped, Core-level `DELETE` if it currently
    exists -- never `Session.get()` + `Session.delete()`. A row already
    gone through some other path (its parent deleted out from under it,
    cascading it away without telling the ORM) would make
    `Session.delete()` issue a `DELETE` matching zero rows against a
    stale-but-"persistent" object, which raises `StaleDataError` at
    flush. A Core statement has no such expectation to violate.
    """
    if _row_exists(db, model, pk):
        db.execute(delete(model).where(model.id == pk))
        _expunge_stale(db, model, pk)


def _sparse_row_exists(db: DbSession, model: type, item_id: uuid.UUID) -> bool:
    """Like `_row_exists()`, but for `ProjectLaborLine`/`ProjectMaterialPrice`,
    whose primary key column is `item_id`, not `id` -- `_row_exists()`
    hardcodes `model.id`, which these two sparse pricing tables don't
    define. Kept as a separate function rather than generalizing
    `_row_exists()` itself, so this task doesn't touch the helper every
    other kind's reversal (`delete`, `scale`, `bulk_approve`) depends on.
    Same direct-query rationale as `_row_exists()`: never trust the
    identity map alone.
    """
    return db.execute(select(model.item_id).where(model.item_id == item_id)).scalar_one_or_none() is not None


def _delete_sparse_row_if_present(db: DbSession, model: type, item_id: uuid.UUID) -> None:
    """Like `_delete_row_if_present()`, scoped to the `item_id`-keyed
    sparse pricing tables -- see `_sparse_row_exists()` for why this
    isn't just a call into the generic helper.
    """
    if _sparse_row_exists(db, model, item_id):
        db.execute(delete(model).where(model.item_id == item_id))
        _expunge_stale(db, model, item_id)


def _apply_sparse_pricing_row(db: DbSession, model: type, item_id: uuid.UUID, snapshot_types: dict, state: dict) -> None:
    """Reverses a labor_edit/material_price_edit action onto ProjectLaborLine
    or ProjectMaterialPrice. Unlike Item (always exists once ingested),
    these rows are sparse -- created on first edit -- so `state` may be
    an empty dict (the row didn't exist before this action; undo means it
    shouldn't exist now) or a decoded snapshot of every column (the row
    existed; undo/redo means it should hold exactly these values).

    Guards on the parent `Item` existing before touching either table,
    the same way `_apply_item_state()` does for approve/reject/edit --
    this is a single-item reversal, not a batch one, so it follows that
    function's raise-a-409 pattern rather than `_apply_bulk_approve()`'s/
    `_apply_scale()`'s skip-and-continue. Checked unconditionally, before
    the `state`-empty branch too: even a delete-if-present reversal onto
    a now-gone item should report the same 409 rather than silently
    no-op'ing, since a caller relying on undo/redo actually having
    happened has no other way to learn it didn't.
    """
    item = db.execute(
        select(Item).where(Item.id == item_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if item is None:
        raise DomainError("item_no_longer_exists", _ITEM_GONE_MESSAGE, status=409)

    if not state:
        _delete_sparse_row_if_present(db, model, item_id)
        return
    decoded = decode_snapshot(state, snapshot_types)
    decoded.pop("item_id", None)
    if not _sparse_row_exists(db, model, item_id):
        _expunge_stale(db, model, item_id)
        db.add(model(item_id=item_id, **decoded))
    else:
        row = db.get(model, item_id)
        for key, value in decoded.items():
            setattr(row, key, value)


def _decode_item_row(row: dict, *, exclude: frozenset[str] = frozenset()) -> tuple[uuid.UUID, dict]:
    """Decode one `{"id": ..., ...}` entry from a `bulk_approve`/`scale`
    items list into `(item_id, decoded_column_values)`. `"id"` is only
    the lookup key, never a column to write back; `exclude` drops further
    non-column keys riding along -- `scale`'s `"warnings"` entries.
    """
    item_id = uuid.UUID(row["id"])
    fields = {key: value for key, value in row.items() if key not in {"id", *exclude}}
    return item_id, decode_snapshot(fields, ITEM_SNAPSHOT_TYPES)


def _apply_item_state(db: DbSession, item_id: uuid.UUID | None, state: dict) -> None:
    """Merge a flat, already-decoded-shape snapshot onto one `Item` row --
    the shared restore path for `approve`/`reject`/`unreject`/`edit`,
    which record only the columns they touched. Never a full-row
    restore, so an unrelated concurrent edit to another field survives.

    Bumps `item.version` after applying the snapshot -- undo and redo
    are themselves mutations (task-13b-brief.md), so a client holding a
    version from before the undo must not be able to write again just
    because the row's fields happened to move back to values that
    version once described. The snapshot itself never carries a
    `"version"` key (concurrency.py's module docstring), so this bump is
    always relative to whatever the row currently holds, never a value
    read back out of the action log.
    """
    if not state or item_id is None:
        return

    item = db.execute(
        select(Item).where(Item.id == item_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if item is None:
        raise DomainError("item_no_longer_exists", _ITEM_GONE_MESSAGE, status=409)

    for key, value in decode_snapshot(state, ITEM_SNAPSHOT_TYPES).items():
        setattr(item, key, value)
    item.version += 1


def _apply_bulk_approve(db: DbSession, state: dict) -> None:
    """Restore (undo) or re-apply (redo) every item in a bulk approval's
    snapshot, locked together in ascending `Item.id` order -- the same
    fixed ordering `bulk.bulk_approve()` uses, so this can never deadlock
    against a concurrent bulk approval or a second undo. An item missing
    from the database (deleted since the batch was recorded) is skipped
    rather than failing the whole reversal.

    Each item actually touched gets its `version` bumped too -- see
    `_apply_item_state()`'s docstring for why undo/redo always move the
    counter forward rather than restoring whatever it held before.
    """
    rows = state.get(ITEMS_SNAPSHOT_KEY, [])
    if not rows:
        return

    ids = [uuid.UUID(row["id"]) for row in rows]
    locked = db.scalars(
        select(Item).where(Item.id.in_(ids)).order_by(Item.id)
        .with_for_update().execution_options(populate_existing=True)
    ).all()
    by_id = {row.id: row for row in locked}

    for row in rows:
        item_id, fields = _decode_item_row(row)
        item = by_id.get(item_id)
        if item is None:
            continue
        for key, value in fields.items():
            setattr(item, key, value)
        item.version += 1


def _apply_scale(db: DbSession, action: Action, direction: str) -> None:
    """Restore or re-apply a compound scale confirmation: the sheet's
    scale, every released item's status, and -- the part that separates a
    working undo from one that silently destroys evidence -- the
    scale-reason warnings `scale.set_scale()` deleted.

    Status and warnings are handled in one loop, gated by the same
    "does this item still exist" check, matching `_apply_bulk_approve()`.
    An earlier version checked item-existence only for the status update
    and unconditionally tried to restore each item's warnings regardless
    -- for an item deleted in between, that meant inserting a `Warning`
    row whose `item_id` no longer existed, a `ForeignKeyViolation`.

    The warning list itself is always read from `action.before`
    regardless of direction, since that is the only place `set_scale()`
    recorded it (`after` only carries `{"id", "status"}` per item). Undo
    re-inserts any warning not already present; redo deletes them again
    -- without that, a redo would leave an item both Ready to review and
    still carrying the warning that explained why it wasn't.
    """
    state = action.before if direction == "before" else action.after

    sheet = db.execute(
        select(Sheet).where(Sheet.id == action.sheet_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if sheet is None:
        raise DomainError(
            "sheet_no_longer_exists",
            "This sheet no longer exists. Refresh the project to see its current sheets.",
            status=409,
        )
    sheet.scale = state["scale"]

    rows = state.get(ITEMS_SNAPSHOT_KEY, [])
    if not rows:
        return

    warnings_by_item_id = {
        uuid.UUID(row["id"]): row.get("warnings", [])
        for row in action.before.get(ITEMS_SNAPSHOT_KEY, [])
    }

    ids = [uuid.UUID(row["id"]) for row in rows]
    locked = db.scalars(
        select(Item).where(Item.id.in_(ids)).order_by(Item.id)
        .with_for_update().execution_options(populate_existing=True)
    ).all()
    by_id = {row.id: row for row in locked}

    for row in rows:
        item_id, fields = _decode_item_row(row, exclude=frozenset({"warnings"}))
        item = by_id.get(item_id)
        if item is None:
            continue  # deleted since -- nothing to restore, status or warnings
        item.status = fields["status"]

        for encoded_warning in warnings_by_item_id.get(item_id, []):
            warning_fields = decode_snapshot(encoded_warning, WARNING_SNAPSHOT_TYPES)
            if direction == "before":
                _restore_row_if_missing(db, Warning, warning_fields)
            else:
                _delete_row_if_present(db, Warning, warning_fields["id"])

        # Every item this loop reaches had its status and/or warnings
        # touched -- see _apply_item_state()'s docstring for why undo/redo
        # bump the counter forward rather than restoring a snapshotted one.
        item.version += 1


def _apply_delete(db: DbSession, action: Action, direction: str) -> None:
    """Restore a deleted item and its warnings (undo), or remove it again
    (redo). `before` is `delete_item()`'s full column snapshot plus a
    nested `"warnings"` list -- the cascade destroys both the row and its
    evidence, so both have to be reconstructed, not just the row.

    Restoring the item and restoring each warning are independent checks,
    not one early return gated on the item alone -- an item that already
    came back (through a prior undo) but lost a warning some other way
    must still get that warning back, not report success while leaving
    the evidence missing.
    """
    if direction == "before":
        state = action.before
        item_fields = {key: value for key, value in state.items() if key != "warnings"}
        # No "version" key reaches here: review._apply_delete() pops it
        # from the snapshot before it is ever recorded, deliberately, so
        # the reconstructed row below gets the ordinary column default
        # (1) rather than resurrecting a pre-delete counter value --
        # nothing between deletion and restoration could have held a
        # valid reference to this row anyway, so starting a fresh version
        # lineage at 1 is both simplest and safe.
        decoded = decode_snapshot(item_fields, ITEM_SNAPSHOT_TYPES)
        _restore_row_if_missing(db, Item, decoded)
        for encoded_warning in state.get("warnings", []):
            warning_fields = decode_snapshot(encoded_warning, WARNING_SNAPSHOT_TYPES)
            _restore_row_if_missing(db, Warning, warning_fields)
    else:
        item = db.execute(
            select(Item).where(Item.id == action.item_id)
            .with_for_update().execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if item is not None:
            db.delete(item)
