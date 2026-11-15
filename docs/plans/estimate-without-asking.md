# Estimate without asking — slice 2 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Where the engine could not identify, measure, or fully count something, write a real takeoff line that carries money and discloses itself, and give every line a 1–10 confidence an estimator can sort and check.

**Architecture:** A pure `confidence.py` scores every line from a named method plus named adjustments. A new `estimate/complete.py` writes **companion allowance lines** — `Item` rows with `origin = "assumed"` attached to a real sheet — each paired with an `Assumption` disclosure through the generator list `estimate/write.py` already walks. Every guessed quantity is derived from what this project itself counted, via a pure `estimate/siblings.py`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + pytest (`cd api && ../.enginevenv/bin/python -m pytest -q`); React 18 + plain CSS tokens + vitest (`npm test -- --run`, `npm run build`).

**Spec:** [`docs/specs/estimate-without-asking.md`](../specs/estimate-without-asking.md). Read it first; every decision below comes from it.

**Base branch:** this work builds on the ROM (`basis.py`, `estimate/write.py`, `ResolvedLine`, migration 0032), which lands via PR #12. Rebase onto `main` after that merges — the docs branch was cut from pre-ROM `main` and none of those modules exist on it.

## The unifying shape

Working the five cases through produced one simplification worth stating before the tasks: **every completion case writes the same thing — one companion allowance line, attached to a real sheet, carrying money the counted lines do not.**

| Case | What's wrong | The companion line covers |
|---|---|---|
| 1 | Counted, never identified | the cost of devices whose catalog item is unknown |
| 2 | No confirmed scale | the measured runs that cannot convert to feet |
| 3 | Counted thin vs. siblings | the shortfall against the sibling median |
| 4 | Produced nothing at all | the whole sheet, from the sibling median |
| 5 | A system never found | a share of the counted electrical work |

Why this and not the two obvious alternatives:

- **Not an assumption carrying a positive amount.** Only items add money (`rom_totals` sums `countable_items`), and `CLAUDE.md` holds that an assumption may only subtract. A disclosure beside an unchanged total was the original bug.
- **Not writing a cost onto the counted item.** That would overwrite what the engine read with what we guessed, and `merge.py` would fight it on the next run. The counted line keeps saying exactly what was counted; the allowance sits beside it saying what we think it costs.
- **Never an assumed scale written onto `Sheet.scale`.** A stored scale is indistinguishable from a confirmed one, and that is the single most dangerous write in this design. Case 2 carries money in a companion line and leaves the sheet's scale empty and its items *Missing information*, so Export still blocks on a person.

## Global Constraints

- **Four review labels, never a fifth.** A guessed line's status is `ready`; "Guessed" is the `origin` axis, not a label.
- **Origin colours are `--slate` (counted) / `--plum` (assumed).** Never `--amber`, `--blue`, `--red`, `--green`. `src/components/estimate/originColors.test.js` must keep passing.
- **Nothing unapproved scores above 9.** 10 means a person checked it.
- **Every guessed quantity is relative to this project's own counts.** No absolute device constants. Nothing counted means nothing guessed.
- **Money comes from `totals.resolved_lines()`**, never `Item`'s stored cost columns.
- **No approval is ever written by code.** Completion lines are `ready`, never `approved`.
- **`Sheet.scale` is never written by this slice.**
- **Confidence renders** — this slice amends `CLAUDE.md` and ROADMAP invariant 7 deliberately (Task 13).
- **Sentence case, no "successfully", no model names, no confidence *percentages*.** A 1–10 meter is not a percentage.
- Migration head after the ROM merges is `0032_assumption_origin`. New migration is `0033`.

## Review Focus

1. **A project with no counted items at all** — every case must produce nothing. A relative guess with no base is how a fabricated building gets into a bid. (Task 5)
2. **A single-sheet project** — no siblings to compare against; cases 3 and 4 must stand down rather than compare a sheet to itself. (Task 5)
3. **A re-run after a person approved or edited a companion line** — must neither duplicate it nor overwrite them. (Task 10)
4. **A companion line a person deleted** — a re-run must not resurrect it. (Task 10)
5. **Items predating this slice, with null confidence** — the bar renders empty, sorting puts them last, nothing throws. (Task 12)

---

### Task 1: The confidence scale

