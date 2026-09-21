import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Identity, Index,
    Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
# Several tables below hold foreign keys to users.id and orgs.id. Those
# targets must be registered on Base.metadata wherever these models are
# -- a process that imports only this module (the worker, alembic, a
# script) otherwise raises NoReferencedTableError on its first flush.
# A model module, not a router, so no import boundary moves.
import app.identity.models  # noqa: E402, F401
# The wire shape's closed set, reused as the column's check constraint --
# one definition, enforced in both places. app.documents.schemas imports
# nothing from app, so this direction adds no cycle.
from app.documents.schemas import DOC_STATUSES
from app.jobs.schemas import JOB_KINDS, JOB_STATUSES, RENDER_STATUSES
from app.scope.schemas import SCOPE_KINDS, SCOPE_STATUSES


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
    # Which mechanism actually priced this takeoff -- "llm" or
    # "deterministic" -- read from the engine payload's own `source`
    # field at ingest/reprocess time. Labor and Material Pricing's
    # precedence resolution treats a project's engine-computed
    # material_cost/labor_hours as a trustworthy baseline ONLY when this
    # is "llm": the deterministic fallback's numbers (catalog.py's fixed
    # placeholder hours, regions.py's ~15-entry hardcoded rate table) are
    # rough guesses this product cannot present as real pricing to a firm
    # bidding real work. NULL (a project ingested before this column
    # existed) is treated identically to "deterministic" everywhere.
    pricing_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pricing_note: Mapped[str] = mapped_column(Text, default="", server_default="")


