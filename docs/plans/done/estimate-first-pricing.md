# Estimate-first pricing — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-09-18
**Spec:** [`docs/specs/estimate-first-pricing.md`](../specs/estimate-first-pricing.md). Read it first; every decision below is made there.

**Goal:** Every countable item gets a dated, located market estimate from 1build or Google Shopping the day it is counted, and an estimator can upload a supplier's filled-in price sheet that outranks it.

**Architecture:** A new worker job kind `price` looks items up (cache → source → `item_market_prices`), queued when a run's last sheet finishes; `pricing.resolve_material_price` gains a "Market estimate" tier under "Company price" and a "Supplier quote" tier above it. A second job kind `price_sheet` parses an uploaded `.xlsx`/`.csv` into a preview the estimator applies through one `commit()`. The API never calls a source; the worker holds both keys.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (api), the existing `jobs` table and `sandbox.py` worker, `openpyxl` (new), `urllib` for the two HTTP clients (no new HTTP dependency), React + the existing `DataGrid`.

## Global constraints

- Copy: sentence case; no "successfully," no "please," no exclamation marks; **no vendor name, model name, or confidence on any row or warning** — tier label is "Market estimate," basis note is a place and a date.
- Every warning carries `title, found, why, fix, where`.
- Status values on a row are only `ready | attention | missing | approved`.
- `app.main` never imports `app.worker` or `app.engine`; `app.worker` never imports a router (`test_worker_import_boundary.py`, `test_api_import_boundary.py` guard both — run them after every task that adds a module).
- Every new `/api/*` route gets a row in `test_tenancy.py`'s `TENANCY_TABLE` (or `MULTIPART_TENANCY_TABLE`) or its runtime guard fails.
- Every mutation goes through `actions.commit()` (project) or `record_company_action()` (company). Never a mutable table.
- Run `../.enginevenv/bin/python -m pytest` from `api/` and `npm run build` from the root before each commit.
- Commit after each task on branch `feat/estimate-first-pricing` (create it from `main` in Task 1).

## File map

```
api/app/
  config.py                          + onebuild_api_key, serpapi_key, market_lookup_monthly_cap
  jobs/schemas.py                    + "price", "price_sheet" in JOB_KINDS and timeouts
  jobs/queue.py                      + enqueue_price, enqueue_price_sheet
  documents/schemas.py               + "Pricing" in DOC_TYPES
  documents/service.py               store_upload accepts .xlsx/.csv for "Pricing"; no read job for it
  takeoff/models.py                  + MarketLookup, ItemMarketPrice, Project.postal_code, ProjectMaterialPrice.supplier_name/quote_date
  takeoff/pricing.py                 resolve_material_price(..., market=None): the two tiers
  takeoff/schemas.py                 MaterialRowOut market fields; PriceSheetPreviewOut; PriceSheetApplyIn; PostalCodeIn
  takeoff/pricing_router.py          refresh, price-request, price-sheets (upload/preview/apply), usage routes
  takeoff/undo_apply.py              supplier_quote_apply branch
  takeoff/undo.py                    "supplier_quote_apply" in REVERSIBLE
  takeoff/router.py                  PATCH /projects/{id}/postal-code; postal_code on create
  market/__init__.py
  market/classify.py                 PURE: classify_for_lookup, extract_model, parse_zip, unit_matches, lookup_key
  market/copy.py                     the six outcomes' warning copy
  market/price_sheet.py              PURE: build_request_workbook, parse_price_sheet
  worker/market_sources.py           OneBuildSource, ShoppingSource (urllib), get_sources()  -- worker only
  worker/price_job.py                @register("price")
  worker/price_sheet_job.py          @register("price_sheet")
  worker/classify_job.py             _finish_project queues price
  migrations/versions/0025_market_pricing.py
  eval/pricing_coverage.py           the after-the-fact coverage test
api/tests/
  test_market_classify.py, test_market_price_sheet.py, test_pricing.py (+), test_pricing_endpoints.py (+),
  test_worker_price.py, test_worker_price_sheet.py, test_tenancy.py (+), test_undo_redo.py (+), test_projects.py (+)
src/
  lib/store/api.js, api-mapping.js   refreshMarketEstimates, getPriceRequestUrl, uploadPriceSheet, getPriceSheetPreview, applyPriceSheet, setPostalCode
  components/pricing/pricingColumns.jsx        Range column; tier tag beside the pill
  components/pricing/MaterialPricingWorkspace.jsx   three header actions; per-row warning
  components/pricing/PriceSheetImport.jsx      upload → preview → apply modal
  components/pricing/marketOutcomeCopy.js      mirrors api/app/market/copy.py
  components/projects/NewProject.jsx           ZIP field
  components/settings/ProjectSettings.jsx      editable ZIP
```

---

### Task 1: Schema — models, migration, config, job kinds

**Files:**
- Modify: `api/app/config.py`, `api/.env.example`, `api/app/jobs/schemas.py`, `api/app/documents/schemas.py:8`, `api/app/takeoff/models.py` (Project ~line 92, ProjectMaterialPrice ~line 495, append two classes), `api/requirements.txt`
- Create: `api/migrations/versions/0025_market_pricing.py`
- Test: `api/tests/test_market_models.py`

**Interfaces:**
- Produces: `MarketLookup`, `ItemMarketPrice` ORM classes; `Project.postal_code: str | None`; `ProjectMaterialPrice.supplier_name: str`, `.quote_date: date | None`; `settings.onebuild_api_key`, `settings.serpapi_key`, `settings.market_lookup_monthly_cap`; `JOB_KINDS` includes `"price"`, `"price_sheet"`; `timeout_for("price") == 120`, `timeout_for("price_sheet") == 60`; `DOC_TYPES` includes `"Pricing"`.

- [ ] **Step 1: Branch**

```bash
git checkout main && git pull && git checkout -b feat/estimate-first-pricing
```

- [ ] **Step 2: Write the failing model test**

`api/tests/test_market_models.py`:

```python
"""The two market tables and the columns this feature adds to existing
ones exist, with the shapes the spec sets out."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.jobs.schemas import JOB_KINDS, timeout_for
from app.documents.schemas import DOC_TYPES
from app.takeoff.models import ItemMarketPrice, MarketLookup, ProjectMaterialPrice


def test_market_lookup_is_unique_per_source_query_location(db, org):
    row = MarketLookup(source="onebuild", query_key="20a duplex receptacle", location_key="78701",
                       status="priced", result={"rate": 1}, fetched_at=datetime.now(timezone.utc), billed=True, org_id=org.id)
    db.add(row); db.flush()
    dup = MarketLookup(source="onebuild", query_key="20a duplex receptacle", location_key="78701",
                       status="priced", result={}, fetched_at=datetime.now(timezone.utc), billed=True, org_id=org.id)
    db.add(dup)
    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_item_market_price_is_one_per_item_and_cascades(db, item, org):
    lookup = MarketLookup(source="onebuild", query_key="q", location_key="78701", status="priced", result={},
                          fetched_at=datetime.now(timezone.utc), billed=True, org_id=org.id)
    db.add(lookup); db.flush()
    mp = ItemMarketPrice(item_id=item.id, lookup_id=lookup.id, outcome="priced", source="onebuild", query="q",
                         unit_price=Decimal("12.40"), price_low=Decimal("12.40"), price_high=Decimal("12.40"),
                         unit="ea", location_label="Travis County, TX", fetched_at=datetime.now(timezone.utc))
    db.add(mp); db.flush()
    db.delete(item); db.flush()
    assert db.scalars(select(ItemMarketPrice).where(ItemMarketPrice.item_id == item.id)).first() is None


def test_project_material_price_carries_supplier_fields(db, item):
    row = ProjectMaterialPrice(item_id=item.id, price_override=Decimal("9.10"), source="supplier_quote",
                               supplier_name="Codale", quote_date=date(2026, 9, 18))
    db.add(row); db.flush()
    db.refresh(row)
    assert row.supplier_name == "Codale" and row.quote_date == date(2026, 9, 18)


def test_project_has_postal_code(project):
    assert project.postal_code is None


def test_job_kinds_and_doc_types_gained_their_values():
    assert "price" in JOB_KINDS and "price_sheet" in JOB_KINDS
    assert timeout_for("price") == 120 and timeout_for("price_sheet") == 60
    assert "Pricing" in DOC_TYPES
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_market_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'ItemMarketPrice'`

- [ ] **Step 4: Config and env**

`api/app/config.py`, inside `Settings` after `blob_region`:

```python
    # Market pricing (docs/specs/estimate-first-pricing.md). Both keys
    # are optional and read only by the worker; absence marks a lookup
    # "unavailable", never an error. The cap is per org per calendar
    # month and is what stops one 400-item set from spending the budget.
    onebuild_api_key: str = ""
    serpapi_key: str = ""
    market_lookup_monthly_cap: int = 2000
```

`api/.env.example`, append:

```
# Optional. Market estimates (docs/specs/estimate-first-pricing.md).
# Read by the worker only. Without them every market row reads
# "Market estimates aren't set up" -- not an error.
ONEBUILD_API_KEY=
SERPAPI_KEY=
MARKET_LOOKUP_MONTHLY_CAP=2000
```

`api/requirements.txt`, append: `openpyxl>=3.1`. Then `../.enginevenv/bin/pip install -r requirements.txt`.

- [ ] **Step 5: Job kinds and doc types**

`api/app/jobs/schemas.py`:

```python
JOB_KINDS = ("read", "classify", "sheet", "render", "price", "price_sheet")
...
_DEFAULT_TIMEOUTS = {"read": 120, "classify": 300, "sheet": 180, "render": 300, "price": 120, "price_sheet": 60}
```

`api/app/documents/schemas.py:8`:

```python
DOC_TYPES = ("Drawings", "Specifications", "Addendum", "Scope", "Other", "Pricing")
```

- [ ] **Step 6: Models**

`api/app/takeoff/models.py` — on `Project`, after `location`:

```python
    # The ZIP both market sources want. Parsed from `location` once by
    # migration 0025, editable on project settings. None means every
    # market lookup is "location_needed" -- never a national number.
    postal_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
```

On `ProjectMaterialPrice`, after `reason`:

```python
    # source == "supplier_quote" only: who quoted and when, for the
    # row's basis note. Blank/None on the other two sources.
    supplier_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    quote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
```

and widen its `source` comment to `# "project_price" | "allowance" | "supplier_quote"`.

Append at end of file (imports `Boolean`, `JSONB`, `UniqueConstraint`, `Date` already exist in the module):

```python
class MarketLookup(Base):
    """One call to one market source, cached (estimate-first-pricing
    §4). Org-independent by design: public market data keyed by what
    was asked and where, reused across projects and orgs. The row is
    also the meter -- `billed` rows count against `org_id`'s cap."""

    __tablename__ = "market_lookups"
    __table_args__ = (UniqueConstraint("source", "query_key", "location_key", name="uq_market_lookup"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(20))        # "onebuild" | "shopping"
    query_key: Mapped[str] = mapped_column(String(300))
    location_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))        # "priced" | "no_match" | "failed"
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    billed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)


class ItemMarketPrice(Base):
    """The market estimate for one item, one row per item at most --
    derived, not a person's judgment, so outside ITEM_SNAPSHOT_TYPES
    like ItemEvidenceImage. `outcome` is the closed set in
    app/market/copy.py; only "priced" resolves in the chain."""

    __tablename__ = "item_market_prices"

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    lookup_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("market_lookups.id", ondelete="SET NULL"), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    query: Mapped[str] = mapped_column(String(300), default="", server_default="")
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_low: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_high: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    labor_rate_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    unit: Mapped[str] = mapped_column(String(10), default="", server_default="")
    location_label: Mapped[str] = mapped_column(String(100), default="", server_default="")
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
```

- [ ] **Step 7: Migration**

`api/migrations/versions/0025_market_pricing.py`:

```python
"""market_pricing

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-18 00:00:00.000000

docs/specs/estimate-first-pricing.md: the two market tables, the
project ZIP (backfilled from `location`'s trailing 5-digit token, the
same rule regions.py reads a state by), the supplier fields on
project_material_prices, and two new job kinds. Job kinds are spelled
out here rather than imported, per 0020/0021's convention.
"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = '0025'
down_revision: Union[str, None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = "'read', 'classify', 'sheet', 'render', 'price', 'price_sheet'"
_OLD_KINDS = "'read', 'classify', 'sheet', 'render'"


def upgrade() -> None:
    op.add_column('projects', sa.Column('postal_code', sa.String(length=10), nullable=True))
    conn = op.get_bind()
    for pid, location in conn.execute(sa.text("SELECT id, location FROM projects")).fetchall():
        m = re.search(r"\b(\d{5})(?:-\d{4})?\s*(?:USA?)?\s*$", location or "", re.IGNORECASE)
        if m:
            conn.execute(sa.text("UPDATE projects SET postal_code = :z WHERE id = :id"), {"z": m.group(1), "id": pid})

    op.add_column('project_material_prices', sa.Column('supplier_name', sa.String(length=200), nullable=False, server_default=''))
    op.add_column('project_material_prices', sa.Column('quote_date', sa.Date(), nullable=True))

    op.create_table(
        'market_lookups',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('query_key', sa.String(length=300), nullable=False),
        sa.Column('location_key', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('result', JSONB, nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('billed', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False),
        sa.UniqueConstraint('source', 'query_key', 'location_key', name='uq_market_lookup'),
    )
    op.create_index('ix_market_lookups_org_id', 'market_lookups', ['org_id'])
    op.create_index('ix_market_lookups_org_fetched', 'market_lookups', ['org_id', 'fetched_at'])

    op.create_table(
        'item_market_prices',
        sa.Column('item_id', UUID(as_uuid=True), sa.ForeignKey('items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('lookup_id', UUID(as_uuid=True), sa.ForeignKey('market_lookups.id', ondelete='SET NULL'), nullable=True),
        sa.Column('outcome', sa.String(length=20), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('query', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('unit_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('price_low', sa.Numeric(10, 2), nullable=True),
        sa.Column('price_high', sa.Numeric(10, 2), nullable=True),
        sa.Column('labor_rate_per_unit', sa.Numeric(10, 2), nullable=True),
        sa.Column('unit', sa.String(length=10), nullable=False, server_default=''),
        sa.Column('location_label', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_id', UUID(as_uuid=True), nullable=True),
    )

    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_KINDS})")


def downgrade() -> None:
    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_OLD_KINDS})")
    op.drop_table('item_market_prices')
    op.drop_index('ix_market_lookups_org_fetched', table_name='market_lookups')
    op.drop_index('ix_market_lookups_org_id', table_name='market_lookups')
    op.drop_table('market_lookups')
    op.drop_column('project_material_prices', 'quote_date')
    op.drop_column('project_material_prices', 'supplier_name')
    op.drop_column('projects', 'postal_code')
```

- [ ] **Step 8: Run the model test and the whole suite**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_market_models.py tests/test_jobs_model.py tests/test_takeoff_models.py -v`
Expected: PASS. (The test database is created from `Base.metadata`, so the models are what the tests see; the migration is exercised by `docker compose run --rm api alembic upgrade head` in Task 12.)

- [ ] **Step 9: Commit**

```bash
git add api/app/config.py api/.env.example api/requirements.txt api/app/jobs/schemas.py api/app/documents/schemas.py api/app/takeoff/models.py api/migrations/versions/0025_market_pricing.py api/tests/test_market_models.py
git commit -m "Market pricing: the two tables, the project ZIP, supplier fields, two job kinds"
```

---

### Task 2: The two new tiers in `resolve_material_price`

**Files:**
- Modify: `api/app/takeoff/pricing.py:36-61`
- Create: `api/app/market/__init__.py` (empty), `api/app/market/copy.py`
- Test: `api/tests/test_pricing.py` (append), `api/tests/test_market_copy.py`

**Interfaces:**
- Produces: `resolve_material_price(item, project, override, company_price, market=None) -> MaterialResolution`; `MaterialResolution` gains `price_low: Decimal | None`, `price_high: Decimal | None`, `market_outcome: str | None`; `WIDE_RANGE_RATIO = Decimal("0.5")`; `market.copy.OUTCOMES: tuple[str, ...]`, `market.copy.warning_for(outcome: str, *, query: str, sheet_number: str, description: str) -> dict` (the four-field dict plus `title`).

- [ ] **Step 1: Failing tests for the chain**

Append to `api/tests/test_pricing.py`:

```python
# ---- Market estimate and supplier quote (estimate-first-pricing §5) ----

def _market(outcome="priced", price="10", low="8", high="12"):
    return type("M", (), {"outcome": outcome, "unit_price": Decimal(price), "price_low": Decimal(low),
                          "price_high": Decimal(high), "location_label": "Travis County, TX",
                          "fetched_at": __import__("datetime").datetime(2026, 9, 18, 12, 0),
                          "source": "onebuild"})()