**Files:**
- Create: `api/app/takeoff/confidence.py`
- Test: `api/tests/test_confidence.py`

**Interfaces:**
- Produces: `BASE_SCORES: dict[str, int]`, `ADJUSTMENTS: dict[str, int]`, and
  `score(method: str, adjustments: Sequence[str] = (), *, approved: bool = False) -> tuple[int, list[str]]`
  returning the clamped score and the reasons that produced it.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_counted_line_matched_to_a_schedule_scores_nine():
    assert score("counted_matched")[0] == 9

def test_a_counted_but_unidentified_line_scores_five():
    """Quantity as good as any counted line, cost a class average. One
    number carries both, so the lower is the honest one."""
    assert score("counted_unidentified")[0] == 5

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
    """Spec invariant 2: a 9 beside a +/-25% band would be two parts of
    the product disagreeing about one fact."""
    from app.estimate.basis import BASIS
    assert BASE_SCORES["firm_rule"] > BASE_SCORES["class_average_sibling"]
    assert BASIS["rule_of_thumb"].spread >= BASIS["class_average"].spread
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_confidence.py -q`
Expected: FAIL, no module named `app.takeoff.confidence`

- [ ] **Step 3: Implement `confidence.py`**

`BASE_SCORES` exactly as the spec's table: `counted_matched` 9, `counted_high` 8, `schedule_read` 8, `measured_confirmed` 7, `counted_uncertain` 6, `counted_unidentified` 5, `firm_rule` 5, `measured_unconfirmed` 4, `class_average_sibling` 3, `class_average_system` 2. `ADJUSTMENTS`: `corroborated` +1, `sources_disagree` −1, `partial_page` −1, `not_in_legend` −1.

One module-level comment recording that these are a deliberately single editable table, expected to move once a real bid set has been through them, per the estimator.

Clamp to 1..9, then `approved` overrides to 10. Each applied base and adjustment appends one estimator-facing sentence to `reasons`; no model names, no percentages.

- [ ] **Step 4: Run to verify it passes** — Expected: PASS

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
- Test: `api/tests/test_models.py`

**Interfaces:**
- Produces: `Item.origin: str` (`"counted"` default), `Item.confidence: int | None`, `Item.confidence_reasons: list | None`, `Project.building_type: str | None`, `Project.building_type_source: str | None` (`"inferred"` / `"estimator"`).

- [ ] **Step 1: Write the failing tests**

```python
def test_an_item_defaults_to_counted(db, project, sheet):
    item = make_item(db, project, sheet)
    assert item.origin == "counted" and item.confidence is None

def test_an_unrecognized_origin_is_refused(db, project, sheet):
    with pytest.raises(IntegrityError):
        make_item(db, project, sheet, origin="maybe"); db.flush()

def test_an_unrecognized_building_type_source_is_refused(db, project):
    with pytest.raises(IntegrityError):
        project.building_type_source = "hunch"; db.flush()

def test_building_type_is_optional(db, project):
    assert project.building_type is None
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, unknown attribute

- [ ] **Step 3: Add the columns and write migration `0033`**

`down_revision = "0032"`. `items.origin` `String(20)` not null `server_default="counted"` with `ck_items_origin` over `basis.ORIGINS`. `items.confidence` `SmallInteger` nullable. `items.confidence_reasons` `JSONB` nullable. `projects.building_type` `String(100)` nullable. `projects.building_type_source` `String(20)` nullable with `ck_projects_building_type_source` over `("inferred", "estimator")`.

No backfill: existing rows are genuinely `counted` with unknown confidence, and the spec requires null to render empty rather than be invented. Mirror `0032_assumption_origin.py`'s comment style, recording why `origin` is stored rather than derived.

