# The pricing grid — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Labor and Material pricing tables with one shared, keyboard-navigable editable grid that edits in place, clears an entry back to the next source, sums a pinned footer, and reports saves and undo the way every other workspace does.

**Architecture:** A new `DataGrid` component (`src/components/grid/`) owns cell navigation, in-place editors, per-cell validation, and the Clear affordance; it holds no data and reports `onCommit(row, key, value)` (value `null` = clear). The two screens become column definitions plus a commit function that routes through `useReviewStore`'s existing `runMutation`/`showToast`. The API's two pricing PATCH routes start returning the resolved row, and one new `DELETE` clears a material override, so the screens patch a single row from the response instead of refetching.

**Tech Stack:** React 18 function components, plain CSS tokens in `src/styles.css`, `lucide-react` for the one icon, vitest + testing-library on the client; FastAPI + SQLAlchemy + pytest on the API.

Spec: [`docs/specs/pricing-grid.md`](../specs/pricing-grid.md). Read it before starting; every task below cites the section it implements.

## Global constraints

Copied from the spec and `CLAUDE.md`; every task inherits them.

- Status renders only through the existing `Pill` component; source tiers only through `<span className="pill pill--neutral">`. No new colour for any state. Selection is a ring, never a fill.
- Plain CSS, tokens only (`--blue`, `--ink-2`, `--ink-3`, `--line-2`, `--surface`, `--red`, `--r-sm`). No inline hex, no new dependency.
- Sentence case for every string. No exclamation marks, no "successfully", no "please".
- No save button. Save state is the top bar's `Saving…` / `Saved <time>` / `Couldn't save — retrying`. Every write shows a five-second toast with Undo.
- Tabular numerals (`className="tabular"`) on every numeric cell.
- Number editors are `<input type="text" inputmode="decimal">`, never `type="number"`.
- Clearing a cell to empty is a commit of `null` when the column's `edit.hasEntry(row)` is true, and sends nothing otherwise.
- Every API mutation goes through `actions.commit()`. Kinds stay `labor_edit` and `material_price_edit` — no new kind.
- `npm run build` passes before every commit that touches `src/`.

## How to run things

Frontend tests, from the repo root:

```bash
npx vitest run src/components/grid
```

Backend tests need the compose Postgres up (`docker compose up -d postgres` from the repo root if it is not). Run from `api/`, with a database name unique to this branch so a parallel session's test run cannot collide:

```bash
cd api && DATABASE_URL=postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff TEST_DATABASE_URL=postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test_grid ../../../../.enginevenv/bin/pytest -q tests/test_pricing_endpoints.py
```

(`.enginevenv` lives at the main checkout root, four levels up from `api/` in this worktree. If `../../../../.enginevenv/bin/pytest` does not exist, run `python3 -m venv ../../../../.enginevenv && ../../../../.enginevenv/bin/pip install -r requirements.txt` once from `api/`.)

Commit messages end with:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

## File map

| File | Responsibility |
|---|---|
| `api/app/takeoff/schemas.py` | `LaborRowOut` gains `adjustment_percent`, `adjustment_reason` |
| `api/app/takeoff/pricing_router.py` | `labor_row_for()` / `material_row_for()` single-item builders; PATCH routes return the row; new `DELETE /items/{id}/material-price` |
| `api/tests/test_pricing_endpoints.py` | backend tests for all of the above |
| `src/lib/store/api-mapping.js` | `mapLaborRow` carries the adjustment fields |
| `src/lib/store/api.js` | `setLaborLine` / `setMaterialPrice` return mapped rows; new `clearMaterialPrice` |
| `src/lib/format.js` | `saveStateText(saved)` moves here from `TakeoffSpreadsheet.jsx` |
| `src/lib/useReviewStore.js` | returns `runMutation` and `showToast` |
| `src/components/grid/useGridNavigation.js` | pure movement functions + the active-cell hook |
| `src/components/grid/DataGrid.jsx` | the grid: cells, editors, validation, Clear button, footer |
| `src/components/grid/DataGrid.test.jsx` | grid behaviour tests |
| `src/components/labor/laborColumns.js` | labor columns with `edit` descriptors |
| `src/components/labor/LaborWorkspace.jsx` | the screen on the grid |
| `src/components/pricing/pricingColumns.js` | material columns with `edit` descriptors, Basis + Reason + Line total |
| `src/components/pricing/MaterialPricingWorkspace.jsx` | the screen on the grid, allowance hold, clear |
| `src/styles.css` | `.grid*` rules |

---

### Task 1: The pricing PATCH routes return the resolved row; `LaborRowOut` carries the adjustment fields

Spec: "Labor → Backend changes", "Material pricing → Backend changes" (the PATCH half), "Testing → Backend".

**Files:**
- Modify: `api/app/takeoff/schemas.py:457-471` (`LaborRowOut`)
- Modify: `api/app/takeoff/pricing_router.py` (imports at top; `patch_labor` ~line 86; `patch_material_price` ~line 130; `get_labor` ~line 163; `get_material_pricing` ~line 198)
- Test: `api/tests/test_pricing_endpoints.py`

**Interfaces:**
- Produces: `labor_row_for(item, project, db, user) -> LaborRowOut` and `material_row_for(item, project, db, user) -> MaterialRowOut` in `pricing_router.py`; both PATCH routes return those. Task 2 reuses `material_row_for`. Task 3 reads `adjustment_percent` / `adjustment_reason` off the wire.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_pricing_endpoints.py`:

```python
# --- pricing-grid: the PATCH routes return the resolved row ---


def test_get_labor_returns_the_adjustment_fields(client, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/labor",
                 json={"adjustmentPercent": 25, "adjustmentReason": "Mounting height above 16 ft"})
    response = client.get(f"/api/projects/{item.project_id}/labor")
    row = next(r for r in response.json()["rows"] if r["item_id"] == str(item.id))
    assert float(row["adjustment_percent"]) == 25.0
    assert row["adjustment_reason"] == "Mounting height above 16 ft"


def test_get_labor_adjustment_fields_are_empty_with_no_line(client, item, signed_in_user):
    response = client.get(f"/api/projects/{item.project_id}/labor")
    row = next(r for r in response.json()["rows"] if r["item_id"] == str(item.id))
    assert row["adjustment_percent"] is None
    assert row["adjustment_reason"] == ""


def test_patch_labor_returns_the_resolved_row(client, item, signed_in_user):
    """The grid patches one row from the response instead of refetching
    the list, so the PATCH body has to be the same row the list would
    return after the write."""
    response = client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["item_id"] == str(item.id)
    assert float(body["hours_per_unit"]) == 0.75
    assert body["hours_source_label"] == "Estimator entered"
    listed = next(r for r in client.get(f"/api/projects/{item.project_id}/labor").json()["rows"]
                  if r["item_id"] == str(item.id))
    assert listed == body


def test_patch_material_price_returns_the_resolved_row(client, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/material-price",
                            json={"priceOverride": 15.5, "source": "project_price"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["item_id"] == str(item.id)
    assert float(body["unit_price"]) == 15.5
    assert body["source"] == "project_price"
    assert body["source_label"] == "Project price"
    listed = next(r for r in client.get(f"/api/projects/{item.project_id}/material-pricing").json()["rows"]
                  if r["item_id"] == str(item.id))
    assert listed == body
```

- [ ] **Step 2: Run them to verify they fail**

Run (from `api/`, with the env vars from "How to run things"):
```bash
../../../../.enginevenv/bin/pytest -q tests/test_pricing_endpoints.py -k "adjustment_fields or returns_the_resolved_row"
```
Expected: 4 failed — `KeyError: 'adjustment_percent'` and `KeyError: 'item_id'` (the PATCH bodies are `{"itemId": ...}` today).

- [ ] **Step 3: Extend `LaborRowOut`**

In `api/app/takeoff/schemas.py`, replace the `LaborRowOut` class body:

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
    # The per-row adjustment the estimator typed (labor-material-pricing
    # spec, "Final labor hours and cost"). Stored since that plan, returned
    # since the pricing grid -- the grid edits them as cells.
    adjustment_percent: Decimal | None = None
    adjustment_reason: str = ""
    status: str
    basis_note: str = ""

    model_config = MODEL_CONFIG
