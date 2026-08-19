"""The projects list, assembled in one query.

Spec §5.1's dashboard renders review progress and outstanding warnings per
row. Those are aggregates over `items`, and fetching them per project is
the classic N+1 -- invisible against the one seeded project, quadratic
against a firm with fifty live bids. So the counts are computed with
correlated scalar subqueries in the same statement as the list.

The counts deliberately mirror the item-level rules rather than
reimplementing them: `items_approved` counts `status = ReviewStatus.APPROVED`,
the same predicate totals.py's `_countable` uses, and a rejected item or one
on a superseded sheet is excluded everywhere -- ROADMAP.md's "superseded
sheets never contribute to totals" invariant applies to this dashboard
count exactly as it applies to the totals query, so it is enforced inside
`_live_items` rather than left to a caller to remember.
"""

from __future__ import annotations

import dataclasses
import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.identity.models import User
from app.takeoff.models import Item, Project, ReviewStatus, Sheet


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


def _live_items(project_id_column):
    """Items that belong to a project's current takeoff: not rejected, and
    not on a superseded sheet. ROADMAP.md invariant 2 -- superseded sheets
    never contribute -- applies to these counts exactly as it does to
    totals, and enforcing it here rather than in the caller is the whole
    reason that invariant is written down."""
    return (
        select(Item.id)
        .join(Sheet, Sheet.id == Item.sheet_id)
        .where(
            Item.project_id == project_id_column,
            Sheet.superseded_at.is_(None),
            Item.rejected_at.is_(None),
        )
    )


def list_projects(
    db: Session, org_id: uuid.UUID, *, include_archived: bool = False
) -> list[ProjectRow]:
    live = _live_items(Project.id)

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
