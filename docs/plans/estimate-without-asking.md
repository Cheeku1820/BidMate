# Estimate without asking — slice 2 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Where the engine counted nothing, write a real guessed takeoff line that carries money and discloses itself, and give every line a 1–10 confidence an estimator can sort and check.

**Architecture:** A pure `confidence.py` scores every line from a named method plus named adjustments. A new `estimate/complete.py` writes `Item` rows with `origin = "assumed"` for work never counted, each paired with an `Assumption` disclosure through the generator list `estimate/write.py` already walks. Completion gets its **own** write path rather than `takeoff/merge.py`, because merge keys on `(sheet_number, source_tag)` and a synthetic tag there would fabricate a symbol cluster.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + pytest (`cd api && ../.enginevenv/bin/python -m pytest -q`); React 18 + plain CSS tokens + vitest (`npm test -- --run`, `npm run build`).

**Spec:** [`docs/specs/estimate-without-asking.md`](../specs/estimate-without-asking.md). Read it first; every decision below comes from it.

> **Tasks 5 and 6 are superseded and must be rewritten before
> implementation starts.** They were written when "a sheet that could
> not be read" was the leading gap. The estimator's read is that reading
> is reliable and the real gaps are **unidentified symbols, unresolved
> scale, and undercounting** — so the spec now carries five cases in a
> different order, and every guessed quantity is relative to what the
> project itself counted rather than an absolute constant. Tasks 1–4 and
> 7–10 stand. Rewrite 5 and 6 into five tasks against the spec's current
> case list, after a real bid set has been through the merged ROM, since
> that run is what fixes the starting numbers and confirms the ordering.

## Global Constraints

- **Four review labels, never a fifth.** A guessed line's status is `ready`; "Guessed" is the `origin` axis, not a label.
- **Origin colours are `--slate` (counted) / `--plum` (assumed).** Never `--amber`, `--blue`, `--red`, `--green`. `src/components/estimate/originColors.test.js` holds this line and must keep passing.
- **Nothing unapproved scores above 9.** 10 means a person checked it.
- **Money comes from `totals.resolved_lines()`**, never `Item`'s stored cost columns.
- **No approval is ever written by code.** Completion lines are `ready`, never `approved`.
- **Confidence renders** — this slice amends `CLAUDE.md` and ROADMAP invariant 7 deliberately (Task 10). Until that task lands the docs and the code disagree; land it in the same branch.
- **Sentence case, no "successfully", no model names, no confidence *percentages*.** A 1–10 meter is not a percentage.
- Migration head is `0032_assumption_origin`. New migration is `0033`.

## Review Focus

Input classes the spec implies but no task's happy path exercises. Each has its test added to the owning task.

1. **A project with no sheets and no items** — completion must return nothing, not invent a building. (Task 5)
2. **An unresolvable building type** — case 2 must skip silently and say so, never guess a baseline. (Task 6)
3. **A re-run after a person approved a guessed line** — must neither duplicate it nor overwrite the approval. (Task 7)
4. **A guessed line a person deleted** — a re-run must not resurrect it. (Task 7)
5. **Items predating this slice, with null confidence** — the bar renders empty and sorting puts them last; nothing throws. (Task 9)

---

### Task 1: The confidence scale

**Files:**
- Create: `api/app/takeoff/confidence.py`
- Test: `api/tests/test_confidence.py`

**Interfaces:**
- Produces: `BASE_SCORES: dict[str, int]`, `ADJUSTMENTS: dict[str, int]`, and
  `score(method: str, adjustments: Sequence[str] = (), *, approved: bool = False) -> tuple[int, list[str]]`
  returning the clamped score and the human-readable reasons that produced it.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_counted_line_matched_to_a_schedule_scores_nine():
    assert score("counted_matched")[0] == 9

def test_a_class_average_for_a_whole_missing_system_scores_two():
    assert score("class_average_system")[0] == 2

def test_corroboration_raises_and_disagreement_lowers():
    assert score("counted_high", ["corroborated"])[0] == 9
    assert score("counted_high", ["sources_disagree"])[0] == 7

def test_nothing_unapproved_reaches_ten():
    assert score("counted_matched", ["corroborated", "corroborated"])[0] == 9

