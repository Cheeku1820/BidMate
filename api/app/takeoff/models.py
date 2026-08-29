import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Identity, Index,
    Integer, Numeric, String, Text, func, text,
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


class WarningReason(enum.Enum):
    """What kind of evidence a warning is about -- a closed vocabulary,
    extendable only by a migration someone writes on purpose (see
    migrations/versions/0005_warning_reason.py and, for the third member
    below, 0007_warning_reason_schedule_conflict.py).

    This exists so a caller that only knows how to resolve one kind of
    evidence gap -- `scale.set_scale()` resolves a missing scale -- can
    tell its own warnings apart from every other reason an item might be
    Missing information, instead of treating every warning on a Missing
    information item as something it is entitled to clear. Confirming a
    scale must never delete the warning that explains an unclassified
    symbol, or one that explains a fixture disagreeing with its
    schedule; only a typed reason makes that distinction checkable in
    code rather than left to the coincidence of what the seed data
    contains.

    Members are named for the evidence that is missing or in conflict,
    not for the status it produces (`ReviewStatus.MISSING` already names
    that) -- "scale" reads as "this warning is about the sheet's scale,"
    which is what a reader actually needs to know at the call site.
    SCHEDULE_CONFLICT (added by 0007, ported from src/lib/data.js's
    "Fixture type conflicts with the schedule") is deliberately its own
    named value rather than a catch-all OTHER -- a junk-drawer member
    would stop this from being a closed vocabulary at all, and the
    pipeline that eventually emits real warnings (ROADMAP.md Track 2)
    has to classify every one it produces into an actual reason, not a
    default.
    """

    SCALE = "scale"
    LEGEND = "legend"
    SCHEDULE_CONFLICT = "schedule_conflict"


warning_reason_enum = Enum(
    WarningReason, name="warning_reason", values_callable=lambda e: [m.value for m in e]
)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    revision_set_label: Mapped[str] = mapped_column(String(300), default="")
    # Spec §5.1's dashboard columns. Text columns default to "" rather than
    # NULL so the table never has to render a null guard per cell; the two
    # genuinely optional facts (bid date, assigned estimator) stay nullable
    # because spec §6.1 makes both optional at creation and a fabricated
    # date would read as real.
    number: Mapped[str] = mapped_column(String(100), default="", server_default="")
    customer: Mapped[str] = mapped_column(String(300), default="", server_default="")
    location: Mapped[str] = mapped_column(String(300), default="", server_default="")
    bid_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The workflow position from spec §1's workspace list, collapsed to the
    # filter set spec §5.1 names. Not a status label -- the four review
    # labels describe items, this describes a project, and conflating them
    # is how a fifth status gets invented.
    stage: Mapped[str] = mapped_column(String(50), default="setup", server_default="setup")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # ROADMAP.md invariant 8 -- every mutation is attributable. The action
    # log is project-scoped, so a project's own creation has no project to
    # belong to; attribution lives on the row instead. Nullable because
    # rows predating this column have an owner nobody can now recover, and
    # an honest NULL beats an invented one.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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

    # Engine ingest metadata. The canvas addresses a page image by
    # (takeoff_id, page_index), and normalizes marker coordinates against
    # the page's own point dimensions -- a sheet's markers land wrongly if
    # normalized against another sheet's size.
    takeoff_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    page_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    width_pt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    height_pt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Set when a sheet could not be read. BUILD-STAGES: a sheet the engine
    # reads poorly is marked unreadable with a reason, never returned as a
    # short list of items -- silence reads as completeness.
    unreadable_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    ai_reading: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


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
    # Cost, carried for the spreadsheet and export. The engine stops at
    # total direct cost -- markup, overhead, and profit are an
    # estimator-owned layer and deliberately have no column here.
    material_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    labor_hours: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    # Every coordinate this cluster was counted at, in sheet space. `x`/`y`
    # is the marker; this is what the canvas draws when showing all
    # placements of one item.
    placements: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ai_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # The engine cluster tag this item came from ("A", "F2", "R"). The
    # merge key for an approval-preserving re-run: Counting is
    # deterministic geometry, so the same drawing yields the same tag on
    # the same sheet, which is what lets a re-run recognise the item it
    # produced last time instead of replacing it blindly.
    source_tag: Mapped[str] = mapped_column(String(50), default="", server_default="")
    # Optimistic-concurrency counter for the five single-item mutations
    # (task-13b-brief.md) -- deliberately not `updated_at` (below), which
    # is driven by `onupdate=func.now()` and therefore transaction-
    # constant (Task 5's finding: two writes in the same transaction
    # share a timestamp, so it cannot distinguish "before this write" from
    # "after"), and deliberately not SQLAlchemy's `version_id_col` (it
    # detects concurrent *database* races, but every write here already
    # re-reads under `FOR UPDATE` with `populate_existing=True`, so the
    # ORM would compare against the row it just refreshed and never see
    # what the *client* last saw). Checked and incremented by hand in
    # `app.takeoff.concurrency` and every module that mutates an `Item`.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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

    reason: Mapped[WarningReason] = mapped_column(warning_reason_enum, nullable=False)
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


class Note(Base):
    """Something the drawings do not say, recorded by a person.

    `usage` is the whole point: `reference` is documentation, `context`
    is handed to the engine as authoritative input on the next run. The
    estimator chooses; nothing infers it, because a note that silently
    moved the estimate would be a number nobody decided.

    `status` here is deliberately NOT the four review labels. Those
    describe an item's evidence; `confirmed`/`open` describes whether the
    estimator has settled the note. Sharing a vocabulary between the two
    is how a fifth review status gets invented by accident.
    """

    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(20), default="project", server_default="project")
    scope_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    rfi_needed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    usage: Mapped[str] = mapped_column(String(20), default="reference", server_default="reference")
    source_ref: Mapped[str] = mapped_column(String(300), default="", server_default="")
    obsolete_after_revision: Mapped[str] = mapped_column(String(100), default="", server_default="")
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
