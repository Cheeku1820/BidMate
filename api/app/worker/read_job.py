"""read: open one stored document once. Drawings -> sheet rows (upserted
by (document, page)); everything else -> context text. Both -> scope
statements, re-finding only the undecided ones."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.engine import documents
from app.jobs import copy, queue
from app.takeoff import merge
from app.takeoff.ingest import map_payload
from app.takeoff.models import Document, Job, Project, ScopeStatement, Sheet
from app.worker.blobs import blob_to_tempfile
from app.worker.handlers import register
from app.worker.sandbox import Terminal

CONTEXT_CAP = documents.SCOPE_MAX_CHARS


@register("read")
def run(db: Session, job: Job) -> None:
    doc = db.get(Document, job.document_id)
    if doc is None:
        return
    project = db.get(Project, doc.project_id)
    with blob_to_tempfile(doc.storage_key, doc.filename) as path:
        try:
            reading = documents.read(path, doc.doc_type)
        except documents.EncryptedDocument:
            raise Terminal(copy.ENCRYPTED) from None
        except documents.UnreadableDocument:
            raise Terminal(copy.UNREADABLE) from None

    if doc.doc_type == "Drawings":
        mapped = map_payload({"takeoff_id": str(doc.id), "sheets": [documents.sheet_to_payload(s) for s in reading.sheets]})
        kept = merge.upsert_sheet_rows(db, project, mapped.sheets)
        for row, detected in zip(mapped.sheets, reading.sheets):
            sheet = kept[row["key"]]
            sheet.schedule_text = detected.schedule_text
            sheet.region = list(detected.region)
            sheet.legend = [vars(e) for e in detected.legend]
        # The drawing behind the markers, cut and stored by its own job
        # so the read never waits on it. Keyed by the file's hash: the
        # same bytes read again queue nothing.
        for sheet in kept.values():
            queue.enqueue_render(db, sheet, queue.render_prefix(project, sheet, doc.sha256))
        _drop_vanished_sheets(db, doc, {s.id for s in kept.values()})
    else:
        doc.context_text = reading.context_text[:CONTEXT_CAP]
        # A file retyped away from Drawings stops contributing sheets:
        # every page it once reported is a vanished page now.
        _drop_vanished_sheets(db, doc, set())

    _replace_found_scope(db, doc, project, reading.scope, run_id=job.id)
    doc.page_count = reading.page_count
    doc.status, doc.error = "processed", ""
    db.flush()


def _drop_vanished_sheets(db, doc, keep_ids):
    """A sheet whose page this run no longer reports -- the file was
    re-uploaded with fewer pages, or a page stopped reading as a plan.
    The rule (un-approved items go, an approved item keeps its sheet,
    marked PAGE_GONE) is `merge.drop_sheets`', shared with the API's
    delete-document path so there is one implementation of it."""
    gone = [s.id for s in db.scalars(select(Sheet).where(Sheet.takeoff_id == str(doc.id))) if s.id not in keep_ids]
    merge.drop_sheets(db, gone)


def _replace_found_scope(db, doc, project, statements, run_id):
    """Drop the still-undecided ("found") statements from a prior run and
    re-insert whatever the engine found this time -- except a statement a
    person already decided (dismissed or confirmed) on a prior run. That
    decision is keyed on (kind, quote): the verbatim passage is the
    evidence, and a re-read that finds the same passage again must not
    raise a second, duplicate question about something already settled."""
    decided = {
        (row.kind, row.quote)
        for row in db.scalars(
            select(ScopeStatement).where(ScopeStatement.document_id == doc.id, ScopeStatement.status != "found")
        )
    }
    db.execute(delete(ScopeStatement).where(ScopeStatement.document_id == doc.id, ScopeStatement.status == "found"))
    for s in statements:
        quote = s.quote[:600]
        if (s.kind, quote) in decided:
            continue
        db.add(ScopeStatement(org_id=project.org_id, project_id=doc.project_id, document_id=doc.id,
                              page_index=s.page_index, kind=s.kind, text=s.text[:500], quote=quote,
                              status="found", run_id=run_id))
    db.flush()
