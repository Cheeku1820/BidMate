"""Read endpoints: project list, project detail, the polling snapshot, and
totals -- plus the shared tenancy gates (`load_project`, `load_item`,
`load_sheet`, `not_found`) that this module and `mutations.py` both import.
Thin HTTP layer only -- `router -> service -> models`, per the design's
structural rules.

Task 13's mutation endpoints live in `mutations.py`, a separate module and
a separate `APIRouter`, both included by `main.py` -- this file was 104
lines after Task 11 and nine more endpoints plus their request/response
models would have pushed it well past this project's ~300-line guideline
(task-13-brief.md, correction 7). The tenancy gates stay here rather than
moving, since `collab/router.py` already imports `load_project` from this
module and there is no reason to disturb that import for a split that is
about mutations, not reads.
"""

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.takeoff import snapshot as snapshot_module
from app.takeoff.models import Item, Project, Sheet
from app.takeoff.projects import list_projects
from app.takeoff.schemas import ProjectDetailOut, ProjectOut, SnapshotOut, TotalsOut
from app.takeoff.snapshot import sheet_out
from app.takeoff.totals import approved_totals

router = APIRouter(prefix="/api", tags=["takeoff"])

# The single tenancy-refusal message, named once so main.py's
# CrossOrgActionError handler can answer with the identical body rather
# than a hand-copied string that could drift from this one.
PROJECT_NOT_FOUND_CODE = "project_not_found"
PROJECT_NOT_FOUND_MESSAGE = "That project is not available to your account."


def not_found() -> DomainError:
    """A fresh instance per raise.

    A module-level exception singleton re-raised on every rejection
    accumulates tracebacks -- each retained frame holds that frame's locals,
    which on an auth-adjacent path means retaining request data for the life
    of the process, and growing without bound under load.
    """
    return DomainError(PROJECT_NOT_FOUND_CODE, PROJECT_NOT_FOUND_MESSAGE, status=404)


def load_project(project_id: uuid.UUID, db: DbSession, user: User) -> Project:
    """The single tenancy gate for every project-scoped route.

    Answers the same 404 whether the project does not exist at all or
    exists in another org -- never a 403 -- so a cross-org probe cannot use
    the status code to confirm a project exists under an id it guessed.
    """
    project = db.get(Project, project_id)
    if project is None or project.org_id != user.org_id:
        raise not_found()
    return project


def load_item(item_id: uuid.UUID, db: DbSession, user: User) -> Item:
    """The tenancy gate for every item-scoped route.

    Deliberately returns the row unlocked -- `review._apply_approve()`
    and its siblings already re-read under `FOR UPDATE` with
    `populate_existing=True` before mutating anything, so the service
    owns locking (task-13-brief.md, correction 8: "do NOT fix load_item
    returning an unlocked row"). This function's only job is to prove the
    item exists and belongs to the caller's org before any service
    function is ever called, delegating the actual org check to
    `load_project` rather than duplicating it.
    """
    item = db.get(Item, item_id)
    if item is None:
        raise not_found()
    load_project(item.project_id, db, user)
    return item


def load_sheet(sheet_id: uuid.UUID, db: DbSession, user: User) -> Sheet:
    """The tenancy gate for the one sheet-scoped route (`POST
    /sheets/{id}/scale`). Same shape as `load_item` above, for the same
    reason: resolve the row, then defer to `load_project` for the org
    check, so there remains exactly one function that decides whether a
    project belongs to the caller.
    """
    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise not_found()
    load_project(sheet.project_id, db, user)
    return sheet


@router.get("/projects", response_model=list[ProjectOut])
def get_projects(
    includeArchived: bool = False,
    db: DbSession = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ProjectOut]:
    rows = list_projects(db, user.org_id, include_archived=includeArchived)
    return [ProjectOut.model_validate(row, from_attributes=True) for row in rows]


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
def get_project(
    project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)
) -> ProjectDetailOut:
    project = load_project(project_id, db, user)
    sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id).order_by(Sheet.sort_order)))
    return ProjectDetailOut(
        id=project.id,
        name=project.name,
        revision_set_label=project.revision_set_label,
        sheets=[sheet_out(s) for s in sheets],
    )


@router.get("/projects/{project_id}/snapshot", response_model=SnapshotOut)
def get_snapshot(
    project_id: uuid.UUID,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    project = load_project(project_id, db, user)
    # Computed exactly once, before anything else is read, and reused for
    # both the header and (via build()'s version= parameter) the response
    # body -- see snapshot.build()'s docstring for why computing it a
    # second time after the body's reads is a real bug under READ
    # COMMITTED, not just a redundant query.
    etag = snapshot_module.version(db, project.id)

    if request.headers.get("if-none-match") == etag:
        # RFC 7232: a 304 still carries the ETag it matched against, so
        # the client can keep using it on the next conditional request
        # without having to re-derive it from a 200 it never got.
        not_modified = Response(status_code=304)
        not_modified.headers["ETag"] = etag
        return not_modified

    response.headers["ETag"] = etag
    return snapshot_module.build(db, user, project.id, etag)


@router.get("/projects/{project_id}/totals", response_model=TotalsOut)
def get_totals(
    project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)
) -> TotalsOut:
    project = load_project(project_id, db, user)
    return TotalsOut(**asdict(approved_totals(db, project.id)))
