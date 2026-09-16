"""python -m app.worker -- the only process that opens a PDF. Polls the
jobs table, runs each claimed job in a sandboxed child, and records the
outcome in the worker's own words."""
from __future__ import annotations

import logging
import os
import socket
import time
import uuid

from sqlalchemy import select

from app.jobs import copy, queue
from app.jobs.schemas import timeout_for
from app.takeoff.models import Job
from app.worker import sandbox
from app.worker.handlers import session_scope

logger = logging.getLogger("worker")
POLL_SECONDS = 2


def run_one(job_id: str, kind: str) -> sandbox.Outcome:
    if os.environ.get("WORKER_INLINE") == "1":   # tests: same process, same database session factory
        from app.worker import handlers
        try:
            handlers.run(kind, job_id)
            return ("ok", "")
        except sandbox.Transient as exc:
            return ("transient", str(exc))
        except sandbox.Terminal as exc:
            return ("terminal", str(exc))
        except Exception as exc:  # noqa: BLE001 -- mirrors the child: the class name is logged, never stored
            logger.exception("job body raised %s", type(exc).__name__)
            return ("terminal", copy.UNREADABLE)
    return sandbox.run_in_child("app.worker.handlers.run", (kind, job_id), timeout_for(kind))


def apply_outcome(db, job: Job, outcome: sandbox.Outcome) -> None:
    kind, message = outcome
    if kind == "ok":
        return
    if kind == "transient":
        completed_run = queue.requeue(db, job, message or copy.UNAVAILABLE)
    else:  # terminal or timeout
        completed_run = queue.mark_failed(db, job, queue.terminal_copy(job, message))
    if completed_run:
        _finish_run(db, job.run_id)


def _finish_run(db, run_id: uuid.UUID) -> None:
    """A failed sheet job was the last of its run to finish, so the run
    completed here rather than in a sheet handler -- and the project
    writes that handler would have made are owed here instead."""
    from app.takeoff.models import Project
    from app.worker.classify_job import _finish_project   # the queue cannot import the worker; this module can

    classify = db.scalars(select(Job).where(Job.kind == "classify", Job.run_id == run_id)).one()
    _finish_project(db, db.get(Project, classify.project_id), classify)


def tick(worker_id: str) -> bool:
    """One poll. Returns whether a job ran."""
    with session_scope() as db:
        for run_id in queue.reclaim_stale(db):   # a stale, exhausted last sheet ends its run here
            _finish_run(db, run_id)
        job = queue.claim_next(db, worker_id)
        db.commit()
        if job is None:
            return False
        job_id, kind = str(job.id), job.kind
    outcome = run_one(job_id, kind)
    with session_scope() as db:
        job = db.get(Job, uuid.UUID(job_id))
        if job is not None and job.status == "running":
            apply_outcome(db, job, outcome)
        db.commit()
    return True


def run_forever(worker_id: str, *, max_ticks: int | None = None) -> None:
    """The loop. A tick that raises -- the database restarting under
    reclaim_stale, a child that could not be spawned -- is logged and
    the worker polls again, the way a job that fails is recorded and
    the worker moves on. `max_ticks` exists so a test can run a bounded
    number of iterations."""
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        ticks += 1
        try:
            ran = tick(worker_id)
        except Exception:  # noqa: BLE001 -- the worker outlives any one tick
            logger.exception("tick failed; polling again in %ss", POLL_SECONDS)
            ran = False
        if not ran:
            time.sleep(POLL_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    logger.info("worker %s polling", worker_id)
    run_forever(worker_id)


if __name__ == "__main__":
    main()
