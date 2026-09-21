# Phases and timeline — design

**Date:** 2026-09-21
**Status:** Draft for review. Spec-first: the build starts after stream A merges (`docs/roadmap/workstreams-2026-09.md` §4).
**Builds on:** `labor-material-pricing.md` (the company labor tables and `resolve_labor`), `estimate-first-pricing.md` (the price-request round trip, the quote-required word list), `docs/roadmap/phasing-research.md` (the evidence: the two example workbooks and how the trade schedules today).
**Changes:** every item gains a phase; the labor hours the product already resolves gain a place in time; the price request gains one column; export rolls up per phase.
**Hands off to:** stream F's plan screen (§9), which proposes phases from what the documents say; stream C's Excel-on-template export (§8), which owns the workbook this defines the rows for.

## 1. What this is for

An estimator's number is hours and material. The bid the GC wants is that, plus *when* — how many people on site each week, when each area is done, and which equipment has to be ordered before anyone mobilizes. Today the product stops at hours per item. The firm's own workbook stops there too (`phasing-research.md` §1): the Gerber Collision bid is two phases, each a complete mini-estimate rolled up as one lump-sum line on the summary, and nothing in the file says how long either takes or when the gear was ordered. That work happened somewhere else, by hand, from the same hours.

After this design a project carries **phases** — the areas or stages of a renovation the GC has split the job into, each owning sheets, each rolled up as its own line the way the summary sheet does — and a **timeline** derived from hours the product already has: per phase, one bar per stage of electrical work (demolition, rough-in, wire pull, gear, trim, close-out), each with the crew the firm would put on it and the working days that crew needs; below the bars, the weekly manpower chart a GC asks for; above them, the order-by date for every piece of long-lead gear whose lead time someone has actually quoted.

Three rules hold throughout, and they are what keep this inside `CLAUDE.md`:

- **Nothing here changes what is counted.** A phase is a grouping of items that already exist; a stage is a grouping of hours already resolved. Totals, statuses, approvals, and the four review labels are untouched. Hiding a phase on screen never changes a total.
- **Everything computed is a baseline the estimator overrides.** Every default is a firm setting; every derived date, crew, and duration on a project is editable; an edit is stored as the estimator's and shown as such. The product's version is the computed one, labeled as computed.
- **A date appears only when data supports it.** A lead time comes from a supplier's quote or the firm's own dated entry — never from a published industry range. Without one, the item carries the flag and says the lead time is not yet quoted, and no order-by date is drawn.

The engine stops at direct cost, as before. No agent proposes markup, a schedule contingency, or overtime; the per-phase markup block in the firm's template stays the estimator's layer.

## 2. What the evidence says, in one paragraph each

**The workbooks** (`phasing-research.md` §1–2). A phase is a whole sheet family (`E-1.0`, `ED-2.0` in Phase I; `XE-1.0`, `XED-1.0`, `XES-1.1` in Phase II), with its own general-conditions lines (cleanup; planning, coordination and layout — both `LS`, both left at zero hours), its own demolition lines (counted items with unit hours, like new work), and its own subtotal. The summary carries each phase as one `LS` line with its total hours. Markup is applied once, on the summary. A single-phase bid is the same template with one sheet — the degenerate case, which this design must make cost nothing.

**The trade** (`phasing-research.md` §4, §7). Crew size = hours ÷ working days ÷ productive hours per day, and six productive hours is the honest divisor. Crews are planned per phase against the GC's window, in both directions: given a crew, how long; given the window, what crew. Diminishing returns past four or five on a task. Field cost codes are the stages: rough, pull, panel, trim, punch. The GC asks for a manpower loading chart — hours per week as people per week — not a Gantt; the two are one dataset. Long-lead gear lives in a procurement log tied to the install activity: order-by = needed-by − lead time.

**Lead times in 2026** (`phasing-research.md` §5, §7). Low-voltage switchboards around a year; medium-voltage switchgear longer; pad-mount transformers 40–65 weeks; generators 32–66 weeks by size; transfer switches 24–40. The advice to estimators is to identify every piece of distribution gear before pricing, get current lead times from the manufacturer rather than memory, and state them in the bid. Those ranges are why the feature exists and are not a source of any number in it.

## 3. The model

### 3.1 Phases