- [ ] **Step 4: Run the suite, then apply**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_models.py -q`
Run: `docker compose run --rm api alembic upgrade head`
Expected: PASS; `0033` applied

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
    assert build_row(spec={"confidence": "high"}, classification_basis=None)["confidence"] == 9

def test_a_row_named_from_context_scores_lower_than_a_matched_one():
    assert build_row(classification_basis="inferred")["confidence"] < 9

def test_a_low_confidence_row_keeps_attention_and_scores_six():
    row = build_row(spec={"confidence": "low"})
    assert row["status"] == "attention" and row["confidence"] == 6

def test_merge_persists_the_confidence_and_its_reasons(db, project, sheet):
    merge_sheet(db, project=project, sheet=sheet, rows=[row], ai_reading=True)
    item = db.scalars(select(Item)).one()
    assert item.confidence == 9 and item.confidence_reasons
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, KeyError `'confidence'`

- [ ] **Step 3: Map the engine's inputs to a method and score the row**

In `rows.py`, directly after the existing `status` line: `classification_basis == "inferred"` → `counted_uncertain`; `spec["confidence"] == "high"` with a legend match → `counted_matched`; `"high"` without → `counted_high`; otherwise `counted_uncertain`. Pass `not_in_legend` when the cluster's tag had no legend row. **Leave `status` untouched** — this task adds a channel, it does not change routing.

In `merge.py`, carry both fields in `_overwrite`, and add `confidence` to `_changes_visibly` so a score change alone is not counted as estimator-facing news.

- [ ] **Step 4: Run to verify it passes** — Expected: PASS

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
  `infer_building_type(db: DbSession, project: Project) -> tuple[str, str] | None`
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

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, no module

- [ ] **Step 3: Implement deterministic inference over stored text**

Read `Sheet.number`, `Sheet.title`, `Sheet.schedule_text`, `ScopeStatement.text` — all stored by the read job, so this opens no file and is API-safe. Keyword sets per type in one table, shaped like `StandardExclusion.vocabulary`.

Deliberately **not** a language call: this product has one classifier, and a deterministic guess that returns `None` under conflict is honest where a model's tiebreak would not be. Return `None` when `building_type_source == "estimator"`, when nothing matches, or when two types tie.

- [ ] **Step 4: Run to verify it passes** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/building_type.py api/tests/test_building_type.py
git commit -m "feat: infer the building type from what the read job stored"
```

---

### Task 5: Sibling statistics — the base every guess is relative to

**Files:**
- Create: `api/app/estimate/siblings.py`
- Test: `api/tests/test_siblings.py`

**Interfaces:**
- Produces: `MIN_SAMPLE: int`, frozen dataclass `SiblingStats(median: int, sample: int, sheet_numbers: tuple[str, ...])`, and two functions:
  - `sibling_stats(counts: Sequence[tuple[str, int]]) -> SiblingStats | None` — **pure**, no database.
  - `plan_sheet_counts(db: DbSession, project: Project) -> list[tuple[str, int]]` — `(sheet_number, counted_device_quantity)` for every `sheet_kind == "plan"` sheet, from `countable_items`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_median_of_three_siblings():
    assert sibling_stats([("E-1.0", 40), ("E-1.1", 60), ("E-1.2", 50)]).median == 50

def test_an_even_sample_takes_the_lower_middle():
    """Deliberate: an estimate that rounds down is the safer error when
    the number is a guess being handed to a GC."""
    assert sibling_stats([("A", 40), ("B", 60)]).median == 40

def test_too_small_a_sample_is_no_basis_at_all():
    """Review focus 2: a single-sheet project has no siblings."""
    assert sibling_stats([("E-1.0", 40)]) is None
    assert sibling_stats([]) is None

def test_sheets_that_counted_nothing_are_excluded_from_the_base():
    """A sheet that failed is what we are guessing FOR; letting it into
    the median drags every guess toward zero."""
    stats = sibling_stats([("A", 40), ("B", 60), ("C", 50), ("D", 0)])
    assert stats.median == 50 and stats.sample == 3

def test_the_stats_name_the_sheets_they_came_from():
    assert sibling_stats([("A", 40), ("B", 60)]).sheet_numbers == ("A", "B")

def test_plan_sheet_counts_ignores_schedules_and_legends(db, project):
    add_sheet(db, project, number="E-501", kind="schedule")
    add_sheet(db, project, number="E-1.0", kind="plan")
    assert [n for n, _ in plan_sheet_counts(db, project)] == ["E-1.0"]
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, no module

- [ ] **Step 3: Implement**

`MIN_SAMPLE = 2`. `sibling_stats` drops zero counts, returns `None` below `MIN_SAMPLE`, and takes the lower middle on an even sample. Keep it pure and database-free, in the shape of `schedule/plan.py`, so the whole rule is testable on plain data.

