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
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff import actions
from app.takeoff.ingest import map_payload
from app.takeoff.models import Item, Project, ReviewStatus, Sheet, Warning, WarningReason


def _key(sheet_number: str, source_tag: str) -> tuple[str, str]:
    return (sheet_number or "", source_tag or "")


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
    # Bumped exactly like every other mutation that changes a row's
    # fields (review._apply_edit, undo_apply._apply_item_state) -- a
    # client holding a stale version must not write over this re-run.
    item.version += 1


def reprocess_takeoff(db: DbSession, *, actor: User, project: Project, payload: dict) -> dict:
    mapped = map_payload(payload)

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
    by_key: dict[tuple[str, str], list[Item]] = {}
    for i in existing:
        by_key.setdefault(_key(number_by_sheet_id.get(i.sheet_id, ""), i.source_tag), []).append(i)

    # Every approved item the run left alone -- whether it was matched
    # against an incoming row and skipped, or never matched at all --
    # counted here, once, so the number and the audit label always agree
    # with what actually happened.
    preserved = reclassified = added = 0

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
            _overwrite(current, sheet, row)
            _replace_warning(db, current.id, row["warning"])
            reclassified += 1
        else:
            item = Item(
                id=uuid.uuid4(), project_id=project.id, sheet_id=sheet.id,
                symbol=row["symbol"], name=row["name"], description=row["description"],
                system=row["system"], category=row["category"], quantity=row["quantity"],
                unit=row["unit"], status=ReviewStatus(row["status"]), x=row["x"], y=row["y"],
                placements=row["placements"], material_cost=row["material_cost"],
                labor_hours=row["labor_hours"], labor_cost=row["labor_cost"],
                total_cost=row["total_cost"], ai_confirmed=row["ai_confirmed"],
                source_tag=row["source_tag"],
            )
            db.add(item)
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
    actions.commit(
        db, actor=actor, project_id=project.id, kind="note_apply",
        label=(f"Applied notes and re-ran the takeoff: {reclassified} reclassified, "
               f"{preserved} approved left unchanged"),
        before={}, after={},
    )
    return {"reclassified": reclassified, "preserved": preserved, "added": added, "removed": removed}
