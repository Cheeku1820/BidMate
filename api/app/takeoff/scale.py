"""Scale confirmation: one compound action covering a sheet's scale and
every measured item that scale unblocks.

Confirming a sheet's scale does two things at once: it sets the sheet's
`scale` column, and it re-derives every *Missing information* item on
that sheet -- the ones that could not be measured without a scale -- to
*Ready to review*, clearing the warning that explained why each was
blocked. The interaction design (`DESIGN.md`, "Undo semantics") is
explicit that this is a single undoable action: an estimator who
confirms a scale and immediately realizes the title block was right all
along gets one undo, not one per released item.

This lives in its own module rather than another function in
`review.py` for the same reason `bulk.py` does -- it is a materially
different act (a sheet-level change plus a batch of item releases, not a
single item's review state), and `review.py` is already at this
project's line-count guideline.

Locking: every candidate item is locked with `SELECT ... FOR UPDATE`, in
ascending `Item.id` order -- the fixed, caller-independent convention
recorded next to `actions.commit()` and already followed by
`bulk.bulk_approve()`. Two reviewers confirming scales on sheets whose
blocked-item sets overlap (a shared conduit run split across two markers,
say) must lock in the same order regardless of which reviewer's request
happens to run first, or the two transactions deadlock against each
other.

Recording: `commit()`'s `before`/`after` are flat dicts, so recording a
sheet's prior scale plus N items' prior state needs a nesting
convention. This follows `review._apply_delete()` / `bulk.py`'s
precedent -- nest under a key, pre-encode the nested structure with
`encode_snapshot()` before handing it to `commit()`, since `commit()`'s
own encoding is shallow and does not reach inside a nested list.

What Task 10's undo needs is more than `{id, status}` per item: it also
has to restore the warning that explained why each item was Missing
information, since this function deletes those warning rows outright
(the same way `review._apply_delete()` snapshots a warning before its
row is destroyed, rather than leaving it to be reconstructed from
nothing). So each item's snapshot carries its own `warnings` list,
encoded with `review.WARNING_SNAPSHOT_TYPES`' shape, plus a decodable
`status` an undo can flip back to. The sheet's prior scale sits
alongside it under `"scale"`.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.actions import commit, encode_snapshot
from app.takeoff.models import Action, Item, ReviewStatus, Sheet, Warning
from app.takeoff.review import _column_snapshot

# The key `before`/`after` nest per-item snapshots under, matching
# `bulk.ITEMS_SNAPSHOT_KEY`'s naming so a future reader of either module
# recognizes the pattern immediately rather than treating it as a new one.
ITEMS_SNAPSHOT_KEY = "items"


def set_scale(db: DbSession, actor: User, sheet: Sheet, value: str) -> Action:
    """Set `sheet`'s scale and release every item that scale was blocking,
    as one action.

    Only items on `sheet` move -- a project can have many sheets each
    missing their own scale independently, and confirming one must never
    touch another sheet's Missing information items.
    """
    blocked = list(db.scalars(
        select(Item)
        .where(Item.sheet_id == sheet.id, Item.status == ReviewStatus.MISSING)
        .order_by(Item.id)
        .with_for_update()
    ))

    items_before: list[dict] = []
    items_after: list[dict] = []

    for item in blocked:
        warnings = db.execute(select(Warning).where(Warning.item_id == item.id)).scalars().all()
        items_before.append(encode_snapshot({
            "id": item.id,
            "status": item.status,
            "warnings": [encode_snapshot(_column_snapshot(w)) for w in warnings],
        }))
        for warning in warnings:
            db.delete(warning)
        item.status = ReviewStatus.READY
        items_after.append(encode_snapshot({"id": item.id, "status": item.status}))

    prior_scale = sheet.scale
    sheet.scale = value

    count = len(blocked)
    return commit(
        db, actor=actor, project_id=sheet.project_id, kind="scale",
        label=f"Set scale on {sheet.number} — {count} measured item{'s' if count != 1 else ''} recalculated",
        before={"scale": prior_scale, ITEMS_SNAPSHOT_KEY: items_before},
        after={"scale": value, ITEMS_SNAPSHOT_KEY: items_after},
        sheet_id=sheet.id,
    )
