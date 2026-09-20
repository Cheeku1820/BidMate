"""price_sheet: read an uploaded supplier price sheet into a preview on
the job's payload. Nothing is applied here -- the estimator does that
from the preview (estimate-first-pricing §6). A refused sheet is a
completed job carrying the reason, not a failure."""
from __future__ import annotations

import os
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market.price_sheet import parse_price_sheet
from app.takeoff.models import Document, Item, Job, ProjectMaterialPrice
from app.takeoff.totals import countable_items
from app.worker import blobs
from app.worker.handlers import register

_DATE_RE = re.compile(r"(\d{4})[-_.](\d{2})[-_.](\d{2})")


def _supplier_and_date(filename: str) -> tuple[str, str | None]:
    stem = os.path.splitext(os.path.basename(filename))[0]
    m = _DATE_RE.search(stem)
    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    if re.search(r"price request", stem, re.IGNORECASE):
        # The platform's own download name (price_sheet_router.py's
        # get_price_request builds "<project name> - price request -
        # <date>.xlsx") uploaded back unmodified. There is no supplier
        # in that name -- what is left after stripping the phrase below
        # is the *project's* name, and guessing that as the supplier
        # would prefill the estimator's own project onto the quote.
        return "", date
    name = _DATE_RE.sub("", stem).replace("_", " ").replace("-", " ").strip(" .")
    name = re.sub(r"\b(price( request| sheet)?|quote|pricing)\b", "", name, flags=re.IGNORECASE).strip()
    return name[:200], date


@register("price_sheet")
def run(db: Session, job: Job) -> None:
    doc = db.get(Document, job.document_id)
    if doc is None:
        return
    store = blobs.get_blob_store()
    with blobs.storage_errors(doc.filename):
        data = store.open(doc.storage_key).read()
    parsed = parse_price_sheet(data, doc.filename)
    items = list(db.scalars(countable_items(job.project_id)))
    by_id = {str(i.id): i for i in items}
    by_name = {i.name: i for i in items}
    overrides = {r.item_id: r for r in db.scalars(select(ProjectMaterialPrice).where(ProjectMaterialPrice.item_id.in_([i.id for i in items])))}
    matched, unmatched, seen = [], [], set()
    for r in parsed.rows:
        item = by_id.get(r.row_key or "") or (by_name.get(r.item_name) if r.row_key is None else None)
        if item is None or str(item.id) in seen:
            unmatched.append({"item_name": r.item_name, "unit_price": str(r.unit_price) if r.unit_price is not None else None, "line": r.line})
            continue
        seen.add(str(item.id))
        if r.unit_price is None:
            continue   # listed under unpriced below
        cur = overrides.get(item.id)
        matched.append({"item_id": str(item.id), "item_name": item.name,
                        "current_unit_price": str(cur.price_override) if cur else None,
                        "current_source_label": {"project_price": "Project price", "allowance": "Allowance", "supplier_quote": "Supplier quote"}.get(cur.source) if cur else None,
                        "new_unit_price": str(r.unit_price), "part_no": r.part_no, "notes": r.notes, "line": r.line})
    priced_ids = {m["item_id"] for m in matched}
    unpriced = [{"item_id": str(i.id), "item_name": i.name} for i in items if str(i.id) not in priced_ids]
    supplier, date = _supplier_and_date(doc.filename)
    job.payload = {**(job.payload or {}), "preview": {
        "matched": matched, "unmatched": unmatched, "unpriced": unpriced, "refused": parsed.refused,
        "supplier_name": supplier, "quote_date": date}}
    db.flush()
