"""The plan's own rows: decisions a person made on derived lines, and
phases a person stated. Everything else on the plan screen is derived
on read from sheets, documents and scope statements (docs/specs/
project-plan-screen.md, "Why derive"), so nothing here mirrors a line.

Kept out of app/takeoff/models.py on purpose: nothing there needs a
foreign key to these, and this stream owns this package alone. The
status set is spelled inline for the check constraint, as
takeoff/models.py does for scope statements; app/plan/schemas.py
carries the same tuple for the wire."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
import app.takeoff.models  # noqa: E402, F401 -- notes, users, projects must be registered for the FKs below


class PlanDecision(Base):
    __tablename__ = "plan_decisions"
    __table_args__ = (
        UniqueConstraint("project_id", "entry_key", name="uq_plan_decisions_project_key"),
        CheckConstraint("status in ('found', 'confirmed', 'dismissed', 'answered')", name="ck_plan_decisions_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    entry_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="found", server_default="found")
    edited_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notes.id", ondelete="SET NULL"), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanPhase(Base):
    __tablename__ = "plan_phases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