```

- [ ] **Step 4: Add the single-row builders and use them from the list routes**

In `api/app/takeoff/pricing_router.py`, add to the imports:

```python
from app.takeoff.models import Project
```

(keep the existing `from app.takeoff.models import (...)` block; add `Project` to it rather than a second import line — the block is alphabetical, so it goes between `CompanyMaterialPrice` and `ProjectLaborLine`).

Add these two builders directly above `def get_labor(` (they replace the row-construction inside both list loops):

```python
def _labor_row_out(item, resolution, line) -> LaborRowOut:
    """One place a labor row is shaped, for the list route and the PATCH
    route both -- the grid patches a single row from the PATCH response,
    so the two must never drift."""
    return LaborRowOut(
        item_id=item.id, item_name=item.name, quantity=item.quantity,
        hours_per_unit=resolution.hours_per_unit, hours_source_label=resolution.hours_source_label,
        rate=resolution.rate, rate_source_label=resolution.rate_source_label,
        adjusted_hours=resolution.adjusted_hours, labor_cost=resolution.labor_cost,
        adjustment_percent=line.adjustment_percent if line is not None else None,
        adjustment_reason=line.adjustment_reason if line is not None else "",
        status=resolution.status, basis_note=resolution.basis_note,
    )


def labor_row_for(item, project, db: DbSession, user: User) -> LaborRowOut:
    """The resolved labor row for one item, read fresh after a write."""
    line = db.get(ProjectLaborLine, item.id)
    company_rates = db.get(CompanyLaborRate, user.org_id)
    company_hours = db.scalars(
        select(CompanyLaborHoursOverride).where(
            CompanyLaborHoursOverride.org_id == user.org_id,
            CompanyLaborHoursOverride.item_name == item.name,
        )
    ).one_or_none()
    resolution = resolve_labor(item, project, line, company_rates=company_rates, company_hours=company_hours)
    return _labor_row_out(item, resolution, line)


def _material_row_out(item, resolution, override) -> MaterialRowOut:
    return MaterialRowOut(
        item_id=item.id, item_name=item.name, quantity=item.quantity,
        unit_price=resolution.unit_price,
        source=override.source if override is not None else None,
        source_label=resolution.source_label,
        reason=override.reason if override is not None else "",
        status=resolution.status, basis_note=resolution.basis_note,
    )


def material_row_for(item, project, db: DbSession, user: User) -> MaterialRowOut:
    """The resolved material row for one item, read fresh after a write."""
    override = db.get(ProjectMaterialPrice, item.id)
    company_price = db.scalars(
        select(CompanyMaterialPrice).where(
            CompanyMaterialPrice.org_id == user.org_id,
            CompanyMaterialPrice.item_name == item.name,
        )
    ).one_or_none()
    resolution = resolve_material_price(item, project, override, company_price)
    return _material_row_out(item, resolution, override)
```

In `get_labor`, replace the `rows.append(LaborRowOut(...))` call (the whole multi-line constructor) with:

```python
        rows.append(_labor_row_out(item, resolution, lines.get(item.id)))
```

In `get_material_pricing`, replace the `rows.append(MaterialRowOut(...))` call with:

```python
        rows.append(_material_row_out(item, resolution, override))
```

- [ ] **Step 5: Return the row from both PATCH routes**

In `patch_labor`, replace the last two lines (`db.commit()` / `return {"itemId": str(item_id)}`) with:

```python
    db.commit()
    project = db.get(Project, item.project_id)
    return labor_row_for(item, project, db, user)
```

and change the decorator to declare the response model:

```python
@router.patch("/items/{item_id}/labor", response_model=LaborRowOut)
```

In `patch_material_price`, do the same:

```python
    db.commit()
    project = db.get(Project, item.project_id)
    return material_row_for(item, project, db, user)
```

```python
@router.patch("/items/{item_id}/material-price", response_model=MaterialRowOut)
```

- [ ] **Step 6: Run the pricing and undo suites**

```bash
../../../../.enginevenv/bin/pytest -q tests/test_pricing_endpoints.py tests/test_undo_redo.py
```
Expected: all pass. (Two existing tests read `response.json()["itemId"]`? Search first: `grep -n itemId tests/test_pricing_endpoints.py tests/test_undo_redo.py`. If any assert on `itemId`, change them to `item_id` — the spec replaces that body.)

- [ ] **Step 7: Commit**

```bash
git add api/app/takeoff/schemas.py api/app/takeoff/pricing_router.py api/tests/test_pricing_endpoints.py
git commit -m "Pricing PATCH routes return the resolved row; labor rows carry the adjustment

The grid patches one row from the response instead of refetching the
list, so the PATCH body is now the same row the list route returns.
adjustment_percent and adjustment_reason were stored and never
returned; the grid edits them as cells.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Clearing on the API — labor null is tested, material gets `DELETE`

Spec: "Clearing an entry", "Labor → Clearing", "Material pricing → Clearing / Backend changes" (the DELETE half), "Testing → Backend".

**Files:**
- Modify: `api/app/takeoff/pricing_router.py` (new route after `patch_material_price`)
- Test: `api/tests/test_pricing_endpoints.py`

**Interfaces:**
- Consumes: `material_row_for()` from Task 1.
- Produces: `DELETE /api/items/{item_id}/material-price -> MaterialRowOut`, `404` code `no_material_price_to_clear`. Task 3's `clearMaterialPrice` calls it.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_pricing_endpoints.py`:

```python
# --- pricing-grid: clearing an entry ---


def test_patch_labor_with_null_hours_clears_the_override(client, db, item, signed_in_user):
    """An explicit null is 'go back to whatever is next' -- with no company
    standard and no engine baseline, that is Missing information, which is
    the honest state for 'I don't want a number here'."""
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    response = client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": None})
    assert response.status_code == 200, response.text
    assert db.get(ProjectLaborLine, item.id).hours_override is None
    body = response.json()
    assert body["hours_per_unit"] is None
    assert body["hours_source_label"] is None
    assert body["status"] == "missing"


def test_clearing_hours_falls_back_to_the_company_standard(client, db, org, item, signed_in_user):
    from decimal import Decimal

    from app.takeoff.models import CompanyLaborHoursOverride

    db.add(CompanyLaborHoursOverride(org_id=org.id, item_name=item.name, hours_per_unit=Decimal("0.4")))
    db.commit()
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    body = client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": None}).json()
    assert body["hours_source_label"] == "Company standard"
    assert float(body["hours_per_unit"]) == 0.4


def test_clearing_hours_records_null_in_after_and_undo_restores_it(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": None})
    latest = db.scalars(
        select(Action).where(Action.kind == "labor_edit", Action.item_id == item.id).order_by(Action.seq.desc())
    ).first()
    assert latest.after["hours_override"] is None
    client.post(f"/api/projects/{item.project_id}/undo")
    db.expire_all()
    assert float(db.get(ProjectLaborLine, item.id).hours_override) == 0.75


def test_delete_material_price_removes_the_override_and_returns_the_row(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/material-price",
                 json={"priceOverride": 15.5, "source": "allowance", "reason": "no vendor quote yet"})
    response = client.delete(f"/api/items/{item.id}/material-price")
    assert response.status_code == 200, response.text
    assert db.get(ProjectMaterialPrice, item.id) is None
    body = response.json()
    assert body["item_id"] == str(item.id)
    assert body["unit_price"] is None
    assert body["source"] is None
    assert body["reason"] == ""
    assert body["status"] == "missing"


def test_delete_material_price_is_recorded_with_an_empty_after(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/material-price", json={"priceOverride": 15.5, "source": "project_price"})
    client.delete(f"/api/items/{item.id}/material-price")
    latest = db.scalars(
        select(Action).where(Action.kind == "material_price_edit", Action.item_id == item.id).order_by(Action.seq.desc())
    ).first()
    assert latest.after == {}
    assert float(latest.before["price_override"]) == 15.5
    assert latest.label == "Cleared material price for 20A duplex receptacle"


def test_delete_material_price_404s_when_there_is_nothing_to_clear(client, item, signed_in_user):
    response = client.delete(f"/api/items/{item.id}/material-price")
    assert response.status_code == 404
    assert response.json()["code"] == "no_material_price_to_clear"


def test_undo_restores_a_cleared_material_price(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/material-price",
                 json={"priceOverride": 15.5, "source": "allowance", "reason": "no vendor quote yet"})
    client.delete(f"/api/items/{item.id}/material-price")
    client.post(f"/api/projects/{item.project_id}/undo")
    db.expire_all()
    row = db.get(ProjectMaterialPrice, item.id)
    assert row is not None
    assert float(row.price_override) == 15.5 and row.source == "allowance" and row.reason == "no vendor quote yet"
```

`Action` and `select` are already imported at the top of this file.

- [ ] **Step 2: Run them to verify they fail**

```bash
../../../../.enginevenv/bin/pytest -q tests/test_pricing_endpoints.py -k "clears_the_override or falls_back or records_null or delete_material_price or restores_a_cleared"
```
Expected: the three labor tests may already pass (the null path exists); the four `delete_material_price` / `restores_a_cleared` tests fail with `405 Method Not Allowed`. If any labor test fails, read the failure — it is a real defect in the null path and the fix belongs in `patch_labor`.

If the `404` test's `response.json()["code"]` assertion fails on the key name, check how `DomainError` is serialised: `grep -n "code" api/app/errors.py api/app/main.py | head` and match the test to the real key.

- [ ] **Step 3: Add the route**

In `api/app/takeoff/pricing_router.py`, directly after `patch_material_price`:

```python
@router.delete("/items/{item_id}/material-price", response_model=MaterialRowOut)
def delete_material_price(
    item_id: uuid.UUID,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Clear the estimator's price entry so the row falls back to the
    company price, the regional baseline, or Missing information.

    Returns the fallen-back row rather than 204: the grid renders it and
    words the toast from its new source label. Recorded as
    material_price_edit with an empty `after` -- undo_apply's
    _apply_sparse_pricing_row already reads an empty state as "this row
    should not exist", so undo and redo of a clear need nothing new."""
    item = load_item(item_id, db, user)
    row = db.get(ProjectMaterialPrice, item_id)
    if row is None:
        raise DomainError("no_material_price_to_clear", "This item has no price entry to clear.", status=404)
    before = _snapshot(ProjectMaterialPrice, item_id, db)
    db.delete(row)
    db.flush()
    actions.commit(
        db, actor=user, project_id=item.project_id, kind="material_price_edit",
        label=f"Cleared material price for {item.name}", item_id=item_id,
        before=before, after={},
    )
    db.commit()
    project = db.get(Project, item.project_id)
    return material_row_for(item, project, db, user)
```

- [ ] **Step 4: Run the suites**

```bash
../../../../.enginevenv/bin/pytest -q tests/test_pricing_endpoints.py tests/test_undo_redo.py
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/pricing_router.py api/tests/test_pricing_endpoints.py
git commit -m "Clear a material price with DELETE; test that a null labor field clears

Both land in the action log under the existing kinds with the row's
snapshot as before and an empty after, which is the shape undo already
reverses.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The store returns rows from writes and can clear a material price

Spec: "Labor → Backend changes" (`mapLaborRow`), "Saving → Commit flow" step 4.

**Files:**
- Modify: `src/lib/store/api-mapping.js:213-227` (`mapLaborRow`)
- Modify: `src/lib/store/api.js:488-508` (`setLaborLine`, `setMaterialPrice`) and the returned object (~line 575)
- Test: `src/lib/store/api-mapping.test.js`, `src/lib/store/api.test.js` (create if it does not exist; check with `ls src/lib/store/*.test.js`)

**Interfaces:**
- Produces: `store.setLaborLine(itemId, changes) -> Promise<LaborRow>`, `store.setMaterialPrice(itemId, changes) -> Promise<MaterialRow>`, `store.clearMaterialPrice(itemId) -> Promise<MaterialRow>`. `LaborRow` gains `adjustmentPercent: number | null` and `adjustmentReason: string`. Tasks 7 and 8 consume all three.

- [ ] **Step 1: Write the failing mapping test**

In `src/lib/store/api-mapping.test.js`, inside `describe("mapLaborRow", ...)`, add:

```js
  test("carries the adjustment percent and reason, and defaults them when absent", () => {
    const withAdjustment = mapLaborRow({
      item_id: "abc", item_name: "x", quantity: "1", hours_per_unit: null, hours_source_label: null,
      rate: null, rate_source_label: null, adjusted_hours: null, labor_cost: null, status: "missing",
      basis_note: "", adjustment_percent: "25.00", adjustment_reason: "Mounting height above 16 ft",
    });
    expect(withAdjustment.adjustmentPercent).toBe(25);
    expect(withAdjustment.adjustmentReason).toBe("Mounting height above 16 ft");

    const without = mapLaborRow({
      item_id: "abc", item_name: "x", quantity: "1", hours_per_unit: null, hours_source_label: null,
      rate: null, rate_source_label: null, adjusted_hours: null, labor_cost: null, status: "missing", basis_note: "",
    });
    expect(without.adjustmentPercent).toBeNull();
    expect(without.adjustmentReason).toBe("");
  });
```

- [ ] **Step 2: Run it to verify it fails**

```bash
npx vitest run src/lib/store/api-mapping.test.js
```
Expected: 1 failed — `expected undefined to be 25`.

- [ ] **Step 3: Extend `mapLaborRow`**

In `src/lib/store/api-mapping.js`, add two fields to the object `mapLaborRow` returns, after `laborCost`:

```js
    adjustmentPercent: r.adjustment_percent == null ? null : Number(r.adjustment_percent),
    adjustmentReason: r.adjustment_reason ?? "",
```

- [ ] **Step 4: Write the failing store tests**

Check whether `src/lib/store/api.test.js` exists and how it stubs `fetch` (`grep -n "fetch" src/lib/store/api.test.js | head`). If it exists, add the three tests below inside its top-level `describe` using its existing fetch stub; if it does not, create the file:

```js
/* ============================================================
   api.test.js — the store's write methods for the pricing grid. fetch
   is stubbed per test; the assertion is on what crosses the wire and
   what comes back mapped.
   ============================================================ */

import { afterEach, describe, expect, test, vi } from "vitest";
import { createApiStore } from "./api.js";

const laborWire = {
  item_id: "i1", item_name: "20A duplex receptacle", quantity: "10", hours_per_unit: "0.75",
  hours_source_label: "Estimator entered", rate: null, rate_source_label: null, adjusted_hours: null,
  labor_cost: null, adjustment_percent: null, adjustment_reason: "", status: "missing", basis_note: "",
};
const materialWire = {
  item_id: "i1", item_name: "20A duplex receptacle", quantity: "10", unit_price: null, source: null,
  source_label: null, reason: "", status: "missing", basis_note: "",
};

function stubFetch(body) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, status: 200, text: async () => JSON.stringify(body), json: async () => body, headers: new Headers(),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("pricing writes", () => {
  test("setLaborLine sends the change and returns the mapped row", async () => {
    const fetchMock = stubFetch(laborWire);
    const store = createApiStore();
    const row = await store.setLaborLine("i1", { hoursOverride: 0.75 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/items/i1/labor");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ hoursOverride: 0.75 });
    expect(row.hoursPerUnit).toBe(0.75);
    expect(row.hoursSourceLabel).toBe("Estimator entered");
  });

  test("setMaterialPrice returns the mapped row", async () => {
    stubFetch({ ...materialWire, unit_price: "15.50", source: "project_price", source_label: "Project price", status: "approved" });
    const store = createApiStore();
    const row = await store.setMaterialPrice("i1", { priceOverride: 15.5, source: "project_price", reason: "" });
    expect(row.unitPrice).toBe(15.5);
    expect(row.sourceLabel).toBe("Project price");
  });

  test("clearMaterialPrice sends DELETE and returns the fallen-back row", async () => {
    const fetchMock = stubFetch(materialWire);
    const store = createApiStore();
    const row = await store.clearMaterialPrice("i1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/items/i1/material-price");
    expect(init.method).toBe("DELETE");
    expect(row.unitPrice).toBeNull();
    expect(row.status).toBe("missing");
  });
});
```

If `createApiStore` is not the exported factory's name, check `grep -n "^export" src/lib/store/api.js` and use the real one. If the store's `request()` also reads headers you did not stub (e.g. an ETag), extend the stub object rather than the store.

- [ ] **Step 5: Run to verify they fail**

```bash
npx vitest run src/lib/store/api.test.js
```
Expected: 3 failed — the first two on `row.hoursPerUnit` / `row.unitPrice` being undefined (the raw wire object comes back), the third on `store.clearMaterialPrice is not a function`.

- [ ] **Step 6: Implement**

In `src/lib/store/api.js`, replace `setLaborLine` and `setMaterialPrice` and add `clearMaterialPrice`:

```js
  async function setLaborLine(itemId, changes) {
    // A labor edit changes the item's laborCost/totalCost, both of
    // which mapItem carries and getSnapshot()'s cache can serve stale
    // via a 304 -- invalidate exactly like mutateItem/startTakeoff do,
    // per invalidateCache()'s own comment above.
    const result = await request(`/api/items/${itemId}/labor`, { method: "PATCH", body: changes });
    invalidateCache();
    // The route returns the resolved row (pricing-grid spec), so the
    // screen replaces one row from this rather than refetching the list.
    return mapLaborRow(result);
  }

  async function setMaterialPrice(itemId, changes) {
    // Same reasoning as setLaborLine: a material-price edit changes the
    // item's materialCost/totalCost, so the cache must not answer the
    // next poll with the pre-edit figures.
    const result = await request(`/api/items/${itemId}/material-price`, { method: "PATCH", body: changes });
    invalidateCache();
    return mapMaterialRow(result);
  }

  async function clearMaterialPrice(itemId) {
    // Removes the estimator's price entry; the row comes back resolved
    // to whatever is next in the chain, which is what the toast names.
    const result = await request(`/api/items/${itemId}/material-price`, { method: "DELETE" });
    invalidateCache();
    return mapMaterialRow(result);
  }
```

Confirm `mapLaborRow` and `mapMaterialRow` are imported at the top of `api.js` (`grep -n "mapLaborRow" src/lib/store/api.js`); they are used by `getLaborRows` so they should be. Add `clearMaterialPrice,` to the returned object next to `setMaterialPrice,`.

- [ ] **Step 7: Run the store tests and the two workspace suites**

```bash
npx vitest run src/lib/store src/components/labor src/components/pricing
```
Expected: all pass. The existing workspace tests mock `setLaborLine`/`setMaterialPrice` with `mockResolvedValue({})` and then refetch, so they are unaffected until Tasks 7–8.

- [ ] **Step 8: Commit**

```bash
git add src/lib/store/api-mapping.js src/lib/store/api-mapping.test.js src/lib/store/api.js src/lib/store/api.test.js
git commit -m "Store: pricing writes return the mapped row; clearMaterialPrice

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `useReviewStore` exposes `runMutation` and `showToast`; `saveStateText` moves to `lib/format.js`

Spec: "Saving → Save state and undo".

**Files:**
- Modify: `src/lib/useReviewStore.js` (the returned object, ~line 250)
- Modify: `src/lib/format.js` (append `saveStateText`)
- Modify: `src/components/takeoff/TakeoffSpreadsheet.jsx:39-51` (delete the local `saveStateText`, import it)
- Test: `src/lib/format.test.js` (create if absent — check `ls src/lib/*.test.js`), `src/lib/useReviewStore.test.js` (exists? check; if not, the return-shape test goes in a new file)

**Interfaces:**
- Produces: `saveStateText(saved) -> string | null` from `lib/format.js`; `runMutation(fn) -> Promise` and `showToast(text)` on the `useReviewStore` return value, therefore on the workspace context. Tasks 7 and 8 consume both.

- [ ] **Step 1: Write the failing format test**

Create or append to `src/lib/format.test.js`:

```js
import { describe, expect, test } from "vitest";
import { saveStateText, timeOf } from "./format.js";

describe("saveStateText", () => {
  test("names the three autosave states and nothing for no state", () => {
    const at = Date.parse("2026-08-25T15:00:00Z");
    expect(saveStateText({ state: "saving", at })).toBe("Saving…");
    expect(saveStateText({ state: "error", at })).toBe("Couldn't save — retrying");
    expect(saveStateText({ state: "saved", at })).toBe("Saved " + timeOf(at));
    expect(saveStateText(null)).toBeNull();
  });
});
```

(If the file already exists, add only the `saveStateText` import and the `describe` block.)

- [ ] **Step 2: Run it to verify it fails**

```bash
npx vitest run src/lib/format.test.js
```
Expected: fails — `saveStateText is not a function` / not exported.

- [ ] **Step 3: Move `saveStateText`**

Append to `src/lib/format.js`:

```js
/** The three-state autosave copy every workspace top bar shows
 *  (DESIGN.md, "Autosave and save status"): Saving… while a write is
 *  in flight, Saved <time> once it lands, and the retrying copy on a
 *  technical failure. One copy here, read by the takeoff table and
 *  both pricing screens -- the blueprint's TopBar.jsx renders the same
 *  states from the same `saved` object. */
export function saveStateText(saved) {
  if (!saved) return null;
  if (saved.state === "saving") return "Saving…";
  if (saved.state === "error") return "Couldn't save — retrying";
  return "Saved " + timeOf(saved.at);
}
```

In `src/components/takeoff/TakeoffSpreadsheet.jsx`, delete the local `function saveStateText(saved) {...}` and its comment block (lines ~39–51), and change the format import to:

```js
import { saveStateText, timeOf } from "../../lib/format.js";
```

If `timeOf` is no longer used anywhere else in that file after the deletion (`grep -n "timeOf" src/components/takeoff/TakeoffSpreadsheet.jsx`), import only `saveStateText`.

- [ ] **Step 4: Expose `runMutation` and `showToast`**

In `src/lib/useReviewStore.js`, in the returned object, add after `dismissToast,`:

```js
    // For screens whose rows live outside the polled snapshot (labor,
    // material pricing): the same Saving…/Saved tracker and the same
    // five-second toast every item mutation above uses, so those
    // screens report a save the way this one does rather than growing
    // a second copy of either.
    runMutation,
    showToast,
```

- [ ] **Step 5: Write the return-shape test**

If `src/lib/useReviewStore.test.js` exists, add a test inside it following its render pattern; otherwise create:

```js
import { describe, expect, test, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useReviewStore } from "./useReviewStore.js";

describe("useReviewStore", () => {
  test("exposes runMutation and showToast for screens outside the snapshot", () => {
    const store = {
      getSnapshot: vi.fn().mockResolvedValue(null),
      subscribe: vi.fn(() => () => {}),
    };
    const { result } = renderHook(() => useReviewStore(store, { onSignedOut: () => {} }));
    expect(typeof result.current.runMutation).toBe("function");
    expect(typeof result.current.showToast).toBe("function");
  });
});
```

Check the hook's real export name and the store methods it calls on mount (`grep -n "store\.\w*(" src/lib/useReviewStore.js | head`) and stub those on the fake store so the hook mounts cleanly.

- [ ] **Step 6: Run everything that touches these files**

```bash
npx vitest run src/lib src/components/takeoff
```
Expected: all pass, including `TakeoffSpreadsheet.saveState.test.jsx`.

- [ ] **Step 7: Build and commit**

```bash
npm run build
git add src/lib/format.js src/lib/format.test.js src/lib/useReviewStore.js src/lib/useReviewStore.test.js src/components/takeoff/TakeoffSpreadsheet.jsx
git commit -m "Share saveStateText and expose runMutation/showToast from the review store

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `useGridNavigation` — the movement rules, pure and tested

Spec: "Cell states → Active" (the key table and "only editable cells participate").

**Files:**
- Create: `src/components/grid/useGridNavigation.js`
- Test: `src/components/grid/useGridNavigation.test.js`

**Interfaces:**
- Produces: `isEditable(column, row) -> boolean`, `firstEditable(columns, rows) -> {row, col} | null`, `moveActive(active, direction, columns, rows) -> {row, col} | null`, and `useGridNavigation(columns, rows) -> { active, setActive, move }`. Task 6's `DataGrid` consumes all four. `active` is `{ row: number, col: string }` — a row index and a column key. `direction` is one of `"left" | "right" | "up" | "down" | "next" | "prev" | "home" | "end"`.

- [ ] **Step 1: Write the failing tests**

Create `src/components/grid/useGridNavigation.test.js`:

```js
/* ============================================================
   useGridNavigation.test.js — the movement rules, on plain data.
   Column keys: name (row header, read-only), qty (read-only),
   hours / note / basis (editable; basis disabled on row 2).
   ============================================================ */

import { describe, expect, test } from "vitest";
import { firstEditable, isEditable, moveActive } from "./useGridNavigation.js";

const columns = [
  { key: "name", label: "Item", header: true, render: (r) => r.name },
  { key: "qty", label: "Quantity", render: (r) => r.qty },
  { key: "hours", label: "Hours", render: (r) => r.hours, edit: { kind: "number", value: (r) => r.hours } },
  { key: "note", label: "Note", render: (r) => r.note, edit: { kind: "text", value: (r) => r.note } },
  {
    key: "basis", label: "Basis", render: (r) => r.basis,
    edit: { kind: "select", value: (r) => r.basis, options: [], disabled: (r) => r.locked },
  },
];
const rows = [
  { name: "One", qty: 1, hours: 0.5, note: "", basis: "a" },
  { name: "Two", qty: 2, hours: null, note: "x", basis: "b", locked: true },
  { name: "Three", qty: 3, hours: 1, note: "", basis: "a" },
];

describe("isEditable", () => {
  test("needs an edit descriptor and not to be disabled on the row", () => {
    expect(isEditable(columns[1], rows[0])).toBe(false);
    expect(isEditable(columns[2], rows[0])).toBe(true);
    expect(isEditable(columns[4], rows[0])).toBe(true);
    expect(isEditable(columns[4], rows[1])).toBe(false);
  });
});

describe("firstEditable", () => {
  test("is the first editable cell of the first row that has one", () => {
    expect(firstEditable(columns, rows)).toEqual({ row: 0, col: "hours" });
    expect(firstEditable(columns, [])).toBeNull();
    expect(firstEditable([columns[0], columns[1]], rows)).toBeNull();
  });
});

describe("moveActive", () => {
  test("left and right step within the row over editable cells only, and stop at the edges", () => {
    expect(moveActive({ row: 0, col: "hours" }, "right", columns, rows)).toEqual({ row: 0, col: "note" });
    expect(moveActive({ row: 0, col: "note" }, "right", columns, rows)).toEqual({ row: 0, col: "basis" });
    expect(moveActive({ row: 0, col: "basis" }, "right", columns, rows)).toEqual({ row: 0, col: "basis" });
    expect(moveActive({ row: 0, col: "hours" }, "left", columns, rows)).toEqual({ row: 0, col: "hours" });
    // Row 2's basis is disabled, so right from note stays on note.
    expect(moveActive({ row: 1, col: "note" }, "right", columns, rows)).toEqual({ row: 1, col: "note" });
  });

  test("up and down stay in the column and skip rows where it is not editable", () => {
    expect(moveActive({ row: 0, col: "hours" }, "down", columns, rows)).toEqual({ row: 1, col: "hours" });
    expect(moveActive({ row: 0, col: "basis" }, "down", columns, rows)).toEqual({ row: 2, col: "basis" });
    expect(moveActive({ row: 2, col: "basis" }, "up", columns, rows)).toEqual({ row: 0, col: "basis" });
    expect(moveActive({ row: 0, col: "hours" }, "up", columns, rows)).toEqual({ row: 0, col: "hours" });
    expect(moveActive({ row: 2, col: "hours" }, "down", columns, rows)).toEqual({ row: 2, col: "hours" });
  });

  test("next and prev wrap between rows and return null past either end of the grid", () => {
    expect(moveActive({ row: 0, col: "basis" }, "next", columns, rows)).toEqual({ row: 1, col: "hours" });
    expect(moveActive({ row: 1, col: "hours" }, "prev", columns, rows)).toEqual({ row: 0, col: "basis" });
    expect(moveActive({ row: 2, col: "basis" }, "next", columns, rows)).toBeNull();
    expect(moveActive({ row: 0, col: "hours" }, "prev", columns, rows)).toBeNull();
  });

  test("home and end go to the row's first and last editable cell", () => {
    expect(moveActive({ row: 1, col: "note" }, "home", columns, rows)).toEqual({ row: 1, col: "hours" });
    expect(moveActive({ row: 1, col: "hours" }, "end", columns, rows)).toEqual({ row: 1, col: "note" });
  });

  test("a null active cell moves nowhere", () => {
    expect(moveActive(null, "right", columns, rows)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
npx vitest run src/components/grid/useGridNavigation.test.js
```
Expected: fails to import — module not found.

- [ ] **Step 3: Implement**

Create `src/components/grid/useGridNavigation.js`:

```js
/* ============================================================
   useGridNavigation.js — which cell is active in a DataGrid, and where
   it goes on each key (docs/specs/pricing-grid.md, "Cell states →
   Active").

   The movement rules are pure functions over (columns, rows) so they
   are tested on plain data; the hook underneath is thin. An active
   cell is { row: index, col: column key }. Only editable cells
   participate -- a column with no `edit`, or whose `edit.disabled(row)`
   is true for this row, is stepped over in every direction. That is
   what makes Tab walk hours → rate → adjustment → reason → next row's
   hours on the labor screen rather than stopping on Status and
   Quantity.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";

export function isEditable(column, row) {
  return Boolean(column.edit) && !(column.edit.disabled && column.edit.disabled(row));
}

function editableKeys(columns, row) {
  return columns.filter((c) => isEditable(c, row)).map((c) => c.key);
}

export function firstEditable(columns, rows) {
  for (let r = 0; r < rows.length; r += 1) {
    const keys = editableKeys(columns, rows[r]);
    if (keys.length) return { row: r, col: keys[0] };
  }
  return null;
}

/** The active cell after moving in `direction`. Returns null only for
 *  "next"/"prev" past the grid's last/first editable cell -- the one
 *  case focus should leave the grid, which is what an un-prevented Tab
 *  does. Every other dead end stays put. */
export function moveActive(active, direction, columns, rows) {
  if (!active) return null;
  const keys = editableKeys(columns, rows[active.row]);
  const i = keys.indexOf(active.col);
  switch (direction) {
    case "left":
      return i > 0 ? { row: active.row, col: keys[i - 1] } : active;
    case "right":
      return i < keys.length - 1 ? { row: active.row, col: keys[i + 1] } : active;
    case "home":
      return keys.length ? { row: active.row, col: keys[0] } : active;
    case "end":
      return keys.length ? { row: active.row, col: keys[keys.length - 1] } : active;
    case "up":
    case "down": {
      const step = direction === "up" ? -1 : 1;
      for (let r = active.row + step; r >= 0 && r < rows.length; r += step) {
        if (editableKeys(columns, rows[r]).includes(active.col)) return { row: r, col: active.col };
      }
      return active;
    }
    case "next": {
      if (i < keys.length - 1) return { row: active.row, col: keys[i + 1] };
      for (let r = active.row + 1; r < rows.length; r += 1) {
        const k = editableKeys(columns, rows[r]);
        if (k.length) return { row: r, col: k[0] };
      }
      return null;
    }
    case "prev": {
      if (i > 0) return { row: active.row, col: keys[i - 1] };
      for (let r = active.row - 1; r >= 0; r -= 1) {
        const k = editableKeys(columns, rows[r]);
        if (k.length) return { row: r, col: k[k.length - 1] };
      }
      return null;
    }
    default:
      return active;
  }
}

/** Active-cell state for a DataGrid. Starts on the first editable cell
 *  once rows exist (roving tabindex needs one tabbable cell), and moves
 *  back onto the grid if rows shrink under it. */
export function useGridNavigation(columns, rows) {
  const [active, setActive] = useState(null);

  useEffect(() => {
    if (!active || active.row >= rows.length) setActive(firstEditable(columns, rows));
  }, [active, columns, rows]);

  const move = useCallback((direction) => moveActive(active, direction, columns, rows), [active, columns, rows]);

  return { active, setActive, move };
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
npx vitest run src/components/grid/useGridNavigation.test.js
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/components/grid/useGridNavigation.js src/components/grid/useGridNavigation.test.js
git commit -m "Grid navigation: the active-cell movement rules, pure and tested

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `DataGrid` — cells, editors, validation, clearing, footer

Spec: "The grid" in full — "Files", "Column definitions", "Cell states" (all three), "Validation on the cell", "Clearing an entry", "Accessibility", and "Styling".

**Files:**
- Create: `src/components/grid/DataGrid.jsx`
- Modify: `src/styles.css` (append a `.grid` block after the `.takeoff-table` rules, ~line 1690)
- Test: `src/components/grid/DataGrid.test.jsx`

**Interfaces:**
- Consumes: `useGridNavigation`, `isEditable` from Task 5.
- Produces: `<DataGrid columns rows rowKey rowLabel onCommit onCancel footer caption ref />`.
  - `columns[]`: `{ key, label, align?: "left"|"right", header?: boolean, className?: (row) => string|undefined, render: (row) => node, edit?: { kind: "number"|"text"|"select", value: (row) => any, min?, minMessage?, options?: [{value,label}], disabled?: (row) => boolean, hasEntry?: (row) => boolean, required?: (row) => boolean, requiredMessage? } }`
  - `onCommit(row, key, value)` — `value` is a `number` for `number` cells, a `string` for `text`/`select`, or `null` for a clear. Called once per changed cell.
  - `onCancel(row, key)` — Escape closed an editor without committing.
  - `ref.current.openEditor(rowKeyValue, colKey, { message })` — makes that cell active and opens its editor, optionally with a validation message already showing.
  Tasks 7 and 8 consume all of it.

- [ ] **Step 1: Write the failing tests**

Create `src/components/grid/DataGrid.test.jsx`:

```jsx
/* ============================================================
   DataGrid.test.jsx — the grid's behaviour on plain data
   (docs/specs/pricing-grid.md, "Testing → DataGrid.test.jsx").

   Gridcells are located by position: the row header is a rowheader,
   not a gridcell, so each row exposes four gridcells in column order
   qty, hours, note, basis.
   ============================================================ */

import { createRef } from "react";
import { describe, expect, test, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import DataGrid from "./DataGrid.jsx";

const columns = [
  { key: "name", label: "Item", align: "left", header: true, render: (r) => r.name },
  { key: "qty", label: "Quantity", align: "right", render: (r) => r.qty },
  {
    key: "hours", label: "Hours", align: "right",
    render: (r) => (r.hours == null ? "—" : String(r.hours)),
    edit: { kind: "number", min: 0, minMessage: "Hours can't be negative", value: (r) => r.hours, hasEntry: (r) => r.entered },
  },
  {
    key: "note", label: "Note", align: "left",
    render: (r) => r.note || "—",
    edit: { kind: "text", value: (r) => r.note, required: (r) => r.mustNote, requiredMessage: "A note is needed" },
  },
  {
    key: "basis", label: "Basis", align: "left",
    render: (r) => r.basis,
    edit: {
      kind: "select", value: (r) => r.basis, disabled: (r) => r.locked,
      options: [{ value: "a", label: "A" }, { value: "b", label: "B" }],
    },
  },
];
const rows = [
  { id: "r1", name: "One", qty: 1, hours: 0.5, entered: true, note: "", basis: "a" },
  { id: "r2", name: "Two", qty: 2, hours: null, entered: false, note: "x", basis: "b", locked: true },
  { id: "r3", name: "Three", qty: 3, hours: 1, entered: true, note: "", mustNote: true, basis: "a" },
];

function setup(extra = {}) {
  const onCommit = vi.fn();
  const onCancel = vi.fn();
  const ref = createRef();
  render(
    <DataGrid
      ref={ref} columns={columns} rows={rows} rowKey={(r) => r.id} rowLabel={(r) => r.name}
      onCommit={onCommit} onCancel={onCancel} caption="Test grid" {...extra}
    />,
  );
  return { onCommit, onCancel, ref };
}

/** gridcell at (row index, column among qty/hours/note/basis). */
function cell(row, col) {
  const bodyRows = screen.getAllByRole("row").slice(1); // skip the header row
  return within(bodyRows[row]).getAllByRole("gridcell")[col];
}
const HOURS = 1, NOTE = 2, BASIS = 3;

describe("DataGrid markup", () => {
  test("is a grid with a caption, one tabbable cell, and it is the first editable one", () => {
    setup();
    expect(screen.getByRole("grid", { name: "Test grid" })).toBeInTheDocument();
    const tabbable = document.querySelectorAll('[role="gridcell"][tabindex="0"]');
    expect(tabbable).toHaveLength(1);
    expect(tabbable[0]).toBe(cell(0, HOURS));
    expect(cell(0, HOURS)).toHaveAttribute("aria-selected", "true");
  });

  test("marks editable cells and not read-only or disabled ones", () => {
    setup();
    expect(cell(0, HOURS)).toHaveAttribute("data-editable");
    expect(cell(0, 0)).not.toHaveAttribute("data-editable");
    expect(cell(1, BASIS)).not.toHaveAttribute("data-editable");
  });
});

describe("moving the active cell", () => {
  test("arrow keys move over editable cells only and focus follows", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowRight" });
    expect(cell(0, NOTE)).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(cell(0, NOTE));
    fireEvent.keyDown(cell(0, NOTE), { key: "ArrowDown" });
    expect(cell(1, NOTE)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(1, NOTE), { key: "ArrowRight" }); // row 2's basis is disabled
    expect(cell(1, NOTE)).toHaveAttribute("aria-selected", "true");
  });

  test("Tab wraps to the next row and Shift+Tab back", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "End" });
    expect(cell(0, BASIS)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(0, BASIS), { key: "Tab" });
    expect(cell(1, HOURS)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(1, HOURS), { key: "Tab", shiftKey: true });
    expect(cell(0, BASIS)).toHaveAttribute("aria-selected", "true");
  });

  test("clicking an editable cell makes it active; a second click opens the editor", () => {
    setup();
    fireEvent.click(cell(2, HOURS));
    expect(cell(2, HOURS)).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(cell(2, HOURS));
    expect(screen.getByRole("textbox", { name: "Hours, Three" })).toHaveValue("1");
  });
});

describe("editing", () => {
  test("a printable key opens the editor with that character; Enter commits and moves down", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "7" });
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    expect(input).toHaveValue("7");
    expect(input).toHaveAttribute("inputmode", "decimal");
    fireEvent.change(input, { target: { value: "7.5" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommit).toHaveBeenCalledWith(rows[0], "hours", 7.5);
    expect(cell(1, HOURS)).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(cell(1, HOURS));
  });

  test("Enter opens with the current value; Escape discards, stays, and reports the cancel", () => {
    const { onCommit, onCancel } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    expect(input).toHaveValue("0.5");
    fireEvent.change(input, { target: { value: "9" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledWith(rows[0], "hours");
    expect(document.activeElement).toBe(cell(0, HOURS));
  });

  test("Tab commits and moves right; an unchanged value commits nothing", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Tab" });
    expect(onCommit).not.toHaveBeenCalled();
    expect(cell(0, NOTE)).toHaveAttribute("aria-selected", "true");
  });

  test("blur commits", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, NOTE), { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Note, One" });
    fireEvent.change(input, { target: { value: "checked" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(rows[0], "note", "checked");
  });

  test("a select cell opens on Space and commits on change", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "End" });
    fireEvent.keyDown(cell(0, BASIS), { key: " " });
    const select = screen.getByRole("combobox", { name: "Basis, One" });
    fireEvent.change(select, { target: { value: "b" } });
    expect(onCommit).toHaveBeenCalledWith(rows[0], "basis", "b");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(cell(0, BASIS)).toHaveAttribute("aria-selected", "true");
  });
});

describe("validation", () => {
  test("a non-number keeps the editor open with a message and commits nothing", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "a" });
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", screen.getByRole("alert").id);
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("below the minimum shows the column's message", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "-" });
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "-1" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("Hours can't be negative");
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("emptying a required text cell is refused with its message", () => {
    const { onCommit } = setup();
    fireEvent.click(cell(2, NOTE));
    fireEvent.keyDown(cell(2, NOTE), { key: "Enter" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("A note is needed");
    expect(onCommit).not.toHaveBeenCalled();
  });
});

describe("clearing an entry", () => {
  test("emptying the editor on a cell with an entry commits null; without an entry commits nothing", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onCommit).toHaveBeenCalledWith(rows[0], "hours", null);
    onCommit.mockClear();
    fireEvent.click(cell(1, HOURS));
    fireEvent.keyDown(cell(1, HOURS), { key: "Enter" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("Delete on an active cell clears an entry and does nothing without one", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Delete" });
    expect(onCommit).toHaveBeenCalledWith(rows[0], "hours", null);
    onCommit.mockClear();
    fireEvent.click(cell(1, HOURS));
    fireEvent.keyDown(cell(1, HOURS), { key: "Backspace" });
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("the Clear button renders only on an active cell with an entry, and clears on click", () => {
    const { onCommit } = setup();
    const clear = within(cell(0, HOURS)).getByRole("button", { name: "Clear entry" });
    fireEvent.click(clear);
    expect(onCommit).toHaveBeenCalledWith(rows[0], "hours", null);
    fireEvent.click(cell(1, HOURS));
    expect(within(cell(1, HOURS)).queryByRole("button", { name: "Clear entry" })).not.toBeInTheDocument();
    expect(within(cell(0, HOURS)).queryByRole("button", { name: "Clear entry" })).not.toBeInTheDocument();
  });
});

describe("openEditor", () => {
  test("opens a named cell's editor with a message already showing", () => {
    const { ref } = setup();
    act(() => ref.current.openEditor("r2", "note", { message: "Say why" }));
    expect(screen.getByRole("textbox", { name: "Note, Two" })).toHaveValue("x");
    expect(screen.getByRole("alert")).toHaveTextContent("Say why");
    expect(cell(1, NOTE)).toHaveAttribute("aria-selected", "true");
  });
});

describe("footer", () => {
  test("renders the footer row inside tfoot", () => {
    setup({ footer: <tr><td colSpan={5}>Total 1.5</td></tr> });
    expect(screen.getByText("Total 1.5").closest("tfoot")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
npx vitest run src/components/grid/DataGrid.test.jsx
```
Expected: fails to import `./DataGrid.jsx`.

- [ ] **Step 3: Implement `DataGrid.jsx`**

Create `src/components/grid/DataGrid.jsx`:

```jsx
/* ============================================================
   DataGrid.jsx — a spreadsheet-like editable table
   (docs/specs/pricing-grid.md, "The grid").

   Cells look like data until you edit them. One cell is active (roving
   tabindex, aria-selected, the focus ring); typing, Enter, or F2 opens
   an editor in place; Enter/Tab commit and move; Escape discards.
   Emptying a cell that carries an estimator entry -- or Delete on it,
   or the × that appears on it -- commits `null`, which the screen
   reads as "clear this and fall back to the next source".

   The grid owns no data. It renders `rows` through `columns` and tells
   the screen `onCommit(row, key, value)` once per changed cell. Status
   and source tiers are ordinary read-only columns whose `render`
   returns the existing Pill / .pill--neutral markup; nothing here
   invents a status treatment, and the active ring is a ring, never a
   fill, so selection cannot read as a status.

   Number editors are text inputs with inputmode="decimal", not
   type="number": the spinner and the browser's own validation get in
   the way of Tab-through entry, and the grid validates itself.
   ============================================================ */

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { X } from "lucide-react";
import { isEditable, useGridNavigation } from "./useGridNavigation.js";

const cellId = (row, col) => `${row}:${col}`;

function parseNumber(raw, edit) {
  const n = Number(raw);
  if (raw.trim() === "" || Number.isNaN(n)) return { error: "Enter a number" };
  if (edit.min != null && n < edit.min) return { error: edit.minMessage || `Enter a number of at least ${edit.min}` };
  return { value: n };
}

const DataGrid = forwardRef(function DataGrid(
  { columns, rows, rowKey, rowLabel, onCommit, onCancel, footer, caption },
  ref,
) {
  const { active, setActive, move } = useGridNavigation(columns, rows);
  // { row, col, value, message, caret } while an editor is open.
  const [editing, setEditing] = useState(null);
  const cells = useRef(new Map());
  const editorRef = useRef(null);
  // Set before any change that should end with the active cell focused
  // -- a key move, a commit, a cancel -- and consumed by the effect
  // below. Not set on mount, so rendering the grid never steals focus.
  const focusPending = useRef(false);
  // Set right before an editor is closed by code, so the blur that
  // closing fires does not commit a second time.
  const closing = useRef(false);

  useEffect(() => {
    if (focusPending.current && active && !editing) {
      focusPending.current = false;
      const el = cells.current.get(cellId(active.row, active.col));
      if (el) el.focus();
    }
  }, [active, editing]);

  useEffect(() => {
    const el = editorRef.current;
    if (!editing || !el) return;
    closing.current = false;
    el.focus();
    if (editing.caret === "end" && typeof el.setSelectionRange === "function") {
      const n = el.value.length;
      el.setSelectionRange(n, n);
    }
  }, [editing]);

  const columnByKey = (key) => columns.find((c) => c.key === key);

  function activate(next) {
    if (!next) return;
    focusPending.current = true;
    setActive(next);
  }

  function startEdit(row, col, { value, caret, message } = {}) {
    const column = columnByKey(col);
    const current = column.edit.value(rows[row]);
    setActive({ row, col });
    setEditing({ row, col, value: value ?? String(current ?? ""), caret, message: message || null });
  }

  useImperativeHandle(
    ref,
    () => ({
      openEditor(rowKeyValue, col, { message } = {}) {
        const row = rows.findIndex((r) => rowKey(r) === rowKeyValue);
        if (row < 0) return;
        startEdit(row, col, { caret: "end", message });
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, columns, rowKey],
  );

  function closeEditor() {
    closing.current = true;
    focusPending.current = true;
    setEditing(null);
  }

  function clear(row, column) {
    const r = rows[row];
    if (column.edit.hasEntry && column.edit.hasEntry(r)) onCommit(r, column.key, null);
  }

  /** Commits the open editor. Returns true when it may close: the value
   *  was valid and (if changed) committed, or unchanged. False leaves
   *  it open with a message. */
  function commitEditor() {
    const { row, col, value } = editing;
    const column = columnByKey(col);
    const edit = column.edit;
    const r = rows[row];
    const current = edit.value(r);
    if (value.trim() === "") {
      if (edit.required && edit.required(r)) {
        setEditing({ ...editing, message: edit.requiredMessage || "This can't be empty" });
        return false;
      }
      if (edit.hasEntry && edit.hasEntry(r)) onCommit(r, col, null);
      return true;
    }
    if (edit.kind === "number") {
      const parsed = parseNumber(value, edit);
      if (parsed.error) {
        setEditing({ ...editing, message: parsed.error });
        return false;
      }
      if (current == null || Number(current) !== parsed.value) onCommit(r, col, parsed.value);
      return true;
    }
    if (value !== String(current ?? "")) onCommit(r, col, value);
    return true;
  }

  function onEditorKeyDown(event) {
    if (event.key === "Enter") {
      event.preventDefault();
      if (commitEditor()) {
        closeEditor();
        activate(move("down"));
      }
    } else if (event.key === "Tab") {
      event.preventDefault();
      if (commitEditor()) {
        closeEditor();
        activate(move(event.shiftKey ? "prev" : "next") || active);
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      const { row, col } = editing;
      closeEditor();
      if (onCancel) onCancel(rows[row], col);
    }
  }

  function onEditorBlur() {
    if (closing.current || !editing) return;
    if (commitEditor()) {
      closing.current = true;
      setEditing(null);
    }
  }

  function onSelectChange(event) {
    const { row, col } = editing;
    const column = columnByKey(col);
    const next = event.target.value;
    // Close first, report second: a screen may answer the commit by
    // opening another cell's editor (the material screen does, for an
    // allowance's reason), and that has to be the last state write.
    closeEditor();
    if (next !== String(column.edit.value(rows[row]) ?? "")) onCommit(rows[row], col, next);
  }

  const MOVES = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down", Home: "home", End: "end" };

  function onCellKeyDown(event, row, column) {
    if (editing) return;
    if (MOVES[event.key]) {
      event.preventDefault();
      activate(move(MOVES[event.key]));
      return;
    }
    if (event.key === "Tab") {
      const next = move(event.shiftKey ? "prev" : "next");
      if (next) {
        event.preventDefault();
        activate(next);
      }
      return; // null: let Tab leave the grid
    }
    if (!isEditable(column, rows[row])) return;
    const kind = column.edit.kind;
    if (event.key === "Enter" || event.key === "F2") {
      event.preventDefault();
      startEdit(row, column.key, { caret: "end" });
    } else if (event.key === " " && kind === "select") {
      event.preventDefault();
      startEdit(row, column.key);
    } else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      clear(row, column);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey && kind !== "select") {
      event.preventDefault();
      startEdit(row, column.key, { value: event.key, caret: "end" });
    }
  }

  function onCellClick(row, column) {
    if (!isEditable(column, rows[row])) return;
    const isActive = active && active.row === row && active.col === column.key;
    if (isActive && !editing) startEdit(row, column.key, { caret: "end" });
    else if (!isActive) activate({ row, col: column.key });
  }

  function renderEditor(row, column) {
    const label = `${column.label}, ${rowLabel(rows[row])}`;
    const errorId = `grid-error-${cellId(row, column.key)}`;
    const described = editing.message ? errorId : undefined;
    const editor =
      column.edit.kind === "select" ? (
        <select
          ref={editorRef}
          className="grid-editor"
          aria-label={label}
          value={editing.value}
          onChange={onSelectChange}
          onKeyDown={(event) => {
            if (event.key === "Escape" || event.key === "Tab") onEditorKeyDown(event);
          }}
          onBlur={() => {
            if (!closing.current) closeEditor();
          }}
        >
          {column.edit.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          ref={editorRef}
          className={"grid-editor" + (column.align === "right" ? " tabular" : "")}
          type="text"
          inputMode={column.edit.kind === "number" ? "decimal" : undefined}
          aria-label={label}
          aria-invalid={editing.message ? true : undefined}
          aria-describedby={described}
          value={editing.value}
          onChange={(event) => setEditing({ ...editing, value: event.target.value, message: null })}
          onKeyDown={onEditorKeyDown}
          onBlur={onEditorBlur}
        />
      );
    return (
      <div className="grid-editor-wrap">
        {editor}
        {editing.message ? (
          <div id={errorId} className="grid-cell-error" role="alert">
            {editing.message}
          </div>
        ) : null}
      </div>
    );
  }

  function renderCell(r, row, column) {
    const editable = isEditable(column, r);
    const isActive = Boolean(active && active.row === row && active.col === column.key);
    const isEditing = Boolean(editing && editing.row === row && editing.col === column.key);
    const id = cellId(row, column.key);
    const Tag = column.header ? "th" : "td";
    const extra = column.className ? column.className(r) : undefined;
    const className = [column.align === "right" ? "tabular" : "", extra || ""].join(" ").trim() || undefined;
    const showClear = isActive && !isEditing && editable && column.edit.hasEntry && column.edit.hasEntry(r);
    return (
      <Tag
        key={column.key}
        scope={column.header ? "row" : undefined}
        role={column.header ? "rowheader" : "gridcell"}
        ref={(el) => (el ? cells.current.set(id, el) : cells.current.delete(id))}
        tabIndex={isActive ? 0 : -1}
        aria-selected={isActive || undefined}
        data-editable={editable || undefined}
        className={className}
        style={{ textAlign: column.align }}
        onClick={() => onCellClick(row, column)}
        onKeyDown={(event) => onCellKeyDown(event, row, column)}
      >
        {isEditing ? (
          renderEditor(row, column)
        ) : (
          <>
            {column.render(r)}
            {showClear ? (
              <button
                type="button"
                className="grid-clear"
                aria-label="Clear entry"
                onClick={(event) => {
                  event.stopPropagation();
                  clear(row, column);
                }}
              >
                <X size={14} aria-hidden="true" />
              </button>
            ) : null}
          </>
        )}
      </Tag>
    );
  }

  return (
    <div className="takeoff-table-scroll">
      <table className="data-table takeoff-table grid" role="grid">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr role="row">
            {columns.map((c) => (
              <th key={c.key} scope="col" role="columnheader" style={{ textAlign: c.align }}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, row) => (
            <tr key={rowKey(r)} role="row">
              {columns.map((c) => renderCell(r, row, c))}
            </tr>
          ))}
        </tbody>
        {footer ? <tfoot>{footer}</tfoot> : null}
      </table>
    </div>
  );
});

export default DataGrid;
```

- [ ] **Step 4: Add the styles**

In `src/styles.css`, directly after the `.takeoff-table tbody tr.is-selected` rule (~line 1690), append:

```css
/* The pricing grid (docs/specs/pricing-grid.md, "Styling"). Extends the
   takeoff table: sticky header, same cell padding. Three things are
   added and none of them is a colour for a state -- the editable mark,
   the active ring, and the pinned footer. Status stays the Pill. */
.grid td, .grid th { position: relative; }
.grid td[data-editable], .grid th[data-editable] {
  box-shadow: inset -2px 0 0 var(--ink-3);
  cursor: text;
}
/* The active cell: a ring, never a fill, so selection cannot read as a
   status. Replaces the global :focus-visible outline on the cell. */
.grid [aria-selected="true"] {
  box-shadow: inset 0 0 0 2px var(--blue);
  outline: none;
}
.grid [aria-selected="true"][data-editable] { padding-right: 32px; }
/* A change held locally until the estimator finishes it (an allowance
   waiting on its reason): dashed, the same channel unverified
   measurements use. */
.grid td.is-pending { outline: 1px dashed var(--ink-3); outline-offset: -4px; }

.grid-editor-wrap { position: relative; }
.grid-editor {
  width: 100%;
  box-sizing: border-box;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: inherit;
  outline: none;
}
.grid-cell-error {
  position: absolute;
  left: 0;
  top: 100%;
  z-index: 2;
  margin-top: 2px;
  padding: 4px 8px;
  background: var(--surface);
  border: 1px solid var(--red);
  border-radius: var(--r-sm);
  color: var(--red);
  font-size: 12.5px;
  white-space: nowrap;
}
.grid-clear {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--ink-2);
  cursor: pointer;
}
.grid-clear:hover { background: var(--paper-1); }

.grid tfoot td, .grid tfoot th {
  position: sticky;
  bottom: 0;
  z-index: 1;
  background: var(--surface);
  border-top: 2px solid var(--line-2);
  border-bottom: 0;
  font-weight: 600;
}
.grid-footer-note {
  display: block;
  margin-top: 2px;
  font-weight: 400;
  font-size: 12.5px;
  color: var(--ink-2);
}
```

- [ ] **Step 5: Run the grid tests**

```bash
npx vitest run src/components/grid
```
Expected: all pass. If `document.activeElement` assertions fail, check the focus effect runs — `fireEvent` is wrapped in `act`, so effects flush; the likely cause is `focusPending` not being set on the path under test.

- [ ] **Step 6: Build and commit**

```bash
npm run build
git add src/components/grid/DataGrid.jsx src/components/grid/DataGrid.test.jsx src/styles.css
git commit -m "DataGrid: a spreadsheet-like editable table

Cells look like data until edited; one active cell with roving
tabindex; typing, Enter, or F2 opens an in-place editor; Enter/Tab
commit and move; Escape discards; emptying, Delete, or the × clears an
entry. Validation stays on the cell. Status and source tiers render
through the columns' own Pill markup -- the grid adds no colour.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: The Labor workspace on the grid

Spec: "The two screens → Labor" (table, clearing, footer), "Saving" (commit flow, save state and undo, toast copy).

**Files:**
- Replace: `src/components/labor/laborColumns.js` → `src/components/labor/laborColumns.jsx`
- Modify: `src/components/labor/LaborWorkspace.jsx` (rewrite)
- Test: `src/components/labor/LaborWorkspace.test.jsx` (rewrite the edit tests; keep the render tests)

**Interfaces:**
- Consumes: `DataGrid` (Task 6), `store.setLaborLine -> LaborRow` (Task 3), `runMutation`, `showToast`, `saved`, `toast`, `dismissToast`, `undo` off the workspace context (Task 4), `saveStateText` (Task 4).

- [ ] **Step 1: Rewrite the tests**

Replace `src/components/labor/LaborWorkspace.test.jsx` with:

```jsx
/* ============================================================
   LaborWorkspace.test.jsx — the Labor screen on the pricing grid
   (docs/specs/pricing-grid.md). useWorkspaceContext.js is mocked
   directly, as before; the context now also carries the review
   store's runMutation/showToast/saved/toast/undo, which this screen
   uses for the same save state and toast every other workspace shows.
   ============================================================ */

import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import LaborWorkspace from "./LaborWorkspace.jsx";

const baseRow = {
  itemId: "i1", itemName: "20A duplex receptacle", quantity: 10, hoursPerUnit: null,
  hoursSourceLabel: null, rate: null, rateSourceLabel: null, adjustedHours: null,
  laborCost: null, adjustmentPercent: null, adjustmentReason: "", status: "missing", basisNote: "",
};
const pricedRow = {
  ...baseRow, hoursPerUnit: 0.5, hoursSourceLabel: "Estimated basis", rate: 78,
  rateSourceLabel: "Estimated basis", adjustedHours: 5, laborCost: 390, status: "ready",
  basisNote: "Rate based on Sacramento, CA area cost data.",
};

let context;

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderLabor({ store, extra = {} }) {
  const review = {
    runMutation: vi.fn((fn) => fn()),
    showToast: vi.fn(),
    saved: { state: "saved", at: Date.parse("2026-08-25T15:00:00Z") },
    toast: null,
    dismissToast: vi.fn(),
    undo: vi.fn().mockResolvedValue(undefined),
  };
  context = { store, projectId: "p1", ...review, ...extra };
  render(
    <MemoryRouter>
      <LaborWorkspace />
    </MemoryRouter>,
  );
  return review;
}

/** The cell under `columnLabel` on the row whose header names `itemName`.
 *  Every column renders one cell in header order (the Item column as a
 *  rowheader, the rest as gridcells), so the column's index in the
 *  header row is its index among the row's cells. The header's
 *  accessible name includes the basis note, hence the regex. */
function cellFor(itemName, columnLabel) {
  const row = screen.getByRole("rowheader", { name: new RegExp(itemName) }).closest("tr");
  const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
  return Array.from(row.querySelectorAll('[role="gridcell"], [role="rowheader"]'))[headers.indexOf(columnLabel)];
}

describe("LaborWorkspace", () => {
  test("renders a row per item, with the Missing information status when nothing resolves", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    expect(screen.getByText(/missing information/i)).toBeInTheDocument();
  });

  test("shows both tier tags and the basis note when a row resolves from the estimated basis", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "x", rows: [pricedRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getAllByText("Estimated basis")).toHaveLength(2));
    expect(screen.getByText("Rate based on Sacramento, CA area cost data.")).toBeInTheDocument();
  });

  test("renders the adjustment percent and reason", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({
        pricingSource: "llm", pricingNote: "",
        rows: [{ ...pricedRow, adjustmentPercent: 25, adjustmentReason: "Mounting height above 16 ft" }],
      }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText("+25%")).toBeInTheDocument());
    expect(screen.getByText("Mounting height above 16 ft")).toBeInTheDocument();
  });

  test("editing hours sends hoursOverride, patches the row from the response, and toasts", async () => {
    const updated = { ...baseRow, hoursPerUnit: 0.75, hoursSourceLabel: "Estimator entered", status: "approved" };
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn().mockResolvedValue(updated),
    };
    const review = renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    const hours = cellFor("20A duplex receptacle", "Hours/unit");
    fireEvent.keyDown(hours, { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Hours/unit, 20A duplex receptacle" });
    fireEvent.change(input, { target: { value: "0.75" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { hoursOverride: 0.75 }));
    await waitFor(() => expect(screen.getByText("Estimator entered")).toBeInTheDocument());
    expect(store.getLaborRows).toHaveBeenCalledTimes(1); // no refetch
    expect(review.runMutation).toHaveBeenCalled();
    expect(review.showToast).toHaveBeenCalledWith("Set hours to 0.75 on 20A duplex receptacle");
  });

  test("editing the adjustment sends adjustmentPercent, and the reason sends adjustmentReason", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows: [pricedRow] }),
      setLaborLine: vi.fn().mockImplementation((_id, changes) =>
        Promise.resolve({ ...pricedRow, ...(changes.adjustmentPercent != null ? { adjustmentPercent: changes.adjustmentPercent } : {}),
          ...(changes.adjustmentReason != null ? { adjustmentReason: changes.adjustmentReason } : {}) }),
      ),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    const adj = cellFor("20A duplex receptacle", "Adjustment");
    fireEvent.click(adj);
    fireEvent.keyDown(adj, { key: "2" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "25" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Tab" }); // commits, moves to Adjustment reason
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { adjustmentPercent: 25 }));
    const reason = cellFor("20A duplex receptacle", "Adjustment reason");
    fireEvent.keyDown(reason, { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Mounting height above 16 ft" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() =>
      expect(store.setLaborLine).toHaveBeenCalledWith("i1", { adjustmentReason: "Mounting height above 16 ft" }),
    );
  });

  test("clearing hours sends null, re-renders from the fallen-back row, and names the new source", async () => {
    const entered = { ...pricedRow, hoursPerUnit: 0.75, hoursSourceLabel: "Estimator entered", status: "approved" };
    const fallenBack = { ...pricedRow, hoursPerUnit: 0.4, hoursSourceLabel: "Company standard" };
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows: [entered] }),
      setLaborLine: vi.fn().mockResolvedValue(fallenBack),
    };
    const review = renderLabor({ store });
    await waitFor(() => expect(screen.getByText("Estimator entered")).toBeInTheDocument());
    const hours = cellFor("20A duplex receptacle", "Hours/unit");
    fireEvent.keyDown(hours, { key: "Delete" });
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { hoursOverride: null }));
    await waitFor(() => expect(screen.getByText("Company standard")).toBeInTheDocument());
    expect(review.showToast).toHaveBeenCalledWith("Cleared hours on 20A duplex receptacle — now Company standard");
  });

  test("a failed save restores the row and shows the error", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows: [pricedRow] }),
      setLaborLine: vi.fn().mockRejectedValue(new Error("Network down")),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    const hours = cellFor("20A duplex receptacle", "Hours/unit");
    fireEvent.keyDown(hours, { key: "9" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Network down"));
    expect(cellFor("20A duplex receptacle", "Hours/unit")).toHaveTextContent("0.500");
  });

  test("the footer sums adjusted hours and labor cost over priced rows and names what is left out", async () => {
    const rows = [
      pricedRow,
      { ...pricedRow, itemId: "i2", itemName: "Exit sign", adjustedHours: 2.5, laborCost: 195 },
      { ...baseRow, itemId: "i3", itemName: "Unknown symbol" },
    ];
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /Exit sign/ })).toBeInTheDocument());
    const footer = document.querySelector("tfoot");
    expect(footer).toHaveTextContent("7.50");
    expect(footer).toHaveTextContent("$585");
    expect(footer).toHaveTextContent("1 row not yet priced is not in this total");
  });

  test("shows the save state in the top bar and an undoable toast", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    const review = renderLabor({
      store,
      extra: { saved: { state: "saving", at: Date.now() }, toast: { id: "t1", text: "Set hours to 0.75 on 20A duplex receptacle" } },
    });
    await waitFor(() => expect(screen.getByText("Saving…")).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Set hours to 0.75 on 20A duplex receptacle");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(review.undo).toHaveBeenCalled();
    expect(review.dismissToast).toHaveBeenCalled();
    await waitFor(() => expect(store.getLaborRows).toHaveBeenCalledTimes(2)); // reloads after undo
  });

  test("shows the no-automatic-estimate copy when the project was not priced automatically", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "deterministic", pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText(/no automatic labor-hour estimate/i)).toBeInTheDocument());
  });
});
```

Look at the existing file's remaining tests (the pricing-note ones, the empty state, the load error) and carry any not covered above into this file unchanged, with the new `renderLabor` signature. `within` is imported for those; drop the import if nothing uses it.

Note on the Hours/unit cell: it is the grid's first editable cell, so it is already active when the grid mounts. The tests below never click it first — a click on the active cell opens the editor, and the keystroke the test sends next would land in the editor instead of on the cell.

- [ ] **Step 2: Run to verify they fail**

```bash
npx vitest run src/components/labor
```
Expected: the new edit/clear/footer/toast tests fail (no gridcells, no `Adjustment` column, no `tfoot`).

- [ ] **Step 3: Replace `laborColumns.js` with `laborColumns.jsx`**

Delete `src/components/labor/laborColumns.js` (it renders `Pill` now, so it is JSX) and create `src/components/labor/laborColumns.jsx`:

```jsx
/* ============================================================
   laborColumns.jsx — what the Labor workspace shows and which cells
   edit (docs/specs/pricing-grid.md, "The two screens → Labor").
   Header and body read one list, as before; `edit` is what DataGrid
   reads to make a cell typeable, and `hasEntry` is what lets it be
   cleared back to the next source.

   Rows come from store.getLaborRows, one per takeoff item, resolved
   fresh through the precedence chain in
   docs/specs/labor-material-pricing.md. hoursPerUnit / rate /
   adjustedHours / laborCost are independently nullable, so every
   numeric cell falls back to NONE rather than a fabricated 0.
   ============================================================ */

