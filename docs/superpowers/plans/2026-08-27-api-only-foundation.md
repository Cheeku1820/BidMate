# API-only foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the backend the ability to receive a processed takeoff, then delete the `localStorage` seed store so the API is the only data source.

**Architecture:** A new `POST /api/projects/{id}/takeoff` endpoint accepts the engine's payload, maps it to domain rows server-side, and replaces the project's takeoff in one transaction — refusing with a 409 if that would discard estimator approvals. The client's api store gains `attachEngineTakeoff`, and every seed module is then deleted.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, Postgres, pytest. React 18, Vite, Vitest, React Testing Library.

**Spec:** [`2026-08-27-api-only-foundation-design.md`](../specs/2026-08-27-api-only-foundation-design.md)

## Global Constraints

- **Order is load-bearing.** Tasks 1–7 must land before Task 9 deletes the seed store. The app cannot process a document into a reviewable takeoff until Task 7 is done.
- **Status vocabulary is closed.** `ready`, `attention`, `missing`, `approved`. Never add a fifth. `rejected` is a field, not a status.
- **`WarningReason` is a closed vocabulary:** `scale`, `legend`, `schedule_conflict`. Extending it requires a deliberate migration.
- **Every warning carries five fields:** `reason`, `title`, `found`, `why`, `fix`, `where`. A partial warning is a schema error, rejected at the API boundary.
- **Every mutation is attributable** — routed through `app.takeoff.actions.commit()`, never `db.add()` for a reviewable change.
- **The engine stops at total direct cost.** No markup, overhead, profit, or tax.
- **Sheet space is 1000 × 750.** Engine coordinates are PDF points and must be normalized per sheet.
- **Copy rules:** sentence case, no exclamation marks, no "successfully", no "please". Error copy names a recovery action. Never surface model names, confidence scores, or processing internals.
- **Run `npm run build` before committing** client changes. Backend tests need `TEST_DATABASE_URL` set to a database that is not `DATABASE_URL`.

---

## File Structure

**Created**
- `api/migrations/versions/0011_engine_ingest_columns.py` — additive columns
- `api/app/takeoff/ingest.py` — pure engine→domain mapping, no DB access
- `api/app/takeoff/ingest_service.py` — transactional replace + approval guard
- `api/app/create_admin.py` — org + user CLI, replacing `seed.py`
- `api/tests/test_ingest_mapping.py`, `api/tests/test_ingest_endpoint.py`
- `src/lib/vocabulary.js` — the status vocabulary, renamed from `data.js`

**Modified**
- `api/app/engine/estimate.py` — carry `symbol` and `warning` through the row builders
- `api/app/takeoff/models.py`, `schemas.py`, `mutations.py` — new columns, ingest schema, endpoint
- `src/lib/store/api.js` — `attachEngineTakeoff`
- `src/lib/store/index.js` — collapse to the api store
- `src/components/documents/ProcessingStatus.jsx` — confirmation dialog, sample path removed

**Deleted**
- `src/lib/store/seed*.js`, `local-transport.js`, `src/lib/data.js`, `src/components/documents/SampleBanner.jsx`
- `api/app/seed.py`, `api/tests/test_seed.py`
- `demo/index.html`, `vite.demo.config.js`, `.github/workflows/deploy.yml`

---

## Task 1: Migration — columns the engine produces

**Files:**
- Create: `api/migrations/versions/0011_engine_ingest_columns.py`
- Modify: `api/app/takeoff/models.py` (Sheet ~line 105, Item ~line 122)
- Test: `api/tests/test_takeoff_models.py`

**Interfaces:**
- Produces: `Sheet.takeoff_id`, `Sheet.page_index`, `Sheet.width_pt`, `Sheet.height_pt`, `Sheet.unreadable_reason`, `Sheet.ai_reading`; `Item.material_cost`, `Item.labor_hours`, `Item.labor_cost`, `Item.total_cost`, `Item.placements`, `Item.ai_confirmed`

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_takeoff_models.py`:

```python
def test_sheet_carries_engine_page_metadata(db, project):
    """The canvas fetches a page image by takeoff_id + page_index, and
    normalizes marker coordinates against the page's point dimensions.
    Without these the ingested sheet renders no image and no markers."""
    sheet = Sheet(
        project_id=project.id, number="E2.1", title="Power plan",
        discipline="Electrical", revision="3", scale="", plan="",
        takeoff_id="tk-abc", page_index=2, width_pt=3024, height_pt=2160,
        unreadable_reason="", ai_reading={"summary": "reads as a power plan"},
    )
    db.add(sheet)
    db.flush()
    assert sheet.takeoff_id == "tk-abc"
    assert sheet.page_index == 2
    assert sheet.width_pt == 3024
    assert sheet.height_pt == 2160
    assert sheet.ai_reading == {"summary": "reads as a power plan"}


def test_sheet_engine_metadata_defaults_are_safe(db, project):
    """A sheet created without engine metadata (any pre-ingest path) is
    still valid -- the migration adds no required column."""
    sheet = Sheet(
        project_id=project.id, number="E1.1", title="Lighting",
        discipline="Electrical", revision="1", scale="", plan="",
    )
    db.add(sheet)
    db.flush()
    assert sheet.takeoff_id == ""
    assert sheet.page_index == 0
    assert sheet.ai_reading is None


def test_item_carries_cost_and_placements(db, project, sheet):
    """The spreadsheet's cost columns and the canvas's multi-placement
    markers both read these. The engine stops at total direct cost --
    there is deliberately no markup column here."""
    item = Item(
        project_id=project.id, sheet_id=sheet.id, symbol="receptacle",
        name="20A duplex receptacle", system="Power", category="Devices",
        quantity=47, unit="ea", status=ReviewStatus.READY,
        material_cost=Decimal("188.00"), labor_hours=Decimal("15.51"),
        labor_cost=Decimal("1209.78"), total_cost=Decimal("1397.78"),
        placements=[[120, 340], [180, 340]], ai_confirmed=True,
    )
    db.add(item)
    db.flush()
    assert item.material_cost == Decimal("188.00")
    assert item.total_cost == Decimal("1397.78")
    assert item.placements == [[120, 340], [180, 340]]
    assert item.ai_confirmed is True
```

Add to that file's imports: `from decimal import Decimal` and ensure `ReviewStatus` and `Sheet` are imported from `app.takeoff.models`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_takeoff_models.py -k engine_page_metadata -v`
Expected: FAIL — `TypeError: 'takeoff_id' is an invalid keyword argument for Sheet`

- [ ] **Step 3: Add the columns to the models**

In `api/app/takeoff/models.py`, inside `class Sheet`, after `sort_order`:

```python
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
```

Inside `class Item`, after `evidence`:

```python
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
```

Ensure the file imports `Boolean` and `Text` from `sqlalchemy` and `Decimal` from `decimal` (check the existing import block first — `Numeric`, `Integer`, `JSONB`, and `String` are already imported).

- [ ] **Step 4: Write the migration**

Create `api/migrations/versions/0011_engine_ingest_columns.py`:

```python
"""engine_ingest_columns

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-27 00:00:00.000000

Convention: revision ids match the versions/ filename sequence number
rather than the autogenerated hash, so the chain and the directory
listing always agree.

Adds the columns the takeoff engine produces and the built UI already
renders: per-sheet page metadata (so the canvas can fetch the right page
image and normalize marker coordinates against the right page size) and
per-item cost, placements, and the vision-pass confirmation flag.

Every column is defaulted or nullable, so no backfill step is needed --
the only rows that exist are fixtures being deleted in the same slice.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sheets', sa.Column('takeoff_id', sa.String(length=100), nullable=False, server_default=''))
    op.add_column('sheets', sa.Column('page_index', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('sheets', sa.Column('width_pt', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('sheets', sa.Column('height_pt', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('sheets', sa.Column('unreadable_reason', sa.Text(), nullable=False, server_default=''))
    op.add_column('sheets', sa.Column('ai_reading', JSONB(), nullable=True))

    op.add_column('items', sa.Column('material_cost', sa.Numeric(12, 2), nullable=False, server_default='0'))
    op.add_column('items', sa.Column('labor_hours', sa.Numeric(12, 2), nullable=False, server_default='0'))
    op.add_column('items', sa.Column('labor_cost', sa.Numeric(12, 2), nullable=False, server_default='0'))
    op.add_column('items', sa.Column('total_cost', sa.Numeric(12, 2), nullable=False, server_default='0'))
    op.add_column('items', sa.Column('placements', JSONB(), nullable=True))
    op.add_column('items', sa.Column('ai_confirmed', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    for col in ('ai_confirmed', 'placements', 'total_cost', 'labor_cost', 'labor_hours', 'material_cost'):
        op.drop_column('items', col)
    for col in ('ai_reading', 'unreadable_reason', 'height_pt', 'width_pt', 'page_index', 'takeoff_id'):
        op.drop_column('sheets', col)
```

