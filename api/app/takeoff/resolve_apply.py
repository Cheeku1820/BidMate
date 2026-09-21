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

from app.engine.contracts import RESOLVE_CATEGORIES, RESOLVE_SYSTEMS
from app.errors import DomainError
from app.identity.models import User
from app.takeoff import review
from app.takeoff.actions import commit, encode_snapshot
from app.takeoff.concurrency import check_version
from app.takeoff.edit_validation import validate_edit
from app.takeoff.models import Action, Item, ReviewStatus, Sheet, SymbolResolution, Warning, WarningReason
from app.takeoff.resolve import targets_for
from app.takeoff.snapshots import ITEMS_SNAPSHOT_KEY, _column_snapshot
from app.takeoff.totals import countable_items

LIBRARY_KEY = "library"
_REVERSIBLE_ITEM_FIELDS = ("name", "system", "category", "quantity", "status", "approved_by_user_id", "approved_at",
                           "rejected_by_user_id", "rejected_at", "reject_reason", "resolve_note")

# The warnings a reclassify is entitled to clear, and when. A LEGEND
# warning ("symbol not in legend -- assign a classification") is
# answered by any reading: the estimator has just said what the symbol
# is, in their words, whether or not a key was set. A SCHEDULE_CONFLICT
# warning stands until the reading is actually matched to the schedule
# or the catalog. Never SCALE: naming an item says nothing about the
# sheet's scale, and deleting that warning would leave a Missing
# information row with nothing explaining why (WarningReason's docstring
# in models.py is about exactly this).
def _reasons_cleared_by(proposal: dict) -> tuple[WarningReason, ...]:
    if bool(proposal.get("schedule_match")) or bool(proposal.get("catalog_id")):
        return (WarningReason.LEGEND, WarningReason.SCHEDULE_CONFLICT)
    return (WarningReason.LEGEND,)


@dataclass
class ApplyResult:
    action: Action | None
    also_matching_count: int = 0
    also_matching_sheets: list[str] = field(default_factory=list)


def _warnings_with(db: DbSession, item_id: uuid.UUID, reasons: tuple[WarningReason, ...]) -> list[Warning]:
    return db.scalars(select(Warning).where(Warning.item_id == item_id, Warning.reason.in_(reasons))).all()


def _item_snapshot(db: DbSession, item: Item, *, clears: tuple[WarningReason, ...] = ()) -> dict:
    """`clears` names the warning reasons this apply deletes; only those
    are snapshotted, so undo puts back exactly what was cleared and redo
    (`undo_apply._apply_resolve`, which deletes whatever the
    before-snapshot lists) never removes a scale warning the apply
    itself left alone."""
    snap = {"id": item.id, **{k: getattr(item, k) for k in _REVERSIBLE_ITEM_FIELDS}}
    if clears:
        snap["warnings"] = [encode_snapshot(_column_snapshot(w)) for w in _warnings_with(db, item.id, clears)]
    return encode_snapshot(snap)


def _count(rows: list[Item]) -> str:
    """The device count the label names: the summed quantity across the
    cluster's rows (the same figure `resolve.resolve_for_item` reports as
    `count`, and the one the panel's statement shows), never the row
    count -- a tag counted 30 times is one row with quantity 30."""
    total = sum((Decimal(r.quantity) for r in rows), Decimal(0))
    return f"{total.normalize():f}"


def _validate_reclassify(proposal: dict) -> None:
    """The same rules `PATCH /items/{id}` applies to these fields
    (`edit_validation.validate_edit`), plus the closed sets the
    classifier draws `system` and `category` from. This route writes the
    same columns from a client-supplied body, so it refuses the same
    things with the same copy -- ROADMAP invariant 4, rules are
    server-authoritative."""
    if not str(proposal.get("name") or "").strip():
        raise DomainError("field_cannot_be_empty", "Name cannot be blank. Say what the item is, then apply it again.")
    changes = {"system": proposal.get("system"), "category": proposal.get("category")}
    if proposal.get("quantity") is not None:
        changes["quantity"] = proposal["quantity"]
    validate_edit(changes)
    if proposal["system"] not in RESOLVE_SYSTEMS:
        raise DomainError("invalid_system", f"System must be one of {', '.join(RESOLVE_SYSTEMS)}. Correct it and apply again.")
    if proposal["category"] not in RESOLVE_CATEGORIES:
        raise DomainError("invalid_category", f"Category must be one of {', '.join(RESOLVE_CATEGORIES)}. Correct it and apply again.")