def test_supplier_quote_outranks_company_price():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"price_override": Decimal("9.10"), "source": "supplier_quote",
                              "supplier_name": "Codale", "quote_date": date(2026, 9, 18)})()
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": date.today()})()
    result = resolve_material_price(item, project, override, company, market=_market())
    assert result.unit_price == Decimal("9.10")
    assert result.source_label == "Supplier quote" and result.status == "approved"
    assert result.basis_note == "Codale, Sep 18, 2026"


def test_company_price_outranks_market_estimate():
    item, project = FakeItem(), FakeProject(pricing_source=None)
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": date.today()})()
    result = resolve_material_price(item, project, None, company, market=_market())
    assert result.source_label == "Company price" and result.unit_price == Decimal("13")


def test_market_estimate_outranks_regional_baseline():
    item, project = FakeItem(), FakeProject(pricing_source="llm")
    result = resolve_material_price(item, project, None, None, market=_market())
    assert result.source_label == "Market estimate" and result.unit_price == Decimal("10")
    assert result.status == "ready"
    assert result.price_low == Decimal("8") and result.price_high == Decimal("12")
    assert result.basis_note == "Travis County, TX, Sep 18"


def test_market_estimate_wide_range_is_attention_at_the_boundary():
    item, project = FakeItem(), FakeProject(pricing_source=None)
    narrow = resolve_material_price(item, project, None, None, market=_market(price="100", low="76", high="125"))
    assert narrow.status == "ready"                      # (125-76)/100 = 0.49
    wide = resolve_material_price(item, project, None, None, market=_market(price="100", low="75", high="126"))
    assert wide.status == "attention"                    # 0.51


def test_unpriced_market_outcome_falls_through():
    item, project = FakeItem(material_cost=Decimal("0")), FakeProject(pricing_source=None)
    result = resolve_material_price(item, project, None, None, market=_market(outcome="quote_required"))
    assert result.status == "missing" and result.unit_price is None
    assert result.market_outcome == "quote_required"


def test_unpriced_market_outcome_still_reaches_regional_baseline():
    item, project = FakeItem(), FakeProject(pricing_source="llm")
    result = resolve_material_price(item, project, None, None, market=_market(outcome="no_match"))
    assert result.source_label == "Regional baseline"
```

`api/tests/test_market_copy.py`:

```python
"""Every market outcome has four-field warning copy that names no
vendor, no model, and no number (CLAUDE.md, product language)."""
import pytest

from app.market.copy import OUTCOMES, warning_for

BANNED = ("1build", "google", "serpapi", "confidence", "model", "ai ", "llm")


@pytest.mark.parametrize("outcome", [o for o in OUTCOMES if o != "priced"])
def test_each_outcome_has_four_fields_in_plain_words(outcome):
    w = warning_for(outcome, query="20A duplex receptacle", sheet_number="E2.1", description="Duplex receptacle, 20A")
    for key in ("title", "found", "why", "fix", "where"):
        assert w[key].strip(), key
    text = " ".join(w.values()).lower()
    assert not any(b in text for b in BANNED), text
    assert w["title"][0].isupper() and "!" not in text


def test_priced_has_no_warning():
    assert warning_for("priced", query="q", sheet_number="E2.1", description="d") is None
```

- [ ] **Step 2: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_pricing.py tests/test_market_copy.py -v`
Expected: FAIL — `TypeError: resolve_material_price() got an unexpected keyword argument 'market'` and `ModuleNotFoundError: app.market`.

- [ ] **Step 3: The copy module**

`api/app/market/__init__.py`: empty. `api/app/market/copy.py`:

```python
"""The market lookup's outcomes and the estimator-facing words for each
(estimate-first-pricing §5). Pure data; the worker writes the outcome,
the pricing router turns it into the warning. Nothing here names a
vendor, a model, or a number -- the row's evidence carries the place,
the date, and the sellers."""
from __future__ import annotations

OUTCOMES = ("priced", "no_match", "quote_required", "location_needed", "unavailable", "over_budget", "failed")

_COPY = {
    "quote_required": (
        "Quote required",
        "This item is engineered equipment or a lump sum, which is priced by quote rather than from a catalog.",
        "Enter the supplier's price, or upload their price sheet.",
    ),
    "no_match": (
        "No market price found",
        "No catalog item matched closely enough to price it.",
        "Enter a price, add a company price for this item, or upload a supplier price sheet.",
    ),
    "location_needed": (
        "Project location needed",
        "A market estimate is priced for a place, and this project has no ZIP code.",
        "Add the project ZIP code in project settings, then refresh market estimates.",
    ),
    "unavailable": (
        "Market estimates aren't set up",
        "This workspace has no market pricing source configured.",
        "Enter a price, or ask an administrator to set up market estimates.",
    ),
    "over_budget": (
        "Market estimates paused this month",
        "This month's market lookups have been used.",
        "Enter a price, or upload a supplier price sheet.",
    ),
    "failed": (
        "Market estimate didn't complete",
        "The lookup for this item did not finish.",
        "Refresh market estimates. If it happens again, enter a price.",
    ),
}


def warning_for(outcome: str, *, query: str, sheet_number: str, description: str) -> dict | None:
    """The four-field warning for an unpriced outcome, or None for
    "priced". `found` says what was asked; `where` says where the item's
    own description lives, which is the evidence a person checks."""
    if outcome == "priced":
        return None
    title, why, fix = _COPY[outcome]
    return {
        "title": title,
        "found": f"Looked for \"{query}\"." if query else "No lookup was made for this item.",
        "why": why,
        "fix": fix,
        "where": f"{sheet_number}, item description: {description[:120]}" if description else sheet_number,
    }
```

- [ ] **Step 4: The chain**

`api/app/takeoff/pricing.py` — extend the dataclass and the function:

```python
# A market estimate whose sellers disagree by more than half of the
# median reads Needs attention ("Wide price range"): a person looks
# before it stands. (high - low) / median, strictly greater.
WIDE_RANGE_RATIO = Decimal("0.5")


@dataclass
class MaterialResolution:
    unit_price: Decimal | None
    source_label: str | None  # "Project price" | "Allowance" | "Supplier quote" | "Company price" | "Market estimate" | "Regional baseline" | None
    status: str  # "ready" | "attention" | "missing" | "approved"
    basis_note: str = ""
    price_low: Decimal | None = None
    price_high: Decimal | None = None
    market_outcome: str | None = None


def _short_date(d) -> str:
    return f"{d:%b} {d.day}"


def resolve_material_price(item, project, override, company_price, market=None) -> MaterialResolution:
    """`override` is a ProjectMaterialPrice row or None. `company_price`
    is a CompanyMaterialPrice row (already looked up by item.name by the
    caller) or None. `market` is the item's ItemMarketPrice row or None;
    only outcome "priced" resolves, every other outcome is carried on
    the result so the row can say what happened."""
    outcome = market.outcome if market is not None else None

    if override is not None:
        if override.source == "supplier_quote":
            note = override.supplier_name or ""
            if override.quote_date is not None:
                note = f"{note}, {override.quote_date:%b} {override.quote_date.day}, {override.quote_date.year}" if note else f"{override.quote_date:%b %d, %Y}"
            return MaterialResolution(unit_price=override.price_override, source_label="Supplier quote",
                                      status="approved", basis_note=note, market_outcome=outcome)
        label = "Allowance" if override.source == "allowance" else "Project price"
        return MaterialResolution(unit_price=override.price_override, source_label=label, status="approved",
                                  market_outcome=outcome)

    if company_price is not None:
        stale = (date.today() - company_price.effective_date) > timedelta(days=STALE_PRICE_DAYS)
        status = "attention" if stale else "ready"
        return MaterialResolution(unit_price=company_price.unit_price, source_label="Company price", status=status,
                                  market_outcome=outcome)

    if market is not None and market.outcome == "priced" and market.unit_price:
        low, high, mid = market.price_low, market.price_high, market.unit_price
        wide = low is not None and high is not None and (high - low) / mid > WIDE_RANGE_RATIO
        note = market.location_label
        if market.fetched_at is not None:
            note = f"{note}, {_short_date(market.fetched_at)}" if note else _short_date(market.fetched_at)
        return MaterialResolution(unit_price=mid, source_label="Market estimate",
                                  status="attention" if wide else "ready", basis_note=note,
                                  price_low=low, price_high=high, market_outcome="priced")

    if project.pricing_source == "llm" and item.quantity and item.material_cost:
        unit_price = item.material_cost / item.quantity
        return MaterialResolution(unit_price=unit_price, source_label="Regional baseline", status="ready",
                                  basis_note=project.pricing_note, market_outcome=outcome)

    return MaterialResolution(unit_price=None, source_label=None, status="missing", market_outcome=outcome)
```

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_pricing.py tests/test_market_copy.py tests/test_pricing_endpoints.py -v`
Expected: PASS (existing callers pass no `market`, so nothing else changes).

- [ ] **Step 6: Commit**

```bash
git add api/app/takeoff/pricing.py api/app/market api/tests/test_pricing.py api/tests/test_market_copy.py
git commit -m "Pricing chain: Supplier quote above Company price, Market estimate below it"
```

---

### Task 3: Lookup classification — pure functions

**Files:**
- Create: `api/app/market/classify.py`
- Test: `api/tests/test_market_classify.py`

**Interfaces:**
- Produces:
  - `parse_zip(location: str) -> str | None`
  - `extract_model(description: str) -> tuple[str, str] | None` → `(manufacturer, model)`; manufacturer may be `""`
  - `classify_for_lookup(name: str, description: str, unit: str) -> Lookup` where `Lookup = NamedTuple(source: str | None, query: str, reason: str)`; `source` is `"onebuild" | "shopping" | None` (None with `reason == "quote_required"`)
  - `unit_matches(source_uom: str, item_unit: str) -> bool`
  - `lookup_key(query: str) -> str`
  - `QUOTE_REQUIRED_WORDS: tuple[str, ...]`

- [ ] **Step 1: Failing tests**

`api/tests/test_market_classify.py`:

```python
"""How an item is routed to a market source -- deterministic, no
network (estimate-first-pricing §3 step 1)."""
import pytest

from app.market.classify import classify_for_lookup, extract_model, lookup_key, parse_zip, unit_matches


@pytest.mark.parametrize("location, zip_", [
    ("Unalaska, AK 99685", "99685"),
    ("Springfield, IL 62701 USA", "62701"),
    ("Austin, TX 78701-1234", "78701"),
    ("Springfield, IL", None),
    ("", None),
    ("Suite 12345 Main St", None),      # a number that is not at the end is not a ZIP
])
def test_parse_zip(location, zip_):
    assert parse_zip(location) == zip_


def test_extract_model_reads_manufacturer_and_model_lines():
    desc = "C: 8' LED Vaportite\nManufacturer: Current\nModel: CVT8-LSCS-MV\nWattage: 60"
    assert extract_model(desc) == ("Current", "CVT8-LSCS-MV")


def test_extract_model_needs_a_model_line():
    assert extract_model("A: 8' LED strip fixture\nManufacturer: Signify") is None
    assert extract_model("Duplex Receptacle, 20A Flush Wall Mounted") is None


def test_extract_model_rejects_short_or_wordy_tokens():
    assert extract_model("Model: LED") is None
    assert extract_model("Model: 2x4") is None


@pytest.mark.parametrize("name, description, unit, source, reason", [
    ("Lump sum cost for wiring and conduits", "", "LS", None, "quote_required"),
    ("Switch Board MSBS", "", "EA", None, "quote_required"),
    ("ACME Boost Transformer", "", "EA", None, "quote_required"),
    ("S.P.D (Surge Protective Device)", "Manufacturer: DEHN INC.\nModel: #CG3-060", "EA", None, "quote_required"),
    ("Furnish & install new setup transformer", "", "EA", None, "quote_required"),
    ("Connection to electrical equipments", "", "EA", None, "quote_required"),
    ("Luminaire", "C: 8' LED Vaportite\nManufacturer: Current\nModel: CVT8-LSCS-MV", "EA", "shopping", "model"),
    ("20A duplex receptacle", "", "EA", "onebuild", "name"),
    ("2x4 LED troffer", "A: 8' LED strip\nManufacturer: Signify", "EA", "onebuild", "name"),
])
def test_classify_for_lookup(name, description, unit, source, reason):
    lookup = classify_for_lookup(name, description, unit)
    assert lookup.source == source and lookup.reason == reason


def test_shopping_query_is_manufacturer_then_model():
    lookup = classify_for_lookup("Luminaire", "Manufacturer: Current\nModel: CVT8-LSCS-MV", "EA")
    assert lookup.query == "Current CVT8-LSCS-MV"


def test_onebuild_query_is_the_item_name():
    assert classify_for_lookup("20A duplex receptacle", "Duplex Receptacle", "EA").query == "20A duplex receptacle"


@pytest.mark.parametrize("uom, unit, ok", [
    ("EA", "ea", True), ("EA", "EA", True), ("LF", "ft", True), ("LF", "LF", True),
    ("EA", "ft", False), ("SF", "ea", False), ("", "ea", False),
])
def test_unit_matches(uom, unit, ok):
    assert unit_matches(uom, unit) is ok


def test_lookup_key_normalizes():
    assert lookup_key("  20A  Duplex   Receptacle ") == "20a duplex receptacle"
```

- [ ] **Step 2: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_market_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: app.market.classify`

- [ ] **Step 3: Implement**

`api/app/market/classify.py`:

```python
"""Which market source prices an item, and with what query. Pure and
deterministic (estimate-first-pricing §3): a lump sum or engineered gear
is "quote required" and spends nothing; a manufacturer model number goes
to shopping; everything else goes to 1build by name. Match on whole
words, never substrings -- regions.py's docstring records why."""
from __future__ import annotations

import re
from typing import NamedTuple


class Lookup(NamedTuple):
    source: str | None      # "onebuild" | "shopping" | None
    query: str
    reason: str             # "quote_required" | "model" | "name"


# Whole-word (or whole-phrase) markers of gear that is priced by quote.
# Every entry is matched with \b on both sides, case-insensitively.
QUOTE_REQUIRED_WORDS: tuple[str, ...] = (
    "switchboard", "switch board", "switchgear", "mcc", "motor control center",
    "transformer", "spd", "surge protective", "surge protection", "generator", "ats",
    "automatic transfer", "bus duct", "busway", "vfd", "variable frequency",
    "furnish and install", "furnish & install", "connection to", "provide power for", "lump sum",
)
_QUOTE_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in QUOTE_REQUIRED_WORDS) + r")\b", re.IGNORECASE)

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\s*(?:USA?)?\s*$", re.IGNORECASE)
_MODEL_LINE_RE = re.compile(r"^\s*model\s*(?:no\.?|#|number)?\s*[:#]?\s*#?\s*(\S+)", re.IGNORECASE | re.MULTILINE)
_MANUF_LINE_RE = re.compile(r"^\s*manufacturer\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
# A model token: 6+ chars, at least one letter and one digit, only
# letters, digits, hyphens, slashes, dots. "LED" and "2x4" are not models.
_MODEL_TOKEN_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9./-]{6,}$")

_UOM_ALIASES = {
    "ea": {"ea", "each"},
    "ft": {"ft", "lf", "feet", "foot"},
    "sf": {"sf", "sqft"},
}


def parse_zip(location: str) -> str | None:
    m = _ZIP_RE.search(location or "")
    return m.group(1) if m else None


def extract_model(description: str) -> tuple[str, str] | None:
    m = _MODEL_LINE_RE.search(description or "")
    if not m:
        return None
    token = m.group(1).strip().rstrip(",;")
    if not _MODEL_TOKEN_RE.match(token):
        return None
    mf = _MANUF_LINE_RE.search(description or "")
    manufacturer = mf.group(1).strip().rstrip(".") if mf else ""
    return manufacturer, token


def classify_for_lookup(name: str, description: str, unit: str) -> Lookup:
    text = f"{name}\n{description or ''}"
    if (unit or "").strip().upper() == "LS" or _QUOTE_RE.search(text):
        return Lookup(None, "", "quote_required")
    model = extract_model(description or "")
    if model is not None:
        manufacturer, token = model
        return Lookup("shopping", f"{manufacturer} {token}".strip(), "model")
    return Lookup("onebuild", (name or "").strip(), "name")


def _canon(unit: str) -> str | None:
    u = (unit or "").strip().lower()
    for canon, aliases in _UOM_ALIASES.items():
        if u in aliases:
            return canon
    return None


def unit_matches(source_uom: str, item_unit: str) -> bool:
    a, b = _canon(source_uom), _canon(item_unit)
    return a is not None and a == b


def lookup_key(query: str) -> str:
    return " ".join((query or "").lower().split())
```

