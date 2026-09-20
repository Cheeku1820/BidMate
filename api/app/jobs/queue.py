"""The job queue, in Postgres. Shared by the API (enqueue, status) and
the worker (claim, finish). Imports no engine and no router -- the API
imports this module, so anything it pulled in would boot in the API
process (test_worker_import_boundary.py guards it)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.jobs import copy
from app.jobs.schemas import MAX_ATTEMPTS, RETRY_BACKOFF_SECONDS, STALE_GRACE_SECONDS, timeout_for
from app.takeoff.models import Document, Job, Project, Sheet

_IN_FLIGHT = ("queued", "running")
_RUN_IN_FLIGHT = copy.RUN_IN_FLIGHT


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
    """The run the project is in the middle of, as its classify job, or
    None. A run is in flight from the moment its classify job is queued
    until its last sheet job is terminal -- not just while classify
    itself runs. A second run started during the sheet phase would have
    two runs merging into the same sheets, and whichever finished last
    would own the pricing basis."""
    classify = db.scalars(select(Job).where(
        Job.kind == "classify", Job.project_id == project_id, Job.status.in_(_IN_FLIGHT))).first()
    if classify is not None:
        return classify
    open_sheet = db.scalars(select(Job).where(
        Job.kind == "sheet", Job.project_id == project_id, Job.status.in_(_IN_FLIGHT)).order_by(Job.queued_at)).first()
    if open_sheet is None:
        return None
    return db.scalars(select(Job).where(Job.kind == "classify", Job.run_id == open_sheet.run_id)).first()


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


def render_prefix(project: Project, sheet: Sheet, sha256: str) -> str:
    """Where a sheet's tiles live: content-addressed by the document's
    hash, so a re-upload with new bytes renders under a fresh prefix and
    a re-read of the same bytes finds its tiles already there."""
    return f"orgs/{project.org_id}/projects/{project.id}/sheets/{sheet.id}/{sha256[:16]}/"


def enqueue_render(db: Session, sheet: Sheet, prefix: str) -> Job | None:
    """One render per sheet per document version. Nothing to do when the
    sheet already carries this prefix, or a render is already queued."""
    if sheet.render_key == prefix and sheet.render_status == "rendered":
        return None
    if db.scalars(select(Job).where(
            Job.kind == "render", Job.sheet_id == sheet.id, Job.status.in_(_IN_FLIGHT))).first():
        return None
    project = db.get(Project, sheet.project_id)
    sheet.render_status, sheet.render_error = "pending", ""
    job = Job(org_id=project.org_id, project_id=project.id, kind="render", sheet_id=sheet.id,
              payload={"prefix": prefix}, max_attempts=MAX_ATTEMPTS)
    db.add(job)
    db.flush()
    return job


def enqueue_price_sheet(db: Session, document: Document, requested_by: uuid.UUID | None) -> Job:
    """Parse an uploaded price sheet into a preview. One per document;
    a second upload is a second document."""
    project = db.get(Project, document.project_id)
    job = Job(org_id=project.org_id, project_id=project.id, kind="price_sheet", document_id=document.id,
              requested_by=requested_by, max_attempts=MAX_ATTEMPTS)
    db.add(job)
    db.flush()
    return job


def enqueue_price(db: Session, project: Project, requested_by: uuid.UUID | None, run_id: uuid.UUID | None = None) -> Job | None:
    """One market-pricing job per project at a time (estimate-first-
    pricing §3). Queued by the run that just completed, by the
    estimator's Refresh, or by a ZIP being set. Returns None while one
    is already queued or running -- the caller's copy says so."""
    if db.scalars(select(Job).where(
            Job.kind == "price", Job.project_id == project.id, Job.status.in_(_IN_FLIGHT))).first():
        return None
    job = Job(org_id=project.org_id, project_id=project.id, kind="price", run_id=run_id,
              requested_by=requested_by, max_attempts=MAX_ATTEMPTS)
    db.add(job)
    db.flush()
    return job


_READY = text(
    "status = 'queued' AND (not_before IS NULL OR not_before <= now()) AND "
    "(kind <> 'sheet' OR run_id IN (SELECT run_id FROM jobs WHERE kind = 'classify' AND status = 'done'))"
)


