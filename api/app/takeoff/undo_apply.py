"""Per-kind state reversal for `undo.py`, split out for the same reason
`bulk.py` and `scale.py` were split out of `review.py`: a materially
different concern (reversing four distinct snapshot shapes, each with
its own locking and staleness handling) that would otherwise push
`undo.py` well past this project's line-count guideline.

`apply()` is the only export. It dispatches on `Action.kind`, because
each kind's `before`/`after` shape differs (see `review.py`, `bulk.py`,
`scale.py` for how each is written):

- `approve` / `reject` / `unreject` / `edit` -- a flat dict of changed
  `Item` columns, restored with one `decode_snapshot()` call against
  `snapshots.ITEM_SNAPSHOT_TYPES`.
- `delete` -- `before` is a full `Item` column snapshot plus a nested
  `"warnings"` list (both destroyed by the cascade); `after` is `{}`.
  Undo reconstructs the row and its warnings; redo deletes it again.
- `bulk_approve` / `scale` -- both nest a list of per-item dicts, each
  carrying its own `"id"`, under `ITEMS_SNAPSHOT_KEY`. `scale` also
  carries the sheet's prior `"scale"` and, per released item, the
  scale-reason `"warnings"` `set_scale()` deleted. Undo has to restore
  the sheet's scale, every item's status, *and* those warnings together,
  or it quietly destroys the evidence it exists to protect; redo has to
  delete those same warnings a second time, or an item ends up both
  Ready to review and still carrying the warning that explained why it
  wasn't -- see `_apply_scale()`.

Locking follows the convention next to `actions.commit()`: multiple
`Item` rows lock in ascending `Item.id` order; a `Sheet` locks before its
items. Authorization is `undo.py`'s job, checked before this module is
ever called.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.takeoff.actions import decode_snapshot
from app.takeoff.bulk import ITEMS_SNAPSHOT_KEY
from app.takeoff.models import Action, Item, Sheet, Warning
from app.takeoff.snapshots import ITEM_SNAPSHOT_TYPES, WARNING_SNAPSHOT_TYPES


def apply(db: DbSession, action: Action, direction: str) -> None:
    """Mutate domain rows to match `action`'s `before` snapshot
    (`direction="before"`, an undo) or `after` snapshot
    (`direction="after"`, a redo).
    """
    state = action.before if direction == "before" else action.after

    if action.kind == "scale":
        _apply_scale(db, action, direction)
    elif action.kind == "bulk_approve":
        _apply_bulk_approve(db, state)
    elif action.kind == "delete":
        _apply_delete(db, action, direction)
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
    """Drop a stale identity-mapped object for `pk`, if one is present,
    before inserting a fresh row with the same id. Only ever called after
    `_row_exists()` has confirmed the database has no such row, so a
    `Session.get()` hit here is exactly the stale cascade-orphaned
    instance `_row_exists()` describes. Without this, `db.add()`-ing a
    new object at the same identity produces an `SAWarning` from
    SQLAlchemy's own conflict detector -- correctly, since two live
    objects claiming one identity is how a later silent overwrite happens.
    """
    stale = db.get(model, pk)
    if stale is not None:
        db.expunge(stale)


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
    """
    if not state or item_id is None:
        return

    item = db.execute(
        select(Item).where(Item.id == item_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if item is None:
        raise DomainError(
            "item_no_longer_exists",
            "This item was deleted since that action was recorded. Refresh the sheet to see its current items.",
            status=409,
        )

    for key, value in decode_snapshot(state, ITEM_SNAPSHOT_TYPES).items():
        setattr(item, key, value)


def _apply_bulk_approve(db: DbSession, state: dict) -> None:
    """Restore (undo) or re-apply (redo) every item in a bulk approval's
    snapshot, locked together in ascending `Item.id` order -- the same
    fixed ordering `bulk.bulk_approve()` uses, so this can never deadlock
    against a concurrent bulk approval or a second undo. An item missing
    from the database (deleted since the batch was recorded) is skipped
    rather than failing the whole reversal.
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


def _apply_scale(db: DbSession, action: Action, direction: str) -> None:
    """Restore or re-apply a compound scale confirmation: the sheet's
    scale, every released item's status, and -- the part that separates a
    working undo from one that silently destroys evidence -- the
    scale-reason warnings `scale.set_scale()` deleted.

    The warning list is always read from `action.before` regardless of
    direction, since that is the only place `set_scale()` recorded it
    (`after` only carries `{"id", "status"}` per item). Undo re-inserts
    any warning not already present; redo deletes them again -- without
    that, a redo would leave an item both Ready to review and still
    carrying the warning that explained why it wasn't.
    """
    state = action.before if direction == "before" else action.after

    sheet = db.execute(
        select(Sheet).where(Sheet.id == action.sheet_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if sheet is None:
        raise DomainError(
            "sheet_no_longer_exists",
            "This sheet no longer exists. It may have been removed since this action was recorded.",
            status=409,
        )
    sheet.scale = state["scale"]

    rows = state.get(ITEMS_SNAPSHOT_KEY, [])
    if rows:
        ids = [uuid.UUID(row["id"]) for row in rows]
        locked = db.scalars(
            select(Item).where(Item.id.in_(ids)).order_by(Item.id)
            .with_for_update().execution_options(populate_existing=True)
        ).all()
        by_id = {row.id: row for row in locked}
        for row in rows:
            item_id, fields = _decode_item_row(row, exclude=frozenset({"warnings"}))
            item = by_id.get(item_id)
            if item is not None:
                item.status = fields["status"]

    for row in action.before.get(ITEMS_SNAPSHOT_KEY, []):
        for encoded_warning in row.get("warnings", []):
            fields = decode_snapshot(encoded_warning, WARNING_SNAPSHOT_TYPES)
            if direction == "before":
                if not _row_exists(db, Warning, fields["id"]):
                    db.add(Warning(**fields))
            else:
                existing = db.get(Warning, fields["id"])
                if existing is not None:
                    db.delete(existing)


def _apply_delete(db: DbSession, action: Action, direction: str) -> None:
    """Restore a deleted item and its warnings (undo), or remove it again
    (redo). `before` is `delete_item()`'s full column snapshot plus a
    nested `"warnings"` list -- the cascade destroys both the row and its
    evidence, so both have to be reconstructed, not just the row.
    """
    if direction == "before":
        state = action.before
        item_fields = {key: value for key, value in state.items() if key != "warnings"}
        decoded = decode_snapshot(item_fields, ITEM_SNAPSHOT_TYPES)
        if _row_exists(db, Item, decoded["id"]):
            return  # already present -- nothing to restore
        _expunge_stale(db, Item, decoded["id"])
        db.add(Item(**decoded))
        for encoded_warning in state.get("warnings", []):
            fields = decode_snapshot(encoded_warning, WARNING_SNAPSHOT_TYPES)
            if not _row_exists(db, Warning, fields["id"]):
                _expunge_stale(db, Warning, fields["id"])
                db.add(Warning(**fields))
    else:
        item = db.execute(
            select(Item).where(Item.id == action.item_id)
            .with_for_update().execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if item is not None:
            db.delete(item)