- [ ] **Step 4: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_market_classify.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/market/classify.py api/tests/test_market_classify.py
git commit -m "Market lookup routing: quote-required words, model numbers to shopping, names to 1build"
```

---

### Task 4: Project ZIP on the wire

**Files:**
- Modify: `api/app/takeoff/schemas.py` (`ProjectOut` ~162, `ProjectCreateIn` ~199), `api/app/takeoff/projects.py:194` (`create_project`), `api/app/takeoff/router.py:112` (`post_project`; add `patch_postal_code`), `src/lib/store/api.js:343` (`createProject`; add `setPostalCode`), `src/lib/store/api-mapping.js` (`mapProject`), `src/components/projects/NewProject.jsx`, `src/components/settings/ProjectSettings.jsx:121`
- Test: `api/tests/test_projects.py` (append), `api/tests/test_tenancy.py` (row), `src/components/settings/ProjectSettings.test.jsx` (append or create)

**Interfaces:**
- Produces: `ProjectCreateIn.postal_code: str = ""` (validated `^\d{5}$` or empty); `ProjectOut.postal_code: str | None`; `PATCH /api/projects/{project_id}/postal-code` body `{"postal_code": "78701"}` (or `""` to clear) → `ProjectOut`; `create_project(..., postal_code: str | None = None)`; store `setPostalCode(projectId, postalCode)`.

- [ ] **Step 1: Failing API tests**

Append to `api/tests/test_projects.py`:

```python
def test_create_project_parses_zip_from_location_when_not_given(client, signed_in_user):
    r = client.post("/api/projects", json={"name": "Unalaska Bid", "location": "Unalaska, AK 99685"})
    assert r.status_code == 201, r.text
    assert r.json()["postalCode"] == "99685"


def test_create_project_takes_an_explicit_zip(client, signed_in_user):
    r = client.post("/api/projects", json={"name": "FedEx Office", "location": "Austin, TX", "postalCode": "78701"})
    assert r.status_code == 201 and r.json()["postalCode"] == "78701"


def test_create_project_refuses_a_malformed_zip(client, signed_in_user):
    r = client.post("/api/projects", json={"name": "X", "location": "Austin, TX", "postalCode": "7870"})
    assert r.status_code == 422


def test_patch_postal_code_is_audited(client, db, signed_in_user, project):
    project.org_id = signed_in_user.org_id; db.flush(); db.commit()
    r = client.patch(f"/api/projects/{project.id}/postal-code", json={"postal_code": "78701"})
    assert r.status_code == 200 and r.json()["postalCode"] == "78701"
    from app.takeoff.models import Action
    from sqlalchemy import select
    a = db.scalars(select(Action).where(Action.project_id == project.id, Action.kind == "project_edit")).first()
    assert a is not None and a.after == {"postal_code": "78701"}
    r = client.patch(f"/api/projects/{project.id}/postal-code", json={"postal_code": ""})
    assert r.status_code == 200 and r.json()["postalCode"] is None
```

Add to `TENANCY_TABLE` in `api/tests/test_tenancy.py`:

```python
    ("PATCH", "/api/projects/{project_id}/postal-code",
     lambda p, s, i: f"/api/projects/{p.id}/postal-code", lambda p, s, i: {"postal_code": "78701"}, None),
```

- [ ] **Step 2: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_projects.py -k postal -v tests/test_tenancy.py -k postal`
Expected: FAIL (422 on unknown field / 404 route).

- [ ] **Step 3: Schemas**

In `ProjectOut` after `location: str`: `postal_code: str | None`. In `ProjectCreateIn` after `location`:

```python
    # Five digits or empty. Empty means "parse one from location if it
    # ends in one" -- see create_project. Camel-cased on the wire like
    # the rest of this schema (postalCode).
    postal_code: str = Field(default="", pattern=r"^(\d{5})?$")
```

Add near `ProjectCreateIn`:

```python
class PostalCodeIn(BaseModel):
    postal_code: str = Field(pattern=r"^(\d{5})?$")

    model_config = MODEL_CONFIG
```

Check `list_projects()` in `projects.py` builds `ProjectOut` explicitly (line ~160 `location=project.location,`) — add `postal_code=project.postal_code,` there and anywhere else `ProjectOut(` is constructed (`grep -n "ProjectOut(" api/app/takeoff/*.py`).

- [ ] **Step 4: Service and routes**

`create_project` gains `postal_code: str | None = None` and, before `Project(...)`:

```python
    from app.market.classify import parse_zip
    postal_code = postal_code or parse_zip(location)
```

and passes `postal_code=postal_code` into `Project(...)`. `post_project` passes `postal_code=payload.postal_code or None`.

In `router.py`, next to `post_project`:

```python
@router.patch("/projects/{project_id}/postal-code", response_model=ProjectOut)
def patch_postal_code(
    project_id: uuid.UUID,
    body: PostalCodeIn,
    db: DbSession = Depends(get_db),
    user: User = Depends(current_user),
) -> ProjectOut:
    """The one project field an estimator edits after creation today.
    Audited, not undoable: a ZIP is settings, and the market job that
    reads it is queued by the pricing router, not here."""
    project = load_project(project_id, db, user)
    before = {"postal_code": project.postal_code}
    project.postal_code = body.postal_code or None
    actions.commit(db, actor=user, project_id=project.id, kind="project_edit",
                   label="Set project ZIP code" if body.postal_code else "Cleared project ZIP code",
                   before=before, after={"postal_code": project.postal_code})
    db.commit()
    return project_out(db, project)   # whatever helper GET /projects/{id} already uses to build ProjectOut; reuse it, do not re-derive the counts
```

If no such helper exists, extract one from the existing `GET /projects` list builder in `projects.py` (`list_projects` → a `project_out(db, project)` that returns one `ProjectOut`) and use it in both places.

- [ ] **Step 5: Run the API tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_projects.py tests/test_tenancy.py -v`
Expected: PASS.

- [ ] **Step 6: Frontend**

`src/lib/store/api-mapping.js` `mapProject`: add `postalCode: p.postalCode ?? null,`. `src/lib/store/api.js` `createProject` gains `postalCode = ""` in its destructured argument and sends `postalCode`; add:

```js
  async function setPostalCode(projectId, postalCode) {
    const p = await request(`/api/projects/${projectId}/postal-code`, { method: "PATCH", body: { postal_code: postalCode } });
    invalidateProject(projectId);   // whatever cache-bust helper the other project mutations use
    return mapProject(p);
  }
```

and export it with the others. `NewProject.jsx`: a **ZIP code** text field (`inputMode="numeric"`, `pattern="\d{5}"`, helper text "Used to price materials for the project's location") after Project address, sent as `postalCode`. `ProjectSettings.jsx`: replace the read-only Location row's neighbour with an editable **ZIP code** row — an input prefilled with `project.postalCode ?? ""`, saved on blur through `store.setPostalCode`, with the save state and a toast "Set project ZIP code" through the same `runMutation`/`showToast` the pricing screens use (`useWorkspaceContext`).

Frontend test (append to `src/components/settings/ProjectSettings.test.jsx`, following its existing render helper):

```jsx
it("saves the ZIP code on blur", async () => {
  const setPostalCode = vi.fn().mockResolvedValue({ ...project, postalCode: "78701" });
  renderSettings({ store: { ...store, setPostalCode } });
  const zip = await screen.findByLabelText("ZIP code");
  await userEvent.clear(zip);
  await userEvent.type(zip, "78701");
  await userEvent.tab();
  expect(setPostalCode).toHaveBeenCalledWith(project.id, "78701");
});
```

- [ ] **Step 7: Build and test the client**

Run: `npm test -- ProjectSettings NewProject && npm run build`
Expected: PASS, build clean.

- [ ] **Step 8: Commit**

```bash
git add api/app/takeoff/schemas.py api/app/takeoff/projects.py api/app/takeoff/router.py api/tests/test_projects.py api/tests/test_tenancy.py src/lib/store src/components/projects/NewProject.jsx src/components/settings
git commit -m "Project ZIP code: parsed from the address, editable in settings, on the wire"
```

---

### Task 5: The two source clients (worker only)

**Files:**
- Create: `api/app/worker/market_sources.py`
- Test: `api/tests/test_market_sources.py`

**Interfaces:**
- Produces:
  - `class SourceResult(NamedTuple)`: `status: str` (`"priced" | "no_match" | "failed"`), `unit_price: Decimal | None`, `low: Decimal | None`, `high: Decimal | None`, `labor_rate: Decimal | None`, `uom: str`, `location_label: str`, `result: dict` (the trimmed payload stored on `MarketLookup.result`)
  - `class OneBuildSource: def __init__(self, api_key: str, fetch=_post_json)`; `.name == "onebuild"`; `.location_key(project) -> str | None` (the ZIP); `.lookup(query: str, item_unit: str, location_key: str) -> SourceResult`
  - `class ShoppingSource: def __init__(self, api_key: str, fetch=_get_json)`; `.name == "shopping"`; `.location_key(project) -> str | None` (`"<city>, <ST>"` from `location`, else the ZIP); `.lookup(...)` same signature
  - `get_sources() -> dict[str, OneBuildSource | ShoppingSource]` — only the sources whose key is set
  - `class SourceError(Exception)` — network/HTTP failure, mapped to `"failed"` by the caller

- [ ] **Step 1: Failing tests with fake fetchers**

`api/tests/test_market_sources.py`:

```python
"""The two clients, against canned responses. No network: `fetch` is
injected. Trimming is asserted because the stored result is what the
row's evidence shows (estimate-first-pricing §7)."""
from decimal import Decimal

import pytest

from app.worker.market_sources import OneBuildSource, ShoppingSource, SourceError, get_sources

ONEBUILD = {"data": {"sources": {"nodes": [
    {"name": "Duplex receptacle, 20A, commercial grade", "uom": "EA", "materialRateUsdCents": 1240, "laborRateUsdCents": 2250,
     "calculatedUnitRateUsdCents": 3490, "sourceType": "MATERIAL", "id": "abc", "extra": "dropped"},
    {"name": "Receptacle branch circuit", "uom": "LF", "materialRateUsdCents": 310, "laborRateUsdCents": 900},
]}}}

SHOPPING = {"shopping_results": [
    {"title": "Columbia CVT8-LSCS-MV 8ft Vaportite", "price": "$156.75", "extracted_price": 156.75, "source": "LBC Lighting", "link": "https://www.lbclightingpro.com/x", "thumbnail": "dropped"},
    {"title": "CVT8-LSCS-MV", "price": "$169.95", "extracted_price": 169.95, "source": "Codale", "link": "https://www.codale.com/y"},
    {"title": "CVT8-LSCS-MV", "price": "$303.33", "extracted_price": 303.33, "source": "Cooper", "link": "http://insecure.example/z"},
    {"title": "no price", "source": "X", "link": "https://x.example"},
]}


class P:
    def __init__(self, location="Austin, TX", postal_code="78701"):
        self.location, self.postal_code = location, postal_code


def test_onebuild_picks_first_unit_match_and_trims():
    calls = []
    src = OneBuildSource("k", fetch=lambda url, headers, body: (calls.append((url, headers, body)) or ONEBUILD))
    r = src.lookup("20A duplex receptacle", "EA", "78701")
    assert r.status == "priced" and r.unit_price == Decimal("12.40") and r.labor_rate == Decimal("22.50")
    assert r.low == r.high == Decimal("12.40") and r.uom == "EA"
    assert r.result == {"matched": {"name": "Duplex receptacle, 20A, commercial grade", "uom": "EA",
                                    "materialRateUsdCents": 1240, "laborRateUsdCents": 2250}}
    assert calls[0][1]["1build-api-key"] == "k" and "78701" in calls[0][2]["variables"]["zip"]


def test_onebuild_no_unit_match_is_no_match():
    r = OneBuildSource("k", fetch=lambda *a: ONEBUILD).lookup("wire", "SF", "78701")
    assert r.status == "no_match" and r.unit_price is None


def test_onebuild_network_failure_raises_source_error():
    def boom(*a):
        raise OSError("timeout")
    with pytest.raises(SourceError):
        OneBuildSource("k", fetch=boom).lookup("x", "EA", "78701")


def test_shopping_low_median_high_and_https_only():
    r = ShoppingSource("k", fetch=lambda url, params: SHOPPING).lookup("Current CVT8-LSCS-MV", "EA", "Austin, TX")
    assert r.status == "priced"
    assert (r.low, r.unit_price, r.high) == (Decimal("156.75"), Decimal("169.95"), Decimal("303.33"))
    sellers = r.result["sellers"]
    assert [s["seller"] for s in sellers] == ["LBC Lighting", "Codale", "Cooper"]
    assert sellers[2]["link"] is None and "thumbnail" not in sellers[0]


def test_shopping_one_listing_is_no_match():
    one = {"shopping_results": SHOPPING["shopping_results"][:1]}
    assert ShoppingSource("k", fetch=lambda u, p: one).lookup("q", "EA", "Austin, TX").status == "no_match"


def test_location_keys():
    assert OneBuildSource("k").location_key(P()) == "78701"
    assert OneBuildSource("k").location_key(P(postal_code=None)) is None
    assert ShoppingSource("k").location_key(P()) == "Austin, TX"
    assert ShoppingSource("k").location_key(P(location="", postal_code="78701")) == "78701"


def test_get_sources_only_returns_configured(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "onebuild_api_key", "a")
    monkeypatch.setattr(config.settings, "serpapi_key", "")
    assert set(get_sources()) == {"onebuild"}
```

- [ ] **Step 2: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_market_sources.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`api/app/worker/market_sources.py`:

```python
"""The two market sources, as small HTTP clients. Worker only -- the
API never imports this module (test_api_import_boundary.py). `fetch` is
injectable so the clients are tested against canned responses; the
default fetchers use urllib with a 20 s timeout.

Both `lookup`s return a SourceResult whose `result` is already trimmed
to what the row's evidence shows (estimate-first-pricing §7). Titles
and seller names are seller-written text: stored and displayed as text,
never interpreted."""
from __future__ import annotations

import json
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Callable, NamedTuple

from app.config import settings
from app.market.classify import unit_matches

_TIMEOUT = 20
_ONEBUILD_URL = "https://gateway-external.1build.com/"
_SERPAPI_URL = "https://serpapi.com/search.json"
_ONEBUILD_QUERY = """
query Sources($term: String!, $zip: String!) {
  sources(input: {searchTerm: $term, zip: $zip, pageSize: 5}) {
    nodes { name uom materialRateUsdCents laborRateUsdCents }
  }
}"""


class SourceError(Exception):
    """The source could not be reached or answered with an error."""


class SourceResult(NamedTuple):
    status: str                       # "priced" | "no_match" | "failed"
    unit_price: Decimal | None
    low: Decimal | None
    high: Decimal | None
    labor_rate: Decimal | None
    uom: str
    location_label: str
    result: dict