- [ ] **Step 4: Run to verify it passes** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/siblings.py api/tests/test_siblings.py
git commit -m "feat: sibling sheet statistics, the base every guess is relative to"
```

---

### Task 6: Case 1 — counted but never identified

**Files:**
- Create: `api/app/estimate/complete.py`, `api/app/estimate/complete_copy.py`
- Test: `api/tests/test_complete.py`

**Interfaces:**
- Consumes: `resolved_lines`, `ResolvedLine.priced`, `confidence.score`.
- Produces: `completion_lines(db: DbSession, project: Project, *, exclude: set[uuid.UUID] | None = None) -> list[dict]` — companion allowance dicts carrying `sheet_id`, `subject_kind`, `case`, `name`, `system`, `category`, `quantity`, `unit`, `origin="assumed"`, `basis`, `confidence`, `confidence_reasons`, and the four disclosure fields (`found`, `why`, `fix`, `where`).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_counted_line_nothing_priced_gets_a_companion_allowance(db, project, sheet):
    make_item(db, project, sheet, quantity=47, material_cost=0, labor_hours=0)
    [line] = completion_lines(db, project)
    assert line["case"] == "unidentified" and line["origin"] == "assumed"
    assert line["sheet_id"] == sheet.id and line["confidence"] == 5

def test_a_priced_counted_line_gets_no_companion(db, project, sheet):
    make_item(db, project, sheet, quantity=47, material_cost=Decimal("12.00"))
    assert completion_lines(db, project) == []

def test_one_companion_per_sheet_not_per_cluster(db, project, sheet):
    for tag in ("A", "B", "C"):
        make_item(db, project, sheet, source_tag=tag, material_cost=0, labor_hours=0)
    assert len([l for l in completion_lines(db, project) if l["case"] == "unidentified"]) == 1

def test_the_counted_line_itself_is_never_rewritten(db, project, sheet):
    item = make_item(db, project, sheet, quantity=47, material_cost=0)
    completion_lines(db, project)
    db.refresh(item)
    assert item.material_cost == 0 and item.origin == "counted"

def test_the_disclosure_names_the_sheet_and_the_device_count(db, project, sheet):
    make_item(db, project, sheet, quantity=47, material_cost=0, labor_hours=0)
    [line] = completion_lines(db, project)
    assert all(line[f] for f in ("found", "why", "fix", "where"))
    assert "47" in line["found"] and sheet.number in line["found"]

def test_a_project_with_no_counted_items_completes_nothing(db, project):
    """Review focus 1: a relative guess with no base is a fabricated building."""
    assert completion_lines(db, project) == []
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, no module

- [ ] **Step 3: Implement case 1**

Walk `resolved_lines(db, project, exclude=exclude)`, keep those where `not line.priced`, group by `sheet_id`, and emit one companion per sheet carrying that sheet's unpriced device quantity. Cost per device from the class average for the line's `system`, read off the same resolvers `generate_cost.py` uses — never a literal. Method `counted_unidentified`.

`complete_copy.py` holds every estimator-facing sentence, shaped like `estimate/copy.py`. The counted item is read and never written.

- [ ] **Step 4: Run to verify it passes** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/complete.py api/app/estimate/complete_copy.py api/tests/test_complete.py
git commit -m "feat: a counted line nothing could price gets a companion allowance"
```

---

### Task 7: Case 2 — measured runs with no confirmed scale

**Files:**
- Modify: `api/app/estimate/complete.py`, `api/app/estimate/complete_copy.py`
- Test: `api/tests/test_complete.py`

**Interfaces:**
- Consumes: `generate_takeoff._NO_SINGLE_SCALE` (promote to a shared constant), `siblings.sibling_stats`.
- Produces: `completion_lines` additionally returning `case == "unscaled"` rows with `basis == "scaled"` and `confidence == 4`.

- [ ] **Step 1: Write the failing tests**

