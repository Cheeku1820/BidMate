"""POST /items/{id}/resolve, behind the route: which items, which kind
of change, and what the sentence means (say-what-it-is spec, "The
resolve service"). Reads only. Nothing here calls commit()."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.engine import conversation
from app.engine import resolve as engine_resolve
from app.engine.catalog import CATALOG
from app.takeoff.models import Item, Sheet, SymbolResolution
from app.takeoff.totals import countable_items


def targets_for(db: DbSession, item: Item, *, cluster: bool = True) -> list[Item]:
    """The cluster the engine counted: countable items on the same sheet
    with the same source_tag. An untagged item is its own cluster.

    The anchor item is always included, even if `countable_items` would
    exclude it on its own (a rejected item is not "countable", but it is
    still the item the estimator opened `/resolve` from -- omitting it
    would mean editing this one item is impossible once it's rejected)."""
    if not cluster or not item.source_tag:
        return [item]
    rows = db.scalars(
        countable_items(item.project_id)
        .where(Item.sheet_id == item.sheet_id, Item.source_tag == item.source_tag)
        .order_by(Item.id)
    ).all()
    if not rows:
        return [item]
    if item.id not in {r.id for r in rows}:
        rows = [item, *rows]
    return rows


def _schedule_text(db: DbSession, project_id: uuid.UUID) -> str:
    """The schedule and legend text the read kept on each sheet
    (`Sheet.schedule_text`), concatenated and capped -- quoted data for
    the model, never instructions."""
    sheets = db.scalars(select(Sheet).where(Sheet.project_id == project_id).order_by(Sheet.sort_order)).all()
    return "\n".join(s.schedule_text for s in sheets if s.schedule_text)[:6000]


def resolve_for_item(db: DbSession, item: Item, text: str, *, cluster: bool = True) -> dict:
    targets = targets_for(db, item, cluster=cluster)
    ids = [str(t.id) for t in targets]
    versions = {t.id: t.version for t in targets}
    base = {"target_item_ids": [t.id for t in targets], "versions": versions, "reject_reason": None,
            "name": item.name, "system": item.system, "category": item.category, "unit": item.unit or "ea",
            "catalog_id": None, "schedule_match": None, "quantity": None}

    # How many placements this identity covers, not how many item rows
    # the cluster is stored as: the engine lands one row per (sheet,
    # source_tag) cluster with quantity = the placement count
    # (`engine/rows.py`, `merge.py`), so a tag counted 30 times is one
    # row with quantity 30 -- len(targets) would read "1" for it.
    count = int(sum(t.quantity for t in targets))

    routed = conversation.route(text, ids)
    if routed.intent == "exclude":
        return {**base, "intent": "exclude", "reject_reason": text.strip(), "source": "read",
                "summary": f"Reject {count} — {text.strip()}"}
    # An empty sentence, or one that reads as project context rather than
    # a device identity ("ceiling is 14 feet") -- context capture is out
    # of this spec's scope, so it is a couldn't-read result here rather
    # than something sent to the classification model as a device name.
    if not (text or "").strip() or routed.intent == "set_context":
        return {**base, "intent": "unknown", "source": "read", "summary": "Couldn't read that — try naming the device."}

    resolutions = [
        {"id": str(r.id), "tag": r.tag, "name": r.name, "system": r.system, "category": r.category}
        for r in db.scalars(select(SymbolResolution).where(SymbolResolution.project_id == item.project_id))
    ]
    cands = engine_resolve.candidates(text, CATALOG, resolutions, tag_hint=item.source_tag or None)
    sheet = db.get(Sheet, item.sheet_id)
    ctx = {"tag": item.source_tag, "count": count, "sheet": sheet.number if sheet else ""}
    proposal = engine_resolve.resolve(text, ctx, cands, _schedule_text(db, item.project_id))
    return {**base, **proposal, "intent": "reclassify"}