import Pill from "../Pill.jsx";

export const NONE = "—";
export const money = (n) => "$" + Math.round(Number(n)).toLocaleString();
export const money2 = (n) => "$" + Number(n).toFixed(2);
const percent = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(Number(n)).toLocaleString() + "%";

export const COLUMNS = [
  { key: "status", label: "Status", align: "left", render: (row) => <Pill status={row.status} /> },
  {
    key: "itemName", label: "Item", align: "left", header: true,
    render: (row) => (
      <>
        {row.itemName}
        {row.basisNote ? <div className="muted">{row.basisNote}</div> : null}
      </>
    ),
  },
  { key: "quantity", label: "Quantity", align: "right", render: (row) => row.quantity },
  {
    key: "hoursPerUnit", label: "Hours/unit", align: "right",
    render: (row) => (row.hoursPerUnit != null ? Number(row.hoursPerUnit).toFixed(3) : NONE),
    edit: {
      kind: "number", min: 0, minMessage: "Hours can't be negative",
      value: (row) => row.hoursPerUnit,
      hasEntry: (row) => row.hoursSourceLabel === "Estimator entered",
    },
  },
  {
    key: "hoursSourceLabel", label: "Hours source", align: "left",
    render: (row) => (row.hoursSourceLabel ? <span className="pill pill--neutral">{row.hoursSourceLabel}</span> : NONE),
  },
  {
    key: "rate", label: "Rate", align: "right",
    render: (row) => (row.rate != null ? money2(row.rate) + "/hr" : NONE),
    edit: {
      kind: "number", min: 0, minMessage: "Rate can't be negative",
      value: (row) => row.rate,
      hasEntry: (row) => row.rateSourceLabel === "Estimator entered",
    },
  },
  {
    key: "rateSourceLabel", label: "Rate source", align: "left",
    render: (row) => (row.rateSourceLabel ? <span className="pill pill--neutral">{row.rateSourceLabel}</span> : NONE),
  },
  {
    key: "adjustmentPercent", label: "Adjustment", align: "right",
    render: (row) => (row.adjustmentPercent != null ? percent(row.adjustmentPercent) : NONE),
    edit: {
      kind: "number", min: -100, minMessage: "Adjustment can't be below −100%",
      value: (row) => row.adjustmentPercent,
      hasEntry: (row) => row.adjustmentPercent != null,
    },
  },
  {
    key: "adjustmentReason", label: "Adjustment reason", align: "left",
    render: (row) => row.adjustmentReason || NONE,
    edit: { kind: "text", value: (row) => row.adjustmentReason, hasEntry: (row) => Boolean(row.adjustmentReason) },
  },
  {
    key: "adjustedHours", label: "Adj. hours", align: "right",
    render: (row) => (row.adjustedHours != null ? Number(row.adjustedHours).toFixed(2) : NONE),
  },
  {
    key: "laborCost", label: "Labor cost", align: "right",
    render: (row) => (row.laborCost != null ? money(row.laborCost) : NONE),
  },
];

