"""Runs inside the child. Opens its own session, runs the handler for the
job's kind, marks the job done in the same transaction, commits. A
Transient/Terminal escapes to the sandbox after a rollback; the parent
applies the failure (queue.requeue / queue.mark_failed)."""
from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from typing import Callable

from sqlalchemy.orm import Session

from app import db as db_module
from app.jobs import queue
from app.takeoff.models import Job
from app.worker.sandbox import Terminal

HANDLERS: dict[str, Callable[[Session, Job], None]] = {}   # filled by read_job / classify_job / sheet_job / render_job


def register(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


def _load_handlers() -> None:
    # The four handler modules register themselves on import.
    for name in ("read_job", "classify_job", "sheet_job", "render_job"):
        __import__(f"app.worker.{name}")


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """A session for one unit of worker work. `SessionLocal` is looked up
    on the module at call time so a test can substitute its own session;
    in inline mode (WORKER_INLINE=1) that shared session is left open,
    because closing it would close the test's."""
    db = db_module.SessionLocal()
    try:
        yield db
    finally:
        if os.environ.get("WORKER_INLINE") != "1":
            db.close()


def run(kind: str, job_id: str) -> None:
    _load_handlers()
    with session_scope() as db:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None or job.status != "running":
            return
        handler = HANDLERS.get(kind)
        if handler is None:
            raise Terminal(f"No handler for {kind}")
        try:
            handler(db, job)
            db.refresh(job)
            if job.status == "running":     # a handler may have marked itself done (sheet_job does)
                queue.mark_done(db, job)
            db.commit()
        except Exception:
            db.rollback()
            raise