def test_an_approved_line_is_ten_whatever_it_was():
    assert score("class_average_system", approved=True)[0] == 10

def test_the_floor_is_one():
    assert score("class_average_system",
                 ["sources_disagree", "partial_page", "not_in_legend"])[0] == 1

def test_every_score_names_its_reasons():
    _, reasons = score("measured_unconfirmed", ["not_in_legend"])
    assert any("scale" in r.lower() for r in reasons)
    assert any("legend" in r.lower() for r in reasons)

def test_an_unknown_method_is_refused():
    with pytest.raises(KeyError):
        score("vibes")

def test_base_scores_follow_the_basis_spreads():
    """Invariant 2 in the spec: a 9 beside a +/-25% band would be two
    parts of the product disagreeing about one fact."""
    from app.estimate.basis import BASIS
    assert BASE_SCORES["firm_rule"] > BASE_SCORES["class_average_sheet"]
    assert BASIS["rule_of_thumb"].spread >= BASIS["class_average"].spread
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_confidence.py -q`
Expected: FAIL, no module named `app.takeoff.confidence`

- [ ] **Step 3: Implement `confidence.py`**

`BASE_SCORES` keys and values exactly as the spec's table: `counted_matched` 9, `counted_high` 8, `schedule_read` 8, `measured_confirmed` 7, `counted_uncertain` 6, `firm_rule` 5, `measured_unconfirmed` 4, `class_average_sheet` 3, `class_average_system` 2. `ADJUSTMENTS`: `corroborated` +1, `sources_disagree` −1, `partial_page` −1, `not_in_legend` −1. One module-level comment block recording that these are expected to move and are deliberately one editable table — per the spec, the estimator asked for them to be changeable later.

Clamp to 1..9, then `approved` overrides to 10. Each applied base and adjustment appends one estimator-facing sentence to `reasons`; no model names, no percentages.

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_confidence.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/confidence.py api/tests/test_confidence.py
git commit -m "feat: the 1-10 confidence scale, as a sum of named reasons"
```

---

### Task 2: Columns and migration

**Files:**
- Modify: `api/app/takeoff/models.py` (`Item`, `Project`)
- Create: `api/migrations/versions/0033_item_origin_and_confidence.py`
- Test: `api/tests/test_migrations.py` (extend existing), `api/tests/test_models.py`

**Interfaces:**
- Produces: `Item.origin: str` (`"counted"` default), `Item.confidence: int | None`, `Item.confidence_reasons: list | None`, `Project.building_type: str | None`, `Project.building_type_source: str | None` (`"inferred"` / `"estimator"`).

- [ ] **Step 1: Write the failing tests**

```python
def test_an_item_defaults_to_counted(db, project, sheet):
    item = make_item(db, project, sheet)
    assert item.origin == "counted"
    assert item.confidence is None

def test_an_unrecognized_origin_is_refused(db, project, sheet):
    with pytest.raises(IntegrityError):
        make_item(db, project, sheet, origin="maybe"); db.flush()

def test_an_unrecognized_building_type_source_is_refused(db, project):
    with pytest.raises(IntegrityError):
        project.building_type_source = "hunch"; db.flush()

def test_building_type_is_optional(db, project):
    assert project.building_type is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_models.py -q -k "origin or building_type"`
Expected: FAIL, unknown attribute

- [ ] **Step 3: Add the columns and write migration `0033`**

`down_revision = "0032"`. `items.origin` `String(20)`, not null, `server_default="counted"`, with `ck_items_origin` over `basis.ORIGINS`. `items.confidence` `SmallInteger` nullable. `items.confidence_reasons` `JSONB` nullable. `projects.building_type` `String(100)` nullable, `projects.building_type_source` `String(20)` nullable with `ck_projects_building_type_source` over `("inferred", "estimator")`. No backfill: existing rows are genuinely `counted` with unknown confidence, and the spec requires null to render empty rather than be invented.

Mirror the comment style of `0032_assumption_origin.py`, recording why `origin` is stored rather than derived.

