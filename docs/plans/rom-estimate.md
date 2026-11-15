# ROM estimate implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a complete Division 26 rough-order-of-magnitude estimate the moment processing finishes, with every line tagged `counted` or `assumed` and every assumption carrying a basis a reader can check.

**Architecture:** An `Assumption` record is written per section by the worker, beside the items it explains. `rom_totals()` lands next to `approved_totals()` over the same `countable_items()` predicate, applying no status filter. A new read endpoint assembles sections, a generated qualifications block, and a budget range derived from named basis classes. The Estimate summary workspace renders it. Nothing in the review workspace changes.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (Postgres), React 18 + plain CSS, pytest, vitest.

**Spec:** [`docs/specs/rom-estimate.md`](../specs/rom-estimate.md). Approved mockup: [`docs/specs/assets/rom-mockup.html`](../specs/assets/rom-mockup.html).

## Global Constraints

- **`counted`/`assumed` is a different axis from the four review labels.** Never render origin with the review-status components, colours, or tokens. Use `--slate` for counted and `--amber` for assumed, as the mockup does.
- **Green never appears in the ROM.** It stays reserved for estimator-approved content.
- **Origin is never colour alone** — a word in the tag plus a dashed left edge on assumed rows.
- **`countable_items()` in `api/app/takeoff/totals.py` is the only exclusion predicate.** Both aggregations build on it. No hand-copied `!rejected` filter anywhere.
- **An assumption missing `basis` or `where` is refused at the boundary**, the way `validate_warning()` in `api/app/takeoff/ingest.py:216` refuses a warning missing one of its five fields.
- **No markup, overhead, profit, bond, or tax.** Direct cost only.
- **Copy:** sentence case, no model names, no confidence numbers, no processing internals. `className="tabular"` on every quantity and total.
- **`app.main` may not import anything that opens a file.** Assumption generation runs in `app.worker`; `api/tests/test_api_import_boundary.py` enforces this and must stay green.
- **Run `npm run build` before each frontend commit.**

**Test commands:** backend `.enginevenv/bin/python -m pytest api/tests/<file> -v` (or `docker compose run --rm api python -m pytest tests/<file> -v`); frontend `npm test -- <path>`.

## Review Focus

Five conditions the spec implies that no task's happy path exercises. Each has its test added to the task that owns the code.

1. **A project with zero items** — fresh upload, or every sheet unreadable. The ROM must render as an empty document with a stated reason, and the range must not divide by zero. *Task 3, Task 8.*
2. **An assumption whose subject item was later rejected or deleted** — the orphan must drop out of both the total and the qualifications block rather than citing a line that is no longer there. *Task 4.*
3. **Every item excluded by scope assumptions** — the total is zero, and the document must say the scope removed everything rather than presenting a bare `$0`. *Task 4.*
4. **An item on a superseded sheet carrying an assumption** — stays out of `rom_totals()`, because `countable_items()` excludes it (invariant 2). *Task 2.*
5. **A re-run producing the same assumption twice** — one ceiling-height assumption shared by forty items, generated again on the next run, must still yield one qualification line. *Task 8, Task 11.*

---

### Task 1: The assumption record

**Files:**
- Create: `api/app/estimate/__init__.py`, `api/app/estimate/basis.py`
- Modify: `api/app/takeoff/models.py` (add `Assumption` after `Note`, ~line 697)
- Create: `api/migrations/versions/0029_assumptions.py`
- Test: `api/tests/test_assumption_record.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `BASIS` (closed mapping basis key → `BasisSpec(label, spread)`), `SECTIONS = ("scope", "takeoff", "labor", "material")`, `validate_assumption(raw: dict) -> dict`, and the `Assumption` model.

- [ ] **Step 1: Write the failing tests**

```python
def test_basis_set_is_closed_and_carries_spreads():
    assert set(BASIS) == {
        "supplier_quote", "firm_default", "market_estimate", "class_average",
        "inferred", "rule_of_thumb", "scaled", "standard_exclusion",
    }
    assert BASIS["supplier_quote"].spread == Decimal("0")
    assert BASIS["standard_exclusion"].spread == Decimal("0")
    assert BASIS["firm_default"].spread == Decimal("0.10")
    assert BASIS["market_estimate"].spread == Decimal("0.15")
    assert BASIS["class_average"].spread == Decimal("0.20")
    assert BASIS["scaled"].spread == Decimal("0.20")
    assert BASIS["inferred"].spread == Decimal("0.25")
    assert BASIS["rule_of_thumb"].spread == Decimal("0.25")