```python
def test_measured_items_on_an_unscaled_sheet_get_an_allowance(db, project):
    sheet = add_sheet(db, project, number="E-2.1", kind="plan", scale="")
    make_item(db, project, sheet, unit="ft", path=[[0, 0], [10, 10]], status="missing")
    [line] = [l for l in completion_lines(db, project) if l["case"] == "unscaled"]
    assert line["confidence"] == 4 and line["basis"] == "scaled"

def test_a_confirmed_scale_produces_no_allowance(db, project):
    sheet = add_sheet(db, project, number="E-2.1", kind="plan", scale='1/8" = 1\'-0"')
    make_item(db, project, sheet, unit="ft", path=[[0, 0], [10, 10]])
    assert not [l for l in completion_lines(db, project) if l["case"] == "unscaled"]

def test_the_sheets_scale_is_never_written(db, project):
    sheet = add_sheet(db, project, number="E-2.1", kind="plan", scale="")
    make_item(db, project, sheet, unit="ft", path=[[0, 0], [10, 10]], status="missing")
    completion_lines(db, project)
    db.refresh(sheet)
    assert not sheet.scale

def test_the_measured_items_keep_missing_information(db, project):
    """The firewall stays shut: Export still blocks until a person sets
    the scale. Only the ROM stops being silently short."""
    sheet = add_sheet(db, project, number="E-2.1", kind="plan", scale="")
    item = make_item(db, project, sheet, unit="ft", path=[[0, 0], [10, 10]], status="missing")
    completion_lines(db, project)
    db.refresh(item)
    assert item.status == "missing"

def test_the_disclosure_says_which_sheet_lacks_a_scale(db, project):
    sheet = add_sheet(db, project, number="E-2.1", kind="plan", scale="")
    make_item(db, project, sheet, unit="ft", path=[[0, 0], [10, 10]], status="missing")
    [line] = [l for l in completion_lines(db, project) if l["case"] == "unscaled"]
    assert "E-2.1" in line["found"] and "scale" in line["why"].lower()
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, no `unscaled` case

- [ ] **Step 3: Implement case 2**

Promote `_NO_SINGLE_SCALE` out of `generate_takeoff.py` into a shared constant so one list governs both the disclosure and this case. For each plan sheet whose scale is absent or ambiguous and which carries measured items, emit one companion allowance. Length per run from a sibling sheet's resolved feet-per-run where available, else the firm's rule. Method `measured_unconfirmed`.

Write nothing to `Sheet.scale` and nothing to the measured items — a stored scale is indistinguishable from a confirmed one.

- [ ] **Step 4: Run to verify it passes** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/complete.py api/app/estimate/complete_copy.py api/tests/test_complete.py
git commit -m "feat: unscaled measured runs carry an allowance, and the scale stays unset"
```

---

### Task 8: Cases 3 and 4 — a sheet thin or empty against its siblings

**Files:**
- Modify: `api/app/estimate/complete.py`, `api/app/estimate/complete_copy.py`
- Test: `api/tests/test_complete.py`

**Interfaces:**
- Consumes: `siblings.sibling_stats`, `siblings.plan_sheet_counts`.
- Produces: `completion_lines` additionally returning `case in ("thin", "empty")` rows, `basis == "class_average"`, `confidence == 3`. `THIN_FRACTION: float` as one named constant.

Built together because they share one calculation: the shortfall against the sibling median. An empty sheet is the thin case with a count of zero.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_sheet_counted_well_below_its_siblings_is_topped_up(db, project):
    for n in ("E-1.0", "E-1.1"): make_item(db, project, add_sheet(db, project, number=n, kind="plan"), quantity=60)
    thin = add_sheet(db, project, number="E-1.2", kind="plan")
    make_item(db, project, thin, quantity=5)
    [line] = [l for l in completion_lines(db, project) if l["case"] == "thin"]
    assert line["sheet_id"] == thin.id and line["quantity"] == 55

def test_a_sheet_in_line_with_its_siblings_is_left_alone(db, project):
    for n in ("E-1.0", "E-1.1", "E-1.2"):
        make_item(db, project, add_sheet(db, project, number=n, kind="plan"), quantity=60)
    assert not [l for l in completion_lines(db, project) if l["case"] in ("thin", "empty")]

def test_a_sheet_that_counted_nothing_is_guessed_from_its_siblings(db, project):
    for n in ("E-1.0", "E-1.1"): make_item(db, project, add_sheet(db, project, number=n, kind="plan"), quantity=60)
    empty = add_sheet(db, project, number="E-1.2", kind="plan", render_status="failed")
    [line] = [l for l in completion_lines(db, project) if l["case"] == "empty"]
    assert line["quantity"] == 60 and "partial" in " ".join(line["confidence_reasons"]).lower()

