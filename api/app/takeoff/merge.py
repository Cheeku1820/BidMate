"""merge.py -- the one write path for engine output, per sheet.

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

Lifted from reprocess.py (Task 5) and narrowed to one sheet at a time:
`merge_sheet` is what a per-sheet worker (B2) will call once a sheet's
own rows are ready, rather than waiting for the whole project. Locking,
the deleted-key lookup, and the leftover sweep are all scoped to the one
sheet passed in, so a worker merging sheet E2.1 never locks, reads, or
deletes anything that belongs to E2.2.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, fields

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff import actions, undo
from app.takeoff.evidence_images import upsert_evidence_image
from app.takeoff.ingest import basis_note, map_payload
from app.takeoff.models import (
    Action,
    Item,
    Project,
    ProjectLaborLine,
    ProjectMaterialPrice,
    ReviewStatus,
    Sheet,
    Warning,
    WarningReason,
)


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


@dataclass
class MergeCounts:
    reclassified: int = 0
    preserved: int = 0
    added: int = 0
    removed: int = 0
    skipped_deleted: int = 0


def upsert_sheet_rows(db, project, mapped_sheets) -> dict[str, Sheet]:
    """Match by (takeoff_id, page_index) -- a sheet's stable identity now
    that takeoff_id is the document id -- and by number for rows with no
    takeoff id (the CLI path). Existing rows keep their id and their
    scale (a person confirms or calibrates that; the engine does not
    write over it); kind, title, dimensions and unreadable_reason are
    the engine's and are refreshed."""
    existing = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id)))
    by_page = {(s.takeoff_id, s.page_index): s for s in existing}
    # `by_number`, with no ordering and no revision filter, means two
    # sheets in a project sharing a number resolve to whichever this
    # dict comprehension happened to keep -- arbitrarily. That is latent
    # today because nothing writes `superseded_at`: a project holds one
    # revision of each sheet and numbers are in fact unique. It becomes
    # a real defect the moment revisions land (ROADMAP.md 2.2), so
    # whoever builds them has to key this on (number, revision) or
    # filter superseded sheets out here.
    by_number = {s.number: s for s in existing}
    out: dict[str, Sheet] = {}
    for row in mapped_sheets:
        sheet = by_page.get((row["takeoff_id"], row["page_index"])) if row["takeoff_id"] else by_number.get(row["number"])
        if sheet is None:
            sheet = Sheet(id=uuid.uuid4(), project_id=project.id, number=row["number"], title=row["title"],
                          discipline=row["discipline"], revision=row["revision"], scale=row["scale"], scale_options=[],
                          plan=row["plan"], sort_order=row["sort_order"], takeoff_id=row["takeoff_id"],
                          page_index=row["page_index"], width_pt=row["width_pt"], height_pt=row["height_pt"],
                          unreadable_reason=row["unreadable_reason"], ai_reading=row["ai_reading"], kind=row["kind"])
            db.add(sheet)
        else:
            sheet.number, sheet.title, sheet.kind = row["number"], row["title"], row["kind"]
            sheet.width_pt, sheet.height_pt = row["width_pt"], row["height_pt"]
            sheet.unreadable_reason, sheet.sort_order = row["unreadable_reason"], row["sort_order"]
        out[row["key"]] = sheet
    db.flush()
    return out