- [ ] **Step 4: Run the suite and apply the migration**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_models.py tests/test_migrations.py -q`
Expected: PASS
Run: `docker compose run --rm api alembic upgrade head`
Expected: `0033` applied, no error

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/models.py api/migrations/versions/0033_item_origin_and_confidence.py api/tests/
git commit -m "feat: item origin and confidence columns, project building type"
```

---

### Task 3: Counted lines carry a confidence

**Files:**
- Modify: `api/app/engine/rows.py:186`, `api/app/takeoff/merge.py` (`_overwrite`, `_changes_visibly`)
- Test: `api/tests/test_rows.py`, `api/tests/test_merge.py`

**Interfaces:**
- Consumes: `confidence.score` (Task 1), `Item.confidence` (Task 2).
- Produces: engine row dicts gaining `"confidence": int` and `"confidence_reasons": list[str]`; `merge_sheet` persisting both.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_legend_matched_row_scores_nine():
    row = build_row(spec={"confidence": "high"}, classification_basis=None, ...)
    assert row["confidence"] == 9

def test_a_row_named_from_context_scores_lower_than_a_matched_one():
    assert build_row(..., classification_basis="inferred")["confidence"] < 9

def test_a_low_confidence_row_keeps_its_attention_status_and_scores_six():
    row = build_row(spec={"confidence": "low"}, ...)
    assert row["status"] == "attention" and row["confidence"] == 6

def test_merge_persists_the_confidence_and_its_reasons(db, project, sheet):
    merge_sheet(db, project=project, sheet=sheet, rows=[row], ai_reading=True)
    item = db.scalars(select(Item)).one()
    assert item.confidence == 9 and item.confidence_reasons
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_rows.py tests/test_merge.py -q -k confidence`
Expected: FAIL, KeyError `'confidence'`

- [ ] **Step 3: Map the engine's inputs to a method and score the row**

In `rows.py`, immediately after the existing `status` line, derive the method: `classification_basis == "inferred"` → `counted_uncertain`; `spec["confidence"] == "high"` with a legend match → `counted_matched`; `"high"` without → `counted_high`; otherwise `counted_uncertain`. Pass `not_in_legend` as an adjustment when the cluster's tag had no legend row. Leave `status` exactly as it is — this task adds a channel, it does not change routing.

In `merge.py`, carry both fields in `_overwrite` and add `confidence` to `_changes_visibly` so a score change alone does not count as a visible change (it is not estimator-facing news on its own).

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_rows.py tests/test_merge.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/rows.py api/app/takeoff/merge.py api/tests/
git commit -m "feat: every counted line carries a confidence and its reasons"
```

---

### Task 4: Building type, inferred from what was read

**Files:**
- Create: `api/app/estimate/building_type.py`
- Test: `api/tests/test_building_type.py`

**Interfaces:**
- Produces: `TYPES: tuple[str, ...]` and
  `infer_building_type(db: DbSession, project: Project) -> tuple[str | None, str] | None`
  returning `(type, evidence_sentence)`, or `None` when nothing supports a call.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_school_set_is_inferred_from_sheet_titles(db, project):
    add_sheet(db, project, number="E-1.0", title="Classroom wing power plan")
    assert infer_building_type(db, project)[0] == "school"

def test_an_estimators_own_choice_is_never_overwritten(db, project):
    project.building_type, project.building_type_source = "warehouse", "estimator"
    assert infer_building_type(db, project) is None

def test_nothing_to_go_on_returns_none(db, project):
    assert infer_building_type(db, project) is None

def test_the_evidence_names_where_it_came_from(db, project):
    add_sheet(db, project, number="E-1.0", title="Patient room power plan")
    kind, evidence = infer_building_type(db, project)
    assert kind == "healthcare" and "E-1.0" in evidence

def test_conflicting_signals_return_none_rather_than_the_loudest(db, project):
    add_sheet(db, project, number="E-1.0", title="Classroom wing")
    add_sheet(db, project, number="E-2.0", title="Patient room")
    assert infer_building_type(db, project) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_building_type.py -q`
Expected: FAIL, no module

- [ ] **Step 3: Implement deterministic inference over stored text**

Read `Sheet.number`, `Sheet.title`, `Sheet.schedule_text`, and `ScopeStatement.text` — all already stored by the read job, so this opens no file and is API-safe. Keyword sets per type in one table, same shape as `StandardExclusion.vocabulary`. Deliberately **not** a language call: one classifier, and a deterministic guess that returns `None` under conflict is honest where a model's tiebreak would not be. Return `None` when `building_type_source == "estimator"`, when nothing matches, or when two types tie.

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_building_type.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/building_type.py api/tests/test_building_type.py
git commit -m "feat: infer the building type from what the read job stored"
```

