"""classify: count every readable plan sheet, classify once, queue one
sheet job per plan sheet. A sheet whose counting raises is marked
unreadable and the run continues -- a run is per project; a sheet fails
alone. Also home to `_finish_project`, the project-level writes made
once per run by whichever job turns out to be the last to finish."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engine import classification, counting, documents
from app.engine.estimate import _unmatched_note, _wiring_note
from app.identity.models import User
from app.jobs import copy, queue
from app.takeoff import actions
from app.takeoff import notes as notes_service
from app.takeoff.ingest import basis_note
from app.takeoff.models import Classification as ClassificationRow, Document, Item, Job, Project, ScopeStatement, Sheet
from app.worker.blobs import blob_to_tempfile
from app.worker.handlers import register
from app.worker.sandbox import Terminal

CONTEXT_CAP = 12000


def _detected(s: Sheet):
    """The Documents agent's record, rebuilt from the sheet row. The row's
    `page_index` is 1-based (the read job stores the engine payload's
    `page`); the engine opens pages 0-based, and a marker counted on the
    wrong page is the one visibly wrong marker that costs trust in every
    other, so the conversion happens here, at the store's edge, once."""
    return documents.sheet_from_row(s.page_index - 1, s.number, s.title, s.scale, s.width_pt, s.height_pt, s.region,
                                    s.kind, s.schedule_text, s.legend, s.unreadable_reason)


def _scope_block(db: Session, project_id) -> str:
    """Scope statements a person has not dismissed, in the document-text
    block -- untrusted, exactly where `context_text` goes (spec §4)."""
    rows = db.scalars(select(ScopeStatement).where(ScopeStatement.project_id == project_id,
                                                   ScopeStatement.status.in_(("found", "confirmed"))).order_by(ScopeStatement.kind))
    lines = [f"- [{r.kind}] {r.edited_text or r.text}" for r in rows]
    return "[scope statements from the project documents]\n" + "\n".join(lines) if lines else ""


def _classification_row(db: Session, project: Project, job: Job, cls) -> ClassificationRow:
    """Insert the run's row, or -- a reclaimed job re-run after an earlier
    attempt already committed one -- keep what exists. The unique index on
    `run_id` is what decides; the savepoint keeps the failed insert from
    poisoning the rest of the transaction."""
    row = ClassificationRow(project_id=project.id, run_id=job.run_id,
                            specs_by_tag=cls.specs_by_tag if cls.source == "llm" else {},
                            labor_rate=cls.labor_rate, material_factor=cls.material_factor, source=cls.source,
                            location_note=cls.location_note)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row
    except IntegrityError:   # the savepoint's rollback has already expunged `row`
        return db.scalars(select(ClassificationRow).where(ClassificationRow.run_id == job.run_id)).one()


@register("classify")
def run(db: Session, job: Job) -> None:
    project = db.get(Project, job.project_id)
    drawings = list(db.scalars(select(Document).where(Document.project_id == project.id, Document.doc_type == "Drawings",
                                                       Document.status == "processed")))
    if not drawings:
        raise Terminal(copy.NO_DRAWINGS)
    all_sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id).order_by(Sheet.sort_order)))
    by_doc: dict[str, list[Sheet]] = {}
    for s in all_sheets:
        by_doc.setdefault(s.takeoff_id, []).append(s)

    detected = {s.id: _detected(s) for s in all_sheets}
    clusters_by_sheet: dict = {}
    for doc in drawings:
        plans = [s for s in by_doc.get(str(doc.id), []) if s.kind == "plan" and not s.unreadable_reason]
        if not plans:
            continue
        with blob_to_tempfile(doc.storage_key, doc.filename) as path:
            for s in plans:
                try:
                    clusters_by_sheet[s.id] = counting.count_sheet(path, detected[s.id])
                except Exception:  # noqa: BLE001 -- one sheet, not the run
                    s.unreadable_reason = copy.SHEET_UNREADABLE
                    detected[s.id].unreadable_reason = copy.SHEET_UNREADABLE
    db.flush()

    clusters = [c for cs in clusters_by_sheet.values() for c in cs]
    schedule_text = "\n\n".join(s.schedule_text for s in all_sheets if s.schedule_text)
    others = db.scalars(select(Document).where(Document.project_id == project.id, Document.doc_type != "Drawings",
                                                Document.status == "processed", Document.context_text != ""))
    context_parts = [f"[{d.filename}]\n{d.context_text}" for d in others]
    scope = _scope_block(db, project.id)
    if scope:
        context_parts.append(scope)
    context = "\n\n".join(context_parts)[:CONTEXT_CAP]
    context_notes = [n for n in notes_service.list_notes(db, project.id) if n.usage == "context"]
    notes = [{"scope": n.scope, "title": n.title, "body": n.body, "source_ref": n.source_ref} for n in context_notes]

    cls = classification.classify_run(clusters, list(detected.values()), schedule_text, context, notes, project.location or "")
    # The deterministic classifier's answer is per cluster and not JSON;
    # a sheet job re-derives it from its own clusters, so the row carries
    # specs only on the model path.
    _classification_row(db, project, job, cls)
    notes_service.mark_applied(db, context_notes)
    project.stage = "processing"
    plan_sheets = [s for s in all_sheets if s.id in clusters_by_sheet]
    already_queued = db.scalar(select(func.count()).select_from(Job).where(Job.run_id == job.run_id, Job.kind == "sheet"))
    if not already_queued:   # a re-run of this job must not queue a second set
        queue.enqueue_sheets(db, job, [(s, {"clusters": [{"tag": c.tag, "placements": [[p.x, p.y] for p in c.placements]}
                                                         for c in clusters_by_sheet[s.id]]}) for s in plan_sheets])
    queue.mark_done(db, job)
    if queue.complete_run_if_finished(db, job.run_id):   # only with no sheet jobs: the run is over already
        _finish_project(db, project, job)
    db.flush()


def _finish_project(db: Session, project: Project, classify_job: Job) -> None:
    """The project-level writes, once per run, by whichever job completed
    it: the wiring and unmatched notes folded up from every sheet job's
    result, the pricing basis, and the `ingest` audit action attributed
    to the person who pressed Start. The caller is whoever got True from
    `queue.complete_run_if_finished` -- the last sheet handler, the
    classify handler on a run with no sheets, or the worker's failure
    path when the last sheet to finish failed."""
    sheet_jobs = list(db.scalars(select(Job).where(Job.run_id == classify_job.run_id, Job.kind == "sheet")))
    results = [(j.payload or {}).get("result") or {} for j in sheet_jobs]
    assembly_applied = any(r.get("assembly_applied") for r in results)
    bare_names = {name for r in results for name in r.get("bare_names", [])}
    row = db.scalars(select(ClassificationRow).where(ClassificationRow.run_id == classify_job.run_id)).first()
    if row is not None:
        row.wiring_note = _wiring_note(assembly_applied)
        row.unmatched_note = _unmatched_note(bare_names)
        project.pricing_source = row.source
        project.pricing_note = basis_note({"location_note": row.location_note, "wiring_note": row.wiring_note,
                                           "unmatched_note": row.unmatched_note})
    actor = db.get(User, classify_job.requested_by) if classify_job.requested_by else None
    n_items = db.scalar(select(func.count()).select_from(Item).where(Item.project_id == project.id))
    if actor is not None:
        actions.commit(db, actor=actor, project_id=project.id, kind="ingest",
                       label=f"Processed {len(sheet_jobs)} sheet(s) into {n_items} item(s)", before={}, after={})
    db.flush()
