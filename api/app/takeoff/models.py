import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, Enum, ForeignKey, Identity, Index, Integer,
    Numeric, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReviewStatus(enum.Enum):
    READY = "ready"
    ATTENTION = "attention"
    MISSING = "missing"
    APPROVED = "approved"


status_enum = Enum(ReviewStatus, name="review_status", values_callable=lambda e: [m.value for m in e])


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    revision_set_label: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sheet(Base):
    __tablename__ = "sheets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(300))
    discipline: Mapped[str] = mapped_column(String(100))
    revision: Mapped[str] = mapped_column(String(50))
    revision_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    scale: Mapped[str] = mapped_column(String(50))
    scale_options: Mapped[list] = mapped_column(JSONB, default=list)
    plan: Mapped[str] = mapped_column(String(50))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)

    symbol: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    system: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    unit: Mapped[str] = mapped_column(String(10))

    status: Mapped[ReviewStatus] = mapped_column(status_enum, default=ReviewStatus.READY, index=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    path: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Warning(Base):
    """Optional per item — but a row that exists is never partial."""

    __tablename__ = "warnings"
    __table_args__ = (
        CheckConstraint("(item_id is not null) or (sheet_id is not null)", name="warning_has_a_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), nullable=True, index=True)
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    found: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    fix: Mapped[str] = mapped_column(Text, nullable=False)
    where_: Mapped[str] = mapped_column("where", Text, nullable=False)


class Action(Base):
    """Append-only. Undo appends a compensating row; nothing is ever rewritten."""

    __tablename__ = "actions"
    __table_args__ = (
        # At most one action may claim to undo a given action, but most
        # actions undo nothing at all, so NULL has to stay unconstrained --
        # a plain unique index would forbid more than one NULL-free row,
        # which is not what "undoes nothing" means here.
        Index(
            "uq_actions_undoes_action_id", "undoes_action_id",
            unique=True, postgresql_where=text("undoes_action_id is not null"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # created_at is the *transaction* timestamp -- identical for every row
    # written in the same transaction (the compound scale-confirmation
    # flow writes more than one) -- so it cannot give a total order on its
    # own. seq is a real Postgres identity sequence: strictly increasing
    # per row regardless of transaction boundaries or clock resolution,
    # which is what a LIFO undo needs to find "the most recent action"
    # unambiguously.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(String(300))
    before: Mapped[dict] = mapped_column(JSONB, default=dict)
    after: Mapped[dict] = mapped_column(JSONB, default=dict)
    undoes_action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("actions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
