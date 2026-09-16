"""The job queue, in Postgres. Shared by the API (enqueue, status) and
the worker (claim, finish). Imports no engine and no router -- the API
imports this module, so anything it pulled in would boot in the API
process (test_worker_import_boundary.py guards it)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.jobs import copy
from app.jobs.schemas import MAX_ATTEMPTS, RETRY_BACKOFF_SECONDS, STALE_GRACE_SECONDS, timeout_for
from app.takeoff.models import Document, Job, Project, Sheet

_IN_FLIGHT = ("queued", "running")
_RUN_IN_FLIGHT = "This project's takeoff is already running. Wait for it to finish before starting another."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_read(db: Session, document: Document) -> Job:
    """One read per document at a time: a second call while one is queued
    or running returns that job rather than a duplicate. Either way the
    document reads as processing from here until the worker reports."""
    project = db.get(Project, document.project_id)
    existing = db.scalars(select(Job).where(
        Job.kind == "read", Job.document_id == document.id, Job.status.in_(_IN_FLIGHT))).first()
    document.status = "processing"
    document.error = ""
    if existing is not None:
        return existing
    job = Job(org_id=project.org_id, project_id=project.id, kind="read", document_id=document.id,
              max_attempts=MAX_ATTEMPTS)
    db.add(job)
    db.flush()
    return job


def in_flight_run(db: Session, project_id: uuid.UUID) -> Job | None:
    return db.scalars(select(Job).where(
        Job.kind == "classify", Job.project_id == project_id, Job.status.in_(_IN_FLIGHT))).first()


def enqueue_classify(db: Session, project: Project, requested_by: uuid.UUID) -> Job:
    """One run per project at a time. The check gives a good message; the
    partial unique index on the table is what makes it true under two
    concurrent requests, and its IntegrityError gets the same message."""
    if in_flight_run(db, project.id) is not None:
        raise DomainError("run_in_flight", _RUN_IN_FLIGHT, status=409)
    job = Job(org_id=project.org_id, project_id=project.id, kind="classify", run_id=uuid.uuid4(),
              requested_by=requested_by, max_attempts=MAX_ATTEMPTS)
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DomainError("run_in_flight", _RUN_IN_FLIGHT, status=409) from None
    return job


def enqueue_sheets(db: Session, classify_job: Job, sheets: list[tuple[Sheet, dict]]) -> list[Job]:
    """The classify job queues one sheet job per plan sheet, in its own
    run and attributed to the same person. A sheet job is not claimable
    until its classify job is done (see _READY)."""
    jobs = [Job(org_id=classify_job.org_id, project_id=classify_job.project_id, kind="sheet", sheet_id=s.id,
                run_id=classify_job.run_id, requested_by=classify_job.requested_by, payload=payload,
                max_attempts=MAX_ATTEMPTS)
            for s, payload in sheets]
    db.add_all(jobs)
    db.flush()
    return jobs


_READY = text(
    "status = 'queued' AND (not_before IS NULL OR not_before <= now()) AND "
    "(kind <> 'sheet' OR run_id IN (SELECT run_id FROM jobs WHERE kind = 'classify' AND status = 'done'))"
)


def claim_next(db: Session, worker_id: str) -> Job | None:
    """Oldest ready job, locked for this transaction. SKIP LOCKED is the
    whole coordinator: a second worker claiming at the same moment steps
    past the row this one holds. The caller commits to release it."""
    job = db.scalars(
        select(Job).where(_READY).order_by(Job.queued_at).with_for_update(skip_locked=True).limit(1)
    ).first()
    if job is None:
        return None
    job.status, job.locked_by, job.started_at, job.progress = "running", worker_id, _now(), ""
    job.attempts += 1
    db.flush()
    return job


def terminal_copy(job: Job, message: str) -> str:
    """The estimator copy a terminal failure lands with. A body that gave
    no reason of its own gets the generic one -- and on a sheet job that
    generic ("re-save the file") would be wrong, because the file was
    read fine; what failed was this sheet's takeoff, and the recovery is
    to start it again."""
    if job.kind == "sheet" and message in ("", copy.UNREADABLE):
        return copy.SHEET_FAILED
    return message or copy.UNREADABLE


def reclaim_stale(db: Session) -> int:
    """A job still `running` past its timeout plus the grace period was
    claimed by a worker that died with it. Back onto the queue with its
    attempts intact -- or, if it had already used them all, failed with
    the generic copy. Returns how many stale jobs were dealt with."""
    n = 0
    for job in db.scalars(select(Job).where(Job.status == "running")):
        limit = timedelta(seconds=timeout_for(job.kind) + STALE_GRACE_SECONDS)
        if job.started_at is None or _now() - job.started_at <= limit:
            continue
        if job.attempts >= job.max_attempts:
            mark_failed(db, job, terminal_copy(job, ""))
        else:
            job.status, job.locked_by = "queued", ""
        n += 1
    db.flush()
    return n


def mark_done(db: Session, job: Job) -> None:
    job.status, job.finished_at, job.error = "done", _now(), ""
    db.flush()


def mark_failed(db: Session, job: Job, error: str) -> None:
    """Terminal. A read's failure is the document's failure, in the same
    words; a sheet's failure may be the last thing its run was waiting
    on, so the run gets its chance to complete."""
    job.status, job.finished_at, job.error = "failed", _now(), error
    if job.kind == "read" and job.document_id:
        doc = db.get(Document, job.document_id)
        if doc is not None:
            doc.status, doc.error = "failed", error
    db.flush()
    if job.kind == "sheet" and job.run_id:
        complete_run_if_finished(db, job.run_id)


def requeue(db: Session, job: Job, error: str) -> None:
    """A transient failure: try again after the backoff, until the
    attempts run out, at which point the last transient reason is the
    terminal one."""
    if job.attempts >= job.max_attempts:
        mark_failed(db, job, error)
        return
    job.status, job.locked_by, job.error = "queued", "", error
    job.not_before = _now() + timedelta(seconds=RETRY_BACKOFF_SECONDS)
    db.flush()


def complete_run_if_finished(db: Session, run_id: uuid.UUID) -> bool:
    """True exactly once per run: the first caller to see every sheet job
    terminal. Serialised on the classify job's row lock so two sheets
    finishing together cannot both, or neither, complete the run. The
    classify job's `progress` records completion, so a later call sees
    it. The project's pricing basis and the run's `ingest` action are
    the sheet handler's to write on True; this only moves the stage."""
    classify = db.scalars(
        select(Job).where(Job.kind == "classify", Job.run_id == run_id).with_for_update()
    ).first()
    if classify is None or classify.progress == "complete":
        return False
    open_count = db.scalar(select(func.count()).select_from(Job).where(
        Job.run_id == run_id, Job.kind == "sheet", Job.status.in_(_IN_FLIGHT)))
    if open_count:
        return False
    classify.progress = "complete"
    project = db.get(Project, classify.project_id)
    project.stage = "review"
    db.flush()
    return True