- [ ] **Step 5: Run the tests**

Run: `cd api && pytest tests/test_takeoff_models.py -v`
Expected: PASS (all three new tests)

- [ ] **Step 6: Verify the migration applies**

Run: `cd api && alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
Expected: no error. This proves `downgrade()` is real, not decorative.

- [ ] **Step 7: Commit**

```bash
git add api/migrations/versions/0011_engine_ingest_columns.py api/app/takeoff/models.py api/tests/test_takeoff_models.py
git commit -m "Add the columns the engine produces to sheets and items"
```

---

## Task 2: Stop the engine dropping symbol and warning

**Files:**
- Modify: `api/app/engine/estimate.py:160-215` (`_row_from_spec`, `_row_from_catalog`)
- Test: `api/tests/test_engine_classify.py`

**Interfaces:**
- Consumes: `ClassifiedItem.symbol`, `ClassifiedItem.warning` (`api/app/engine/contracts.py:55-69`)
- Produces: engine rows gain `"symbol"` and `"warning"` keys. Task 3's mapper reads both.

**Why this task exists:** `classification.py` computes a `symbol` and a four-field `warning` for every item, and both row builders throw them away. Two consequences: the client re-derives symbols by fuzzy string matching on the item name, and every *Needs attention* item reaches review with **no warning to act on** — which is precisely the four-question guarantee the product rests on.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_engine_classify.py`:

```python
from app.engine import estimate as estimate_mod
from app.engine.contracts import ClassifiedItem, Placement


class _FakeCluster:
    def __init__(self):
        self.count = 3
        self.tag = "F2"
        self.sheet_page_index = 0
        self.placements = [Placement(x=10, y=20)]


def test_row_from_catalog_carries_symbol_and_warning():
    """classification.py already decided both. Dropping them here is why
    an attention item used to reach review with nothing to act on, and
    why the client had to guess a symbol from the item's name."""
    warning = {
        "reason": "legend", "title": "Symbol not in legend",
        "found": "Tag F2 appears 3 times on E2.1 but isn't a recognized device.",
        "why": "An unclassified symbol has no catalog item, so it isn't counted or priced yet.",
        "fix": "Assign a classification, or reject it if it isn't a device.",
        "where": "E2.1.",
    }
    item = ClassifiedItem(
        catalog_id="unknown", name="Unclassified symbol F2", system="Unknown",
        category="Unclassified", unit="ea", symbol="generic", quantity=3,
        sheet_page_index=0, placements=[Placement(x=10, y=20)],
        status="attention", warning=warning, source_tag="F2",
    )
    row = estimate_mod._row_from_catalog(item, _FakeCluster(), [], 78.0, 1.0)
    assert row["symbol"] == "generic"
    assert row["warning"] == warning


def test_row_from_spec_marks_attention_with_a_warning():
    """The LLM path sets status=attention whenever confidence isn't high.
    An attention item with no warning gives the estimator no recovery
    action, so the row builder supplies the four-field shape."""
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["status"] == "attention"
    assert row["warning"] is not None
    for field in ("reason", "title", "found", "why", "fix", "where"):
        assert row["warning"][field], f"warning is missing {field}"


def test_row_from_spec_high_confidence_carries_no_warning():
    spec = {"name": "20A duplex receptacle", "system": "Power", "category": "Devices",
            "unit": "ea", "confidence": "high", "material_cost": 4, "labor_hours": 0.33}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["status"] == "ready"
    assert row["warning"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_engine_classify.py -k "symbol_and_warning or attention_with_a_warning" -v`
Expected: FAIL with `KeyError: 'symbol'`

- [ ] **Step 3: Carry both through**

In `api/app/engine/estimate.py`, add this helper above `_row_from_spec`:

```python
def _unconfirmed_type_warning(tag: str, count: int, sheet_no: str) -> dict:
    """The four-field shape for an item the classifier could not place
    confidently. An attention item with no warning tells the estimator
    something is wrong but not what to do about it, which is the one
    thing a warning exists to prevent."""
    return {
        "reason": "legend",
        "title": "Item type needs confirmation",
        "found": f"Type {tag} appears {count} times on {sheet_no}, but its description could not be matched to a schedule with confidence.",
        "why": "The exact item and its price can't be confirmed until the type is matched to the schedule.",
        "fix": "Confirm the item type against the schedule, then approve.",
        "where": f"{sheet_no} and the project schedules.",
    }
```

In `_row_from_spec`, replace the `status = ...` line and add two keys to the returned dict:

```python
    status = "ready" if spec.get("confidence") == "high" else "attention"
    sheet_no = _sheet_no(sheets, cluster.sheet_page_index)
    warning = None if status == "ready" else _unconfirmed_type_warning(cluster.tag, qty, sheet_no)
```

Then in that dict, change `"sheet": _sheet_no(sheets, cluster.sheet_page_index),` to `"sheet": sheet_no,` and add:

```python
        "symbol": spec.get("symbol", ""),
        "warning": warning,
```

In `_row_from_catalog`, add to the returned dict:

```python
        "symbol": item.symbol,
        "warning": item.warning,
```

- [ ] **Step 4: Run the tests**

Run: `cd api && pytest tests/test_engine_classify.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/estimate.py api/tests/test_engine_classify.py
git commit -m "Carry the classifier's symbol and warning through to engine rows"
```

---

## Task 3: The engine→domain mapper

**Files:**
- Create: `api/app/takeoff/ingest.py`
- Test: `api/tests/test_ingest_mapping.py`

**Interfaces:**
- Consumes: engine payload rows from Task 2 (`symbol`, `warning`, `placements`, cost keys)
- Produces:
  - `normalize_point(value: int | float, extent: int, target: int) -> int`
  - `infer_symbol(name: str, system: str) -> str`
  - `validate_warning(raw: dict) -> dict` — raises `DomainError("invalid_warning", ..., status=422)`
  - `map_payload(payload: dict) -> MappedTakeoff` where `MappedTakeoff` is a dataclass with `.sheets: list[dict]` and `.items: list[dict]`; each item dict carries `sheet_key: str` naming the sheet it belongs to, and each sheet dict carries `key: str`

This module does **no database access** — pure functions, so the mapping is testable without Postgres.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_ingest_mapping.py`:

```python
"""app/takeoff/ingest.py -- the engine payload to domain mapping, moved
server-side from the client's seed-ingest.js. Pure functions: no database.
"""
import pytest

from app.errors import DomainError
from app.takeoff.ingest import infer_symbol, map_payload, normalize_point, validate_warning

SHEET_SPACE_W = 1000
SHEET_SPACE_H = 750


def _payload(**over):
    base = {
        "sheets": [
            {"id": "tk1:0", "number": "E2.1", "takeoff_id": "tk1", "page": 0,
             "width_pt": 2000, "height_pt": 1500, "unreadable": None, "ai_reading": None},
        ],
        "items": [
            {"name": "20A duplex receptacle", "system": "Power", "category": "Devices",
             "unit": "ea", "quantity": 47, "status": "ready", "sheet_id": "tk1:0",
             "symbol": "receptacle", "warning": None, "x": 1000, "y": 750,
             "placements": [[1000, 750], [500, 375]],
             "material_cost": 188.0, "labor_hours": 15.51, "labor_cost": 1209.78,
             "total_cost": 1397.78, "ai_confirmed": False},
        ],
    }
    base.update(over)
    return base