---

### Task 5: Completion case 1 — a sheet that produced nothing

**Files:**
- Create: `api/app/estimate/complete.py`, `api/app/estimate/complete_copy.py`
- Test: `api/tests/test_complete.py`

**Interfaces:**
- Consumes: `confidence.score`, `Item.origin`.
- Produces: `completion_lines(db: DbSession, project: Project) -> list[dict]` — each dict carrying `sheet_id`, `subject_kind` (`"sheet"` or `"system"`), `name`, `system`, `category`, `quantity`, `unit`, `origin="assumed"`, `confidence`, `confidence_reasons`, `basis`, and the four disclosure fields (`found`, `why`, `fix`, `where`). `subject_kind` is what Task 6 filters on and what the paired `Assumption` row carries.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_plan_sheet_with_no_items_gets_a_guessed_line(db, project):
    sheet = add_sheet(db, project, number="E-2.3", kind="plan", render_status="failed")
    [line] = completion_lines(db, project)
    assert line["sheet_id"] == sheet.id and line["origin"] == "assumed"
    assert line["basis"] == "class_average"
    assert line["confidence"] == 3

def test_a_schedule_sheet_with_no_items_is_not_completed(db, project):
    add_sheet(db, project, number="E-501", kind="schedule")
    assert completion_lines(db, project) == []

def test_a_plan_sheet_that_counted_items_is_left_alone(db, project, sheet):
    make_item(db, project, sheet)
    assert completion_lines(db, project) == []

def test_the_disclosure_names_the_sheet_and_answers_four_questions(db, project):
    add_sheet(db, project, number="E-2.3", kind="plan", render_status="failed")
    [line] = completion_lines(db, project)
    assert all(line[f] for f in ("found", "why", "fix", "where"))
    assert "E-2.3" in line["found"]

def test_a_project_with_no_sheets_completes_nothing(db, project):
    """Review focus 1: no sheets must mean no guesses, not a guessed building."""
    assert completion_lines(db, project) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_complete.py -q`
Expected: FAIL, no module

- [ ] **Step 3: Implement case 1**

Select sheets where `sheet_kind == "plan"` that own no rows in `countable_items`. Quantity from a per-sheet device allowance held as one named constant in `complete.py` with its reasoning beside it (the spec leaves the figure to the builder; make it one editable number, not a literal in a loop). `complete_copy.py` holds every estimator-facing sentence, in the shape of `estimate/copy.py`. Method `class_average_sheet`; add `partial_page` when `render_status == "failed"`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_complete.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/complete.py api/app/estimate/complete_copy.py api/tests/test_complete.py
git commit -m "feat: a sheet that produced nothing gets a guessed line, not silence"
```

---

### Task 6: Completion case 2 — a system never found

**Files:**
- Modify: `api/app/estimate/complete.py`, `api/app/estimate/complete_copy.py`
- Test: `api/tests/test_complete.py`

**Interfaces:**
- Consumes: `infer_building_type` (Task 4).
- Produces: `completion_lines` additionally returning system-level rows, each with `basis="class_average"` and `confidence == 2`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_school_with_no_fire_alarm_gets_a_guessed_allowance(db, project):
    project.building_type, project.building_type_source = "school", "estimator"
    add_sheet(db, project, number="E-1.0", kind="plan")
    make_item(db, project, sheet, system="Power")
    lines = [l for l in completion_lines(db, project) if l["system"] == "Fire alarm"]
    assert lines and lines[0]["confidence"] == 2

def test_a_system_already_counted_is_not_guessed(db, project, sheet):
    make_item(db, project, sheet, system="Fire alarm")
    assert not [l for l in completion_lines(db, project) if l["system"] == "Fire alarm"]

