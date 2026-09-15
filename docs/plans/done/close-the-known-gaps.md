# Close the Known Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the correctness gaps and missing safety infrastructure carried forward from the three open PRs, so nothing already reviewed can silently regress.

**Architecture:** Six independent tasks. One adds the CI that has never existed and gates every suite in the repo. Two close real defects — a silent data loss on delete+undo, and an unaudited mutation path the design spec claims is audited. Three are cleanup that stops a future reader from acting on stale or unreachable code.

**Tech Stack:** GitHub Actions, Python (FastAPI, SQLAlchemy 2.0, Alembic, pytest), React 18 (Vitest).

**Branch:** cut a new branch from `feat/five-agents-basic` (the top of the open PR stack: #2 → #3 → #4). These fixes touch code introduced across all three PRs, so branching from the top is the only place they all exist together. They land as a fourth stacked PR.

## Global Constraints

- **Division 26 electrical only.**
- **The four review labels are closed:** `ready`, `attention`, `missing`, `approved`. Never a fifth.
- **Every warning is `{reason, title, found, why, fix, where}`** — four estimator-facing fields plus a closed-vocabulary `reason` (`scale`, `legend`, `schedule_conflict`).
- **The action log is append-only.** Undo writes a compensating action; it never deletes history.
- **Every mutation is attributable** — `by` and `at` on every action.
- **No estimator-facing copy** may mention model names, confidence numbers, "I think," or processing internals. Sentence case.
- **`undo_apply.py` is the most correctness-sensitive file in this codebase**, with a documented history of two silent bugs (item-doubling, approval-loss) and one near-miss. Changes to it get their own task and their own reasoning.

---

### Task 1: Run the tests on every push

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `vite.config.js`

**Interfaces:**
- Consumes: nothing. Produces: nothing importable — this is repository infrastructure.

There is no `.github/workflows/` directory. 597 backend tests and 495 frontend tests exist and **none of them run on a push or a pull request.** Three PRs are open whose green suites were verified once, by hand, on one machine.

Two stale worktrees under `.claude/worktrees/` contain full copies of the frontend suite, and `vitest` currently executes them alongside the real one — so a CI run would execute a phantom suite against stale code.

- [ ] **Step 1: Exclude the stale worktrees from vitest**

In `vite.config.js`, find the `test` config block and add an `exclude` that keeps the defaults and adds the worktree path. Read the existing block first — if it already has an `exclude`, extend it rather than replacing it:

```js
    exclude: ["**/node_modules/**", "**/dist/**", "**/.claude/worktrees/**"],
```

- [ ] **Step 2: Confirm the phantom suite is gone**

Run: `npm test -- --run 2>&1 | tail -4`
Expected: the file count drops from 72 to the number of real suites, and the run no longer lists any path under `.claude/worktrees/`. Record both counts in your report — if the count does not change, the worktrees were not being picked up on this checkout and you should say so rather than assuming.

- [ ] **Step 3: Write the workflow**

Create `.github/workflows/ci.yml`. The backend suite needs Postgres; `api/tests/conftest.py` requires both `DATABASE_URL` and `TEST_DATABASE_URL`, and the host venv in this project uses psycopg v3, so the URL scheme is `postgresql+psycopg://`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: takeoff
          POSTGRES_PASSWORD: takeoff
          POSTGRES_DB: takeoff
        options: >-
          --health-cmd "pg_isready -U takeoff"
          --health-interval 3s --health-timeout 3s --health-retries 20
        ports: ["5432:5432"]
    env:
      DATABASE_URL: postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff
      TEST_DATABASE_URL: postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        working-directory: api
        run: pip install -r requirements.txt
      - name: Run migrations
        working-directory: api
        run: alembic upgrade head
      - name: Run tests
        working-directory: api
        run: pytest -q

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
      - run: npm ci
      - run: npm test -- --run
      - run: npm run build
```

**Note on the migration step.** The backend test suite builds its schema from `Base.metadata`, not from the migration chain — so `pytest` passing has never proven the migrations apply. Running `alembic upgrade head` here is deliberate: it makes CI the first thing in this project that ever checks them.

- [ ] **Step 4: Verify the workflow parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('valid')"`
Expected: `valid`

You cannot execute the workflow locally. Instead, verify each command it runs works on this checkout, and report the result of each:
- `cd api && alembic upgrade head` (against the running docker Postgres)
- `docker compose exec -T api pytest -q`
- `npm test -- --run` and `npm run build`

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml vite.config.js
git commit -m "Run the test suites on every push"
```

---

### Task 2: Delete and undo must not lose a typed price

**Files:**
- Modify: `api/app/takeoff/undo_apply.py`
- Modify: `api/app/takeoff/review.py` (wherever `delete_item()` builds its snapshot — find it by searching for the function, not by line number)
- Modify: `api/app/takeoff/snapshots.py`
- Test: `api/tests/test_undo_redo.py`

**Interfaces:**
- Consumes: `LABOR_LINE_SNAPSHOT_TYPES` and `MATERIAL_PRICE_SNAPSHOT_TYPES`, already in `snapshots.py`.
- Produces: no new public function. `delete_item()`'s `before` snapshot gains two optional keys; `_apply_delete` reads them.

`ProjectLaborLine` and `ProjectMaterialPrice` both declare `ForeignKey("items.id", ondelete="CASCADE")`, so deleting an item destroys its pricing overrides in the database. `_apply_delete` restores the item's own columns and its warnings from the snapshot, but never captured the pricing rows — so **undoing a delete brings the item back with an estimator's typed price silently gone.**

This is the third defect found in this file. Read its module docstring before you start: it records the two that shipped, and why each was invisible.

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_undo_redo.py`. Match the file's existing fixtures and helper style — read a neighbouring delete/undo test first and follow it rather than inventing a new setup:

```python
def test_undoing_a_delete_restores_a_typed_price(client, db, project, item, signed_in_user):
    """ProjectLaborLine and ProjectMaterialPrice cascade on item delete, so
    without capturing them in the delete snapshot an estimator's own typed
    figures are destroyed by a delete and never come back. The item returns
    priced at nothing, which reads as a real answer rather than a loss."""
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 1.25})
    client.patch(f"/api/items/{item.id}/material-price",
                 json={"priceOverride": 42.5, "source": "project_price"})

    client.delete(f"/api/items/{item.id}")
    client.post(f"/api/projects/{project.id}/undo")

    db.expire_all()
    labor = db.get(ProjectLaborLine, item.id)
    price = db.get(ProjectMaterialPrice, item.id)
    assert labor is not None and float(labor.hours_override) == 1.25
    assert price is not None and float(price.price_override) == 42.5
```

Import `ProjectLaborLine` and `ProjectMaterialPrice` from `app.takeoff.models` at the top of the file if they are not already imported.

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_undo_redo.py::test_undoing_a_delete_restores_a_typed_price -v --no-header`
Expected: FAIL — `labor is not None` is False, because the row cascaded away and nothing restored it.

If it unexpectedly passes, stop and report: something already restores these and the finding is wrong.

- [ ] **Step 3: Capture the pricing rows in the delete snapshot**

Find `delete_item()` (search `api/app/takeoff/` for `def delete_item`). It builds a `before` dict holding the item's column snapshot plus its warnings. Add the two pricing rows alongside, using the same `encode_snapshot` treatment the item columns already get — both tables carry `Decimal`, `UUID` and `datetime` columns that `json.dumps` cannot serialize:

```python
    # Both cascade on the item's delete, so if they are not captured here
    # they cannot be restored by any later undo -- the item comes back
    # priced at nothing, which reads as an answer rather than a loss.
```

Store them under stable keys (`"labor_line"`, `"material_price"`), each either the encoded column dict or `None` when the row does not exist.

- [ ] **Step 4: Restore them in `_apply_delete`**

In `_apply_delete`, where the item and its warnings are recreated on the undo direction, recreate the two pricing rows from those keys when present, decoding with `LABOR_LINE_SNAPSHOT_TYPES` and `MATERIAL_PRICE_SNAPSHOT_TYPES`.

**Two things this file's history says to get right:**
- The redo direction deletes the item again; the cascade handles the pricing rows, so redo needs no explicit deletion. Confirm that by reading the code rather than assuming.
- An action recorded *before* this change has no `"labor_line"` key. Reading it must not raise — use `.get()`, and treat absent as "there was none."

- [ ] **Step 5: Run the test and the full suite**

Run: `docker compose exec -T api pytest tests/test_undo_redo.py -v --no-header`
Expected: PASS, including every pre-existing test in the file.

Then: `docker compose exec -T api pytest -q`
Expected: no regressions against the current baseline. Record the baseline before you start and report both numbers.

- [ ] **Step 6: Verify the guard is load-bearing**

Temporarily revert Step 4's restore, confirm the new test fails, restore it. Report what you saw — this file's history is exactly why that check is not optional.

- [ ] **Step 7: Commit**

```bash
git add api/app/takeoff/undo_apply.py api/app/takeoff/review.py api/tests/test_undo_redo.py
git commit -m "Restore a typed price when a delete is undone"
```

---

### Task 3: Audit the company pricing edits

**Files:**
- Create: `api/migrations/versions/<next>_company_action_log.py`
- Modify: `api/app/takeoff/models.py`
- Modify: `api/app/takeoff/pricing_router.py`
- Test: `api/tests/test_pricing_endpoints.py`

**Interfaces:**
- Produces: a `CompanyAction` model and a `record_company_action(db, *, actor, kind, label, before, after)` helper. Nothing else imports them yet.

Six company-scoped routes in `pricing_router.py` change org-wide pricing — labour rates, material prices, labour-hour overrides — and none of them record anything. Only `updated_by_user_id` and `updated_at` survive on the row itself, so there is no history: who changed the journeyman rate last month, and from what, is unanswerable. The design spec says these edits are logged.

**The decision this task makes, and why.** `Action.project_id` is a non-nullable `ForeignKey("projects.id")`, so a company edit has no home in the existing log. Three options were weighed:

1. *Make `project_id` nullable and add `org_id`.* Rejected. `undo.py` and `undo_apply.py` filter the action log by `project_id` and depend on a partial unique index over `undoes_action_id`; loosening the column that scopes all of it, in the file this codebase has been bitten by twice, is a large risk for a logging feature.
2. *Leave attribution-only and amend the spec.* Rejected. The action log is the compliance record and the firm's defence when a bid is challenged; a pricing change that moves every total in a project is exactly what an auditor asks about.
3. **A separate `company_actions` table.** Taken. Company edits are genuinely a different scope — org-level settings, never undoable, never part of a project's history — and keeping them out of the project log means `undo` cannot accidentally see them at all.

The cost is real and should be recorded rather than glossed: the compliance record now lives in two tables, and anyone auditing has to know to read both. State that in the model's docstring.

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_pricing_endpoints.py`:

```python
def test_a_company_rate_change_is_recorded(client, db, org, signed_in_user):
    """Attribution on the row says who touched it last; it cannot say what
    the rate was before, or that it changed twice. A pricing change moves
    every total on every project in the org, which is the kind of change an
    audit asks about."""
    from app.takeoff.models import CompanyAction

    client.put("/api/company/labor-rates", json={
        "journeymanRate": 68, "foremanRate": 82, "apprenticeRate": 41, "productivityFactor": 1.0})
    client.put("/api/company/labor-rates", json={
        "journeymanRate": 72, "foremanRate": 82, "apprenticeRate": 41, "productivityFactor": 1.0})

    rows = db.query(CompanyAction).filter(CompanyAction.org_id == org.id).order_by(CompanyAction.seq).all()
    assert len(rows) == 2
    assert rows[1].before["journeyman_rate"] == "68.00"
    assert rows[1].after["journeyman_rate"] == "72.00"
    assert rows[1].actor_user_id == signed_in_user.id
```

Check the fixtures this file already uses — if `org` or `signed_in_user` is named differently, follow the file rather than this snippet, and say so in your report.

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_pricing_endpoints.py::test_a_company_rate_change_is_recorded -v --no-header`
Expected: FAIL with `ImportError` or `AttributeError` — `CompanyAction` does not exist.

- [ ] **Step 3: Add the model**

In `api/app/takeoff/models.py`, alongside the other pricing tables:

```python
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
```

Check the imports at the top of `models.py` and the exact name of the orgs table before writing this — `ForeignKey("orgs.id")` must match reality.

- [ ] **Step 4: Write the migration**

Generate it against the running database, then read the generated file before trusting it:

```bash
docker compose exec -T api alembic revision --autogenerate -m "company action log"
```

Verify it creates only `company_actions` and drops nothing. Then verify the chain applies and reverses cleanly:

```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api alembic downgrade -1
docker compose exec -T api alembic upgrade head
```

Report the output of all three. A migration that cannot reverse is a migration nobody can back out.

- [ ] **Step 5: Record from the six routes**

Add a small helper in `pricing_router.py` and call it from each of the six company routes (`PUT /company/labor-rates`, `PUT`/`DELETE /company/material-prices/{item_name}`, `PUT`/`DELETE /company/labor-hours-overrides/{item_name}`). Use the existing `_snapshot()` helper for before/after — it already applies `encode_snapshot`, which these tables need for their `Decimal` and `datetime` columns.

The two `GET` routes record nothing. A read is not a change.

Write the `label` in the product's own voice — "Changed the journeyman rate", not "PUT /company/labor-rates". It is estimator-facing text and the language rules apply.

- [ ] **Step 6: Run the test and the full suite**

Run: `docker compose exec -T api pytest tests/test_pricing_endpoints.py -v --no-header`, then `docker compose exec -T api pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 7: Confirm undo cannot see these rows**

Run the undo/redo suite: `docker compose exec -T api pytest tests/test_undo_redo.py -q`
Expected: unchanged. Also confirm by reading that no query in `undo.py` or `undo_apply.py` touches `company_actions`. Report both.

- [ ] **Step 8: Commit**

```bash
git add api/app/takeoff/models.py api/app/takeoff/pricing_router.py api/migrations/versions/ api/tests/test_pricing_endpoints.py
git commit -m "Record an org-level pricing change in an audit log"
```

---

### Task 4: Resolve the unreachable assembly entries

**Files:**
- Modify: `api/app/engine/assemblies.py`
- Test: `api/tests/test_engine_assemblies.py`

**Interfaces:** no signature changes.

`ASSEMBLIES` holds `luminaire_troffer` and `luminaire_highbay`, and nothing can reach either: no value in `TAG_TO_CATALOG` names them, and every fixture-type letter routes to `luminaire_generic`. They are currently byte-identical to `luminaire_generic`, which makes the duplication harmless but the deadness invisible.

Unreachable pricing data is how a future change edits the wrong table and sees no effect.

- [ ] **Step 1: Confirm they are still unreachable**

```bash
cd api && ../.enginevenv/bin/python -c "
from app.engine.assemblies import ASSEMBLIES
from app.engine.catalog import TAG_TO_CATALOG
reachable = set(TAG_TO_CATALOG.values()) | {'luminaire_generic'}
print(sorted(set(ASSEMBLIES) - reachable))
"
```
Expected: `['luminaire_highbay', 'luminaire_troffer']`. If the list differs, report it — something changed and the rest of this task needs rethinking.

- [ ] **Step 2: Delete the two entries, and say why in a comment**

Remove both from `ASSEMBLIES`. They are recoverable from git the moment a real path produces those ids, and a wrong-but-plausible row that nothing reads is worse than an absence. Leave a comment where they were:

```python
    # luminaire_troffer and luminaire_highbay are deliberately absent.
    # Classification routes every fixture-type letter to luminaire_generic,
    # so nothing can reach a more specific luminaire id; entries for them
    # were unreachable and identical to the generic one. Add them back the
    # day something resolves a specific fixture -- an unreachable row is a
    # table a future change edits with no effect.
```

- [ ] **Step 3: Assert the invariant rather than the instances**

The existing `test_every_catalog_device_that_gets_installed_has_an_assembly` checks coverage in one direction. Add the other:

```python
def test_no_assembly_is_unreachable():
    """An assembly nothing can resolve to is a table a future change edits
    with no effect -- the failure mode that hid luminaire_generic being
    priced bare for an entire plan."""
    from app.engine.catalog import TAG_TO_CATALOG
    reachable = set(TAG_TO_CATALOG.values()) | {"luminaire_generic"}
    assert set(ASSEMBLIES) <= reachable, f"unreachable: {sorted(set(ASSEMBLIES) - reachable)}"
```

- [ ] **Step 4: Run the engine suite**

Run: `docker compose exec -T api pytest tests/test_engine_assemblies.py tests/test_engine_pricing.py -v --no-header`
Expected: PASS. The real-set total must not move — nothing reached those entries. Confirm with the CLI and report the figure.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/assemblies.py api/tests/test_engine_assemblies.py
git commit -m "Drop two assembly entries nothing can reach"
```

---

### Task 5: Name the sheet a legend definition came from

**Files:**
- Modify: `api/app/engine/classification.py`
- Test: `api/tests/test_engine_classify.py`

**Interfaces:**
- Consumes: `LegendEntry.page_index`, already populated by `documents.py` and currently read by nothing.

`LegendEntry` carries `page_index` and no consumer uses it, so both legend-derived warnings end their `where` field with "and the legend sheet" — unnamed. A warning's `where` is contractually *which sheet holds the evidence*, and on a 14-sheet set "the legend sheet" sends an estimator looking.

- [ ] **Step 1: Write the failing test**

```python
def test_a_legend_warning_names_the_sheet_the_definition_came_from():
    """`where` is contractually which sheet holds the evidence. LegendEntry
    already carries page_index; without using it the warning says "the
    legend sheet" and an estimator on a 14-sheet set has to go hunting."""
    sheets = [
        _sheet(page_index=0, number="E0.1", legend=[LegendEntry("CKT", "CIRCUIT", "abbreviation", page_index=0)]),
        _sheet(page_index=1, number="E2.1", legend=[]),
    ]
    clusters = [DeviceCluster(tag="CKT", sheet_page_index=1, placements=[Placement(1, 1)] * 3)]
    items = classify(clusters, sheets)
    assert "E0.1" in items[0].warning["where"]
```

Use the file's existing sheet/cluster helpers — read a neighbouring test and follow its construction rather than inventing `_sheet` if it does not exist.

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_engine_classify.py -k names_the_sheet -v --no-header`
Expected: FAIL — `where` says "the legend sheet".

- [ ] **Step 3: Carry the source sheet through**

`classify()` builds `abbrev` as `symbol -> description`. Widen it to carry the defining sheet's number alongside the description, keeping the existing **first-wins** behaviour (a `setdefault` over sheets in order — a later sheet's mis-parse must not overwrite a real definition; that fix already exists and must not regress). Then use the number in both `_modifier_warning` and `_ambiguous_tag_warning`'s `where`.

