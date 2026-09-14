"""ingest_service.py -- writing a processed takeoff into a project.

Replacement, not append: processing the same document set twice must
yield one takeoff rather than two overlaid, which on a bid would mean
every count silently doubled.

The whole write is one transaction. A half-written takeoff -- sheets
without their items, items without their warnings -- would render as a
complete but wrong review, which is the failure mode this product exists
to prevent.
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.takeoff import actions
from app.takeoff.evidence_images import upsert_evidence_image
from app.takeoff.ingest import map_payload
from app.takeoff.models import Item, Project, ReviewStatus, Sheet, Warning, WarningReason


def ingest_takeoff(
    db: DbSession,
    *,
    actor: User,
    project: Project,
    payload: dict,
    confirm_replace: bool = False,
) -> dict:
    """Replace `project`'s takeoff with the engine's output.

    Mapping and validation happen before a single row is deleted, so a
    payload carrying a partial warning leaves the existing takeoff
    exactly as it was.
    """
    mapped = map_payload(payload)

    # Replacing a takeoff destroys whatever it holds, and what it can hold
    # is estimator approvals -- the one act in this product that carries a
    # person's professional judgment, and the legal firewall the status
    # vocabulary rests on. Refuse by default and make the estimator say so.
    #
    # Server-authoritative on purpose: the client's confirmation dialog is
    # good feedback, but this refusal is what actually protects the data.
    if not confirm_replace:
        approved = db.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.project_id == project.id, Item.status == ReviewStatus.APPROVED)
        )
        if approved:
            raise DomainError(
                "approved_items_present",
                f"{approved} item(s) on this project are estimator approved. "
                "Processing again replaces the whole takeoff, and those approvals would be discarded.",
                status=409,
            )

    existing_sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id)))
    if existing_sheets:
        sheet_ids = [s.id for s in existing_sheets]
        item_ids = list(db.scalars(select(Item.id).where(Item.project_id == project.id)))
        if item_ids:
            db.execute(delete(Warning).where(Warning.item_id.in_(item_ids)))
        db.execute(delete(Warning).where(Warning.sheet_id.in_(sheet_ids)))
        db.execute(delete(Item).where(Item.project_id == project.id))
        db.execute(delete(Sheet).where(Sheet.project_id == project.id))

    sheet_ids_by_key: dict[str, uuid.UUID] = {}
    for row in mapped.sheets:
        sheet = Sheet(
            id=uuid.uuid4(), project_id=project.id, number=row["number"], title=row["title"],
            discipline=row["discipline"], revision=row["revision"], scale=row["scale"],
            scale_options=[], plan=row["plan"], sort_order=row["sort_order"],
            takeoff_id=row["takeoff_id"], page_index=row["page_index"],
            width_pt=row["width_pt"], height_pt=row["height_pt"],
            unreadable_reason=row["unreadable_reason"], ai_reading=row["ai_reading"],
        )
        db.add(sheet)
        sheet_ids_by_key[row["key"]] = sheet.id

    # This codebase deliberately declares no ORM relationship() between
    # Item and Sheet (every cross-row read goes through an explicit
    # select(), matching snapshot.py's convention) -- which means the
    # unit of work has no relationship graph to topologically sort
    # inserts by, and emits sheets and items in add() order rather than
    # FK order. Without this flush, an item's INSERT can be emitted
    # before its sheet's, raising a ForeignKeyViolation on a session
    # that has never seen this project's sheets before (confirmed by
    # reproducing it directly against Postgres).
    db.flush()

    for row in mapped.items:
        item = Item(
            id=uuid.uuid4(), project_id=project.id, sheet_id=sheet_ids_by_key[row["sheet_key"]],
            symbol=row["symbol"], name=row["name"], description=row["description"],
            system=row["system"], category=row["category"], quantity=row["quantity"],
            unit=row["unit"], status=ReviewStatus(row["status"]),
            x=row["x"], y=row["y"], placements=row["placements"],
            material_cost=row["material_cost"], labor_hours=row["labor_hours"],
            labor_cost=row["labor_cost"], total_cost=row["total_cost"],
            ai_confirmed=row["ai_confirmed"], source_tag=row["source_tag"],
            evidence=row["evidence"],
        )
        db.add(item)
        db.flush()
        upsert_evidence_image(db, item.id, row["evidence_png"])
        if row["warning"]:
            w = row["warning"]
            db.add(Warning(
                id=uuid.uuid4(), item_id=item.id, sheet_id=None,
                reason=WarningReason(w["reason"]), title=w["title"], found=w["found"],
                why=w["why"], fix=w["fix"], where_=w["where"],
            ))

    project.stage = "review"
    # Fall back to what the project already carries, not to None: a
    # payload that simply does not mention pricing has not repriced
    # anything, and clearing this flips every labor and material row
    # on the project to Missing information.
    project.pricing_source = payload.get("source", project.pricing_source)
    project.pricing_note = str(payload.get("location_note") or "")

    actions.commit(
        db, actor=actor, project_id=project.id, kind="ingest",
        label=f"Processed {len(mapped.sheets)} sheet(s) into {len(mapped.items)} item(s)",
        before={}, after={},
    )

    return {"sheets": len(mapped.sheets), "items": len(mapped.items)}