def test_normalize_point_scales_into_sheet_space():
    """A point at the middle of a 2000pt-wide page is the middle of the
    1000-unit sheet space."""
    assert normalize_point(1000, 2000, SHEET_SPACE_W) == 500
    assert normalize_point(0, 2000, SHEET_SPACE_W) == 0
    assert normalize_point(2000, 2000, SHEET_SPACE_W) == 1000


def test_normalize_point_survives_a_zero_extent():
    """A sheet the engine could not measure must not divide by zero and
    take the whole ingest down with it."""
    assert normalize_point(500, 0, SHEET_SPACE_W) == 0


def test_map_payload_normalizes_against_the_items_own_sheet():
    """Two sheets of different sizes: an item's coordinates must be scaled
    by ITS sheet's dimensions, or markers land wrongly on one of them."""
    payload = _payload(
        sheets=[
            {"id": "tk1:0", "number": "E1.1", "takeoff_id": "tk1", "page": 0,
             "width_pt": 2000, "height_pt": 1500, "unreadable": None, "ai_reading": None},
            {"id": "tk1:1", "number": "E2.1", "takeoff_id": "tk1", "page": 1,
             "width_pt": 4000, "height_pt": 3000, "unreadable": None, "ai_reading": None},
        ],
        items=[
            {"name": "Panel", "system": "Distribution", "category": "Gear", "unit": "ea",
             "quantity": 1, "status": "ready", "sheet_id": "tk1:0", "symbol": "panel",
             "warning": None, "x": 1000, "y": 750, "placements": [],
             "material_cost": 0, "labor_hours": 0, "labor_cost": 0, "total_cost": 0},
            {"name": "Panel", "system": "Distribution", "category": "Gear", "unit": "ea",
             "quantity": 1, "status": "ready", "sheet_id": "tk1:1", "symbol": "panel",
             "warning": None, "x": 1000, "y": 750, "placements": [],
             "material_cost": 0, "labor_hours": 0, "labor_cost": 0, "total_cost": 0},
        ],
    )
    mapped = map_payload(payload)
    first = next(i for i in mapped.items if i["sheet_key"] == "tk1:0")
    second = next(i for i in mapped.items if i["sheet_key"] == "tk1:1")
    assert (first["x"], first["y"]) == (500, 500)
    assert (second["x"], second["y"]) == (250, 250)


def test_map_payload_normalizes_every_placement():
    mapped = map_payload(_payload())
    assert mapped.items[0]["placements"] == [[500, 500], [250, 250]]


def test_map_payload_carries_cost_and_sheet_metadata():
    mapped = map_payload(_payload())
    item = mapped.items[0]
    assert item["material_cost"] == 188.0
    assert item["total_cost"] == 1397.78
    sheet = mapped.sheets[0]
    assert sheet["takeoff_id"] == "tk1"
    assert sheet["width_pt"] == 2000
    assert sheet["number"] == "E2.1"


def test_map_payload_prefers_the_engines_symbol():
    """The classifier already chose a symbol; guessing from the name is
    only a fallback for rows that carry none."""
    mapped = map_payload(_payload())
    assert mapped.items[0]["symbol"] == "receptacle"


def test_map_payload_falls_back_to_inferring_a_symbol():
    payload = _payload()
    payload["items"][0]["symbol"] = ""
    mapped = map_payload(payload)
    assert mapped.items[0]["symbol"] == "receptacle"


def test_infer_symbol_maps_names_to_glyphs():
    assert infer_symbol("20A duplex receptacle", "Power") == "receptacle"
    assert infer_symbol("Single-pole switch", "Power") == "switch"
    assert infer_symbol("Panelboard LP-2", "Distribution") == "panel"
    assert infer_symbol("High bay fixture", "Lighting") == "highbay"
    assert infer_symbol("2x4 troffer", "Lighting") == "troffer"
    assert infer_symbol("Data outlet", "Low voltage") == "data"
    assert infer_symbol("Something unheard of", "") == "junction"


def test_validate_warning_accepts_the_full_shape():
    warning = {"reason": "legend", "title": "Symbol not in legend", "found": "f",
               "why": "w", "fix": "x", "where": "E2.1"}
    assert validate_warning(warning)["reason"] == "legend"


@pytest.mark.parametrize("missing", ["title", "found", "why", "fix", "where"])
def test_validate_warning_rejects_a_partial_warning(missing):
    """A warning missing a field is a schema error, not a copy oversight --
    and the refusal names the field so the pipeline can be fixed."""
    warning = {"reason": "legend", "title": "t", "found": "f", "why": "w", "fix": "x", "where": "E2.1"}
    del warning[missing]
    with pytest.raises(DomainError) as exc:
        validate_warning(warning)
    assert exc.value.status == 422
    assert missing in exc.value.message


def test_validate_warning_rejects_an_unknown_reason():
    """WarningReason is a closed vocabulary. A new kind of warning needs a
    migration someone writes on purpose, not a string that slips through."""
    warning = {"reason": "vibes", "title": "t", "found": "f", "why": "w", "fix": "x", "where": "E2.1"}
    with pytest.raises(DomainError) as exc:
        validate_warning(warning)
    assert exc.value.status == 422


def test_map_payload_rejects_an_item_on_an_unknown_sheet():
    payload = _payload()
    payload["items"][0]["sheet_id"] = "tk9:404"
    with pytest.raises(DomainError) as exc:
        map_payload(payload)
    assert exc.value.status == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_ingest_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.takeoff.ingest'`

- [ ] **Step 3: Write the mapper**

Create `api/app/takeoff/ingest.py`:

```python
"""ingest.py -- maps the takeoff engine's payload into domain rows.

This mapping used to live in the client (src/lib/store/seed-ingest.js).
It belongs on the server: it is domain logic, and ROADMAP invariant 7
keeps processing internals behind the API boundary. Pure functions, no
database access, so the mapping is testable without Postgres.

Coordinates arrive as PDF points and are normalized into the canvas's
fixed 1000x750 sheet space against EACH SHEET'S OWN dimensions -- a
sheet's markers land wrongly if scaled by another sheet's page size.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.errors import DomainError
from app.takeoff.models import WarningReason

SHEET_SPACE_W = 1000
SHEET_SPACE_H = 750

WARNING_FIELDS = ("title", "found", "why", "fix", "where")
VALID_REASONS = {r.value for r in WarningReason}


@dataclass
class MappedTakeoff:
    sheets: list[dict]
    items: list[dict]


def normalize_point(value, extent: int, target: int) -> int:
    """Scale a PDF point into sheet space. An unmeasured page (extent 0)
    yields 0 rather than dividing by zero and failing the whole ingest."""
    if not extent:
        return 0
    return round((float(value or 0) / float(extent)) * target)


def infer_symbol(name: str, system: str) -> str:
    """Fallback glyph choice for a row that carries no symbol of its own.
    The classifier's symbol is preferred wherever it exists."""
    n = (name or "").lower()
    sys = (system or "").lower()
    if "gfci" in n or "receptacle" in n or ("outlet" in n and "data" not in n):
        return "receptacle"
    if "switch" in n:
        return "switch"
    if "disconnect" in n:
        return "disconnect"
    if "panel" in n or "board" in n:
        return "panel"
    if "junction" in n or "box" in n:
        return "junction"
    if "data" in n or "telecom" in n or "outlet" in n or "low voltage" in sys:
        return "data"
    if "exit" in n:
        return "exit"
    if "high bay" in n or "highbay" in n:
        return "highbay"
    if any(w in n for w in ("troffer", "downlight", "luminaire", "fixture", "light")) or sys == "lighting":
        return "troffer"
    return "junction"


def validate_warning(raw: dict) -> dict:
    """Four fields plus a typed reason, or the write is refused.

    A warning that skips one leaves the estimator without an answer to
    'what do I do about this', which is the whole reason the shape is
    enforced here rather than trusted from the pipeline.
    """
    if not isinstance(raw, dict):
        raise DomainError("invalid_warning", "A warning must be an object with reason, title, found, why, fix, and where.", status=422)
    missing = [f for f in WARNING_FIELDS if not str(raw.get(f) or "").strip()]
    if missing:
        raise DomainError(
            "invalid_warning",
            f"A warning is missing required field(s): {', '.join(missing)}. Every warning states what was found, why it matters, what to check, and where the evidence is.",
            status=422,
        )
    reason = str(raw.get("reason") or "").strip()
    if reason not in VALID_REASONS:
        raise DomainError(
            "invalid_warning",
            f"A warning carries an unrecognized reason {reason!r}. Recognized reasons are: {', '.join(sorted(VALID_REASONS))}.",
            status=422,
        )
    return {
        "reason": reason,
        "title": str(raw["title"]).strip(),
        "found": str(raw["found"]).strip(),
        "why": str(raw["why"]).strip(),
        "fix": str(raw["fix"]).strip(),
        "where": str(raw["where"]).strip(),
    }


def map_payload(payload: dict) -> MappedTakeoff:
    """Engine payload -> domain rows, keyed by the engine's sheet ids.

    `sheet_key` on each item names the sheet dict's `key`; the service
    layer resolves those to real database ids after inserting sheets.
    """
    sheets: list[dict] = []
    dims: dict[str, tuple[int, int]] = {}

    for index, raw in enumerate(payload.get("sheets") or []):
        key = str(raw.get("id") or f"sheet-{index}")
        width = int(raw.get("width_pt") or 0)
        height = int(raw.get("height_pt") or 0)
        dims[key] = (width, height)
        sheets.append({
            "key": key,
            "number": str(raw.get("number") or f"E{index + 1}"),
            "title": str(raw.get("title") or "Electrical plan"),
            "discipline": "Electrical",
            "revision": str(raw.get("revision") or ""),
            "scale": str(raw.get("scale") or ""),
            "plan": "",
            "sort_order": index,
            "takeoff_id": str(raw.get("takeoff_id") or payload.get("takeoff_id") or ""),
            "page_index": int(raw.get("page") or 0),
            "width_pt": width,
            "height_pt": height,
            "unreadable_reason": str(raw.get("unreadable") or ""),
            "ai_reading": raw.get("ai_reading"),
        })

    fallback = sheets[0]["key"] if sheets else None
    items: list[dict] = []

    for raw in payload.get("items") or []:
        key = str(raw.get("sheet_id") or fallback or "")
        if key not in dims:
            raise DomainError(
                "invalid_takeoff",
                f"An item references sheet {key!r}, which is not in the processed set.",
                status=422,
            )
        width, height = dims[key]
        name = str(raw.get("name") or "Unclassified item")
        system = str(raw.get("system") or "Unknown")
        warning = raw.get("warning")
        items.append({
            "sheet_key": key,
            "symbol": str(raw.get("symbol") or "") or infer_symbol(name, system),
            "name": name,
            "description": str(raw.get("description") or ""),
            "system": system,
            "category": str(raw.get("category") or ""),
            "quantity": raw.get("quantity") or 0,
            "unit": str(raw.get("unit") or "ea"),
            "status": str(raw.get("status") or "ready"),
            "x": normalize_point(raw.get("x"), width, SHEET_SPACE_W),
            "y": normalize_point(raw.get("y"), height, SHEET_SPACE_H),
            "placements": [
                [normalize_point(p[0], width, SHEET_SPACE_W), normalize_point(p[1], height, SHEET_SPACE_H)]
                for p in (raw.get("placements") or [])
                if isinstance(p, (list, tuple)) and len(p) >= 2
            ],
            "material_cost": raw.get("material_cost") or 0,
            "labor_hours": raw.get("labor_hours") or 0,
            "labor_cost": raw.get("labor_cost") or 0,
            "total_cost": raw.get("total_cost") or 0,
            "ai_confirmed": bool(raw.get("ai_confirmed")),
            "warning": validate_warning(warning) if warning else None,
        })

    return MappedTakeoff(sheets=sheets, items=items)
```

- [ ] **Step 4: Run the tests**

Run: `cd api && pytest tests/test_ingest_mapping.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/ingest.py api/tests/test_ingest_mapping.py
git commit -m "Map the engine payload to domain rows, server-side"
```

---

## Task 4: Ingest service and endpoint

**Files:**
- Create: `api/app/takeoff/ingest_service.py`
- Modify: `api/app/takeoff/schemas.py`, `api/app/takeoff/mutations.py`
- Test: `api/tests/test_ingest_endpoint.py`

**Interfaces:**
- Consumes: `map_payload`, `MappedTakeoff` (Task 3); `actions.commit()`
- Produces: `ingest_takeoff(db, *, actor: User, project: Project, payload: dict, confirm_replace: bool = False) -> dict` returning `{"sheets": int, "items": int}`; endpoint `POST /api/projects/{project_id}/takeoff`

Approval protection is Task 5 — this task lands the replace path with `confirm_replace` accepted but not yet enforced.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_ingest_endpoint.py`:

```python
"""POST /api/projects/{id}/takeoff -- the endpoint that lets a processed
takeoff reach the database. Before it existed, the backend could serve a
takeoff but never receive one, so processing had nowhere to land.
"""
import uuid

from sqlalchemy import select

from app.takeoff.models import Action, Item, Sheet

PAYLOAD = {
    "sheets": [
        {"id": "tk1:0", "number": "E2.1", "takeoff_id": "tk1", "page": 0,
         "width_pt": 2000, "height_pt": 1500, "unreadable": None, "ai_reading": None},
    ],
    "items": [
        {"name": "20A duplex receptacle", "system": "Power", "category": "Devices",
         "unit": "ea", "quantity": 47, "status": "ready", "sheet_id": "tk1:0",
         "symbol": "receptacle", "warning": None, "x": 1000, "y": 750,
         "placements": [[1000, 750]], "material_cost": 188.0, "labor_hours": 15.51,
         "labor_cost": 1209.78, "total_cost": 1397.78},
    ],
}


def _ingest(client, project_id, payload=None, **body):
    return client.post(f"/api/projects/{project_id}/takeoff",
                       json={"payload": payload or PAYLOAD, **body})


def test_ingest_writes_sheets_and_items(client, db, project, signed_in_user):
    response = _ingest(client, project.id)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == 1

    sheet = db.scalars(select(Sheet).where(Sheet.project_id == project.id)).one()
    assert sheet.number == "E2.1"
    assert sheet.takeoff_id == "tk1"
    item = db.scalars(select(Item).where(Item.project_id == project.id)).one()
    assert item.name == "20A duplex receptacle"
    assert item.x == 500 and item.y == 500
    assert float(item.total_cost) == 1397.78


def test_ingest_replaces_rather_than_appends(client, db, project, signed_in_user):
    """Processing the same set twice yields one takeoff, not two overlaid.
    An append would silently double every count on the bid."""
    _ingest(client, project.id)
    _ingest(client, project.id)
    assert len(list(db.scalars(select(Item).where(Item.project_id == project.id)))) == 1
    assert len(list(db.scalars(select(Sheet).where(Sheet.project_id == project.id)))) == 1


def test_ingest_moves_the_project_to_review(client, db, project, signed_in_user):
    _ingest(client, project.id)
    db.refresh(project)
    assert project.stage == "review"


def test_ingest_records_one_attributable_action(client, db, project, signed_in_user):
    """Every mutation is attributable -- ingest included."""
    _ingest(client, project.id)
    actions = list(db.scalars(select(Action).where(Action.project_id == project.id, Action.kind == "ingest")))
    assert len(actions) == 1
    assert actions[0].actor_user_id == signed_in_user.id


def test_ingest_rejects_a_partial_warning(client, db, project, signed_in_user):
    """Four fields or the write is refused, at the boundary."""
    payload = {**PAYLOAD, "items": [{**PAYLOAD["items"][0], "status": "attention",
               "warning": {"reason": "legend", "title": "t", "found": "f", "why": "w"}}]}
    response = _ingest(client, project.id, payload=payload)
    assert response.status_code == 422
    assert "fix" in response.json()["detail"]["message"]
    assert not list(db.scalars(select(Item).where(Item.project_id == project.id)))