A project has one or more phases, ordered. A phase has a name, the sheets it covers, an optional start date, an optional required finish (the GC's window), and notes.

**The first phase is implicit.** A project with no `phases` row behaves exactly as today. The row is created the first time anything needs it — the schedule screen opening, a second phase being added, a sheet being assigned — named "Phase 1". Until a second phase exists, the item panel shows no phase field, the spreadsheet no phase column, and export no phase roll-up. The single-phase FedEx bid sees nothing new.

**Sheets belong to phases; items inherit.** `Sheet.phase_id` (nullable; null reads as the project's first phase). `Item.phase_id` (nullable; null reads as the item's sheet's phase). One function resolves it:

```python
def phase_of(item: Item, sheet: Sheet, first_phase: Phase) -> Phase
```

used by totals, labor, export, and the schedule. Nothing re-derives it. A per-item override is for the panel that feeds both areas or the corridor a sheet shares; it is set on the item, undoable, and shown in the panel as "Phase 2 (moved from Phase 1)" so the exception is visible.

**Deleting a phase** moves its sheets and any item overrides to the phase before it (or after, for the first), in the same action, so no item is ever without a phase. The last phase cannot be deleted; it can be renamed.

### 3.2 Phase lines: general conditions

The firm's template carries two lump-sum lines per phase. They are **phase lines**, not items: `PhaseLine(phase_id, kind="general_conditions", label, percent_of_direct_hours, hours_override)`, created with the phase from the company template (§3.4), one per template row, the percent copied from the template at creation.

A line's hours are computed — `percent × the phase's direct hours` (the sum of stage hours before general conditions), recomputed on every read — until the estimator types a number, which lands in `hours_override` and stops moving. "Reset to computed" clears the override. The read reports which it was (`hours_source: computed | estimator`). The cost of a phase line is its hours × the firm's journeyman rate (the same rate `resolve_labor` reaches for an item with no override); it carries no material.

**Demolition is not a phase line.** A removal is a counted item with unit hours, exactly as the Gerber workbook prices it, and it lands in the demolition stage through the split table like every other item (§3.3). The engine does not emit a `Demolition` category today; until it does, or until the estimator classifies removals as such through the item panel, the demolition bar is empty and says so.

### 3.3 Stages and the firm's split

Six stages, a fixed vocabulary in `api/app/schedule/stages.py`, mirrored in `src/components/schedule/stages.js`, in this order:

| key | label | what lands here |
|---|---|---|
| `demolition` | Demolition | removals, relocations, make-safe |
| `rough_in` | Rough-in | conduit, boxes, sleeves, feeders in the ground or walls |
| `wire_pull` | Wire pull | conductors, cable |
| `gear` | Gear | switchboards, panels, transformers set and terminated |
| `trim` | Trim | devices, fixtures, plates, directories |
| `closeout` | Close-out | testing, punch, as-builts |

An item's hours are split across stages by its **category**, through a firm-owned table `CompanyStageSplit(org_id, category, demolition, rough_in, wire_pull, gear, trim, closeout)`, percents summing to 100, matched case-insensitively on `Item.category`. The table is seeded per org on first use with trade-norm defaults and `firm_edited = false`:

| category | demolition | rough-in | wire pull | gear | trim | close-out |
|---|---|---|---|---|---|---|
| Devices | 0 | 45 | 25 | 0 | 25 | 5 |
| Power | 0 | 45 | 25 | 0 | 25 | 5 |
| Lighting / Fixtures | 0 | 25 | 15 | 0 | 55 | 5 |
| Distribution / Equipment | 0 | 20 | 10 | 60 | 5 | 5 |
| Low voltage | 0 | 35 | 35 | 0 | 25 | 5 |
| Boxes | 0 | 90 | 0 | 0 | 5 | 5 |
| Demolition | 100 | 0 | 0 | 0 | 0 | 0 |
| *(any other)* | 0 | 0 | 0 | 0 | 95 | 5 |

The seed values are the product's starting point and are labeled as such everywhere they show: until any row is `firm_edited`, every stage bar carries "Default split — set yours in Company settings." A category with no row uses the *(any other)* row and the item is listed under "N items use the default split" on the screen. The estimator fixes a wrong split once, in the table, and every project follows.

Per stage, the firm also sets its crew and productivity: `CompanyStageCrew(org_id, stage, foreman, journeyman, apprentice, productive_hours_per_day, productivity_factor, max_crew)`. Seed: crews of 1/2/2 for rough-in and wire pull, 1/2/0 for gear, 0/2/2 for trim, 0/1/1 for demolition and close-out; six productive hours a day; factor 1.0; max crew 6. Same `firm_edited` rule.

### 3.4 The company template for phase lines

`CompanyPhaseLineTemplate(org_id, label, percent_of_direct_hours, sort_order)`, seeded with the two lines the firm's workbook carries: "Final and daily cleanup" at 3% and "Project planning, coordination and layout" at 4%. Editable, addable, deletable; a change applies to phases created afterwards and to any existing line still `computed`.

### 3.5 Per-phase overrides

`PhaseStagePlan(phase_id, stage, foreman, journeyman, apprentice, productive_hours_per_day, hours_override, start_date, duration_days, updated_by_user_id, updated_at)` — one row per phase × stage at most, every field nullable and independent, null meaning "computed." The same sparse-override shape as `ProjectLaborLine`, and the same undo coverage.

### 3.6 Project dates

`Project.expected_award_date` and `Project.mobilization_date`, both nullable, both estimator-typed on project settings. Neither is derived from anything. A phase's start defaults to the previous phase's end, or to mobilization for the first; with no date anywhere the axis is relative ("Week 1", "Week 2", …) and the screen says so.

### 3.7 Long-lead items

`ItemLeadTime(item_id, flagged, lead_weeks, source, source_label, quoted_at, needed_for_stage, updated_by_user_id, updated_at)` — one row per item at most.

- **`flagged`** resolves at read time: the row's value when a row exists, otherwise a match of the item's name or description against the distribution-gear subset of `market/classify.py`'s `QUOTE_REQUIRED_WORDS` — switchboard, switchgear, MCC, transformer, generator, ATS, bus duct/busway — plus `panelboard` (added to a separate `LONG_LEAD_WORDS` tuple in `schedule/lead_times.py`, not to the pricing list, so the price job is unchanged). No row is written by the match; a row appears only when the estimator acts on the item. SPDs and VFDs stay quote-required for price and are not flagged for lead time. The estimator can flag or unflag anything.
- **`lead_weeks`** is null until one of two sources fills it: `source = "supplier_quote"` (§7.1) or `source = "estimator"` (typed on the item, with a required `source_label` — who said so — and `quoted_at` defaulting to today). When the item has no weeks of its own, the read resolves a third source, shown as "Company": `CompanyLeadTime(org_id, item_class, lead_weeks, source_label, quoted_at)`, a firm table keyed on the long-lead word that matched. It is never copied onto the item — `ItemLeadTime.source` is only ever `supplier_quote` or `estimator` — so a refreshed company row updates every project.
- **Staleness.** A lead time whose `quoted_at` is older than the org's `lead_time_stale_days` (`CompanyScheduleSettings`, a singleton per org like `CompanyLaborRate`; default 60) reads *Needs attention* on the item with a four-field warning (§5). The date still draws; the marker carries the attention icon.
- **`needed_for_stage`** defaults to `gear` and is editable.

## 4. The arithmetic

All of it in `api/app/schedule/plan.py`, pure functions over plain dataclasses, no database, no dates other than the ones passed in. The router assembles inputs and calls `build_schedule(project, phases, items_with_labor, splits, crews, plans, lead_times, today)`.

1. **Hours per item.** `resolve_labor(...)` as the Labor screen calls it. An item whose labor does not resolve (`status == "missing"`) contributes nothing and is counted: the screen says "N items aren't in the schedule yet — they need labor hours," linking to Labor. A labor override on the Labor screen moves the bar; that is the point of reading through one function.
2. **Split.** `share[stage] = adjusted_hours × split[category][stage] / 100`.
3. **Stage hours per phase.** `Σ share[stage]` over the phase's items, × the stage's `productivity_factor`. Then the phase's general-conditions hours are added to each stage in proportion to its share of direct hours, so the lump-sum lines are on the bars without a seventh bar. `hours_override` on the plan row replaces the computed figure for that stage.
4. **Crew and duration.** `crew = foreman + journeyman + apprentice` (plan row, else company row); `crew_hours_per_day = crew × productive_hours_per_day`; `duration_days = max(1, ceil(hours / crew_hours_per_day))`. A stage with zero hours has no bar. `duration_days` on the plan row replaces the computed figure.
5. **Dates.** Stages run in vocabulary order, each starting the working day after the previous ends; a plan row's `start_date` pins a stage (later stages still follow it). Working days are Monday to Friday; no holidays, no overtime — §12.
6. **The reverse solve.** When a phase has a `required_finish_date`, `plan.py` also returns, per stage, the crew that would meet it with the same stage proportions (`needed_crew = ceil(hours / (days_available × productive_hours))`). The screen shows it beside the computed crew as "to finish by <date>: 5 on rough-in." When `needed_crew > max_crew` the copy is "More than 6 on rough-in to finish by <date> — the window is tighter than one crew can meet," and nothing is applied; applying a suggested crew is an explicit press that writes the plan row.
7. **Manpower.** For each calendar week (or relative week) the schedule spans, sum the crew of every bar active that week, by role, across every phase. Peak and average are stated in text beside the chart.
8. **Order-by.** For each flagged item with `lead_weeks`: `needed_by = start of needed_for_stage in the item's phase`; `order_by = needed_by − lead_weeks × 7 days`. If `order_by < expected_award_date` (or `< today` when award is unset) the marker's copy is "Order date has passed — 40 weeks lead, gear starts <date>"; nothing is compressed to fit.

Rounding: hours to two decimals, days up to the whole day. Every number the screen shows comes from this module; the client never re-derives a duration.

## 5. Status and language

The schedule is not an item and carries no review label. Two words replace the four here, rendered with the `--slate` tier tag the pricing screens use, never a status pill:

- **Computed** — derived from the firm's tables and the resolved hours
- **Yours** — an estimator's override, with who and when on hover

The four labels appear on this screen only where an item's own status appears: the long-lead list shows each item's status pill, and a stale lead time is *Needs attention* on the item, with this warning:

| field | copy |
|---|---|
| title | Lead time may be out of date |
| found | The lead time on this item was quoted <n> days ago by <source_label>. |
| why | Order dates on the timeline are counted from it, and gear lead times are moving. |
| fix | Ask the supplier for a current lead time, or upload their price sheet with the lead-time column filled. |
| where | Phases and schedule, long-lead items; the item's detail panel |

Screen copy rules, as everywhere: sentence case; no exclamation marks; no "AI," "model," or confidence; "computed" and "default" are the words that say where a number came from. The seeded split and crew tables are "the default" and "set yours in Company settings," never "recommended" or "industry standard."

## 6. The screen

`src/components/schedule/`, workspace **Phases and schedule**, slug `schedule`, in the Cost group of `ProjectNav.jsx` after Labor (it reads labor; it feeds export). Built-state true; the badge counts flagged items with no lead time.

```
src/components/schedule/
  ScheduleWorkspace.jsx     the screen: phase list, bars, manpower chart, long-lead list
  PhaseList.jsx             phases as rows: name, sheets, dates, hours; add / rename / reorder / delete; sheet assignment
  StageBars.jsx             the week grid and one bar per stage per phase; order-by markers
  StageEditor.jsx           the bar's editor: crew per role, hours/day, start, duration, hours override, reset
  ManpowerChart.jsx         weekly crew by role, peak and average in text
  LongLeadList.jsx          flagged items: lead weeks, source, order-by; flag/unflag; type a lead time
  stages.js                 the six stages, mirroring api/app/schedule/stages.py
  scheduleCopy.js           every string on the screen, one place
src/components/settings/CompanySettings.jsx   gains "Crews and stages" and "Lead times" tabs
src/components/settings/ProjectSettings.jsx   gains expected award and mobilization dates
src/components/ItemDetailPanel.jsx            gains Phase (when >1 phase) and Long-lead (flag, weeks, source)
src/components/takeoff/spreadsheetColumns.js  gains a Phase column and group-by-phase (when >1 phase)
```

**Phase list.** One row per phase: name, the sheets it covers as chips (click a chip to move it; a multi-select "Assign sheets" control), items moved in or out ("2 items moved in from Phase 1"), start, required finish, direct hours, general-conditions hours with their two lines expandable and editable. Add phase, rename inline, reorder with up/down controls, delete with a confirm that names where the sheets go.

**Stage bars.** A week grid — calendar weeks when the project has a mobilization date, "Week 1…" otherwise — and one row per phase with a bar per stage. A bar's label: stage, hours, crew as "1F 2J 2A", days. A computed bar is solid in `--blue-2`; an overridden bar carries a small "Yours" tag. The empty demolition bar reads "No demolition items yet." Clicking a bar opens `StageEditor` in the right panel with every field and a "Reset to computed" per field. Above each phase's row, order-by markers: a diamond with the item name and date; the attention icon when stale; the "date has passed" copy inline when it applies.

**Manpower chart.** Below the bars, aligned to the same weeks: a stacked bar per week (foreman, journeyman, apprentice), and beside it "Peak 6 on site in week 4; average 4." Sums every phase. No interaction; it is the printout.

**Long-lead list.** Every flagged item: name, phase, status pill, lead weeks with its source tag ("Graybar, Sep 12" / "Company: Eaton rep, Aug 3" / "Not yet quoted"), needed-for stage, order-by. Controls: flag or unflag any item (a search field adds one), type a lead time (weeks, who said so, when), change the stage it is needed for.

**When nothing is scheduled** — no labor resolves, or the project has no items — the screen shows the phase list and one line: "Nothing to schedule yet. Labor hours come from the Labor workspace," with a link.

Every mutation shows the five-second toast with Undo and the top bar's save state, like every workspace.

## 7. Long-lead data sources

### 7.1 The supplier's quote

`market/price_sheet.py`'s `HEADER` gains `Lead time (weeks)` between `Supplier part no.` and `Notes`. The price request writes it blank; the parser reads it as an optional whole number of weeks (blank is nothing; non-numeric lands the row under `unreadable` with "Row 14: the lead time isn't a number of weeks," alongside stream A's per-row handling). The preview's matched rows show the lead time beside the price; apply writes `ItemLeadTime(flagged=True, lead_weeks, source="supplier_quote", source_label=supplier_name, quoted_at=quote_date)` for every ticked row that carries one, in the same `supplier_quote_apply` action, `before`/`after` per row. A sheet without the column is not refused — `REQUIRED_HEADER` is unchanged — so a sheet from before this change applies exactly as before.

### 7.2 The firm's own entry

Company settings gain a **Lead times** tab: item class (one of the long-lead words), weeks, who said so, when. Through `record_company_action`, not undoable. On an item, "Type a lead time" writes `source="estimator"` with the same three fields; that one is undoable (`lead_time_edit`).

### 7.3 Precedence

Item row with `source in ("supplier_quote", "estimator")` → company row for the matched class → nothing. Shown as the source tag. The item row wins because it is this item from this supplier; the company row is the firm's general knowledge.

## 8. Export

`ExportPreview.jsx` and the CSV it writes gain three things, all read from the schedule route so the client sums nothing:

1. **A summary block** when the project has more than one phase: one row per phase — name, `1`, `LS`, total hours, material total — the `SUMMARY BID` shape. Single-phase projects get no block.
2. **Sections per phase** in the detail rows: a phase heading, its general-conditions lines (label, `1`, `LS`, hours), then its items in the order the export already uses. Single-phase projects get the general-conditions lines under one heading and are otherwise unchanged.
3. **A long-lead section** when any item is flagged: item, phase, lead weeks, source, needed-for stage, order-by (or "not yet quoted"). This is Electronate's "state lead times explicitly in the bid" as rows.

The totals the export reconciles against are unchanged and still come from `approved_totals`. The Excel-on-the-firm's-template work is stream C's; this defines the rows and the order.

## 9. The plan-screen handoff (stream F)

Stream F's plan record — what the documents say, for an electrical sub — gains one field this stream consumes:

```python
phases_proposed: list[{"name": str, "sheet_numbers": list[str], "evidence": {"document_id", "page"} | None}]
```

F owns detection — sheet-number families (`E-` against `XE-`), a phasing plan sheet, phased demolition sheets, a phasing paragraph in the specs — and F never creates a phase. This stream owns one route, `POST /projects/{id}/phases/propose`, which takes that list (from F's record, or typed) and returns a preview: the phases that would be created and which sheets would move. The estimator confirms and it lands as one `phase_propose_apply` action carrying every create and assignment, undoable as one. Until F ships, the route exists and the schedule screen's "Propose from sheet numbers" button calls it with the one detector this stream writes itself: group plan sheets by the letters before the first digit, propose a phase per group when there are at least two groups. F replaces the input; the route and the confirm stay.

## 10. API surface

New router `api/app/schedule/router.py`, mounted in `main.py` (append one line), tenancy through `load_project` like every project-scoped route, every mutation through `commit()`:

```
GET    /api/projects/{id}/schedule                       -> ScheduleOut: phases, stage bars, manpower weeks, long-lead rows, unscheduled item count, defaults_in_use flags
POST   /api/projects/{id}/phases                         -> create; body: name, after_phase_id
PATCH  /api/phases/{id}                                  -> name, start_date, required_finish_date, notes, sort_order
DELETE /api/phases/{id}                                  -> moves sheets and overrides to the neighbour; 409 on the last phase
PUT    /api/phases/{id}/sheets                           -> body: sheet_ids; one action, sheets moved in and out
PATCH  /api/items/{id}/phase                             -> body: phase_id | null (null = inherit)
PATCH  /api/phases/{id}/lines/{line_id}                  -> hours | null (null = back to computed)
PUT    /api/phases/{id}/stages/{stage}                   -> the plan row's fields; null clears one
PATCH  /api/items/{id}/lead-time                         -> flagged, lead_weeks, source_label, quoted_at, needed_for_stage
POST   /api/projects/{id}/phases/propose                 -> preview (no write)
POST   /api/projects/{id}/phases/propose/apply           -> the confirmed preview, one action
GET    /api/company/stage-splits   PUT /api/company/stage-splits/{category}   DELETE …/{category}
GET    /api/company/stage-crews    PUT /api/company/stage-crews/{stage}
GET    /api/company/phase-line-templates  PUT/DELETE …/{id}
GET    /api/company/lead-times     PUT/DELETE /api/company/lead-times/{item_class}
```

`ProjectOut` and the project PATCH gain `expected_award_date`, `mobilization_date`. `ItemOut` gains `phase_id` (resolved, never null) and `phase_overridden`. `PriceSheetPreviewOut`'s matched rows gain `lead_weeks`.

Action kinds, all in `undo.REVERSIBLE`: `phase_create`, `phase_edit`, `phase_delete`, `phase_reorder`, `sheet_phase_set`, `item_phase_set`, `phase_line_edit`, `stage_plan_edit`, `lead_time_edit`, `phase_propose_apply`. `supplier_quote_apply` gains lead-time fields in its per-row `before`/`after`. Company edits go through `record_company_action` with kinds `stage_split_edit`, `stage_crew_edit`, `phase_line_template_edit`, `company_lead_time_edit`.

`undo_apply.apply()` gains one branch per kind. `phase_delete`'s snapshot carries the phase row, its lines, its plan rows, and every sheet and item id it moved, so undo restores all of it; `sheet_phase_set` carries `{sheet_id: before_phase_id}` per sheet.

## 11. Data model and migration

One migration, `00XX_phases_and_schedule` (numbered at build time; renumbered at integration to sit behind whatever landed first, as `bbd9757` did):

```python
class Phase(Base):
    __tablename__ = "phases"
    __table_args__ = (UniqueConstraint("project_id", "sort_order", name="uq_phase_order", deferrable=True, initially="DEFERRED"),)
    id, project_id (FK projects CASCADE, index), name: String(200), sort_order: int,
    start_date: Date | None, required_finish_date: Date | None, notes: Text default "",
    created_at, updated_at

class PhaseLine(Base):
    __tablename__ = "phase_lines"
    id, phase_id (FK phases CASCADE, index), kind: String(30) = "general_conditions",
    label: String(200), percent_of_direct_hours: Numeric(5,2),
    hours_override: Numeric(10,2) | None,        # None = computed
    sort_order: int, updated_by_user_id, updated_at

class PhaseStagePlan(Base):
    __tablename__ = "phase_stage_plans"
    __table_args__ = (UniqueConstraint("phase_id", "stage"), CheckConstraint(stage in STAGES))
    id, phase_id (FK phases CASCADE, index), stage: String(20),
    foreman, journeyman, apprentice: int | None,
    productive_hours_per_day: Numeric(4,2) | None,
    hours_override: Numeric(10,2) | None, start_date: Date | None, duration_days: int | None,
    updated_by_user_id, updated_at

class ItemLeadTime(Base):
    __tablename__ = "item_lead_times"
    item_id (PK, FK items CASCADE), flagged: bool, lead_weeks: int | None,
    source: String(20) | None,                    # "supplier_quote" | "estimator"
    source_label: String(200) default "", quoted_at: Date | None,
    needed_for_stage: String(20) default "gear",
    updated_by_user_id, updated_at

class CompanyStageSplit(Base):
    __tablename__ = "company_stage_splits"
    __table_args__ = (UniqueConstraint("org_id", "category_key"),)
    id, org_id (FK orgs CASCADE, index), category_key: String(100),   # casefolded; "*" is the fallback row
    category_label: String(100), demolition, rough_in, wire_pull, gear, trim, closeout: Numeric(5,2),
    firm_edited: bool default false, updated_by_user_id, updated_at
    # CHECK: the six sum to 100

class CompanyStageCrew(Base):
    __tablename__ = "company_stage_crews"
    __table_args__ = (UniqueConstraint("org_id", "stage"),)
    id, org_id, stage: String(20), foreman, journeyman, apprentice: int,
    productive_hours_per_day: Numeric(4,2) default 6, productivity_factor: Numeric(5,3) default 1,
    max_crew: int default 6, firm_edited: bool, updated_by_user_id, updated_at

class CompanyScheduleSettings(Base):
    __tablename__ = "company_schedule_settings"       # singleton per org, like CompanyLaborRate
    org_id (PK), lead_time_stale_days: int default 60, updated_by_user_id, updated_at

class CompanyPhaseLineTemplate(Base):
    __tablename__ = "company_phase_line_templates"
    id, org_id, label: String(200), percent_of_direct_hours: Numeric(5,2), sort_order: int,
    updated_by_user_id, updated_at

class CompanyLeadTime(Base):
    __tablename__ = "company_lead_times"
    __table_args__ = (UniqueConstraint("org_id", "item_class"),)
    id, org_id, item_class: String(50),               # one of LONG_LEAD_WORDS
    lead_weeks: int, source_label: String(200), quoted_at: Date, updated_by_user_id, updated_at
```

Columns added: `sheets.phase_id` (FK phases, `ON DELETE SET NULL`, nullable, index), `items.phase_id` (same), `projects.expected_award_date`, `projects.mobilization_date` (Date, nullable).

`ItemLeadTime` and `Item.phase_id` join `ITEM_SNAPSHOT_TYPES`' neighbours the way `ProjectLaborLine` does: captured by `review._apply_delete()`'s snapshot and restored by `undo_apply._apply_delete()`, because both cascade with the item and both are a person's judgment.

**Backfill: none.** No phase rows are created by the migration; a missing first phase is created on first read (§3.1). The seeds for the company tables are inserted per org by a `schedule/defaults.py::ensure_defaults(db, org_id)` the routes call, not by the migration — an org created after the migration needs them too, and `CompanyLaborRate` is already created on first read the same way.

The merge path (`takeoff/merge.py`) is unchanged: a re-run never touches `phase_id` on a sheet or item it recognises, and a new sheet lands with `phase_id = NULL` (the first phase). A sheet that vanishes from a re-read keeps its phase with its unreadable mark.

## 12. Out of scope, named

- **Calendars beyond Monday to Friday.** No holidays, no six-day weeks, no overtime. A later slice adds a firm calendar; the arithmetic takes working days and does not care where they come from.
- **Dependencies between phases or across stages.** Phases are sequential or dated; stages within a phase are sequential. No overlap of rough-in in area B with trim in area A on the same phase row — that is two phases.
- **Dragging bars.** Dates change in the editor; the bars follow.
- **Importing the GC's schedule** (Procore, MS Project, P6). The required-finish date per phase is the manual version; stream C's connectors are where an import would land.
- **A critical path.** The order-by marker is the one dependency this slice draws.
- **Sub-phases or areas inside a phase.** One level.
- **Per-item stage split overrides.** The category table is the lever; a wrong split is fixed there.
- **The conversation panel proposing phases, crews, or lead times.** Stream E, after this ships; the routes above are what it will propose through.
- **Labor from the market feed** (`ItemMarketPrice.labor_rate_per_unit`) — still stored, still not resolved (`estimate-first-pricing.md` §9).
- **Markup, contingency, or schedule risk pricing.** The estimator's layer, as always.
- **Published lead-time ranges as a fallback.** Deliberately not built (§1).

## 13. Testing

**Pure module (`tests/test_schedule_plan.py`, no database):**
- Split: a 10-hour Devices item lands 4.5 / 2.5 / 0 / 0 / 2.5 / 0.5; an unlisted category lands 9.5 in trim and 0.5 in close-out and is counted as "default split"; a category row that does not sum to 100 is refused at the boundary.
- General conditions: 7% of 100 direct hours is 7 hours spread in proportion; a typed 12 replaces it; null goes back to 7.
- Duration: 40 hours, crew 5, six productive hours → 2 days; 1 hour → 1 day; hours 0 → no bar. A `duration_days` override of 4 wins.
- Dates: stages chain on working days across a weekend; a pinned `start_date` shifts every later stage; no mobilization → relative weeks; a second phase starts the working day after the first ends unless dated.
- Reverse solve: 120 hours in 4 days at 6 h/day → crew 5; in 2 days → crew 10 → over `max_crew` with the plain copy and no write.
- Manpower: two phases overlapping in week 3 sum their crews by role; peak and average are right.
- Order-by: 40 weeks before a gear start of 2027-03-01 → 2026-05-25; award 2026-09-01 → "Order date has passed" copy; no `lead_weeks` → no date, "Not yet quoted."
- Staleness: `quoted_at` 61 days ago with the default → attention, with all four warning fields.

**Routes (`tests/test_schedule_api.py`, `tests/test_tenancy.py` rows for every new route):**
- A project with no phases returns one implicit phase and no `phases` row until a write.
- Create, rename, reorder, delete; delete on the last phase → 409; delete moves sheets and overrides and is undone in one press.
- `PUT …/sheets` moves sheets in and out as one action; an item override survives its sheet moving.
- `PATCH /items/{id}/phase` with null returns to inherit; `ItemOut.phase_overridden` reads true then false.
- Every new kind is in `REVERSIBLE`, undoes, and redoes (`test_undo_redo.py` table rows).
- The propose route returns a preview and writes nothing; apply writes one action; undo removes every created phase and restores every sheet.
- A rival org gets 404 on every new route, phase ids included.

**Invariants:**
- `approved_totals`, the labor list, the material list, and the export rows for a single-phase project are byte-identical before and after the migration and before and after the first phase row is created.
- Assigning every sheet to a second phase changes no total, no status, and no labor row.
- `merge.py`'s re-run leaves `phase_id` untouched on recognised sheets and items.

**Price sheet (`tests/test_market_price_sheet.py`, `tests/test_worker_price_sheet.py`):**
- The request workbook carries the new column blank; a sheet without it still applies; a filled cell lands `lead_weeks` with the supplier and date; "12 wks" is `unreadable` with the row number; apply's `before`/`after` carries the lead-time fields and undo removes them.

**Copy:** every string in `scheduleCopy.js` is sentence case; no string contains a number of weeks that did not come from a row; the seeded tables render "Default" and never "recommended."

**Frontend (`src/components/schedule/*.test.jsx`):** the phase field and column are absent with one phase and present with two; a computed bar shows "Computed" and an overridden one "Yours"; the empty state links to Labor; the long-lead list shows "Not yet quoted" and no date for a flagged item without weeks; `npm run build` passes.

## 14. Open decisions, not resolved here

- **Whether a phase's markup differs from the project's.** The firm's template carries a markup block per phase sheet *and* on the summary, applied once. If a firm bids phases at different margins (a competitive base bid, a fuller alternate), the estimate-summary screen — not built — needs a per-phase markup. Nothing here prevents it; nothing here builds it.
- **Whether the demolition stage should read sheet numbers.** `ED-`/`XED-` sheets are demolition plans by convention. A rule "items on a sheet whose number starts with a demolition prefix land in the demolition stage" would fill the bar on the Gerber set today without a category. It is a Documents-agent question (sheet kind or discipline), and deciding it in a schedule spec would be the wrong place.
- **Whether a lead time from one project's supplier quote should offer itself on the next.** The same question as firm symbol memory (`ROADMAP.md`); the company lead-time table is the deliberate, dated version until that policy exists.