Where a definition's sheet cannot be determined, keep the current generic wording rather than naming a wrong sheet.

- [ ] **Step 4: Run the suite**

Run: `docker compose exec -T api pytest tests/test_engine_classify.py -v --no-header`, then the full suite.
Expected: PASS, no regressions. The first-wins test must still pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/classification.py api/tests/test_engine_classify.py
git commit -m "Name the sheet a legend definition came from"
```

---

### Task 6: Correct the stale documents

**Files:**
- Modify: `docs/specs/grounded-classification-warnings.md`
- Modify: `CLAUDE.md`

**Interfaces:** documentation only, no code.

Two documents describe behaviour that no longer exists. Both are read by the next person before they touch this code.

- [ ] **Step 1: Correct the grounded-warnings spec**

Three places in that spec describe what shipped before the final review changed it. Read the file and reconcile each against the current code in `llm.py`, `estimate.py`, `ingest.py`, and `ItemDetailPanel.jsx`:

- Section A's JSON block still shows the model returning a five-field warning including `found` and `where`. The model is now asked for three fields; `found` and `where` are synthesized per cluster.
- Section B says the sheet-reference check runs over `found` and `where`. It runs over all five fields.
- Section C specifies `where` styled like the "View evidence" link. That treatment was removed — it is now a muted italic citation, because blue on a warning card read as clickable when it is not.

Correct each to describe the code as it stands. Where the change was deliberate, say so briefly — the spec's value is that it explains why, not just what.

- [ ] **Step 2: Correct CLAUDE.md's scope limits**

Its "Known scope limits" section still lists Labor and Material pricing as disabled and unbuilt in the project nav. Both are built, routed, and now carry the pricing basis note. Update that paragraph to match, and leave the genuinely-unbuilt entries (Assemblies, Estimate summary, Revisions, Final review) alone.

- [ ] **Step 3: Verify no other document contradicts the code**

Search the docs for claims about the three areas this plan touched:

```bash
grep -rn "not built\|unbuilt\|disabled" CLAUDE.md README.md ROADMAP.md | grep -i "labor\|material\|pricing"
```

Report anything you find that is now false. Fix it if it is a one-line claim; report it rather than rewriting if it is a whole section.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/grounded-classification-warnings.md CLAUDE.md
git commit -m "Correct two documents that describe behaviour that changed"
```