def test_ingest_stores_a_valid_warning(client, db, project, signed_in_user):
    payload = {**PAYLOAD, "items": [{**PAYLOAD["items"][0], "status": "attention",
               "warning": {"reason": "legend", "title": "Symbol not in legend", "found": "f",
                           "why": "w", "fix": "x", "where": "E2.1"}}]}
    assert _ingest(client, project.id, payload=payload).status_code == 200
    item = db.scalars(select(Item).where(Item.project_id == project.id)).one()
    assert item.warnings[0].title == "Symbol not in legend"


def test_ingest_refuses_another_orgs_project(client, other_org_project, signed_in_user):
    """Same 404 whether it does not exist or belongs to someone else."""
    assert _ingest(client, other_org_project.id).status_code == 404


def test_ingest_refuses_an_unknown_project(client, signed_in_user):
    assert _ingest(client, uuid.uuid4()).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_ingest_endpoint.py -v`
Expected: FAIL — 404/405, the route does not exist

- [ ] **Step 3: Write the service**

Create `api/app/takeoff/ingest_service.py`:

```python
"""ingest_service.py -- writing a processed takeoff into a project.

Replacement, not append: processing the same document set twice must
yield one takeoff rather than two overlaid, which on a bid would mean
every count silently doubled.

The whole write is one transaction. A half-written takeoff -- sheets
without their items, items without their warnings -- would render as a
complete but wrong review, which is the failure mode this product exists
to prevent.
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff import actions
from app.takeoff.ingest import map_payload
from app.takeoff.models import Item, Project, ReviewStatus, Sheet, Warning, WarningReason


def ingest_takeoff(
    db: DbSession,
    *,
    actor: User,
    project: Project,
    payload: dict,
    confirm_replace: bool = False,
) -> dict:
    """Replace `project`'s takeoff with the engine's output.

    Mapping and validation happen before a single row is deleted, so a
    payload carrying a partial warning leaves the existing takeoff
    exactly as it was.
    """
    mapped = map_payload(payload)

    existing_sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id)))
    if existing_sheets:
        sheet_ids = [s.id for s in existing_sheets]
        item_ids = list(db.scalars(select(Item.id).where(Item.project_id == project.id)))
        if item_ids:
            db.execute(delete(Warning).where(Warning.item_id.in_(item_ids)))
        db.execute(delete(Warning).where(Warning.sheet_id.in_(sheet_ids)))
        db.execute(delete(Item).where(Item.project_id == project.id))
        db.execute(delete(Sheet).where(Sheet.project_id == project.id))

    sheet_ids_by_key: dict[str, uuid.UUID] = {}
    for row in mapped.sheets:
        sheet = Sheet(
            id=uuid.uuid4(), project_id=project.id, number=row["number"], title=row["title"],
            discipline=row["discipline"], revision=row["revision"], scale=row["scale"],
            scale_options=[], plan=row["plan"], sort_order=row["sort_order"],
            takeoff_id=row["takeoff_id"], page_index=row["page_index"],
            width_pt=row["width_pt"], height_pt=row["height_pt"],
            unreadable_reason=row["unreadable_reason"], ai_reading=row["ai_reading"],
        )
        db.add(sheet)
        sheet_ids_by_key[row["key"]] = sheet.id

    for row in mapped.items:
        item = Item(
            id=uuid.uuid4(), project_id=project.id, sheet_id=sheet_ids_by_key[row["sheet_key"]],
            symbol=row["symbol"], name=row["name"], description=row["description"],
            system=row["system"], category=row["category"], quantity=row["quantity"],
            unit=row["unit"], status=ReviewStatus(row["status"]),
            x=row["x"], y=row["y"], placements=row["placements"],
            material_cost=row["material_cost"], labor_hours=row["labor_hours"],
            labor_cost=row["labor_cost"], total_cost=row["total_cost"],
            ai_confirmed=row["ai_confirmed"],
        )
        db.add(item)
        if row["warning"]:
            w = row["warning"]
            db.add(Warning(
                id=uuid.uuid4(), item_id=item.id, sheet_id=None,
                reason=WarningReason(w["reason"]), title=w["title"], found=w["found"],
                why=w["why"], fix=w["fix"], where_=w["where"],
            ))

    project.stage = "review"

    actions.commit(
        db, actor=actor, project_id=project.id, kind="ingest",
        label=f"Processed {len(mapped.sheets)} sheet(s) into {len(mapped.items)} item(s)",
        before={}, after={},
    )

    return {"sheets": len(mapped.sheets), "items": len(mapped.items)}
```

- [ ] **Step 4: Add the request schema**

In `api/app/takeoff/schemas.py`, append:

```python
class TakeoffIngestIn(BaseModel):
    """The engine's payload, plus the estimator's explicit consent to
    replace approved work (see ingest_service for when that is required)."""

    payload: dict
    confirm_replace: bool = False


class TakeoffIngestOut(BaseModel):
    sheets: int
    items: int
```

- [ ] **Step 5: Add the endpoint**

In `api/app/takeoff/mutations.py`, add the imports:

```python
from app.takeoff.ingest_service import ingest_takeoff
from app.takeoff.schemas import TakeoffIngestIn, TakeoffIngestOut
```

and the route:

```python
@router.post("/projects/{project_id}/takeoff", response_model=TakeoffIngestOut)
def post_takeoff(
    project_id: uuid.UUID,
    payload: TakeoffIngestIn,
    db: DbSession = Depends(get_db),
    user: User = Depends(current_user),
) -> TakeoffIngestOut:
    project = load_project(project_id, db, user)
    result = ingest_takeoff(
        db, actor=user, project=project,
        payload=payload.payload, confirm_replace=payload.confirm_replace,
    )
    db.commit()
    return TakeoffIngestOut(**result)
```

Check the top of `mutations.py` for how it imports `load_project` — reuse the same import rather than adding a second path to it.

- [ ] **Step 6: Run the tests**

Run: `cd api && pytest tests/test_ingest_endpoint.py -v`
Expected: PASS

- [ ] **Step 7: Pin what undo does after an ingest**

`undo.REVERSIBLE` deliberately does not contain `"ingest"`, so an ingest is not itself undoable. But the stack still holds pre-ingest actions pointing at items the ingest deleted, and undo must fail honestly rather than resurrect a row from a takeoff that no longer exists. Append to `api/tests/test_ingest_endpoint.py`:

```python
def test_undo_after_ingest_refuses_instead_of_resurrecting(client, db, project, sheet, signed_in_user):
    """Ingest replaces the takeoff, so actions recorded against the old
    items point at rows that are gone. Undo must say so plainly rather
    than restore an item into a takeoff it was never part of."""
    from app.takeoff.models import Item, ReviewStatus

    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Panel LP-2",
                system="Distribution", category="Gear", quantity=1, unit="ea",
                status=ReviewStatus.READY)
    db.add(item)
    db.commit()

    assert client.post(f"/api/items/{item.id}/approve",
                       headers={"If-Match": "1"}).status_code in (200, 409)
    _ingest(client, project.id, confirm_replace=True)

    response = client.post(f"/api/projects/{project.id}/undo")
    # Either there is nothing eligible to undo, or the eligible action
    # names an item that is gone. Both are honest; a 500 is not.
    assert response.status_code in (200, 409)
    if response.status_code == 409:
        assert response.json()["detail"]["code"] == "item_no_longer_exists"
```

If this test fails with a 500, stop and fix the cause before continuing — an unhandled error here means undo can crash after every re-process.

- [ ] **Step 8: Run the whole backend suite**

Run: `cd api && pytest -q`
Expected: PASS — no regression in snapshot, totals, or undo tests.

- [ ] **Step 9: Commit**

```bash
git add api/app/takeoff/ingest_service.py api/app/takeoff/schemas.py api/app/takeoff/mutations.py api/tests/test_ingest_endpoint.py
git commit -m "Let a processed takeoff be written into a project"
```

---

## Task 5: Refuse to discard approvals without consent

**Files:**
- Modify: `api/app/takeoff/ingest_service.py`
- Test: `api/tests/test_ingest_endpoint.py`

**Interfaces:**
- Consumes: `ingest_takeoff(..., confirm_replace: bool)` from Task 4
- Produces: `DomainError("approved_items_present", <message naming the count>, status=409)`. The client keys on that exact code string in Task 7.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_ingest_endpoint.py`:

```python
def _approve_one(db, project, sheet, user):
    from app.takeoff.models import Item, ReviewStatus
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Panel LP-2",
                system="Distribution", category="Gear", quantity=1, unit="ea",
                status=ReviewStatus.APPROVED, approved_by_user_id=user.id)
    db.add(item)
    db.flush()
    return item


def test_ingest_refuses_when_approvals_would_be_lost(client, db, project, sheet, signed_in_user):
    """Replacing a takeoff that holds approvals discards a person's
    professional judgment. Product spec section 6 requires confirmation
    before discarding corrections, so the server refuses by default."""
    _approve_one(db, project, sheet, signed_in_user)
    db.commit()

    response = _ingest(client, project.id)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "approved_items_present"
    assert "1" in detail["message"]


def test_ingest_refusal_writes_nothing(client, db, project, sheet, signed_in_user):
    """The refusal must leave the takeoff untouched -- a half-applied
    refusal is worse than either outcome."""
    approved = _approve_one(db, project, sheet, signed_in_user)
    db.commit()

    _ingest(client, project.id)

    db.expire_all()
    still_there = db.get(Item, approved.id)
    assert still_there is not None
    assert still_there.status.value == "approved"
    assert db.get(Sheet, sheet.id) is not None


def test_ingest_proceeds_once_the_estimator_confirms(client, db, project, sheet, signed_in_user):
    approved = _approve_one(db, project, sheet, signed_in_user)
    db.commit()

    response = _ingest(client, project.id, confirm_replace=True)
    assert response.status_code == 200

    db.expire_all()
    assert db.get(Item, approved.id) is None
    assert db.scalars(select(Item).where(Item.project_id == project.id)).one().name == "20A duplex receptacle"


def test_ingest_needs_no_confirmation_on_a_fresh_project(client, db, project, signed_in_user):
    """First processing has nothing to lose, so the estimator is never
    asked a question with only one answer."""
    assert _ingest(client, project.id).status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_ingest_endpoint.py -k approvals -v`
Expected: FAIL — got 200, expected 409

- [ ] **Step 3: Add the guard**

In `api/app/takeoff/ingest_service.py`, add the import:

```python
from app.errors import DomainError
```

and insert this immediately after `mapped = map_payload(payload)`:

```python
    # Replacing a takeoff destroys whatever it holds, and what it can hold
    # is estimator approvals -- the one act in this product that carries a
    # person's professional judgment, and the legal firewall the status
    # vocabulary rests on. Refuse by default and make the estimator say so.
    #
    # Server-authoritative on purpose: the client's confirmation dialog is
    # good feedback, but this refusal is what actually protects the data.
    if not confirm_replace:
        approved = db.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.project_id == project.id, Item.status == ReviewStatus.APPROVED)
        )
        if approved:
            raise DomainError(
                "approved_items_present",
                f"{approved} item(s) on this project are estimator approved. "
                "Processing again replaces the whole takeoff, and those approvals would be discarded.",
                status=409,
            )
```

Add `func` to the SQLAlchemy import: `from sqlalchemy import delete, func, select`.

- [ ] **Step 4: Run the tests**

Run: `cd api && pytest tests/test_ingest_endpoint.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/ingest_service.py api/tests/test_ingest_endpoint.py
git commit -m "Refuse to replace a takeoff that holds approvals, without consent"
```

---

## Task 6: The api store can attach a takeoff

**Files:**
- Modify: `src/lib/store/api.js`
- Test: `src/lib/store/api.test.js`

**Interfaces:**
- Produces: `attachEngineTakeoff(projectId, payload, { confirmReplace = false } = {})` on the store returned by `createApiStore()`. Rejects with `{ code, message }`; `code === "approved_items_present"` is what `ProcessingStatus` keys on in Task 7.

- [ ] **Step 1: Write the failing test**

Append to `src/lib/store/api.test.js`, following the existing fetch-mocking style in that file:

```javascript
describe("attachEngineTakeoff", () => {
  it("posts the engine payload to the project's takeoff endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ sheets: 2, items: 47 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const store = createApiStore();
    const result = await store.attachEngineTakeoff("p1", { sheets: [], items: [] });

    expect(result).toEqual({ sheets: 2, items: 47 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/projects/p1/takeoff");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      payload: { sheets: [], items: [] },
      confirm_replace: false,
    });
  });

  it("sends confirm_replace only when the estimator has confirmed", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ sheets: 1, items: 1 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const store = createApiStore();
    await store.attachEngineTakeoff("p1", { sheets: [] }, { confirmReplace: true });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body).confirm_replace).toBe(true);
  });

  it("surfaces the server's refusal code so the caller can confirm", async () => {
    const body = JSON.stringify({
      detail: {
        code: "approved_items_present",
        message: "3 item(s) on this project are estimator approved.",
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 409 })));

    const store = createApiStore();
    await expect(store.attachEngineTakeoff("p1", {})).rejects.toMatchObject({
      code: "approved_items_present",
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/lib/store/api.test.js`
Expected: FAIL — `store.attachEngineTakeoff is not a function`

- [ ] **Step 3: Implement it**

In `src/lib/store/api.js`, inside `createApiStore()`, add before the `return {` block:

```javascript
  /** Writes a processed takeoff into the project. The server replaces
   *  rather than appends, and refuses with `approved_items_present` when
   *  that would discard estimator approvals — pass confirmReplace only
   *  after a person has actually been asked. */
  async function attachEngineTakeoff(id, payload, { confirmReplace = false } = {}) {
    const result = await request(`/api/projects/${id}/takeoff`, {
      method: "POST",
      body: { payload, confirm_replace: confirmReplace },
    });
    invalidateCache();
    return result;
  }
```

Add `attachEngineTakeoff,` to the returned object.

- [ ] **Step 4: Run the tests**

Run: `npm test -- src/lib/store/api.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/store/api.js src/lib/store/api.test.js
git commit -m "Let the api store write a processed takeoff"
```

---

## Task 7: Ask before replacing approved work

**Files:**
- Modify: `src/components/documents/ProcessingStatus.jsx`
- Test: `src/components/documents/ProcessingStatus.test.jsx`

**Interfaces:**
- Consumes: `store.attachEngineTakeoff(projectId, payload, { confirmReplace })` (Task 6)

- [ ] **Step 1: Write the failing test**

Replace the sample-path tests in `src/components/documents/ProcessingStatus.test.jsx` with:

```javascript
it("asks before replacing a takeoff that holds approvals", async () => {
  const store = {
    listProjects: vi.fn().mockResolvedValue([{ id: "p1", name: "Riverside" }]),
    attachEngineTakeoff: vi
      .fn()
      .mockRejectedValueOnce({
        code: "approved_items_present",
        message: "3 item(s) on this project are estimator approved.",
      })
      .mockResolvedValueOnce({ sheets: 1, items: 4 }),
  };
  renderProcessing(store);

  // The estimator sees what would be lost, in the server's own words.
  expect(await screen.findByText(/3 item\(s\) on this project are estimator approved/)).toBeInTheDocument();
  expect(store.attachEngineTakeoff).toHaveBeenCalledTimes(1);

  await userEvent.click(screen.getByRole("button", { name: /replace the takeoff/i }));

  await waitFor(() => expect(store.attachEngineTakeoff).toHaveBeenCalledTimes(2));
  expect(store.attachEngineTakeoff.mock.calls[1][2]).toEqual({ confirmReplace: true });
});

it("leaves the takeoff alone when the estimator declines", async () => {
  const store = {
    listProjects: vi.fn().mockResolvedValue([{ id: "p1", name: "Riverside" }]),
    attachEngineTakeoff: vi.fn().mockRejectedValue({
      code: "approved_items_present",
      message: "3 item(s) on this project are estimator approved.",
    }),
  };
  renderProcessing(store);

  await userEvent.click(await screen.findByRole("button", { name: /keep the current takeoff/i }));

  expect(store.attachEngineTakeoff).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: /replace the takeoff/i })).not.toBeInTheDocument();
});
```

Keep the file's existing `renderProcessing` helper and imports; add `userEvent` and `waitFor` if they are not already imported. The helper must seed an uploaded file for `getUploadedFiles(projectId)` so the engine path runs — follow how the existing engine-path test in this file does it.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/components/documents/ProcessingStatus.test.jsx`
Expected: FAIL — no confirmation UI rendered

- [ ] **Step 3: Add the confirmation**

In `ProcessingStatus.jsx`, add state near the other `useState` calls:

```javascript
  // Set when the server refuses to replace a takeoff that holds
  // approvals. Carries the server's own message, which names the count —
  // the estimator is told what they would lose, not asked a vague
  // "are you sure".
  const [replaceConfirm, setReplaceConfirm] = useState(null);
```

Extract the attach into a helper inside the component:

```javascript
  const attachTakeoff = useCallback(
    async (payload, { confirmReplace = false } = {}) => {
      try {
        await store.attachEngineTakeoff(projectId, payload, { confirmReplace });
        clearUploadedFiles(projectId);
        setReplaceConfirm(null);
        setReviewPath(`/projects/${projectId}/takeoff`);
        setMode("done");
      } catch (err) {
        if (err?.code === "approved_items_present") {
          setReplaceConfirm({ message: err.message, payload });
          setMode("confirm-replace");
          return;
        }
        throw err;
      }
    },
    [store, projectId],
  );
```

In the engine path, replace `await store.attachEngineTakeoff(projectId, payload);` and the `clearUploadedFiles`/`setMode("done")` lines that follow it with `await attachTakeoff(payload);` — keeping the `setSummary(...)` call before it.

Render the confirmation when `mode === "confirm-replace"`:

```jsx
{mode === "confirm-replace" && replaceConfirm ? (
  <div className="processing-confirm" role="alertdialog" aria-labelledby="replace-confirm-title">
    <h2 id="replace-confirm-title">Replacing this takeoff discards approved items</h2>
    <p>{replaceConfirm.message}</p>
    <p>Approving an item is a record that a person checked it. Replacing the takeoff removes those records along with the items.</p>
    <div className="processing-confirm-actions">
      <button type="button" className="btn" onClick={() => { setReplaceConfirm(null); setReviewPath(`/projects/${projectId}/takeoff`); setMode("done"); }}>
        Keep the current takeoff
      </button>
      <button type="button" className="btn btn-danger" onClick={() => attachTakeoff(replaceConfirm.payload, { confirmReplace: true })}>
        Replace the takeoff
      </button>
    </div>
  </div>
) : null}
```

Import `useCallback` from React. Add a `.processing-confirm` block to `src/styles.css` using existing tokens — no inline hex.

- [ ] **Step 4: Run the tests**

Run: `npm test -- src/components/documents/ProcessingStatus.test.jsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/documents/ProcessingStatus.jsx src/components/documents/ProcessingStatus.test.jsx src/styles.css
git commit -m "Ask before a re-process discards approved items"
```

---

## Task 8: Split the vocabulary out of data.js

**Files:**
- Create: `src/lib/vocabulary.js`
- Delete: `src/lib/data.js`
- Modify: the nine importers listed below

**Interfaces:**
- Produces: `STATUS`, `STATUS_ORDER`, `SYSTEMS` exported from `src/lib/vocabulary.js`

`data.js` holds two unrelated things: the status vocabulary (imported by nine components) and the twelve-item fixture (imported only by `seed-fixture.js`). This task keeps the first and drops the second, so Task 9's deletion cannot take the vocabulary with it.

- [ ] **Step 1: Create the new module**

Create `src/lib/vocabulary.js` containing **only** the `STATUS`, `STATUS_ORDER`, and `SYSTEMS` exports copied verbatim from `src/lib/data.js` (lines 9–19), with this header:

```javascript
/* ============================================================
   vocabulary.js — the four review labels, their order, and the system
   list. The spine CLAUDE.md protects: four statuses, never a fifth.

   Split out of the former data.js, which carried this alongside the
   twelve-item seed fixture. The fixture is gone; the vocabulary is not
   fixture data and never was.
   ============================================================ */
```

- [ ] **Step 2: Repoint every importer**

Run this to confirm the list, then update each import path from `data.js` to `vocabulary.js`:

```bash
grep -rn "lib/data.js" src
```

Expected files: `ItemDetailPanel.jsx`, `Pill.jsx`, `BlueprintCanvas.jsx`, `Workspace.jsx`, `SheetsRail.jsx`, `MiscModals.jsx`, `takeoff/TakeoffSpreadsheet.jsx`, `takeoff/spreadsheetColumns.js`, `takeoff/BulkApproveBar.jsx`. (`store/seed-fixture.js` also imports it — leave that one; Task 9 deletes the file.)

- [ ] **Step 3: Verify nothing but seed-fixture still references data.js**

Run: `grep -rn "lib/data.js\|from \"../data.js\"" src`
Expected: only `src/lib/store/seed-fixture.js`

- [ ] **Step 4: Run the suite and the build**

Run: `npm test && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/vocabulary.js src/components src/lib
git commit -m "Split the status vocabulary out of the seed fixture file"
```

---

## Task 9: Delete the seed store

**Files:**
- Delete: `src/lib/data.js`, `src/lib/store/seed.js`, `seed-fixture.js`, `seed-ingest.js`, `seed-projects.js`, `seed-review.js`, `seed-scale.js`, `seed-undo.js`, `local-transport.js`, `src/components/documents/SampleBanner.jsx`, and the seed test files (`seed.test.js`, `seed-projects.test.js`, `seed-sample.test.js`, `contract.test.js`)
- Modify: `src/lib/store/index.js`, `src/components/Workspace.jsx:207`, `src/components/takeoff/TakeoffSpreadsheet.jsx:218`, `src/components/projects/ProjectOverview.jsx`, `src/components/documents/ProcessingStatus.jsx`, `src/components/Login.jsx`

- [ ] **Step 1: Collapse the store selector**

Replace the body of `src/lib/store/index.js` with:

```javascript
import { createApiStore } from "./api.js";

/** One data source. The seed/localStorage store this used to choose
 *  between was deleted in the API-only slice — see
 *  docs/superpowers/specs/2026-08-27-api-only-foundation-design.md. */
export function createStore() {
  return createApiStore();
}
```

- [ ] **Step 2: Delete the seed modules**

```bash
git rm src/lib/data.js src/lib/store/seed.js src/lib/store/seed-fixture.js \
  src/lib/store/seed-ingest.js src/lib/store/seed-projects.js src/lib/store/seed-review.js \
  src/lib/store/seed-scale.js src/lib/store/seed-undo.js src/lib/store/local-transport.js \
  src/components/documents/SampleBanner.jsx
git rm src/lib/store/seed.test.js src/lib/store/seed-projects.test.js \
  src/lib/store/seed-sample.test.js src/lib/store/contract.test.js
```

If a listed test file does not exist, skip it — confirm with `ls src/lib/store/`.

- [ ] **Step 3: Remove the sample-takeoff path**

- `Workspace.jsx`: delete the `SampleBanner` import and the `{project?.sample ? <SampleBanner /> : null}` line.
- `TakeoffSpreadsheet.jsx`: same two deletions.
- `ProjectOverview.jsx`: remove the `sample` branch; a project either has a takeoff or does not.
- `ProcessingStatus.jsx`: delete the entire `--- sample fallback (no upload) ---` block, the `SAMPLE_SHEETS` constant, `sampleProgress` state, and the `mode === "sample"` rendering. With no uploaded files there is now nothing to process: set `setError("No documents have been uploaded for this project yet. Upload a drawing set to start a takeoff.")` and `setMode("error")`.
- Remove `project.sample` from `mapProject` in `src/lib/store/api-mapping.js` if present.

- [ ] **Step 4: Unconditional login**

In `src/components/Login.jsx`, remove the comment claiming it only renders under the api store. In `src/lib/store/api.js`, update the `login` docstring that references "the seed store has no login concept" — it now describes the only store.

- [ ] **Step 5: Verify no seed references survive**

Run: `grep -rniE "seed|sample takeoff|VITE_DATA_SOURCE" src/ vite.config.js docker-compose.yml`
Expected: no functional references. Fix anything that remains.

- [ ] **Step 6: Run the suite and the build**

Run: `npm test && npm run build`
Expected: PASS. Tests that mocked the store interface keep passing; delete any test whose only subject was seed behavior.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Delete the seed store: the API is the only data source"
```

---

## Task 10: Replace seed.py with account creation

**Files:**
- Create: `api/app/create_admin.py`
- Delete: `api/app/seed.py`, `api/tests/test_seed.py`
- Test: `api/tests/test_create_admin.py`

**Interfaces:**
- Produces: `create_admin(db, *, email: str, password: str, org_name: str) -> User`, and `python -m app.create_admin`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_create_admin.py`:

```python
"""app/create_admin.py -- the only account-creation path, replacing the
demo seed. It creates an org and a user and nothing else: no project, no
sheets, no items. A migrated database otherwise has no user and the login
screen cannot be passed.
"""
import pytest
from sqlalchemy import func, select

from app.create_admin import create_admin
from app.identity.models import Org, User
from app.takeoff.models import Item, Project, Sheet


def test_create_admin_creates_an_org_and_a_user(db):
    user = create_admin(db, email="you@example.com", password="correct-horse", org_name="Meridian Electric")
    db.flush()
    assert user.email == "you@example.com"
    assert db.get(Org, user.org_id).name == "Meridian Electric"


def test_create_admin_creates_no_project_data(db):
    """This is account creation, not a fixture. Anything else it wrote
    would be the seed data this slice exists to remove."""
    create_admin(db, email="you@example.com", password="correct-horse", org_name="Meridian Electric")
    db.flush()
    assert db.scalar(select(func.count()).select_from(Project)) == 0
    assert db.scalar(select(func.count()).select_from(Sheet)) == 0
    assert db.scalar(select(func.count()).select_from(Item)) == 0


def test_create_admin_stores_a_hashed_password(db):
    user = create_admin(db, email="you@example.com", password="correct-horse", org_name="Meridian")
    db.flush()
    assert "correct-horse" not in (user.password_hash or "")


def test_create_admin_refuses_a_duplicate_email(db):
    create_admin(db, email="you@example.com", password="correct-horse", org_name="Meridian")
    db.flush()
    with pytest.raises(ValueError, match="already exists"):
        create_admin(db, email="you@example.com", password="another-one", org_name="Meridian")
```

Check `api/app/identity/models.py` for the exact `User` password column name and use it in the third test.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_create_admin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.create_admin'`

- [ ] **Step 3: Write the module**

Create `api/app/create_admin.py`:

```python
"""create_admin.py -- creates an org and one user, and nothing else.

