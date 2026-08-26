"""`PUT /api/presence` -- the one collab endpoint this task adds. Thin
HTTP layer only, per the design's structural rule (`router -> service ->
models`; no service imports a router).
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.collab.service import heartbeat
from app.db import get_db
from app.identity.models import User
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["collab"])


class PresenceIn(BaseModel):
    project_id: uuid.UUID
    sheet_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None


@router.put("/presence", status_code=204)
def put_presence(body: PresenceIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> None:
    """A presence write is a write, not a read with side effects -- it
    gets the same tenancy gate `GET /snapshot` does, not a weaker one.
    `load_project` answers the identical 404 whether `project_id` belongs
    to another org or does not exist at all, so a heartbeat aimed at a
    project this user cannot see cannot be used to confirm the project
    exists.

    `db.commit()` here, in the router, after the service call returns --
    `get_db` (app/db.py) never commits on its own, by design, so every
    mutating route has to. This is the one mutating route Task 12 adds;
    Task 13 is about to add ten more (task-12-brief.md, "Committing"), and
    this is the convention it should repeat rather than inventing a
    second one: call the service function, then `db.commit()` in the
    handler, matching the only other mutating routes that exist today
    (`app.auth.router.login`/`logout`). The alternative -- committing
    inside the service function -- would make every service function
    responsible for transaction boundaries it currently has no reason to
    know about, and would make a service function's unit tests (which run
    directly against the `db` fixture's session, uncommitted, throughout
    this codebase -- see test_presence.py's non-HTTP tests) silently start
    committing state the rest of that test's transaction depends on
    staying uncommitted.
    """
    project = load_project(body.project_id, db, user)
    heartbeat(db, user, project.id, body.sheet_id, body.item_id)
    db.commit()