def test_a_single_sheet_project_guesses_nothing(db, project):
    """Review focus 2: no siblings, no comparison, no guess."""
    make_item(db, project, add_sheet(db, project, number="E-1.0", kind="plan"), quantity=5)
    assert not [l for l in completion_lines(db, project) if l["case"] in ("thin", "empty")]

def test_the_disclosure_names_the_sheets_the_median_came_from(db, project):
    for n in ("E-1.0", "E-1.1"): make_item(db, project, add_sheet(db, project, number=n, kind="plan"), quantity=60)
    add_sheet(db, project, number="E-1.2", kind="plan")
    [line] = [l for l in completion_lines(db, project) if l["case"] == "empty"]
    assert "E-1.0" in line["where"] and "E-1.1" in line["where"]
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, no `thin` case

- [ ] **Step 3: Implement cases 3 and 4**

`THIN_FRACTION` as one named constant with its reasoning beside it — the spec leaves the threshold open deliberately, so make it one number a person can change, never a literal in a branch. A sheet counting below `median * THIN_FRACTION` is topped up to the median; the companion's quantity is the shortfall. A sheet at zero takes the whole median and adds the `partial_page` adjustment when `render_status == "failed"`. Stand down entirely when `sibling_stats` returns `None`. Method `class_average_sibling`.

- [ ] **Step 4: Run the whole completion suite** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/complete.py api/app/estimate/complete_copy.py api/tests/test_complete.py
git commit -m "feat: a sheet thin or empty against its siblings is topped up from them"
```

---

### Task 9: Case 5 — a system the job should have and nothing found

**Files:**
- Modify: `api/app/estimate/complete.py`, `api/app/estimate/complete_copy.py`
- Test: `api/tests/test_complete.py`

**Interfaces:**
- Consumes: `building_type.infer_building_type` (Task 4).
- Produces: `completion_lines` additionally returning `case == "system"` rows, `subject_kind == "system"`, `confidence == 2`. `SYSTEM_SHARES: dict[str, dict[str, float]]` — share of counted electrical cost per system, keyed by building type.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_school_with_no_fire_alarm_gets_a_share_of_the_counted_work(db, project, sheet):
    project.building_type, project.building_type_source = "school", "estimator"
    make_item(db, project, sheet, system="Power", material_cost=Decimal("10000"))
    [line] = [l for l in completion_lines(db, project) if l["system"] == "Fire alarm"]
    assert line["confidence"] == 2 and line["basis"] == "class_average"

def test_a_system_already_counted_is_not_guessed(db, project, sheet):
    project.building_type, project.building_type_source = "school", "estimator"
    make_item(db, project, sheet, system="Fire alarm", material_cost=Decimal("100"))
    assert not [l for l in completion_lines(db, project) if l["system"] == "Fire alarm"]

def test_an_unknown_building_type_skips_system_completion(db, project, sheet):
    """Review focus: never invent a baseline for an unknown building."""
    make_item(db, project, sheet, system="Power", material_cost=Decimal("10000"))
    assert not [l for l in completion_lines(db, project) if l["case"] == "system"]

def test_nothing_counted_means_no_share_to_take(db, project, sheet):
    """Review focus 1 again: a share of zero is zero, never a constant."""
    project.building_type, project.building_type_source = "school", "estimator"
    assert not [l for l in completion_lines(db, project) if l["case"] == "system"]

def test_a_system_line_still_points_at_a_real_sheet(db, project, sheet):
    project.building_type, project.building_type_source = "school", "estimator"
    make_item(db, project, sheet, system="Power", material_cost=Decimal("10000"))
    line = [l for l in completion_lines(db, project) if l["case"] == "system"][0]
    assert line["sheet_id"] is not None and "nominal" in line["where"].lower()

def test_a_spec_section_naming_the_work_is_quoted_as_the_evidence(db, project, sheet):
    add_scope_statement(db, project, text="Division 28 fire alarm by this contractor.")
    make_item(db, project, sheet, system="Power", material_cost=Decimal("10000"))
    line = [l for l in completion_lines(db, project) if l["system"] == "Fire alarm"][0]
    assert "Division 28" in line["found"]
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, no `system` case

- [ ] **Step 3: Implement case 5**

`SYSTEM_SHARES` keyed by building type, valued by `SYSTEMS` entries from the existing vocabulary and a fraction of counted electrical cost. Skip entirely when neither `Project.building_type` nor `infer_building_type` yields a type, and when nothing was counted.

Evidence precedence per the spec, strongest first: a `ScopeStatement` or `schedule_text` naming the work, else the sheet that came back empty, else the building type alone — which the copy must call out as the weakest. `Item.sheet_id` is NOT NULL, so attach to the lowest-numbered electrical plan sheet and say in `where` that the location is nominal.

- [ ] **Step 4: Run to verify it passes** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/complete.py api/app/estimate/complete_copy.py api/tests/test_complete.py
git commit -m "feat: a system the drawings imply and nothing counted gets a share"
```

