"""sheet: price one sheet's clusters from the run's classification, crop
evidence, read with vision, merge. One transaction per sheet -- and the
last sheet of a run to finish is the one that completes it."""
from __future__ import annotations

import os
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import db as db_module
from app.engine import documents, sheet as sheet_mod
from app.engine.contracts import Classification, DeviceCluster, Placement
from app.jobs import queue
from app.takeoff import merge
from app.takeoff.ingest import map_payload
from app.takeoff.models import Classification as ClassificationRow, Document, Job, Project, Sheet
from app.worker.blobs import blob_to_tempfile
from app.worker.classify_job import _detected, _finish_project
from app.worker.handlers import register


def _classification(db: Session, job: Job, clusters: list[DeviceCluster]) -> Classification:
    """The run's classification, rebuilt from its row. On the model path
    the row carries the whole answer; on the deterministic path the
    answer is per cluster (`classification.classify_cluster`, which
    `sheet.rows_for` calls itself), so the record only names the tags
    this sheet may price -- its own."""
    row = db.scalars(select(ClassificationRow).where(ClassificationRow.run_id == job.run_id)).one()
    cls = Classification(specs_by_tag=row.specs_by_tag or {}, labor_rate=float(row.labor_rate),
                         material_factor=float(row.material_factor), source=row.source, location_note=row.location_note)
    if cls.source != "llm":
        cls.classified_tags = {c.tag for c in clusters}
    return cls


def _report_checking(db: Session, job: Job) -> None:
    """Screen E's "Checking schedules": written and committed through a
    session of its own, so the job's one transaction stays one. Skipped
    inline, where the only session is the test's. The handler session's
    copy of `progress` is expired so its final write below is a real
    change rather than "" compared against a stale ""."""
    if os.environ.get("WORKER_INLINE") == "1":
        return
    with db_module.SessionLocal() as s:
        s.execute(update(Job).where(Job.id == job.id).values(progress="checking"))
        s.commit()
    db.expire(job, ["progress"])


@register("sheet")
def run(db: Session, job: Job) -> None:
    sheet = db.get(Sheet, job.sheet_id)
    doc = db.get(Document, uuid.UUID(sheet.takeoff_id)) if sheet is not None and sheet.takeoff_id else None
    if sheet is None or doc is None:
        # Deleted between queue and run. Nothing to merge; the run still
        # has to be able to finish without this sheet.
        queue.mark_done(db, job)
        if queue.complete_run_if_finished(db, job.run_id):
            _finish_project(db, db.get(Project, job.project_id), _classify_job(db, job))
        return
    project = db.get(Project, job.project_id)
    all_sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id)))
    detected_all = [_detected(s) for s in all_sheets]
    detected = next(d for s, d in zip(all_sheets, detected_all) if s.id == sheet.id)
    clusters = [DeviceCluster(c["tag"], detected.page_index, [Placement(int(x), int(y)) for x, y in c["placements"]])
                for c in (job.payload or {}).get("clusters", [])]
    cls = _classification(db, job, clusters)

    _report_checking(db, job)
    with blob_to_tempfile(doc.storage_key, doc.filename) as path:
        result = sheet_mod.finish(path, detected, clusters, cls, detected_all)

    payload = {"takeoff_id": str(doc.id), "source": cls.source,
               "sheets": [{**documents.sheet_to_payload(detected), "ai_reading": result.ai_reading}],
               "items": [{**r, "sheet_id": str(detected.page_index)} for r in result.rows]}
    # The groundedness check sees every sheet on the project, not just
    # this one: a warning that sends the estimator to the schedule on
    # E0.1 is grounded, and a one-sheet payload alone would call it
    # fabricated and swap in the generic template.
    mapped = map_payload(payload, valid_sheet_numbers={s.number for s in all_sheets})
    merge.merge_sheet(db, project=project, sheet=sheet, rows=mapped.items, ai_reading=mapped.sheets[0]["ai_reading"])
    # "unchecked" surfaces as copy.SCHEDULES_UNCHECKED on screen E; a
    # checked sheet clears the "checking" the side session wrote.
    job.progress = "unchecked" if result.ai_reading is None and cls.source == "llm" else ""
    # What the project-level notes are folded from, once every sheet is
    # in. A new dict, not a mutation: JSONB changes are detected by
    # reassignment.
    job.payload = {**(job.payload or {}), "result": {"assembly_applied": result.assembly_applied,
                                                    "bare_names": sorted(result.bare_names)}}
    # Done before the completion check, so the last sibling to look
    # counts this job as finished.
    queue.mark_done(db, job)
    if queue.complete_run_if_finished(db, job.run_id):
        _finish_project(db, project, _classify_job(db, job))


def _classify_job(db: Session, job: Job) -> Job:
    """The run's classify job; it exists whenever the run just completed."""
    return db.scalars(select(Job).where(Job.kind == "classify", Job.run_id == job.run_id)).one()
