"""render: one sheet's tile pyramid into the blob store. The takeoff never
waits on this; a failure marks one sheet and says so."""
from __future__ import annotations

import os
import tempfile
import uuid

from sqlalchemy.orm import Session

from app.engine import tiles
from app.takeoff.models import Document, Job, Sheet
from app.worker import blobs
from app.worker.handlers import register


@register("render")
def run(db: Session, job: Job) -> None:
    sheet = db.get(Sheet, job.sheet_id)
    doc = db.get(Document, uuid.UUID(sheet.takeoff_id)) if sheet is not None and sheet.takeoff_id else None
    if sheet is None or doc is None:
        return   # deleted between queue and run; nothing to draw
    prefix = (job.payload or {}).get("prefix") or ""
    store = blobs.get_blob_store()   # looked up at call time, as blob_to_tempfile does, so a test can patch it
    with blobs.blob_to_tempfile(doc.storage_key, doc.filename) as path, tempfile.TemporaryDirectory() as out:
        ts = tiles.render_sheet(path, sheet.page_index - 1, out)   # the store is 1-based
        # Every tile lands before the row flips, so a reader never sees
        # a key whose pyramid is half there. Re-uploading the same keys
        # (a reclaimed job re-running) is harmless. The same classification
        # blob_to_tempfile's download uses applies here too -- a storage
        # blip on the way out is transient and retries like any other job,
        # not a terminal RENDER_FAILED.
        with blobs.storage_errors(doc.filename):
            for rel in ts.files:
                full = os.path.join(out, rel)
                with open(full, "rb") as fh:
                    store.put(prefix + rel, fh, "image/png", os.path.getsize(full))
    sheet.render_key, sheet.render_status, sheet.render_error = prefix, "rendered", ""
    sheet.max_zoom = ts.levels[-1].z
    db.flush()
