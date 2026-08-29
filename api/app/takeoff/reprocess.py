"""reprocess.py -- re-running the engine after a note, without
discarding a person's judgment.

Deliberately not ingest_service. Ingest replaces a takeoff wholesale and
refuses when approvals exist; this one preserves them and proceeds. Two
different intentions about what may be destroyed, so two entry points
rather than one with a flag deciding which.

The merge key is (sheet number, source_tag). Counting is deterministic
geometry -- the same drawing yields the same cluster tag on the same
sheet -- which is what makes recognising last run's item possible at all.
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
    # lock in one canonical-order statement before this function deletes
    # or inserts anything is what keeps a concurrent reprocess or bulk
    # approve on overlapping items from deadlocking against this one.
    existing = list(
        db.scalars(
            select(Item).where(Item.project_id == project.id).order_by(Item.id).with_for_update()
        )
    )
    number_by_sheet_id = {s.id: s.number for s in sheets.values()}
    by_key: dict[tuple[str, str], Item] = {
        _key(number_by_sheet_id.get(i.sheet_id, ""), i.source_tag): i for i in existing
    }

    preserved = reclassified = added = 0
    seen: set[tuple[str, str]] = set()

    for row in mapped.items:
        number = sheet_number_by_key.get(row["sheet_key"], "")
        key = _key(number, row["source_tag"])
        seen.add(key)
        current = by_key.get(key)

        # An estimator approved this. Their name is on it; a re-run does
        # not get to change it -- not the row, not its warnings, not
        # even a touch that would bump updated_at. Skip entirely.
        if current is not None and current.status is ReviewStatus.APPROVED:
            preserved += 1
            continue

        sheet = sheets[number]
        if current is not None:
            db.execute(delete(Warning).where(Warning.item_id == current.id))
            db.delete(current)
            db.flush()
            reclassified += 1
        else:
            added += 1

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

    # An un-approved item the engine no longer finds is gone. An approved
    # one stays: removing it would delete a decision silently. Anything
    # already handled above (present in `seen`, whether preserved or
    # replaced) is skipped here too, so an already-deleted row is never
    # deleted twice.
    removed = 0
    for key, item in by_key.items():
        if key in seen or item.status is ReviewStatus.APPROVED:
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