def _post_json(url: str, headers: dict, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _get_json(url: str, params: dict) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _cents(v) -> Decimal | None:
    return None if v is None else (Decimal(int(v)) / 100).quantize(Decimal("0.01"))


class OneBuildSource:
    name = "onebuild"

    def __init__(self, api_key: str, fetch: Callable[[str, dict, dict], dict] = _post_json):
        self._key, self._fetch = api_key, fetch

    def location_key(self, project) -> str | None:
        return project.postal_code or None

    def lookup(self, query: str, item_unit: str, location_key: str) -> SourceResult:
        try:
            data = self._fetch(_ONEBUILD_URL, {"1build-api-key": self._key},
                               {"query": _ONEBUILD_QUERY, "variables": {"term": query, "zip": location_key}})
        except (OSError, urllib.error.URLError, ValueError) as e:
            raise SourceError(str(e)) from e
        if "errors" in data:
            raise SourceError(str(data["errors"])[:300])
        nodes = (((data.get("data") or {}).get("sources") or {}).get("nodes")) or []
        label = f"ZIP {location_key}"
        for n in nodes:
            if unit_matches(n.get("uom") or "", item_unit) and n.get("materialRateUsdCents"):
                price = _cents(n["materialRateUsdCents"])
                trimmed = {k: n.get(k) for k in ("name", "uom", "materialRateUsdCents", "laborRateUsdCents")}
                return SourceResult("priced", price, price, price, _cents(n.get("laborRateUsdCents")),
                                    n["uom"], label, {"matched": trimmed})
        return SourceResult("no_match", None, None, None, None, "", label, {"candidates": len(nodes)})


class ShoppingSource:
    name = "shopping"

    def __init__(self, api_key: str, fetch: Callable[[str, dict], dict] = _get_json):
        self._key, self._fetch = api_key, fetch

    def location_key(self, project) -> str | None:
        m = re.search(r"([A-Za-z .'-]+),\s*([A-Z]{2})\b", project.location or "")
        if m:
            return f"{m.group(1).strip()}, {m.group(2)}"
        return project.postal_code or None

    def lookup(self, query: str, item_unit: str, location_key: str) -> SourceResult:
        try:
            data = self._fetch(_SERPAPI_URL, {"engine": "google_shopping", "q": query, "location": location_key,
                                              "hl": "en", "gl": "us", "api_key": self._key})
        except (OSError, urllib.error.URLError, ValueError) as e:
            raise SourceError(str(e)) from e
        if data.get("error"):
            raise SourceError(str(data["error"])[:300])
        sellers = []
        for r in data.get("shopping_results") or []:
            price = r.get("extracted_price")
            if price is None:
                continue
            link = r.get("link") or ""
            sellers.append({"title": str(r.get("title", ""))[:200], "seller": str(r.get("source", ""))[:100],
                            "price": float(price), "link": link if link.startswith("https://") else None})
        if len(sellers) < 2:
            return SourceResult("no_match", None, None, None, None, "", location_key, {"sellers": sellers})
        prices = sorted(Decimal(str(s["price"])) for s in sellers)
        median = Decimal(str(statistics.median(prices))).quantize(Decimal("0.01"))
        return SourceResult("priced", median, prices[0], prices[-1], None, "EA", location_key, {"sellers": sellers})


def get_sources() -> dict[str, OneBuildSource | ShoppingSource]:
    out: dict = {}
    if settings.onebuild_api_key:
        out["onebuild"] = OneBuildSource(settings.onebuild_api_key)
    if settings.serpapi_key:
        out["shopping"] = ShoppingSource(settings.serpapi_key)
    return out
```

- [ ] **Step 4: Run the tests and the import boundary**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_market_sources.py tests/test_api_import_boundary.py tests/test_worker_import_boundary.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/market_sources.py api/tests/test_market_sources.py
git commit -m "Market sources: 1build and Google Shopping clients, trimmed results, worker only"
```

---

### Task 6: The `price` job

**Files:**
- Modify: `api/app/jobs/queue.py` (add `enqueue_price`), `api/app/worker/handlers.py:30` (`_load_handlers` list), `api/app/worker/classify_job.py:140` (`_finish_project` queues it)
- Create: `api/app/worker/price_job.py`
- Test: `api/tests/test_worker_price.py`, `api/tests/test_jobs_queue.py` (append)

**Interfaces:**
- Consumes: `classify_for_lookup`, `lookup_key`, `get_sources`, `SourceError`, `MarketLookup`, `ItemMarketPrice`, `settings.market_lookup_monthly_cap`.
- Produces: `queue.enqueue_price(db, project: Project, requested_by: uuid.UUID | None, run_id: uuid.UUID | None = None) -> Job | None` (None while one is in flight); `price_job.run(db, job)`; `price_job.CACHE_DAYS = 30`; `price_job.billed_this_month(db, org_id) -> int`.

- [ ] **Step 1: Failing queue test**

Append to `api/tests/test_jobs_queue.py`:

```python
def test_enqueue_price_is_one_in_flight_per_project(db, project, dana):
    from app.jobs import queue
    a = queue.enqueue_price(db, project, dana.id)
    b = queue.enqueue_price(db, project, dana.id)
    assert a is not None and b is None
    assert a.kind == "price" and a.requested_by == dana.id
```

- [ ] **Step 2: Failing worker tests**

`api/tests/test_worker_price.py`:

```python
"""The price job, with both sources faked in-process (estimate-first-
pricing §3, §10 'Worker, sources stubbed')."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.jobs import queue
from app.takeoff.models import Item, ItemMarketPrice, MarketLookup, ReviewStatus
from app.worker import market_sources, price_job
from app.worker.market_sources import SourceError, SourceResult
from tests.test_worker_read import _run_all, inline  # noqa: F401


class FakeSource:
    def __init__(self, name, answer=None, loc="78701"):
        self.name, self.calls, self._answer, self._loc = name, [], answer, loc

    def location_key(self, project):
        return self._loc

    def lookup(self, query, unit, loc):
        self.calls.append(query)
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _priced(p="12.40", low=None, high=None, labor="22.50"):
    return SourceResult("priced", Decimal(p), Decimal(low or p), Decimal(high or p), Decimal(labor), "EA",
                        "Travis County, TX", {"matched": {"name": "x"}})


def _wire(monkeypatch, db, sources, cap=2000):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    monkeypatch.setattr(market_sources, "get_sources", lambda: sources)
    monkeypatch.setattr(price_job, "get_sources", lambda: sources)
    monkeypatch.setattr("app.config.settings.market_lookup_monthly_cap", cap)


def _item(db, project, sheet, name, description="", unit="EA"):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=name, description=description,
             system="Power", category="Devices", quantity=2, unit=unit, status=ReviewStatus.READY, x=1, y=1)
    db.add(i); db.flush()
    return i


def test_prices_by_name_through_onebuild_and_writes_the_row(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    i = _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    mp = db.get(ItemMarketPrice, i.id)
    assert mp.outcome == "priced" and mp.unit_price == Decimal("12.40") and mp.labor_rate_per_unit == Decimal("22.50")
    assert mp.source == "onebuild" and mp.location_label == "Travis County, TX" and mp.query == "20A duplex receptacle"
    assert db.get(MarketLookup, mp.lookup_id).billed is True and src.calls == ["20A duplex receptacle"]


def test_model_numbers_go_to_shopping(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    shop = FakeSource("shopping", _priced("169.95", "156.75", "303.33", labor=None) if False else
                      SourceResult("priced", Decimal("169.95"), Decimal("156.75"), Decimal("303.33"), None, "EA", "Austin, TX", {"sellers": []}))
    _wire(monkeypatch, db, {"onebuild": FakeSource("onebuild", _priced()), "shopping": shop})
    i = _item(db, project, sheet, "Luminaire", "C: 8' LED Vaportite\nManufacturer: Current\nModel: CVT8-LSCS-MV")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    mp = db.get(ItemMarketPrice, i.id)
    assert mp.source == "shopping" and shop.calls == ["Current CVT8-LSCS-MV"]
    assert (mp.price_low, mp.unit_price, mp.price_high) == (Decimal("156.75"), Decimal("169.95"), Decimal("303.33"))


def test_quote_required_spends_nothing(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    i = _item(db, project, sheet, "Switch Board MSBS")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert db.get(ItemMarketPrice, i.id).outcome == "quote_required" and src.calls == []


def test_cache_hit_within_30_days_calls_nothing_and_is_not_billed(db, project, sheet, dana, org, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    db.add(MarketLookup(source="onebuild", query_key="20a duplex receptacle", location_key="78701", status="priced",
                        result={"matched": {"name": "x", "uom": "EA", "materialRateUsdCents": 999, "laborRateUsdCents": 100}},
                        fetched_at=datetime.now(timezone.utc) - timedelta(days=10), billed=True, org_id=org.id))
    db.flush()
    i = _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    mp = db.get(ItemMarketPrice, i.id)
    assert src.calls == [] and mp.unit_price == Decimal("9.99")
    assert db.scalar(select(func.count()).select_from(MarketLookup)) == 1


def test_stale_cache_is_refetched(db, project, sheet, dana, org, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    db.add(MarketLookup(source="onebuild", query_key="20a duplex receptacle", location_key="78701", status="priced",
                        result={}, fetched_at=datetime.now(timezone.utc) - timedelta(days=31), billed=True, org_id=org.id))
    db.flush()
    _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert src.calls == ["20A duplex receptacle"]


def test_cap_marks_the_rest_over_budget_and_the_job_completes(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src}, cap=2)
    items = [_item(db, project, sheet, f"Item {n}") for n in range(4)]
    job = queue.enqueue_price(db, project, dana.id); _run_all(db)
    db.refresh(job)
    outcomes = sorted(db.get(ItemMarketPrice, i.id).outcome for i in items)
    assert outcomes == ["over_budget", "over_budget", "priced", "priced"] and job.status == "done"


def test_no_key_marks_unavailable(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    _wire(monkeypatch, db, {})
    i = _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert db.get(ItemMarketPrice, i.id).outcome == "unavailable"


def test_no_zip_marks_location_needed(db, project, sheet, dana, monkeypatch):
    project.postal_code = None
    src = FakeSource("onebuild", _priced(), loc=None)
    _wire(monkeypatch, db, {"onebuild": src})
    i = _item(db, project, sheet, "20A duplex receptacle")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert db.get(ItemMarketPrice, i.id).outcome == "location_needed" and src.calls == []


def test_source_error_marks_failed_and_continues(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    _wire(monkeypatch, db, {"onebuild": FakeSource("onebuild", SourceError("timeout"))})
    a = _item(db, project, sheet, "A"); b = _item(db, project, sheet, "B")
    job = queue.enqueue_price(db, project, dana.id); _run_all(db)
    db.refresh(job)
    assert job.status == "done"
    assert {db.get(ItemMarketPrice, a.id).outcome, db.get(ItemMarketPrice, b.id).outcome} == {"failed"}


def test_rerun_prices_only_items_without_a_fresh_row(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    a = _item(db, project, sheet, "A")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    b = _item(db, project, sheet, "B")
    queue.enqueue_price(db, project, dana.id); _run_all(db)
    assert src.calls == ["A", "B"]
```

- [ ] **Step 3: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_jobs_queue.py -k price tests/test_worker_price.py -v`
Expected: FAIL — `AttributeError: module 'app.jobs.queue' has no attribute 'enqueue_price'`.

- [ ] **Step 4: Queue**

`api/app/jobs/queue.py`, after `enqueue_render`:

```python
def enqueue_price(db: Session, project: Project, requested_by: uuid.UUID | None, run_id: uuid.UUID | None = None) -> Job | None:
    """One market-pricing job per project at a time (estimate-first-
    pricing §3). Queued by the run that just completed, by the
    estimator's Refresh, or by a ZIP being set. Returns None while one
    is already queued or running -- the caller's copy says so."""
    if db.scalars(select(Job).where(
            Job.kind == "price", Job.project_id == project.id, Job.status.in_(_IN_FLIGHT))).first():
        return None
    job = Job(org_id=project.org_id, project_id=project.id, kind="price", run_id=run_id,
              requested_by=requested_by, max_attempts=MAX_ATTEMPTS)
    db.add(job)
    db.flush()
    return job
```

- [ ] **Step 5: The handler**

`api/app/worker/price_job.py`:

```python
"""price: a market estimate for every countable item on the project
(docs/specs/estimate-first-pricing.md §3). Cache first, then the
source, one call per distinct query; a cap per org per month; every
outcome written so the row can say what happened. A source failure
marks its items "failed" and the job still completes -- one dead feed
must not fail a run."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.market.classify import classify_for_lookup, lookup_key
from app.takeoff.models import Item, ItemMarketPrice, Job, MarketLookup, Project
from app.takeoff.totals import countable_items
from app.worker.handlers import register
from app.worker.market_sources import SourceError, SourceResult, get_sources

CACHE_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def billed_this_month(db: Session, org_id) -> int:
    start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count()).select_from(MarketLookup).where(
        MarketLookup.org_id == org_id, MarketLookup.billed.is_(True), MarketLookup.fetched_at >= start)) or 0


def _fresh(lookup: MarketLookup | None) -> bool:
    return lookup is not None and lookup.fetched_at >= _now() - timedelta(days=CACHE_DAYS)


def _result_from_cache(lookup: MarketLookup, source_name: str) -> SourceResult:
    """Rebuild a SourceResult from a stored, trimmed result."""
    r = lookup.result or {}
    if lookup.status != "priced":
        return SourceResult(lookup.status, None, None, None, None, "", lookup.location_key, r)
    if source_name == "onebuild":
        m = r.get("matched") or {}
        price = (Decimal(int(m.get("materialRateUsdCents") or 0)) / 100).quantize(Decimal("0.01"))
        labor = m.get("laborRateUsdCents")
        labor = None if labor is None else (Decimal(int(labor)) / 100).quantize(Decimal("0.01"))
        return SourceResult("priced", price, price, price, labor, m.get("uom") or "", f"ZIP {lookup.location_key}", r)
    prices = sorted(Decimal(str(s["price"])) for s in r.get("sellers") or [])
    import statistics
    median = Decimal(str(statistics.median(prices))).quantize(Decimal("0.01"))
    return SourceResult("priced", median, prices[0], prices[-1], None, "EA", lookup.location_key, r)


def _write(db: Session, item: Item, *, outcome: str, source: str | None, query: str, res: SourceResult | None,
           lookup: MarketLookup | None, run_id) -> None:
    row = db.get(ItemMarketPrice, item.id) or ItemMarketPrice(item_id=item.id)
    row.outcome, row.source, row.query, row.run_id = outcome, source, query[:300], run_id
    row.lookup_id = lookup.id if lookup is not None else None
    row.unit_price = res.unit_price if res else None
    row.price_low, row.price_high = (res.low, res.high) if res else (None, None)
    row.labor_rate_per_unit = res.labor_rate if res else None
    row.unit = (res.uom if res else "") or ""
    row.location_label = (res.location_label if res else "") or ""
    row.fetched_at = lookup.fetched_at if lookup is not None else None
    db.add(row)


@register("price")
def run(db: Session, job: Job) -> None:
    project = db.get(Project, job.project_id)
    if project is None:
        return
    sources = get_sources()
    cap = settings.market_lookup_monthly_cap
    used = billed_this_month(db, project.org_id)
    items = list(db.scalars(countable_items(project.id)))
    for item in items:
        existing = db.get(ItemMarketPrice, item.id)
        if existing is not None and existing.outcome == "priced" and existing.lookup_id is not None \
                and _fresh(db.get(MarketLookup, existing.lookup_id)):
            continue
        lookup = classify_for_lookup(item.name, item.description or "", item.unit)
        if lookup.source is None:
            _write(db, item, outcome="quote_required", source=None, query="", res=None, lookup=None, run_id=job.run_id)
            continue
        source = sources.get(lookup.source)
        if source is None:
            _write(db, item, outcome="unavailable", source=lookup.source, query=lookup.query, res=None, lookup=None, run_id=job.run_id)
            continue
        loc = source.location_key(project)
        if not loc:
            _write(db, item, outcome="location_needed", source=lookup.source, query=lookup.query, res=None, lookup=None, run_id=job.run_id)
            continue
        key = lookup_key(lookup.query)
        cached = db.scalars(select(MarketLookup).where(
            MarketLookup.source == source.name, MarketLookup.query_key == key, MarketLookup.location_key == loc)).first()
        if _fresh(cached):
            res = _result_from_cache(cached, source.name)
            _write(db, item, outcome=res.status, source=source.name, query=lookup.query, res=res if res.status == "priced" else None,
                   lookup=cached, run_id=job.run_id)
            continue
        if used >= cap:
            _write(db, item, outcome="over_budget", source=source.name, query=lookup.query, res=None, lookup=None, run_id=job.run_id)
            continue
        try:
            res = source.lookup(lookup.query, item.unit, loc)
        except SourceError:
            _write(db, item, outcome="failed", source=source.name, query=lookup.query, res=None, lookup=None, run_id=job.run_id)
            continue
        used += 1
        row = cached or MarketLookup(source=source.name, query_key=key, location_key=loc, org_id=project.org_id)
        row.status, row.result, row.fetched_at, row.billed = res.status, res.result, _now(), True
        db.add(row)
        db.flush()
        _write(db, item, outcome=res.status, source=source.name, query=lookup.query,
               res=res if res.status == "priced" else None, lookup=row, run_id=job.run_id)
    db.flush()
```

Register it: `handlers._load_handlers` list becomes `("read_job", "classify_job", "sheet_job", "render_job", "price_job", "price_sheet_job")` (the second module lands in Task 9; until then import of a missing module would fail — so add `"price_job"` now and `"price_sheet_job"` in Task 9).

- [ ] **Step 6: Queue it when a run completes**

`api/app/worker/classify_job.py` `_finish_project`, after the `actions.commit(... kind="ingest" ...)` line (so it runs only when the run had an actor, before the final `db.flush()`):

```python
    from app.jobs import queue   # local: classify_job already imports queue at module level? if so, use it
    queue.enqueue_price(db, project, classify_job.requested_by, run_id=classify_job.run_id)
```

(Use the module-level `queue` import if `classify_job.py` already has one; check with `grep -n "^from app.jobs import" api/app/worker/classify_job.py`.)

- [ ] **Step 7: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_worker_price.py tests/test_jobs_queue.py tests/test_worker_run.py tests/test_worker_loop.py -v`
Expected: PASS. If `test_worker_run.py` counts jobs per run, update its expected count for the one `price` job a completed run now queues.

- [ ] **Step 8: Commit**

```bash
git add api/app/jobs/queue.py api/app/worker/price_job.py api/app/worker/handlers.py api/app/worker/classify_job.py api/tests/test_worker_price.py api/tests/test_jobs_queue.py api/tests/test_worker_run.py
git commit -m "The price job: cache, cap, both sources, an outcome per item, queued when a run completes"
```

---

### Task 7: Market fields on the material rows, refresh and usage routes

**Files:**
- Modify: `api/app/takeoff/schemas.py:492` (`MaterialRowOut`), `api/app/takeoff/pricing_router.py` (`_material_row_out`, `material_row_for`, `get_material_pricing`; two new routes), `api/tests/test_tenancy.py`
- Test: `api/tests/test_pricing_endpoints.py` (append)

**Interfaces:**
- Produces: `MaterialRowOut` gains `price_low: Decimal | None`, `price_high: Decimal | None`, `market_outcome: str | None`, `market_warning: dict | None` (the four fields + title), `market_evidence: list[dict]` (shopping sellers `{seller, price, link}` or the 1build `[{name, uom}]`), `fetched_at: datetime | None`, `supplier_name: str`, `quote_date: date | None`; `POST /api/projects/{project_id}/market-pricing/refresh` → 202 `{"queued": bool}`; `GET /api/company/market-pricing/usage` → `{"used": int, "cap": int}`; `MaterialListOut` gains `market_job: str | None` (`"queued" | "running" | None`).

- [ ] **Step 1: Failing endpoint tests**

Append to `api/tests/test_pricing_endpoints.py` (use its existing sign-in/project helpers; the fixtures `client, db, signed_in_user, project, sheet, item` exist in conftest — set `project.org_id = signed_in_user.org_id` as the file's other tests do):

```python
def test_material_rows_carry_the_market_estimate(client, db, signed_in_user, project, sheet, item, org):
    from datetime import datetime, timezone
    from decimal import Decimal
    from app.takeoff.models import ItemMarketPrice, MarketLookup
    project.org_id = signed_in_user.org_id
    lk = MarketLookup(source="shopping", query_key="current cvt8-lscs-mv", location_key="Austin, TX", status="priced",
                      result={"sellers": [{"title": "t", "seller": "Codale", "price": 169.95, "link": "https://codale.example/x"}]},
                      fetched_at=datetime(2026, 9, 18, tzinfo=timezone.utc), billed=True, org_id=org.id)
    db.add(lk); db.flush()
    db.add(ItemMarketPrice(item_id=item.id, lookup_id=lk.id, outcome="priced", source="shopping", query="Current CVT8-LSCS-MV",
                           unit_price=Decimal("169.95"), price_low=Decimal("156.75"), price_high=Decimal("303.33"),
                           unit="EA", location_label="Austin, TX", fetched_at=lk.fetched_at))
    db.commit()
    r = client.get(f"/api/projects/{project.id}/material-pricing")
    row = r.json()["rows"][0]
    assert row["source_label"] == "Market estimate" and row["status"] == "attention"
    assert row["price_low"] == "156.75" and row["price_high"] == "303.33"
    assert row["market_evidence"] == [{"seller": "Codale", "price": 169.95, "link": "https://codale.example/x"}]
    assert row["basis_note"] == "Austin, TX, Sep 18" and row["market_warning"] is None


def test_material_rows_carry_the_outcome_warning(client, db, signed_in_user, project, sheet, item):
    from app.takeoff.models import ItemMarketPrice
    project.org_id = signed_in_user.org_id
    db.add(ItemMarketPrice(item_id=item.id, outcome="location_needed", source="onebuild", query="20A duplex receptacle"))
    db.commit()
    row = client.get(f"/api/projects/{project.id}/material-pricing").json()["rows"][0]
    assert row["status"] == "missing" and row["market_outcome"] == "location_needed"
    w = row["market_warning"]
    assert w["title"] == "Project location needed" and set(w) == {"title", "found", "why", "fix", "where"}
    assert w["where"].startswith("E2.1")


def test_refresh_queues_one_price_job(client, db, signed_in_user, project):
    from sqlalchemy import func, select
    from app.takeoff.models import Job
    project.org_id = signed_in_user.org_id; db.commit()
    assert client.post(f"/api/projects/{project.id}/market-pricing/refresh").status_code == 202
    assert client.post(f"/api/projects/{project.id}/market-pricing/refresh").json() == {"queued": False}
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "price", Job.project_id == project.id)) == 1
    assert client.get(f"/api/projects/{project.id}/material-pricing").json()["market_job"] == "queued"


def test_usage_counts_billed_lookups_this_month(client, db, signed_in_user, org):
    from datetime import datetime, timezone
    from app.takeoff.models import MarketLookup
    db.add(MarketLookup(source="onebuild", query_key="a", location_key="1", status="priced", result={},
                        fetched_at=datetime.now(timezone.utc), billed=True, org_id=signed_in_user.org_id))
    db.add(MarketLookup(source="onebuild", query_key="b", location_key="1", status="priced", result={},
                        fetched_at=datetime.now(timezone.utc), billed=False, org_id=signed_in_user.org_id))
    db.commit()
    assert client.get("/api/company/market-pricing/usage").json() == {"used": 1, "cap": 2000}
```

Tenancy rows: add `("POST", "/api/projects/{project_id}/market-pricing/refresh", lambda p, s, i: f"/api/projects/{p.id}/market-pricing/refresh", None, None)` to `TENANCY_TABLE`, and `("GET", "/api/company/market-pricing/usage")` to the company-route list at line ~334.

- [ ] **Step 2: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_pricing_endpoints.py -k "market or refresh or usage" -v`
Expected: FAIL.

- [ ] **Step 3: Schema**

`MaterialRowOut` gains, after `basis_note`:

```python
    price_low: Decimal | None = None
    price_high: Decimal | None = None
    market_outcome: str | None = None
    market_warning: dict | None = None
    market_evidence: list[dict] = []
    fetched_at: datetime | None = None
    supplier_name: str = ""
    quote_date: date | None = None
```

`MaterialListOut` gains `market_job: str | None = None`. Add `from datetime import date, datetime` if missing.

- [ ] **Step 4: Router**

`pricing_router.py`:

```python
from app.jobs import queue
from app.market.copy import warning_for
from app.takeoff.models import ItemMarketPrice, Job, MarketLookup, Sheet


def _evidence(market: ItemMarketPrice | None, lookup: MarketLookup | None) -> list[dict]:
    if market is None or lookup is None or market.outcome != "priced":
        return []
    r = lookup.result or {}
    if market.source == "shopping":
        return [{"seller": s.get("seller", ""), "price": s.get("price"), "link": s.get("link")} for s in r.get("sellers") or []]
    m = r.get("matched") or {}
    return [{"name": m.get("name", ""), "uom": m.get("uom", "")}] if m else []


def _material_row_out(item, resolution, override, market=None, lookup=None, sheet_number="") -> MaterialRowOut:
    warning = None
    if resolution.status == "missing" and market is not None:
        warning = warning_for(market.outcome, query=market.query, sheet_number=sheet_number, description=item.description or "")
    return MaterialRowOut(
        item_id=item.id, item_name=item.name, quantity=item.quantity,
        unit_price=resolution.unit_price,
        source=override.source if override is not None else None,
        source_label=resolution.source_label,
        reason=override.reason if override is not None else "",
        status=resolution.status, basis_note=resolution.basis_note,
        price_low=resolution.price_low, price_high=resolution.price_high,
        market_outcome=resolution.market_outcome, market_warning=warning,
        market_evidence=_evidence(market, lookup),
        fetched_at=market.fetched_at if market is not None else None,
        supplier_name=override.supplier_name if override is not None else "",
        quote_date=override.quote_date if override is not None else None,
    )
```

`material_row_for`: load `market = db.get(ItemMarketPrice, item.id)`, `lookup = db.get(MarketLookup, market.lookup_id) if market and market.lookup_id else None`, `sheet = db.get(Sheet, item.sheet_id)`, pass `market=market` into `resolve_material_price` and `market, lookup, sheet.number` into `_material_row_out`.

`get_material_pricing`: bulk-load `markets = {m.item_id: m for m in db.scalars(select(ItemMarketPrice).where(ItemMarketPrice.item_id.in_(ids)))}`, `lookups = {l.id: l for l in db.scalars(select(MarketLookup).where(MarketLookup.id.in_({m.lookup_id for m in markets.values() if m.lookup_id})))}`, `sheet_numbers = {s.id: s.number for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id))}`; per item pass them through. Then:

```python
    job = db.scalars(select(Job).where(Job.kind == "price", Job.project_id == project.id,
                                       Job.status.in_(("queued", "running")))).first()
    return MaterialListOut(pricing_source=project.pricing_source, pricing_note=project.pricing_note, rows=rows,
                           market_job=job.status if job is not None else None)
```

New routes:

```python
@router.post("/projects/{project_id}/market-pricing/refresh", status_code=202)
def refresh_market_pricing(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Queue a price job. Not a mutation of anything an estimator owns,
    so not through commit(); the job writes only item_market_prices."""
    project = load_project(project_id, db, user)
    job = queue.enqueue_price(db, project, user.id)
    db.commit()
    return {"queued": job is not None}


@router.get("/company/market-pricing/usage")
def get_market_usage(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    from datetime import datetime, timezone
    from sqlalchemy import func
    from app.config import settings
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(MarketLookup).where(
        MarketLookup.org_id == user.org_id, MarketLookup.billed.is_(True), MarketLookup.fetched_at >= start)) or 0
    return {"used": used, "cap": settings.market_lookup_monthly_cap}
```

Also: `patch_postal_code` in Task 4 should queue a price job when the ZIP was set and the project has items — add to `router.py`'s route after the commit: `if body.postal_code: queue.enqueue_price(db, project, user.id); db.commit()` (import `queue` from `app.jobs`; `router.py` may import it already for `POST .../takeoff`).

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_pricing_endpoints.py tests/test_tenancy.py tests/test_projects.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/takeoff/schemas.py api/app/takeoff/pricing_router.py api/app/takeoff/router.py api/tests/test_pricing_endpoints.py api/tests/test_tenancy.py
git commit -m "Material rows carry the market estimate, its range, evidence, and outcome warning; refresh and usage routes"
```

---

### Task 8: Material pricing workspace — tier tag, range, evidence, refresh

**Files:**
- Modify: `src/lib/store/api-mapping.js:240` (`mapMaterialRow`), `src/lib/store/api.js` (add `refreshMarketEstimates`, `getMarketUsage`), `src/components/pricing/pricingColumns.jsx`, `src/components/pricing/MaterialPricingWorkspace.jsx`, `src/styles.css`
- Create: `src/components/pricing/marketOutcomeCopy.js`
- Test: `src/components/pricing/MaterialPricingWorkspace.test.jsx` (append)

**Interfaces:**
- Consumes: the `MaterialRowOut` fields from Task 7.
- Produces: row fields `priceLow, priceHigh, marketOutcome, marketWarning, marketEvidence, fetchedAt, supplierName, quoteDate`; list field `marketJob`; store `refreshMarketEstimates(projectId) -> {queued}`; `getMarketUsage() -> {used, cap}`.

- [ ] **Step 1: Failing component tests**

Append to `MaterialPricingWorkspace.test.jsx`, using its existing `renderWorkspace`/store-mock helpers:

```jsx
const marketRow = {
  itemId: "i1", itemName: "2x4 LED troffer", quantity: 12, unitPrice: 169.95, source: null,
  sourceLabel: "Market estimate", reason: "", status: "attention", basisNote: "Austin, TX, Sep 18",
  priceLow: 156.75, priceHigh: 303.33, marketOutcome: "priced", marketWarning: null,
  marketEvidence: [{ seller: "Codale", price: 169.95, link: "https://codale.example/x" }], fetchedAt: "2026-09-18T00:00:00Z",
  supplierName: "", quoteDate: null,
};

it("shows the market estimate's range and tier tag beside the status pill", async () => {
  renderWorkspace({ rows: [marketRow] });
  expect(await screen.findByText("Market estimate")).toBeInTheDocument();
  expect(screen.getByText("$156.75–$303.33")).toBeInTheDocument();
  expect(screen.getByText("Needs attention")).toBeInTheDocument();
});

it("shows the outcome warning on an unpriced row", async () => {
  const row = { ...marketRow, unitPrice: null, sourceLabel: null, status: "missing", marketOutcome: "location_needed",
    marketWarning: { title: "Project location needed", found: "Looked for \"2x4 LED troffer\".", why: "w", fix: "Add the project ZIP code in project settings, then refresh market estimates.", where: "E2.1" } };
  renderWorkspace({ rows: [row] });
  expect(await screen.findByText("Project location needed")).toBeInTheDocument();
  expect(screen.getByText(/Add the project ZIP code/)).toBeInTheDocument();
});

it("refresh queues the job and says so", async () => {
  const refreshMarketEstimates = vi.fn().mockResolvedValue({ queued: true });
  renderWorkspace({ rows: [marketRow], store: { refreshMarketEstimates } });
  await userEvent.click(await screen.findByRole("button", { name: "Refresh market estimates" }));
  expect(refreshMarketEstimates).toHaveBeenCalled();
  expect(await screen.findByText(/Refreshing market estimates/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- MaterialPricingWorkspace`
Expected: FAIL.

- [ ] **Step 3: Mapping and store**

`mapMaterialRow` adds:

```js
    priceLow: r.price_low == null ? null : Number(r.price_low),
    priceHigh: r.price_high == null ? null : Number(r.price_high),
    marketOutcome: r.market_outcome ?? null,
    marketWarning: r.market_warning ?? null,
    marketEvidence: r.market_evidence ?? [],
    fetchedAt: r.fetched_at ?? null,
    supplierName: r.supplier_name ?? "",
    quoteDate: r.quote_date ?? null,
```

`getMaterialRows` also returns `marketJob: body.market_job ?? null`. Add:

```js
  async function refreshMarketEstimates(projectId) {
    return request(`/api/projects/${projectId}/market-pricing/refresh`, { method: "POST" });
  }
  async function getMarketUsage() {
    return request("/api/company/market-pricing/usage");
  }
```

- [ ] **Step 4: Columns and copy**

`marketOutcomeCopy.js`:

```js
// Mirrors api/app/market/copy.py's titles, for the empty/queued states
// the screen words itself. Row warnings come from the API already formed.
export const REFRESHING = "Refreshing market estimates — rows update as they're priced.";
export const REFRESH_BUSY = "Market estimates are already being refreshed.";
export const NO_ZIP = "Add the project ZIP code in project settings to price materials for its location.";
```

`pricingColumns.jsx`: the `itemName` column's render adds, under the basis note, the warning when present:

```jsx
        {row.marketWarning ? (
          <div className="row-warning">
            <strong>{row.marketWarning.title}</strong> {row.marketWarning.fix}
          </div>
        ) : null}
```

The `source` (Basis) column renders the tier as `<span className="pill pill--tier">{label}</span>` (a `--slate` tier tag — add `.pill--tier` in `styles.css` using the existing `--slate` token, distinct from status pills) and, for `row.sourceLabel === "Supplier quote"`, appends `row.supplierName`. Add a **Range** column after Unit price:

```jsx
  {
    key: "range", label: "Range", align: "right",
    render: (row) => (row.priceLow != null && row.priceHigh != null && row.priceLow !== row.priceHigh
      ? <span className="tabular">{money(row.priceLow)}–{money(row.priceHigh)}</span> : NONE),
  },
```

and, on Market estimate rows with `marketEvidence`, a details element in the Material cell listing `seller — $price` with `link` as an `<a target="_blank" rel="noreferrer">` when present (seller-written text rendered as text).

- [ ] **Step 5: Workspace header**

In `MaterialPricingWorkspace.jsx`: state `marketJob` from `load()`; a header row under `<h1>`:

```jsx
        <div className="page-actions">
          <button type="button" className="btn" onClick={refresh} disabled={!!marketJob}>Refresh market estimates</button>
        </div>
        {marketJob ? <p className="muted">{REFRESHING}</p> : null}
```

with

```js
  const refresh = async () => {
    const { queued } = await store.refreshMarketEstimates(projectId);
    if (queued) setMarketJob("queued"); else showToast(REFRESH_BUSY);
  };
```

and a poll: while `marketJob` is set, re-run `load()` every 5 s (`useEffect` with `setInterval`, cleared when `marketJob` becomes null — the same shape `ProcessingStatus.jsx` uses). Replace the `pricingSource !== "llm"` paragraph with one that reads: "Prices start from a market estimate for the project's location. Enter a price, or upload your supplier's price sheet, to replace one." Remove the "reprocess … pricing assistant" sentence.

- [ ] **Step 6: Run tests and build**

Run: `npm test -- MaterialPricingWorkspace && npm run build`
Expected: PASS, build clean.

- [ ] **Step 7: Commit**

```bash
git add src/lib/store src/components/pricing src/styles.css
git commit -m "Material pricing: market estimate tag, range, sellers as evidence, refresh"
```

---

### Task 9: Price request workbook and price sheet parser (pure) + `Pricing` uploads

**Files:**
- Create: `api/app/market/price_sheet.py`
- Modify: `api/app/documents/service.py:59-75` (`store_upload`), `api/app/documents/service.py:128,166` (no read job for `Pricing`)
- Test: `api/tests/test_market_price_sheet.py`, `api/tests/test_documents_upload.py` (append)

**Interfaces:**
- Produces:
  - `build_request_workbook(rows: list[dict]) -> bytes` — `rows` are `{item_id, item_name, description, quantity, unit}`; sheet "Price request", header row `Item | Description | Qty | Unit | Unit price | Supplier part no. | Notes | Row key`, column H hidden.
  - `parse_price_sheet(data: bytes, filename: str) -> ParsedSheet` where `ParsedSheet = NamedTuple(rows: list[ParsedRow], refused: str | None)`, `ParsedRow = NamedTuple(row_key: str | None, item_name: str, unit_price: Decimal | None, part_no: str, notes: str, line: int)`.
  - `REQUIRED_HEADER = ("Item", "Unit price")`; `HEADER = (...)` the eight names.
  - `store_upload` accepts `.xlsx`/`.csv` when `doc_type == "Pricing"` and queues no `read`.

- [ ] **Step 1: Failing tests**

`api/tests/test_market_price_sheet.py`:

```python
"""The price request workbook and the parser that reads it back --
pure, no database (estimate-first-pricing §6)."""
import io
from decimal import Decimal

import openpyxl

from app.market.price_sheet import HEADER, build_request_workbook, parse_price_sheet

ROWS = [
    {"item_id": "11111111-1111-1111-1111-111111111111", "item_name": "20A duplex receptacle", "description": "Duplex Receptacle", "quantity": 14, "unit": "EA"},
    {"item_id": "22222222-2222-2222-2222-222222222222", "item_name": "Panelboard", "description": "Panel Board", "quantity": 1, "unit": "EA"},
]


def test_request_workbook_has_one_row_per_item_and_a_hidden_key_column():
    wb = openpyxl.load_workbook(io.BytesIO(build_request_workbook(ROWS)))
    ws = wb["Price request"]
    assert [c.value for c in ws[1]] == list(HEADER)
    assert ws.cell(2, 1).value == "20A duplex receptacle" and ws.cell(2, 3).value == 14
    assert ws.cell(2, 8).value == ROWS[0]["item_id"] and ws.column_dimensions["H"].hidden is True
    assert ws.cell(2, 5).value is None    # unit price left blank for the supplier


def test_parse_round_trip_reads_prices_by_row_key():
    wb = openpyxl.load_workbook(io.BytesIO(build_request_workbook(ROWS)))
    ws = wb.active
    ws.cell(2, 5).value = 9.10
    ws.cell(2, 6).value = "HBL5362"
    ws.cell(3, 5).value = "$ 2,250.00"
    out = io.BytesIO(); wb.save(out)
    parsed = parse_price_sheet(out.getvalue(), "codale.xlsx")
    assert parsed.refused is None
    assert parsed.rows[0].row_key == ROWS[0]["item_id"] and parsed.rows[0].unit_price == Decimal("9.10") and parsed.rows[0].part_no == "HBL5362"
    assert parsed.rows[1].unit_price == Decimal("2250.00")


def test_parse_blank_price_is_none_and_kept():
    wb = openpyxl.load_workbook(io.BytesIO(build_request_workbook(ROWS)))
    out = io.BytesIO(); wb.save(out)
    parsed = parse_price_sheet(out.getvalue(), "x.xlsx")
    assert [r.unit_price for r in parsed.rows] == [None, None]


def test_parse_csv_without_key_column_matches_by_name_later():
    csv = "Item,Unit price\n20A duplex receptacle,9.10\nSomething new,4\n"
    parsed = parse_price_sheet(csv.encode(), "quote.csv")
    assert parsed.refused is None
    assert parsed.rows[0].row_key is None and parsed.rows[0].item_name == "20A duplex receptacle"
    assert parsed.rows[1].unit_price == Decimal("4")


def test_parse_refuses_a_sheet_without_a_unit_price_header():
    csv = "Product,Price\nx,1\n"
    parsed = parse_price_sheet(csv.encode(), "quote.csv")
    assert parsed.rows == [] and "Unit price" in parsed.refused and "Item" in parsed.refused


def test_parse_finds_the_header_below_a_title_row():
    csv = "Codale quote 9/18\n\nItem,Unit price\n20A duplex receptacle,9.10\n"
    assert parse_price_sheet(csv.encode(), "q.csv").rows[0].unit_price == Decimal("9.10")
```

Append to `api/tests/test_documents_upload.py` (use its existing upload helper that posts multipart to `/api/projects/{id}/documents`):

```python
def test_a_pricing_upload_accepts_xlsx_and_queues_no_read(client, db, signed_in_user, project, blob_store):
    from sqlalchemy import func, select
    from app.takeoff.models import Job
    project.org_id = signed_in_user.org_id; db.commit()
    r = client.post(f"/api/projects/{project.id}/documents",
                    files={"file": ("codale.xlsx", b"PK\x03\x04fake", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    data={"doc_type": "Pricing"})
    assert r.status_code == 201, r.text
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "read")) == 0


def test_a_pricing_upload_refuses_a_pdf_and_drawings_refuse_xlsx(client, db, signed_in_user, project, blob_store):
    project.org_id = signed_in_user.org_id; db.commit()
    r = client.post(f"/api/projects/{project.id}/documents", files={"file": ("q.pdf", b"%PDF-1.4", "application/pdf")}, data={"doc_type": "Pricing"})
    assert r.status_code == 415
    r = client.post(f"/api/projects/{project.id}/documents", files={"file": ("q.xlsx", b"PK", "application/octet-stream")}, data={"doc_type": "Drawings"})
    assert r.status_code == 415
```

- [ ] **Step 2: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_market_price_sheet.py tests/test_documents_upload.py -k "pricing" -v`
Expected: FAIL.

- [ ] **Step 3: The pure module**

`api/app/market/price_sheet.py`:

```python
"""The price request an estimator sends a supplier, and the parser
that reads the filled sheet back (estimate-first-pricing §6). Pure:
bytes in, records out. Only two cells are interpreted -- the price (a
number) and the row key (an id the caller checks belongs to the
project). Everything else is text, carried as text."""
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

import openpyxl
from openpyxl.utils import get_column_letter

HEADER = ("Item", "Description", "Qty", "Unit", "Unit price", "Supplier part no.", "Notes", "Row key")
REQUIRED_HEADER = ("Item", "Unit price")
_KEY_COL = HEADER.index("Row key") + 1
_MONEY_RE = re.compile(r"[^\d.\-]")


class ParsedRow(NamedTuple):
    row_key: str | None
    item_name: str
    unit_price: Decimal | None
    part_no: str
    notes: str
    line: int


class ParsedSheet(NamedTuple):
    rows: list[ParsedRow]
    refused: str | None


def build_request_workbook(rows: list[dict]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Price request"
    ws.append(list(HEADER))
    for r in rows:
        ws.append([r["item_name"], (r.get("description") or "").splitlines()[0] if r.get("description") else "",
                   r["quantity"], r["unit"], None, None, None, str(r["item_id"])])
    ws.column_dimensions[get_column_letter(_KEY_COL)].hidden = True
    for col, width in zip("ABCDEFG", (36, 48, 8, 8, 14, 20, 30)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _price(v) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    s = _MONEY_RE.sub("", str(v))
    try:
        return Decimal(s).quantize(Decimal("0.01")) if s not in ("", "-", ".") else None
    except InvalidOperation:
        return None


def _grid(data: bytes, filename: str) -> list[list]:
    if filename.lower().endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb.active
    return [list(row) for row in ws.iter_rows(values_only=True)]


def _find_header(grid: list[list]) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(grid[:20]):
        names = {str(c).strip().lower(): j for j, c in enumerate(row) if c is not None and str(c).strip()}
        if all(h.lower() in names for h in REQUIRED_HEADER):
            return i, names
    return None


def parse_price_sheet(data: bytes, filename: str) -> ParsedSheet:
    try:
        grid = _grid(data, filename)
    except Exception:
        return ParsedSheet([], "This file couldn't be read as a spreadsheet. Upload the .xlsx or .csv the price request was sent as.")
    found = _find_header(grid)
    if found is None:
        return ParsedSheet([], f"The sheet needs a header row with the columns {' and '.join(REQUIRED_HEADER)}. "
                               f"The price request download has them in place.")
    hi, cols = found
    rows: list[ParsedRow] = []
    for n, row in enumerate(grid[hi + 1:], start=hi + 2):
        def cell(name):
            j = cols.get(name.lower())
            return row[j] if j is not None and j < len(row) else None
        name = cell("Item")
        if name is None or not str(name).strip():
            continue
        key = cell("Row key")
        rows.append(ParsedRow(
            row_key=str(key).strip() if key not in (None, "") else None,
            item_name=str(name).strip(),
            unit_price=_price(cell("Unit price")),
            part_no=str(cell("Supplier part no.") or "").strip()[:100],
            notes=str(cell("Notes") or "").strip()[:500],
            line=n,
        ))
    return ParsedSheet(rows, None)
```

- [ ] **Step 4: Uploads**

`documents/service.py` `store_upload`: replace the `_is_pdf` refusal with:

```python
    if doc_type == "Pricing":
        if not _is_spreadsheet(filename):
            raise DomainError("unsupported_document",
                              f"{filename} isn't a spreadsheet. Upload the .xlsx or .csv your supplier filled in.", status=415)
    elif not _is_pdf(filename, content_type):
        raise DomainError(... unchanged ...)
```

with `def _is_spreadsheet(filename: str) -> bool: return filename.lower().endswith((".xlsx", ".csv"))`. At both `queue.enqueue_read(db, document)` call sites (lines ~128 and ~166), guard with `if document.doc_type != "Pricing":`. Check `set_doc_type` (line 150): retyping a `Pricing` sheet to `Drawings` must be refused (`DomainError("invalid_doc_type", "A price sheet can't be used as a drawing.", status=422)`) and vice versa, since the read job only parses PDFs.

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_market_price_sheet.py tests/test_documents_upload.py tests/test_documents_manage.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/market/price_sheet.py api/app/documents/service.py api/tests/test_market_price_sheet.py api/tests/test_documents_upload.py
git commit -m "Price request workbook, price sheet parser, and Pricing uploads that queue no read"
```

---

### Task 10: `price_sheet` job, preview, apply, undo

**Files:**
- Create: `api/app/worker/price_sheet_job.py`
- Modify: `api/app/jobs/queue.py` (add `enqueue_price_sheet`), `api/app/worker/handlers.py:30`, `api/app/takeoff/pricing_router.py` (four routes), `api/app/takeoff/schemas.py` (`PriceSheetPreviewOut`, `PriceSheetApplyIn`), `api/app/takeoff/undo.py:76`, `api/app/takeoff/undo_apply.py:92`, `api/tests/test_tenancy.py`
- Test: `api/tests/test_worker_price_sheet.py`, `api/tests/test_pricing_endpoints.py` (append), `api/tests/test_undo_redo.py` (append)

**Interfaces:**
- Consumes: `parse_price_sheet`, `build_request_workbook`, `documents.service.store_upload/open_content`, `record_company_action`, `_snapshot`.
- Produces:
  - `queue.enqueue_price_sheet(db, document: Document, requested_by) -> Job`
  - Job payload after the run: `{"preview": {"matched": [...], "unmatched": [...], "unpriced": [...], "refused": str | None, "supplier_name": str, "quote_date": "YYYY-MM-DD" | None}}`; `matched` rows are `{item_id, item_name, current_unit_price, current_source_label, new_unit_price, part_no, notes, line}`.
  - `GET /api/projects/{project_id}/material-pricing/price-request` → `.xlsx`, optional `?only=missing`
  - `POST /api/projects/{project_id}/material-pricing/price-sheets` (multipart `file`) → 202 `{"document_id"}`
  - `GET /api/projects/{project_id}/material-pricing/price-sheets/{document_id}/preview` → `PriceSheetPreviewOut` (`state: "reading" | "ready" | "failed"`, plus the preview)
  - `POST .../price-sheets/{document_id}/apply` body `PriceSheetApplyIn {item_ids: list[uuid], supplier_name: str, quote_date: date, save_to_company: bool}` → `MaterialListOut`
  - Action kind `"supplier_quote_apply"` with `before/after = {"rows": {item_id: snapshot | {}}}`, in `REVERSIBLE`.

- [ ] **Step 1: Failing worker test**

`api/tests/test_worker_price_sheet.py`:

```python
"""The price_sheet job turns an uploaded sheet into a preview on the
job payload -- matched by row key, unmatched listed, unpriced listed,
a foreign row key ignored (estimate-first-pricing §6)."""
import io
import uuid

import openpyxl
from sqlalchemy import select

from app.jobs import queue
from app.market.price_sheet import build_request_workbook
from app.takeoff.models import Document, Item, Job, ReviewStatus
from tests.test_worker_read import _run_all, inline  # noqa: F401


def _sheet_doc(db, project, dana, store, data, name="codale.xlsx"):
    d = Document(project_id=project.id, filename=name, doc_type="Pricing",
                 content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 size_bytes=len(data), sha256=uuid.uuid4().hex * 2, storage_key=f"k/{uuid.uuid4()}", uploaded_by=dana.id)
    db.add(d); db.flush()
    store.put(d.storage_key, io.BytesIO(data), d.content_type, len(data))
    return d


def test_preview_matches_by_key_and_lists_the_rest(db, project, sheet, item, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    other = Item(project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Panelboard", system="Distribution",
                 category="Equipment", quantity=1, unit="EA", status=ReviewStatus.READY, x=1, y=1)
    db.add(other); db.flush()
    wb = openpyxl.load_workbook(io.BytesIO(build_request_workbook([
        {"item_id": str(item.id), "item_name": item.name, "description": "", "quantity": 14, "unit": "EA"},
        {"item_id": str(other.id), "item_name": other.name, "description": "", "quantity": 1, "unit": "EA"},
    ])))
    ws = wb.active
    ws.cell(2, 5).value = 9.10                       # item priced
    ws.append(["Something extra", "", 1, "EA", 4, "", "", str(uuid.uuid4())])   # foreign key, not ours
    ws.append(["Renamed thing", "", 1, "EA", 5, "", "", None])                  # no key, no name match
    out = io.BytesIO(); wb.save(out)
    d = _sheet_doc(db, project, dana, inline, out.getvalue())
    job = queue.enqueue_price_sheet(db, d, dana.id); _run_all(db)
    db.refresh(job)
    p = job.payload["preview"]
    assert job.status == "done" and p["refused"] is None
    assert [m["item_id"] for m in p["matched"]] == [str(item.id)] and p["matched"][0]["new_unit_price"] == "9.10"
    assert [u["item_name"] for u in p["unmatched"]] == ["Something extra", "Renamed thing"]
    assert [u["item_id"] for u in p["unpriced"]] == [str(other.id)]
    assert p["supplier_name"] == "codale"


def test_preview_matches_by_exact_name_without_a_key(db, project, sheet, item, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _sheet_doc(db, project, dana, inline, f"Item,Unit price\n{item.name},9.10\n".encode(), name="q.csv")
    job = queue.enqueue_price_sheet(db, d, dana.id); _run_all(db)
    db.refresh(job)
    assert [m["item_id"] for m in job.payload["preview"]["matched"]] == [str(item.id)]


def test_refused_sheet_completes_with_the_reason(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _sheet_doc(db, project, dana, inline, b"Product,Price\nx,1\n", name="q.csv")
    job = queue.enqueue_price_sheet(db, d, dana.id); _run_all(db)
    db.refresh(job)
    assert job.status == "done" and "Unit price" in job.payload["preview"]["refused"]
```

- [ ] **Step 2: Failing route and undo tests**

Append to `api/tests/test_pricing_endpoints.py`:

```python
def test_price_request_download_is_an_xlsx_with_one_row_per_item(client, db, signed_in_user, project, item):
    import io, openpyxl
    project.org_id = signed_in_user.org_id; db.commit()
    r = client.get(f"/api/projects/{project.id}/material-pricing/price-request")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
    assert ws.cell(2, 1).value == item.name and ws.cell(2, 8).value == str(item.id)


def test_apply_writes_supplier_quotes_as_one_undoable_action(client, db, signed_in_user, project, item):
    from datetime import date
    from sqlalchemy import select
    from app.takeoff.models import Action, Document, Job, ProjectMaterialPrice
    project.org_id = signed_in_user.org_id
    d = Document(project_id=project.id, filename="codale.xlsx", doc_type="Pricing", content_type="x", size_bytes=1,
                 sha256="a" * 64, storage_key="k", uploaded_by=signed_in_user.id)
    db.add(d); db.flush()
    job = Job(org_id=project.org_id, project_id=project.id, kind="price_sheet", document_id=d.id, status="done",
              payload={"preview": {"matched": [{"item_id": str(item.id), "item_name": item.name, "current_unit_price": None,
                                                "current_source_label": None, "new_unit_price": "9.10", "part_no": "", "notes": "", "line": 2}],
                                   "unmatched": [], "unpriced": [], "refused": None, "supplier_name": "codale", "quote_date": None}})
    db.add(job); db.commit()
    r = client.post(f"/api/projects/{project.id}/material-pricing/price-sheets/{d.id}/apply",
                    json={"item_ids": [str(item.id)], "supplier_name": "Codale", "quote_date": "2026-09-18", "save_to_company": True})
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0]
    assert row["source_label"] == "Supplier quote" and row["unit_price"] == "9.10" and row["status"] == "approved"
    pm = db.get(ProjectMaterialPrice, item.id)
    assert pm.source == "supplier_quote" and pm.supplier_name == "Codale" and pm.quote_date == date(2026, 9, 18)
    a = db.scalars(select(Action).where(Action.project_id == project.id, Action.kind == "supplier_quote_apply")).one()
    assert a.label == "Applied supplier pricing from Codale for 1 item" and a.before == {"rows": {str(item.id): {}}}
    from app.takeoff.models import CompanyMaterialPrice
    cp = db.scalars(select(CompanyMaterialPrice).where(CompanyMaterialPrice.item_name == item.name)).one()
    assert cp.unit_price == Decimal("9.10") and cp.effective_date == date(2026, 9, 18)


def test_apply_refuses_an_item_not_in_the_preview(client, db, signed_in_user, project, item):
    import uuid
    from app.takeoff.models import Document, Job
    project.org_id = signed_in_user.org_id
    d = Document(project_id=project.id, filename="q.csv", doc_type="Pricing", content_type="x", size_bytes=1,
                 sha256="b" * 64, storage_key="k2", uploaded_by=signed_in_user.id)
    db.add(d); db.flush()
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="price_sheet", document_id=d.id, status="done",
               payload={"preview": {"matched": [], "unmatched": [], "unpriced": [], "refused": None, "supplier_name": "", "quote_date": None}}))
    db.commit()
    r = client.post(f"/api/projects/{project.id}/material-pricing/price-sheets/{d.id}/apply",
                    json={"item_ids": [str(item.id)], "supplier_name": "X", "quote_date": "2026-09-18", "save_to_company": False})
    assert r.status_code == 422
```

Append to `api/tests/test_undo_redo.py` (use its existing helpers for posting undo and reading rows):

```python
def test_undo_of_a_supplier_quote_apply_restores_the_prior_price(client, db, signed_in_user, project, item):
    from decimal import Decimal
    from app.takeoff import actions
    from app.takeoff.models import ProjectMaterialPrice
    project.org_id = signed_in_user.org_id
    db.add(ProjectMaterialPrice(item_id=item.id, price_override=Decimal("15"), source="project_price")); db.flush()
    before = {"rows": {str(item.id): {"item_id": str(item.id), "price_override": "15.00", "source": "project_price", "reason": "",
                                       "supplier_name": "", "quote_date": None, "updated_by_user_id": None, "updated_at": None}}}
    row = db.get(ProjectMaterialPrice, item.id)
    row.price_override, row.source, row.supplier_name = Decimal("9.10"), "supplier_quote", "Codale"
    db.flush()
    after = {"rows": {str(item.id): {**before["rows"][str(item.id)], "price_override": "9.10", "source": "supplier_quote", "supplier_name": "Codale"}}}
    actions.commit(db, actor=signed_in_user, project_id=project.id, kind="supplier_quote_apply",
                   label="Applied supplier pricing from Codale for 1 item", before=before, after=after)
    db.commit()
    assert client.post(f"/api/projects/{project.id}/undo").status_code == 200
    db.expire_all()
    row = db.get(ProjectMaterialPrice, item.id)
    assert row.price_override == Decimal("15") and row.source == "project_price"
```

Tenancy: add the four routes to `TENANCY_TABLE` (GET price-request; GET preview with a `d` document fixture path — follow how `documents` rows in the table build a document id; POST apply with body `{"item_ids": [], "supplier_name": "x", "quote_date": "2026-09-18", "save_to_company": False}`), and the multipart upload to `MULTIPART_TENANCY_TABLE`.

- [ ] **Step 3: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_worker_price_sheet.py tests/test_pricing_endpoints.py -k "price_request or apply" tests/test_undo_redo.py -k supplier -v`
Expected: FAIL.

- [ ] **Step 4: Queue + job**

`queue.py`:

```python
def enqueue_price_sheet(db: Session, document: Document, requested_by: uuid.UUID | None) -> Job:
    """Parse an uploaded price sheet into a preview. One per document;
    a second upload is a second document."""
    project = db.get(Project, document.project_id)
    job = Job(org_id=project.org_id, project_id=project.id, kind="price_sheet", document_id=document.id,
              requested_by=requested_by, max_attempts=MAX_ATTEMPTS)
    db.add(job)
    db.flush()
    return job
```

`api/app/worker/price_sheet_job.py`:

```python
"""price_sheet: read an uploaded supplier price sheet into a preview on
the job's payload. Nothing is applied here -- the estimator does that
from the preview (estimate-first-pricing §6). A refused sheet is a
completed job carrying the reason, not a failure."""
from __future__ import annotations

import os
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market.price_sheet import parse_price_sheet
from app.takeoff.models import Document, Item, Job, ProjectMaterialPrice
from app.takeoff.totals import countable_items
from app.worker import blobs
from app.worker.handlers import register

_DATE_RE = re.compile(r"(\d{4})[-_.](\d{2})[-_.](\d{2})")


def _supplier_and_date(filename: str) -> tuple[str, str | None]:
    stem = os.path.splitext(os.path.basename(filename))[0]
    m = _DATE_RE.search(stem)
    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    name = _DATE_RE.sub("", stem).replace("_", " ").replace("-", " ").strip(" .")
    name = re.sub(r"\b(price( request| sheet)?|quote|pricing)\b", "", name, flags=re.IGNORECASE).strip()
    return name[:200], date


@register("price_sheet")
def run(db: Session, job: Job) -> None:
    doc = db.get(Document, job.document_id)
    if doc is None:
        return
    store = blobs.get_blob_store()
    with blobs.storage_errors(doc.filename):
        data = store.get(doc.storage_key).read()   # whatever BlobStore's read method is named; blob_to_tempfile's source shows it
    parsed = parse_price_sheet(data, doc.filename)
    items = list(db.scalars(countable_items(job.project_id)))
    by_id = {str(i.id): i for i in items}
    by_name = {i.name: i for i in items}
    overrides = {r.item_id: r for r in db.scalars(select(ProjectMaterialPrice).where(ProjectMaterialPrice.item_id.in_([i.id for i in items])))}
    matched, unmatched, seen = [], [], set()
    for r in parsed.rows:
        item = by_id.get(r.row_key or "") or (by_name.get(r.item_name) if r.row_key is None else None)
        if item is None or str(item.id) in seen:
            unmatched.append({"item_name": r.item_name, "unit_price": str(r.unit_price) if r.unit_price is not None else None, "line": r.line})
            continue
        seen.add(str(item.id))
        if r.unit_price is None:
            continue   # listed under unpriced below
        cur = overrides.get(item.id)
        matched.append({"item_id": str(item.id), "item_name": item.name,
                        "current_unit_price": str(cur.price_override) if cur else None,
                        "current_source_label": {"project_price": "Project price", "allowance": "Allowance", "supplier_quote": "Supplier quote"}.get(cur.source) if cur else None,
                        "new_unit_price": str(r.unit_price), "part_no": r.part_no, "notes": r.notes, "line": r.line})
    priced_ids = {m["item_id"] for m in matched}
    unpriced = [{"item_id": str(i.id), "item_name": i.name} for i in items if str(i.id) not in priced_ids]
    supplier, date = _supplier_and_date(doc.filename)
    job.payload = {**(job.payload or {}), "preview": {
        "matched": matched, "unmatched": unmatched, "unpriced": unpriced, "refused": parsed.refused,
        "supplier_name": supplier, "quote_date": date}}
    db.flush()
```

Add `"price_sheet_job"` to `handlers._load_handlers`.

- [ ] **Step 5: Schemas and routes**

`schemas.py`:

```python
class PriceSheetPreviewOut(BaseModel):
    state: str                     # "reading" | "ready" | "failed"
    error: str = ""
    matched: list[dict] = []
    unmatched: list[dict] = []
    unpriced: list[dict] = []
    refused: str | None = None
    supplier_name: str = ""
    quote_date: date | None = None
    model_config = MODEL_CONFIG


class PriceSheetApplyIn(BaseModel):
    item_ids: list[uuid.UUID]
    supplier_name: str = Field(min_length=1, max_length=200)
    quote_date: date
    save_to_company: bool = False
    model_config = MODEL_CONFIG
```

`pricing_router.py` (imports: `Response`, `UploadFile`, `File` from fastapi; `documents.service` as `doc_service`; `get_blob_store`; `build_request_workbook`; `Document`, `CompanyMaterialPrice`):

```python
@router.get("/projects/{project_id}/material-pricing/price-request")
def get_price_request(project_id: uuid.UUID, only: str | None = None,
                      user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    rows = get_material_pricing(project_id, user, db).rows   # the resolved rows, so `only=missing` uses the real status
    if only == "missing":
        rows = [r for r in rows if r.status == "missing"]
    items = {i.id: i for i in db.scalars(countable_items(project.id))}
    data = build_request_workbook([{"item_id": r.item_id, "item_name": r.item_name,
                                    "description": items[r.item_id].description, "quantity": float(r.quantity),
                                    "unit": items[r.item_id].unit} for r in rows])
    name = f"{project.name} - price request - {date.today():%Y-%m-%d}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/projects/{project_id}/material-pricing/price-sheets", status_code=202)
def post_price_sheet(project_id: uuid.UUID, file: UploadFile = File(...),
                     user: User = Depends(current_user), db: DbSession = Depends(get_db), store=Depends(get_blob_store)):
    project = load_project(project_id, db, user)
    document = doc_service.store_upload(db, actor=user, project=project, upload=file, doc_type="Pricing", store=store)
    queue.enqueue_price_sheet(db, document, user.id)
    db.commit()
    return {"document_id": str(document.id)}


def _preview_job(db, project, document_id) -> tuple[Document, Job | None]:
    document = db.get(Document, document_id)
    if document is None or document.project_id != project.id or document.doc_type != "Pricing":
        raise DomainError("price_sheet_not_found", "That price sheet isn't on this project.", status=404)
    job = db.scalars(select(Job).where(Job.kind == "price_sheet", Job.document_id == document.id)
                     .order_by(Job.queued_at.desc())).first()
    return document, job


@router.get("/projects/{project_id}/material-pricing/price-sheets/{document_id}/preview", response_model=PriceSheetPreviewOut)
def get_price_sheet_preview(project_id: uuid.UUID, document_id: uuid.UUID,
                            user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    _, job = _preview_job(db, project, document_id)
    if job is None or job.status in ("queued", "running"):
        return PriceSheetPreviewOut(state="reading")
    if job.status == "failed":
        return PriceSheetPreviewOut(state="failed", error=job.error)
    return PriceSheetPreviewOut(state="ready", **(job.payload or {}).get("preview", {}))


@router.post("/projects/{project_id}/material-pricing/price-sheets/{document_id}/apply", response_model=MaterialListOut)
def apply_price_sheet(project_id: uuid.UUID, document_id: uuid.UUID, body: PriceSheetApplyIn,
                      user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """One commit() for every ticked row (estimate-first-pricing §6).
    `before`/`after` carry a snapshot per item ({} = no row), which is
    what undo_apply replays row by row."""
    project = load_project(project_id, db, user)
    _, job = _preview_job(db, project, document_id)
    preview = ((job.payload if job else None) or {}).get("preview") or {}
    by_id = {m["item_id"]: m for m in preview.get("matched", [])}
    wanted = [str(i) for i in body.item_ids]
    if not wanted or any(i not in by_id for i in wanted):
        raise DomainError("price_sheet_rows", "Choose rows from the price sheet preview to apply.", status=422)
    before, after = {}, {}
    for item_id in wanted:
        iid = uuid.UUID(item_id)
        item = load_item(iid, db, user)
        before[item_id] = _snapshot(ProjectMaterialPrice, iid, db) or {}
        row = db.get(ProjectMaterialPrice, iid) or ProjectMaterialPrice(item_id=iid, price_override=0, source="supplier_quote")
        row.price_override = Decimal(by_id[item_id]["new_unit_price"])
        row.source, row.reason = "supplier_quote", ""
        row.supplier_name, row.quote_date, row.updated_by_user_id = body.supplier_name, body.quote_date, user.id
        db.add(row)
        db.flush(); db.refresh(row)
        after[item_id] = _snapshot(ProjectMaterialPrice, iid, db)
        if body.save_to_company:
            existing = db.scalars(select(CompanyMaterialPrice).where(
                CompanyMaterialPrice.org_id == user.org_id, CompanyMaterialPrice.item_name == item.name)).one_or_none()
            if existing is None:
                cp = CompanyMaterialPrice(org_id=user.org_id, item_name=item.name, unit_price=row.price_override,
                                          effective_date=body.quote_date, updated_by_user_id=user.id)
                db.add(cp); db.flush(); db.refresh(cp)
                record_company_action(db, actor=user, kind="company_material_price_edit",
                                      label=f"Added company price for {item.name} from {body.supplier_name}",
                                      before={}, after=_snapshot(CompanyMaterialPrice, cp.id, db))
    n = len(wanted)
    actions.commit(db, actor=user, project_id=project.id, kind="supplier_quote_apply",
                   label=f"Applied supplier pricing from {body.supplier_name} for {n} item{'' if n == 1 else 's'}",
                   before={"rows": before}, after={"rows": after})
    db.commit()
    return get_material_pricing(project_id, user, db)
```

(`from decimal import Decimal` and `from datetime import date` at the top. `get_material_pricing(project_id, user, db)` — call the route function directly with the same three arguments; it takes plain values.)

- [ ] **Step 6: Undo**

`undo.py:76`: add `"supplier_quote_apply"` to `REVERSIBLE`. `undo_apply.py` next to the `material_price_edit` branch:

```python
    elif action.kind == "supplier_quote_apply":
        for item_id, row_state in (state.get("rows") or {}).items():
            _apply_sparse_pricing_row(db, ProjectMaterialPrice, uuid.UUID(item_id), MATERIAL_PRICE_SNAPSHOT_TYPES, row_state)
```

Check `MATERIAL_PRICE_SNAPSHOT_TYPES` (in `snapshots.py`) includes the two new columns: add `"supplier_name": str` and `"quote_date": date` in the same shape the others are declared.

- [ ] **Step 7: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_worker_price_sheet.py tests/test_pricing_endpoints.py tests/test_undo_redo.py tests/test_tenancy.py tests/test_snapshot.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add api/app/worker/price_sheet_job.py api/app/worker/handlers.py api/app/jobs/queue.py api/app/takeoff/pricing_router.py api/app/takeoff/schemas.py api/app/takeoff/undo.py api/app/takeoff/undo_apply.py api/app/takeoff/snapshots.py api/tests
git commit -m "Supplier price sheets: upload, preview in the worker, apply as one undoable action"
```

---

### Task 11: Price sheet import modal and download

**Files:**
- Create: `src/components/pricing/PriceSheetImport.jsx`, `src/components/pricing/PriceSheetImport.test.jsx`
- Modify: `src/lib/store/api.js` (`getPriceRequestUrl`, `uploadPriceSheet`, `getPriceSheetPreview`, `applyPriceSheet`), `src/components/pricing/MaterialPricingWorkspace.jsx`, `src/styles.css`

**Interfaces:**
- Consumes: Task 10's routes.
- Produces: store `uploadPriceSheet(projectId, file) -> {documentId}`, `getPriceSheetPreview(projectId, documentId) -> preview (camelCased)`, `applyPriceSheet(projectId, documentId, {itemIds, supplierName, quoteDate, saveToCompany}) -> {rows, ...}`, `priceRequestUrl(projectId, {onlyMissing}) -> string`; `<PriceSheetImport projectId store onApplied onClose />`.

- [ ] **Step 1: Failing component test**

`PriceSheetImport.test.jsx`:

```jsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PriceSheetImport from "./PriceSheetImport.jsx";

const preview = {
  state: "ready", refused: null, supplierName: "codale", quoteDate: "2026-09-18",
  matched: [{ itemId: "i1", itemName: "20A duplex receptacle", currentUnitPrice: null, currentSourceLabel: null, newUnitPrice: "9.10", partNo: "HBL5362", notes: "", line: 2 }],
  unmatched: [{ itemName: "Something extra", unitPrice: "4", line: 3 }],
  unpriced: [{ itemId: "i2", itemName: "Panelboard" }],
};

function store(overrides = {}) {
  return {
    uploadPriceSheet: vi.fn().mockResolvedValue({ documentId: "d1" }),
    getPriceSheetPreview: vi.fn().mockResolvedValue(preview),
    applyPriceSheet: vi.fn().mockResolvedValue({ rows: [] }),
    ...overrides,
  };
}

describe("PriceSheetImport", () => {
  it("uploads, shows the preview in three groups, and applies the ticked rows", async () => {
    const s = store();
    const onApplied = vi.fn();
    render(<PriceSheetImport projectId="p1" store={s} onApplied={onApplied} onClose={() => {}} />);
    const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await userEvent.upload(screen.getByLabelText("Price sheet"), file);
    expect(await screen.findByText("1 row matched")).toBeInTheDocument();
    expect(screen.getByText("1 row not on this project")).toBeInTheDocument();
    expect(screen.getByText("1 item left unpriced")).toBeInTheDocument();
    expect(screen.getByLabelText("Supplier")).toHaveValue("codale");
    await userEvent.clear(screen.getByLabelText("Supplier"));
    await userEvent.type(screen.getByLabelText("Supplier"), "Codale");
    await userEvent.click(screen.getByRole("button", { name: "Apply 1 price" }));
    await waitFor(() => expect(s.applyPriceSheet).toHaveBeenCalledWith("p1", "d1",
      { itemIds: ["i1"], supplierName: "Codale", quoteDate: "2026-09-18", saveToCompany: false }));
    expect(onApplied).toHaveBeenCalled();
  });

  it("shows a refused sheet's reason and no apply", async () => {
    const s = store({ getPriceSheetPreview: vi.fn().mockResolvedValue({ ...preview, matched: [], refused: "The sheet needs a header row with the columns Item and Unit price." }) });
    render(<PriceSheetImport projectId="p1" store={s} onApplied={() => {}} onClose={() => {}} />);
    await userEvent.upload(screen.getByLabelText("Price sheet"), new File(["x"], "q.csv", { type: "text/csv" }));
    expect(await screen.findByText(/needs a header row/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply/ })).toBeNull();
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npm test -- PriceSheetImport`
Expected: FAIL — module not found.

- [ ] **Step 3: Store**

`api.js`:

```js
  function priceRequestUrl(projectId, { onlyMissing = false } = {}) {
    return `/api/projects/${projectId}/material-pricing/price-request${onlyMissing ? "?only=missing" : ""}`;
  }
  async function uploadPriceSheet(projectId, file) {
    const form = new FormData();
    form.append("file", file);
    const r = await request(`/api/projects/${projectId}/material-pricing/price-sheets`, { method: "POST", body: form });
    return { documentId: r.document_id };
  }
  async function getPriceSheetPreview(projectId, documentId) {
    const p = await request(`/api/projects/${projectId}/material-pricing/price-sheets/${documentId}/preview`);
    return {
      state: p.state, error: p.error ?? "", refused: p.refused ?? null,
      supplierName: p.supplier_name ?? "", quoteDate: p.quote_date ?? null,
      matched: (p.matched ?? []).map((m) => ({ itemId: m.item_id, itemName: m.item_name, currentUnitPrice: m.current_unit_price,
        currentSourceLabel: m.current_source_label, newUnitPrice: m.new_unit_price, partNo: m.part_no, notes: m.notes, line: m.line })),
      unmatched: (p.unmatched ?? []).map((u) => ({ itemName: u.item_name, unitPrice: u.unit_price, line: u.line })),
      unpriced: (p.unpriced ?? []).map((u) => ({ itemId: u.item_id, itemName: u.item_name })),
    };
  }
  async function applyPriceSheet(projectId, documentId, { itemIds, supplierName, quoteDate, saveToCompany }) {
    invalidateSnapshot(projectId);   // the same cache-bust setMaterialPrice performs
    const body = await request(`/api/projects/${projectId}/material-pricing/price-sheets/${documentId}/apply`,
      { method: "POST", body: { item_ids: itemIds, supplier_name: supplierName, quote_date: quoteDate, save_to_company: saveToCompany } });
    return { pricingSource: body.pricing_source, pricingNote: body.pricing_note, marketJob: body.market_job ?? null, rows: body.rows.map(mapMaterialRow) };
  }
```

(`request` must pass a `FormData` body through untouched — check how `UploadDocuments.jsx`'s upload path sends multipart and reuse it.)

- [ ] **Step 4: The modal**

`PriceSheetImport.jsx` — uses `Modal.jsx`. States: `idle` (file input labelled "Price sheet", helper "Upload the .xlsx or .csv your supplier filled in. Start from Download price request so rows match exactly."), `reading` (polls `getPriceSheetPreview` every 2 s until `state !== "reading"`), `ready` (three groups with headings `N row(s) matched`, `N row(s) not on this project`, `N item(s) left unpriced`; matched rows have a checkbox each, checked by default, showing item name, current price + tier, new price, part no.; unmatched and unpriced are plain lists), fields **Supplier** (text, prefilled), **Quote date** (date, prefilled), checkbox **Also save these to the company price book** (off), primary button `Apply N price(s)` disabled when none ticked or supplier blank; `refused` renders the reason and no apply. On apply: `await store.applyPriceSheet(...)`, `onApplied(result)`, close. Errors render inline in the modal in the estimator's words from the API.

- [ ] **Step 5: Wire into the workspace**

`MaterialPricingWorkspace.jsx` header actions gain:

```jsx
          <a className="btn" href={store.priceRequestUrl(projectId)} download>Download price request</a>
          <button type="button" className="btn" onClick={() => setImporting(true)}>Upload supplier pricing</button>
```

and `{importing ? <PriceSheetImport projectId={projectId} store={store} onClose={() => setImporting(false)}
  onApplied={(result) => { setRows(result.rows); setImporting(false); showToast(`Applied supplier pricing for ${n} items`); }} /> : null}` where `n` is the count applied (the modal passes it in `onApplied(result, n)`). The undo toast wiring is the existing `showToast` — the action is in `REVERSIBLE`, so the top-bar undo already names it.

- [ ] **Step 6: Run tests and build**

Run: `npm test -- pricing && npm run build`
Expected: PASS, build clean.

- [ ] **Step 7: Commit**

```bash
git add src/components/pricing src/lib/store src/styles.css
git commit -m "Price sheet import: download the request, upload the filled sheet, preview, apply"
```

---

### Task 12: Coverage eval, migration check, docs

**Files:**
- Create: `api/eval/pricing_coverage.py`
- Modify: `CLAUDE.md` (Known scope limits + the `api/app/` tree), `README.md` (Run it: the two keys; Known limitations), `docs/README.md` (the specs/plans table), `docs/specs/estimate-first-pricing.md` (§10 result, after the run)
- Test: `api/tests/test_eval_pricing_coverage.py`

**Interfaces:**
- Produces: `python -m eval.pricing_coverage [--zip 78701] [--dry-run]`, writing `bid_examples/_derived/pricing_coverage.md`; `eval.pricing_coverage.classify_lines(lines) -> dict[str, int]` (pure, tested) where a line is `{name, description, unit, unit_material}`.

- [ ] **Step 1: Failing test for the pure half**

`api/tests/test_eval_pricing_coverage.py`:

```python
from eval.pricing_coverage import classify_lines

LINES = [
    {"name": "Duplex Receptacle", "description": "", "unit": "EA", "unit_material": 15},
    {"name": "Switch Board MSBS", "description": "", "unit": "EA", "unit_material": 14500},
    {"name": "C: 8' LED Vaportite", "description": "Manufacturer: Current\nModel: CVT8-LSCS-MV", "unit": "EA", "unit_material": 250},
    {"name": "Lump sum cost for wiring and conduits", "description": "", "unit": "LS", "unit_material": 1850},
]


def test_classify_lines_counts_by_route():
    assert classify_lines(LINES) == {"lines": 4, "onebuild": 1, "shopping": 1, "quote_required": 2}
```

- [ ] **Step 2: Run to see it fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_eval_pricing_coverage.py -v`
Expected: FAIL.

- [ ] **Step 3: The script**

`api/eval/pricing_coverage.py`:

```python
"""Coverage of the two market sources against the firm's own bid lines
(estimate-first-pricing §10). Reads the two estimate workbooks in
bid_examples/, routes every per-unit Division 26 line as the price job
would, calls both sources for the given ZIP, and writes a table to
bid_examples/_derived/pricing_coverage.md (gitignored -- a firm's
prices stay out of git). --dry-run routes without calling anything.

    cd api && python -m eval.pricing_coverage --zip 78701
"""
from __future__ import annotations

import argparse
import glob
import os
import statistics
from decimal import Decimal

from app.market.classify import classify_for_lookup

CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "bid_examples")
OUT = os.path.join(CORPUS, "_derived", "pricing_coverage.md")


def classify_lines(lines: list[dict]) -> dict[str, int]:
    counts = {"lines": len(lines), "onebuild": 0, "shopping": 0, "quote_required": 0}
    for ln in lines:
        lk = classify_for_lookup(ln["name"], ln.get("description", ""), ln["unit"])
        counts[lk.source or "quote_required"] += 1
    return counts


def read_lines() -> list[dict]:
    import openpyxl
    files = glob.glob(os.path.join(CORPUS, "FedEx Office Bid", "*.xlsx")) + glob.glob(os.path.join(CORPUS, "Gerber*", "*.xlsx"))
    out, seen = [], set()
    for f in files:
        wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
        for ws in wb.worksheets:
            if ws.title.upper().startswith("SUMMARY"):
                continue
            hdr = None
            section = ""
            for row in ws.iter_rows(values_only=True):
                vals = [str(v).strip() if v is not None else "" for v in row]
                if hdr is None:
                    if "DESCRIPTION" in vals and "QTY." in vals:
                        hdr = {n: i for i, n in enumerate(vals)}
                    continue
                csi, desc, qty = vals[hdr["CSI NO."]], vals[hdr["DESCRIPTION"]], vals[hdr["QTY."]]
                if csi and not qty:
                    section = csi[:2]
                    continue
                if not desc or not qty or section != "26" or desc.lower() == "sub total" or desc in seen:
                    continue
                seen.add(desc)
                first, _, rest = desc.partition("\n")
                um = vals[hdr["UNIT MATERIAL COST"]] if "UNIT MATERIAL COST" in hdr else ""
                out.append({"name": first, "description": rest, "unit": vals[hdr["UNIT"]],
                            "unit_material": float(um) if um else None})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default="78701")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    lines = read_lines()
    counts = classify_lines(lines)
    rows, priced = [], {"onebuild": 0, "shopping": 0, "no_match": 0, "failed": 0}
    if not args.dry_run:
        from app.worker.market_sources import SourceError, get_sources
        sources = get_sources()

        class P:
            location, postal_code = f"Austin, TX {args.zip}", args.zip
        for ln in lines:
            lk = classify_for_lookup(ln["name"], ln["description"], ln["unit"])
            if lk.source is None or lk.source not in sources:
                continue
            src = sources[lk.source]
            try:
                res = src.lookup(lk.query, ln["unit"], src.location_key(P()))
            except SourceError:
                priced["failed"] += 1
                continue
            if res.status != "priced":
                priced["no_match"] += 1
                continue
            priced[lk.source] += 1
            ratio = (float(res.unit_price) / ln["unit_material"]) if ln["unit_material"] else None
            rows.append((ln["name"][:50], lk.source, ln["unit_material"], float(res.unit_price), ratio))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write(f"# Pricing coverage, ZIP {args.zip}\n\n")
        fh.write("| Lines | Routed to 1build | Routed to shopping | Quote required | Priced by 1build | Priced by shopping | No match | Failed |\n|---|---|---|---|---|---|---|---|\n")
        fh.write(f"| {counts['lines']} | {counts['onebuild']} | {counts['shopping']} | {counts['quote_required']} | "
                 f"{priced['onebuild']} | {priced['shopping']} | {priced['no_match']} | {priced['failed']} |\n\n")
        if rows:
            ratios = [r[4] for r in rows if r[4]]
            fh.write(f"Median market / firm ratio: {statistics.median(ratios):.2f}\n\n" if ratios else "")
            fh.write("| Line | Source | Firm unit cost | Market | Ratio |\n|---|---|---|---|---|\n")
            for name, src, firm, market, ratio in rows:
                fh.write(f"| {name} | {src} | {firm} | {market:.2f} | {f'{ratio:.2f}' if ratio else ''} |\n")
    print(open(OUT).read())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test and a dry run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_eval_pricing_coverage.py -v && ../.enginevenv/bin/python -m eval.pricing_coverage --dry-run`
Expected: PASS; the dry run prints the routing table for the ~80 corpus lines.

- [ ] **Step 5: Migration against the real database**

Run: `docker compose up -d postgres && docker compose run --rm api alembic upgrade head && docker compose run --rm api alembic downgrade 0023 && docker compose run --rm api alembic upgrade head`
Expected: both directions apply cleanly.

- [ ] **Step 6: Docs**

- `CLAUDE.md`: in the `api/app/` tree add `market/` (`classify.py`, `copy.py`, `price_sheet.py`) and `worker/price_job.py`, `worker/price_sheet_job.py`, `worker/market_sources.py` with one-line descriptions; in *Known scope limits* replace "Labor and Material pricing are now built and routed, each carrying a pricing basis note." with a sentence naming the market estimate tier, the supplier price sheet round trip, and that labor from the market feed is stored but not resolved (spec §9). Add to the Pricing agent row of the five-agents table: "Lookup (market estimate by ZIP), plus a price-sheet round trip; a quote-line matcher later."
- `README.md` *Run it*: after the `ANTHROPIC_API_KEY` paragraph, a paragraph: `ONEBUILD_API_KEY` and `SERPAPI_KEY` in `api/.env` turn on market estimates; without them every market row says so and nothing else is affected. *Known limitations*: "Market estimates are catalog and shopping prices, not contractor net pricing; the supplier price sheet is how a real quote gets in."
- `docs/README.md`: add the row `| Estimate-first pricing | specs/estimate-first-pricing.md | plans/estimate-first-pricing.md | in progress |`.

- [ ] **Step 7: Full suite, build, commit**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q && cd .. && npm test -- --run && npm run build`
Expected: all green.

```bash
git add api/eval/pricing_coverage.py api/tests/test_eval_pricing_coverage.py CLAUDE.md README.md docs/README.md
git commit -m "Pricing coverage eval, migration verified both ways, docs"
```

- [ ] **Step 8: After the keys exist — the real coverage run**

With `ONEBUILD_API_KEY` and `SERPAPI_KEY` in `api/.env`: `cd api && ../.enginevenv/bin/python -m eval.pricing_coverage --zip 78701`. Paste the first table (counts only, no prices) into `docs/specs/estimate-first-pricing.md` §10 under a "Result" heading, and note the decision it supports (both sources / 1build only). Commit as "Spec: coverage result".

---

## Self-review

**Spec coverage.** §1 chain → Task 2. §2 sources → Task 5. §3 job, classification, cache, cap, location, keys absent, reprocess → Tasks 3, 6; ZIP → Task 4. §4 data model → Task 1 (`ProjectMaterialPrice.supplier_name/quote_date`, `MarketLookup`, `ItemMarketPrice`, `postal_code`, migration 0025). §5 resolution, outcomes copy, warnings → Tasks 2, 7. §6 supplier sheets: request → Tasks 9, 10; upload as `Pricing` document → Task 9; preview in the worker → Task 10; apply as one `commit()` + company save → Task 10; modal → Task 11. §7 security → Task 5 (trimming, https-only), Task 9 (only price and key interpreted). §8 API surface → Tasks 4, 7, 10; frontend files → Tasks 8, 11. §10 tests → each task; coverage eval → Task 12. §11 dependencies/config → Task 1.

**Gaps found and folded in:** the spec's §3 "a ZIP being set queues a price job" — added to Task 7 Step 4 on `patch_postal_code`. `set_doc_type` retyping a `Pricing` sheet — Task 9 Step 4. `MATERIAL_PRICE_SNAPSHOT_TYPES` gaining the two columns so undo round-trips them — Task 10 Step 6.

**Type consistency.** `resolve_material_price(item, project, override, company_price, market=None)` (Task 2) is what Task 7 calls. `SourceResult` fields (Task 5) are what Task 6's `_write` and `_result_from_cache` read. `queue.enqueue_price(db, project, requested_by, run_id=None)` is used identically in Tasks 6, 7, and 4/7's postal-code hook. Preview payload keys (`matched[].item_id`, `new_unit_price` as a string) are the same in Task 10's job, its apply route, and Task 11's mapping. `ItemMarketPrice.outcome` values are exactly `market.copy.OUTCOMES`.

**Open detail an implementer must check, named rather than guessed:** the `BlobStore` read method name in Task 10 Step 4 (`blob_to_tempfile` in `app/worker/blobs.py` shows it); the project cache-bust helper names in Task 4 Step 6 and Task 11 Step 3 (`api.js` around `setMaterialPrice` shows the one used); whether `router.py` already imports `queue`.