def merge_sheet(db, *, project, sheet, rows, ai_reading) -> MergeCounts:
    # Lock only this sheet's items, in ascending id order -- sufficient
    # on its own when this function runs once per transaction, which is
    # the worker's design point (one sheet merged per transaction). A
    # caller that merges more than one sheet in a single transaction
    # (merge_payload, below) must pre-lock the whole project's items in
    # ascending id order *before* calling this function for any sheet --
    # the convention actions.commit()'s docstring lays out for any
    # caller that touches more than one row of the same table in one
    # transaction (bulk.bulk_approve, scale.set_scale). Without that
    # pre-lock, issuing one lock statement per sheet in sheet order
    # rather than one statement in id order can deadlock against
    # bulk.bulk_approve's single ascending-id lock across the same
    # items.
    existing = list(
        db.scalars(
            select(Item).where(Item.sheet_id == sheet.id).order_by(Item.id).with_for_update()
        )
    )
    # Only this sheet's entry -- a deletion on another sheet must not be
    # consumed by this sheet's merge.
    deleted_by_key = _deliberately_deleted(db, project.id, {sheet.id: sheet.number})
    by_key: dict[tuple[str, str], list[Item]] = {}
    for i in existing:
        by_key.setdefault(_key(sheet.number, i.source_tag), []).append(i)
    # Un-approved before approved, then a stable tiebreak -- see
    # `_bucket_order()`. Sorted once per bucket, up front, so every
    # `pop(0)` below draws from a fixed, deterministic order rather than
    # whatever order the locking query happened to return.
    for bucket in by_key.values():
        bucket.sort(key=_bucket_order)

    counts = MergeCounts()

    for row in rows:
        key = _key(sheet.number, row["source_tag"])
        bucket = by_key.get(key)
        current = bucket.pop(0) if bucket else None

        # An estimator approved this. Their name is on it; a re-run does
        # not get to change it -- not the row, not its warnings, not
        # even a touch that would bump updated_at or version. The
        # incoming row that matched it is discarded rather than becoming
        # a duplicate, exactly as it would have with a single approved
        # match under the old one-item-per-key scheme.
        if current is not None and current.status is ReviewStatus.APPROVED:
            counts.preserved += 1
            continue

        if current is not None:
            # Asked *before* the overwrite, while the row still holds
            # what the estimator last saw -- `reclassified` counts rows
            # that changed, not rows that were touched.
            changed = _changes_visibly(current, sheet, row, _warning_title(db, current.id))
            old_name = current.name
            _overwrite(current, sheet, row)
            # A price and an hours figure belong to the item as it was
            # classified when someone priced it. ProjectLaborLine and
            # ProjectMaterialPrice are keyed on item_id, not on name, so a
            # re-run that turns a duplex receptacle into an isolated
            # ground receptacle would otherwise carry the old money along
            # under the new name. Drop them and let the row resolve again
            # -- an absent price is visible; a wrong one is not. Approved
            # items never reach this branch, so nobody's approved pricing
            # is touched.
            if current.name != old_name:
                db.execute(delete(ProjectLaborLine).where(ProjectLaborLine.item_id == current.id))
                db.execute(delete(ProjectMaterialPrice).where(ProjectMaterialPrice.item_id == current.id))
            _replace_warning(db, current.id, row["warning"])
            upsert_evidence_image(db, current.id, row["evidence_png"])
            if changed:
                counts.reclassified += 1
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
            counts.skipped_deleted += 1
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
            counts.added += 1

    # Whatever is left in each bucket is what the engine did not report
    # this run, whether because its key vanished entirely or because
    # there were more existing items sharing a key than incoming rows to
    # match them. An un-approved leftover is gone; an approved one stays
    # -- removing it would delete a decision silently.
    for bucket in by_key.values():
        for item in bucket:
            if item.status is ReviewStatus.APPROVED:
                counts.preserved += 1
                continue
            db.execute(delete(Warning).where(Warning.item_id == item.id))
            db.delete(item)
            counts.removed += 1

    sheet.ai_reading = ai_reading
    db.flush()
    return counts


def merge_payload(db, *, actor, project, payload) -> dict:
    """Whole-payload merge for the CLI and tests: upsert every sheet,
    merge each sheet's rows, set the pricing basis, one audit action.

    Locks every item in the project, in ascending id order, in one
    statement before merging any sheet. `merge_sheet`'s own per-sheet
    lock is sufficient when it runs alone (one sheet per transaction --
    the worker's design point), but this function merges every sheet in
    one transaction, and issuing one lock statement per sheet in sheet
    order rather than one statement in id order can deadlock against
    `bulk.bulk_approve`'s single ascending-id lock across the same
    items. Taking the whole-project lock up front, in the canonical
    order `actions.commit()`'s docstring requires of any caller that
    locks more than one row of a table in one transaction, is what
    keeps this function safe to call as a caller of `merge_sheet` even
    though `merge_sheet` re-locks (a no-op within the same transaction)
    the subset it needs.
    """
    mapped = map_payload(payload)
    db.scalars(
        select(Item).where(Item.project_id == project.id).order_by(Item.id).with_for_update()
    ).all()
    sheets = upsert_sheet_rows(db, project, mapped.sheets)
    total = MergeCounts()
    for key, sheet in sheets.items():
        rows = [r for r in mapped.items if r["sheet_key"] == key]
        raw = next(s for s in mapped.sheets if s["key"] == key)
        c = merge_sheet(db, project=project, sheet=sheet, rows=rows, ai_reading=raw["ai_reading"])
        for f in fields(MergeCounts):
            setattr(total, f.name, getattr(total, f.name) + getattr(c, f.name))
    # Fall back to what the project already carries, not to None: a
    # payload that simply does not mention pricing has not repriced
    # anything, and clearing this flips every labor and material row
    # on the project to Missing information.
    project.pricing_source = payload.get("source", project.pricing_source)
    project.pricing_note = basis_note(payload)
    label = (f"Applied notes and re-ran the takeoff: {total.reclassified} reclassified, "
             f"{total.preserved} approved left unchanged")
    if total.skipped_deleted:
        label += f", {total.skipped_deleted} deleted left deleted"
    actions.commit(db, actor=actor, project_id=project.id, kind="note_apply", label=label, before={}, after={})
    return asdict(total)