---

### Task 10: Writing completion, and surviving a re-run

**Files:**
- Modify: `api/app/estimate/complete.py`, `api/app/estimate/write.py`
- Test: `api/tests/test_complete_write.py`

**Interfaces:**
- Produces:
  - `write_completion(db: DbSession, project: Project) -> int` — upserts companion `Item` rows by identity `(project_id, sheet_id, case, system)`.
  - `completion_assumptions(db: DbSession, project: Project, *, exclude: set[uuid.UUID] | None = None) -> list[dict]` — the paired disclosures, in the shape the three existing generators return, so `validate_assumption` accepts them unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_rerun_does_not_duplicate_a_companion_line(db, project):
    write_completion(db, project); db.commit()
    write_completion(db, project); db.commit()
    assert db.scalar(select(func.count()).select_from(Item).where(Item.origin == "assumed")) == 1

def test_an_approved_companion_survives_a_rerun_untouched(db, project, dana):
    """Review focus 3."""
    write_completion(db, project); db.commit()
    item = db.scalars(select(Item).where(Item.origin == "assumed")).one()
    item.status, item.approved_by_user_id, item.quantity = "approved", dana.id, 61
    db.commit(); write_completion(db, project); db.commit(); db.refresh(item)
    assert item.status == "approved" and item.quantity == 61

def test_a_deleted_companion_is_not_resurrected(db, project, dana):
    """Review focus 4."""
    write_completion(db, project); db.commit()
    item = db.scalars(select(Item).where(Item.origin == "assumed")).one()
    delete_item(db, actor=dana, item=item); db.commit()
    write_completion(db, project); db.commit()
    assert db.scalar(select(func.count()).select_from(Item).where(Item.origin == "assumed")) == 0

def test_a_companion_never_arrives_approved(db, project):
    write_completion(db, project); db.commit()
    assert db.scalars(select(Item).where(Item.origin == "assumed")).one().status == "ready"

def test_a_companion_moves_the_rom_total(db, project):
    before = rom_totals(db, project).direct_cost
    write_completion(db, project); db.commit()
    assert rom_totals(db, project).direct_cost > before

def test_each_companion_has_a_paired_disclosure(db, project):
    regenerate(db, project); db.commit()
    assumed = db.scalars(select(Item).where(Item.origin == "assumed")).all()
    rows = db.scalars(select(Assumption).where(Assumption.section == "takeoff")).all()
    assert len(assumed) > 0 and len(rows) >= len(assumed)

def test_an_excluded_companion_is_not_disclosed(db, project):
    """Scope removed it, so its price basis would describe money that is
    not in the number -- the same argument the other generators make."""
    ids = {l["sheet_id"] for l in completion_lines(db, project)}
    assert completion_assumptions(db, project, exclude=ids) == []
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, no `write_completion`

- [ ] **Step 3: Implement the write path**

Delete-and-rewrite only companions nobody has touched — `status == "ready"`, no `approved_by_user_id`, no `rejected_at`, `version == 1`. An identity match on a touched row is skipped, never overwritten. For deliberate deletion, reuse the pattern `merge._deliberately_deleted` already uses against the action log rather than inventing a second mechanism.

Do **not** route through `merge_sheet`: its `_key` is `(sheet_number, source_tag)`, and a synthetic tag there would fabricate a cluster that `resolve_apply.py` would then treat as "every one like this."

- [ ] **Step 3b: Wire both halves into `write.py`**

