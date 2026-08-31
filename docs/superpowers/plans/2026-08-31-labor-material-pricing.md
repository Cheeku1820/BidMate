# Labor and Material Pricing Workspaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Labor and Material Pricing workspaces — real, backend-persisted company rate/price libraries, per-item project overrides, and a precedence chain gated on whether a project was actually priced by the LLM — per `docs/superpowers/specs/2026-08-31-labor-material-pricing-design.md`.

**Architecture:** Two new sparse per-item tables (`ProjectLaborLine`, `ProjectMaterialPrice`) hold estimator overrides; three new org-scoped tables (`CompanyLaborRate`, `CompanyLaborHoursOverride`, `CompanyMaterialPrice`) hold company defaults; two new columns on `Project` (`pricing_source`, `pricing_note`) record which mechanism actually priced a takeoff. A precedence resolver (pure functions, no I/O) walks project override → company default → engine baseline (only when `pricing_source == "llm"`) → Missing information, for both labor and materials independently. A new router serves resolved rows and accepts overrides; `CompanySettings.jsx` moves its Labor/Material tabs off `localStorage` onto the same backend.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Postgres, React 18, Vitest.

## Global Constraints

- No AI framing, model names, or confidence numbers anywhere in product-facing copy or code comments — see `docs/superpowers/specs/2026-08-31-labor-material-pricing-design.md`'s "no hardcode" reasoning: `pricing_source`/`pricing_note` name a *mechanism* internally but the estimator-facing copy never says "LLM," "model," or "AI." Use "the pricing assistant" or similar plain phrasing only where a human-facing message must explain why a number is missing.
- Every mutation routes through `actions.commit()` for attribution and audit, matching every other mutation in this codebase.
- Company-level edits are logged/attributed but are **not** added to `undo.REVERSIBLE`. Project-level edits (`ProjectLaborLine`, `ProjectMaterialPrice`) **are** added to `REVERSIBLE`.
- Migration revision ids match the `versions/` filename sequence number. The next one is `0014`.
- Backend tests run from `api/` with: `TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest -q`. `npm run build` must pass before any frontend commit.
- Company-scoped rate/price entries key on the item's classified **name** (`item_name`, exact string match) — there is no `Item.catalog_id` to key on (see the design doc's §2 reasoning). An unmatched name falls through to the next precedence tier; it never raises or silently mismatches.
- `Project.pricing_source == None` (a project ingested before this plan) is treated identically to `"deterministic"` everywhere — no baseline tier, never a false "not sure so let's guess" state.
- Nothing in this plan is pre-computed and stored: precedence resolution runs fresh on every `GET`, matching `ROADMAP.md` invariant 1 (totals computed in one place).
- New wire schemas use plain `MODEL_CONFIG` (snake_case field names), matching `ItemOut`'s convention — not `CAMEL_MODEL_CONFIG`. The frontend maps snake_case → camelCase in `api-mapping.js`, the same way `mapItem` already does for `Item`.

---

### Task 1: `Project.pricing_source` / `pricing_note`, wired from ingest and reprocess

**Files:**
- Modify: `api/app/takeoff/models.py` (add two columns to `Project`, after `updated_at`)
- Create: `api/migrations/versions/0014_pricing_source.py`
- Modify: `api/app/takeoff/ingest_service.py` (set the two fields from the payload)
- Modify: `api/app/takeoff/reprocess.py` (same)
- Test: `api/tests/test_ingest_endpoint.py` (append), `api/tests/test_reprocess.py` (append)

**Interfaces:**
- Produces: `Project.pricing_source: str | None`, `Project.pricing_note: str`. Every later task that resolves a "baseline" price/hours tier reads these two fields.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_ingest_endpoint.py`:

```python
def test_ingest_sets_pricing_source_and_note_from_the_payload(client, db, project, signed_in_user):
    payload = {**PAYLOAD, "source": "llm", "location_note": "Rate based on Sacramento, CA area cost data."}
    response = _ingest(client, project.id, payload=payload)
    assert response.status_code == 200, response.text
    db.refresh(project)
    assert project.pricing_source == "llm"
    assert project.pricing_note == "Rate based on Sacramento, CA area cost data."


def test_ingest_without_a_source_field_leaves_pricing_source_none(client, db, project, signed_in_user):
    response = _ingest(client, project.id)  # PAYLOAD has no "source" key
    assert response.status_code == 200, response.text
    db.refresh(project)
    assert project.pricing_source is None
    assert project.pricing_note == ""
```

Append to `api/tests/test_reprocess.py`:

```python
def test_reprocess_updates_pricing_source_and_note(client, db, project, signed_in_user):
    _seed(client, project, [_item("R", "20A duplex receptacle")])
    payload = {**_payload([_item("R", "20A duplex receptacle")]), "source": "deterministic",
               "location_note": "National average rate (no local data matched)."}
    client.post(f"/api/projects/{project.id}/reprocess", json={"payload": payload})
    db.refresh(project)
    assert project.pricing_source == "deterministic"
    assert project.pricing_note == "National average rate (no local data matched)."
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_ingest_endpoint.py -k pricing_source tests/test_reprocess.py -k pricing_source -v
```

Expected: FAIL — `Project` has no `pricing_source` attribute yet.

- [ ] **Step 3: Implement**

In `api/app/takeoff/models.py`, inside `class Project`, add after `updated_at`:

```python
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
```

Create `api/migrations/versions/0014_pricing_source.py`:

```python
"""pricing_source

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-31 00:00:00.000000

Convention: revision ids match the versions/ filename sequence number
rather than the autogenerated hash, so the chain and the directory
listing always agree.

Two columns on projects recording which mechanism (llm or deterministic)
actually priced the most recent ingest/reprocess, and its one-sentence
basis -- Labor and Material Pricing's precedence resolution reads these
to decide whether the engine's own cost figures are trustworthy enough
to show as a baseline tier.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0014'
down_revision: Union[str, None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('pricing_source', sa.String(length=20), nullable=True))
    op.add_column('projects', sa.Column('pricing_note', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('projects', 'pricing_note')
    op.drop_column('projects', 'pricing_source')
```

In `api/app/takeoff/ingest_service.py`, find where `project.stage = "review"` is set (near the end of `ingest_takeoff`, after the items loop) and add immediately after it:

```python
    project.stage = "review"
    project.pricing_source = payload.get("source")
    project.pricing_note = str(payload.get("location_note") or "")
```

In `api/app/takeoff/reprocess.py`, find `reprocess_takeoff`'s equivalent project-stage/meta update (search for where the function reads from `payload` at the top level, e.g. `sheet_number_by_key` construction) and add, anywhere after `payload` is available and before the function returns:

```python
    project.pricing_source = payload.get("source")
    project.pricing_note = str(payload.get("location_note") or "")
```

If `reprocess_takeoff` does not currently assign anything to `project` directly (check its body — it may only touch `Item`/`Sheet`/`Warning` rows), add these two lines right before the function's final `return` statement, referencing the `project` parameter already passed into the function.

- [ ] **Step 4: Run the migration**

```bash
cd api
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" alembic upgrade head
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" alembic downgrade -1
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" alembic upgrade head
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" alembic upgrade head
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_ingest_endpoint.py tests/test_reprocess.py -v
```

Expected: all PASS, including every pre-existing test in both files.

- [ ] **Step 6: Commit**

```bash
git add api/app/takeoff/models.py api/migrations/versions/0014_pricing_source.py api/app/takeoff/ingest_service.py api/app/takeoff/reprocess.py api/tests/test_ingest_endpoint.py api/tests/test_reprocess.py
git commit -m "Track which mechanism (llm or deterministic) actually priced a project"
```

---

### Task 2: Company-level and project-level pricing tables

**Files:**
- Modify: `api/app/takeoff/models.py` (five new classes, inserted after `ItemEvidenceImage` and before `Warning`)
- Create: `api/migrations/versions/0015_labor_material_pricing_tables.py`
- Test: `api/tests/test_takeoff_models.py` (append)

**Interfaces:**
- Produces: `CompanyLaborRate`, `CompanyLaborHoursOverride`, `CompanyMaterialPrice`, `ProjectLaborLine`, `ProjectMaterialPrice` — all SQLAlchemy models. Every later task in this plan depends on these five classes existing exactly as specified here.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_takeoff_models.py`:

```python
def test_project_labor_line_cascades_on_item_delete(db, item):
    from app.takeoff.models import ProjectLaborLine

    db.add(ProjectLaborLine(item_id=item.id, hours_override=1.5))
    db.commit()
    db.delete(item)
    db.commit()
    assert db.get(ProjectLaborLine, item.id) is None


def test_project_material_price_cascades_on_item_delete(db, item):
    from app.takeoff.models import ProjectMaterialPrice

    db.add(ProjectMaterialPrice(item_id=item.id, price_override=12.5, source="project_price"))
    db.commit()
    db.delete(item)
    db.commit()
    assert db.get(ProjectMaterialPrice, item.id) is None


def test_company_material_price_unique_per_org_and_item_name(db, org):
    from sqlalchemy.exc import IntegrityError

    from app.takeoff.models import CompanyMaterialPrice

    db.add(CompanyMaterialPrice(org_id=org.id, item_name="20A duplex receptacle", unit_price=12.0, effective_date="2026-08-01"))
    db.commit()
    db.add(CompanyMaterialPrice(org_id=org.id, item_name="20A duplex receptacle", unit_price=13.0, effective_date="2026-08-15"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_pricing_tables_are_not_in_the_undo_snapshot_types():
    """These are sparse override rows a separate task's own mutation
    endpoints and undo dispatch manage directly (Tasks 4-5) -- they must
    stay outside Item's own delete-undo snapshot the same way
    ItemEvidenceImage does."""
    from app.takeoff.snapshots import ITEM_SNAPSHOT_TYPES

    for leaked in ("hours_override", "crew_journeyman", "price_override", "journeyman_rate"):
        assert leaked not in ITEM_SNAPSHOT_TYPES
```

Check the top of `api/tests/test_takeoff_models.py` for whether `pytest` is already imported; add `import pytest` near the top if not.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_takeoff_models.py -k "labor_line or material_price or pricing_tables" -v
```

Expected: FAIL with `ImportError` (the classes don't exist yet).

- [ ] **Step 3: Implement the models**

In `api/app/takeoff/models.py`, insert the five classes below between `ItemEvidenceImage` and `class Warning(Base):`. `UniqueConstraint` needs adding to the existing top-of-file `sqlalchemy` import tuple if not already present — check before adding it a second time.

```python
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
    else at its default. Edited only through Task 4's mutation endpoint
    and reversed only through Task 5's undo dispatch -- deliberately
    outside Item's own column-walking delete-undo snapshot, the same
    reasoning as ItemEvidenceImage."""

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
    what the estimator meant by it. Same undo/snapshot exclusion as
    ProjectLaborLine above."""

    __tablename__ = "project_material_prices"

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    price_override: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    source: Mapped[str] = mapped_column(String(20))  # "project_price" | "allowance"
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

Create `api/migrations/versions/0015_labor_material_pricing_tables.py`:

```python
"""labor_material_pricing_tables

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-31 00:00:00.000001

Convention: revision ids match the versions/ filename sequence number.

