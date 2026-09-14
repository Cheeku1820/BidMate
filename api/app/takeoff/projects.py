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
from app.takeoff.models import Action, Item, Project, ReviewStatus
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
    def _count(*predicates):
        """One correlated scalar count per dashboard column.

        `.with_only_columns(func.count())` keeps the correlation to the
        outer `Project` row; wrapping the select in `.subquery()` and
        selecting from it does NOT -- a correlated select becomes a
        standalone derived table, and every project then reported the
        org-wide total. A brand-new project claiming the busiest one's
        item count is a wrong number on the dashboard, and it also
        silently disabled processing, since the processing screen reads
        `itemsTotal > 0` as "this project already has a takeoff".
        `.correlate(Project)` states the intent rather than leaving it to
        SQLAlchemy's inference.
        """
        return (
            countable_items(Project.id)
            .where(*predicates)
            .with_only_columns(func.count())
            .correlate(Project)
            .scalar_subquery()
        )

    items_total = _count()
    items_approved = _count(Item.status == ReviewStatus.APPROVED)
    warnings_open = _count(Item.status == ReviewStatus.ATTENTION)
    missing_info = _count(Item.status == ReviewStatus.MISSING)

    # Project.updated_at only advances when the `projects` row itself is
    # UPDATEd, and nothing in the review flow touches that row -- an
    # approval writes `items` and `actions`, not `projects`. Left as
    # Project.updated_at alone, the "Updated" column (and this query's
    # default sort) would freeze at creation time for the entire life of
    # a project under active review, which is a fabricated-freshness
    # claim on one side of the seam (final-review fix 2) to match the
    # equally dishonest `Date.now()`-at-read-time the seed store used to
    # make up on the other side.
    #
    # `actions` is append-only and already carries a timestamp on every
    # mutation (ROADMAP.md: "the action log ... becomes ... the audit
    # trail"), so the honest "last touched" moment is the later of the
    # project row's own updated_at and its most recent action -- a
    # correlated scalar subquery in the same shape as items_total etc.
    # above, so this composes with the existing structure rather than
    # adding a second kind of query to the function. Postgres's
    # GREATEST() ignores NULL arguments (a project with no actions yet)
    # and only returns NULL if every argument is NULL, so a brand-new
    # project with zero actions still reports its own updated_at rather
    # than NULL.
    last_action_at = (
        select(func.max(Action.created_at))
        .where(Action.project_id == Project.id)
        .scalar_subquery()
    )
    effective_updated_at = func.greatest(Project.updated_at, last_action_at).label("effective_updated_at")

    stmt = (
        select(
            Project,
            User.name.label("estimator_name"),
            items_total.label("items_total"),
            items_approved.label("items_approved"),
            warnings_open.label("warnings_open"),
            missing_info.label("missing_info"),
            effective_updated_at,
        )
        .outerjoin(User, User.id == Project.estimator_user_id)
        .where(Project.org_id == org_id)
        .order_by(effective_updated_at.desc())
    )
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))

    rows = []
    for project, estimator_name, total, approved, attention, missing, updated_at in db.execute(stmt):
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
                updated_at=updated_at,
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
    created_by_user_id: uuid.UUID,
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
    `create_project` cannot skip it by construction.

    `created_by_user_id` is keyword-only and has no default, so a caller
    cannot create an unattributed project by forgetting it -- ROADMAP.md
    invariant 8 enforced by the signature rather than by vigilance."""
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
        created_by_user_id=created_by_user_id,
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
