"""Start takeoff and the processing poll (spec §7). Both org-scoped
through `load_project` -- 404, never 403 -- and both registered in
test_tenancy.py's table. This module imports the queue and never the
worker: the API process must not boot the engine."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.jobs import copy, queue, status
from app.takeoff import actions
from app.takeoff.models import Document
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["processing"])


class TakeoffStartOut(BaseModel):
    run_id: uuid.UUID


@router.post("/projects/{project_id}/takeoff", status_code=202, response_model=TakeoffStartOut)
def start_takeoff(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> TakeoffStartOut:
    """One classify job, fresh run, attributed to the person who pressed
    Start. Refused while a run is in flight (`queue.enqueue_classify`),
    and refused outright when no drawing set has been read -- a run
    with nothing to count would only fail later, out of sight."""
    project = load_project(project_id, db, user)
    drawings = db.scalars(select(Document).where(Document.project_id == project.id, Document.doc_type == "Drawings")).all()
    # A set still being read would be silently left out of the run --
    # classify lists only `processed` drawings -- and its sheets would
    # then show as waiting under a run that has finished. Refused until
    # the read lands; screen D disables Start for the same reason.
    if any(d.status in ("uploaded", "processing") for d in drawings):
        raise DomainError("drawings_still_reading", copy.DRAWINGS_READING, status=409)
    if not any(d.status == "processed" for d in drawings):
        raise DomainError("no_readable_drawings", copy.NO_DRAWINGS, status=409)
    job = queue.enqueue_classify(db, project, user.id)
    actions.commit(db, actor=user, project_id=project.id, kind="takeoff_start", label="Started takeoff", before={}, after={})
    db.commit()
    return TakeoffStartOut(run_id=job.run_id)


@router.get("/projects/{project_id}/processing")
def get_processing(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> dict:
    return status.build_processing(db, load_project(project_id, db, user))