def test_validate_assumption_refuses_missing_basis():
    with pytest.raises(DomainError) as e:
        validate_assumption({"section": "takeoff", "title": "t", "found": "f",
                             "why": "w", "where": "EL101"})
    assert e.value.code == "invalid_assumption"

def test_validate_assumption_refuses_missing_where():
    with pytest.raises(DomainError) as e:
        validate_assumption({"section": "takeoff", "title": "t", "found": "f",
                             "why": "w", "basis": "rule_of_thumb"})
    assert e.value.code == "invalid_assumption"

def test_validate_assumption_refuses_unknown_basis():
    with pytest.raises(DomainError):
        validate_assumption({"section": "takeoff", "title": "t", "found": "f",
                             "why": "w", "basis": "vibes", "where": "EL101"})

def test_validate_assumption_refuses_unknown_section():
    with pytest.raises(DomainError):
        validate_assumption({"section": "vibes", "title": "t", "found": "f",
                             "why": "w", "basis": "scaled", "where": "EL101"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_assumption_record.py -v`
Expected: FAIL, `ModuleNotFoundError: app.estimate.basis`

- [ ] **Step 3: Write `api/app/estimate/basis.py`**

`BasisSpec` is a frozen dataclass of `label: str` and `spread: Decimal`. `BASIS` is a module-level dict literal with the eight keys and spreads asserted above, mirroring the spec's table. `SECTIONS` is the four-tuple. `validate_assumption(raw)` mirrors `ingest.validate_warning` — required fields `("section", "title", "found", "why", "basis", "where")`, each non-empty after strip, plus membership checks on `section` and `basis`; raises `DomainError("invalid_assumption", <estimator-facing message>, status=422)`.

- [ ] **Step 4: Add the `Assumption` model to `api/app/takeoff/models.py`**

Columns: `id` (UUID pk), `project_id` (FK projects, cascade, indexed), `section` (String(20)), `subject_kind` (String(20): `project`, `sheet`, `item`), `subject_id` (UUID, nullable), `title`/`found`/`why`/`where` (Text), `basis` (String(30)), `value` (String(100), nullable), `unit` (String(20), nullable), `excluded_value` (Numeric(12,2), nullable — dollars a `standard_exclusion` removed), `source` (String(20): `engine` or `estimator`), `created_by_user_id` (FK users, nullable), `created_at` (timestamptz, default now). Docstring must state that `counted`/`assumed` is a separate axis from the four review labels, in the manner of `Note`'s docstring.

- [ ] **Step 5: Write migration `0029_assumptions.py`**

`revision = '0029'`, `down_revision = '0028'`. Creates the `assumptions` table with the columns above plus indexes on `project_id` and `(project_id, section)`.

- [ ] **Step 6: Run the tests and the migration**

Run: `.enginevenv/bin/python -m pytest api/tests/test_assumption_record.py -v`
Expected: PASS
Run: `docker compose run --rm api alembic upgrade head`
Expected: `Running upgrade 0028 -> 0029`

- [ ] **Step 7: Commit**

```bash
git add api/app/estimate/ api/app/takeoff/models.py api/migrations/versions/0029_assumptions.py api/tests/test_assumption_record.py
git commit -m "feat: assumption record, basis vocabulary, and boundary validation"
```

---

### Task 2: `rom_totals()`

**Files:**
- Modify: `api/app/takeoff/totals.py`
- Test: `api/tests/test_rom_totals.py`

**Interfaces:**
- Consumes: `countable_items(project_id)`, already in `api/app/takeoff/totals.py`.
- Produces: `rom_totals(db, project_id) -> RomTotals` with fields `by_system: dict[str, Decimal]`, `material_cost: Decimal`, `labor_cost: Decimal`, `labor_hours: Decimal`, `direct_cost: Decimal`, `counted_count: int`, `assumed_count: int`, `unpriced_count: int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_rom_totals_includes_unapproved_items(db, project_with_mixed_statuses):
    # four items: ready, attention, missing, approved — all priced $100
    assert rom_totals(db, project.id).direct_cost == Decimal("400")

def test_approved_totals_is_unchanged_by_rom_totals(db, project_with_mixed_statuses):
    assert approved_totals(db, project.id).approved_count == 1

def test_rom_totals_excludes_rejected(db, project_with_rejected_item):
    assert rom_totals(db, project.id).direct_cost == Decimal("0")

def test_rom_totals_excludes_superseded_sheet(db, project_with_superseded_sheet):
    # Review Focus 4 — an assumption on a superseded sheet's item changes nothing
    assert rom_totals(db, project.id).direct_cost == Decimal("0")

def test_rom_totals_counts_unpriced_separately(db, project_with_unpriced_item):
    t = rom_totals(db, project.id)
    assert t.unpriced_count == 1
    assert t.direct_cost == Decimal("0")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_rom_totals.py -v`
Expected: FAIL, `ImportError: cannot import name 'rom_totals'`

- [ ] **Step 3: Implement `rom_totals(db: DbSession, project_id: uuid.UUID) -> RomTotals` in `api/app/takeoff/totals.py`**

Build on `countable_items(project_id)` with no status filter. `unpriced_count` counts items whose `total_cost` is zero *and* which carry no material price resolution — an item genuinely priced at zero is not unpriced. Add a module comment stating that the two aggregations are different numbers on purpose and must never be presented as the same one.

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_rom_totals.py api/tests/test_totals.py -v`
Expected: PASS, including the pre-existing totals tests

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/totals.py api/tests/test_rom_totals.py
git commit -m "feat: rom_totals over the same countable predicate, no status filter"
```

---

### Task 3: The budget range

**Files:**
- Create: `api/app/estimate/range.py`
- Test: `api/tests/test_estimate_range.py`

**Interfaces:**
- Consumes: `BASIS` from Task 1.
- Produces: `budget_range(direct_cost: Decimal, exposures: list[Exposure]) -> RangeResult` with `low`, `high`, `spread_dollars`; `Exposure(basis: str, dollars: Decimal)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_zero_spread_bases_contribute_nothing():
    r = budget_range(Decimal("1000"), [Exposure("supplier_quote", Decimal("1000"))])
    assert (r.low, r.high) == (Decimal("1000"), Decimal("1000"))

def test_single_exposure_applies_its_spread():
    r = budget_range(Decimal("1000"), [Exposure("rule_of_thumb", Decimal("400"))])
    assert r.spread_dollars == Decimal("100")  # 400 * 0.25
    assert (r.low, r.high) == (Decimal("900"), Decimal("1100"))

def test_exposures_combine_linearly_not_in_quadrature():
    r = budget_range(Decimal("1000"), [
        Exposure("rule_of_thumb", Decimal("400")),   # 100
        Exposure("class_average", Decimal("200")),   # 40
    ])
    assert r.spread_dollars == Decimal("140")

def test_low_never_goes_below_zero():
    r = budget_range(Decimal("100"), [Exposure("rule_of_thumb", Decimal("1000"))])
    assert r.low == Decimal("0")

def test_no_exposures_gives_a_point_range():
    # Review Focus 1 — a project with nothing in it must not divide by zero
    r = budget_range(Decimal("0"), [])
    assert (r.low, r.high, r.spread_dollars) == (Decimal("0"), Decimal("0"), Decimal("0"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_estimate_range.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `budget_range` in `api/app/estimate/range.py`**

Pure; no database access. Sum `dollars * BASIS[basis].spread` across exposures, clamp `low` at zero. Module docstring states why linear rather than root-sum-square, quoting the spec's reason: an estimator must be able to explain the range to a GC in one sentence.

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_estimate_range.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/range.py api/tests/test_estimate_range.py
git commit -m "feat: budget range as a dollar-weighted linear spread over basis classes"
```

---

### Task 4: Scope exclusions filter the total

**Files:**
- Create: `api/app/estimate/exclusions.py`
- Modify: `api/app/takeoff/totals.py` (`rom_totals` takes the exclusion set)
- Test: `api/tests/test_scope_exclusions.py`

**Interfaces:**
- Consumes: `Assumption`, `rom_totals`.
- Produces: `excluded_item_ids(db, project_id) -> set[uuid.UUID]`, `excluded_value(db, project_id) -> Decimal`. `rom_totals` gains keyword `exclude: set[uuid.UUID] | None = None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_excluded_items_leave_the_total(db, project_with_fire_alarm_items):
    # a standard_exclusion assumption covering system "Fire alarm"
    assert rom_totals(db, project.id, exclude=excluded_item_ids(db, project.id)).direct_cost \
        == Decimal("300")  # 400 total less the 100 of fire alarm

def test_excluded_value_is_carried_for_the_qualifications_block(db, project_with_fire_alarm_items):
    assert excluded_value(db, project.id) == Decimal("100")

def test_orphan_assumption_drops_out(db, project_with_rejected_subject):
    # Review Focus 2 — subject item rejected after the assumption was written
    assert excluded_item_ids(db, project.id) == set()
    assert excluded_value(db, project.id) == Decimal("0")

def test_everything_excluded_is_distinguishable_from_nothing_counted(db, project_fully_excluded):
    # Review Focus 3 — zero, but for a stated reason
    t = rom_totals(db, project.id, exclude=excluded_item_ids(db, project.id))
    assert t.direct_cost == Decimal("0")
    assert excluded_value(db, project.id) > Decimal("0")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_scope_exclusions.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `api/app/estimate/exclusions.py`**

An exclusion is an `Assumption` with `section="scope"` and `basis="standard_exclusion"`. Resolve its `subject_kind`/`subject_id` to item ids through `countable_items()` — never a separate query with its own filters — so an item that is rejected or on a superseded sheet is already gone. `excluded_value` sums `total_cost` over that same resolved set.

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_scope_exclusions.py api/tests/test_rom_totals.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/exclusions.py api/app/takeoff/totals.py api/tests/test_scope_exclusions.py
git commit -m "feat: scope exclusions remove items from the ROM and carry their value"
```

---

### Task 5: Labor and material assumptions

**Files:**
- Create: `api/app/estimate/generate_cost.py`
- Test: `api/tests/test_generate_cost_assumptions.py`

**Interfaces:**
- Consumes: `resolve_labor`, `resolve_material_price` (`api/app/takeoff/pricing.py`), `validate_assumption`.
- Produces: `labor_assumptions(db, project) -> list[dict]`, `material_assumptions(db, project) -> list[dict]`. Both return validated assumption dicts, not ORM rows.

- [ ] **Step 1: Write the failing tests**

```python
def test_firm_default_rate_becomes_an_assumption(db, project_without_project_rate):
    a = one(labor_assumptions(db, project), title_contains="rate")
    assert a["basis"] == "firm_default"
    assert a["section"] == "labor"

def test_project_rate_override_produces_no_assumption(db, project_with_own_rate):
    assert not any("rate" in a["title"] for a in labor_assumptions(db, project))

def test_unquoted_gear_takes_class_average(db, project_with_switchboard_no_quote):
    a = one(material_assumptions(db, project), title_contains="Switchboard")
    assert a["basis"] == "class_average"

def test_supplier_quote_produces_no_assumption(db, project_with_quoted_switchboard):
    assert not any("Switchboard" in a["title"] for a in material_assumptions(db, project))

def test_every_generated_assumption_validates(db, project_without_project_rate):
    for a in labor_assumptions(db, project) + material_assumptions(db, project):
        validate_assumption(a)  # raises if basis or where is missing
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_generate_cost_assumptions.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `generate_cost.py`**

Both resolvers already return a basis note per line; read those rather than recomputing. Map the resolver's own source signal to a basis key — firm table → `firm_default`, market feed → `market_estimate`, supplier price sheet → `supplier_quote` (which emits no assumption), neither → `class_average`. Copy for each basis lives in `api/app/estimate/copy.py` alongside `api/app/market/copy.py`'s register; no model names, no processing internals.

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_generate_cost_assumptions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/generate_cost.py api/app/estimate/copy.py api/tests/test_generate_cost_assumptions.py
git commit -m "feat: labor and material assumptions from the existing resolver bases"
```

---

### Task 6: Takeoff assumptions

**Files:**
- Create: `api/app/estimate/generate_takeoff.py`
- Test: `api/tests/test_generate_takeoff_assumptions.py`

**Interfaces:**
- Consumes: `validate_assumption`, `Sheet`, `Item`.
- Produces: `takeoff_assumptions(db, project) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_homerun_footage_uses_the_firm_rule(db, project_with_devices_no_routes):
    a = one(takeoff_assumptions(db, project), title_contains="homerun")
    assert a["basis"] == "rule_of_thumb"
    assert a["unit"] == "ft"

def test_missing_scale_is_one_sheet_level_assumption_not_one_per_item(db, sheet_without_scale_and_forty_measured_items):
    scale = [a for a in takeoff_assumptions(db, project) if "scale" in a["title"].lower()]
    assert len(scale) == 1
    assert scale[0]["subject_kind"] == "sheet"

def test_missing_scale_assumption_names_what_it_affects(db, sheet_without_scale_and_forty_measured_items):
    a = one(takeoff_assumptions(db, project), title_contains="scale")
    assert "40" in a["found"] or "every measured" in a["found"].lower()

def test_sheet_with_a_scale_produces_no_scale_assumption(db, sheet_with_scale):
    assert not any("scale" in a["title"].lower() for a in takeoff_assumptions(db, project))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_generate_takeoff_assumptions.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `generate_takeoff.py`**

Three producers: branch footage from the firm's feet-per-device rule (`rule_of_thumb`), a per-sheet scale assumption when `Sheet.scale` is unset and the sheet carries measured items (`scaled`, `subject_kind="sheet"`, one record naming the count it affects), and feeder lengths implied by the one-line but not dimensioned (`scaled`). Counting is not touched.

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_generate_takeoff_assumptions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/generate_takeoff.py api/tests/test_generate_takeoff_assumptions.py
git commit -m "feat: takeoff assumptions, with a missing scale assumed once per sheet"
```

---

### Task 7: Scope assumptions

**Files:**
- Create: `api/app/estimate/generate_scope.py`
- Test: `api/tests/test_generate_scope_assumptions.py`

**Interfaces:**
- Consumes: `validate_assumption`, `app.scope.service` read paths.
- Produces: `scope_assumptions(db, project) -> list[dict]`; `STANDARD_EXCLUSIONS: tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_silent_document_set_yields_standard_exclusions(db, project_with_scope_silent_on_temp_power):
    a = one(scope_assumptions(db, project), title_contains="Temporary power")
    assert a["basis"] == "standard_exclusion"
    assert a["section"] == "scope"

def test_an_addressed_exclusion_is_not_assumed(db, project_with_scope_stating_temp_power_included):
    assert not any("Temporary power" in a["title"] for a in scope_assumptions(db, project))

def test_extracted_scope_statements_are_not_assumptions(db, project_with_full_scope_letter):
    assert scope_assumptions(db, project) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_generate_scope_assumptions.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement `generate_scope.py`**

`STANDARD_EXCLUSIONS` covers temporary power, trenching and backfill, concrete pads, access panels, and utility company work. For each, emit a `standard_exclusion` assumption only when no extracted scope statement addresses it. Wording starts from `api/app/plan/copy.py`'s existing four-field copy, re-pointed from "state it here as an answer" to "assumed, change it if wrong."

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_generate_scope_assumptions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/generate_scope.py api/tests/test_generate_scope_assumptions.py
git commit -m "feat: scope assumptions for exclusions no document addresses"
```

---

### Task 8: Assembly, qualifications, and the read endpoint

**Files:**
- Create: `api/app/estimate/assemble.py`, `api/app/estimate/schemas.py`, `api/app/estimate/router.py`
- Modify: `api/app/main.py` (register the router)
- Test: `api/tests/test_estimate_endpoint.py`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: `GET /api/projects/{project_id}/estimate` → `EstimateOut` with `direct_cost`, `range: {low, high}`, `sections: [{key, label, counted_count, assumed_count, lines: [{title, origin, basis, where, value, unit, amount}]}]`, `qualifications: [{title, where, excluded_value}]`, `excluded_value`, and `empty_reason: str | None` (set when the project has no countable items, null otherwise). A line that nothing could price carries `amount: null`, never `"0"` — the distinction Task 10 renders.

- [ ] **Step 1: Write the failing tests**

```python
def test_endpoint_returns_four_sections_in_order(client, project):
    keys = [s["key"] for s in client.get(url).json()["sections"]]
    assert keys == ["scope", "takeoff", "labor", "material"]

def test_every_line_carries_an_origin(client, project):
    for s in client.get(url).json()["sections"]:
        assert all(l["origin"] in ("counted", "assumed") for l in s["lines"])

def test_one_assumption_shared_by_forty_items_is_one_qualification(client, project_with_shared_ceiling_assumption):
    # Review Focus 5
    titles = [q["title"] for q in client.get(url).json()["qualifications"]]
    assert len([t for t in titles if "ceiling" in t.lower()]) == 1

def test_empty_project_renders_with_a_reason(client, project_with_no_items):
    # Review Focus 1
    body = client.get(url).json()
    assert body["direct_cost"] == "0"
    assert body["range"]["low"] == body["range"]["high"] == "0"
    assert body["empty_reason"]

def test_estimate_is_org_scoped(client_other_org, project):
    assert client_other_org.get(url).status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_estimate_endpoint.py -v`
Expected: FAIL, 404 — route not registered

- [ ] **Step 3: Implement assembly, schemas, and the route**

`assemble.py` reads through `rom_totals` and `excluded_item_ids`, groups assumptions by section, and dedupes the qualifications block on `(basis, title)` so one shared assumption yields one line. Ordering: scope exclusions first (they subtract), then by descending dollar exposure. The route follows `api/app/schedule/router.py`'s `load_project` org-scoping exactly.

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_estimate_endpoint.py api/tests/test_api_import_boundary.py -v`
Expected: PASS, including the import-boundary test

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/ api/app/main.py api/tests/test_estimate_endpoint.py
git commit -m "feat: ROM assembly, generated qualifications, and the estimate endpoint"
```

---

### Task 9: Generation runs in the worker

**Files:**
- Create: `api/app/worker/estimate_job.py`
- Modify: `api/app/worker/handlers.py`, `api/app/jobs/queue.py` (register the `estimate` kind), `api/app/worker/sheet_job.py` (enqueue on completion)
- Test: `api/tests/test_estimate_job.py`

**Interfaces:**
- Consumes: Tasks 5–7 generators, `validate_assumption`.
- Produces: job kind `estimate`, handler `run_estimate_job(db, job)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_job_writes_assumptions_for_every_section(db, processed_project):
    run_estimate_job(db, job_for(processed_project))
    sections = {a.section for a in db.query(Assumption).all()}
    assert sections == {"scope", "takeoff", "labor", "material"}

def test_rerun_replaces_engine_assumptions_without_duplicating(db, processed_project):
    run_estimate_job(db, job_for(processed_project))
    first = db.query(Assumption).count()
    run_estimate_job(db, job_for(processed_project))
    assert db.query(Assumption).count() == first

def test_job_refuses_an_invalid_assumption(db, processed_project, monkeypatch):
    monkeypatch.setattr("app.estimate.generate_scope.scope_assumptions",
                        lambda *_: [{"section": "scope", "title": "t"}])
    with pytest.raises(DomainError):
        run_estimate_job(db, job_for(processed_project))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_estimate_job.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement the job**

Queued by `sheet_job` when the last sheet of a run completes. Deletes this project's `source="engine"` assumptions and writes the fresh set in one transaction; every dict passes `validate_assumption` before it is written. `source="estimator"` rows are never touched — Task 11 tests that from the merge side.

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_estimate_job.py api/tests/test_api_import_boundary.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/estimate_job.py api/app/worker/handlers.py api/app/jobs/queue.py api/app/worker/sheet_job.py api/tests/test_estimate_job.py
git commit -m "feat: estimate job generates assumptions after a run completes"
```

---

### Task 10: The Estimate summary workspace

**Files:**
- Create: `src/components/estimate/EstimateSummary.jsx`, `src/components/estimate/EstimateSection.jsx`, `src/components/estimate/QualificationsBlock.jsx`, `src/components/estimate/useEstimate.js`, `src/components/estimate/estimateCopy.js`
- Modify: `src/routes.jsx:61` (add the route), `src/components/shell/ProjectNav.jsx:115` (`built: true`), `src/lib/store/api.js` (add `getEstimate`), `src/styles.css` (origin tag tokens)
- Test: `src/components/estimate/EstimateSummary.test.jsx`

**Interfaces:**
- Consumes: `GET /api/projects/{id}/estimate` from Task 8; `useWorkspaceContext()`.
- Produces: the routed `estimate` workspace.

- [ ] **Step 1: Write the failing tests**

```jsx
it("renders four sections in spec order", async () => { /* scope, takeoff, labor, material */ });
it("tags each line with a word, not colour alone", async () => {
  expect(await screen.findAllByText("Assumed")).not.toHaveLength(0);
});
it("shows the qualifications block built from the assumed lines", async () => {
  expect(await screen.findByText(/what this number assumes/i)).toBeInTheDocument();
});
it("never renders an approved-status pill", async () => {
  expect(screen.queryByText("Estimator approved")).not.toBeInTheDocument();
});
it("states the reason when the project is empty", async () => { /* Review Focus 1 */ });
it("renders an unpriced line blank, not as zero", async () => {
  const row = await screen.findByRole("row", { name: /unclassified/i });
  expect(within(row).queryByText("$0")).not.toBeInTheDocument();
  expect(within(row).getByText(/not priced/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -- src/components/estimate`
Expected: FAIL, cannot resolve `EstimateSummary.jsx`

- [ ] **Step 3: Build the workspace**

Mirror `docs/specs/assets/rom-mockup.html` structurally. `useEstimate.js` follows `useSchedule.js`'s shape — its own fetch, not the polled snapshot. New tokens in `styles.css` for the origin tags; reuse `--slate`/`--amber`, add no new hex. Assumed rows carry `border-left: 3px dashed var(--amber)`. `className="tabular"` on every amount.

- [ ] **Step 4: Run to verify they pass**

Run: `npm test -- src/components/estimate && npm run build`
Expected: PASS, build clean

- [ ] **Step 5: Commit**

```bash
git add src/components/estimate/ src/routes.jsx src/components/shell/ProjectNav.jsx src/lib/store/api.js src/styles.css
git commit -m "feat: Estimate summary workspace rendering the ROM"
```

---

### Task 11: A re-run never discards an estimator's override

**Files:**
- Modify: `api/app/takeoff/merge.py`
- Create: `api/app/estimate/override.py` (PATCH handler for one assumption)
- Modify: `api/app/estimate/router.py`
- Test: `api/tests/test_assumption_override.py`

**Interfaces:**
- Consumes: `Assumption`, `commit()` from `api/app/takeoff/actions.py`.
- Produces: `PATCH /api/assumptions/{id}` → `EstimateOut`; the override is one undoable `commit()` action.

- [ ] **Step 1: Write the failing tests**

```python
def test_override_flips_the_line_to_counted(client, assumption):
    body = client.patch(url, json={"value": "16", "unit": "ft"}).json()
    line = find_line(body, "ceiling")
    assert line["origin"] == "counted"
    assert "Entered by" in line["where"]

def test_override_survives_a_rerun(db, processed_project, assumption):
    override(assumption, value="16")
    run_estimate_job(db, job_for(processed_project))   # Review Focus 5
    assert db.get(Assumption, assumption.id).value == "16"
    assert db.get(Assumption, assumption.id).source == "estimator"

def test_override_is_undoable(client, assumption):
    client.patch(url, json={"value": "16"})
    client.post("/api/undo")
    assert client.get(estimate_url).json() == original

def test_override_is_attributed(db, assumption, user):
    override(assumption, value="16", user=user)
    assert db.get(Assumption, assumption.id).created_by_user_id == user.id
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_assumption_override.py -v`
Expected: FAIL, 404 — route not registered

- [ ] **Step 3: Implement the override and the merge guard**

The PATCH sets `value`, flips `source` to `estimator`, stamps `created_by_user_id`, and rewrites `where` to `Entered by <name>, <date>`; it routes through `commit()` as one undoable action. In `merge.py`, add the guard beside the approval-preserving logic: a run may delete and rewrite `source="engine"` assumptions and must leave `source="estimator"` untouched. Add a comment tying it to `CLAUDE.md`'s "the engine never discards a person's judgment."

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_assumption_override.py api/tests/test_merge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/override.py api/app/estimate/router.py api/app/takeoff/merge.py api/tests/test_assumption_override.py
git commit -m "feat: estimator override of an assumption, preserved across a re-run"
```

---

### Task 12: Widen the classifier's context and tag inference

**Files:**
- Modify: `api/app/engine/llm.py:94-96` (`_prompt`), `api/app/engine/context.py` (`PROMPT_BUDGET`)
- Modify: `api/app/engine/classification.py` (emit `inferred` on a context-named cluster)
- Test: `api/tests/test_classifier_context_budget.py`

**Interfaces:**
- Consumes: `BASIS["inferred"]` from Task 1.
- Produces: classification results carrying `basis="inferred"` where a cluster was named from context rather than matched.

This task is independently valuable and could ship on its own; it is last because nothing else depends on it.

- [ ] **Step 1: Write the failing tests**

```python
def test_schedule_text_is_no_longer_truncated_at_6000(monkeypatch):
    prompt = _prompt(tags=[{"tag": "F", "count": 47}], schedule_text="X" * 40000, location="IN")
    assert prompt.count("X") > 6000

def test_legend_text_reaches_the_prompt(monkeypatch):
    prompt = _prompt(tags=[...], schedule_text="...", location="IN", legend_text="F = 2x4 LED troffer")
    assert "2x4 LED troffer" in prompt

def test_a_cluster_named_from_context_is_tagged_inferred(fake_llm_naming_from_context):
    row = classify_run(...)[0]
    assert row["basis"] == "inferred"

def test_a_cluster_matched_to_a_legend_row_is_not_inferred(fake_llm_matching_legend):
    assert classify_run(...)[0].get("basis") != "inferred"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.enginevenv/bin/python -m pytest api/tests/test_classifier_context_budget.py -v`
Expected: FAIL on the truncation assertion

- [ ] **Step 3: Raise the budget and pass the legend through**

Replace the `[:6000]` slice in `_prompt` with the module's `PROMPT_BUDGET`, raised to a value sized for a full schedule set, and thread `legend_text` from `engine/legend.py` into `build_classifier_context`. Keep `_defang_block_headers` applied to every added block — more untrusted document text reaching the prompt makes that function more load-bearing, not less. Raise `max_tokens` on the classify call to match the larger answer.

- [ ] **Step 4: Run to verify they pass**

Run: `.enginevenv/bin/python -m pytest api/tests/test_classifier_context_budget.py api/tests/test_assistant_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suites and commit**

```bash
.enginevenv/bin/python -m pytest api/tests -q && npm test && npm run build
git add api/app/engine/ api/tests/test_classifier_context_budget.py
git commit -m "feat: give the classifier the legend and full schedules, tag inference as inferred"
```