---

## Not in this plan

- **The sheet-number tie-break in `documents.py:83`** is being fixed in a separate session. Do not touch it here; a concurrent edit to the same function is how a merge conflict becomes a silent revert.
- **`ExportPreview`'s dead `pricingSource` and `laborRate` fields.** They have never rendered on any path. Making them appear is a copy decision, not a bug fix — and on a deterministic project the sentence they would print ("Priced automatically for the location") is false. Needs a product call first.
- **Geometry-based counting, the project symbol library, and the unbuilt pricing UI** (crew-mix editor, filter chips, company hours-override screen). Each needs its own spec.

## Self-Review

**Spec coverage:** every item from the agreed inventory maps to a task — CI and the vitest exclusion to Task 1, delete+undo to Task 2, company audit to Task 3, dead assemblies to Task 4, `page_index` to Task 5, stale docs to Task 6. The three excluded items are named above with reasons.

**Placeholder scan:** no TBDs. Every step carries real commands, real code, and real expected output. Task 3's migration filename is intentionally left as `<next>` because Alembic generates it.

**Type consistency:** `CompanyAction` is defined once (Task 3, Step 3) and used only in that task's test. `LegendEntry.page_index` (Task 5) already exists from earlier work. No task references a symbol another task creates, so the six are genuinely independent and can be reviewed in any order.

**One risk worth naming:** Task 2 touches `undo_apply.py`, and both prior bugs in that file were silent. Step 6's mutation check is not optional there — it is the only thing that distinguishes a real fix from a test that would pass either way.
