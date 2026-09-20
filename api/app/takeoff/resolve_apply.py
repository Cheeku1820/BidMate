"""Apply a proposal the estimator confirmed (say-what-it-is spec,
"Applying a proposal"). The one place a sentence becomes a write.

One `resolve` action for the whole cluster: every target's before/after
under ITEMS_SNAPSHOT_KEY (the bulk/scale list shape, each row carrying
its own id, plus that item's cleared warnings so undo can put them
back), and the library row it wrote under LIBRARY_KEY. Approval reuses
review._apply_approve so a Missing information target refuses the whole
apply with the same rule and copy the A key hits.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.takeoff import review
from app.takeoff.actions import commit, encode_snapshot
from app.takeoff.concurrency import check_version, lock_item
from app.takeoff.models import Action, Item, ReviewStatus, Sheet, SymbolResolution, Warning
from app.takeoff.snapshots import ITEMS_SNAPSHOT_KEY, _column_snapshot
from app.takeoff.totals import countable_items

LIBRARY_KEY = "library"
_REVERSIBLE_ITEM_FIELDS = ("name", "system", "category", "quantity", "status", "approved_by_user_id", "approved_at",
                           "rejected_by_user_id", "rejected_at", "reject_reason", "resolve_note")


@dataclass
class ApplyResult:
    action: Action | None
    also_matching_count: int = 0
    also_matching_sheets: list[str] = field(default_factory=list)


def _item_snapshot(db: DbSession, item: Item, *, warnings: bool) -> dict:
    snap = {"id": item.id, **{k: getattr(item, k) for k in _REVERSIBLE_ITEM_FIELDS}}
    if warnings:
        rows = db.scalars(select(Warning).where(Warning.item_id == item.id)).all()
        snap["warnings"] = [encode_snapshot(_column_snapshot(w)) for w in rows]
    return encode_snapshot(snap)


def _also_matching(db: DbSession, item: Item, target_ids: set[uuid.UUID]) -> tuple[int, list[str]]:
    if not item.source_tag:
        return 0, []
    rows = db.scalars(
        countable_items(item.project_id).where(Item.source_tag == item.source_tag, Item.id.not_in(target_ids))
    ).all()
    if not rows:
        return 0, []
    sheet_ids = {r.sheet_id for r in rows}
    numbers = sorted(s.number for s in db.scalars(select(Sheet).where(Sheet.id.in_(sheet_ids))))
    return len(rows), numbers


def apply_proposal(db: DbSession, actor: User, item: Item, proposal: dict, *, approve: bool, note: str) -> ApplyResult:
    intent = proposal["intent"]
    if intent not in ("reclassify", "exclude"):
        raise DomainError("proposal_not_applicable", "This proposal can't be applied — say what the item is first.")
    ids = sorted({uuid.UUID(str(i)) for i in proposal["target_item_ids"]} | {item.id})
    versions = {uuid.UUID(str(k)): int(v) for k, v in (proposal.get("versions") or {}).items()}

    locked = db.scalars(
        select(Item).where(Item.id.in_(ids), Item.project_id == item.project_id).order_by(Item.id)
        .with_for_update().execution_options(populate_existing=True)
    ).all()
    for row in locked:
        if row.id in versions:
            check_version(db, row, versions[row.id])

    before_rows, after_rows = [], []
    if intent == "exclude":
        reason = (proposal.get("reject_reason") or note or "").strip()
        if not reason:
            raise DomainError("reject_reason_required", "Say why this isn't counted — the reason stays with the item.")
        for row in locked:
            before_rows.append(_item_snapshot(db, row, warnings=False))
            review._apply_reject(db, row, actor, row.version)
            row.reject_reason = reason
            after_rows.append(_item_snapshot(db, row, warnings=False))
        count = len(locked)
        label = f"Rejected {count} — {reason}"
        action = commit(db, actor=actor, project_id=item.project_id, kind="resolve", label=label, item_id=item.id,
                        before={ITEMS_SNAPSHOT_KEY: before_rows}, after={ITEMS_SNAPSHOT_KEY: after_rows}, note=note)
        return ApplyResult(action=action)

    clears_warning = bool(proposal.get("schedule_match")) or bool(proposal.get("catalog_id"))
    for row in locked:
        before_rows.append(_item_snapshot(db, row, warnings=True))
        row.name = proposal["name"]
        row.system = proposal["system"]
        row.category = proposal["category"]
        if proposal.get("quantity") is not None:
            row.quantity = Decimal(str(proposal["quantity"]))
        row.resolve_note = note or None
        if clears_warning:
            for w in db.scalars(select(Warning).where(Warning.item_id == row.id)).all():
                db.delete(w)
            if row.status is ReviewStatus.ATTENTION:
                row.status = ReviewStatus.READY
        row.version += 1
        if approve:
            review._apply_approve(db, actor, row, None)   # raises on Missing information / rejected -- nothing committed
        db.flush()
        after_rows.append(_item_snapshot(db, row, warnings=True))

    lib_before, lib_after = None, None
    if item.source_tag:
        existing = db.scalars(select(SymbolResolution).where(
            SymbolResolution.project_id == item.project_id, SymbolResolution.tag == item.source_tag)).first()
        lib_before = encode_snapshot(_column_snapshot(existing)) if existing else None
        target = existing or SymbolResolution(org_id=actor.org_id, project_id=item.project_id, tag=item.source_tag)
        target.name, target.system, target.category = proposal["name"], proposal["system"], proposal["category"]
        target.catalog_id = proposal.get("catalog_id")
        target.resolved_by_user_id = actor.id
        db.add(target); db.flush(); db.refresh(target)
        lib_after = encode_snapshot(_column_snapshot(target))

    count = len(locked)
    label = (f"Approved {count} × {proposal['name']}" if approve else f"Read {item.source_tag or 'item'} as {proposal['name']}")
    action = commit(db, actor=actor, project_id=item.project_id, kind="resolve", label=label, item_id=item.id,
                    before={ITEMS_SNAPSHOT_KEY: before_rows, LIBRARY_KEY: lib_before},
                    after={ITEMS_SNAPSHOT_KEY: after_rows, LIBRARY_KEY: lib_after}, note=note)
    n, sheets = _also_matching(db, item, set(ids))
    return ApplyResult(action=action, also_matching_count=n, also_matching_sheets=sheets)
