"""estimate: regenerate one project's ROM assumptions.

The shortest body in the worker. It opens no file, makes no network
call, and holds no key -- which raises the fair question of why it is
here at all rather than inline in the API.

Two reasons. It is a batch walk over every item on a project, and a
request should not be waiting on one; and it runs when a run completes,
which is a fact only the queue knows. `app.main` may not import anything
that opens a file, and generation sits behind `app.estimate`, which
opens nothing -- so the rule that put this here is the queue, not the
sandbox.

The domain rule about what replacing a generated set means lives in
`app.estimate.write`, beside the generators. This module is the queue's
half: find the project, call it, mark the job done.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.estimate.write import regenerate
from app.jobs import queue
from app.takeoff.models import Job, Project
from app.worker.handlers import register


@register("estimate")
def run(db: Session, job: Job) -> None:
    project = db.get(Project, job.project_id)
    if project is None:
        # Deleted between queue and run. Nothing to generate, and the
        # queue must not spend three attempts discovering that -- the
        # same reading `sheet_job` gives a sheet that vanished.
        queue.mark_done(db, job)
        return

    regenerate(db, project)
    queue.mark_done(db, job)