def test_an_unknown_building_type_skips_system_completion(db, project):
    """Review focus 2: never guess a baseline for an unknown building."""
    add_sheet(db, project, number="E-1.0", kind="plan")
    make_item(db, project, sheet, system="Power")
    assert all(l["subject_kind"] != "system" for l in completion_lines(db, project))

def test_a_system_line_still_points_at_a_sheet(db, project, sheet):
    project.building_type, project.building_type_source = "school", "estimator"
    make_item(db, project, sheet, system="Power")
    line = [l for l in completion_lines(db, project) if l["system"] == "Fire alarm"][0]
    assert line["sheet_id"] is not None
    assert "nominal" in line["where"].lower() or line["where"]

def test_a_spec_section_naming_the_work_is_quoted_as_the_evidence(db, project, sheet):
    add_scope_statement(db, project, text="Division 28 fire alarm by this contractor.")
    make_item(db, project, sheet, system="Power")
    line = [l for l in completion_lines(db, project) if l["system"] == "Fire alarm"][0]
    assert "Division 28" in line["found"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_complete.py -q -k system`
Expected: FAIL

- [ ] **Step 3: Implement case 2**

Expected systems per building type in one table, keyed by `building_type`, valued by `SYSTEMS` entries from the existing vocabulary. Skip entirely when `infer_building_type` yields nothing and `Project.building_type` is unset. Evidence precedence per the spec, strongest first: a `ScopeStatement` or `schedule_text` naming the work, else the sheet that came back empty, else the building type alone — which the copy must call out as the weakest. `Item.sheet_id` is NOT NULL, so attach a system line to the lowest-numbered electrical plan sheet and say in `where` that the location is nominal.

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_complete.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/complete.py api/app/estimate/complete_copy.py api/tests/test_complete.py
git commit -m "feat: a system the drawings imply and nothing counted gets an allowance"
```

---

### Task 7: Writing completion, and surviving a re-run

**Files:**
- Modify: `api/app/estimate/complete.py`, `api/app/estimate/write.py`
- Test: `api/tests/test_complete_write.py`

**Interfaces:**
- Produces: `write_completion(db: DbSession, project: Project) -> int` — upserts guessed `Item` rows by identity `(project_id, sheet_id, system, name)` and returns how many it wrote.
- Produces: `completion_assumptions(db: DbSession, project: Project, *, exclude: set[uuid.UUID] | None = None) -> list[dict]` — the paired disclosures, in the same shape the three existing generators return, so `validate_assumption` accepts them unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_rerun_does_not_duplicate_a_guessed_line(db, project):
    write_completion(db, project); db.commit()
    write_completion(db, project); db.commit()
    assert db.scalar(select(func.count()).select_from(Item)
                     .where(Item.origin == "assumed")) == 1

def test_an_approved_guessed_line_survives_a_rerun_untouched(db, project, dana):
    """Review focus 3."""
    write_completion(db, project); db.commit()
    item = db.scalars(select(Item).where(Item.origin == "assumed")).one()
    item.status, item.approved_by_user_id = "approved", dana.id
    item.quantity = 61; db.commit()
    write_completion(db, project); db.commit()
    db.refresh(item)
    assert item.status == "approved" and item.quantity == 61

def test_a_deleted_guessed_line_is_not_resurrected(db, project, dana):
    """Review focus 4."""
    write_completion(db, project); db.commit()
    item = db.scalars(select(Item).where(Item.origin == "assumed")).one()
    delete_item(db, actor=dana, item=item); db.commit()
    write_completion(db, project); db.commit()
    assert db.scalar(select(func.count()).select_from(Item)
                     .where(Item.origin == "assumed")) == 0

def test_a_guessed_line_never_arrives_approved(db, project):
    write_completion(db, project); db.commit()
    assert db.scalars(select(Item).where(Item.origin == "assumed")).one().status == "ready"

def test_a_guessed_line_moves_the_rom_total(db, project):
    before = rom_totals(db, project).direct_cost
    write_completion(db, project); db.commit()
    assert rom_totals(db, project).direct_cost > before

def test_each_guessed_line_has_a_paired_disclosure(db, project):
    regenerate(db, project); db.commit()
    assumed = db.scalars(select(Item).where(Item.origin == "assumed")).all()
    rows = db.scalars(select(Assumption).where(Assumption.basis == "class_average")).all()
    assert len(rows) >= len(assumed)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_complete_write.py -q`
Expected: FAIL, no `write_completion`

- [ ] **Step 3: Implement the write path**

Delete-and-rewrite only guessed items nobody has touched — `status == "ready"`, no `approved_by_user_id`, no `rejected_at`, `version == 1`. An identity match on a touched row is skipped, never overwritten. For deliberate deletion, reuse the pattern `merge._deliberately_deleted` already uses against the action log rather than inventing a second mechanism. Do **not** route through `merge_sheet`: its `_key` is `(sheet_number, source_tag)` and a synthetic tag there would fabricate a cluster that `resolve_apply.py` would then treat as "every one like this."

- [ ] **Step 3b: Wire both halves into `write.py`**

Call `write_completion` from `regenerate` inside its existing advisory lock and **before** `generate(db, project)`, so one project cannot have two writers and the disclosures see the items that were just written.

Add `completion_assumptions(db, project, exclude=exclude)` to the `produced` tuple in `generate`, after `scope` and alongside `takeoff_assumptions` — it takes `exclude` for the same reason the other three do: a guessed line scope removed is not in the number, so disclosing it would describe money that is not there.

- [ ] **Step 4: Run the whole backend suite**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q`
Expected: PASS, no regression in the ROM, merge, or totals suites

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/complete.py api/app/estimate/write.py api/tests/test_complete_write.py
git commit -m "feat: write guessed lines, preserving every judgment across a re-run"
```

---

### Task 8: The wire shape

**Files:**
- Modify: `api/app/takeoff/schemas.py` (`ItemOut`), `src/lib/store/api-mapping.js:28`
- Test: `api/tests/test_items_api.py`, `src/lib/store/api-mapping.test.js`

**Interfaces:**
- Produces: `ItemOut.origin: str`, `ItemOut.confidence: int | None`, `ItemOut.confidence_reasons: list[str] | None`; client items gaining `origin`, `confidence`, `confidenceReasons`.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_item_reports_its_origin_and_confidence(client, db, project, sheet, signed_in_user):
    [row] = client.get(f"/api/projects/{project.id}/items").json()
    assert row["origin"] == "counted" and "confidence" in row

def test_no_processing_internals_leak(client, db, project, sheet, signed_in_user):
    """Invariant 7 still holds for everything except the agreed score."""
    body = json.dumps(client.get(f"/api/projects/{project.id}/items").json()).lower()
    assert not any(w in body for w in ("model", "prompt", "token", "attempt"))
```

```js
it("maps origin and confidence onto the item", () => {
  expect(mapItem({ origin: "assumed", confidence: 3, confidence_reasons: ["x"] }))
    .toMatchObject({ origin: "assumed", confidence: 3, confidenceReasons: ["x"] });
});
it("leaves confidence null for an item that predates the column", () => {
  expect(mapItem({ origin: "counted" }).confidence).toBeNull();
});
```

- [ ] **Step 2: Run to verify both fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_items_api.py -q -k "origin or internals"` and `npm test -- --run src/lib/store/api-mapping.test.js`
Expected: FAIL

- [ ] **Step 3: Add the three fields to `ItemOut` and the mapping**

- [ ] **Step 4: Run both to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/schemas.py src/lib/store/api-mapping.js api/tests/ src/lib/store/
git commit -m "feat: origin and confidence on the item wire shape"
```

---

### Task 9: The row says guessed, and shows a bar

**Files:**
- Modify: `src/components/takeoff/TakeoffSpreadsheet.jsx`, `src/styles.css`
- Create: `src/components/takeoff/ConfidenceBar.jsx`
- Test: `src/components/takeoff/ConfidenceBar.test.jsx`, `src/components/takeoff/TakeoffSpreadsheet.test.jsx`

**Interfaces:**
- Consumes: client `origin`, `confidence`, `confidenceReasons` (Task 8).
- Produces: `<ConfidenceBar value={number|null} reasons={string[]} />`.

- [ ] **Step 1: Write the failing tests**

```jsx
it("draws ten steps and fills to the score", () => {
  render(<ConfidenceBar value={3} reasons={["Typical for this kind of job"]} />);
  expect(screen.getByRole("img")).toHaveAccessibleName(/3 out of 10/i);
});

it("names its reasons in the accessible label, since a bar alone is shape only", () => {
  render(<ConfidenceBar value={4} reasons={["No confirmed scale"]} />);
  expect(screen.getByRole("img")).toHaveAccessibleName(/no confirmed scale/i);
});

it("renders empty rather than zero when nothing was scored", () => {
  /* Review focus 5. */
  render(<ConfidenceBar value={null} reasons={[]} />);
  expect(screen.getByRole("img")).toHaveAccessibleName(/not scored/i);
});

it("marks a guessed row guessed, and not with a review label", () => {
  renderSpreadsheet({ items: [item({ origin: "assumed", status: "ready" })] });
  expect(screen.getByText("Guessed")).toBeInTheDocument();
  expect(screen.queryByText("Needs attention")).not.toBeInTheDocument();
});

it("links a guessed row to the sheet its evidence sits on", () => {
  renderSpreadsheet({ items: [item({ origin: "assumed", sheetId: "s1" })] });
  expect(screen.getByRole("link", { name: /E-2.3/ })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- --run src/components/takeoff/`
Expected: FAIL

- [ ] **Step 3: Build the bar and the two columns**

Ten steps, filled to `value`, `role="img"` with an `aria-label` carrying "N out of 10" and the reasons — the digit is never drawn, per the estimator's choice, so the label is the only text channel and must carry it. Guessed tag reuses the existing `.est-tag-assumed` token pair (`--plum`); add no new colour. Sort and filter are **not** in this slice.

- [ ] **Step 4: Run tests, the origin-colour guard, and the build**

Run: `npm test -- --run` and `npm run build`
Expected: PASS, including `src/components/estimate/originColors.test.js`

- [ ] **Step 5: Commit**

```bash
git add src/components/takeoff/ src/styles.css
git commit -m "feat: a guessed row says so and carries a confidence bar"
```

---

### Task 10: The canvas, and the doctrine amendment

**Files:**
- Modify: `src/components/BlueprintCanvas.jsx:254,308`, `CLAUDE.md`, `ROADMAP.md` (invariant 7), `README.md`
- Test: `src/components/BlueprintCanvas.test.jsx`

**Interfaces:** none; this task closes the two gaps the spec names.

- [ ] **Step 1: Write the failing test**

```jsx
it("draws no marker for a line that was never located on the page", () => {
  render(<BlueprintCanvas items={[item({ origin: "assumed", x: null, y: null })]} ... />);
  expect(screen.queryByRole("button", { name: /guessed/i })).not.toBeInTheDocument();
});

it("still draws located items beside it", () => { /* ... */ });
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- --run src/components/BlueprintCanvas.test.jsx`
Expected: FAIL — the marker renders at an undefined position

- [ ] **Step 3: Guard the marker filters and amend the docs**

Both filters at `:254` and `:308` gain a coordinate check. Then:
- `CLAUDE.md`: replace "Confidence never renders" with the decision actually made — a 1–10 meter renders as one sort key and an explained score, percentages stay banned, and the reasoning for the change is recorded beside it. Add the counted/assumed origin on an `Item` to the "rules that are easy to break" list.
- `ROADMAP.md` invariant 7: narrow it to model identifiers, prompts, and stage names, naming confidence as the deliberate exception.
- `README.md`: add guessed lines to the walkthrough and to known limitations (sort and filter not yet built).

- [ ] **Step 4: Run everything**

Run: `npm test -- --run && npm run build` and `cd api && ../.enginevenv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/BlueprintCanvas.jsx CLAUDE.md ROADMAP.md README.md src/components/BlueprintCanvas.test.jsx
git commit -m "fix: no marker without a position, and record the confidence decision"
```

---

## Not in this plan

- **Completion case 3** — a sheet counted implausibly thin. Its threshold is a product question the spec deliberately leaves open, and it carries the highest false-positive risk of the three cases. Build it once cases 1 and 2 have been seen on a real set.
- **Sort and filter** on money, hours, and confidence — slice 3.
- **Reading a quantity off a schedule** — slice 4.
- **Slice 1** (un-gating the flow) — deliberately sequenced after this one at the estimator's direction.