/** What each editable column sends on the wire, and what its toast says. */
export const FIELDS = {
  hoursPerUnit: { wire: "hoursOverride", noun: "hours", format: (v) => Number(v).toFixed(2).replace(/\.?0+$/, "") },
  rate: { wire: "rateOverride", noun: "rate", format: (v) => money2(v) + "/hr" },
  adjustmentPercent: { wire: "adjustmentPercent", noun: "adjustment", format: (v) => percent(v) },
  adjustmentReason: { wire: "adjustmentReason", noun: "adjustment reason", format: null },
};
```

Check nothing else imports the old path: `grep -rn "laborColumns" src` should show only the workspace (updated in the next step).

- [ ] **Step 4: Rewrite `LaborWorkspace.jsx`**

```jsx
/* ============================================================
   LaborWorkspace.jsx — the Labor workspace on the pricing grid
   (docs/specs/pricing-grid.md, "The two screens → Labor").

   Labor rows are not part of the review snapshot useReviewStore polls
   -- getLaborRows/setLaborLine are a separate surface, because a labor
   edit is a pricing fact, not a takeoff mutation. So this screen
   fetches its own rows through `store` from useWorkspaceContext(), and
   after a write replaces the one row the PATCH response describes
   rather than refetching the list (the grid's active cell must not
   lose its place mid-Tab).

   What it borrows from the review store is the reporting: runMutation
   drives the top bar's Saving…/Saved, showToast the five-second Undo.
   Undo pulls from the shared stack and lands in the action log, not in
   this screen's rows, so the toast's Undo reloads them.
   ============================================================ */

