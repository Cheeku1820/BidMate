"""The projects list, assembled in one query.

Spec §5.1's dashboard renders review progress and outstanding warnings per
row. Those are aggregates over `items`, and fetching them per project is
the classic N+1 -- invisible against the one seeded project, quadratic
against a firm with fifty live bids. So the counts are computed with
correlated scalar subqueries in the same statement as the list.

The counts use `totals.countable_items()` -- the same exclusion predicate
`approved_totals()` groups over -- rather than a second copy of it. That
predicate already encodes "not rejected, not on a superseded sheet"
(ROADMAP.md invariant 2), and ROADMAP.md invariant 1 wants totals computed
in exactly one place; a hand-copied predicate here would be a second place
for that rule to drift out of sync with the drawer totals the moment
either one changes.
"""

from __future__ import annotations

import dataclasses
import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.identity.models import User
from app.takeoff.models import Item, Project, ReviewStatus
from app.takeoff.totals import countable_items


@dataclasses.dataclass(frozen=True)
class ProjectRow:
    id: uuid.UUID
    name: str
    number: str
    customer: str
    location: str
    bid_due_date: datetime.date | None
    stage: str
    revision_set_label: str
    archived_at: datetime.datetime | None
    updated_at: datetime.datetime
    estimator_name: str | None
    items_total: int
    items_approved: int
    warnings_open: int
    missing_info: int


def list_projects(
    db: Session, org_id: uuid.UUID, *, include_archived: bool = False
) -> list[ProjectRow]:
    # Correlated against the outer `Project` row rather than a fixed id --
    # `countable_items()` accepts a column expression exactly as it accepts
    # a concrete uuid.UUID, since `Item.project_id == project_id` is a
    # plain SQLAlchemy comparison either way. `.with_only_columns(Item.id)`
    # narrows the `select(Item)` it returns to the one column each scalar
    # subquery below actually needs, without touching the join or the
    # where clause that predicate owns.
    live = countable_items(Project.id).with_only_columns(Item.id)

    items_total = select(func.count()).select_from(live.subquery()).scalar_subquery()
    items_approved = (
        select(func.count())
        .select_from(live.where(Item.status == ReviewStatus.APPROVED).subquery())
        .scalar_subquery()
    )
    warnings_open = (
        select(func.count())
        .select_from(live.where(Item.status == ReviewStatus.ATTENTION).subquery())
        .scalar_subquery()
    )
    missing_info = (
        select(func.count())
        .select_from(live.where(Item.status == ReviewStatus.MISSING).subquery())
        .scalar_subquery()
    )

    stmt = (
        select(
            Project,
            User.name.label("estimator_name"),
            items_total.label("items_total"),
            items_approved.label("items_approved"),
            warnings_open.label("warnings_open"),
            missing_info.label("missing_info"),
        )
        .outerjoin(User, User.id == Project.estimator_user_id)
        .where(Project.org_id == org_id)
        .order_by(Project.updated_at.desc())
    )
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))

    rows = []
    for project, estimator_name, total, approved, attention, missing in db.execute(stmt):
        rows.append(
            ProjectRow(
                id=project.id,
                name=project.name,
                number=project.number,
                customer=project.customer,
                location=project.location,
                bid_due_date=project.bid_due_date,
                stage=project.stage,
                revision_set_label=project.revision_set_label,
                archived_at=project.archived_at,
                updated_at=project.updated_at,
                estimator_name=estimator_name,
                items_total=total,
                items_approved=approved,
                warnings_open=attention,
                missing_info=missing,
            )
        )
    return rows


def _estimator_not_found() -> DomainError:
    # 404, not 422: `users.id` is globally unique, so an FK alone would
    # happily accept another org's user, and a 422 that distinguished "no
    # such user" from "that user is not yours" would itself be a small
    # cross-tenant disclosure -- it would let a caller probe which ids
    # exist at all, just in a different org. Answering the same 404 either
    # way mirrors router.py's `not_found()` for projects, which exists for
    # the identical reason: never let a caller use the status code to
    # confirm something exists under an id it guessed.
    return DomainError(
        "estimator_not_found",
        "That estimator is not available to your account. Choose someone from your own organization.",
        status=404,
    )


def create_project(
    db: Session,
    org_id: uuid.UUID,
    *,
    name: str,
    location: str,
    number: str = "",
    customer: str = "",
    bid_due_date: datetime.date | None = None,
    estimator_user_id: uuid.UUID | None = None,
) -> Project:
    """Creates a project in the caller's org. Stage starts at 'setup'
    because no document has been uploaded yet -- spec §1's workspace order
    starts at Overview, and a project claiming to be in review before it
    has a sheet would misreport on the dashboard.

    `estimator_user_id`, when given, is checked against the caller's own
    org before the project is created -- not merely a foreign-key
    reference, since `users.id` is globally unique and a bare FK would
    accept any org's user. Left unchecked, a caller could assign another
    org's user as estimator and that user's name would then surface in
    `list_projects()`'s `outerjoin(User, ...)` above, a cross-tenant
    identity leak. Checked here, inside the service function, rather than
    only in the router handler, so a future second caller of
    `create_project` cannot skip it by construction."""
    if estimator_user_id is not None:
        estimator = db.get(User, estimator_user_id)
        if estimator is None or estimator.org_id != org_id:
            raise _estimator_not_found()

    project = Project(
        org_id=org_id,
        name=name,
        location=location,
        number=number,
        customer=customer,
        bid_due_date=bid_due_date,
        estimator_user_id=estimator_user_id,
        stage="setup",
    )
    db.add(project)
    db.flush()
    return project


def project_row(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> ProjectRow:
    """A single row in the same shape the list returns, so creation can
    respond with exactly what the dashboard will later render rather than a
    second, subtly different project shape."""
    for row in list_projects(db, org_id, include_archived=True):
        if row.id == project_id:
            return row
    raise LookupError(project_id)