# Claim order. A render is queued by the read, before anyone has pressed
# Start takeoff, so oldest-first alone parks every run behind the whole
# set's thumbnails -- two minutes of "Waiting" on screen E for twelve
# seconds of counting, on a fourteen-sheet set. A person is sitting on
# the read, the run, and its sheets; nobody is sitting on a thumbnail,
# and the canvas falls back to blank paper until it lands. Within a
# priority, oldest first, as before.
_CLAIM_PRIORITY = case((Job.kind == "render", 1), else_=0)


def claim_next(db: Session, worker_id: str) -> Job | None:
    """The next ready job -- takeoff work ahead of renders, oldest first
    within that -- locked for this transaction. SKIP LOCKED is the whole
    coordinator: a second worker claiming at the same moment steps past
    the row this one holds. The caller commits to release it."""
    job = db.scalars(
        select(Job).where(_READY).order_by(_CLAIM_PRIORITY, Job.queued_at).with_for_update(skip_locked=True).limit(1)
    ).first()
    if job is None:
        return None
    job.status, job.locked_by, job.started_at, job.progress = "running", worker_id, _now(), ""
    job.attempts += 1
    db.flush()
    return job


def terminal_copy(job: Job, message: str) -> str:
    """The estimator copy a terminal failure lands with. A body that gave
    no reason of its own gets the generic one -- and on a sheet, classify
    or render job that generic ("re-save the file") would be wrong,
    because the file was read fine; what failed was the takeoff (start
    it again) or the drawing behind it (the takeoff still counts it)."""
    if job.kind == "sheet" and message in ("", copy.UNREADABLE):
        return copy.SHEET_FAILED
    if job.kind == "classify" and message in ("", copy.UNREADABLE):
        return copy.RUN_FAILED
    if job.kind == "render" and message in ("", copy.UNREADABLE):
        return copy.RENDER_FAILED
    return message or copy.UNREADABLE


def reclaim_stale(db: Session) -> list[uuid.UUID]:
    """A job still `running` past its timeout plus the grace period was
    claimed by a worker that died with it. Back onto the queue with its
    attempts intact -- or, if it had already used them all, failed with
    the generic copy. Returns the ids of the runs those failures
    completed: a run that ends here still owes its project-level writes,
    and they live on the worker's side."""
    completed: list[uuid.UUID] = []
    for job in db.scalars(select(Job).where(Job.status == "running")):
        limit = timedelta(seconds=timeout_for(job.kind) + STALE_GRACE_SECONDS)
        if job.started_at is None or _now() - job.started_at <= limit:
            continue
        if job.attempts >= job.max_attempts:
            if mark_failed(db, job, terminal_copy(job, "")):
                completed.append(job.run_id)
        else:
            job.status, job.locked_by = "queued", ""
    db.flush()
    return completed


def mark_done(db: Session, job: Job) -> None:
    job.status, job.finished_at, job.error = "done", _now(), ""
    db.flush()


def mark_failed(db: Session, job: Job, error: str) -> bool:
    """Terminal. A read's failure is the document's failure, in the same
    words, and a render's failure is its sheet's; a sheet's failure may
    be the last thing its run was waiting on, so the run gets its chance
    to complete. Returns whether this
    failure completed a run -- the caller then owes the run its
    project-level writes, which live on the worker's side."""
    job.status, job.finished_at, job.error = "failed", _now(), error
    if job.kind == "read" and job.document_id:
        doc = db.get(Document, job.document_id)
        if doc is not None:
            doc.status, doc.error = "failed", error
    if job.kind == "render" and job.sheet_id:
        sheet = db.get(Sheet, job.sheet_id)
        if sheet is not None:
            sheet.render_status, sheet.render_error = "failed", error
    db.flush()
    if job.kind == "sheet" and job.run_id:
        return complete_run_if_finished(db, job.run_id)
    return False


def requeue(db: Session, job: Job, error: str) -> bool:
    """A transient failure: try again after the backoff, until the
    attempts run out, at which point the last transient reason is the
    terminal one. Returns whether that terminal failure completed a run,
    as `mark_failed` does."""
    if job.attempts >= job.max_attempts:
        return mark_failed(db, job, error)
    job.status, job.locked_by, job.error = "queued", "", error
    job.not_before = _now() + timedelta(seconds=RETRY_BACKOFF_SECONDS)
    db.flush()
    return False


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