Call `write_completion` from `regenerate` inside its existing advisory lock and **before** `generate(db, project)`, so one project cannot have two writers and the disclosures see the items just written. Add `completion_assumptions(db, project, exclude=exclude)` to the `produced` tuple in `generate`, alongside `takeoff_assumptions`.

- [ ] **Step 4: Run the whole backend suite**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q`
Expected: PASS, no regression in the ROM, merge, or totals suites

- [ ] **Step 5: Commit**

```bash
git add api/app/estimate/complete.py api/app/estimate/write.py api/tests/test_complete_write.py
git commit -m "feat: write companion allowances, preserving every judgment across a re-run"
```

---

### Task 11: The wire shape

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

- [ ] **Step 2: Run both to verify they fail** — Expected: FAIL

- [ ] **Step 3: Add the three fields to `ItemOut` and the mapping**

- [ ] **Step 4: Run both to verify they pass** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/schemas.py src/lib/store/api-mapping.js api/tests/ src/lib/store/
git commit -m "feat: origin and confidence on the item wire shape"
```

---

### Task 12: The row says guessed, and shows a bar

**Files:**
- Modify: `src/components/takeoff/TakeoffSpreadsheet.jsx`, `src/styles.css`
- Create: `src/components/takeoff/ConfidenceBar.jsx`
- Test: `src/components/takeoff/ConfidenceBar.test.jsx`, `src/components/takeoff/TakeoffSpreadsheet.test.jsx`

**Interfaces:**
- Consumes: client `origin`, `confidence`, `confidenceReasons` (Task 11).
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
  expect(screen.getByRole("link", { name: /E-2.1/ })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL

- [ ] **Step 3: Build the bar and the two columns**

Ten steps filled to `value`, `role="img"`, `aria-label` carrying "N out of 10" and the reasons — the digit is never drawn, per the estimator's choice, so the label is the only text channel and must carry it. The Guessed tag reuses the existing `.est-tag-assumed` token pair (`--plum`); add no new colour. Sort and filter are **not** in this slice.

- [ ] **Step 4: Run tests, the origin-colour guard, and the build**

Run: `npm test -- --run` and `npm run build`
Expected: PASS, including `src/components/estimate/originColors.test.js`

- [ ] **Step 5: Commit**

```bash
git add src/components/takeoff/ src/styles.css
git commit -m "feat: a guessed row says so and carries a confidence bar"
```

---

### Task 13: The canvas, and the doctrine amendment

**Files:**
- Modify: `src/components/BlueprintCanvas.jsx:254,308`, `CLAUDE.md`, `ROADMAP.md`, `README.md`
- Test: `src/components/BlueprintCanvas.test.jsx`

- [ ] **Step 1: Write the failing test**

```jsx
it("draws no marker for a line that was never located on the page", () => {
  render(<BlueprintCanvas items={[item({ origin: "assumed", x: null, y: null })]} />);
  expect(screen.queryByRole("button", { name: /guessed/i })).not.toBeInTheDocument();
});

it("still draws located items beside it", () => { /* ... */ });
```

- [ ] **Step 2: Run to verify it fails** — Expected: FAIL, marker renders at an undefined position

- [ ] **Step 3: Guard the marker filters and amend the docs**

Both filters at `:254` and `:308` gain a coordinate check. Then:
- `CLAUDE.md`: replace "Confidence never renders" with the decision actually made — a 1–10 meter renders as one sort key and an explained score, percentages stay banned, reasoning recorded beside it. Add `Item.origin` to the "rules that are easy to break" list, and the rule that `Sheet.scale` is never written by a guess.
- `ROADMAP.md`: narrow invariant 7 to model identifiers, prompts, and stage names, naming confidence as the deliberate exception. Correct §2.9, which still says no workflow runs the suites — `ci.yml` has existed since 1 October.
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

- **Calibrating the starting numbers.** `BASE_SCORES`, `THIN_FRACTION`, `SYSTEM_SHARES`, and `MIN_SAMPLE` are all deliberately single named values. They get set against a real bid set once the ROM is on `main`, not reasoned out from the code.
- **Sort and filter** on money, hours, and confidence — slice 3.
- **Reading a quantity off a schedule** — slice 4.
- **Slice 1** (un-gating the flow) — sequenced after this one at the estimator's direction.