def _also_matching(db: DbSession, item: Item, target_ids: set[uuid.UUID]) -> tuple[int, list[str]]:
    if not item.source_tag:
        return 0, []
    rows = db.scalars(
        countable_items(item.project_id).where(
            Item.source_tag == item.source_tag,
            Item.id.not_in(target_ids),
            Item.sheet_id != item.sheet_id,
        )
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
    if intent == "reclassify":
        _validate_reclassify(proposal)
    ids = sorted({uuid.UUID(str(i)) for i in proposal["target_item_ids"]} | {item.id})
    # The targets are the anchor's cluster as the server computes it now
    # (`targets_for`: same sheet, same tag, countable, the anchor always
    # included) -- a body naming anything else is refused before any row
    # is locked. The client only ever echoes what /resolve returned, so
    # an id outside that set is a stale or crafted request, not a
    # different reading.
    allowed = {t.id for t in targets_for(db, item)} | {item.id}
    if any(i not in allowed for i in ids):
        raise DomainError("targets_not_in_cluster", "Those items aren't the same symbol on this sheet — reload and try again.")
    versions = {uuid.UUID(str(k)): int(v) for k, v in (proposal.get("versions") or {}).items()}

    locked = db.scalars(
        select(Item).where(Item.id.in_(ids), Item.project_id == item.project_id).order_by(Item.id)
        .with_for_update().execution_options(populate_existing=True)
    ).all()
    # Every locked target must carry a version the client claims to have
    # seen -- an absent id is not "unchecked," it is refused with the same
    # stale-version copy check_version() already produces (no row's
    # version can ever equal -1, so this always raises for a missing id).
    for row in locked:
        check_version(db, row, versions.get(row.id, -1))

    before_rows, after_rows = [], []
    if intent == "exclude":
        reason = (proposal.get("reject_reason") or note or "").strip()
        if not reason:
            raise DomainError("reject_reason_required", "Say why this isn't counted — the reason stays with the item.")
        label = f"Rejected {_count(locked)} — {reason}"
        for row in locked:
            before_rows.append(_item_snapshot(db, row))
            review._apply_reject(db, row, actor, row.version)
            row.reject_reason = reason
            after_rows.append(_item_snapshot(db, row))
        action = commit(db, actor=actor, project_id=item.project_id, kind="resolve", label=label, item_id=item.id,
                        before={ITEMS_SNAPSHOT_KEY: before_rows}, after={ITEMS_SNAPSHOT_KEY: after_rows}, note=note)
        return ApplyResult(action=action)

    # A stated count is one number for one row. The cluster is every
    # same-tag row on the sheet, and writing "28" to each of two rows
    # would count 56 -- so with more than one row the count is refused
    # and the estimator corrects each row where its own count is edited.
    if proposal.get("quantity") is not None and len(locked) > 1:
        raise DomainError("quantity_needs_one_row",
                          f"This tag is counted as {len(locked)} rows on this sheet — correct the count on each row.")
    # Every target is checked before any is written, so a refusal
    # (a Missing information row in the cluster) leaves nothing behind.
    if approve:
        for row in locked:
            review.refuse_unless_approvable(row)

    clears = _reasons_cleared_by(proposal)
    for row in locked:
        before_rows.append(_item_snapshot(db, row, clears=clears))
        row.name = proposal["name"]
        row.system = proposal["system"]
        row.category = proposal["category"]
        if proposal.get("quantity") is not None:
            row.quantity = Decimal(str(proposal["quantity"]))
        row.resolve_note = note or None
        for w in _warnings_with(db, row.id, clears):
            db.delete(w)
        db.flush()
        # Needs attention was the classifier's verdict; once nothing on
        # the row still asks for a decision, it is Ready to review. A
        # schedule conflict that survives a typed reading keeps it.
        if row.status is ReviewStatus.ATTENTION and not db.scalars(select(Warning.id).where(Warning.item_id == row.id)).first():
            row.status = ReviewStatus.READY
        row.version += 1
        if approve:
            review._apply_approve(db, actor, row, None)   # re-checks under FOR UPDATE; nothing committed on a refusal
        db.flush()
        after_rows.append(_item_snapshot(db, row, clears=clears))

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

    label = (f"Approved {_count(locked)} × {proposal['name']}" if approve else f"Read {item.source_tag or 'item'} as {proposal['name']}")
    action = commit(db, actor=actor, project_id=item.project_id, kind="resolve", label=label, item_id=item.id,
                    before={ITEMS_SNAPSHOT_KEY: before_rows, LIBRARY_KEY: lib_before},
                    after={ITEMS_SNAPSHOT_KEY: after_rows, LIBRARY_KEY: lib_after}, note=note)
    n, sheets = _also_matching(db, item, set(ids))
    return ApplyResult(action=action, also_matching_count=n, also_matching_sheets=sheets)