import { useCallback, useEffect, useMemo, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import DataGrid from "../grid/DataGrid.jsx";
import { COLUMNS, FIELDS, money } from "./laborColumns.jsx";
import { saveStateText } from "../../lib/format.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";

const SOURCE_OF = { hoursPerUnit: "hoursSourceLabel", rate: "rateSourceLabel" };

function toastFor(key, value, row, updated) {
  const field = FIELDS[key];
  if (value === null) {
    const source = SOURCE_OF[key] ? updated[SOURCE_OF[key]] : null;
    if (!SOURCE_OF[key]) return `Cleared ${field.noun} on ${row.itemName}`;
    return `Cleared ${field.noun} on ${row.itemName} — ${source ? "now " + source : "nothing else is set"}`;
  }
  if (!field.format) return `Set ${field.noun} on ${row.itemName}`;
  return `Set ${field.noun} to ${field.format(value)} on ${row.itemName}`;
}

export default function LaborWorkspace() {
  const { store, projectId, runMutation, showToast, saved, toast, dismissToast, undo } = useWorkspaceContext();

  const [rows, setRows] = useState(null); // null = loading
  const [pricingSource, setPricingSource] = useState(null);
  const [pricingNote, setPricingNote] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);

  const load = useCallback(() => {
    setLoadError(null);
    return store
      .getLaborRows(projectId)
      .then((result) => {
        setRows(result.rows);
        setPricingSource(result.pricingSource);
        setPricingNote(result.pricingNote);
      })
      .catch((err) => setLoadError(err?.message || "Couldn't load labor pricing. Check your connection and try again."));
  }, [store, projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const replaceRow = (itemId, next) =>
    setRows((current) => current.map((r) => (r.itemId === itemId ? next : r)));

  // The grid reports one changed cell; this sends it, patches the row
  // from the response, and restores the row on failure. A clear is a
  // null value on the wire for the numeric fields and "" for the
  // reason, which the API normalises the same way.
  const commit = async (row, key, value) => {
    const field = FIELDS[key];
    const wire = key === "adjustmentReason" && value === null ? "" : value;
    replaceRow(row.itemId, { ...row, [key]: value });
    setSaveError(null);
    try {
      const updated = await runMutation(() => store.setLaborLine(row.itemId, { [field.wire]: wire }));
      replaceRow(row.itemId, updated);
      showToast(toastFor(key, value, row, updated));
    } catch (err) {
      replaceRow(row.itemId, row);
      setSaveError(err?.message || "That change couldn't be saved. Try again.");
    }
  };

  const totals = useMemo(() => {
    if (!rows) return null;
    const priced = rows.filter((r) => r.adjustedHours != null && r.laborCost != null);
    return {
      hours: priced.reduce((sum, r) => sum + Number(r.adjustedHours), 0),
      cost: priced.reduce((sum, r) => sum + Number(r.laborCost), 0),
      leftOut: rows.length - priced.length,
    };
  }, [rows]);

  const footer = totals ? (
    <tr>
      <td colSpan={COLUMNS.length - 2}>
        Total
        {totals.leftOut > 0 ? (
          <span className="grid-footer-note">
            {totals.leftOut} {totals.leftOut === 1 ? "row" : "rows"} not yet priced {totals.leftOut === 1 ? "is" : "are"} not in this total
          </span>
        ) : null}
      </td>
      <td className="tabular" style={{ textAlign: "right" }}>{totals.hours.toFixed(2)}</td>
      <td className="tabular" style={{ textAlign: "right" }}>{money(totals.cost)}</td>
    </tr>
  ) : null;

  return (
    <>
      <AppTopBar title="Labor" saveState={saveStateText(saved)} />

      <div className="page">
        <h1 className="page-heading">Labor</h1>

        {pricingSource !== "llm" ? (
          <p className="muted">
            This project has no automatic labor-hour estimate. Set hours and rates directly on each row below, or
            reprocess the project once a pricing assistant is configured.
          </p>
        ) : null}
        {pricingNote ? <p className="muted">{pricingNote}</p> : null}

        {loadError ? (
          <div className="load-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="btn" onClick={load}>
              Try again
            </button>
          </div>
        ) : null}

        {saveError ? (
          <div className="load-error" role="alert">
            <p>{saveError}</p>
          </div>
        ) : null}

        {rows === null && !loadError ? <p className="muted">Loading labor pricing…</p> : null}

        {rows !== null && !loadError ? (
          rows.length === 0 ? (
            <div className="empty-state">
              <h2>No items yet</h2>
              <p>This project has no takeoff items to price yet.</p>
            </div>
          ) : (
            <DataGrid
              columns={COLUMNS}
              rows={rows}
              rowKey={(row) => row.itemId}
              rowLabel={(row) => row.itemName}
              onCommit={commit}
              footer={footer}
              caption="Labor by item"
            />
          )
        ) : null}
      </div>

      {toast ? (
        <div className="toast" role="status">
          {toast.text}
          <button
            type="button"
            onClick={() => {
              undo().then(load);
              dismissToast();
            }}
          >
            Undo
          </button>
        </div>
      ) : null}
    </>
  );
}
```

- [ ] **Step 5: Run the labor tests**

```bash
npx vitest run src/components/labor
```
Expected: all pass. Likely first failures and their fixes:
- `rowheader` name: the row header's accessible name includes the basis note; the tests use a regex for that reason.
- The `Adjustment` column is found by exact `columnheader` text "Adjustment"; make sure the label is exactly that and "Adjustment reason" is the next.
- `"0.500"` in the failed-save test depends on `toFixed(3)` in the hours render.

- [ ] **Step 6: Build and commit**

```bash
npm run build
git add src/components/labor
git commit -m "Labor workspace on the pricing grid

Hours, rate, adjustment percent and reason as cells; clearing falls
back to the next source; a pinned footer sums adjusted hours and cost
and says what it leaves out; save state and the undo toast come from
the review store like every other workspace.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The Material pricing workspace on the grid

Spec: "The two screens → Material pricing" (table, Basis rule, one PATCH for the trio, allowance needs a reason, clearing, footer), "Saving".

**Files:**
- Modify: `src/components/pricing/pricingColumns.js` → rename to `pricingColumns.jsx`, rewrite
- Modify: `src/components/pricing/MaterialPricingWorkspace.jsx` (rewrite)
- Test: `src/components/pricing/MaterialPricingWorkspace.test.jsx` (rewrite)

**Interfaces:**
- Consumes: `DataGrid` with `ref.openEditor` and `onCancel` (Task 6); `store.setMaterialPrice -> MaterialRow`, `store.clearMaterialPrice -> MaterialRow` (Task 3); the review-store context (Task 4).

- [ ] **Step 1: Rewrite the tests**

Replace `src/components/pricing/MaterialPricingWorkspace.test.jsx` with:

```jsx
/* ============================================================
   MaterialPricingWorkspace.test.jsx — the Material pricing screen on
   the pricing grid (docs/specs/pricing-grid.md). Context is mocked as
   in LaborWorkspace.test.jsx.
   ============================================================ */

import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import MaterialPricingWorkspace from "./MaterialPricingWorkspace.jsx";

const baseRow = {
  itemId: "i1", itemName: "20A duplex receptacle", quantity: 10, unitPrice: null, source: null,
  sourceLabel: null, reason: "", status: "missing", basisNote: "",
};
const companyRow = { ...baseRow, unitPrice: 12.5, sourceLabel: "Company price", status: "ready" };
const projectRow = { ...baseRow, unitPrice: 15.5, source: "project_price", sourceLabel: "Project price", status: "approved" };

let context;

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderMaterial({ store, extra = {} }) {
  const review = {
    runMutation: vi.fn((fn) => fn()),
    showToast: vi.fn(),
    saved: { state: "saved", at: Date.parse("2026-08-25T15:00:00Z") },
    toast: null,
    dismissToast: vi.fn(),
    undo: vi.fn().mockResolvedValue(undefined),
  };
  context = { store, projectId: "p1", ...review, ...extra };
  render(
    <MemoryRouter>
      <MaterialPricingWorkspace />
    </MemoryRouter>,
  );
  return review;
}

function cellFor(itemName, columnLabel) {
  const row = screen.getByRole("rowheader", { name: new RegExp(itemName) }).closest("tr");
  const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
  return Array.from(row.querySelectorAll('[role="gridcell"], [role="rowheader"]'))[headers.indexOf(columnLabel)];
}

async function loaded(name = /20A duplex receptacle/) {
  await waitFor(() => expect(screen.getByRole("rowheader", { name })).toBeInTheDocument());
}

describe("MaterialPricingWorkspace", () => {
  test("renders a row per item with the Missing information status when nothing resolves", async () => {
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }) };
    renderMaterial({ store });
    await loaded();
    expect(screen.getByText(/missing information/i)).toBeInTheDocument();
  });

  test("Basis is read-only and shows the resolved tier until a price entry exists", async () => {
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [companyRow] }) };
    renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    expect(basis).toHaveTextContent("Company price");
    expect(basis).not.toHaveAttribute("data-editable");
    expect(cellFor("20A duplex receptacle", "Reason")).not.toHaveAttribute("data-editable");
  });

  test("typing a price sends the trio and patches the row; line total is quantity × price", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [companyRow] }),
      setMaterialPrice: vi.fn().mockResolvedValue(projectRow),
    };
    const review = renderMaterial({ store });
    await loaded();
    const price = cellFor("20A duplex receptacle", "Unit price");
    fireEvent.keyDown(price, { key: "1" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "15.5" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", { priceOverride: 15.5, source: "project_price", reason: "" }),
    );
    await waitFor(() => expect(screen.getByText("Project price")).toBeInTheDocument());
    expect(cellFor("20A duplex receptacle", "Line total")).toHaveTextContent("$155.00");
    expect(store.getMaterialRows).toHaveBeenCalledTimes(1);
    expect(review.showToast).toHaveBeenCalledWith("Set price to $15.50 on 20A duplex receptacle");
  });

  test("Basis becomes a select once an entry exists; choosing Allowance with a reason sends the trio", async () => {
    const allowanceRow = { ...projectRow, source: "allowance", sourceLabel: "Allowance", reason: "No vendor quote yet" };
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [{ ...projectRow, reason: "No vendor quote yet" }] }),
      setMaterialPrice: vi.fn().mockResolvedValue(allowanceRow),
    };
    const review = renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    expect(basis).toHaveAttribute("data-editable");
    fireEvent.click(basis);
    fireEvent.keyDown(basis, { key: " " });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "allowance" } });
    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", { priceOverride: 15.5, source: "allowance", reason: "No vendor quote yet" }),
    );
    expect(review.showToast).toHaveBeenCalledWith("Marked 20A duplex receptacle as allowance");
  });

  test("choosing Allowance with no reason holds the change, opens Reason with the message, and sends on commit", async () => {
    const allowanceRow = { ...projectRow, source: "allowance", sourceLabel: "Allowance", reason: "No vendor quote yet" };
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow] }),
      setMaterialPrice: vi.fn().mockResolvedValue(allowanceRow),
    };
    renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    fireEvent.click(basis);
    fireEvent.keyDown(basis, { key: " " });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "allowance" } });
    expect(store.setMaterialPrice).not.toHaveBeenCalled();
    const reasonInput = screen.getByRole("textbox", { name: "Reason, 20A duplex receptacle" });
    expect(screen.getByRole("alert")).toHaveTextContent("An allowance needs a reason");
    expect(cellFor("20A duplex receptacle", "Basis")).toHaveTextContent("Allowance");
    expect(cellFor("20A duplex receptacle", "Basis")).toHaveClass("is-pending");
    fireEvent.change(reasonInput, { target: { value: "No vendor quote yet" } });
    fireEvent.keyDown(reasonInput, { key: "Enter" });
    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", { priceOverride: 15.5, source: "allowance", reason: "No vendor quote yet" }),
    );
    await waitFor(() => expect(cellFor("20A duplex receptacle", "Basis")).not.toHaveClass("is-pending"));
  });

  test("Escape in the held Reason editor reverts Basis and sends nothing", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow] }),
      setMaterialPrice: vi.fn(),
    };
    renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    fireEvent.click(basis);
    fireEvent.keyDown(basis, { key: " " });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "allowance" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    expect(cellFor("20A duplex receptacle", "Basis")).toHaveTextContent("Project price");
    expect(store.setMaterialPrice).not.toHaveBeenCalled();
  });

  test("clearing the price calls DELETE and re-renders the fallen-back row", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow] }),
      clearMaterialPrice: vi.fn().mockResolvedValue(companyRow),
    };
    const review = renderMaterial({ store });
    await loaded();
    const price = cellFor("20A duplex receptacle", "Unit price");
    fireEvent.keyDown(price, { key: "Delete" });
    await waitFor(() => expect(store.clearMaterialPrice).toHaveBeenCalledWith("i1"));
    await waitFor(() => expect(screen.getByText("Company price")).toBeInTheDocument());
    expect(review.showToast).toHaveBeenCalledWith("Cleared price on 20A duplex receptacle — now Company price");
    // Basis and Reason are read-only again.
    expect(cellFor("20A duplex receptacle", "Basis")).not.toHaveAttribute("data-editable");
  });

  test("Delete on Basis or Reason sends nothing", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow] }),
      setMaterialPrice: vi.fn(),
      clearMaterialPrice: vi.fn(),
    };
    renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    fireEvent.click(basis);
    fireEvent.keyDown(basis, { key: "Delete" });
    const reason = cellFor("20A duplex receptacle", "Reason");
    fireEvent.click(reason);
    fireEvent.keyDown(reason, { key: "Delete" });
    expect(store.setMaterialPrice).not.toHaveBeenCalled();
    expect(store.clearMaterialPrice).not.toHaveBeenCalled();
  });

  test("the footer sums line totals over priced rows and names what is left out", async () => {
    const rows = [projectRow, { ...companyRow, itemId: "i2", itemName: "Exit sign", quantity: 4 }, { ...baseRow, itemId: "i3", itemName: "Unknown symbol" }];
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows }) };
    renderMaterial({ store });
    await loaded(/Exit sign/);
    const footer = document.querySelector("tfoot");
    expect(footer).toHaveTextContent("$205.00"); // 155 + 50
    expect(footer).toHaveTextContent("1 row not yet priced is not in this total");
  });

  test("shows the save state and an undoable toast that reloads", async () => {
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }) };
    const review = renderMaterial({
      store,
      extra: { saved: { state: "error", at: Date.now() }, toast: { id: "t1", text: "Set price to $15.50 on 20A duplex receptacle" } },
    });
    await loaded();
    expect(screen.getByText("Couldn't save — retrying")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(review.undo).toHaveBeenCalled();
    await waitFor(() => expect(store.getMaterialRows).toHaveBeenCalledTimes(2));
  });
});
```

Carry over any existing tests not covered here (pricing note copy, empty state, load error) with the new `renderMaterial` signature. `within` is imported for those; drop it if unused.

As on the labor screen, Unit price is the first editable cell and is active on mount, so the tests never click it before sending a key.

- [ ] **Step 2: Run to verify they fail**

```bash
npx vitest run src/components/pricing
```
Expected: the new tests fail (no `Basis`/`Reason`/`Line total` columns, no gridcells).

- [ ] **Step 3: Rewrite `pricingColumns.jsx`**

Delete `pricingColumns.js`, create `src/components/pricing/pricingColumns.jsx`:

```jsx
/* ============================================================
   pricingColumns.jsx — what the Material pricing workspace shows and
   which cells edit (docs/specs/pricing-grid.md, "The two screens →
   Material pricing").

   Basis is the one cell that is sometimes read-only and sometimes a
   select, and the rule is the row's `source`: with no project entry
   yet it shows the resolved tier (Company price, Regional baseline)
   and cannot be edited -- typing a price is what creates an entry;
   with one, it is a select between the two things an entry can mean.
   Reason follows Basis. Neither can be cleared on its own: the price
   is the entry, and clearing it clears all three.

   `pendingSource` is set by the screen while an Allowance choice waits
   on its reason -- rendered as the tag it will become, dashed, so the
   row shows what is about to happen without pretending it has.
   ============================================================ */

import Pill from "../Pill.jsx";

export const NONE = "—";
export const money = (n) => "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const BASIS_LABEL = { project_price: "Project price", allowance: "Allowance" };

export const ALLOWANCE_REASON_MESSAGE =
  "An allowance needs a reason — say what it's standing in for, so the total can be traced back.";

export const COLUMNS = [
  { key: "status", label: "Status", align: "left", render: (row) => <Pill status={row.status} /> },
  {
    key: "itemName", label: "Material", align: "left", header: true,
    render: (row) => (
      <>
        {row.itemName}
        {row.basisNote ? <div className="muted">{row.basisNote}</div> : null}
      </>
    ),
  },
  { key: "quantity", label: "Quantity", align: "right", render: (row) => row.quantity },
  {
    key: "unitPrice", label: "Unit price", align: "right",
    render: (row) => (row.unitPrice != null ? money(row.unitPrice) : NONE),
    edit: {
      kind: "number", min: 0, minMessage: "Price can't be negative",
      value: (row) => row.unitPrice,
      hasEntry: (row) => row.source != null,
    },
  },
  {
    key: "source", label: "Basis", align: "left",
    className: (row) => (row.pendingSource ? "is-pending" : undefined),
    render: (row) => {
      const label = row.pendingSource ? BASIS_LABEL[row.pendingSource] : row.sourceLabel;
      return label ? <span className="pill pill--neutral">{label}</span> : NONE;
    },
    edit: {
      kind: "select",
      value: (row) => row.pendingSource || row.source,
      options: [
        { value: "project_price", label: "Project price" },
        { value: "allowance", label: "Allowance" },
      ],
      disabled: (row) => row.source == null,
    },
  },
  {
    key: "reason", label: "Reason", align: "left",
    render: (row) => row.reason || NONE,
    edit: {
      kind: "text",
      value: (row) => row.reason,
      disabled: (row) => row.source == null,
      required: (row) => (row.pendingSource || row.source) === "allowance",
      requiredMessage: ALLOWANCE_REASON_MESSAGE,
    },
  },
  {
    key: "lineTotal", label: "Line total", align: "right",
    render: (row) => (row.unitPrice != null ? money(Number(row.quantity) * Number(row.unitPrice)) : NONE),
  },
];
```

- [ ] **Step 4: Rewrite `MaterialPricingWorkspace.jsx`**

```jsx
/* ============================================================
   MaterialPricingWorkspace.jsx — the Material pricing workspace on
   the pricing grid (docs/specs/pricing-grid.md, "The two screens →
   Material pricing").

   Same shape as LaborWorkspace.jsx: rows fetched through `store`,
   one row patched from each write's response, save state and the undo
   toast from the review store. What is particular here:

   - Unit price, Basis, and Reason are one entry on the wire. A commit
     on any of them sends all three from the row's current state plus
     the change.
   - An allowance needs a reason, and the API refuses one without. The
     rule is met on the cell: choosing Allowance with an empty Reason
     holds the choice locally (pendingSource), moves to Reason, opens
     its editor with the message, and sends when the reason commits.
     Escape there drops the held choice.
   - Clearing the price removes the whole entry (DELETE) -- an entry
     without a price is not a state the table can hold.
   ============================================================ */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import DataGrid from "../grid/DataGrid.jsx";
import { ALLOWANCE_REASON_MESSAGE, COLUMNS, money } from "./pricingColumns.jsx";
import { saveStateText } from "../../lib/format.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";

function toastFor(key, value, row, updated) {
  if (key === "unitPrice" && value === null) {
    return `Cleared price on ${row.itemName} — ${updated.sourceLabel ? "now " + updated.sourceLabel : "nothing else is set"}`;
  }
  if (key === "source") {
    return value === "allowance" ? `Marked ${row.itemName} as allowance` : `Marked ${row.itemName} as project price`;
  }
  if (key === "reason") return `Set reason on ${row.itemName}`;
  return `Set price to ${money(value)} on ${row.itemName}`;
}

export default function MaterialPricingWorkspace() {
  const { store, projectId, runMutation, showToast, saved, toast, dismissToast, undo } = useWorkspaceContext();

  const [rows, setRows] = useState(null); // null = loading
  const [pricingSource, setPricingSource] = useState(null);
  const [pricingNote, setPricingNote] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const grid = useRef(null);

  const load = useCallback(() => {
    setLoadError(null);
    return store
      .getMaterialRows(projectId)
      .then((result) => {
        setRows(result.rows);
        setPricingSource(result.pricingSource);
        setPricingNote(result.pricingNote);
      })
      .catch((err) => setLoadError(err?.message || "Couldn't load material pricing. Check your connection and try again."));
  }, [store, projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const replaceRow = (itemId, next) =>
    setRows((current) => current.map((r) => (r.itemId === itemId ? next : r)));

  const send = async (row, key, value, request) => {
    setSaveError(null);
    try {
      const updated = await runMutation(request);
      replaceRow(row.itemId, updated);
      showToast(toastFor(key, value, row, updated));
    } catch (err) {
      replaceRow(row.itemId, { ...row, pendingSource: undefined });
      setSaveError(err?.message || "That change couldn't be saved. Try again.");
    }
  };

  const commit = (row, key, value) => {
    if (key === "unitPrice" && value === null) {
      replaceRow(row.itemId, { ...row, unitPrice: null });
      return send(row, key, value, () => store.clearMaterialPrice(row.itemId));
    }
    const next = {
      priceOverride: key === "unitPrice" ? value : row.unitPrice,
      source: key === "source" ? value : row.pendingSource || row.source || "project_price",
      reason: key === "reason" ? value : row.reason,
    };
    if (next.source === "allowance" && !next.reason.trim()) {
      // Hold the choice, ask for the reason where the estimator is looking.
      replaceRow(row.itemId, { ...row, pendingSource: "allowance" });
      grid.current.openEditor(row.itemId, "reason", { message: ALLOWANCE_REASON_MESSAGE });
      return undefined;
    }
    replaceRow(row.itemId, {
      ...row,
      unitPrice: next.priceOverride,
      source: next.source,
      reason: next.reason,
      pendingSource: undefined,
    });
    const toastKey = row.pendingSource && key === "reason" ? "source" : key;
    const toastValue = toastKey === "source" ? next.source : value;
    return send(row, toastKey, toastValue, () => store.setMaterialPrice(row.itemId, next));
  };

  const cancel = (row, key) => {
    if (key === "reason" && row.pendingSource) replaceRow(row.itemId, { ...row, pendingSource: undefined });
  };

  const totals = useMemo(() => {
    if (!rows) return null;
    const priced = rows.filter((r) => r.unitPrice != null);
    return {
      cost: priced.reduce((sum, r) => sum + Number(r.quantity) * Number(r.unitPrice), 0),
      leftOut: rows.length - priced.length,
    };
  }, [rows]);

  const footer = totals ? (
    <tr>
      <td colSpan={COLUMNS.length - 1}>
        Total
        {totals.leftOut > 0 ? (
          <span className="grid-footer-note">
            {totals.leftOut} {totals.leftOut === 1 ? "row" : "rows"} not yet priced {totals.leftOut === 1 ? "is" : "are"} not in this total
          </span>
        ) : null}
      </td>
      <td className="tabular" style={{ textAlign: "right" }}>{money(totals.cost)}</td>
    </tr>
  ) : null;

  return (
    <>
      <AppTopBar title="Material pricing" saveState={saveStateText(saved)} />

      <div className="page">
        <h1 className="page-heading">Material pricing</h1>

        {pricingSource !== "llm" ? (
          <p className="muted">
            This project has no automatic regional price estimate. Set a price directly on each row below, or
            reprocess the project once a pricing assistant is configured.
          </p>
        ) : null}
        {pricingNote ? <p className="muted">{pricingNote}</p> : null}

        {loadError ? (
          <div className="load-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="btn" onClick={load}>
              Try again
            </button>
          </div>
        ) : null}

        {saveError ? (
          <div className="load-error" role="alert">
            <p>{saveError}</p>
          </div>
        ) : null}

        {rows === null && !loadError ? <p className="muted">Loading material pricing…</p> : null}

        {rows !== null && !loadError ? (
          rows.length === 0 ? (
            <div className="empty-state">
              <h2>No items yet</h2>
              <p>This project has no takeoff items to price yet.</p>
            </div>
          ) : (
            <DataGrid
              ref={grid}
              columns={COLUMNS}
              rows={rows}
              rowKey={(row) => row.itemId}
              rowLabel={(row) => row.itemName}
              onCommit={commit}
              onCancel={cancel}
              footer={footer}
              caption="Material pricing by item"
            />
          )
        ) : null}
      </div>

      {toast ? (
        <div className="toast" role="status">
          {toast.text}
          <button
            type="button"
            onClick={() => {
              undo().then(load);
              dismissToast();
            }}
          >
            Undo
          </button>
        </div>
      ) : null}
    </>
  );
}
```

- [ ] **Step 5: Run the pricing tests**

```bash
npx vitest run src/components/pricing src/components/grid
```
Expected: all pass. One subtle spot if "choosing Allowance with no reason" fails with no Reason editor open: `DataGrid.onSelectChange` must call `closeEditor()` *before* `onCommit` (Task 6 does), so the screen's `openEditor` inside the commit handler is the last state write.

- [ ] **Step 6: Build and commit**

```bash
npm run build
git add src/components/pricing
git commit -m "Material pricing workspace on the pricing grid

Unit price, Basis, and Reason as cells that send one entry; an
allowance without a reason is held on the cell until the reason is
typed; clearing the price removes the entry and the row falls back;
a pinned footer sums line totals.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Docs and the full suites

Spec: "Not built in this slice"; keeps `README.md` and the older spec honest.

**Files:**
- Modify: `README.md` (project structure block; the Known limitations list)
- Modify: `docs/specs/labor-material-pricing.md` ("Frontend" section, first paragraph)
- Modify: `CLAUDE.md` (Architecture tree)

- [ ] **Step 1: README project structure**

In `README.md`'s `src/` tree, after the `notes/` block, add:

```
    grid/                      the editable grid under Labor and Material pricing
      DataGrid.jsx             cells, in-place editors, validation, the Clear affordance
      useGridNavigation.js     the active-cell movement rules
    labor/, pricing/           Labor and Material pricing on that grid
```

In "Known limitations", add a bullet:

```
- **The pricing grid edits one cell at a time.** Labor and Material pricing behave like a spreadsheet at the cell level — click or type to edit, Tab/Enter/arrows to move, Delete to clear an entry — but there is no range selection, fill-down, or paste yet. Crew mix and per-line notes are stored by the API and not shown; a project default crew mix in project settings is the intended next step.
```

- [ ] **Step 2: The older spec's Frontend section**

In `docs/specs/labor-material-pricing.md`, under `## Frontend`, replace the paragraph beginning "Both screens are plain tables in this codebase's existing style" with:

```
Both screens were first built as plain tables in the takeoff table's
style. They now render through the shared editable grid in
`src/components/grid/` — see
[`docs/specs/pricing-grid.md`](pricing-grid.md) for cell navigation,
in-place editing, clearing an entry, the footer, and the save-state
and toast wiring. Filter chips were never built on these two screens.
```

- [ ] **Step 3: CLAUDE.md architecture tree**

In `CLAUDE.md`'s `src/` tree, after the `notes/` block, add:

```
    grid/                    the editable grid: DataGrid.jsx + useGridNavigation.js
    labor/, pricing/         Labor and Material pricing, rendered through it
```

- [ ] **Step 4: Run every suite**

```bash
npx vitest run
npm run build
cd api && DATABASE_URL=postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff TEST_DATABASE_URL=postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test_grid ../../../../.enginevenv/bin/pytest -q -rs
```
Expected: all green; the engine regression tests report as skipped (no `BIDMATE_BID_SET`), which is expected.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md docs/specs/labor-material-pricing.md
git commit -m "Docs: the pricing grid under Labor and Material pricing

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review against the spec

- **Grid files, column descriptor, three cell states, key tables, validation, clearing (three ways), accessibility** → Tasks 5–6.
- **Labor table incl. adjustment columns, null clears, `LaborRowOut` fields, PATCH returns row, footer with caption, toast copy** → Tasks 1, 2, 3, 7.
- **Material table incl. Basis rule, one PATCH for the trio, allowance hold on the cell, DELETE clear, line total, footer** → Tasks 1, 2, 3, 8.
- **Save state, `runMutation`/`showToast` exposure, `saveStateText` shared, undo toast reloading rows** → Tasks 4, 7, 8.
- **Styling tokens** → Task 6 Step 4.
- **Backend tests listed in the spec** → Tasks 1–2. **Frontend tests listed** → Tasks 5–8.
- **Not built** (crew mix, notes, range/fill/paste, sort/filter, screen G) — untouched, and named in the README by Task 9.

Names used across tasks: `labor_row_for` / `material_row_for` (Tasks 1, 2); `clearMaterialPrice` (Tasks 3, 8); `runMutation` / `showToast` / `saveStateText` (Tasks 4, 7, 8); `isEditable` / `firstEditable` / `moveActive` / `useGridNavigation` (Tasks 5, 6); `DataGrid` props `columns rows rowKey rowLabel onCommit onCancel footer caption ref` and `edit.{kind,value,min,minMessage,options,disabled,hasEntry,required,requiredMessage}` (Tasks 6, 7, 8); `is-pending` / `pendingSource` (Tasks 6, 8).
