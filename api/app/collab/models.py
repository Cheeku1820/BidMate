"""`Presence` -- one row per (user, project), overwritten on every
heartbeat rather than appended to. This is deliberately not the action
log: a heartbeat carries no `before`/`after`, records no decision, and
would flood `actions` at the highest write frequency in the system for no
audit value -- see `app.collab.service.heartbeat`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Presence(Base):
    __tablename__ = "presence"

    # Composite primary key, not a surrogate id -- a reviewer has at most
    # one live presence row per project, ever, and the upsert in
    # `service.heartbeat` targets exactly this pair with
    # `on_conflict_do_update(index_elements=[user_id, project_id])`.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    # Nullable: a reviewer with the project open but no sheet selected
    # (just landed, or on a list view) is still present. No foreign key --
    # matches Action.item_id/sheet_id (app/takeoff/models.py): a deleted
    # sheet or item must not cascade into deleting or blocking a presence
    # row, and a stale reference here ages out of `active_presence` within
    # one window regardless.
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # timezone=True -> timestamptz. The naive `datetime.utcnow()` default
    # the plan's sketch used is wrong against a `timestamptz` column (see
    # task-12-brief.md item 3) -- `datetime.now(timezone.utc)` throughout,
    # matching the fix already applied to every earlier task that hit this.
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Supports both queries `active_presence`/`presence_signal` run: scoped
    # to one project, filtered to seen_at >= cutoff. project_id alone (the
    # second column of the primary key) is not enough -- Postgres cannot
    # use a composite index's second column without the first, so a query
    # that filters only on project_id gets no help from the primary key.
    __table_args__ = (Index("ix_presence_project_id_seen_at", "project_id", "seen_at"),)