Five new tables: three org-scoped company defaults (labor rates
singleton, sparse labor-hours overrides, sparse material prices) and two
project-scoped sparse per-item overrides (labor line, material price).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0015'
down_revision: Union[str, None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'company_labor_rates',
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('journeyman_rate', sa.Numeric(8, 2), nullable=False, server_default='0'),
        sa.Column('foreman_rate', sa.Numeric(8, 2), nullable=False, server_default='0'),
        sa.Column('apprentice_rate', sa.Numeric(8, 2), nullable=False, server_default='0'),
        sa.Column('productivity_factor', sa.Numeric(5, 3), nullable=False, server_default='1'),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'company_labor_hours_overrides',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_name', sa.String(length=300), nullable=False),
        sa.Column('hours_per_unit', sa.Numeric(8, 3), nullable=False),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('org_id', 'item_name', name='uq_company_labor_hours_item'),
    )
    op.create_table(
        'company_material_prices',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_name', sa.String(length=300), nullable=False),
        sa.Column('unit_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('org_id', 'item_name', name='uq_company_material_price_item'),
    )
    op.create_table(
        'project_labor_lines',
        sa.Column('item_id', UUID(as_uuid=True), sa.ForeignKey('items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('hours_override', sa.Numeric(8, 3), nullable=True),
        sa.Column('crew_journeyman', sa.Integer(), nullable=True),
        sa.Column('crew_foreman', sa.Integer(), nullable=True),
        sa.Column('crew_apprentice', sa.Integer(), nullable=True),
        sa.Column('rate_override', sa.Numeric(8, 2), nullable=True),
        sa.Column('adjustment_percent', sa.Numeric(6, 2), nullable=True),
        sa.Column('adjustment_reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'project_material_prices',
        sa.Column('item_id', UUID(as_uuid=True), sa.ForeignKey('items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('price_override', sa.Numeric(10, 2), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('project_material_prices')
    op.drop_table('project_labor_lines')
    op.drop_table('company_material_prices')
    op.drop_table('company_labor_hours_overrides')
    op.drop_table('company_labor_rates')
```

- [ ] **Step 4: Run the migration up/down/up against both databases**

```bash
cd api
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" alembic upgrade head
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" alembic downgrade -1
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" alembic upgrade head
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" alembic upgrade head
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_takeoff_models.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/takeoff/models.py api/migrations/versions/0015_labor_material_pricing_tables.py api/tests/test_takeoff_models.py
git commit -m "Add company rate/price libraries and project-level pricing overrides"
```

---

### Task 3: Precedence resolution — pure functions

**Files:**
- Create: `api/app/takeoff/pricing.py`
- Test: `api/tests/test_pricing.py`

**Interfaces:**
- Consumes: `Item`, `ProjectLaborLine`, `ProjectMaterialPrice`, `CompanyLaborRate`, `CompanyLaborHoursOverride`, `CompanyMaterialPrice` (Task 2), `Project.pricing_source` (Task 1).
- Produces:
  - `resolve_material_price(item, project, override, company_price) -> MaterialResolution`
  - `resolve_labor(item, project, override, company_rates, company_hours) -> LaborResolution`
  - `MaterialResolution` / `LaborResolution`: plain dataclasses. Task 6's `GET` endpoints and Task 4's mutation responses build their output schemas from these.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_pricing.py`:

```python
"""Precedence resolution for Labor and Material Pricing -- pure
functions, no database. Each tier is tested in isolation and confirmed
to be correctly skipped when a higher tier is present.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.takeoff.pricing import (
    STALE_PRICE_DAYS,
    resolve_labor,
    resolve_material_price,
)


class FakeItem:
    def __init__(self, name="20A duplex receptacle", quantity=Decimal("10"),
                 material_cost=Decimal("120"), labor_hours=Decimal("5"), labor_cost=Decimal("390")):
        self.name = name
        self.quantity = quantity
        self.material_cost = material_cost
        self.labor_hours = labor_hours
        self.labor_cost = labor_cost


class FakeProject:
    def __init__(self, pricing_source="llm", pricing_note="Rate based on Sacramento, CA area cost data."):
        self.pricing_source = pricing_source
        self.pricing_note = pricing_note


# ---- Material price ----

def test_material_price_project_override_wins_over_everything():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"price_override": Decimal("15"), "source": "project_price"})()
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": date.today()})()
    result = resolve_material_price(item, project, override, company)
    assert result.unit_price == Decimal("15")
    assert result.source_label == "Project price"


def test_material_price_allowance_label():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"price_override": Decimal("20"), "source": "allowance"})()
    result = resolve_material_price(item, project, override, None)
    assert result.unit_price == Decimal("20")
    assert result.source_label == "Allowance"


def test_material_price_company_price_wins_over_regional():
    item, project = FakeItem(), FakeProject()
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": date.today()})()
    result = resolve_material_price(item, project, None, company)
    assert result.unit_price == Decimal("13")
    assert result.source_label == "Company price"


def test_material_price_company_price_stale_after_180_days():
    item, project = FakeItem(), FakeProject()
    old = date.today() - timedelta(days=STALE_PRICE_DAYS + 1)
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": old})()
    result = resolve_material_price(item, project, None, company)
    assert result.status == "attention"


def test_material_price_company_price_not_stale_at_179_days():
    item, project = FakeItem(), FakeProject()
    recent = date.today() - timedelta(days=STALE_PRICE_DAYS - 1)
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": recent})()
    result = resolve_material_price(item, project, None, company)
    assert result.status == "ready"


def test_material_price_regional_baseline_only_when_llm_priced():
    item = FakeItem(material_cost=Decimal("120"), quantity=Decimal("10"))
    project = FakeProject(pricing_source="llm")
    result = resolve_material_price(item, project, None, None)
    assert result.unit_price == Decimal("12")
    assert result.source_label == "Regional baseline"
    assert result.status == "ready"


def test_material_price_missing_when_deterministically_priced():
    item = FakeItem(material_cost=Decimal("120"), quantity=Decimal("10"))
    project = FakeProject(pricing_source="deterministic")
    result = resolve_material_price(item, project, None, None)
    assert result.unit_price is None
    assert result.status == "missing"


def test_material_price_missing_when_pricing_source_is_none():
    item = FakeItem()
    project = FakeProject(pricing_source=None)
    result = resolve_material_price(item, project, None, None)
    assert result.status == "missing"


def test_material_price_missing_when_quantity_is_zero():
    item = FakeItem(quantity=Decimal("0"))
    project = FakeProject(pricing_source="llm")
    result = resolve_material_price(item, project, None, None)
    assert result.status == "missing"


# ---- Labor ----

def test_labor_hours_estimator_override_wins():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"hours_override": Decimal("0.75"), "crew_journeyman": None,
                               "crew_foreman": None, "crew_apprentice": None,
                               "rate_override": None, "adjustment_percent": None})()
    result = resolve_labor(item, project, override, company_rates=None, company_hours=None)
    assert result.hours_per_unit == Decimal("0.75")
    assert result.hours_source_label == "Estimator entered"


def test_labor_hours_company_standard_wins_over_baseline():
    item, project = FakeItem(), FakeProject()
    company_hours = type("H", (), {"hours_per_unit": Decimal("0.6")})()
    result = resolve_labor(item, project, None, company_rates=None, company_hours=company_hours)
    assert result.hours_per_unit == Decimal("0.6")
    assert result.hours_source_label == "Company standard"


def test_labor_hours_estimated_basis_only_when_llm_priced():
    item = FakeItem(labor_hours=Decimal("5"), quantity=Decimal("10"))
    project = FakeProject(pricing_source="llm")
    result = resolve_labor(item, project, None, company_rates=None, company_hours=None)
    assert result.hours_per_unit == Decimal("0.5")
    assert result.hours_source_label == "Estimated basis"


def test_labor_hours_missing_when_deterministically_priced():
    item = FakeItem(labor_hours=Decimal("5"), quantity=Decimal("10"))
    project = FakeProject(pricing_source="deterministic")
    result = resolve_labor(item, project, None, company_rates=None, company_hours=None)
    assert result.status == "missing"


def test_labor_rate_estimator_override_wins():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"hours_override": None, "rate_override": Decimal("90"),
                               "crew_journeyman": 1, "crew_foreman": None, "crew_apprentice": None,
                               "adjustment_percent": None})()
    company_rates = type("R", (), {"journeyman_rate": Decimal("68"), "foreman_rate": Decimal("82"),
                                    "apprentice_rate": Decimal("41"), "productivity_factor": Decimal("1")})()
    result = resolve_labor(item, project, override, company_rates=company_rates, company_hours=None)
    assert result.rate == Decimal("90")
    assert result.rate_source_label == "Estimator entered"


def test_labor_rate_crew_mix_blended_average():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"hours_override": None, "rate_override": None,
                               "crew_journeyman": 1, "crew_foreman": 0, "crew_apprentice": 1,
                               "adjustment_percent": None})()
    company_rates = type("R", (), {"journeyman_rate": Decimal("68"), "foreman_rate": Decimal("82"),
                                    "apprentice_rate": Decimal("40"), "productivity_factor": Decimal("1")})()
    result = resolve_labor(item, project, override, company_rates=company_rates, company_hours=None)
    assert result.rate == Decimal("54")  # (68 + 40) / 2
    assert result.rate_source_label == "Company crew rate"


def test_labor_rate_falls_back_to_estimated_basis_without_crew_mix():
    item = FakeItem(labor_cost=Decimal("390"), labor_hours=Decimal("5"))
    project = FakeProject(pricing_source="llm")
    result = resolve_labor(item, project, None, company_rates=None, company_hours=None)
    assert result.rate == Decimal("78")  # 390 / 5
    assert result.rate_source_label == "Estimated basis"


def test_labor_final_cost_applies_adjustment_and_productivity_factor():
    item = FakeItem(quantity=Decimal("10"), labor_hours=Decimal("5"), labor_cost=Decimal("390"))
    project = FakeProject(pricing_source="llm")
    override = type("O", (), {"hours_override": None, "rate_override": None,
                               "crew_journeyman": None, "crew_foreman": None, "crew_apprentice": None,
                               "adjustment_percent": Decimal("10")})()
    company_rates = type("R", (), {"journeyman_rate": Decimal("0"), "foreman_rate": Decimal("0"),
                                    "apprentice_rate": Decimal("0"), "productivity_factor": Decimal("0.97")})()
    result = resolve_labor(item, project, override, company_rates=company_rates, company_hours=None)
    # base hours/unit = 0.5, * qty 10 = 5, * 1.10 adjustment, * 0.97 productivity
    expected_hours = Decimal("0.5") * Decimal("10") * Decimal("1.10") * Decimal("0.97")
    assert result.adjusted_hours == pytest.approx(float(expected_hours), rel=1e-6)


def test_labor_estimator_approved_status_when_row_has_any_override_field_set():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"hours_override": None, "rate_override": None,
                               "crew_journeyman": 1, "crew_foreman": None, "crew_apprentice": None,
                               "adjustment_percent": None})()
    result = resolve_labor(item, project, override, company_rates=None, company_hours=None)
    assert result.status == "approved"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_pricing.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.takeoff.pricing'`.

- [ ] **Step 3: Implement**

Create `api/app/takeoff/pricing.py`:

```python
"""Precedence resolution for Labor and Material Pricing (Task 3 of the
labor-material-pricing plan). Pure functions, no database access, so the
resolution logic is testable without Postgres -- the same reasoning
ingest.py's own docstring gives for staying a pure mapper.

Nothing here is pre-computed and stored: both resolve functions run
fresh against whatever the caller already loaded, matching ROADMAP.md
invariant 1 (totals computed in exactly one place).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

# A company price older than this reads as Needs attention ("Stale
# price") rather than Ready to review -- a fixed constant for this plan,
# not a company setting (design doc's Known limitations).
STALE_PRICE_DAYS = 180


@dataclass
class MaterialResolution:
    unit_price: Decimal | None
    source_label: str | None  # "Project price" | "Allowance" | "Company price" | "Regional baseline" | None
    status: str  # "ready" | "attention" | "missing" | "approved"
    basis_note: str = ""


@dataclass
class LaborResolution:
    hours_per_unit: Decimal | None
    hours_source_label: str | None
    rate: Decimal | None
    rate_source_label: str | None
    adjusted_hours: Decimal | None
    labor_cost: Decimal | None
    status: str
    basis_note: str = ""


def resolve_material_price(item, project, override, company_price) -> MaterialResolution:
    """`override` is a ProjectMaterialPrice row or None. `company_price`
    is a CompanyMaterialPrice row (already looked up by item.name by the
    caller) or None."""
    if override is not None:
        label = "Allowance" if override.source == "allowance" else "Project price"
        return MaterialResolution(unit_price=override.price_override, source_label=label, status="approved")

    if company_price is not None:
        stale = (date.today() - company_price.effective_date) > timedelta(days=STALE_PRICE_DAYS)
        status = "attention" if stale else "ready"
        label = "Company price"
        return MaterialResolution(unit_price=company_price.unit_price, source_label=label, status=status)

    if project.pricing_source == "llm" and item.quantity and item.material_cost:
        unit_price = item.material_cost / item.quantity
        return MaterialResolution(
            unit_price=unit_price, source_label="Regional baseline", status="ready",
            basis_note=project.pricing_note,
        )

    return MaterialResolution(unit_price=None, source_label=None, status="missing")


def _labor_override_has_any_field(override) -> bool:
    return any([
        override.hours_override is not None,
        override.rate_override is not None,
        override.crew_journeyman is not None,
        override.crew_foreman is not None,
        override.crew_apprentice is not None,
        override.adjustment_percent is not None,
    ])


def _resolve_hours(item, project, override, company_hours) -> tuple[Decimal | None, str | None]:
    if override is not None and override.hours_override is not None:
        return override.hours_override, "Estimator entered"
    if company_hours is not None:
        return company_hours.hours_per_unit, "Company standard"
    if project.pricing_source == "llm" and item.quantity and item.labor_hours:
        return item.labor_hours / item.quantity, "Estimated basis"
    return None, None


def _resolve_rate(item, project, override, company_rates) -> tuple[Decimal | None, str | None]:
    if override is not None and override.rate_override is not None:
        return override.rate_override, "Estimator entered"

    if override is not None and company_rates is not None:
        roles = [
            (override.crew_journeyman, company_rates.journeyman_rate),
            (override.crew_foreman, company_rates.foreman_rate),
            (override.crew_apprentice, company_rates.apprentice_rate),
        ]
        total_count = sum(count for count, _ in roles if count)
        if total_count:
            weighted = sum(Decimal(count) * rate for count, rate in roles if count)
            return weighted / Decimal(total_count), "Company crew rate"

    if project.pricing_source == "llm" and item.labor_hours:
        return item.labor_cost / item.labor_hours, "Estimated basis"

    return None, None


def resolve_labor(item, project, override, *, company_rates, company_hours) -> LaborResolution:
    """`override` is a ProjectLaborLine row or None. `company_rates` is
    the org's singleton CompanyLaborRate row or None. `company_hours` is
    a CompanyLaborHoursOverride row (already looked up by item.name) or
    None."""
    hours_per_unit, hours_label = _resolve_hours(item, project, override, company_hours)
    rate, rate_label = _resolve_rate(item, project, override, company_rates)

    if hours_per_unit is None or rate is None:
        status = "approved" if (override is not None and _labor_override_has_any_field(override)) else "missing"
        return LaborResolution(
            hours_per_unit=hours_per_unit, hours_source_label=hours_label,
            rate=rate, rate_source_label=rate_label,
            adjusted_hours=None, labor_cost=None, status=status,
        )

    adjustment_percent = override.adjustment_percent if override is not None and override.adjustment_percent is not None else Decimal("0")
    productivity_factor = company_rates.productivity_factor if company_rates is not None else Decimal("1")
    adjusted_hours = hours_per_unit * item.quantity * (1 + adjustment_percent / 100) * productivity_factor
    labor_cost = adjusted_hours * rate

    if override is not None and _labor_override_has_any_field(override):
        status = "approved"
    else:
        status = "ready"

    return LaborResolution(
        hours_per_unit=hours_per_unit, hours_source_label=hours_label,
        rate=rate, rate_source_label=rate_label,
        adjusted_hours=adjusted_hours, labor_cost=labor_cost, status=status,
        basis_note=project.pricing_note if (hours_label == "Estimated basis" or rate_label == "Estimated basis") else "",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_pricing.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/pricing.py api/tests/test_pricing.py
git commit -m "Add precedence resolution for Labor and Material Pricing"
```

---

### Task 4: Project-level mutation endpoints

**Files:**
- Create: `api/app/takeoff/pricing_router.py`
- Modify: `api/app/takeoff/schemas.py` (append new schemas)
- Test: `api/tests/test_pricing_endpoints.py` (new file)

**Interfaces:**
- Consumes: `ProjectLaborLine`, `ProjectMaterialPrice` (Task 2); `load_item`, `not_found` (existing, from `router.py`).
- Produces: `PATCH /api/items/{item_id}/labor`, `PATCH /api/items/{item_id}/material-price`. The router object `pricing_router` — Task 7 adds more routes to this same file, Task 8 mounts it.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_pricing_endpoints.py`:

```python
"""PATCH /api/items/{item_id}/labor and /material-price -- the two
project-level override mutations."""
from sqlalchemy import select

from app.takeoff.models import Action, ProjectLaborLine, ProjectMaterialPrice


def test_patch_labor_creates_a_row_and_commits_an_action(client, db, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    assert response.status_code == 200, response.text
    row = db.get(ProjectLaborLine, item.id)
    assert row is not None and float(row.hours_override) == 0.75
    action = db.scalars(select(Action).where(Action.kind == "labor_edit", Action.item_id == item.id)).one()
    assert action.actor_user_id == signed_in_user.id


def test_patch_labor_merges_onto_an_existing_row(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/labor", json={"crewJourneyman": 1})
    client.patch(f"/api/items/{item.id}/labor", json={"crewForeman": 1})
    row = db.get(ProjectLaborLine, item.id)
    assert row.crew_journeyman == 1 and row.crew_foreman == 1


def test_patch_labor_requires_at_least_one_field(client, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/labor", json={})
    assert response.status_code >= 400


def test_patch_material_price_creates_a_row(client, db, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/material-price",
                             json={"priceOverride": 15.5, "source": "project_price"})
    assert response.status_code == 200, response.text
    row = db.get(ProjectMaterialPrice, item.id)
    assert row is not None and float(row.price_override) == 15.5 and row.source == "project_price"


def test_patch_material_price_allowance_requires_a_reason(client, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/material-price",
                             json={"priceOverride": 15.5, "source": "allowance"})
    assert response.status_code >= 400


def test_patch_material_price_allowance_with_reason_succeeds(client, db, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/material-price",
                             json={"priceOverride": 15.5, "source": "allowance", "reason": "no vendor quote yet"})
    assert response.status_code == 200, response.text
    row = db.get(ProjectMaterialPrice, item.id)
    assert row.source == "allowance" and row.reason == "no vendor quote yet"


def test_patch_labor_404s_for_another_orgs_item(client, other_org_project, db, signed_in_user):
    from app.takeoff.models import Item, ReviewStatus, Sheet

    sheet = Sheet(project_id=other_org_project.id, number="E1.1", title="t", discipline="Electrical",
                  revision="", scale="", scale_options=[], plan="")
    db.add(sheet)
    db.flush()
    other_item = Item(project_id=other_org_project.id, sheet_id=sheet.id, symbol="receptacle",
                       name="Receptacle", system="Power", category="Devices", quantity=1,
                       unit="EA", status=ReviewStatus.READY)
    db.add(other_item)
    db.commit()

    response = client.patch(f"/api/items/{other_item.id}/labor", json={"hoursOverride": 1})
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_pricing_endpoints.py -v
```

Expected: FAIL — 404 on every request (route doesn't exist; the app isn't even aware of `/labor`/`/material-price` yet).

- [ ] **Step 3: Implement**

Append to `api/app/takeoff/schemas.py`:

```python
class LaborLineUpdateIn(BaseModel):
    hours_override: Decimal | None = Field(default=None)
    crew_journeyman: int | None = Field(default=None, ge=0)
    crew_foreman: int | None = Field(default=None, ge=0)
    crew_apprentice: int | None = Field(default=None, ge=0)
    rate_override: Decimal | None = Field(default=None)
    adjustment_percent: Decimal | None = Field(default=None)
    adjustment_reason: str | None = Field(default=None)
    notes: str | None = Field(default=None)

    model_config = {**MODEL_CONFIG, "alias_generator": to_camel, "populate_by_name": True, "extra": "forbid"}


class MaterialPriceUpdateIn(BaseModel):
    price_override: Decimal
    source: Literal["project_price", "allowance"]
    reason: str = ""

    model_config = {**MODEL_CONFIG, "alias_generator": to_camel, "populate_by_name": True, "extra": "forbid"}

    @field_validator("reason")
    @classmethod
    def _allowance_needs_a_reason(cls, value: str, info) -> str:
        # An allowance with no reason is a number nobody can trace back
        # to a judgment call -- the same principle scale.py already
        # enforces for a confirmed measurement with no evidence behind it.
        if info.data.get("source") == "allowance" and not value.strip():
            raise ValueError("An allowance needs a reason -- state what it's standing in for.")
        return value
```

Create `api/app/takeoff/pricing_router.py`:

```python
"""pricing_router.py -- Labor and Material Pricing (labor-material-pricing
plan). Split from mutations.py rather than added to it, the same reason
mutations.py was split from router.py: this adds a real block of new
endpoints and mutations.py is already at this project's file-size
convention.
"""
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.takeoff import actions
from app.takeoff.actions import encode_snapshot
from app.takeoff.models import (
    CompanyLaborHoursOverride,
    CompanyLaborRate,
    CompanyMaterialPrice,
    Item,
    ProjectLaborLine,
    ProjectMaterialPrice,
)
from app.takeoff.router import load_item, load_project, not_found
from app.takeoff.schemas import LaborLineUpdateIn, MaterialPriceUpdateIn

router = APIRouter(prefix="/api", tags=["pricing"])


def _snapshot(model_cls, pk_value, db: DbSession) -> dict | None:
    """A JSON-safe column snapshot for actions.commit()'s before/after.
    encode_snapshot() is required here, not optional -- both
    ProjectLaborLine and ProjectMaterialPrice carry Decimal, UUID, and
    datetime columns (hours_override, item_id, updated_at, ...), none of
    which json.dumps can serialize directly. This mirrors
    review._apply_edit()'s own `encode_snapshot(_column_snapshot(item))`
    call for the same reason."""
    row = db.get(model_cls, pk_value)
    if row is None:
        return None
    mapper = row.__class__.__mapper__
    raw = {attr.key: getattr(row, attr.key) for attr in mapper.column_attrs}
    return encode_snapshot(raw)


@router.patch("/items/{item_id}/labor")
def patch_labor(
    item_id: uuid.UUID,
    body: LaborLineUpdateIn,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    item = load_item(item_id, db, user)
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    if not changes:
        raise DomainError(
            "no_changes_to_apply",
            "This update has no changes. Include at least one field, such as hours or a crew count.",
        )

    before = _snapshot(ProjectLaborLine, item_id, db)
    row = db.get(ProjectLaborLine, item_id)
    if row is None:
        row = ProjectLaborLine(item_id=item_id)
        db.add(row)
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by_user_id = user.id
    db.flush()
    after = _snapshot(ProjectLaborLine, item_id, db)

    actions.commit(
        db, actor=user, project_id=item.project_id, kind="labor_edit",
        label=f"Updated labor for {item.name}", item_id=item_id,
        before=before or {}, after=after,
    )
    db.commit()
    return {"itemId": str(item_id)}


@router.patch("/items/{item_id}/material-price")
def patch_material_price(
    item_id: uuid.UUID,
    body: MaterialPriceUpdateIn,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    item = load_item(item_id, db, user)

    before = _snapshot(ProjectMaterialPrice, item_id, db)
    row = db.get(ProjectMaterialPrice, item_id)
    if row is None:
        row = ProjectMaterialPrice(item_id=item_id, price_override=body.price_override, source=body.source)
        db.add(row)
    else:
        row.price_override = body.price_override
        row.source = body.source
    row.reason = body.reason
    row.updated_by_user_id = user.id
    db.flush()
    after = _snapshot(ProjectMaterialPrice, item_id, db)

    actions.commit(
        db, actor=user, project_id=item.project_id, kind="material_price_edit",
        label=f"Updated material price for {item.name}", item_id=item_id,
        before=before or {}, after=after,
    )
    db.commit()
    return {"itemId": str(item_id)}
```

`before or {}` on a brand-new row's first edit matches `ingest.py`'s existing `commit(before={}, after={})` convention for "there was nothing before this" (see `ingest_service.py`'s own `actions.commit(..., before={}, after={})` call for the `"ingest"` kind).

- [ ] **Step 4: Mount the router (temporarily, for this task's tests to run)**

In `api/app/main.py`, add the import alongside the other router imports:

```python
from app.takeoff.pricing_router import router as pricing_router
```

and mount it alongside the others:

```python
app.include_router(pricing_router)
```

(Task 8 formalizes this mounting alongside the rest of this plan's routes; doing it here now is what makes this task's own tests able to hit the endpoint.)

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_pricing_endpoints.py -v
```

Expected: all PASS. Then run the full suite once to confirm the new `LaborLineUpdateIn`/`MaterialPriceUpdateIn` schemas and router mount didn't break anything:

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add api/app/takeoff/pricing_router.py api/app/takeoff/schemas.py api/app/main.py api/tests/test_pricing_endpoints.py
git commit -m "Add PATCH endpoints for per-item labor and material price overrides"
```

---

### Task 5: Undo/redo support for `labor_edit` and `material_price_edit`

**Files:**
- Modify: `api/app/takeoff/undo.py` (add both kinds to `REVERSIBLE`)
- Modify: `api/app/takeoff/snapshots.py` (two new snapshot-type dicts)
- Modify: `api/app/takeoff/undo_apply.py` (dispatch + one new generic apply function)
- Test: `api/tests/test_undo_redo.py` (append)

**Interfaces:**
- Consumes: `ProjectLaborLine`, `ProjectMaterialPrice` (Task 2); the `labor_edit`/`material_price_edit` actions Task 4's endpoints already commit.
- Produces: undo/redo of both kinds via the existing `POST /api/projects/{id}/undo` and `/redo` endpoints — no new routes.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_undo_redo.py` (check the file's existing imports and a nearby `delete`-then-`undo` test first, to match its exact request/assertion style before writing these):

```python
def test_undo_reverses_a_labor_edit_that_created_the_row(client, db, item, signed_in_user):
    from app.takeoff.models import ProjectLaborLine

    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    assert db.get(ProjectLaborLine, item.id) is not None

    response = client.post(f"/api/projects/{item.project_id}/undo")
    assert response.status_code == 200, response.text
    assert db.get(ProjectLaborLine, item.id) is None


def test_undo_reverses_a_labor_edit_that_merged_onto_an_existing_row(client, db, item, signed_in_user):
    from app.takeoff.models import ProjectLaborLine

    client.patch(f"/api/items/{item.id}/labor", json={"crewJourneyman": 1})
    client.patch(f"/api/items/{item.id}/labor", json={"crewForeman": 2})

    client.post(f"/api/projects/{item.project_id}/undo")
    row = db.get(ProjectLaborLine, item.id)
    assert row.crew_journeyman == 1 and row.crew_foreman is None


def test_redo_restores_a_labor_edit_after_undo(client, db, item, signed_in_user):
    from app.takeoff.models import ProjectLaborLine

    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    client.post(f"/api/projects/{item.project_id}/undo")
    assert db.get(ProjectLaborLine, item.id) is None

    client.post(f"/api/projects/{item.project_id}/redo")
    row = db.get(ProjectLaborLine, item.id)
    assert float(row.hours_override) == 0.75


def test_undo_reverses_a_material_price_edit(client, db, item, signed_in_user):
    from app.takeoff.models import ProjectMaterialPrice

    client.patch(f"/api/items/{item.id}/material-price", json={"priceOverride": 15.5, "source": "project_price"})
    client.post(f"/api/projects/{item.project_id}/undo")
    assert db.get(ProjectMaterialPrice, item.id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_undo_redo.py -k "labor_edit or material_price_edit" -v
```

Expected: FAIL — the row still exists after `POST /undo` (the action was committed with a kind `undo.py` doesn't know is reversible yet, so `POST /undo` either 404s with nothing eligible, or silently does nothing to this row).

- [ ] **Step 3: Implement**

In `api/app/takeoff/undo.py`, change:

```python
REVERSIBLE = {"approve", "reject", "unreject", "edit", "delete", "bulk_approve", "scale"}
```

to:

```python
REVERSIBLE = {"approve", "reject", "unreject", "edit", "delete", "bulk_approve", "scale", "labor_edit", "material_price_edit"}
```

In `api/app/takeoff/snapshots.py`, add two new dicts near `ITEM_SNAPSHOT_TYPES`:

```python
LABOR_LINE_SNAPSHOT_TYPES: dict[str, type] = {
    "item_id": uuid.UUID,
    "hours_override": Decimal,
    "crew_journeyman": int,
    "crew_foreman": int,
    "crew_apprentice": int,
    "rate_override": Decimal,
    "adjustment_percent": Decimal,
    "adjustment_reason": str,
    "notes": str,
    "updated_by_user_id": uuid.UUID,
    "updated_at": datetime,
}

MATERIAL_PRICE_SNAPSHOT_TYPES: dict[str, type] = {
    "item_id": uuid.UUID,
    "price_override": Decimal,
    "source": str,
    "reason": str,
    "updated_by_user_id": uuid.UUID,
    "updated_at": datetime,
}
```

Check the top of `snapshots.py` for its existing `uuid`/`Decimal`/`datetime` imports — they're already imported for `ITEM_SNAPSHOT_TYPES`, no new imports needed.

In `api/app/takeoff/undo_apply.py`, add the import:

```python
from app.takeoff.models import ProjectLaborLine, ProjectMaterialPrice
from app.takeoff.snapshots import LABOR_LINE_SNAPSHOT_TYPES, MATERIAL_PRICE_SNAPSHOT_TYPES
```

(merge into the existing `from app.takeoff.snapshots import ITEM_SNAPSHOT_TYPES, ITEMS_SNAPSHOT_KEY, WARNING_SNAPSHOT_TYPES` line rather than adding a second one, and check whether `ProjectLaborLine`/`ProjectMaterialPrice` need adding to an existing `from app.takeoff.models import ...` line the same way).

Add a new generic apply function, near `_restore_row_if_missing`/`_delete_row_if_present`:

```python
def _apply_sparse_pricing_row(db: DbSession, model: type, item_id: uuid.UUID, snapshot_types: dict, state: dict) -> None:
    """Reverses a labor_edit/material_price_edit action onto ProjectLaborLine
    or ProjectMaterialPrice. Unlike Item (always exists once ingested),
    these rows are sparse -- created on first edit -- so `state` may be
    an empty dict (the row didn't exist before this action; undo means it
    shouldn't exist now) or a decoded snapshot of every column (the row
    existed; undo/redo means it should hold exactly these values)."""
    if not state:
        _delete_row_if_present(db, model, item_id)
        return
    decoded = decode_snapshot(state, snapshot_types)
    decoded.pop("item_id", None)
    if not _row_exists(db, model, item_id):
        _expunge_stale(db, model, item_id)
        db.add(model(item_id=item_id, **decoded))
    else:
        row = db.get(model, item_id)
        for key, value in decoded.items():
            setattr(row, key, value)
```

In `apply()`'s dispatch, add two branches before the `else`:

```python
    if action.kind == "scale":
        _apply_scale(db, action, direction)
    elif action.kind == "bulk_approve":
        _apply_bulk_approve(db, state)
    elif action.kind == "delete":
        _apply_delete(db, action, direction)
    elif action.kind == "labor_edit":
        _apply_sparse_pricing_row(db, ProjectLaborLine, action.item_id, LABOR_LINE_SNAPSHOT_TYPES, state)
    elif action.kind == "material_price_edit":
        _apply_sparse_pricing_row(db, ProjectMaterialPrice, action.item_id, MATERIAL_PRICE_SNAPSHOT_TYPES, state)
    else:  # approve, reject, unreject, edit
        _apply_item_state(db, action.item_id, state)
```

`_row_exists`, `_expunge_stale`, and `_delete_row_if_present` are already generic over `model` (confirmed by their existing signatures taking `model: type`) — no changes needed to them.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_undo_redo.py -v
```

Expected: all PASS, including every pre-existing test in the file — this is the file with the most concentrated correctness risk in the codebase, so a regression here matters more than in most files.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/undo.py api/app/takeoff/snapshots.py api/app/takeoff/undo_apply.py api/tests/test_undo_redo.py
git commit -m "Add undo/redo support for labor and material price edits"
```

---

### Task 6: Resolved-row list endpoints

**Files:**
- Modify: `api/app/takeoff/pricing_router.py` (add two `GET` routes)
- Modify: `api/app/takeoff/schemas.py` (append `LaborRowOut`, `MaterialRowOut`)
- Test: `api/tests/test_pricing_endpoints.py` (append)

**Interfaces:**
- Consumes: `resolve_material_price`, `resolve_labor` (Task 3); `countable_items` (existing, from `totals.py`).
- Produces: `GET /api/projects/{project_id}/labor -> {pricingSource, pricingNote, rows: [LaborRowOut]}`, `GET /api/projects/{project_id}/material-pricing -> {pricingSource, pricingNote, rows: [MaterialRowOut]}`.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_pricing_endpoints.py`:

```python
def test_get_labor_lists_every_countable_item(client, db, project, item, signed_in_user):
    response = client.get(f"/api/projects/{project.id}/labor")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pricingSource"] is None
    ids = [row["itemId"] for row in body["rows"]]
    assert str(item.id) in ids


def test_get_labor_row_missing_without_llm_pricing(client, project, item, signed_in_user):
    response = client.get(f"/api/projects/{project.id}/labor")
    row = next(r for r in response.json()["rows"] if r["itemId"] == str(item.id))
    assert row["status"] == "missing"


def test_get_labor_row_ready_when_project_priced_by_llm(client, db, project, item, signed_in_user):
    project.pricing_source = "llm"
    db.commit()
    response = client.get(f"/api/projects/{project.id}/labor")
    row = next(r for r in response.json()["rows"] if r["itemId"] == str(item.id))
    assert row["status"] == "ready"
    assert row["hoursSourceLabel"] == "Estimated basis"


def test_get_material_pricing_lists_every_countable_item(client, project, item, signed_in_user):
    response = client.get(f"/api/projects/{project.id}/material-pricing")
    assert response.status_code == 200, response.text
    ids = [row["itemId"] for row in response.json()["rows"]]
    assert str(item.id) in ids


def test_get_material_pricing_uses_company_price_when_present(client, db, org, project, item, signed_in_user):
    from app.takeoff.models import CompanyMaterialPrice

    db.add(CompanyMaterialPrice(org_id=org.id, item_name=item.name, unit_price=99, effective_date="2026-08-01"))
    db.commit()
    response = client.get(f"/api/projects/{project.id}/material-pricing")
    row = next(r for r in response.json()["rows"] if r["itemId"] == str(item.id))
    assert row["sourceLabel"] == "Company price"
    assert float(row["unitPrice"]) == 99.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_pricing_endpoints.py -k "get_labor or get_material" -v
```

Expected: FAIL with 404 (routes don't exist yet).

- [ ] **Step 3: Implement**

Append to `api/app/takeoff/schemas.py`:

```python
class LaborRowOut(BaseModel):
    item_id: uuid.UUID
    item_name: str
    quantity: Decimal
    hours_per_unit: Decimal | None = None
    hours_source_label: str | None = None
    rate: Decimal | None = None
    rate_source_label: str | None = None
    adjusted_hours: Decimal | None = None
    labor_cost: Decimal | None = None
    status: str
    basis_note: str = ""

    model_config = MODEL_CONFIG


class LaborListOut(BaseModel):
    pricing_source: str | None
    pricing_note: str
    rows: list[LaborRowOut]

    model_config = MODEL_CONFIG


class MaterialRowOut(BaseModel):
    item_id: uuid.UUID
    item_name: str
    quantity: Decimal
    unit_price: Decimal | None = None
    source_label: str | None = None
    status: str
    basis_note: str = ""

    model_config = MODEL_CONFIG


class MaterialListOut(BaseModel):
    pricing_source: str | None
    pricing_note: str
    rows: list[MaterialRowOut]

    model_config = MODEL_CONFIG
```

Append to `api/app/takeoff/pricing_router.py`, adding to the existing imports:

```python
from app.takeoff.pricing import resolve_labor, resolve_material_price
from app.takeoff.schemas import LaborListOut, LaborRowOut, MaterialListOut, MaterialRowOut
from app.takeoff.totals import countable_items
```

and the two routes:

```python
@router.get("/projects/{project_id}/labor", response_model=LaborListOut)
def get_labor(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    items = list(db.scalars(countable_items(project.id)))
    lines = {row.item_id: row for row in db.scalars(
        select(ProjectLaborLine).where(ProjectLaborLine.item_id.in_([i.id for i in items]))
    )}
    company_rates = db.get(CompanyLaborRate, user.org_id)
    names = {i.name for i in items}
    company_hours = {
        row.item_name: row
        for row in db.scalars(
            select(CompanyLaborHoursOverride).where(
                CompanyLaborHoursOverride.org_id == user.org_id,
                CompanyLaborHoursOverride.item_name.in_(names),
            )
        )
    }

    rows = []
    for item in items:
        resolution = resolve_labor(
            item, project, lines.get(item.id),
            company_rates=company_rates, company_hours=company_hours.get(item.name),
        )
        rows.append(LaborRowOut(
            item_id=item.id, item_name=item.name, quantity=item.quantity,
            hours_per_unit=resolution.hours_per_unit, hours_source_label=resolution.hours_source_label,
            rate=resolution.rate, rate_source_label=resolution.rate_source_label,
            adjusted_hours=resolution.adjusted_hours, labor_cost=resolution.labor_cost,
            status=resolution.status, basis_note=resolution.basis_note,
        ))
    return LaborListOut(pricing_source=project.pricing_source, pricing_note=project.pricing_note, rows=rows)


@router.get("/projects/{project_id}/material-pricing", response_model=MaterialListOut)
def get_material_pricing(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    items = list(db.scalars(countable_items(project.id)))
    overrides = {row.item_id: row for row in db.scalars(
        select(ProjectMaterialPrice).where(ProjectMaterialPrice.item_id.in_([i.id for i in items]))
    )}
    names = {i.name for i in items}
    company_prices = {
        row.item_name: row
        for row in db.scalars(
            select(CompanyMaterialPrice).where(
                CompanyMaterialPrice.org_id == user.org_id,
                CompanyMaterialPrice.item_name.in_(names),
            )
        )
    }

    rows = []
    for item in items:
        resolution = resolve_material_price(item, project, overrides.get(item.id), company_prices.get(item.name))
        rows.append(MaterialRowOut(
            item_id=item.id, item_name=item.name, quantity=item.quantity,
            unit_price=resolution.unit_price, source_label=resolution.source_label,
            status=resolution.status, basis_note=resolution.basis_note,
        ))
    return MaterialListOut(pricing_source=project.pricing_source, pricing_note=project.pricing_note, rows=rows)
```

`Item` was already imported at the top of `pricing_router.py` in Task 4; no change needed there. `load_project` was already imported in Task 4 too.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_pricing_endpoints.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/pricing_router.py api/app/takeoff/schemas.py api/tests/test_pricing_endpoints.py
git commit -m "Serve resolved Labor and Material Pricing rows for a project"
```

---

### Task 7: Company-level CRUD endpoints

**Files:**
- Modify: `api/app/takeoff/pricing_router.py` (add company-scoped routes)
- Modify: `api/app/takeoff/schemas.py` (append company schemas)
- Test: `api/tests/test_pricing_endpoints.py` (append)

**Interfaces:**
- Consumes: `CompanyLaborRate`, `CompanyLaborHoursOverride`, `CompanyMaterialPrice` (Task 2).
- Produces: the six company-scoped endpoints listed in the design doc's API surface.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_pricing_endpoints.py`:

```python
def test_get_company_labor_rates_defaults_to_zero(client, signed_in_user):
    response = client.get("/api/company/labor-rates")
    assert response.status_code == 200, response.text
    assert response.json()["journeyman_rate"] == "0.00" or float(response.json()["journeyman_rate"]) == 0.0


def test_put_company_labor_rates_persists(client, db, org, signed_in_user):
    response = client.put("/api/company/labor-rates", json={
        "journeymanRate": 68, "foremanRate": 82, "apprenticeRate": 41, "productivityFactor": 0.97,
    })
    assert response.status_code == 200, response.text
    from app.takeoff.models import CompanyLaborRate
    row = db.get(CompanyLaborRate, org.id)
    assert float(row.journeyman_rate) == 68.0


def test_put_company_material_price_creates_and_updates(client, db, org, signed_in_user):
    response = client.put("/api/company/material-prices/20A%20duplex%20receptacle",
                           json={"unitPrice": 13.5, "effectiveDate": "2026-08-01"})
    assert response.status_code == 200, response.text
    response2 = client.put("/api/company/material-prices/20A%20duplex%20receptacle",
                            json={"unitPrice": 14.0, "effectiveDate": "2026-08-15"})
    assert response2.status_code == 200
    from app.takeoff.models import CompanyMaterialPrice
    row = db.scalars(select(CompanyMaterialPrice).where(
        CompanyMaterialPrice.org_id == org.id, CompanyMaterialPrice.item_name == "20A duplex receptacle",
    )).one()
    assert float(row.unit_price) == 14.0


def test_delete_company_material_price(client, db, org, signed_in_user):
    client.put("/api/company/material-prices/20A%20duplex%20receptacle",
               json={"unitPrice": 13.5, "effectiveDate": "2026-08-01"})
    response = client.delete("/api/company/material-prices/20A%20duplex%20receptacle")
    assert response.status_code == 204
    from app.takeoff.models import CompanyMaterialPrice
    remaining = db.scalars(select(CompanyMaterialPrice).where(CompanyMaterialPrice.org_id == org.id)).all()
    assert remaining == []


def test_get_company_material_prices_lists_all(client, org, signed_in_user):
    client.put("/api/company/material-prices/20A%20duplex%20receptacle", json={"unitPrice": 13.5, "effectiveDate": "2026-08-01"})
    response = client.get("/api/company/material-prices")
    names = [row["item_name"] for row in response.json()]
    assert "20A duplex receptacle" in names


def test_put_company_labor_hours_override(client, db, org, signed_in_user):
    response = client.put("/api/company/labor-hours-overrides/20A%20duplex%20receptacle",
                           json={"hoursPerUnit": 0.6})
    assert response.status_code == 200, response.text
    from app.takeoff.models import CompanyLaborHoursOverride
    row = db.scalars(select(CompanyLaborHoursOverride).where(
        CompanyLaborHoursOverride.org_id == org.id, CompanyLaborHoursOverride.item_name == "20A duplex receptacle",
    )).one()
    assert float(row.hours_per_unit) == 0.6
```

Add `from sqlalchemy import select` to the top of `test_pricing_endpoints.py` if not already imported by Task 6's tests.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_pricing_endpoints.py -k "company" -v
```

Expected: FAIL with 404 on every request.

- [ ] **Step 3: Implement**

Append to `api/app/takeoff/schemas.py`:

```python
class CompanyLaborRatesIn(BaseModel):
    journeyman_rate: Decimal
    foreman_rate: Decimal
    apprentice_rate: Decimal
    productivity_factor: Decimal

    model_config = {**MODEL_CONFIG, "alias_generator": to_camel, "populate_by_name": True, "extra": "forbid"}


class CompanyLaborRatesOut(BaseModel):
    journeyman_rate: Decimal
    foreman_rate: Decimal
    apprentice_rate: Decimal
    productivity_factor: Decimal
    updated_at: datetime | None = None

    model_config = MODEL_CONFIG


class CompanyMaterialPriceIn(BaseModel):
    unit_price: Decimal
    effective_date: date

    model_config = {**MODEL_CONFIG, "alias_generator": to_camel, "populate_by_name": True, "extra": "forbid"}


class CompanyMaterialPriceOut(BaseModel):
    item_name: str
    unit_price: Decimal
    effective_date: date
    updated_at: datetime

    model_config = MODEL_CONFIG


class CompanyLaborHoursOverrideIn(BaseModel):
    hours_per_unit: Decimal

    model_config = {**MODEL_CONFIG, "alias_generator": to_camel, "populate_by_name": True, "extra": "forbid"}


class CompanyLaborHoursOverrideOut(BaseModel):
    item_name: str
    hours_per_unit: Decimal
    updated_at: datetime

    model_config = MODEL_CONFIG
```

Append to `api/app/takeoff/pricing_router.py`:

```python
@router.get("/company/labor-rates", response_model=CompanyLaborRatesOut)
def get_company_labor_rates(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.get(CompanyLaborRate, user.org_id)
    if row is None:
        return CompanyLaborRatesOut(journeyman_rate=0, foreman_rate=0, apprentice_rate=0, productivity_factor=1)
    return row


@router.put("/company/labor-rates", response_model=CompanyLaborRatesOut)
def put_company_labor_rates(body: CompanyLaborRatesIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.get(CompanyLaborRate, user.org_id)
    if row is None:
        row = CompanyLaborRate(org_id=user.org_id)
        db.add(row)
    row.journeyman_rate = body.journeyman_rate
    row.foreman_rate = body.foreman_rate
    row.apprentice_rate = body.apprentice_rate
    row.productivity_factor = body.productivity_factor
    row.updated_by_user_id = user.id
    db.commit()
    db.refresh(row)
    return row


@router.get("/company/material-prices", response_model=list[CompanyMaterialPriceOut])
def get_company_material_prices(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return list(db.scalars(select(CompanyMaterialPrice).where(CompanyMaterialPrice.org_id == user.org_id)))


@router.put("/company/material-prices/{item_name}", response_model=CompanyMaterialPriceOut)
def put_company_material_price(item_name: str, body: CompanyMaterialPriceIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyMaterialPrice).where(
        CompanyMaterialPrice.org_id == user.org_id, CompanyMaterialPrice.item_name == item_name,
    )).one_or_none()
    if row is None:
        row = CompanyMaterialPrice(org_id=user.org_id, item_name=item_name, unit_price=body.unit_price, effective_date=body.effective_date)
        db.add(row)
    else:
        row.unit_price = body.unit_price
        row.effective_date = body.effective_date
    row.updated_by_user_id = user.id
    db.commit()
    db.refresh(row)
    return row


@router.delete("/company/material-prices/{item_name}", status_code=204)
def delete_company_material_price(item_name: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyMaterialPrice).where(
        CompanyMaterialPrice.org_id == user.org_id, CompanyMaterialPrice.item_name == item_name,
    )).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()


@router.get("/company/labor-hours-overrides", response_model=list[CompanyLaborHoursOverrideOut])
def get_company_labor_hours_overrides(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return list(db.scalars(select(CompanyLaborHoursOverride).where(CompanyLaborHoursOverride.org_id == user.org_id)))


@router.put("/company/labor-hours-overrides/{item_name}", response_model=CompanyLaborHoursOverrideOut)
def put_company_labor_hours_override(item_name: str, body: CompanyLaborHoursOverrideIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyLaborHoursOverride).where(
        CompanyLaborHoursOverride.org_id == user.org_id, CompanyLaborHoursOverride.item_name == item_name,
    )).one_or_none()
    if row is None:
        row = CompanyLaborHoursOverride(org_id=user.org_id, item_name=item_name, hours_per_unit=body.hours_per_unit)
        db.add(row)
    else:
        row.hours_per_unit = body.hours_per_unit
    row.updated_by_user_id = user.id
    db.commit()
    db.refresh(row)
    return row


@router.delete("/company/labor-hours-overrides/{item_name}", status_code=204)
def delete_company_labor_hours_override(item_name: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyLaborHoursOverride).where(
        CompanyLaborHoursOverride.org_id == user.org_id, CompanyLaborHoursOverride.item_name == item_name,
    )).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()
```

Update the schema import line at the top of `pricing_router.py` to include the six new schema names.

Note: these company-level writes deliberately do **not** call `actions.commit()` — per the design doc and this plan's Global Constraints, company-level edits are attributed via `updated_by_user_id`/`updated_at` on the row itself (visible directly on the row, matching how `CompanySettings.jsx` already shows "updated <date>" per field) rather than through the project-scoped action log, which has no project to attach a company-wide change to.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_pricing_endpoints.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/pricing_router.py api/app/takeoff/schemas.py api/tests/test_pricing_endpoints.py
git commit -m "Add company-level labor rate and material price CRUD endpoints"
```

---

### Task 8: Tenancy coverage for every new route

**Files:**
- Modify: `api/tests/test_tenancy.py`
- Test: (this task's changes are entirely within the test file)

**Interfaces:**
- Consumes: every endpoint from Tasks 4, 6, 7. No production code changes in this task — it closes the same completeness gap Task 9 of the blueprint-evidence plan closed for its own new route.

- [ ] **Step 1: Add rows to `TENANCY_TABLE`**

Append to `TENANCY_TABLE` in `api/tests/test_tenancy.py`, matching its existing five-tuple format exactly:

```python
    ("PATCH", "/api/items/{item_id}/labor",
     lambda p, s, i: f"/api/items/{i.id}/labor", lambda p, s, i: {"hoursOverride": 0.5}, None),
    ("PATCH", "/api/items/{item_id}/material-price",
     lambda p, s, i: f"/api/items/{i.id}/material-price",
     lambda p, s, i: {"priceOverride": 10, "source": "project_price"}, None),
    ("GET", "/api/projects/{project_id}/labor",
     lambda p, s, i: f"/api/projects/{p.id}/labor", None, None),
    ("GET", "/api/projects/{project_id}/material-pricing",
     lambda p, s, i: f"/api/projects/{p.id}/material-pricing", None, None),
```

Company-scoped routes (`/api/company/...`) are deliberately **not** added to `TENANCY_TABLE`: that table's fixture shape (`p, s, i` — a project, a sheet, an item) tests cross-*project* tenancy, and every company route in this plan resolves its scope from `current_user.org_id` alone, with no project/item in the URL to swap for another org's — the same reason `GET /api/auth/me`-shaped routes aren't in this table either. Confirm this by checking whether any existing company-scoped route (if one exists elsewhere in the codebase) is already excluded the same way; if `TENANCY_TABLE`'s own header comment says otherwise, follow the comment instead of this note.

- [ ] **Step 2: Run the tenancy suite**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_tenancy.py -v
```

Expected: all PASS, including the four new parametrized cases (each asserting a 404 when a different org's client tries to hit it).

- [ ] **Step 3: Run the full backend suite**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest -q
```

Expected: all PASS. This is the last backend-only task — a good checkpoint before moving to the frontend.

- [ ] **Step 4: Commit**

```bash
git add api/tests/test_tenancy.py
git commit -m "Add tenancy coverage for the four new project-scoped pricing routes"
```

---

### Task 9: Frontend store methods

**Files:**
- Modify: `src/lib/store/api.js`
- Modify: `src/lib/store/api-mapping.js`
- Test: `src/lib/store/api-mapping.test.js`

**Interfaces:**
- Consumes: every endpoint from Tasks 4, 6, 7.
- Produces: `store.getLaborRows(projectId)`, `store.setLaborLine(itemId, changes)`, `store.getMaterialRows(projectId)`, `store.setMaterialPrice(itemId, changes)`, `store.getCompanyLaborRates()`, `store.setCompanyLaborRates(values)`, `store.getCompanyMaterialPrices()`, `store.setCompanyMaterialPrice(itemName, values)`, `store.deleteCompanyMaterialPrice(itemName)`, `store.getCompanyLaborHoursOverrides()`, `store.setCompanyLaborHoursOverride(itemName, hoursPerUnit)`, `store.deleteCompanyLaborHoursOverride(itemName)`. `mapLaborRow`, `mapMaterialRow` — exported from `api-mapping.js`, used by Tasks 10-11.

- [ ] **Step 1: Write the failing tests**

Append to `src/lib/store/api-mapping.test.js` (check its existing imports/style first):

```js
import { mapLaborRow, mapMaterialRow } from "./api-mapping.js";

describe("mapLaborRow", () => {
  test("maps every field from snake_case to camelCase", () => {
    const row = {
      item_id: "abc", item_name: "20A duplex receptacle", quantity: "10",
      hours_per_unit: "0.5", hours_source_label: "Estimated basis",
      rate: "78", rate_source_label: "Estimated basis",
      adjusted_hours: "5.5", labor_cost: "429", status: "ready", basis_note: "Rate based on Sacramento, CA.",
    };
    const mapped = mapLaborRow(row);
    expect(mapped).toMatchObject({
      itemId: "abc", itemName: "20A duplex receptacle", hoursPerUnit: 0.5,
      hoursSourceLabel: "Estimated basis", rate: 78, status: "ready",
    });
  });

  test("handles null hours/rate without throwing", () => {
    const row = { item_id: "abc", item_name: "x", quantity: "1", hours_per_unit: null,
                  hours_source_label: null, rate: null, rate_source_label: null,
                  adjusted_hours: null, labor_cost: null, status: "missing", basis_note: "" };
    expect(() => mapLaborRow(row)).not.toThrow();
    expect(mapLaborRow(row).hoursPerUnit).toBeNull();
  });
});

describe("mapMaterialRow", () => {
  test("maps every field", () => {
    const row = { item_id: "abc", item_name: "x", quantity: "10", unit_price: "12.5",
                  source_label: "Company price", status: "ready", basis_note: "" };
    const mapped = mapMaterialRow(row);
    expect(mapped).toMatchObject({ itemId: "abc", unitPrice: 12.5, sourceLabel: "Company price" });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm test -- api-mapping
```

Expected: FAIL — `mapLaborRow`/`mapMaterialRow` are not exported yet.

- [ ] **Step 3: Implement**

Append to `src/lib/store/api-mapping.js`:

```js
export function mapLaborRow(r) {
  return {
    itemId: r.item_id,
    itemName: r.item_name,
    quantity: Number(r.quantity),
    hoursPerUnit: r.hours_per_unit == null ? null : Number(r.hours_per_unit),
    hoursSourceLabel: r.hours_source_label ?? null,
    rate: r.rate == null ? null : Number(r.rate),
    rateSourceLabel: r.rate_source_label ?? null,
    adjustedHours: r.adjusted_hours == null ? null : Number(r.adjusted_hours),
    laborCost: r.labor_cost == null ? null : Number(r.labor_cost),
    status: r.status,
    basisNote: r.basis_note ?? "",
  };
}

export function mapMaterialRow(r) {
  return {
    itemId: r.item_id,
    itemName: r.item_name,
    quantity: Number(r.quantity),
    unitPrice: r.unit_price == null ? null : Number(r.unit_price),
    sourceLabel: r.source_label ?? null,
    status: r.status,
    basisNote: r.basis_note ?? "",
  };
}
```

In `src/lib/store/api.js`, add the import at the top:

```js
import { mapLaborRow, mapMaterialRow } from "./api-mapping.js";
```

(merge into the existing `import { ... } from "./api-mapping.js"` line if one exists — check first).

Add the twelve store methods inside `createApiStore()`, following the existing `request()`-wrapper pattern already used elsewhere in this function (check `getSnapshot`/`me` for the exact `request()` helper's signature and adapt these calls to it rather than inventing a second fetch pattern):

```js
  async function getLaborRows(projectId) {
    const body = await request(`/api/projects/${projectId}/labor`);
    return { pricingSource: body.pricing_source, pricingNote: body.pricing_note, rows: body.rows.map(mapLaborRow) };
  }

  async function setLaborLine(itemId, changes) {
    return request(`/api/items/${itemId}/labor`, { method: "PATCH", body: JSON.stringify(changes) });
  }

  async function getMaterialRows(projectId) {
    const body = await request(`/api/projects/${projectId}/material-pricing`);
    return { pricingSource: body.pricing_source, pricingNote: body.pricing_note, rows: body.rows.map(mapMaterialRow) };
  }

  async function setMaterialPrice(itemId, changes) {
    return request(`/api/items/${itemId}/material-price`, { method: "PATCH", body: JSON.stringify(changes) });
  }

  async function getCompanyLaborRates() {
    return request("/api/company/labor-rates");
  }

  async function setCompanyLaborRates(values) {
    return request("/api/company/labor-rates", { method: "PUT", body: JSON.stringify(values) });
  }

  async function getCompanyMaterialPrices() {
    return request("/api/company/material-prices");
  }

  async function setCompanyMaterialPrice(itemName, values) {
    return request(`/api/company/material-prices/${encodeURIComponent(itemName)}`, { method: "PUT", body: JSON.stringify(values) });
  }

  async function deleteCompanyMaterialPrice(itemName) {
    return request(`/api/company/material-prices/${encodeURIComponent(itemName)}`, { method: "DELETE" });
  }

  async function getCompanyLaborHoursOverrides() {
    return request("/api/company/labor-hours-overrides");
  }

  async function setCompanyLaborHoursOverride(itemName, hoursPerUnit) {
    return request(`/api/company/labor-hours-overrides/${encodeURIComponent(itemName)}`, {
      method: "PUT", body: JSON.stringify({ hoursPerUnit }),
    });
  }

  async function deleteCompanyLaborHoursOverride(itemName) {
    return request(`/api/company/labor-hours-overrides/${encodeURIComponent(itemName)}`, { method: "DELETE" });
  }
```

Add all twelve function names to the object `createApiStore()` returns, matching how every other store method (e.g. `getSnapshot`, `me`) is already listed there.

If `request()`'s actual signature differs from `request(path, { method, body })` sketched above (check its real definition before assuming), adapt every call above to match it exactly rather than guessing — this is the single most likely mismatch point in this task, since every other store method must already follow whatever the real signature is.

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- api-mapping
npm run build
```

Expected: all PASS, build clean.

- [ ] **Step 5: Commit**

```bash
git add src/lib/store/api.js src/lib/store/api-mapping.js src/lib/store/api-mapping.test.js
git commit -m "Add store methods for Labor and Material Pricing"
```

---

### Task 10: Labor workspace

**Files:**
- Create: `src/components/labor/LaborWorkspace.jsx`
- Create: `src/components/labor/laborColumns.js`
- Test: `src/components/labor/LaborWorkspace.test.jsx`

**Interfaces:**
- Consumes: `store.getLaborRows`, `store.setLaborLine` (Task 9); `useWorkspaceContext()` (existing, from `src/components/project/useWorkspaceContext.js`).
- Produces: the `LaborWorkspace` component, mounted at a route by Task 12.

- [ ] **Step 1: Read the existing pattern first**

Read `src/components/takeoff/TakeoffSpreadsheet.jsx` and `src/components/takeoff/spreadsheetColumns.js` in full before writing this task — `LaborWorkspace.jsx` follows the exact same shape (a data-driven `COLUMNS` array in its own file, `useWorkspaceContext()` for the shared store, `AppTopBar`, tabular numerals via `className="tabular"` on every quantity/cost cell, a `NONE = "—"` mark for absent values) rather than inventing new conventions. `TakeoffSpreadsheet.test.jsx` is the template for this task's test file's setup/rendering style.

- [ ] **Step 2: Write the failing test**

Create `src/components/labor/LaborWorkspace.test.jsx`, adapting `TakeoffSpreadsheet.test.jsx`'s exact render/store-mock setup to a store that returns from `getLaborRows`:

```jsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import LaborWorkspace from "./LaborWorkspace.jsx";

// Adapt this mock to match useWorkspaceContext()'s real shape and
// whatever provider/wrapper TakeoffSpreadsheet.test.jsx already uses --
// do not invent a second test-setup convention.
const baseRows = [
  { itemId: "i1", itemName: "20A duplex receptacle", quantity: 10, hoursPerUnit: null,
    hoursSourceLabel: null, rate: null, rateSourceLabel: null, adjustedHours: null,
    laborCost: null, status: "missing", basisNote: "" },
];

describe("LaborWorkspace", () => {
  test("renders a row per item, with the Missing information status when nothing resolves", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setLaborLine: vi.fn(),
    };
    render(<LaborWorkspace store={store} projectId="p1" />);
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    expect(screen.getByText(/missing information/i)).toBeInTheDocument();
  });

  test("shows the source label and basis note when a row resolves from the estimated basis", async () => {
    const rows = [{ ...baseRows[0], hoursPerUnit: 0.5, hoursSourceLabel: "Estimated basis",
                     rate: 78, rateSourceLabel: "Estimated basis", adjustedHours: 5, laborCost: 390,
                     status: "ready", basisNote: "Rate based on Sacramento, CA area cost data." }];
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "x", rows }),
      setLaborLine: vi.fn(),
    };
    render(<LaborWorkspace store={store} projectId="p1" />);
    await waitFor(() => expect(screen.getByText("Estimated basis")).toBeInTheDocument());
  });

  test("editing hours calls setLaborLine and refreshes the row", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setLaborLine: vi.fn().mockResolvedValue({}),
    };
    render(<LaborWorkspace store={store} projectId="p1" />);
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    const hoursInput = screen.getByLabelText(/hours per unit/i);
    fireEvent.change(hoursInput, { target: { value: "0.75" } });
    fireEvent.blur(hoursInput);
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { hoursOverride: 0.75 }));
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

```bash
npm test -- LaborWorkspace
```

Expected: FAIL — the component doesn't exist yet.

- [ ] **Step 4: Implement**

Create `src/components/labor/laborColumns.js`:

```js
/* ============================================================
   laborColumns.js — what the Labor workspace shows. Mirrors
   spreadsheetColumns.js's data-driven shape: the header row and the
   body read one list rather than two that can drift.
   ============================================================ */

const NONE = "—";
const money = (n) => "$" + Math.round(Number(n)).toLocaleString();

export const COLUMNS = [
  { key: "itemName", label: "Item", align: "left", render: (row) => row.itemName },
  { key: "quantity", label: "Quantity", align: "right", render: (row) => row.quantity },
  {
    key: "hoursPerUnit", label: "Hours/unit", align: "right",
    render: (row) => (row.hoursPerUnit != null ? row.hoursPerUnit : NONE),
  },
  { key: "hoursSourceLabel", label: "Hours source", align: "left", render: (row) => row.hoursSourceLabel || NONE },
  {
    key: "rate", label: "Rate", align: "right",
    render: (row) => (row.rate != null ? money(row.rate) + "/hr" : NONE),
  },
  { key: "rateSourceLabel", label: "Rate source", align: "left", render: (row) => row.rateSourceLabel || NONE },
  {
    key: "adjustedHours", label: "Adj. hours", align: "right",
    render: (row) => (row.adjustedHours != null ? row.adjustedHours.toFixed(2) : NONE),
  },
  {
    key: "laborCost", label: "Labor cost", align: "right",
    render: (row) => (row.laborCost != null ? money(row.laborCost) : NONE),
  },
];
```

Create `src/components/labor/LaborWorkspace.jsx`:

```jsx
/* ============================================================
   LaborWorkspace.jsx — spec §12, the Labor workspace.

   A plain table in this codebase's established style
   (TakeoffSpreadsheet.jsx): tabular numerals on every quantity/cost,
   inline edit on a cell, autosave with no save button. The
   precedence-tier label ("Estimated basis," "Company standard") renders
   as its own tag next to the four-label status pill, never merged into
   one badge -- see the design doc's "Status" section.
   ============================================================ */

import { useEffect, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import { STATUS } from "../../lib/vocabulary.js";
import { COLUMNS } from "./laborColumns.js";

export default function LaborWorkspace({ store, projectId }) {
  const [rows, setRows] = useState([]);
  const [pricingSource, setPricingSource] = useState(null);
  const [pricingNote, setPricingNote] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    const result = await store.getLaborRows(projectId);
    setRows(result.rows);
    setPricingSource(result.pricingSource);
    setPricingNote(result.pricingNote);
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, [projectId]);

  const editHours = async (itemId, value) => {
    const n = Number(value);
    if (Number.isNaN(n)) return;
    await store.setLaborLine(itemId, { hoursOverride: n });
    await load();
  };

  return (
    <>
      <AppTopBar title="Labor" />
      <div className="page">
        <h1 className="page-heading">Labor</h1>

        {pricingSource !== "llm" && (
          <p className="muted">
            This project has no automatic labor-hour estimate yet — reprocess it with the pricing assistant
            available, or set hours and rates directly on each row below.
          </p>
        )}

        {loading ? (
          <p className="muted">Loading…</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Status</th>
                {COLUMNS.map((c) => (
                  <th key={c.key} style={{ textAlign: c.align }}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const meta = STATUS[row.status];
                return (
                  <tr key={row.itemId}>
                    <td>
                      <span className="pill" style={{ color: meta.color, background: meta.tint }}>
                        {meta.label}
                      </span>
                    </td>
                    {COLUMNS.map((c) => (
                      <td key={c.key} className="tabular" style={{ textAlign: c.align }}>
                        {c.key === "hoursPerUnit" ? (
                          <input
                            type="number"
                            step="0.01"
                            aria-label="Hours per unit"
                            defaultValue={row.hoursPerUnit ?? ""}
                            onBlur={(e) => editHours(row.itemId, e.target.value)}
                            className="field field--number tabular"
                          />
                        ) : (
                          c.render(row)
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
npm test -- LaborWorkspace
```

Expected: all PASS. Adapt the component/test to whatever `AppTopBar`'s and `useWorkspaceContext()`'s real prop signatures turn out to be if they differ from what's sketched here — check `TakeoffSpreadsheet.jsx`'s actual usage before assuming.

- [ ] **Step 6: Commit**

```bash
git add src/components/labor/LaborWorkspace.jsx src/components/labor/laborColumns.js src/components/labor/LaborWorkspace.test.jsx
git commit -m "Add the Labor workspace"
```

---

### Task 11: Material Pricing workspace

**Files:**
- Create: `src/components/pricing/MaterialPricingWorkspace.jsx`
- Create: `src/components/pricing/pricingColumns.js`
- Test: `src/components/pricing/MaterialPricingWorkspace.test.jsx`

**Interfaces:**
- Consumes: `store.getMaterialRows`, `store.setMaterialPrice` (Task 9).
- Produces: the `MaterialPricingWorkspace` component, mounted by Task 12.

- [ ] **Step 1: Write the failing test**

Create `src/components/pricing/MaterialPricingWorkspace.test.jsx`, following `LaborWorkspace.test.jsx`'s exact structure from Task 10:

```jsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import MaterialPricingWorkspace from "./MaterialPricingWorkspace.jsx";

const baseRows = [
  { itemId: "i1", itemName: "20A duplex receptacle", quantity: 10, unitPrice: null,
    sourceLabel: null, status: "missing", basisNote: "" },
];

describe("MaterialPricingWorkspace", () => {
  test("renders Missing information when nothing resolves", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setMaterialPrice: vi.fn(),
    };
    render(<MaterialPricingWorkspace store={store} projectId="p1" />);
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    expect(screen.getByText(/missing information/i)).toBeInTheDocument();
  });

  test("setting a project price calls setMaterialPrice with source project_price", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setMaterialPrice: vi.fn().mockResolvedValue({}),
    };
    render(<MaterialPricingWorkspace store={store} projectId="p1" />);
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    const priceInput = screen.getByLabelText(/unit price/i);
    fireEvent.change(priceInput, { target: { value: "15.5" } });
    fireEvent.blur(priceInput);
    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", { priceOverride: 15.5, source: "project_price" })
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm test -- MaterialPricingWorkspace
```

Expected: FAIL — the component doesn't exist yet.

- [ ] **Step 3: Implement**

Create `src/components/pricing/pricingColumns.js`:

```js
const NONE = "—";
const money = (n) => "$" + Number(n).toFixed(2);

export const COLUMNS = [
  { key: "itemName", label: "Material", align: "left", render: (row) => row.itemName },
  { key: "quantity", label: "Quantity", align: "right", render: (row) => row.quantity },
  {
    key: "unitPrice", label: "Unit price", align: "right",
    render: (row) => (row.unitPrice != null ? money(row.unitPrice) : NONE),
  },
  { key: "sourceLabel", label: "Source", align: "left", render: (row) => row.sourceLabel || NONE },
];
```

Create `src/components/pricing/MaterialPricingWorkspace.jsx`:

```jsx
/* ============================================================
   MaterialPricingWorkspace.jsx — spec §13, the Material Pricing
   workspace. Same shape as LaborWorkspace.jsx -- see that file's header
   comment for the conventions both follow.
   ============================================================ */

import { useEffect, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import { STATUS } from "../../lib/vocabulary.js";
import { COLUMNS } from "./pricingColumns.js";

export default function MaterialPricingWorkspace({ store, projectId }) {
  const [rows, setRows] = useState([]);
  const [pricingSource, setPricingSource] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    const result = await store.getMaterialRows(projectId);
    setRows(result.rows);
    setPricingSource(result.pricingSource);
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, [projectId]);

  const editPrice = async (itemId, value) => {
    const n = Number(value);
    if (Number.isNaN(n)) return;
    await store.setMaterialPrice(itemId, { priceOverride: n, source: "project_price" });
    await load();
  };

  return (
    <>
      <AppTopBar title="Material pricing" />
      <div className="page">
        <h1 className="page-heading">Material pricing</h1>

        {pricingSource !== "llm" && (
          <p className="muted">
            This project has no automatic regional price estimate yet — reprocess it with the pricing
            assistant available, or set a price directly on each row below.
          </p>
        )}

        {loading ? (
          <p className="muted">Loading…</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Status</th>
                {COLUMNS.map((c) => (
                  <th key={c.key} style={{ textAlign: c.align }}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const meta = STATUS[row.status];
                return (
                  <tr key={row.itemId}>
                    <td>
                      <span className="pill" style={{ color: meta.color, background: meta.tint }}>
                        {meta.label}
                      </span>
                    </td>
                    {COLUMNS.map((c) => (
                      <td key={c.key} className="tabular" style={{ textAlign: c.align }}>
                        {c.key === "unitPrice" ? (
                          <input
                            type="number"
                            step="0.01"
                            aria-label="Unit price"
                            defaultValue={row.unitPrice ?? ""}
                            onBlur={(e) => editPrice(row.itemId, e.target.value)}
                            className="field field--number tabular"
                          />
                        ) : (
                          c.render(row)
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- MaterialPricingWorkspace
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/pricing/MaterialPricingWorkspace.jsx src/components/pricing/pricingColumns.js src/components/pricing/MaterialPricingWorkspace.test.jsx
git commit -m "Add the Material Pricing workspace"
```

---

### Task 12: Route wiring and nav flip

**Files:**
- Modify: `src/routes.jsx`
- Modify: `src/components/shell/ProjectNav.jsx`
- Test: `src/components/shell/nav.test.jsx`

**Interfaces:**
- Consumes: `LaborWorkspace` (Task 10), `MaterialPricingWorkspace` (Task 11).

- [ ] **Step 1: Read the existing routing pattern**

Read `src/routes.jsx` in full, and find how `TakeoffSpreadsheet` is currently routed (its path segment, e.g. `/projects/:id/spreadsheet`) — `labor` and `pricing` need the exact same shape at `/projects/:id/labor` and `/projects/:id/pricing`, matching the slugs already declared in `ProjectNav.jsx`'s `GROUPS` array (`slug: "labor"`, `slug: "pricing"`).

- [ ] **Step 2: Write the failing test**

Check `src/components/shell/nav.test.jsx`'s existing assertions about disabled/enabled workspace counts (it likely asserts a specific count of "not built yet" items, or checks specific slugs' `aria-disabled` state) before writing a new assertion — adapt to its actual current shape rather than guessing. Add or modify an assertion so that `labor` and `pricing` render as real links, not disabled spans, e.g.:

```jsx
test("Labor and Material pricing render as enabled workspace links", () => {
  // Adapt this render call to match this file's existing setup exactly.
  render(<ProjectNav projectId="p1" project={someProject} />);
  expect(screen.getByRole("link", { name: "Labor" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Material pricing" })).toBeInTheDocument();
  expect(screen.queryByText(/labor.*not built yet/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run test to verify it fails**

```bash
npm test -- nav.test
```

Expected: FAIL — `getByRole("link", { name: "Labor" })` doesn't find a link, since `labor` is still `built: false` and renders as a disabled `<span role="link" aria-disabled="true">`.

- [ ] **Step 4: Implement**

In `src/components/shell/ProjectNav.jsx`, inside the `GROUPS` array's `"Cost"` group, change:

```js
      { slug: "labor", label: "Labor", built: false, Icon: Users },
      { slug: "pricing", label: "Material pricing", built: false, Icon: DollarSign },
```

to:

```js
      { slug: "labor", label: "Labor", built: true, Icon: Users },
      { slug: "pricing", label: "Material pricing", built: true, Icon: DollarSign },
```

`assemblies` and `estimate` stay `built: false` — untouched by this plan.

In `src/routes.jsx`, add the two new routes alongside the existing `spreadsheet` route, following its exact pattern (check whether routes pass `store`/`projectId` as props directly or through a layout's outlet context — match whichever `TakeoffSpreadsheet`'s route actually does):

```jsx
import LaborWorkspace from "./components/labor/LaborWorkspace.jsx";
import MaterialPricingWorkspace from "./components/pricing/MaterialPricingWorkspace.jsx";

// ... inside the project route's children, alongside the existing "spreadsheet" route:
<Route path="labor" element={<LaborWorkspace store={store} projectId={projectId} />} />
<Route path="pricing" element={<MaterialPricingWorkspace store={store} projectId={projectId} />} />
```

Adjust the exact `store`/`projectId` prop wiring to match how the neighboring `spreadsheet` route actually supplies them — read that route's JSX precisely before writing these two lines.

- [ ] **Step 5: Run tests to verify they pass**

```bash
npm test -- nav.test
npm test
npm run build
```

Expected: all PASS, including the full suite and a clean build — this wires real navigation to real screens for the first time in this plan.

- [ ] **Step 6: Commit**

```bash
git add src/routes.jsx src/components/shell/ProjectNav.jsx src/components/shell/nav.test.jsx
git commit -m "Route Labor and Material pricing, flip both to built in the project nav"
```

---

### Task 13: Migrate `CompanySettings.jsx`'s Labor/Material tabs off `localStorage`

**Files:**
- Modify: `src/components/settings/CompanySettings.jsx`
- Test: `src/components/settings/CompanySettings.test.jsx`

**Interfaces:**
- Consumes: `store.getCompanyLaborRates`, `store.setCompanyLaborRates`, `store.getCompanyMaterialPrices`, `store.setCompanyMaterialPrice`, `store.deleteCompanyMaterialPrice` (Task 9).

- [ ] **Step 1: Read the existing component and test fully**

Read `src/components/settings/CompanySettings.jsx` and `src/components/settings/CompanySettings.test.jsx` in full before editing — this task changes three of six tabs (`labor`, `adjustments`, `material`) and must leave `profile`, `markup`, `export` byte-identical, still reading `getCompanySettings()`/`setCompanyValue()` from `settingsStore.js`.

- [ ] **Step 2: Write the failing test**

Append to `CompanySettings.test.jsx`, matching its existing render/mock conventions:

```jsx
test("Labor rates tab reads and writes through the store, not localStorage", async () => {
  const store = {
    getCompanyLaborRates: vi.fn().mockResolvedValue({ journeyman_rate: "68.00", foreman_rate: "82.00", apprentice_rate: "41.00", productivity_factor: "1.000", updated_at: "2026-08-01T00:00:00Z" }),
    setCompanyLaborRates: vi.fn().mockResolvedValue({}),
  };
  // Adapt to however this file already renders CompanySettings with a store prop.
  render(<CompanySettings store={store} />);
  fireEvent.click(screen.getByRole("tab", { name: /labor rates/i }));
  await waitFor(() => expect(screen.getByDisplayValue("68")).toBeInTheDocument());
});

test("Material pricing tab lists company prices and supports add/remove", async () => {
  const store = {
    getCompanyMaterialPrices: vi.fn().mockResolvedValue([
      { item_name: "20A duplex receptacle", unit_price: "13.50", effective_date: "2026-08-01", updated_at: "2026-08-01T00:00:00Z" },
    ]),
    setCompanyMaterialPrice: vi.fn().mockResolvedValue({}),
    deleteCompanyMaterialPrice: vi.fn().mockResolvedValue({}),
  };
  render(<CompanySettings store={store} />);
  fireEvent.click(screen.getByRole("tab", { name: /material pricing/i }));
  await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
});
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
npm test -- CompanySettings
```

Expected: FAIL — the component doesn't accept a `store` prop yet, and the labor tab still reads `settingsStore.js`.

- [ ] **Step 4: Implement**

In `src/components/settings/CompanySettings.jsx`:

- Add a `store` prop to the component's signature.
- For the `labor` and `adjustments` tabs: replace the `FIELDS.labor`/`FIELDS.adjustments` rendering path with one that, on mount, calls `store.getCompanyLaborRates()` and holds the five values (`journeymanRate`, `foremanRate`, `apprenticeRate`, `productivityFactor`, `updatedAt`) in local state; each field's `onChange` calls `store.setCompanyLaborRates({ ...current, [field]: newValue })` then re-fetches. Keep the exact same visual field list (`journeymanRate`/`foremanRate`/`apprenticeRate` under "Labor rates", `productivityFactor` under "Labor adjustments") and the "Company default · updated {date}" caption pattern the file already uses for every other field — just point its data source at the store instead of `settingsStore.js`.
- For the `material` tab: replace the single `materialSource` text field with a small list (item name, unit price, effective date, a remove button) sourced from `store.getCompanyMaterialPrices()`, plus an add-row form (item name text input, unit price number input) that calls `store.setCompanyMaterialPrice(itemName, { unitPrice, effectiveDate: today })` on submit. Removing a row calls `store.deleteCompanyMaterialPrice(itemName)`.
- `profile`, `markup`, `export` tabs: leave every line touching them completely unchanged, still reading `getCompanySettings()`/`setCompanyValue()` from `settingsStore.js`.

Update whatever renders `<CompanySettings />` (its route in `routes.jsx`) to pass the `store` prop, matching how every other route already passes `store` to its screen.

- [ ] **Step 5: Run tests to verify they pass**

```bash
npm test -- CompanySettings
npm test
npm run build
```

Expected: all PASS, including every pre-existing test in `CompanySettings.test.jsx` for the three untouched tabs.

- [ ] **Step 6: Commit**

```bash
git add src/components/settings/CompanySettings.jsx src/components/settings/CompanySettings.test.jsx src/routes.jsx
git commit -m "Move Labor rates, Labor adjustments, and Material pricing off localStorage"
```

---

## Self-review notes (from writing this plan)

**Spec coverage:** every "In scope" item from the design doc has a task — company libraries (Task 2, 7), project overrides (Task 2, 4), precedence chain (Task 3, 6), `pricing_source` gating (Task 1, 3), undo (Task 5), tenancy (Task 8), `CompanySettings.jsx` migration (Task 13), both workspace screens and nav wiring (Tasks 10-12).

**Deviation from the design doc, one, deliberate:** the doc's endpoint list didn't split `GET`/mutation work by task; this plan splits mutations (Task 4) before reads (Task 6) so the undo-relevant `labor_edit`/`material_price_edit` actions exist and are tested before Task 5 has to reverse them, and so Task 6's `GET` tests can exercise real rows Task 4 already knows how to create.

**Type/name consistency checked:** `resolve_material_price`/`resolve_labor`'s signatures (Task 3) match exactly how Task 6's endpoints call them. `LaborLineUpdateIn`'s field names (Task 4) match `ProjectLaborLine`'s column names (Task 2) match `resolve_labor`'s `override.*` attribute reads (Task 3) match `LABOR_LINE_SNAPSHOT_TYPES`'s keys (Task 5) — traced end to end, no drift. `mapLaborRow`/`mapMaterialRow` (Task 9) read exactly the field names `LaborRowOut`/`MaterialRowOut` (Task 6) serialize.

**Known gap left to the implementer's judgment, flagged rather than guessed:** Tasks 9-13's exact frontend plumbing (the real signature of `request()` in `api.js`, whether routes pass `store`/`projectId` as props or via outlet context, `AppTopBar`'s real prop list) depends on code this plan's author read but a fresh implementer must re-read for themselves — each task says so explicitly rather than presenting an invented signature as fact.