class Sheet(Base):
    __tablename__ = "sheets"
    __table_args__ = (
        CheckConstraint("render_status in ('" + "', '".join(RENDER_STATUSES) + "')", name="ck_sheets_render_status"),
    )

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
    # normalized against another sheet's size. `page_index` is the
    # 1-based page number, the engine payload's `page` (`map_payload`
    # stores it as is; existing rows, evidence crops and the read job's
    # upsert key all depend on that). The engine itself opens pages
    # 0-based; the worker converts once, in classify_job._detected.
    takeoff_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    page_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    width_pt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    height_pt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Set when a sheet could not be read. BUILD-STAGES: a sheet the engine
    # reads poorly is marked unreadable with a reason, never returned as a
    # short list of items -- silence reads as completeness.
    unreadable_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    ai_reading: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # What the sheet is (sheet_kind.KINDS): plan, schedule, legend,
    # diagram, other. A schedule is read and shown; only a plan carries
    # counted items. Its own axis -- never one of the four review labels.
    kind: Mapped[str] = mapped_column(String(20), default="plan", server_default="plan")

    # Written by the read job so classify and sheet jobs never re-open
    # the file for them: the schedule/legend text, the drawing region
    # counting runs within ([x0, y0, x1, y1] in page points), and the
    # parsed legend rows (LegendEntry dicts).
    schedule_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    region: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    legend: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # The rendered page behind the markers (B3). `render_status` is a sheet
    # property on its own axis, like `kind` -- never a review label.
    render_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    render_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    render_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    max_zoom: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Document(Base):
    """An uploaded file, as stored. The API streams and hashes it; it
    never opens it -- page count, dimensions and whether it is even a
    readable PDF are the worker's to find out (B2). `status` and `error`
    are where the worker reports back. docs/specs/documents-stored.md."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_document_project_sha256"),
        # `status` is a closed set of four, and the database is what
        # closes it. B1 only ever writes 'uploaded'; B2's worker writes
        # the other three, and without this a typo there ('error' for
        # 'failed', say) would persist a status no screen knows how to
        # render, silently. Mirrors app.documents.schemas.DOC_STATUSES,
        # which is imported rather than retyped so the two cannot drift,
        # and migration 0020's ck_documents_status.
        CheckConstraint(
            "status in ('" + "', '".join(DOC_STATUSES) + "')",
            name="ck_documents_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(20))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="uploaded", server_default="uploaded")
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_text: Mapped[str] = mapped_column(Text, default="", server_default="")


class Job(Base):
    """One unit of worker work. The queue is this table (spec §2.1): the
    worker claims with FOR UPDATE SKIP LOCKED, so two workers share it
    with no coordinator. The two partial unique indexes are what make
    "one read per document, one run per project at a time" true -- the
    route checks first for a good message, the database decides."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("kind in ('" + "', '".join(JOB_KINDS) + "')", name="ck_jobs_kind"),
        CheckConstraint("status in ('" + "', '".join(JOB_STATUSES) + "')", name="ck_jobs_status"),
        Index("ix_jobs_poll", "status", "kind", "queued_at"),
        Index("uq_jobs_read_in_flight", "document_id", unique=True,
              postgresql_where=text("kind = 'read' AND status IN ('queued', 'running')")),
        Index("uq_jobs_classify_in_flight", "project_id", unique=True,
              postgresql_where=text("kind = 'classify' AND status IN ('queued', 'running')")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    progress: Mapped[str] = mapped_column(String(20), default="", server_default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    locked_by: Mapped[str] = mapped_column(String(100), default="", server_default="")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Classification(Base):
    """One run's classification: the tag -> spec map and the pricing
    basis, written once by the classify job and read by every sheet job
    of that run (spec §2.4). One per project run, so the labor rate and
    material factor are one number per project."""

    __tablename__ = "classifications"
    __table_args__ = (UniqueConstraint("run_id", name="uq_classifications_run"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    specs_by_tag: Mapped[dict] = mapped_column(JSONB, default=dict)
    labor_rate: Mapped[float] = mapped_column(Numeric(10, 2))
    material_factor: Mapped[float] = mapped_column(Numeric(6, 3))
    source: Mapped[str] = mapped_column(String(20))
    location_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    wiring_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    unmatched_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScopeStatement(Base):
    """What the documents say the electrical work is -- found by the
    worker, settled by a person (spec §2.5). `status` is deliberately
    not the four review labels: those describe an item's evidence; this
    describes whether a person has settled a statement, exactly as a
    note's confirmed/open does."""

    __tablename__ = "scope_statements"
    __table_args__ = (
        CheckConstraint("kind in ('" + "', '".join(SCOPE_KINDS) + "')", name="ck_scope_kind"),
        CheckConstraint("status in ('" + "', '".join(SCOPE_STATUSES) + "')", name="ck_scope_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(String(500))
    quote: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="found", server_default="found")
    edited_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    # The estimator's own words at the moment of decision (say-what-it-is
    # spec). A rejection's reason and a reclassification's note live on
    # the item so the spreadsheet and the export can show them; the
    # action log carries them too, as provenance.
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolve_note: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class ItemEvidenceImage(Base):
    """A crop of the source drawing around one item's counted
    location(s) -- what "View evidence" actually shows. Deliberately its
    own table, not a column on Item: `snapshots._column_snapshot()`
    walks every mapped column of Item automatically for the delete-undo
    snapshot, and this codebase has already hit "a new Item column
    breaks decode_snapshot()" twice. Nothing about this row is ever
    reviewed or undone -- it is a cache of what the drawing showed, not
    estimator state -- so it stays outside the action-log/undo system
    entirely rather than being taught to it.

    One row per item at most: `item_id` is both the primary key and the
    foreign key, so a re-run's upsert (see evidence_images.py) never has
    to reason about more than one existing row per item. `ON DELETE
    CASCADE` means deleting an item drops this row, and undoing back
    through that delete does not bring it back -- this table sits
    outside the snapshot system entirely, so nothing restores it.

    `Item.evidence` (the JSONB dict, including `has_image`) is a normal
    mapped column and IS restored on undo like any other snapshotted
    field (see snapshots.py's `ITEM_SNAPSHOT_TYPES`). That means a
    delete-then-undo round trip can leave `item.evidence.has_image`
    reading `true` while this table has no row for that item -- the
    dict says an image exists and it does not. The frontend already
    handles this gracefully: `EvidenceModal` (MiscModals.jsx) requests
    the image, the fetch 404s, and the `onError` fallback shows the
    evidence detail/sheet text with copy that says no drawing crop is
    *available* -- not that one was never captured, which this
    round trip can make false -- rather than crashing or claiming no
    evidence exists.
    """

    __tablename__ = "item_evidence_images"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    png: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SymbolResolution(Base):
    """What this firm read a cluster tag as, on this project -- written
    only when an estimator applies a proposal, never by the engine. The
    sheet job overlays it on a later run so the tag arrives already
    named, at Ready to review, never approved. One row per (project,
    tag); a second resolution of the same tag replaces the first."""
    __tablename__ = "symbol_resolutions"
    __table_args__ = (UniqueConstraint("project_id", "tag", name="uq_symbol_resolution_project_tag"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    tag: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(300))
    system: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    catalog_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CompanyLaborRate(Base):
    """Singleton per org -- the three role rates and the productivity
    factor CompanySettings.jsx's 'Labor rates'/'Labor adjustments' tabs
    render, moved off localStorage (Task 13)."""

    __tablename__ = "company_labor_rates"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True)
    journeyman_rate: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, server_default="0")
    foreman_rate: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, server_default="0")
    apprentice_rate: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, server_default="0")
    # A multiplier, not a percent -- matches settingsStore.js's existing
    # productivityFactor field exactly (1.0 = neutral, 0.97 = 3% more
    # efficient) so the migrated value means the same thing it always did.
    productivity_factor: Mapped[Decimal] = mapped_column(Numeric(5, 3), default=1, server_default="1")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyLaborHoursOverride(Base):
    """Sparse: only items the company has explicitly set custom hours
    for get a row. Everything else falls through to the item's own
    engine-computed labor_hours (when that's trustworthy -- see
    Project.pricing_source)."""

    __tablename__ = "company_labor_hours_overrides"
    __table_args__ = (UniqueConstraint("org_id", "item_name", name="uq_company_labor_hours_item"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    item_name: Mapped[str] = mapped_column(String(300))
    hours_per_unit: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyMaterialPrice(Base):
    """Sparse, same shape as the hours override -- one row per item name
    the company has priced. Replaces CompanySettings.jsx's 'Material
    pricing' tab's single free-text field with a real list (Task 13)."""

    __tablename__ = "company_material_prices"
    __table_args__ = (UniqueConstraint("org_id", "item_name", name="uq_company_material_price_item"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    item_name: Mapped[str] = mapped_column(String(300))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    effective_date: Mapped[date] = mapped_column(Date)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProjectLaborLine(Base):
    """Per-item labor overrides, one row per item at most. Every field is
    nullable and independent: an estimator can override just the crew
    mix and leave hours alone, or type a flat rate and leave everything
    else at its default. Edited through Task 4's mutation endpoint and
    reversed through Task 5's undo dispatch for a `labor_edit` action.

    Also cascades away with its parent `Item` (`ON DELETE CASCADE`
    above), so `review._apply_delete()` captures this row explicitly in
    the delete snapshot, and `undo_apply._apply_delete()` restores it on
    undo -- unlike `ItemEvidenceImage`, which is deliberately left out of
    that snapshot (see its own docstring)."""

    __tablename__ = "project_labor_lines"

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    hours_override: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    crew_journeyman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crew_foreman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crew_apprentice: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_override: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    adjustment_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    adjustment_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProjectMaterialPrice(Base):
    """Per-item material price override, one row per item at most.
    `source` distinguishes a typed project price from a deliberate
    allowance -- both are the same mechanical override, the label is
    what the estimator meant by it. Same delete-snapshot/undo coverage
    as ProjectLaborLine above."""

    __tablename__ = "project_material_prices"

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    price_override: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    source: Mapped[str] = mapped_column(String(20))  # "project_price" | "allowance"
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
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
    """Append-only. Undo appends a compensating row; nothing is ever rewritten.

    Project-scoped mutations only. Org-level pricing edits go through
    `CompanyAction`/`company_actions` instead -- see that class's
    docstring for why, and for the cost of splitting the compliance
    record across two tables."""

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
    # The estimator's own sentence when the action came from the decision
    # area (say-what-it-is spec) -- stored, never interpreted again.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    undoes_action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("actions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CompanyAction(Base):
    """Append-only audit of org-level pricing changes.

    Deliberately separate from `actions`: that table is project-scoped by a
    non-nullable FK and is also the undo stack, and a company edit is
    neither undoable nor part of any project's history. Keeping them apart
    means undo cannot see these rows at all.

    The cost, recorded here so it is not rediscovered: the compliance
    record now spans two tables, and an audit of "everything that changed"
    has to read both.
    """

    __tablename__ = "company_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True, index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(Text)
    before: Mapped[dict] = mapped_column(JSONB, default=dict)
    after: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Single source of truth for company_actions' append-only guard, mirroring
# app.takeoff.actions.ACTION_LOG_GUARD_DDL for `actions` exactly -- same
# trigger shape, same ENABLE ALWAYS (so a session_replication_role =
# replica apply worker can't bypass it), same privilege REVOKE as a second
# line of defense beyond the trigger. Two callers read this constant
# rather than duplicating the SQL: migrations/versions/0017_company_
# action_log_guard.py runs it against the real database, and
# tests/conftest.py's `db` fixture re-runs it after Base.metadata.create_
# all, which does not execute migrations. `CompanyAction`'s docstring
# above claims "append-only" -- this is what makes that claim true rather
# than a convention nothing enforces.
COMPANY_ACTION_LOG_GUARD_DDL = """
create or replace function company_actions_are_append_only() returns trigger as $$
begin
    raise exception 'company_actions is append-only: % is not permitted', tg_op;
end;
$$ language plpgsql;

drop trigger if exists company_actions_no_update on company_actions;
drop trigger if exists company_actions_no_delete on company_actions;
drop trigger if exists company_actions_no_truncate on company_actions;

create trigger company_actions_no_update before update on company_actions
    for each statement execute function company_actions_are_append_only();
create trigger company_actions_no_delete before delete on company_actions
    for each statement execute function company_actions_are_append_only();
create trigger company_actions_no_truncate before truncate on company_actions
    for each statement execute function company_actions_are_append_only();

alter table company_actions enable always trigger company_actions_no_update;
alter table company_actions enable always trigger company_actions_no_delete;
alter table company_actions enable always trigger company_actions_no_truncate;

-- Same two limits as ACTION_LOG_GUARD_DDL's revoke: a no-op while the
-- connecting role is a Postgres superuser (this project's docker-compose
-- setup), and not proof against the table owner granting the privilege
-- back to itself -- a guard against accidents and casual application-
-- level tampering, not a determined holder of the database credentials.
revoke update, delete, truncate on company_actions from current_user;
"""

COMPANY_ACTION_LOG_GUARD_TEARDOWN_DDL = """
drop trigger if exists company_actions_no_update on company_actions;
drop trigger if exists company_actions_no_delete on company_actions;
drop trigger if exists company_actions_no_truncate on company_actions;
drop function if exists company_actions_are_append_only();
"""


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