This replaces the demo seed (app/seed.py), which loaded a twelve-item
fixture takeoff. That fixture is gone: every row in the product now comes
from a document an estimator actually uploaded.

What could not go with it is account creation. A freshly migrated
database contains no user, so there is no credential the login screen
will accept. This is that step, and only that step -- no project, no
sheets, no items.

No default password: credentials are arguments, and main() exits loudly
if the environment does not supply them.
"""
from __future__ import annotations

import os
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.identity.models import Org, User


def create_admin(db: DbSession, *, email: str, password: str, org_name: str) -> User:
    normalized = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == normalized))
    if existing is not None:
        raise ValueError(f"A user with the email {normalized!r} already exists.")

    org = Org(id=uuid.uuid4(), name=org_name)
    db.add(org)

    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        email=normalized,
        name=normalized.split("@")[0],
        password_hash=hash_password(password),
    )
    db.add(user)
    return user


def main() -> None:
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    org_name = os.environ.get("ADMIN_ORG", "My electrical company")
    if not email or not password:
        raise SystemExit(
            "Set ADMIN_EMAIL and ADMIN_PASSWORD to create the first account. "
            "There is no default password."
        )
    db = SessionLocal()
    try:
        user = create_admin(db, email=email, password=password, org_name=org_name)
        db.commit()
        print(f"Created {user.email} in org {org_name!r}. Sign in with that email and password.", file=sys.stderr)
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

Verify against `api/app/identity/models.py` that `Org` and `User` take these fields (particularly `name` on `User`); adjust to match the real columns rather than assuming.

- [ ] **Step 4: Delete the seed**

```bash
git rm api/app/seed.py api/tests/test_seed.py
```

- [ ] **Step 5: Run the backend suite**

Run: `cd api && pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Replace the demo seed with account creation"
```

---

## Task 11: Delete the demo artifacts and update the docs

**Files:**
- Delete: `demo/index.html`, `vite.demo.config.js`, `.github/workflows/deploy.yml`
- Modify: `package.json`, `README.md`, `CLAUDE.md`, `ROADMAP.md`

- [ ] **Step 1: Delete the artifacts**

```bash
git rm demo/index.html vite.demo.config.js .github/workflows/deploy.yml
```

The single-file demo is a seed-mode build by construction and cannot work without a backend. The Pages workflow would publish a client whose API is unreachable — a page that loads a login screen it can never satisfy.

- [ ] **Step 2: Drop the demo build**

In `package.json`, remove the `build:demo` script and the `vite-plugin-singlefile` devDependency, then run `npm install` to update the lockfile.

- [ ] **Step 3: Rewrite the README's run instructions**

Replace the "Take a look" section (the demo link and the seed-mode instructions) with the real path:

````markdown
## Run it

Everything runs against a real backend — Postgres, the API, and the takeoff engine. There is no fixture data: every row comes from a document you upload. You need [Docker](https://www.docker.com/) and Node 18+.

```bash
docker compose up -d postgres api
docker compose run --rm api alembic upgrade head
```

Create the first account. There is no default password — choose your own:

```bash
docker compose run --rm \
  -e ADMIN_EMAIL="you@example.com" \
  -e ADMIN_PASSWORD="choose-a-password" \
  api python -m app.create_admin
```

Start the takeoff engine, from `api/`:

```bash
uvicorn estimate_service:app --port 8100
```

Then the client:

```bash
npm run dev
```

Sign in, create a project, upload a drawing set, and process it.
````

Also remove the "Try the multi-user behavior" claim that it works without a backend, and update "Known limitations" — `localStorage`/`BroadcastChannel` sync is gone; polling against the real API is what remains.

- [ ] **Step 4: Update CLAUDE.md**

- Architecture block: `lib/data.js` becomes `lib/vocabulary.js` (status vocabulary only); the `store/` line drops "seed (localStorage) and api (fetch) behind it" in favour of the single api store.
- "Sync is single-machine (`BroadcastChannel` + `localStorage`)" under open decisions: replace with the real state — polling against the API, with the undo model still open.
- "Known scope limits": remove the claim that there is no document ingestion.

- [ ] **Step 5: Update ROADMAP.md**

In "What the prototype maps to", delete the rows for `localStorage`/`seed.js`, `BroadcastChannel`, and `ITEMS` seed array — those mappings are now done rather than pending. Note in "Where we are" that the client runs against the real API only.

- [ ] **Step 6: Verify**

Run: `npm test && npm run build && cd api && pytest -q`
Expected: PASS

Then confirm nothing references a deleted path:

```bash
grep -rn "build:demo\|demo/index.html\|singlefile\|deploy.yml" README.md CLAUDE.md ROADMAP.md package.json
```
Expected: no hits.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Remove the demo build and Pages deploy, and document the real run path"
```

---

## Manual verification

CI cannot cover the full loop — it needs Postgres, the API, the engine, and a real PDF. Run it once by hand after Task 11:

1. `docker compose up -d postgres api` and `alembic upgrade head`
2. `python -m app.create_admin` with your own credentials
3. `uvicorn estimate_service:app --port 8100` from `api/`
4. `npm run dev`, sign in, create a project, upload a drawing set, process
5. Confirm: markers land on the plan geometry, the spreadsheet shows cost columns, an attention item carries a four-field warning, and the drawer totals are non-zero
6. Process the same project again after approving one item — confirm the replace confirmation appears and names the count, that declining leaves the takeoff intact, and that confirming replaces it
