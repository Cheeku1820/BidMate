"""reprocess.py -- re-running the engine after a note, without
discarding a person's judgment.

Deliberately not ingest_service. Ingest replaces a takeoff wholesale and
refuses when approvals exist; this one preserves them and proceeds. Two
different intentions about what may be destroyed, so two entry points
rather than one with a flag deciding which.

The merge key is (sheet number, source_tag). Counting is deterministic
geometry -- the same drawing yields the same cluster tag on the same
sheet -- which is what makes recognising last run's item possible at all.

That key is not unique, though: `source_tag` defaults to `""`, so every
item ingested before migration 0012 -- i.e. every item on every
pre-existing project -- carries an empty tag, and a sheet commonly holds
many of them. `by_key` therefore maps to a *list* of items sharing a key,
consumed one at a time (`list.pop(0)`) as the engine's rows are walked in
order, so N existing items sharing a key match N incoming rows
positionally instead of collapsing onto a single dict entry and silently
surviving as N-1 duplicates.

Fix round 1 also replaced delete-then-reinsert with an in-place update
for a matched, un-approved item: earlier actions (an edit, say) reference
that item by id, and undo/redo walk the action log by id too. Recreating
the row under a fresh id orphaned every prior action pointing at it --
`note_apply` is not itself undoable, so undo skips past it to the
previous mutation, which then 409s forever because the id it names no
longer exists. Updating the row's columns in place keeps that id alive,
so undo keeps working exactly as it did before the note was applied.

Fix round 2: a bucket with more than one item can hold a mix of
approved and un-approved rows, and `list.pop(0)` doesn't care which it
returns. Popping an approved item first burns the incoming row that
would otherwise have gone to an un-approved sibling -- the row is
correctly never written onto the approved item (that guarantee is
untouched), but it is then simply discarded, so the engine's finding
vanishes instead of landing anywhere. Which item happened to sort first
depended on `Item.id`, a random UUID with no relationship to anything
about the drawing, so the same scenario silently produced a different
item count from one project to the next. `_bucket_order()` below fixes
this by matching every un-approved item in a bucket before any approved
one is even considered -- an approved item is only ever popped once
there is no un-approved sibling left to take the row instead.
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff import actions, undo
from app.takeoff.evidence_images import upsert_evidence_image
from app.takeoff.ingest import map_payload
from app.takeoff.models import Action, Item, Project, ReviewStatus, Sheet, Warning, WarningReason


def _key(sheet_number: str, source_tag: str) -> tuple[str, str]:
    return (sheet_number or "", source_tag or "")


def _deliberately_deleted(db: DbSession, project_id: uuid.UUID, number_by_sheet_id: dict) -> dict:
    """How many items per merge key a person deleted and has not undone.

    Deletion is a hard row delete (`review._apply_delete`), not a flag,
    so the items table cannot distinguish "an estimator deleted this"
    from "this never existed" -- but the action log can, and it is the
    system of record for exactly this kind of question. A live `delete`
    action carries the removed row's full column snapshot, `sheet_id`
    and `source_tag` included, which is the merge key.

    Without this, delete → re-run → undo produced two items for one
    cluster, both counted in the total: the merge found the key
    unmatched and inserted a fresh row, then the next undo (`note_apply`
    is not undoable, so undo skips past it to the earlier `delete`)
    restored the original alongside it.

    Liveness is `undo._live()`, the same walk undo/redo use, so a
    deletion the estimator has already undone correctly does not
    suppress anything -- and a delete → undo → redo chain, which leaves
    the item deleted, correctly does.

    Counted per key rather than treated as a boolean because a key is
    not unique: with three untagged items on a sheet and one deleted,
    exactly one incoming row should be suppressed, not all three.
    """
    rows = undo._action_summaries(db, project_id)
    live = undo._live(rows)
    live_delete_ids = [r.id for r in rows if r.kind == "delete" and live[r.id]]
    if not live_delete_ids:
        return {}

    deleted: dict[tuple[str, str], int] = {}
    for action in db.scalars(select(Action).where(Action.id.in_(live_delete_ids))):
        snapshot = action.before or {}
        # `sheet_id` is a UUID encoded to a string by `encode_snapshot`;
        # the sheet may since have been removed, in which case there is
        # no key to suppress and nothing to do.
        number = number_by_sheet_id.get(_as_uuid(snapshot.get("sheet_id")))
        if number is None:
            continue
        key = _key(number, snapshot.get("source_tag") or "")
        deleted[key] = deleted.get(key, 0) + 1
    return deleted


def _as_uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _bucket_order(item: Item) -> tuple[bool, object, uuid.UUID]:
    """Sort key for items sharing one merge-key bucket.

    `status is APPROVED` first in the tuple means every un-approved item
    in a bucket sorts before every approved one (`False < True`), so
    `list.pop(0)` in the merge loop below always exhausts the
    un-approved items before it ever considers an approved one -- an
    approved item can only consume (and discard) an incoming row once
    there is truly no un-approved sibling left that could have taken it
    instead. That is the actual fix; without it, an approved item could
    win an incoming row purely because it happened to sort first, and
    the engine's finding for that row would vanish with no item left to
    carry it.

    `Item` has no creation-order column, so `updated_at` (set once at
    insert, changed only by a later mutation) is the closest stable,
    meaningful tiebreaker available for items that tie on approval
    status -- not perfect, since every item written in the same ingest
    transaction shares one transaction timestamp (`actions.py`'s
    `Action.created_at` has the identical problem), but still real
    insertion-adjacent information rather than an arbitrary UUID. `id`
    breaks any remaining tie, so a fixed set of rows always sorts the
    same way rather than depending on whatever order a query happened
    to return them in.
    """
    return (item.status is ReviewStatus.APPROVED, item.updated_at, item.id)


# The fields whose change an estimator would call "reclassified".
#
# Chosen as: what the item reads as on the review workspace and the
# takeoff table -- its identity (`name`, `description`, `symbol`), where
# it sits in the estimate (`system`, `category`), the number being bid
# (`quantity`, `unit`), and its review label (`status`).
#
# Deliberately excluded: `x`/`y`/`placements`, and every cost field.
# Coordinates shifting by a fraction of a sheet unit is the geometry
# agent being deterministic about the same drawing, not a
# reclassification, and cost is *derived* -- a pricing table refresh
# would otherwise report every item in the project as reclassified when
# nothing about what the item IS has changed. `ai_confirmed` and
# `source_tag` are pipeline bookkeeping the estimator never sees, and
# `version` is bumped by this function itself.
#
# A warning appearing, vanishing, or changing its title counts too: it
# is the evidence that decides the status, and it is on screen.
_VISIBLE_FIELDS = ("name", "description", "symbol", "system", "category", "quantity", "unit")


def _changes_visibly(item: Item, sheet: Sheet, row: dict, warning_title: str | None) -> bool:
    """Whether writing `row` onto `item` would change something the
    estimator would notice -- the test for counting a row as
    reclassified.

    Without this, `reclassified` counted every matched un-approved row
    whether or not a single field differed. In the documented dev mode
    (no `ANTHROPIC_API_KEY`) notes cannot affect classification at all,
    so a 300-item project reported "300 items reclassified" after a
    re-run that changed nothing -- and the spec's own example
    ("Reclassified 7 items") plainly means seven items that changed.
    """
    if item.sheet_id != sheet.id:
        return True
    if ReviewStatus(row["status"]) is not item.status:
        return True
    if any(getattr(item, field) != row[field] for field in _VISIBLE_FIELDS):
        return True
    incoming = row["warning"]["title"] if row["warning"] else None
    return incoming != warning_title


def _warning_title(db: DbSession, item_id: uuid.UUID) -> str | None:
    row = db.scalars(select(Warning).where(Warning.item_id == item_id)).first()
    return row.title if row else None


def _replace_warning(db: DbSession, item_id: uuid.UUID, warning: dict | None) -> None:
    db.execute(delete(Warning).where(Warning.item_id == item_id))
    if warning:
        db.add(Warning(
            id=uuid.uuid4(), item_id=item_id, sheet_id=None,
            reason=WarningReason(warning["reason"]), title=warning["title"], found=warning["found"],
            why=warning["why"], fix=warning["fix"], where_=warning["where"],
        ))


def _overwrite(item: Item, sheet: Sheet, row: dict) -> None:
    """Set every field the engine owns onto an existing row, in place.

    Deliberately does not touch `notes` -- that field is the estimator's
    own, never the engine's, and nothing here is entitled to overwrite
    it. Deliberately does not touch `approved_by_user_id`/`approved_at`/
    `rejected_by_user_id`/`rejected_at` either: this function is only
    ever called on a row already confirmed not APPROVED, and rejection
    is orthogonal to the engine's fields the same way notes is.
    """
    item.sheet_id = sheet.id
    item.symbol = row["symbol"]
    item.name = row["name"]
    item.description = row["description"]
    item.system = row["system"]
    item.category = row["category"]
    item.quantity = row["quantity"]
    item.unit = row["unit"]
    item.status = ReviewStatus(row["status"])
    item.x = row["x"]
    item.y = row["y"]
    item.placements = row["placements"]
    item.material_cost = row["material_cost"]
    item.labor_hours = row["labor_hours"]
    item.labor_cost = row["labor_cost"]
    item.total_cost = row["total_cost"]
    item.ai_confirmed = row["ai_confirmed"]
    item.source_tag = row["source_tag"]
    item.evidence = row["evidence"]
    # Bumped exactly like every other mutation that changes a row's
    # fields (review._apply_edit, undo_apply._apply_item_state) -- a
    # client holding a stale version must not write over this re-run.
    item.version += 1


def reprocess_takeoff(db: DbSession, *, actor: User, project: Project, payload: dict) -> dict:
    mapped = map_payload(payload)

    # Sheets are keyed by `number` alone, with no ordering and no
    # revision filter, so two sheets in a project sharing a number would
    # resolve to whichever the query returned last -- arbitrarily. That
    # is latent today because nothing writes `superseded_at`: a project
    # holds one revision of each sheet and numbers are in fact unique.
    # It becomes a real defect the moment revisions land (ROADMAP.md
    # 2.2), so whoever builds them has to key this on (number, revision)
    # or filter superseded sheets out here.
    sheets = {s.number: s for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id))}
    for row in mapped.sheets:
        sheet = sheets.get(row["number"])
        if sheet is None:
            sheet = Sheet(
                id=uuid.uuid4(), project_id=project.id, number=row["number"], title=row["title"],
                discipline=row["discipline"], revision=row["revision"], scale=row["scale"],
                scale_options=[], plan=row["plan"], sort_order=row["sort_order"],
                takeoff_id=row["takeoff_id"], page_index=row["page_index"],
                width_pt=row["width_pt"], height_pt=row["height_pt"],
                unreadable_reason=row["unreadable_reason"], ai_reading=row["ai_reading"],
            )
            db.add(sheet)
            sheets[row["number"]] = sheet
    db.flush()

    sheet_number_by_key = {r["key"]: r["number"] for r in mapped.sheets}

    # Lock every existing item up front, in ascending id order -- the
    # convention actions.commit()'s docstring lays out for any caller
    # that touches more than one row of the same table in one
    # transaction (bulk.bulk_approve, scale.set_scale). Acquiring every
    # lock in one canonical-order statement before this function updates,
    # inserts, or deletes anything is what keeps a concurrent reprocess
    # or bulk approve on overlapping items from deadlocking against this
    # one.
    existing = list(
        db.scalars(
            select(Item).where(Item.project_id == project.id).order_by(Item.id).with_for_update()
        )
    )
    number_by_sheet_id = {s.id: s.number for s in sheets.values()}
    # Per merge key, how many items a person deleted and has not undone.
    # Consumed below so the merge does not resurrect them.
    deleted_by_key = _deliberately_deleted(db, project.id, number_by_sheet_id)
    by_key: dict[tuple[str, str], list[Item]] = {}
    for i in existing:
        by_key.setdefault(_key(number_by_sheet_id.get(i.sheet_id, ""), i.source_tag), []).append(i)
    # Un-approved before approved, then a stable tiebreak -- see
    # `_bucket_order()`. Sorted once per bucket, up front, so every
    # `pop(0)` below draws from a fixed, deterministic order rather than
    # whatever order the locking query happened to return.
    for bucket in by_key.values():
        bucket.sort(key=_bucket_order)

    # Every approved item the run left alone -- whether it was matched
    # against an incoming row and skipped, or never matched at all --
    # counted here, once, so the number and the audit label always agree
    # with what actually happened.
    # `skipped_deleted` goes into the audit label rather than the
    # response: the summary strip on screen names what a re-run changed,
    # and declining to resurrect a deleted item is the absence of a
    # change. The action log is where "and it left three deletions
    # alone" is worth being able to read back.
    preserved = reclassified = added = skipped_deleted = 0

    for row in mapped.items:
        number = sheet_number_by_key.get(row["sheet_key"], "")
        key = _key(number, row["source_tag"])
        bucket = by_key.get(key)
        current = bucket.pop(0) if bucket else None

        # An estimator approved this. Their name is on it; a re-run does
        # not get to change it -- not the row, not its warnings, not
        # even a touch that would bump updated_at or version. The
        # incoming row that matched it is discarded rather than becoming
        # a duplicate, exactly as it would have with a single approved
        # match under the old one-item-per-key scheme.
        if current is not None and current.status is ReviewStatus.APPROVED:
            preserved += 1
            continue

        sheet = sheets[number]
        if current is not None:
            # Asked *before* the overwrite, while the row still holds
            # what the estimator last saw -- `reclassified` counts rows
            # that changed, not rows that were touched.
            changed = _changes_visibly(current, sheet, row, _warning_title(db, current.id))
            _overwrite(current, sheet, row)
            _replace_warning(db, current.id, row["warning"])
            upsert_evidence_image(db, current.id, row["evidence_png"])
            if changed:
                reclassified += 1
        elif deleted_by_key.get(key, 0) > 0:
            # The estimator deleted this one and has not undone it. A
            # re-run does not get to bring it back -- deletion is a
            # judgment about the drawing ("that device is existing to
            # remain") that survives the engine seeing the same shape
            # again, exactly as an approval survives it. Decremented so
            # one deletion suppresses one incoming row: keys are not
            # unique, and deleting one of three untagged items on a
            # sheet must not silence the other two.
            deleted_by_key[key] -= 1
            skipped_deleted += 1
        else:
            item = Item(
                id=uuid.uuid4(), project_id=project.id, sheet_id=sheet.id,
                symbol=row["symbol"], name=row["name"], description=row["description"],
                system=row["system"], category=row["category"], quantity=row["quantity"],
                unit=row["unit"], status=ReviewStatus(row["status"]), x=row["x"], y=row["y"],
                placements=row["placements"], material_cost=row["material_cost"],
                labor_hours=row["labor_hours"], labor_cost=row["labor_cost"],
                total_cost=row["total_cost"], ai_confirmed=row["ai_confirmed"],
                source_tag=row["source_tag"], evidence=row["evidence"],
            )
            db.add(item)
            db.flush()
            upsert_evidence_image(db, item.id, row["evidence_png"])
            if row["warning"]:
                w = row["warning"]
                db.add(Warning(id=uuid.uuid4(), item_id=item.id, sheet_id=None,
                               reason=WarningReason(w["reason"]), title=w["title"], found=w["found"],
                               why=w["why"], fix=w["fix"], where_=w["where"]))
            added += 1

    # Whatever is left in each bucket is what the engine did not report
    # this run, whether because its key vanished entirely or because
    # there were more existing items sharing a key than incoming rows to
    # match them. An un-approved leftover is gone; an approved one stays
    # -- removing it would delete a decision silently.
    removed = 0
    for bucket in by_key.values():
        for item in bucket:
            if item.status is ReviewStatus.APPROVED:
                preserved += 1
                continue
            db.execute(delete(Warning).where(Warning.item_id == item.id))
            db.delete(item)
            removed += 1

    db.flush()
    label = (f"Applied notes and re-ran the takeoff: {reclassified} reclassified, "
             f"{preserved} approved left unchanged")
    if skipped_deleted:
        label += f", {skipped_deleted} deleted left deleted"
    actions.commit(
        db, actor=actor, project_id=project.id, kind="note_apply",
        label=label, before={}, after={},
    )
    return {"reclassified": reclassified, "preserved": preserved, "added": added, "removed": removed}
