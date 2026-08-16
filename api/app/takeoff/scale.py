"""Scale confirmation: one compound action covering a sheet's scale and
every measured item that scale unblocks.

Confirming a sheet's scale does two things at once: it sets the sheet's
`scale` column, and it re-derives every *Missing information* item on
that sheet that was blocked *specifically by the missing scale* -- not
every Missing information item on the sheet -- to *Ready to review*,
clearing the warning that explained why each was blocked. The
interaction design (`DESIGN.md`, "Undo semantics") is explicit that this
is a single undoable action: an estimator who confirms a scale and
immediately realizes the title block was right all along gets one undo,
not one per released item.

Why "specifically by the missing scale" matters: *Missing information*
covers any absent evidence -- a scale, a legend entry -- not just a
scale. `Warning.reason` (`app.takeoff.models.WarningReason`) is what
lets this function tell those apart. An item whose only warning has
`reason=LEGEND` (an unclassified symbol) is left untouched entirely,
even if it happens to sit on this sheet and happens to also be Missing
information -- confirming a scale must never delete the warning that
explains why a symbol was never countable, or that item becomes
eligible for bulk approval with a guessed quantity, which is exactly
the failure the status vocabulary exists to prevent. An item blocked on
*both* a scale warning and a legend warning has its scale warning
cleared -- that half of the problem really was resolved -- but stays
Missing information, with its legend warning intact, because the other
half was not.

This lives in its own module rather than another function in
`review.py` for the same reason `bulk.py` does -- it is a materially
different act (a sheet-level change plus a batch of item releases, not a
single item's review state), and `review.py` is already at this
project's line-count guideline.

Authorization runs first, before any row is read or locked -- the same
fix `bulk.bulk_approve()` applies and for the same reason: locking rows
under `FOR UPDATE` is itself an effect (it can block a concurrent
request, and it discloses that the targeted rows exist) that a caller
outside the sheet's org must never be able to trigger. Resolving the
project and comparing org happens before either locking select below.

Locking: the sheet row is locked first, then every candidate item, in
ascending `Item.id` order -- the fixed, caller-independent convention
recorded next to `actions.commit()` and already followed by
`bulk.bulk_approve()`. This is the first caller to lock across two
tables in one action; sheets-before-items is the order, so a future
caller that also needs to lock both never has to guess which comes
first. Locking the sheet matters even when zero items are blocked: with
no items to lock, nothing else in this function takes any lock at all,
so two reviewers concurrently confirming different scales on the same
sheet would otherwise both succeed with no serialization between them,
leaving two actions that each believe they know the sheet's prior
scale. Every locking select also sets `populate_existing=True`, the
same discipline `bulk.py` and `review._apply_approve()` use -- without
it, SQLAlchemy returns an already-identity-mapped Python object without
refreshing its attributes, and a stale `status` or `scale` read here is
exactly what would get written into the `before` snapshot Task 10's
undo restores.

Recording: `commit()`'s `before`/`after` are flat dicts, so recording a
sheet's prior scale plus N items' prior state needs a nesting
convention. This follows `review._apply_delete()` / `bulk.py`'s
precedent -- nest under a key, pre-encode the nested structure with
`encode_snapshot()` before handing it to `commit()`, since `commit()`'s
own encoding is shallow and does not reach inside a nested list. Each
item's snapshot is a dict carrying its own `id` (a list, not a dict
keyed by item id) -- `bulk.py` originally nested its per-item snapshots
under a dict keyed by item-id string instead; the two modules shared a
constant name (`ITEMS_SNAPSHOT_KEY`) for two different payload shapes,
which is exactly the kind of thing that produces a subtly wrong undo.
`bulk.py` now matches this module's list-with-embedded-id form.

What Task 10's undo needs is more than `{id, status}` per item: it also
has to restore the scale warning that explained why each item was
Missing information, since this function deletes that warning row
outright (the same way `review._apply_delete()` snapshots a warning
before its row is destroyed, rather than leaving it to be reconstructed
from nothing). So each item's snapshot carries a `warnings` list holding
only the warning(s) this function actually deletes -- its scale-reason
warnings, encoded with `snapshots.WARNING_SNAPSHOT_TYPES`' shape -- plus
a decodable `status` an undo can flip back to. A non-scale warning left
in place on the item (the mixed scale-and-legend case) is never touched
and never appears in this snapshot, because this function never deleted
it and undo has nothing to restore for it. The sheet's prior scale sits
alongside the item list under `"scale"`.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.actions import CrossOrgActionError, commit, encode_snapshot
from app.takeoff.models import Action, Item, Project, ReviewStatus, Sheet, Warning, WarningReason
from app.takeoff.snapshots import ITEMS_SNAPSHOT_KEY, _column_snapshot


def set_scale(db: DbSession, actor: User, sheet: Sheet, value: str) -> Action:
    """Set `sheet`'s scale and release every item that scale was blocking,
    as one action.

    Only items on `sheet` move -- a project can have many sheets each
    missing their own scale independently, and confirming one must never
    touch another sheet's Missing information items. Within `sheet`,
    only items whose Missing information is explained by a scale warning
    move; an item blocked by an unrelated warning (an unclassified
    symbol, say) is left exactly as it was, whether or not it also
    carries a scale warning of its own -- see the module docstring for
    the mixed-warning case. A rejected item never moves either way,
    matching `bulk.bulk_approve()`: an estimator who already set an item
    aside must not see it move out from under them because a scale was
    confirmed.
    """
    project = db.get(Project, sheet.project_id)
    if project is None or project.org_id != actor.org_id:
        raise CrossOrgActionError(
            f"actor {actor.id} is not authorized to set the scale for project {sheet.project_id}"
        )

    locked_sheet = db.execute(
        select(Sheet).where(Sheet.id == sheet.id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()

    scale_blocked_item_ids = select(Warning.item_id).where(
        Warning.reason == WarningReason.SCALE, Warning.item_id.is_not(None)
    )
    blocked = list(db.scalars(
        select(Item)
        .where(
            Item.sheet_id == locked_sheet.id,
            Item.status == ReviewStatus.MISSING,
            Item.rejected_at.is_(None),
            Item.id.in_(scale_blocked_item_ids),
        )
        .order_by(Item.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ))

    items_before: list[dict] = []
    items_after: list[dict] = []

    for item in blocked:
        warnings = db.execute(select(Warning).where(Warning.item_id == item.id)).scalars().all()
        scale_warnings = [w for w in warnings if w.reason is WarningReason.SCALE]
        other_warnings = [w for w in warnings if w.reason is not WarningReason.SCALE]

        items_before.append(encode_snapshot({
            "id": item.id,
            "status": item.status,
            "warnings": [encode_snapshot(_column_snapshot(w)) for w in scale_warnings],
        }))

        for warning in scale_warnings:
            db.delete(warning)

        # Only fully release the item once nothing else is still blocking
        # it -- an item with a surviving non-scale warning (the legend
        # case) stays Missing information even though its scale problem
        # is resolved.
        if not other_warnings:
            item.status = ReviewStatus.READY
        items_after.append(encode_snapshot({"id": item.id, "status": item.status}))
        # Every item this loop reaches had at least one warning deleted,
        # even when its status did not move (the mixed scale-and-legend
        # case) -- its stored representation changed, so its optimistic-
        # concurrency counter must too, or a client that later loads this
        # item and edits it single-item would be checked against a
        # version that never accounted for this scale confirmation.
        item.version += 1

    prior_scale = locked_sheet.scale
    locked_sheet.scale = value

    count = len(blocked)
    return commit(
        db, actor=actor, project_id=locked_sheet.project_id, kind="scale",
        label=f"Set scale on {locked_sheet.number} — {count} measured item{'s' if count != 1 else ''} recalculated",
        before={"scale": prior_scale, ITEMS_SNAPSHOT_KEY: items_before},
        after={"scale": value, ITEMS_SNAPSHOT_KEY: items_after},
        sheet_id=locked_sheet.id,
    )
