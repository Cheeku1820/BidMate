# Phases and timeline — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-09-21
**Status:** Written with the spec; the build starts after stream A merges (`docs/roadmap/workstreams-2026-09.md` §4, merge order A → B → F → C → D → E). Do not start Task 1 before that.

**Goal:** Give every project phases that roll up like the firm's summary sheet, a per-phase stage timeline derived from the labor hours the product already resolves, a weekly manpower chart summed from it, and order-by dates for long-lead gear whose lead time a supplier or the firm has actually quoted.

**Architecture:** A new `api/app/schedule/` package owns the phase records, the pure derivation (`plan.py`, no database), the company defaults, and one router; nothing in it changes a quantity, a status, or a total. The client gets `src/components/schedule/` — a workspace that renders what `GET /schedule` returns and never re-derives a number — plus small additions to the item panel, the spreadsheet, settings, and the export preview. Every project-level write goes through `actions.commit()` and is undoable; every company-level write goes through `record_company_action()` and is not.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + pytest on the API; React 18 function components, plain CSS tokens, `lucide-react`, vitest + testing-library on the client. No new dependency.

Spec: [`docs/specs/phases-and-timeline.md`](../specs/phases-and-timeline.md). Read it first; every task cites the section it implements. Evidence: [`docs/roadmap/phasing-research.md`](../roadmap/phasing-research.md).

## Global constraints

From the spec and `CLAUDE.md`; every task inherits them.

- Nothing here changes what is counted. `totals.countable_items` stays the one predicate; no task adds a `WHERE phase_id` to a totals query. Hiding a phase on screen never changes a total.
- Every computed value is a baseline the estimator overrides. Overrides are stored on their own nullable columns (null = computed), shown as "Yours" with who and when; computed values are shown as "Computed". Never the four review labels for either — a `--slate` tier tag, as the pricing screens use.
- A lead time comes only from `ItemLeadTime.source in ("supplier_quote", "estimator")` or a `CompanyLeadTime` row. No string in the codebase carries a number of weeks that did not come from a row. No published industry range anywhere in the product.
- Stage vocabulary is exactly `demolition, rough_in, wire_pull, gear, trim, closeout`, defined once in `api/app/schedule/stages.py` and mirrored in `src/components/schedule/stages.js`. No seventh stage.
- Working days are Monday to Friday. No holidays, no overtime, no dragging bars, no critical path, no sub-phases (spec §12).
- Every project-scoped mutation calls `actions.commit()` with a kind from `undo.REVERSIBLE`; every company-scoped mutation calls `record_company_action()`. The action log is append-only.
- Every warning carries `title, found, why, fix, where`. Sentence case everywhere; no exclamation marks, no "successfully", no "please", no "recommended" or "industry standard" for the seeded defaults — they are "the default".
- Plain CSS tokens appended to `src/styles.css` under `/* ==== schedule ==== */`. No inline hex. `lucide-react` icons only. Tabular numerals on every number.
- Shared files (`models.py`, `schemas.py`, `main.py`, `routes.jsx`, `ProjectNav.jsx`, `test_tenancy.py`) are appended to, never reordered (`workstreams-2026-09.md` §4).
- The migration is written as `0026_phases_and_schedule.py` and renumbered at integration behind whatever landed first. One Alembic head at a time.
- `npm run build` passes before every commit that touches `src/`. The corpus under `bid_examples/` is never committed and no price from it appears anywhere.

## How to run things

Backend, from `api/` in this worktree (the compose Postgres must be up: `docker compose up -d postgres` from the repo root). `api/.env` already carries a `TEST_DATABASE_URL` unique to this stream (`takeoff_test_stream_d`):

```bash
cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_plan.py
```

Frontend, from the repo root:

```bash
npx vitest run src/components/schedule
```

```bash
npm run build
```

Commit messages: a plain sentence, a blank line, then `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Never `git add -A`; name the files.

## File map

| File | Responsibility |
|---|---|
| `api/app/schedule/__init__.py` | package marker |
| `api/app/schedule/stages.py` | `STAGES`, `STAGE_LABELS`, `LONG_LEAD_WORDS`, `long_lead_class(text)` |
| `api/app/schedule/defaults.py` | `ensure_defaults(db, org_id)` — seeds the four company tables once per org; the seed tables themselves |
| `api/app/schedule/plan.py` | pure derivation: dataclasses in, `Schedule` out; no database, no `date.today()` |
| `api/app/schedule/phases.py` | `first_phase`, `phase_of`, `resolved_phase_ids`, and the phase mutations (create, rename, reorder, delete, assign sheets, item override, propose, apply) |
| `api/app/schedule/overrides.py` | phase-line and stage-plan edits, lead-time edits |
| `api/app/schedule/assemble.py` | `build_schedule_out(db, project, user, today)` — gathers rows, calls `plan.build_schedule`, shapes `ScheduleOut` |
| `api/app/schedule/schemas.py` | every `…In` / `…Out` for the schedule router |
| `api/app/schedule/router.py` | the routes in spec §10; mounted by one appended line in `main.py` |
| `api/app/schedule/copy.py` | the stale-lead-time warning, the order-date-passed sentence, the default-split sentence |
| `api/app/takeoff/models.py` | appended: the eight new models and the four new columns |
| `api/app/takeoff/undo.py` | `REVERSIBLE` gains the ten new kinds |
| `api/app/takeoff/undo_apply.py` | one branch per new kind, dispatching to `schedule.undo_apply` |
| `api/app/schedule/undo_apply.py` | the compensating writes for each schedule kind |
| `api/app/takeoff/review.py`, `undo_apply._apply_delete` | delete snapshot captures `ItemLeadTime` and `Item.phase_id` |
| `api/app/takeoff/schemas.py` | `ItemOut` gains `phase_id`, `phase_overridden`; `ProjectOut`/patch gain the two dates; `PriceSheetPreviewOut` rows gain `lead_weeks` |
| `api/app/market/price_sheet.py`, `api/app/takeoff/price_sheet_router.py` | the `Lead time (weeks)` column, parsed and applied |
| `api/migrations/versions/0026_phases_and_schedule.py` | the tables and columns in spec §11 |
| `api/tests/test_schedule_plan.py` | the pure module |
| `api/tests/test_schedule_models.py` | models, defaults, constraints |
| `api/tests/test_schedule_phases.py` | phase mutations, undo, invariants |
| `api/tests/test_schedule_api.py` | routes end to end |
| `api/tests/test_tenancy.py`, `api/tests/test_undo_redo.py` | appended rows |
| `src/components/schedule/stages.js` | the six stages, labels, order |
| `src/components/schedule/scheduleCopy.js` | every string on the screen |
| `src/components/schedule/ScheduleWorkspace.jsx` | the screen |
| `src/components/schedule/PhaseList.jsx` | phases, sheet assignment, general-conditions lines |
| `src/components/schedule/StageBars.jsx` | the week grid, bars, order-by markers |
| `src/components/schedule/StageEditor.jsx` | one bar's fields with reset |
| `src/components/schedule/ManpowerChart.jsx` | weekly crew by role |
| `src/components/schedule/LongLeadList.jsx` | flagged items and their lead times |
| `src/lib/store/api.js`, `api-mapping.js` | the schedule surface |
| `src/routes.jsx`, `src/components/shell/ProjectNav.jsx` | one route, one nav entry |
| `src/components/ItemDetailPanel.jsx` | Phase field (when >1 phase), Long-lead block |
| `src/components/takeoff/spreadsheetColumns.js`, `TakeoffSpreadsheet.jsx` | Phase column and group-by (when >1 phase) |
| `src/components/settings/CompanySettings.jsx` | "Crews and stages", "Lead times" tabs |
| `src/components/settings/ProjectSettings.jsx` | expected award, mobilization |
| `src/components/export/ExportPreview.jsx` | phase summary block, per-phase sections, long-lead section |
| `src/styles.css` | appended `/* ==== schedule ==== */` block |

---

### Task 1: Stage vocabulary, models, migration

**Files:**
- Create: `api/app/schedule/__init__.py`, `api/app/schedule/stages.py`
- Modify: `api/app/takeoff/models.py` (append after `ItemMarketPrice`), `api/app/takeoff/models.py::Project` (two columns), `::Sheet`, `::Item` (one column each)
- Create: `api/migrations/versions/0026_phases_and_schedule.py`
- Test: `api/tests/test_schedule_models.py`

**Interfaces:**
- Produces: `STAGES: tuple[str, ...]`, `STAGE_LABELS: dict[str, str]`, `LONG_LEAD_WORDS: tuple[str, ...]`, `long_lead_class(text: str) -> str | None`; models `Phase, PhaseLine, PhaseStagePlan, ItemLeadTime, CompanyStageSplit, CompanyStageCrew, CompanyScheduleSettings, CompanyPhaseLineTemplate, CompanyLeadTime`; columns `Sheet.phase_id`, `Item.phase_id`, `Project.expected_award_date`, `Project.mobilization_date`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_schedule_models.py
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.schedule.stages import LONG_LEAD_WORDS, STAGES, STAGE_LABELS, long_lead_class
from app.takeoff.models import (
    CompanyStageSplit, ItemLeadTime, Phase, PhaseLine, PhaseStagePlan, Sheet, Item,
)


def test_six_stages_in_order():
    assert STAGES == ("demolition", "rough_in", "wire_pull", "gear", "trim", "closeout")
    assert STAGE_LABELS["rough_in"] == "Rough-in"
    assert STAGE_LABELS["closeout"] == "Close-out"


@pytest.mark.parametrize("text,expected", [
    ("Switch Board MSBS", "switchboard"),
    ("Standby Generators 150kW", "generator"),
    ("Panelboard LP-2, 42 circuit", "panelboard"),
    ("Furnish & install new setup transformer", "transformer"),
    ("ATS-1 automatic transfer switch", "ats"),
    ("S.P.D (Surge Protective Device)", None),
    ("VFD for exhaust fan", None),
    ("20A duplex receptacle", None),
])
def test_long_lead_class(text, expected):
    assert long_lead_class(text) == expected


def test_spd_and_vfd_are_not_long_lead_words():
    assert "spd" not in LONG_LEAD_WORDS and "vfd" not in LONG_LEAD_WORDS


def test_phase_rows_and_columns(db, project, sheet, item):
    phase = Phase(project_id=project.id, name="Phase 1", sort_order=0)
    db.add(phase); db.flush()
    sheet.phase_id = phase.id
    item.phase_id = None
    db.add(PhaseLine(phase_id=phase.id, label="Final and daily cleanup", percent_of_direct_hours=Decimal("3"), sort_order=0))
    db.add(PhaseStagePlan(phase_id=phase.id, stage="rough_in", journeyman=3))
    db.add(ItemLeadTime(item_id=item.id, flagged=True))
    db.flush()
    assert db.get(ItemLeadTime, item.id).needed_for_stage == "gear"
    assert db.get(ItemLeadTime, item.id).lead_weeks is None


def test_stage_plan_rejects_unknown_stage(db, project):
    phase = Phase(project_id=project.id, name="Phase 1", sort_order=0)
    db.add(phase); db.flush()
    db.add(PhaseStagePlan(phase_id=phase.id, stage="painting"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_split_must_sum_to_100(db, org):
    db.add(CompanyStageSplit(org_id=org.id, category_key="devices", category_label="Devices",
                             demolition=0, rough_in=45, wire_pull=25, gear=0, trim=25, closeout=4))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_deleting_a_phase_nulls_sheet_and_item_references(db, project, sheet, item):
    phase = Phase(project_id=project.id, name="Phase 2", sort_order=1)
    db.add(phase); db.flush()
    sheet.phase_id = phase.id; item.phase_id = phase.id; db.flush()
    db.delete(phase); db.flush()
    db.refresh(sheet); db.refresh(item)
    assert sheet.phase_id is None and item.phase_id is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_models.py`
Expected: FAIL — `ModuleNotFoundError: app.schedule`

- [ ] **Step 3: Write `stages.py`**

```python
# api/app/schedule/stages.py
"""The six stages of electrical work, in the order they run per area
(phasing-research.md §4, §7). A fixed vocabulary, not a table: the
schedule's arithmetic, its undo snapshots, and the client's grid all
index by these keys. Mirrored by src/components/schedule/stages.js.

LONG_LEAD_WORDS is deliberately a subset of market.classify's
QUOTE_REQUIRED_WORDS -- SPDs and VFDs are priced by quote but are not
schedule-driving gear -- plus "panelboard", which the price job treats
as a catalog item. Kept apart so a change here never changes what the
price job does."""
import re

STAGES: tuple[str, ...] = ("demolition", "rough_in", "wire_pull", "gear", "trim", "closeout")

STAGE_LABELS: dict[str, str] = {
    "demolition": "Demolition",
    "rough_in": "Rough-in",
    "wire_pull": "Wire pull",
    "gear": "Gear",
    "trim": "Trim",
    "closeout": "Close-out",
}

# (class key, the words that name it). Order matters: the first class
# whose pattern matches wins, so "switchboard" is tried before the
# looser "switch" would ever be (it is not a word here at all).
LONG_LEAD_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("switchboard", ("switchboard", "switch board")),
    ("switchgear", ("switchgear",)),
    ("mcc", ("mcc", "motor control center")),
    ("transformer", ("transformer",)),
    ("generator", ("generator",)),
    ("ats", ("ats", "automatic transfer")),
    ("busway", ("bus duct", "busway")),
    ("panelboard", ("panelboard", "panel board")),
)

LONG_LEAD_WORDS: tuple[str, ...] = tuple(key for key, _ in LONG_LEAD_CLASSES)


def _pattern(word: str) -> str:
    return re.escape(word) + (r"s?" if " " not in word else "")


_CLASS_RES = tuple(
    (key, re.compile(r"\b(" + "|".join(_pattern(w) for w in words) + r")\b", re.IGNORECASE))
    for key, words in LONG_LEAD_CLASSES
)


def long_lead_class(text: str) -> str | None:
    """The long-lead class an item's name or description names, or None.
    Read-time only -- nothing writes a row because of this."""
    for key, regex in _CLASS_RES:
        if regex.search(text or ""):
            return key
    return None
```

- [ ] **Step 4: Append the models**

Append to `api/app/takeoff/models.py` after `ItemMarketPrice` (import `STAGES` at the top of the file: `from app.schedule.stages import STAGES` — `app.schedule.stages` imports nothing from `app`, so there is no cycle):

```python
_STAGE_CHECK = "stage in ('" + "', '".join(STAGES) + "')"


class Phase(Base):
    """One area or stage of a job the GC has split the bid into
    (phases-and-timeline.md §3.1). A grouping of sheets and items that
    already exist; owns no quantity and no status. The first phase is
    implicit -- a project with no rows behaves exactly as before."""

    __tablename__ = "phases"
    __table_args__ = (
        UniqueConstraint("project_id", "sort_order", name="uq_phase_order", deferrable=True, initially="DEFERRED"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    required_finish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PhaseLine(Base):
    """A general-conditions lump sum per phase, from the firm's template
    (§3.2). Hours are computed from `percent_of_direct_hours` until the
    estimator types `hours_override`."""

    __tablename__ = "phase_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("phases.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="general_conditions", server_default="general_conditions")
    label: Mapped[str] = mapped_column(String(200))
    percent_of_direct_hours: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    hours_override: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PhaseStagePlan(Base):
    """Sparse per-phase overrides of one stage's crew, hours, and dates
    (§3.5). Every field nullable and independent; null is 'computed'.
    Same shape and undo coverage as ProjectLaborLine."""

    __tablename__ = "phase_stage_plans"
    __table_args__ = (
        UniqueConstraint("phase_id", "stage", name="uq_phase_stage"),
        CheckConstraint(_STAGE_CHECK, name="ck_phase_stage_plans_stage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("phases.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    foreman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    journeyman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    apprentice: Mapped[int | None] = mapped_column(Integer, nullable=True)
    productive_hours_per_day: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    hours_override: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ItemLeadTime(Base):
    """The long-lead flag and quoted lead time on one item (§3.7). One
    row at most; `source` is only ever a supplier's quote or the
    estimator's own dated entry -- the company table is resolved at read
    time and never copied here. Cascades with the item, so the delete
    snapshot captures it and undo restores it."""

    __tablename__ = "item_lead_times"
    __table_args__ = (
        CheckConstraint("needed_for_" + _STAGE_CHECK, name="ck_item_lead_times_stage"),
        CheckConstraint("source is null or source in ('supplier_quote', 'estimator')", name="ck_item_lead_times_source"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    lead_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_label: Mapped[str] = mapped_column(String(200), default="", server_default="")
    quoted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    needed_for_stage: Mapped[str] = mapped_column(String(20), default="gear", server_default="gear")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyStageSplit(Base):
    """How an item category's hours divide across the six stages (§3.3).
    `category_key` is casefolded; "*" is the fallback row. Seeded per
    org by schedule.defaults with firm_edited = false, which the screen
    reads as 'default split -- set yours'."""

    __tablename__ = "company_stage_splits"
    __table_args__ = (
        UniqueConstraint("org_id", "category_key", name="uq_company_stage_split"),
        CheckConstraint("demolition + rough_in + wire_pull + gear + trim + closeout = 100", name="ck_company_stage_split_sum"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    category_key: Mapped[str] = mapped_column(String(100))
    category_label: Mapped[str] = mapped_column(String(100))
    demolition: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    rough_in: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    wire_pull: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    gear: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    trim: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    closeout: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    firm_edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyStageCrew(Base):
    """The firm's default crew and productivity per stage (§3.3)."""

    __tablename__ = "company_stage_crews"
    __table_args__ = (
        UniqueConstraint("org_id", "stage", name="uq_company_stage_crew"),
        CheckConstraint(_STAGE_CHECK, name="ck_company_stage_crews_stage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    foreman: Mapped[int] = mapped_column(Integer, default=0)
    journeyman: Mapped[int] = mapped_column(Integer, default=0)
    apprentice: Mapped[int] = mapped_column(Integer, default=0)
    productive_hours_per_day: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=6, server_default="6")
    productivity_factor: Mapped[Decimal] = mapped_column(Numeric(5, 3), default=1, server_default="1")
    max_crew: Mapped[int] = mapped_column(Integer, default=6, server_default="6")
    firm_edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyScheduleSettings(Base):
    """Singleton per org, like CompanyLaborRate (§3.7)."""

    __tablename__ = "company_schedule_settings"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True)
    lead_time_stale_days: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyPhaseLineTemplate(Base):
    """The general-conditions lines every new phase starts with (§3.4)."""

    __tablename__ = "company_phase_line_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    percent_of_direct_hours: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyLeadTime(Base):
    """The firm's own dated lead time per long-lead class (§7.2)."""

    __tablename__ = "company_lead_times"
    __table_args__ = (UniqueConstraint("org_id", "item_class", name="uq_company_lead_time"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    item_class: Mapped[str] = mapped_column(String(50))
    lead_weeks: Mapped[int] = mapped_column(Integer)
    source_label: Mapped[str] = mapped_column(String(200))
    quoted_at: Mapped[date] = mapped_column(Date)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

And the four columns, appended at the end of each class body:

```python
# Project
    # Phases-and-timeline §3.6: both estimator-typed, neither derived.
    expected_award_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    mobilization_date: Mapped[date | None] = mapped_column(Date, nullable=True)

# Sheet
    # Which phase this sheet's items belong to (§3.1). NULL reads as the
    # project's first phase; SET NULL on phase delete so a sheet is never
    # orphaned by a cascade the service did not plan.
    phase_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("phases.id", ondelete="SET NULL"), nullable=True, index=True)

# Item
    # A per-item phase override (§3.1). NULL inherits the sheet's phase.
    # A person's judgment: captured by the delete snapshot like
    # ProjectLaborLine, and never touched by merge.py.
    phase_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("phases.id", ondelete="SET NULL"), nullable=True, index=True)
```

- [ ] **Step 5: Write the migration**

```python
# api/migrations/versions/0026_phases_and_schedule.py
"""phases_and_schedule

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-21 00:00:00.000000

Written as 0026 on the stream-D branch; renumber at integration to sit
behind whatever landed first, as 0025 was.

docs/specs/phases-and-timeline.md §11: phases, phase lines, stage
plans, item lead times, the four company tables, the singleton
settings row, and four columns. No backfill: the first phase is
created on first read, and the company seeds are inserted per org by
app.schedule.defaults.ensure_defaults, never here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0026'
down_revision: Union[str, None] = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STAGES = "'demolition', 'rough_in', 'wire_pull', 'gear', 'trim', 'closeout'"


def _audit_cols():
    return [
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'phases',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('start_date', sa.Date, nullable=True),
        sa.Column('required_finish_date', sa.Date, nullable=True),
        sa.Column('notes', sa.Text, nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'sort_order', name='uq_phase_order', deferrable=True, initially='DEFERRED'),
    )
    op.create_table(
        'phase_lines',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('phase_id', UUID(as_uuid=True), sa.ForeignKey('phases.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(30), nullable=False, server_default='general_conditions'),
        sa.Column('label', sa.String(200), nullable=False),
        sa.Column('percent_of_direct_hours', sa.Numeric(5, 2), nullable=False),
        sa.Column('hours_override', sa.Numeric(10, 2), nullable=True),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        *_audit_cols(),
    )
    op.create_table(
        'phase_stage_plans',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('phase_id', UUID(as_uuid=True), sa.ForeignKey('phases.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('stage', sa.String(20), nullable=False),
        sa.Column('foreman', sa.Integer, nullable=True),
        sa.Column('journeyman', sa.Integer, nullable=True),
        sa.Column('apprentice', sa.Integer, nullable=True),
        sa.Column('productive_hours_per_day', sa.Numeric(4, 2), nullable=True),
        sa.Column('hours_override', sa.Numeric(10, 2), nullable=True),
        sa.Column('start_date', sa.Date, nullable=True),
        sa.Column('duration_days', sa.Integer, nullable=True),
        *_audit_cols(),
        sa.UniqueConstraint('phase_id', 'stage', name='uq_phase_stage'),
        sa.CheckConstraint(f"stage in ({_STAGES})", name='ck_phase_stage_plans_stage'),
    )
    op.create_table(
        'item_lead_times',
        sa.Column('item_id', UUID(as_uuid=True), sa.ForeignKey('items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('flagged', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('lead_weeks', sa.Integer, nullable=True),
        sa.Column('source', sa.String(20), nullable=True),
        sa.Column('source_label', sa.String(200), nullable=False, server_default=''),
        sa.Column('quoted_at', sa.Date, nullable=True),
        sa.Column('needed_for_stage', sa.String(20), nullable=False, server_default='gear'),
        *_audit_cols(),
        sa.CheckConstraint(f"needed_for_stage in ({_STAGES})", name='ck_item_lead_times_stage'),
        sa.CheckConstraint("source is null or source in ('supplier_quote', 'estimator')", name='ck_item_lead_times_source'),
    )
    op.create_table(
        'company_stage_splits',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('category_key', sa.String(100), nullable=False),
        sa.Column('category_label', sa.String(100), nullable=False),
        *[sa.Column(s, sa.Numeric(5, 2), nullable=False, server_default='0') for s in ('demolition', 'rough_in', 'wire_pull', 'gear', 'trim', 'closeout')],
        sa.Column('firm_edited', sa.Boolean, nullable=False, server_default='false'),
        *_audit_cols(),
        sa.UniqueConstraint('org_id', 'category_key', name='uq_company_stage_split'),
        sa.CheckConstraint('demolition + rough_in + wire_pull + gear + trim + closeout = 100', name='ck_company_stage_split_sum'),
    )
    op.create_table(
        'company_stage_crews',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('stage', sa.String(20), nullable=False),
        sa.Column('foreman', sa.Integer, nullable=False, server_default='0'),
        sa.Column('journeyman', sa.Integer, nullable=False, server_default='0'),
        sa.Column('apprentice', sa.Integer, nullable=False, server_default='0'),
        sa.Column('productive_hours_per_day', sa.Numeric(4, 2), nullable=False, server_default='6'),
        sa.Column('productivity_factor', sa.Numeric(5, 3), nullable=False, server_default='1'),
        sa.Column('max_crew', sa.Integer, nullable=False, server_default='6'),
        sa.Column('firm_edited', sa.Boolean, nullable=False, server_default='false'),
        *_audit_cols(),
        sa.UniqueConstraint('org_id', 'stage', name='uq_company_stage_crew'),
        sa.CheckConstraint(f"stage in ({_STAGES})", name='ck_company_stage_crews_stage'),
    )
    op.create_table(
        'company_schedule_settings',
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('lead_time_stale_days', sa.Integer, nullable=False, server_default='60'),
        *_audit_cols(),
    )
    op.create_table(
        'company_phase_line_templates',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('label', sa.String(200), nullable=False),
        sa.Column('percent_of_direct_hours', sa.Numeric(5, 2), nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        *_audit_cols(),
    )
    op.create_table(
        'company_lead_times',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_class', sa.String(50), nullable=False),
        sa.Column('lead_weeks', sa.Integer, nullable=False),
        sa.Column('source_label', sa.String(200), nullable=False),
        sa.Column('quoted_at', sa.Date, nullable=False),
        *_audit_cols(),
        sa.UniqueConstraint('org_id', 'item_class', name='uq_company_lead_time'),
    )
    op.add_column('sheets', sa.Column('phase_id', UUID(as_uuid=True), sa.ForeignKey('phases.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_sheets_phase_id', 'sheets', ['phase_id'])
    op.add_column('items', sa.Column('phase_id', UUID(as_uuid=True), sa.ForeignKey('phases.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_items_phase_id', 'items', ['phase_id'])
    op.add_column('projects', sa.Column('expected_award_date', sa.Date, nullable=True))
    op.add_column('projects', sa.Column('mobilization_date', sa.Date, nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'mobilization_date')
    op.drop_column('projects', 'expected_award_date')
    op.drop_index('ix_items_phase_id', table_name='items')
    op.drop_column('items', 'phase_id')
    op.drop_index('ix_sheets_phase_id', table_name='sheets')
    op.drop_column('sheets', 'phase_id')
    for table in ('company_lead_times', 'company_phase_line_templates', 'company_schedule_settings',
                  'company_stage_crews', 'company_stage_splits', 'item_lead_times',
                  'phase_stage_plans', 'phase_lines', 'phases'):
        op.drop_table(table)
```

- [ ] **Step 6: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_models.py tests/test_takeoff_models.py tests/test_api_import_boundary.py tests/test_worker_import_boundary.py`
Expected: PASS. The two import-boundary tests must still pass — `app.schedule.stages` imports only `re`.

- [ ] **Step 7: Check the migration chain**

Run: `cd api && ../.enginevenv/bin/python -m alembic heads`
Expected: one head, `0026`. Do not run `upgrade head` against the shared dev database from this worktree (`workstreams-2026-09.md` §4).

- [ ] **Step 8: Commit**

```bash
git add api/app/schedule/__init__.py api/app/schedule/stages.py api/app/takeoff/models.py api/migrations/versions/0026_phases_and_schedule.py api/tests/test_schedule_models.py
git commit -m "Schedule: the six stages, the phase and lead-time models, and their migration

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Company defaults, seeded once per org

**Files:**
- Create: `api/app/schedule/defaults.py`
- Test: `api/tests/test_schedule_models.py` (append)

**Interfaces:**
- Consumes: the models from Task 1.
- Produces: `ensure_defaults(db, org_id) -> None` (idempotent), `SPLIT_SEED`, `CREW_SEED`, `TEMPLATE_SEED`, and `load_company(db, org_id) -> CompanyTables` where `CompanyTables` is a dataclass `(splits: dict[str, CompanyStageSplit], crews: dict[str, CompanyStageCrew], settings: CompanyScheduleSettings, templates: list[CompanyPhaseLineTemplate], lead_times: dict[str, CompanyLeadTime])`.

- [ ] **Step 1: Write the failing tests**

```python
# append to api/tests/test_schedule_models.py
from app.schedule.defaults import ensure_defaults, load_company


def test_ensure_defaults_seeds_once(db, org):
    ensure_defaults(db, org.id)
    ensure_defaults(db, org.id)
    tables = load_company(db, org.id)
    assert set(tables.crews) == set(STAGES)
    assert "*" in tables.splits and "devices" in tables.splits
    assert all(not s.firm_edited for s in tables.splits.values())
    assert [t.label for t in tables.templates] == ["Final and daily cleanup", "Project planning, coordination and layout"]
    assert tables.settings.lead_time_stale_days == 60
    assert tables.lead_times == {}


def test_ensure_defaults_keeps_a_firm_edit(db, org):
    ensure_defaults(db, org.id)
    row = load_company(db, org.id).splits["devices"]
    row.rough_in, row.trim, row.firm_edited = Decimal("50"), Decimal("20"), True
    db.flush()
    ensure_defaults(db, org.id)
    assert load_company(db, org.id).splits["devices"].rough_in == Decimal("50")
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_models.py -k defaults`
Expected: FAIL — `ImportError: app.schedule.defaults`

- [ ] **Step 3: Write `defaults.py`**

```python
# api/app/schedule/defaults.py
"""The firm's starting tables (phases-and-timeline.md §3.3-§3.4),
inserted once per org on first use -- never by the migration, because an
org created afterwards needs them too. A row that exists is left alone,
firm-edited or not: the seed fills gaps and never overwrites.

Every number here is 'the default' in the product's words -- not
'recommended', not 'industry standard'. The screen says so until a
row is firm_edited."""
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.schedule.stages import STAGES
from app.takeoff.models import (
    CompanyLeadTime, CompanyPhaseLineTemplate, CompanyScheduleSettings, CompanyStageCrew, CompanyStageSplit,
)

# category_label -> (demolition, rough_in, wire_pull, gear, trim, closeout)
SPLIT_SEED: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("Devices", (0, 45, 25, 0, 25, 5)),
    ("Power", (0, 45, 25, 0, 25, 5)),
    ("Lighting", (0, 25, 15, 0, 55, 5)),
    ("Fixtures", (0, 25, 15, 0, 55, 5)),
    ("Distribution", (0, 20, 10, 60, 5, 5)),
    ("Equipment", (0, 20, 10, 60, 5, 5)),
    ("Low voltage", (0, 35, 35, 0, 25, 5)),
    ("Boxes", (0, 90, 0, 0, 5, 5)),
    ("Demolition", (100, 0, 0, 0, 0, 0)),
    ("*", (0, 0, 0, 0, 95, 5)),
)

# stage -> (foreman, journeyman, apprentice)
CREW_SEED: dict[str, tuple[int, int, int]] = {
    "demolition": (0, 1, 1),
    "rough_in": (1, 2, 2),
    "wire_pull": (1, 2, 2),
    "gear": (1, 2, 0),
    "trim": (0, 2, 2),
    "closeout": (0, 1, 1),
}

TEMPLATE_SEED: tuple[tuple[str, str], ...] = (
    ("Final and daily cleanup", "3"),
    ("Project planning, coordination and layout", "4"),
)

FALLBACK_KEY = "*"


def category_key(label: str) -> str:
    return (label or "").strip().casefold() or FALLBACK_KEY


@dataclass
class CompanyTables:
    splits: dict[str, CompanyStageSplit] = field(default_factory=dict)
    crews: dict[str, CompanyStageCrew] = field(default_factory=dict)
    settings: CompanyScheduleSettings | None = None
    templates: list[CompanyPhaseLineTemplate] = field(default_factory=list)
    lead_times: dict[str, CompanyLeadTime] = field(default_factory=dict)


def ensure_defaults(db: DbSession, org_id: uuid.UUID) -> None:
    have = {s.category_key for s in db.scalars(select(CompanyStageSplit).where(CompanyStageSplit.org_id == org_id))}
    for label, pct in SPLIT_SEED:
        key = category_key(label)
        if key not in have:
            d, r, w, g, t, c = (Decimal(p) for p in pct)
            db.add(CompanyStageSplit(org_id=org_id, category_key=key, category_label=label,
                                     demolition=d, rough_in=r, wire_pull=w, gear=g, trim=t, closeout=c))
    have = {c.stage for c in db.scalars(select(CompanyStageCrew).where(CompanyStageCrew.org_id == org_id))}
    for stage in STAGES:
        if stage not in have:
            f, j, a = CREW_SEED[stage]
            db.add(CompanyStageCrew(org_id=org_id, stage=stage, foreman=f, journeyman=j, apprentice=a))
    if db.get(CompanyScheduleSettings, org_id) is None:
        db.add(CompanyScheduleSettings(org_id=org_id))
    if not db.scalars(select(CompanyPhaseLineTemplate).where(CompanyPhaseLineTemplate.org_id == org_id)).first():
        for order, (label, pct) in enumerate(TEMPLATE_SEED):
            db.add(CompanyPhaseLineTemplate(org_id=org_id, label=label, percent_of_direct_hours=Decimal(pct), sort_order=order))
    db.flush()


def load_company(db: DbSession, org_id: uuid.UUID) -> CompanyTables:
    ensure_defaults(db, org_id)
    return CompanyTables(
        splits={s.category_key: s for s in db.scalars(select(CompanyStageSplit).where(CompanyStageSplit.org_id == org_id))},
        crews={c.stage: c for c in db.scalars(select(CompanyStageCrew).where(CompanyStageCrew.org_id == org_id))},
        settings=db.get(CompanyScheduleSettings, org_id),
        templates=list(db.scalars(select(CompanyPhaseLineTemplate).where(CompanyPhaseLineTemplate.org_id == org_id).order_by(CompanyPhaseLineTemplate.sort_order))),
        lead_times={l.item_class: l for l in db.scalars(select(CompanyLeadTime).where(CompanyLeadTime.org_id == org_id))},
    )
```

- [ ] **Step 4: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_models.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/schedule/defaults.py api/tests/test_schedule_models.py
git commit -m "Schedule: seed the firm's stage splits, crews, templates, and settings once per org

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The pure derivation — split, hours, duration, dates

**Files:**
- Create: `api/app/schedule/plan.py`
- Test: `api/tests/test_schedule_plan.py`

**Interfaces:**
- Consumes: nothing from the database. Plain dataclasses only.
- Produces (all in `plan.py`):

```python
@dataclass(frozen=True)
class ItemHours:            # one countable item whose labor resolved
    item_id: uuid.UUID; phase_id: uuid.UUID; category: str; adjusted_hours: Decimal

@dataclass(frozen=True)
class SplitRule:            # one CompanyStageSplit row, as percents
    percents: dict[str, Decimal]; firm_edited: bool

@dataclass(frozen=True)
class CrewRule:             # one CompanyStageCrew row
    foreman: int; journeyman: int; apprentice: int
    productive_hours_per_day: Decimal; productivity_factor: Decimal; max_crew: int; firm_edited: bool

@dataclass(frozen=True)
class StageOverride:        # one PhaseStagePlan row; every field optional
    foreman: int | None = None; journeyman: int | None = None; apprentice: int | None = None
    productive_hours_per_day: Decimal | None = None; hours_override: Decimal | None = None
    start_date: date | None = None; duration_days: int | None = None

@dataclass(frozen=True)
class PhaseInput:
    phase_id: uuid.UUID; name: str; sort_order: int
    start_date: date | None; required_finish_date: date | None
    line_percents: list[tuple[uuid.UUID, str, Decimal, Decimal | None]]   # (line_id, label, percent, hours_override)
    overrides: dict[str, StageOverride]

@dataclass
class StageBar:
    stage: str; hours: Decimal; foreman: int; journeyman: int; apprentice: int
    productive_hours_per_day: Decimal; duration_days: int
    start: date | None; end: date | None; start_week: int; end_week: int   # weeks are 1-based, relative
    sources: dict[str, str]     # field -> "computed" | "estimator"
    needed_crew: int | None; over_max: bool

@dataclass
class PhaseLineOut:
    line_id: uuid.UUID; label: str; hours: Decimal; source: str

@dataclass
class PhasePlan:
    phase_id: uuid.UUID; name: str; direct_hours: Decimal; general_conditions_hours: Decimal
    lines: list[PhaseLineOut]; bars: list[StageBar]; start: date | None; end: date | None

def split_hours(item: ItemHours, splits: dict[str, SplitRule]) -> tuple[dict[str, Decimal], bool]   # (share by stage, used_fallback)
def working_days_after(start: date, days: int) -> date        # the date `days` working days after `start` (days=0 -> start)
def next_working_day(d: date) -> date
def build_phase(phase: PhaseInput, items: list[ItemHours], splits, crews, *, phase_start: date | None, relative_week_start: int) -> PhasePlan
```

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_schedule_plan.py
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.schedule.plan import (
    CrewRule, ItemHours, PhaseInput, SplitRule, StageOverride,
    build_phase, next_working_day, split_hours, working_days_after,
)
from app.schedule.stages import STAGES

D = Decimal
PID = uuid.uuid4()


def rule(*pcts, edited=False):
    return SplitRule(percents=dict(zip(STAGES, (D(p) for p in pcts))), firm_edited=edited)


SPLITS = {"devices": rule(0, 45, 25, 0, 25, 5), "*": rule(0, 0, 0, 0, 95, 5)}
CREWS = {s: CrewRule(1, 2, 2, D("6"), D("1"), 6, False) for s in STAGES}


def phase(**kw):
    base = dict(phase_id=PID, name="Phase 1", sort_order=0, start_date=None, required_finish_date=None,
                line_percents=[], overrides={})
    base.update(kw)
    return PhaseInput(**base)


def test_split_devices_item():
    shares, fallback = split_hours(ItemHours(uuid.uuid4(), PID, "Devices", D("10")), SPLITS)
    assert shares == {"demolition": D("0"), "rough_in": D("4.5"), "wire_pull": D("2.5"), "gear": D("0"), "trim": D("2.5"), "closeout": D("0.5")}
    assert fallback is False


def test_split_unlisted_category_uses_fallback():
    shares, fallback = split_hours(ItemHours(uuid.uuid4(), PID, "Nurse call", D("10")), SPLITS)
    assert shares["trim"] == D("9.5") and shares["closeout"] == D("0.5") and fallback is True


def test_split_matches_case_insensitively():
    shares, fallback = split_hours(ItemHours(uuid.uuid4(), PID, "DEVICES", D("10")), SPLITS)
    assert fallback is False and shares["rough_in"] == D("4.5")


def test_working_days_skip_weekends():
    assert next_working_day(date(2026, 9, 26)) == date(2026, 9, 28)   # Sat -> Mon; a weekday is returned unchanged
    assert working_days_after(date(2026, 9, 24), 2) == date(2026, 9, 28)  # Thu + 2 -> Mon


def test_duration_rounds_up_and_zero_hours_has_no_bar():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("80"))]   # rough-in 36 h, crew 5 x 6 = 30/day -> 2 days
    plan = build_phase(phase(), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert "demolition" not in by and "gear" not in by
    assert by["rough_in"].hours == D("36.00") and by["rough_in"].duration_days == 2
    assert by["closeout"].hours == D("4.00") and by["closeout"].duration_days == 1
    assert by["rough_in"].sources["duration_days"] == "computed"


def test_general_conditions_add_to_bars_in_proportion():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("100"))]
    line = (uuid.uuid4(), "Final and daily cleanup", D("7"), None)
    plan = build_phase(phase(line_percents=[line]), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    assert plan.direct_hours == D("100.00") and plan.general_conditions_hours == D("7.00")
    assert plan.lines[0].hours == D("7.00") and plan.lines[0].source == "computed"
    assert {b.stage: b.hours for b in plan.bars}["rough_in"] == D("48.15")   # 45 + 7 * 0.45


def test_typed_general_conditions_win():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("100"))]
    line = (uuid.uuid4(), "Final and daily cleanup", D("7"), D("12"))
    plan = build_phase(phase(line_percents=[line]), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    assert plan.lines[0].hours == D("12.00") and plan.lines[0].source == "estimator"


def test_stages_chain_across_a_weekend_from_mobilization():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300"))]   # rough 135h -> 5 days; pull 75h -> 3; trim 75 -> 3; close 15 -> 1
    plan = build_phase(phase(), items, SPLITS, CREWS, phase_start=date(2026, 10, 5), relative_week_start=1)  # a Monday
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].start == date(2026, 10, 5) and by["rough_in"].end == date(2026, 10, 9)
    assert by["wire_pull"].start == date(2026, 10, 12) and by["wire_pull"].end == date(2026, 10, 14)
    assert by["trim"].start == date(2026, 10, 15) and by["trim"].end == date(2026, 10, 19)
    assert plan.end == date(2026, 10, 20)


def test_no_dates_means_relative_weeks():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300"))]
    plan = build_phase(phase(), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].start is None and by["rough_in"].start_week == 1 and by["rough_in"].end_week == 1
    assert by["wire_pull"].start_week == 2
    assert plan.start is None


def test_pinned_start_shifts_later_stages_and_overrides_are_marked():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300"))]
    ov = {"wire_pull": StageOverride(start_date=date(2026, 10, 19), journeyman=4, duration_days=4)}
    plan = build_phase(phase(overrides=ov), items, SPLITS, CREWS, phase_start=date(2026, 10, 5), relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["wire_pull"].start == date(2026, 10, 19) and by["wire_pull"].journeyman == 4 and by["wire_pull"].duration_days == 4
    assert by["wire_pull"].sources["start"] == "estimator" and by["wire_pull"].sources["journeyman"] == "estimator"
    assert by["wire_pull"].sources["foreman"] == "computed"
    assert by["trim"].start == date(2026, 10, 23)


def test_hours_override_replaces_computed_hours():
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("80"))]
    ov = {"rough_in": StageOverride(hours_override=D("60"))}
    plan = build_phase(phase(overrides=ov), items, SPLITS, CREWS, phase_start=None, relative_week_start=1)
    by = {b.stage: b for b in plan.bars}
    assert by["rough_in"].hours == D("60.00") and by["rough_in"].sources["hours"] == "estimator"


def test_productivity_factor_scales_stage_hours():
    crews = dict(CREWS); crews["trim"] = CrewRule(0, 2, 2, D("6"), D("1.2"), 6, True)
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("100"))]
    plan = build_phase(phase(), items, SPLITS, crews, phase_start=None, relative_week_start=1)
    assert {b.stage: b.hours for b in plan.bars}["trim"] == D("30.00")
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_plan.py`
Expected: FAIL — `ModuleNotFoundError: app.schedule.plan`

- [ ] **Step 3: Write `plan.py` (first half)**

```python
# api/app/schedule/plan.py
"""The schedule's arithmetic (phases-and-timeline.md §4), pure: plain
dataclasses in, a Schedule out, no database, no date.today(). The
router assembles inputs in assemble.py; the client renders what comes
back and never re-derives a number.

Rounding: hours to two decimals (HALF_UP), days up to the whole day.
Working days are Monday to Friday; nothing here knows a holiday."""
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.schedule.stages import STAGES

CENTS = Decimal("0.01")
FALLBACK_KEY = "*"


def q(x: Decimal) -> Decimal:
    return Decimal(x).quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ItemHours:
    item_id: uuid.UUID
    phase_id: uuid.UUID
    category: str
    adjusted_hours: Decimal


@dataclass(frozen=True)
class SplitRule:
    percents: dict[str, Decimal]
    firm_edited: bool


@dataclass(frozen=True)
class CrewRule:
    foreman: int
    journeyman: int
    apprentice: int
    productive_hours_per_day: Decimal
    productivity_factor: Decimal
    max_crew: int
    firm_edited: bool


@dataclass(frozen=True)
class StageOverride:
    foreman: int | None = None
    journeyman: int | None = None
    apprentice: int | None = None
    productive_hours_per_day: Decimal | None = None
    hours_override: Decimal | None = None
    start_date: date | None = None
    duration_days: int | None = None


@dataclass(frozen=True)
class PhaseInput:
    phase_id: uuid.UUID
    name: str
    sort_order: int
    start_date: date | None
    required_finish_date: date | None
    line_percents: list[tuple[uuid.UUID, str, Decimal, Decimal | None]]
    overrides: dict[str, StageOverride]


@dataclass
class StageBar:
    stage: str
    hours: Decimal
    foreman: int
    journeyman: int
    apprentice: int
    productive_hours_per_day: Decimal
    duration_days: int
    start: date | None
    end: date | None
    start_week: int
    end_week: int
    sources: dict[str, str]
    needed_crew: int | None = None
    over_max: bool = False

    @property
    def crew(self) -> int:
        return self.foreman + self.journeyman + self.apprentice


@dataclass
class PhaseLineOut:
    line_id: uuid.UUID
    label: str
    hours: Decimal
    source: str


@dataclass
class PhasePlan:
    phase_id: uuid.UUID
    name: str
    direct_hours: Decimal
    general_conditions_hours: Decimal
    lines: list[PhaseLineOut]
    bars: list[StageBar]
    start: date | None
    end: date | None
    end_week: int = 0


def split_hours(item: ItemHours, splits: dict[str, SplitRule]) -> tuple[dict[str, Decimal], bool]:
    key = (item.category or "").strip().casefold() or FALLBACK_KEY
    rule = splits.get(key)
    fallback = rule is None
    if fallback:
        rule = splits[FALLBACK_KEY]
    shares = {s: item.adjusted_hours * rule.percents.get(s, Decimal("0")) / Decimal("100") for s in STAGES}
    return shares, fallback


def next_working_day(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def working_days_after(start: date, days: int) -> date:
    d = next_working_day(start)
    for _ in range(days):
        d = next_working_day(d + timedelta(days=1))
    return d


def _week_of(d: date, origin: date) -> int:
    return (d - origin).days // 7 + 1
```

- [ ] **Step 4: Write `plan.py` (second half — `build_phase`)**

```python
def build_phase(
    phase: PhaseInput,
    items: list[ItemHours],
    splits: dict[str, SplitRule],
    crews: dict[str, CrewRule],
    *,
    phase_start: date | None,
    relative_week_start: int,
    week_origin: date | None = None,
) -> PhasePlan:
    """One phase's bars. `phase_start` is the resolved calendar start
    (the phase's own date, else the caller's -- previous phase end or
    mobilization) or None for relative weeks. `week_origin` is the
    project's first calendar day, for week numbering across phases."""
    stage_hours = {s: Decimal("0") for s in STAGES}
    for item in items:
        shares, _ = split_hours(item, splits)
        for s in STAGES:
            stage_hours[s] += shares[s]
    direct = sum(stage_hours.values(), Decimal("0"))

    lines: list[PhaseLineOut] = []
    gc_total = Decimal("0")
    for line_id, label, percent, override in phase.line_percents:
        hours = override if override is not None else direct * percent / Decimal("100")
        lines.append(PhaseLineOut(line_id, label, q(hours), "estimator" if override is not None else "computed"))
        gc_total += hours

    bars: list[StageBar] = []
    cursor = next_working_day(phase_start) if phase_start else None
    week_cursor = relative_week_start
    origin = week_origin or phase_start
    for stage in STAGES:
        crew_rule = crews[stage]
        ov = phase.overrides.get(stage, StageOverride())
        base = stage_hours[stage]
        if direct > 0:
            base += gc_total * (stage_hours[stage] / direct)
        hours = base * crew_rule.productivity_factor
        sources = {k: "computed" for k in ("hours", "foreman", "journeyman", "apprentice", "productive_hours_per_day", "start", "duration_days")}
        if ov.hours_override is not None:
            hours, sources["hours"] = ov.hours_override, "estimator"
        if hours <= 0:
            continue
        foreman = crew_rule.foreman if ov.foreman is None else ov.foreman
        journeyman = crew_rule.journeyman if ov.journeyman is None else ov.journeyman
        apprentice = crew_rule.apprentice if ov.apprentice is None else ov.apprentice
        per_day = crew_rule.productive_hours_per_day if ov.productive_hours_per_day is None else ov.productive_hours_per_day
        for name, val in (("foreman", ov.foreman), ("journeyman", ov.journeyman), ("apprentice", ov.apprentice), ("productive_hours_per_day", ov.productive_hours_per_day)):
            if val is not None:
                sources[name] = "estimator"
        crew = foreman + journeyman + apprentice
        capacity = Decimal(crew) * per_day
        duration = max(1, math.ceil(hours / capacity)) if capacity > 0 else 1
        if ov.duration_days is not None:
            duration, sources["duration_days"] = ov.duration_days, "estimator"

        if ov.start_date is not None:
            cursor, sources["start"] = next_working_day(ov.start_date), "estimator"
            if origin is None:
                origin = cursor
        if cursor is not None:
            start = cursor
            end = working_days_after(start, duration - 1)
            start_week = _week_of(start, origin)
            end_week = _week_of(end, origin)
            cursor = working_days_after(end, 1)
            week_cursor = end_week
        else:
            start = end = None
            start_week = week_cursor
            end_week = week_cursor + max(0, (duration - 1) // 5)
            week_cursor = end_week + (1 if (duration % 5 == 0) else 0)
        bars.append(StageBar(stage, q(hours), foreman, journeyman, apprentice, per_day, duration,
                             start, end, start_week, end_week, sources))

    return PhasePlan(
        phase_id=phase.phase_id, name=phase.name, direct_hours=q(direct), general_conditions_hours=q(gc_total),
        lines=lines, bars=bars,
        start=bars[0].start if bars else None,
        end=bars[-1].end if bars else None,
        end_week=bars[-1].end_week if bars else relative_week_start,
    )
```

Note on relative weeks: with no calendar, a bar of `duration` working days occupies `ceil(duration / 5)` weeks starting at `week_cursor`; the next bar starts in the same week only when this one did not fill it. The test `test_no_dates_means_relative_weeks` pins the two cases that matter (5 days fills week 1; the next starts week 2). If `working_days_after(end, 1)` in the calendar branch does not land wire pull on 2026-10-12 in `test_stages_chain_across_a_weekend_from_mobilization`, check `next_working_day` is applied after the `+1` day — it is in the code above.

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_plan.py`
Expected: PASS. If `test_general_conditions_add_to_bars_in_proportion` shows `48.15` vs a neighbour cent, the `q()` is applied once, at the bar — keep it there and do not round `gc_total` early.

- [ ] **Step 6: Commit**

```bash
git add api/app/schedule/plan.py api/tests/test_schedule_plan.py
git commit -m "Schedule: split hours by stage, size each bar by its crew, and chain stages on working days

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The pure derivation — reverse solve, manpower, order-by, staleness

**Files:**
- Modify: `api/app/schedule/plan.py` (append)
- Create: `api/app/schedule/copy.py`
- Test: `api/tests/test_schedule_plan.py` (append)

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class LeadInput:
    item_id: uuid.UUID; item_name: str; phase_id: uuid.UUID; flagged: bool
    lead_weeks: int | None; source: str | None; source_label: str; quoted_at: date | None; needed_for_stage: str

@dataclass
class LeadOut:
    item_id: uuid.UUID; item_name: str; phase_id: uuid.UUID; lead_weeks: int | None
    source: str | None; source_label: str; quoted_at: date | None; needed_for_stage: str
    needed_by: date | None; order_by: date | None; order_by_week: int | None
    passed: bool; stale: bool; note: str      # note: "" | the order-date-passed sentence

@dataclass
class ManpowerWeek:
    week: int; start: date | None; foreman: int; journeyman: int; apprentice: int

@dataclass
class Schedule:
    phases: list[PhasePlan]; manpower: list[ManpowerWeek]; peak_crew: int; average_crew: Decimal
    leads: list[LeadOut]; relative: bool

def needed_crew(hours: Decimal, days_available: int, per_day: Decimal) -> int
def build_schedule(phases: list[PhaseInput], items: list[ItemHours], splits, crews, leads: list[LeadInput], *,
                   mobilization: date | None, expected_award: date | None, today: date, stale_days: int) -> Schedule
# copy.py
def order_date_passed(lead_weeks: int, stage_label: str, stage_start: date) -> str
def stale_lead_time_warning(days: int, source_label: str) -> dict   # title, found, why, fix, where
DEFAULT_SPLIT_NOTE = "Default split — set yours in Company settings"
```

- [ ] **Step 1: Write the failing tests**

```python
# append to api/tests/test_schedule_plan.py
from app.schedule.plan import LeadInput, build_schedule, needed_crew
from app.schedule.copy import DEFAULT_SPLIT_NOTE, order_date_passed, stale_lead_time_warning

P2 = uuid.uuid4()


def two_phases(items_a=D("300"), items_b=D("120"), **kw):
    phases = [phase(), phase(phase_id=P2, name="Phase 2", sort_order=1, **kw)]
    items = [ItemHours(uuid.uuid4(), PID, "Devices", items_a), ItemHours(uuid.uuid4(), P2, "Devices", items_b)]
    return phases, items


def test_needed_crew():
    assert needed_crew(D("120"), 4, D("6")) == 5
    assert needed_crew(D("120"), 2, D("6")) == 10


def test_reverse_solve_marks_over_max_and_writes_nothing():
    phases, items = two_phases(required_finish_date=date(2026, 11, 6))
    sched = build_schedule(phases, items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5),
                           expected_award=None, today=date(2026, 9, 21), stale_days=60)
    p2 = sched.phases[1]
    assert all(b.needed_crew is not None for b in p2.bars)
    assert sched.phases[0].bars[0].needed_crew is None      # no window on phase 1
    tight = build_schedule([phases[0], phase(phase_id=P2, name="Phase 2", sort_order=1, required_finish_date=date(2026, 10, 22))],
                           items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5), expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert any(b.over_max for b in tight.phases[1].bars)


def test_second_phase_follows_first_unless_dated():
    phases, items = two_phases()
    sched = build_schedule(phases, items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5), expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert sched.phases[1].start == date(2026, 10, 21)
    dated = build_schedule([phases[0], phase(phase_id=P2, name="Phase 2", sort_order=1, start_date=date(2026, 11, 2))],
                           items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5), expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert dated.phases[1].start == date(2026, 11, 2)


def test_manpower_sums_overlapping_phases_by_role():
    phases = [phase(), phase(phase_id=P2, name="Phase 2", sort_order=1, start_date=date(2026, 10, 5))]
    items = [ItemHours(uuid.uuid4(), PID, "Devices", D("300")), ItemHours(uuid.uuid4(), P2, "Devices", D("300"))]
    sched = build_schedule(phases, items, SPLITS, CREWS, [], mobilization=date(2026, 10, 5), expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    week1 = sched.manpower[0]
    assert (week1.foreman, week1.journeyman, week1.apprentice) == (2, 4, 4)
    assert sched.peak_crew == 10 and sched.relative is False


def test_relative_schedule_when_nothing_is_dated():
    phases, items = two_phases()
    sched = build_schedule(phases, items, SPLITS, CREWS, [], mobilization=None, expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert sched.relative is True and sched.manpower[0].start is None and sched.manpower[0].week == 1


def lead(**kw):
    base = dict(item_id=uuid.uuid4(), item_name="Switchboard MSB-1", phase_id=PID, flagged=True, lead_weeks=40,
                source="supplier_quote", source_label="Graybar", quoted_at=date(2026, 9, 12), needed_for_stage="gear")
    base.update(kw)
    return LeadInput(**base)


def gear_items():
    return [ItemHours(uuid.uuid4(), PID, "Distribution", D("100"))]   # gear bar exists


def test_order_by_counts_back_from_the_stage_it_is_needed_for():
    sched = build_schedule([phase(start_date=date(2027, 2, 22))], gear_items(), SPLITS | {"distribution": rule(0, 20, 10, 60, 5, 5)},
                           CREWS, [lead()], mobilization=None, expected_award=date(2026, 9, 1), today=date(2026, 9, 21), stale_days=60)
    out = sched.leads[0]
    gear_start = {b.stage: b for b in sched.phases[0].bars}["gear"].start
    assert out.needed_by == gear_start
    assert out.order_by == gear_start - timedelta(weeks=40)
    assert out.passed is True and "Order date has passed" in out.note and "40 weeks" in out.note


def test_order_by_without_award_compares_to_today():
    sched = build_schedule([phase(start_date=date(2027, 9, 6))], gear_items(), SPLITS | {"distribution": rule(0, 20, 10, 60, 5, 5)},
                           CREWS, [lead(lead_weeks=10)], mobilization=None, expected_award=None, today=date(2026, 9, 21), stale_days=60)
    assert sched.leads[0].passed is False and sched.leads[0].note == ""


def test_no_weeks_means_no_date():
    sched = build_schedule([phase(start_date=date(2027, 2, 22))], gear_items(), SPLITS | {"distribution": rule(0, 20, 10, 60, 5, 5)},
                           CREWS, [lead(lead_weeks=None, source=None, source_label="", quoted_at=None)],
                           mobilization=None, expected_award=None, today=date(2026, 9, 21), stale_days=60)
    out = sched.leads[0]
    assert out.order_by is None and out.needed_by is not None and out.passed is False and out.stale is False


def test_stale_lead_time():
    sched = build_schedule([phase(start_date=date(2027, 2, 22))], gear_items(), SPLITS | {"distribution": rule(0, 20, 10, 60, 5, 5)},
                           CREWS, [lead(quoted_at=date(2026, 7, 1))], mobilization=None, expected_award=None,
                           today=date(2026, 9, 21), stale_days=60)
    assert sched.leads[0].stale is True
    w = stale_lead_time_warning(82, "Graybar")
    assert set(w) == {"title", "found", "why", "fix", "where"} and "82 days" in w["found"] and "Graybar" in w["found"]


def test_copy_is_sentence_case_and_carries_no_bare_week_number():
    assert order_date_passed(40, "Gear", date(2027, 2, 22)).startswith("Order date has passed")
    assert DEFAULT_SPLIT_NOTE[0].isupper() and "!" not in DEFAULT_SPLIT_NOTE and "recommended" not in DEFAULT_SPLIT_NOTE.lower()
```

Add `from datetime import timedelta` to the test file's imports.

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_plan.py -k "needed or reverse or second or manpower or relative or order or weeks or stale or copy"`
Expected: FAIL — `ImportError: cannot import name 'build_schedule'`

- [ ] **Step 3: Write `copy.py`**

```python
# api/app/schedule/copy.py
"""The schedule's estimator-facing words, one place (phases-and-timeline.md
§5). Every warning carries all four fields; nothing here names a model, a
confidence, or a published lead time."""
from datetime import date

DEFAULT_SPLIT_NOTE = "Default split — set yours in Company settings"
DEFAULT_CREW_NOTE = "Default crew — set yours in Company settings"
NOT_YET_QUOTED = "Not yet quoted"
NOTHING_TO_SCHEDULE = "Nothing to schedule yet. Labor hours come from the Labor workspace."
NO_DEMOLITION = "No demolition items yet"


def _mon_d(d: date) -> str:
    return f"{d:%b} {d.day}"


def order_date_passed(lead_weeks: int, stage_label: str, stage_start: date) -> str:
    return f"Order date has passed — {lead_weeks} weeks lead, {stage_label.lower()} starts {_mon_d(stage_start)}"


def over_max_crew(max_crew: int, stage_label: str, finish: date) -> str:
    return f"More than {max_crew} on {stage_label.lower()} to finish by {_mon_d(finish)} — the window is tighter than one crew can meet"


def unscheduled_items(count: int) -> str:
    noun = "item isn't" if count == 1 else "items aren't"
    return f"{count} {noun} in the schedule yet — they need labor hours"


def stale_lead_time_warning(days: int, source_label: str) -> dict:
    who = source_label or "the supplier"
    return {
        "title": "Lead time may be out of date",
        "found": f"The lead time on this item was quoted {days} days ago by {who}.",
        "why": "Order dates on the timeline are counted from it, and gear lead times are moving.",
        "fix": "Ask the supplier for a current lead time, or upload their price sheet with the lead-time column filled.",
        "where": "Phases and schedule, long-lead items; the item's detail panel",
    }
```

- [ ] **Step 4: Append to `plan.py`**

```python
@dataclass(frozen=True)
class LeadInput:
    item_id: uuid.UUID
    item_name: str
    phase_id: uuid.UUID
    flagged: bool
    lead_weeks: int | None
    source: str | None
    source_label: str
    quoted_at: date | None
    needed_for_stage: str


@dataclass
class LeadOut:
    item_id: uuid.UUID
    item_name: str
    phase_id: uuid.UUID
    lead_weeks: int | None
    source: str | None
    source_label: str
    quoted_at: date | None
    needed_for_stage: str
    needed_by: date | None
    order_by: date | None
    order_by_week: int | None
    passed: bool
    stale: bool
    note: str


@dataclass
class ManpowerWeek:
    week: int
    start: date | None
    foreman: int
    journeyman: int
    apprentice: int

    @property
    def crew(self) -> int:
        return self.foreman + self.journeyman + self.apprentice


@dataclass
class Schedule:
    phases: list[PhasePlan]
    manpower: list[ManpowerWeek]
    peak_crew: int
    average_crew: Decimal
    leads: list[LeadOut]
    relative: bool


def needed_crew(hours: Decimal, days_available: int, per_day: Decimal) -> int:
    if days_available <= 0 or per_day <= 0:
        return 0
    return math.ceil(hours / (Decimal(days_available) * per_day))


def _working_days_between(a: date, b: date) -> int:
    """Working days from a to b inclusive; 0 when b < a."""
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def build_schedule(
    phases: list[PhaseInput],
    items: list[ItemHours],
    splits: dict[str, SplitRule],
    crews: dict[str, CrewRule],
    leads: list[LeadInput],
    *,
    mobilization: date | None,
    expected_award: date | None,
    today: date,
    stale_days: int,
) -> Schedule:
    from app.schedule.copy import order_date_passed, over_max_crew  # noqa: local to keep plan.py's top import-free of copy
    from app.schedule.stages import STAGE_LABELS

    by_phase: dict[uuid.UUID, list[ItemHours]] = {}
    for it in items:
        by_phase.setdefault(it.phase_id, []).append(it)

    ordered = sorted(phases, key=lambda p: p.sort_order)
    any_dates = mobilization is not None or any(p.start_date or any(o.start_date for o in p.overrides.values()) for p in ordered)
    origin = mobilization or next((p.start_date for p in ordered if p.start_date), None)
    plans: list[PhasePlan] = []
    cursor_date = mobilization
    cursor_week = 1
    for p in ordered:
        start = p.start_date or cursor_date
        plan = build_phase(p, by_phase.get(p.phase_id, []), splits, crews,
                           phase_start=start if any_dates else None, relative_week_start=cursor_week, week_origin=origin)
        if p.required_finish_date is not None and plan.bars:
            finish = p.required_finish_date
            phase_start = plan.start or start
            if phase_start is not None:
                days_available = _working_days_between(phase_start, finish)
                total = sum(b.hours for b in plan.bars)
                for b in plan.bars:
                    share_days = max(1, math.floor(days_available * (b.hours / total))) if total > 0 else 0
                    b.needed_crew = needed_crew(b.hours, share_days, b.productive_hours_per_day)
                    b.over_max = b.needed_crew > crews[b.stage].max_crew
        plans.append(plan)
        if plan.end is not None:
            cursor_date = working_days_after(plan.end, 1)
        cursor_week = plan.end_week + 1

    # Manpower: one row per week the schedule spans, summed over every active bar.
    last_week = max((p.end_week for p in plans), default=0)
    weeks: list[ManpowerWeek] = []
    for w in range(1, last_week + 1):
        row = ManpowerWeek(w, (origin + timedelta(weeks=w - 1)) if (any_dates and origin) else None, 0, 0, 0)
        for p in plans:
            for b in p.bars:
                if b.start_week <= w <= b.end_week:
                    row.foreman += b.foreman
                    row.journeyman += b.journeyman
                    row.apprentice += b.apprentice
        weeks.append(row)
    peak = max((r.crew for r in weeks), default=0)
    average = q(Decimal(sum(r.crew for r in weeks)) / Decimal(len(weeks))) if weeks else Decimal("0")

    # Long-lead: order-by counted back from the stage bar that installs it.
    bars_by_phase = {p.phase_id: {b.stage: b for b in p.bars} for p in plans}
    leads_out: list[LeadOut] = []
    for L in leads:
        if not L.flagged:
            continue
        bar = bars_by_phase.get(L.phase_id, {}).get(L.needed_for_stage)
        needed_by = bar.start if bar else None
        order_by = order_by_week = None
        passed = False
        note = ""
        if L.lead_weeks is not None and needed_by is not None:
            order_by = needed_by - timedelta(weeks=L.lead_weeks)
            order_by_week = _week_of(order_by, origin) if origin else None
            threshold = expected_award or today
            passed = order_by < threshold
            if passed:
                note = order_date_passed(L.lead_weeks, STAGE_LABELS[L.needed_for_stage], needed_by)
        stale = L.lead_weeks is not None and L.quoted_at is not None and (today - L.quoted_at).days > stale_days
        leads_out.append(LeadOut(L.item_id, L.item_name, L.phase_id, L.lead_weeks, L.source, L.source_label, L.quoted_at,
                                 L.needed_for_stage, needed_by, order_by, order_by_week, passed, stale, note))

    return Schedule(plans, weeks, peak, average, leads_out, relative=not any_dates)
```

Move the two local imports to the top of `plan.py` once written (`copy.py` imports nothing from `plan.py`, so there is no cycle); they are local above only to keep the diff readable.

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_plan.py`
Expected: PASS. `test_reverse_solve_marks_over_max_and_writes_nothing`: phase 2 (120 h Devices → rough 54 h, pull 30, trim 30, close 6) starting 2026-10-21 must finish by 2026-10-22 — two working days shared four ways gives each bar one day, and rough-in needs ⌈54 / 6⌉ = 9 > 6. `test_second_phase_follows_first_unless_dated`: phase 1 ends 2026-10-20, so phase 2 starts 2026-10-21.

- [ ] **Step 6: Commit**

```bash
git add api/app/schedule/plan.py api/app/schedule/copy.py api/tests/test_schedule_plan.py
git commit -m "Schedule: the reverse solve, the weekly manpower sum, and order-by dates counted back from the stage that needs the gear

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Phase records — first phase, resolution, and the phase mutations

**Files:**
- Create: `api/app/schedule/phases.py`, `api/app/schedule/undo_apply.py`
- Modify: `api/app/takeoff/undo.py:76` (`REVERSIBLE`), `api/app/takeoff/undo_apply.py:79` (`apply`), `api/app/takeoff/review.py` and `api/app/takeoff/undo_apply.py::_apply_delete` (delete snapshot), `api/app/takeoff/merge.py` (a comment only, plus the test)
- Test: `api/tests/test_schedule_phases.py`, `api/tests/test_undo_redo.py` (append), `api/tests/test_merge.py` (append)

**Interfaces:**
- Produces (in `phases.py`):

```python
def first_phase(db, project: Project, *, create: bool = False) -> Phase | None   # sort_order 0; creates "Phase 1" with its template lines when create=True
def phases_for(db, project_id) -> list[Phase]                                    # ordered; [] when none
def phase_of(item: Item, sheet: Sheet, first: Phase | None) -> uuid.UUID | None    # item.phase_id or sheet.phase_id or first.id
def create_phase(db, *, actor, project, name: str, after_phase_id: uuid.UUID | None) -> Phase
def rename_phase / edit_phase(db, *, actor, phase, changes: dict) -> Phase           # name, start_date, required_finish_date, notes
def reorder_phase(db, *, actor, phase, sort_order: int) -> Phase
def delete_phase(db, *, actor, phase) -> None                                        # 409 DomainError("last_phase") on the only phase
def assign_sheets(db, *, actor, phase, sheet_ids: list[uuid.UUID]) -> Phase
def set_item_phase(db, *, actor, item, phase_id: uuid.UUID | None) -> Item
```

Every mutation ends with `actions.commit(kind=…)` and `db.commit()` is left to the router (same convention as `pricing_router.py`). Kinds: `phase_create`, `phase_edit`, `phase_reorder`, `phase_delete`, `sheet_phase_set`, `item_phase_set`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_schedule_phases.py
import uuid
from decimal import Decimal

import pytest

from app.errors import DomainError
from app.schedule import phases as svc
from app.takeoff import undo
from app.takeoff.models import Action, Item, Phase, PhaseLine, Sheet
from app.takeoff.totals import approved_totals


def test_no_phase_row_until_asked(db, project, dana):
    assert svc.phases_for(db, project.id) == []
    assert svc.first_phase(db, project) is None
    first = svc.first_phase(db, project, create=True)
    assert first.name == "Phase 1" and first.sort_order == 0
    assert [l.label for l in db.query(PhaseLine).filter_by(phase_id=first.id).order_by(PhaseLine.sort_order)] == \
        ["Final and daily cleanup", "Project planning, coordination and layout"]
    assert svc.first_phase(db, project, create=True).id == first.id


def test_phase_of_resolves_item_then_sheet_then_first(db, project, sheet, item, dana):
    first = svc.first_phase(db, project, create=True)
    assert svc.phase_of(item, sheet, first) == first.id
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    sheet.phase_id = second.id
    assert svc.phase_of(item, sheet, first) == second.id
    item.phase_id = first.id
    assert svc.phase_of(item, sheet, first) == first.id


def test_create_records_an_action_and_is_undoable(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    db.commit()
    action = db.query(Action).filter_by(kind="phase_create").one()
    assert action.label == "Added Phase 2"
    assert "phase_create" in undo.REVERSIBLE
    undo.undo(db, actor=dana, project_id=project.id)
    db.commit()
    assert db.get(Phase, second.id) is None
    undo.redo(db, actor=dana, project_id=project.id)
    db.commit()
    assert db.get(Phase, second.id).name == "Phase 2"


def test_assign_sheets_moves_in_and_out_as_one_action(db, project, sheet, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    other = Sheet(project_id=project.id, number="XE-1.0", title="Power plan — phase 2", discipline="Electrical",
                  revision="", scale="", scale_options=[], plan="")
    db.add(other); db.flush()
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id, other.id])
    db.commit()
    assert sheet.phase_id == second.id and other.phase_id == second.id
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[other.id])
    db.commit()
    db.refresh(sheet)
    assert sheet.phase_id is None     # moved back to the first phase (null = first)
    action = db.query(Action).filter_by(kind="sheet_phase_set").order_by(Action.at.desc()).first()
    assert str(sheet.id) in action.before["sheets"]
    undo.undo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(sheet)
    assert sheet.phase_id == second.id


def test_delete_moves_sheets_and_overrides_and_undoes_in_one_press(db, project, sheet, item, dana):
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id])
    svc.set_item_phase(db, actor=dana, item=item, phase_id=second.id)
    db.commit()
    svc.delete_phase(db, actor=dana, phase=second)
    db.commit()
    db.refresh(sheet); db.refresh(item)
    assert sheet.phase_id == first.id and item.phase_id is None
    undo.undo(db, actor=dana, project_id=project.id); db.commit()
    db.refresh(sheet); db.refresh(item)
    restored = db.get(Phase, second.id)
    assert restored is not None and restored.name == "Phase 2"
    assert sheet.phase_id == second.id and item.phase_id == second.id


def test_the_last_phase_cannot_be_deleted(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    with pytest.raises(DomainError) as e:
        svc.delete_phase(db, actor=dana, phase=first)
    assert e.value.code == "last_phase"


def test_phases_change_no_total(db, project, sheet, item, dana):
    before = approved_totals(db, project.id)
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id])
    db.commit()
    assert approved_totals(db, project.id) == before
```

Append to `api/tests/test_merge.py` a test that runs the existing merge fixture twice with `sheet.phase_id` and `item.phase_id` set to a phase, and asserts both are unchanged afterwards (use the file's existing helper that merges a payload for one sheet; the assertion is `sheet.phase_id == phase.id and item.phase_id == phase.id`).

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_phases.py`
Expected: FAIL — `ImportError: app.schedule.phases`

- [ ] **Step 3: Write `phases.py`**

```python
# api/app/schedule/phases.py
"""Phase records and their mutations (phases-and-timeline.md §3.1).
A phase groups sheets and items that already exist; nothing here reads
or writes a quantity or a status. Every mutation records one action
through actions.commit(); db.commit() is the router's."""
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.schedule.defaults import load_company
from app.takeoff import actions
from app.takeoff.actions import encode_snapshot
from app.takeoff.models import Item, Phase, PhaseLine, PhaseStagePlan, Project, Sheet

PHASE_FIELDS = ("name", "sort_order", "start_date", "required_finish_date", "notes")
EDITABLE = ("name", "start_date", "required_finish_date", "notes")


def phases_for(db: DbSession, project_id: uuid.UUID) -> list[Phase]:
    return list(db.scalars(select(Phase).where(Phase.project_id == project_id).order_by(Phase.sort_order)))


def _snapshot_phase(phase: Phase) -> dict:
    return encode_snapshot({f: getattr(phase, f) for f in PHASE_FIELDS} | {"id": phase.id, "project_id": phase.project_id})


def _lines_snapshot(db: DbSession, phase_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(select(PhaseLine).where(PhaseLine.phase_id == phase_id).order_by(PhaseLine.sort_order))
    return [encode_snapshot({"id": r.id, "kind": r.kind, "label": r.label, "percent_of_direct_hours": r.percent_of_direct_hours,
                             "hours_override": r.hours_override, "sort_order": r.sort_order}) for r in rows]


def _plans_snapshot(db: DbSession, phase_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(select(PhaseStagePlan).where(PhaseStagePlan.phase_id == phase_id))
    return [encode_snapshot({c.name: getattr(r, c.name) for c in PhaseStagePlan.__table__.columns}) for r in rows]


def _add_template_lines(db: DbSession, org_id: uuid.UUID, phase: Phase) -> None:
    for t in load_company(db, org_id).templates:
        db.add(PhaseLine(phase_id=phase.id, label=t.label, percent_of_direct_hours=t.percent_of_direct_hours, sort_order=t.sort_order))


def first_phase(db: DbSession, project: Project, *, create: bool = False) -> Phase | None:
    """The implicit first phase. Created on demand -- never by a
    migration, never as a side effect of a read that did not ask."""
    existing = phases_for(db, project.id)
    if existing:
        return existing[0]
    if not create:
        return None
    phase = Phase(project_id=project.id, name="Phase 1", sort_order=0)
    db.add(phase)
    db.flush()
    _add_template_lines(db, project.org_id, phase)
    db.flush()
    return phase


def phase_of(item: Item, sheet: Sheet, first: Phase | None) -> uuid.UUID | None:
    """The one resolution: item override, else the sheet's, else the
    first phase. Callers never re-derive this."""
    if item.phase_id is not None:
        return item.phase_id
    if sheet.phase_id is not None:
        return sheet.phase_id
    return first.id if first else None


def create_phase(db: DbSession, *, actor: User, project: Project, name: str, after_phase_id: uuid.UUID | None) -> Phase:
    ordered = phases_for(db, project.id)
    if not ordered:
        first_phase(db, project, create=True)
        ordered = phases_for(db, project.id)
    position = len(ordered)
    if after_phase_id is not None:
        idx = next((i for i, p in enumerate(ordered) if p.id == after_phase_id), None)
        if idx is None:
            raise DomainError("phase_not_found", "That phase isn't on this project.")
        position = idx + 1
    for p in ordered[position:]:
        p.sort_order += 1
    phase = Phase(project_id=project.id, name=name.strip() or f"Phase {position + 1}", sort_order=position)
    db.add(phase)
    db.flush()
    _add_template_lines(db, project.org_id, phase)
    db.flush()
    actions.commit(db, actor=actor, project_id=project.id, kind="phase_create", label=f"Added {phase.name}",
                   before={}, after={"phase": _snapshot_phase(phase), "lines": _lines_snapshot(db, phase.id)})
    return phase


def edit_phase(db: DbSession, *, actor: User, phase: Phase, changes: dict) -> Phase:
    changes = {k: v for k, v in changes.items() if k in EDITABLE}
    if not changes:
        raise DomainError("no_changes_to_apply", "This update has no changes. Include at least one field, such as the name or a date.")
    before = _snapshot_phase(phase)
    for k, v in changes.items():
        setattr(phase, k, v.strip() if isinstance(v, str) and k == "name" else (v if v is not None else ("" if k == "notes" else None)))
    db.flush()
    label = f"Renamed {before['name']} to {phase.name}" if "name" in changes else f"Changed dates on {phase.name}"
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="phase_edit", label=label,
                   before={"phase": before}, after={"phase": _snapshot_phase(phase)})
    return phase


def reorder_phase(db: DbSession, *, actor: User, phase: Phase, sort_order: int) -> Phase:
    ordered = phases_for(db, phase.project_id)
    before = {"order": [str(p.id) for p in ordered]}
    ordered.remove(phase)
    ordered.insert(max(0, min(sort_order, len(ordered))), phase)
    for i, p in enumerate(ordered):
        p.sort_order = i
    db.flush()
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="phase_reorder", label=f"Moved {phase.name}",
                   before=before, after={"order": [str(p.id) for p in ordered]})
    return phase


def delete_phase(db: DbSession, *, actor: User, phase: Phase) -> None:
    ordered = phases_for(db, phase.project_id)
    if len(ordered) <= 1:
        raise DomainError("last_phase", "A project keeps at least one phase. Rename this one instead.")
    idx = ordered.index(phase)
    target = ordered[idx - 1] if idx > 0 else ordered[1]
    sheets = list(db.scalars(select(Sheet).where(Sheet.phase_id == phase.id)))
    items = list(db.scalars(select(Item).where(Item.phase_id == phase.id)))
    before = {
        "phase": _snapshot_phase(phase), "lines": _lines_snapshot(db, phase.id), "plans": _plans_snapshot(db, phase.id),
        "sheets": {str(s.id): str(phase.id) for s in sheets}, "items": {str(i.id): str(phase.id) for i in items},
        "order": [str(p.id) for p in ordered],
    }
    # The first phase is "null"; any other phase is its id. Keeps
    # "null reads as first" true after the move.
    target_value = None if target.sort_order == 0 or (idx == 0) else target.id
    if idx == 0:
        target_value = None  # the new first phase is whichever is left at order 0 -- null still resolves to it
    for s in sheets:
        s.phase_id = target_value
    for i in items:
        i.phase_id = target_value
    db.delete(phase)
    db.flush()
    remaining = phases_for(db, phase.project_id)
    for n, p in enumerate(remaining):
        p.sort_order = n
    db.flush()
    after = {"sheets": {str(s.id): (str(target_value) if target_value else None) for s in sheets},
             "items": {str(i.id): (str(target_value) if target_value else None) for i in items},
             "order": [str(p.id) for p in remaining]}
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="phase_delete",
                   label=f"Removed {before['phase']['name']} — its sheets moved to {target.name}", before=before, after=after)


def assign_sheets(db: DbSession, *, actor: User, phase: Phase, sheet_ids: list[uuid.UUID]) -> Phase:
    """`sheet_ids` is the full set the phase should own: sheets not in
    it that are currently on this phase move back to the first phase."""
    first = phases_for(db, phase.project_id)[0]
    wanted = set(sheet_ids)
    project_sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == phase.project_id)))
    unknown = wanted - {s.id for s in project_sheets}
    if unknown:
        raise DomainError("sheet_not_found", "One of those sheets isn't on this project.")
    before, after = {}, {}
    for s in project_sheets:
        current = s.phase_id
        if s.id in wanted and current != phase.id:
            before[str(s.id)] = str(current) if current else None
            s.phase_id = phase.id
            after[str(s.id)] = str(phase.id)
        elif s.id not in wanted and current == phase.id:
            before[str(s.id)] = str(current)
            s.phase_id = None if phase.id != first.id else None
            after[str(s.id)] = None
    if not before:
        raise DomainError("no_changes_to_apply", "Those sheets are already where you put them.")
    db.flush()
    n = len(before)
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="sheet_phase_set",
                   label=f"Moved {n} sheet{'s' if n != 1 else ''} on {phase.name}",
                   before={"sheets": before}, after={"sheets": after})
    return phase


def set_item_phase(db: DbSession, *, actor: User, item: Item, phase_id: uuid.UUID | None) -> Item:
    if phase_id is not None:
        phase = db.get(Phase, phase_id)
        if phase is None or phase.project_id != item.project_id:
            raise DomainError("phase_not_found", "That phase isn't on this project.")
        label = f"Moved {item.name} to {phase.name}"
    else:
        label = f"Returned {item.name} to its sheet's phase"
    before = {"phase_id": str(item.phase_id) if item.phase_id else None}
    item.phase_id = phase_id
    db.flush()
    actions.commit(db, actor=actor, project_id=item.project_id, kind="item_phase_set", label=label, item_id=item.id,
                   before=before, after={"phase_id": str(phase_id) if phase_id else None})
    return item
```

Simplify the two `target_value` lines in `delete_phase` to one: `target_value = None if target.sort_order == 0 else target.id`, computed *after* `target` is known and before the delete — when the first phase is deleted, `ordered[1]` becomes the new first and null still resolves to it. Remove the redundant `if idx == 0` line. In `assign_sheets`, `s.phase_id = None if phase.id != first.id else None` collapses to `s.phase_id = None`.

- [ ] **Step 4: Write `schedule/undo_apply.py` and wire the dispatch**

```python
# api/app/schedule/undo_apply.py
"""Compensating writes for the schedule's action kinds. Called from
takeoff.undo_apply.apply() -- one branch per kind there, the work here,
so the takeoff module stays a dispatcher."""
import uuid
from decimal import Decimal
from datetime import date

from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import Action, Item, Phase, PhaseLine, PhaseStagePlan, Sheet, ItemLeadTime


def _uuid(v):
    return uuid.UUID(v) if v else None


def _date(v):
    return date.fromisoformat(v) if v else None


def _restore_phase(db: DbSession, snap: dict, lines: list[dict], plans: list[dict]) -> Phase:
    phase = db.get(Phase, _uuid(snap["id"]))
    if phase is None:
        phase = Phase(id=_uuid(snap["id"]), project_id=_uuid(snap["project_id"]))
        db.add(phase)
    phase.name, phase.sort_order, phase.notes = snap["name"], snap["sort_order"], snap.get("notes", "")
    phase.start_date, phase.required_finish_date = _date(snap.get("start_date")), _date(snap.get("required_finish_date"))
    db.flush()
    for l in lines:
        if db.get(PhaseLine, _uuid(l["id"])) is None:
            db.add(PhaseLine(id=_uuid(l["id"]), phase_id=phase.id, kind=l["kind"], label=l["label"],
                             percent_of_direct_hours=Decimal(l["percent_of_direct_hours"]),
                             hours_override=Decimal(l["hours_override"]) if l.get("hours_override") is not None else None,
                             sort_order=l["sort_order"]))
    for p in plans:
        if db.get(PhaseStagePlan, _uuid(p["id"])) is None:
            row = PhaseStagePlan(id=_uuid(p["id"]), phase_id=phase.id, stage=p["stage"])
            for k in ("foreman", "journeyman", "apprentice", "duration_days"):
                setattr(row, k, p.get(k))
            row.productive_hours_per_day = Decimal(p["productive_hours_per_day"]) if p.get("productive_hours_per_day") is not None else None
            row.hours_override = Decimal(p["hours_override"]) if p.get("hours_override") is not None else None
            row.start_date = _date(p.get("start_date"))
            db.add(row)
    db.flush()
    return phase


def _apply_order(db: DbSession, order: list[str]) -> None:
    for i, pid in enumerate(order):
        phase = db.get(Phase, _uuid(pid))
        if phase is not None:
            phase.sort_order = i
    db.flush()


def _apply_refs(db: DbSession, sheets: dict, items: dict) -> None:
    for sid, pid in (sheets or {}).items():
        sheet = db.get(Sheet, _uuid(sid))
        if sheet is not None:
            sheet.phase_id = _uuid(pid)
    for iid, pid in (items or {}).items():
        item = db.get(Item, _uuid(iid))
        if item is not None:
            item.phase_id = _uuid(pid)
    db.flush()


def apply(db: DbSession, action: Action, direction: str) -> None:
    state = action.before if direction == "before" else action.after
    kind = action.kind
    if kind == "phase_create":
        if direction == "before":
            phase = db.get(Phase, _uuid(action.after["phase"]["id"]))
            if phase is not None:
                db.delete(phase)
                db.flush()
        else:
            _restore_phase(db, action.after["phase"], action.after.get("lines", []), [])
    elif kind == "phase_edit":
        _restore_phase(db, state["phase"], [], [])
    elif kind == "phase_reorder":
        _apply_order(db, state["order"])
    elif kind == "phase_delete":
        if direction == "before":
            _restore_phase(db, action.before["phase"], action.before["lines"], action.before["plans"])
            _apply_order(db, action.before["order"])
            _apply_refs(db, action.before["sheets"], action.before["items"])
        else:
            _apply_refs(db, action.after["sheets"], action.after["items"])
            phase = db.get(Phase, _uuid(action.before["phase"]["id"]))
            if phase is not None:
                db.delete(phase)
                db.flush()
            _apply_order(db, action.after["order"])
    elif kind == "sheet_phase_set":
        _apply_refs(db, state["sheets"], {})
    elif kind == "item_phase_set":
        _apply_refs(db, {}, {str(action.item_id): state["phase_id"]})
    elif kind == "phase_propose_apply":
        if direction == "before":
            _apply_refs(db, action.before["sheets"], {})
            for snap in action.after["phases"]:
                phase = db.get(Phase, _uuid(snap["id"]))
                if phase is not None:
                    db.delete(phase)
            db.flush()
            _apply_order(db, action.before["order"])
        else:
            for snap in action.after["phases"]:
                _restore_phase(db, snap, snap.get("lines", []), [])
            _apply_order(db, action.after["order"])
            _apply_refs(db, action.after["sheets"], {})
    else:  # phase_line_edit, stage_plan_edit, lead_time_edit -- Task 6
        from app.schedule import overrides
        overrides.apply_undo(db, action, direction)
```

In `api/app/takeoff/undo.py:76` append the kinds:

```python
REVERSIBLE = {"approve", "reject", "unreject", "edit", "delete", "bulk_approve", "scale", "labor_edit",
              "material_price_edit", "supplier_quote_apply", "resolve",
              "phase_create", "phase_edit", "phase_reorder", "phase_delete", "sheet_phase_set", "item_phase_set",
              "phase_line_edit", "stage_plan_edit", "lead_time_edit", "phase_propose_apply"}

SCHEDULE_KINDS = {"phase_create", "phase_edit", "phase_reorder", "phase_delete", "sheet_phase_set", "item_phase_set",
                  "phase_line_edit", "stage_plan_edit", "lead_time_edit", "phase_propose_apply"}
```

In `api/app/takeoff/undo_apply.py::apply`, before the final `else`:

```python
    elif action.kind in SCHEDULE_KINDS:
        from app.schedule import undo_apply as schedule_undo
        schedule_undo.apply(db, action, direction)
```

(import `SCHEDULE_KINDS` from `app.takeoff.undo`; the local import avoids `app.schedule` importing `app.takeoff.undo_apply` at module load.)

**Delete snapshot.** In `review.py`'s delete snapshot builder (where `ProjectLaborLine` is captured) add `phase_id` to the item fields captured and capture the `ItemLeadTime` row's columns under `"lead_time"`; in `undo_apply._apply_delete` restore both the way `ProjectLaborLine` is restored. The test in `test_undo_redo.py` to append: delete an item that has `phase_id` set and an `ItemLeadTime` row, undo, assert both are back.

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_phases.py tests/test_undo_redo.py tests/test_merge.py tests/test_totals.py`
Expected: PASS. If `test_delete_moves_sheets_and_overrides_and_undoes_in_one_press` fails on `item.phase_id`, check `_apply_refs` is called with `action.before["items"]` on undo.

- [ ] **Step 6: Commit**

```bash
git add api/app/schedule/phases.py api/app/schedule/undo_apply.py api/app/takeoff/undo.py api/app/takeoff/undo_apply.py api/app/takeoff/review.py api/tests/test_schedule_phases.py api/tests/test_undo_redo.py api/tests/test_merge.py
git commit -m "Schedule: phases as records, resolved once, with every mutation audited and undoable

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Overrides — phase lines, stage plans, lead times

**Files:**
- Create: `api/app/schedule/overrides.py`
- Test: `api/tests/test_schedule_phases.py` (append)

**Interfaces:**
- Produces:

```python
def set_line_hours(db, *, actor, line: PhaseLine, hours: Decimal | None) -> PhaseLine            # kind phase_line_edit
def set_stage_plan(db, *, actor, phase: Phase, stage: str, changes: dict) -> PhaseStagePlan      # kind stage_plan_edit; a change value of None clears that field
def set_lead_time(db, *, actor, item: Item, changes: dict) -> ItemLeadTime                       # kind lead_time_edit; fields flagged, lead_weeks, source_label, quoted_at, needed_for_stage
def apply_undo(db, action, direction) -> None
```

`set_lead_time` with `lead_weeks` in `changes` sets `source = "estimator"` and requires a non-empty `source_label` (`DomainError("lead_time_source_needed", "Say who quoted this lead time — a supplier, a rep, or a manufacturer.")`); `lead_weeks: None` clears weeks, source, label, and date together. `quoted_at` defaults to the `today` the router passes.

- [ ] **Step 1: Write the failing tests**

```python
# append to api/tests/test_schedule_phases.py
from datetime import date
from app.schedule import overrides
from app.takeoff.models import ItemLeadTime, PhaseStagePlan


def test_line_hours_override_and_reset(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    line = db.query(PhaseLine).filter_by(phase_id=first.id).order_by(PhaseLine.sort_order).first()
    overrides.set_line_hours(db, actor=dana, line=line, hours=Decimal("12"))
    db.commit()
    assert line.hours_override == Decimal("12.00")
    overrides.set_line_hours(db, actor=dana, line=line, hours=None)
    db.commit()
    assert line.hours_override is None
    undo.undo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(line)
    assert line.hours_override == Decimal("12.00")


def test_stage_plan_is_sparse_and_clears_per_field(db, project, dana):
    first = svc.first_phase(db, project, create=True)
    row = overrides.set_stage_plan(db, actor=dana, phase=first, stage="rough_in", changes={"journeyman": 4, "start_date": date(2026, 10, 19)})
    db.commit()
    assert row.journeyman == 4 and row.foreman is None
    overrides.set_stage_plan(db, actor=dana, phase=first, stage="rough_in", changes={"journeyman": None})
    db.commit(); db.refresh(row)
    assert row.journeyman is None and row.start_date == date(2026, 10, 19)
    with pytest.raises(DomainError):
        overrides.set_stage_plan(db, actor=dana, phase=first, stage="painting", changes={"journeyman": 1})


def test_lead_time_needs_a_source_and_clears_together(db, project, item, dana):
    with pytest.raises(DomainError) as e:
        overrides.set_lead_time(db, actor=dana, item=item, changes={"lead_weeks": 40}, today=date(2026, 9, 21))
    assert e.value.code == "lead_time_source_needed"
    row = overrides.set_lead_time(db, actor=dana, item=item, changes={"lead_weeks": 40, "source_label": "Eaton rep"}, today=date(2026, 9, 21))
    db.commit()
    assert (row.source, row.quoted_at, row.flagged) == ("estimator", date(2026, 9, 21), True)
    overrides.set_lead_time(db, actor=dana, item=item, changes={"lead_weeks": None}, today=date(2026, 9, 21))
    db.commit(); db.refresh(row)
    assert row.lead_weeks is None and row.source is None and row.source_label == "" and row.quoted_at is None
    undo.undo(db, actor=dana, project_id=project.id); db.commit(); db.refresh(row)
    assert row.lead_weeks == 40 and row.source_label == "Eaton rep"


def test_unflag_keeps_the_row_but_hides_it(db, project, item, dana):
    row = overrides.set_lead_time(db, actor=dana, item=item, changes={"flagged": False}, today=date(2026, 9, 21))
    db.commit()
    assert row.flagged is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_phases.py -k "line_hours or stage_plan or lead_time or unflag"`
Expected: FAIL — `ImportError: app.schedule.overrides`

- [ ] **Step 3: Write `overrides.py`**

```python
# api/app/schedule/overrides.py
"""The estimator's overrides on a phase (phases-and-timeline.md §3.2,
§3.5, §3.7): sparse rows, every field independent, null = computed.
Same shape as ProjectLaborLine, same snapshot discipline."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.schedule.stages import STAGE_LABELS, STAGES
from app.takeoff import actions
from app.takeoff.actions import encode_snapshot
from app.takeoff.models import Action, Item, ItemLeadTime, Phase, PhaseLine, PhaseStagePlan

PLAN_FIELDS = ("foreman", "journeyman", "apprentice", "productive_hours_per_day", "hours_override", "start_date", "duration_days")
LEAD_FIELDS = ("flagged", "lead_weeks", "source", "source_label", "quoted_at", "needed_for_stage")


def _snap(row, fields) -> dict | None:
    return None if row is None else encode_snapshot({f: getattr(row, f) for f in fields})


def set_line_hours(db: DbSession, *, actor: User, line: PhaseLine, hours: Decimal | None) -> PhaseLine:
    phase = db.get(Phase, line.phase_id)
    before = {"hours_override": encode_snapshot({"v": line.hours_override})["v"]}
    line.hours_override = hours
    line.updated_by_user_id = actor.id
    db.flush()
    db.refresh(line)
    label = f"Set {line.label} to {line.hours_override} hours on {phase.name}" if hours is not None else f"Reset {line.label} on {phase.name} to computed"
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="phase_line_edit", label=label,
                   before={"line_id": str(line.id), **before},
                   after={"line_id": str(line.id), "hours_override": encode_snapshot({"v": line.hours_override})["v"]})
    return line


def set_stage_plan(db: DbSession, *, actor: User, phase: Phase, stage: str, changes: dict) -> PhaseStagePlan:
    if stage not in STAGES:
        raise DomainError("unknown_stage", "That isn't one of the six stages.")
    changes = {k: v for k, v in changes.items() if k in PLAN_FIELDS}
    if not changes:
        raise DomainError("no_changes_to_apply", "This update has no changes. Include at least one field, such as a crew count or a start date.")
    row = db.query(PhaseStagePlan).filter_by(phase_id=phase.id, stage=stage).one_or_none()
    before = _snap(row, PLAN_FIELDS)
    if row is None:
        row = PhaseStagePlan(phase_id=phase.id, stage=stage)
        db.add(row)
    for k, v in changes.items():
        setattr(row, k, v)
    row.updated_by_user_id = actor.id
    db.flush()
    db.refresh(row)
    cleared = [k for k, v in changes.items() if v is None]
    label = (f"Reset {STAGE_LABELS[stage].lower()} on {phase.name} to computed" if cleared and len(cleared) == len(changes)
             else f"Changed {STAGE_LABELS[stage].lower()} on {phase.name}")
    actions.commit(db, actor=actor, project_id=phase.project_id, kind="stage_plan_edit", label=label,
                   before={"phase_id": str(phase.id), "stage": stage, "row": before},
                   after={"phase_id": str(phase.id), "stage": stage, "row": _snap(row, PLAN_FIELDS)})
    return row


def set_lead_time(db: DbSession, *, actor: User, item: Item, changes: dict, today: date) -> ItemLeadTime:
    changes = {k: v for k, v in changes.items() if k in ("flagged", "lead_weeks", "source_label", "quoted_at", "needed_for_stage")}
    if not changes:
        raise DomainError("no_changes_to_apply", "This update has no changes.")
    if "needed_for_stage" in changes and changes["needed_for_stage"] not in STAGES:
        raise DomainError("unknown_stage", "That isn't one of the six stages.")
    row = db.get(ItemLeadTime, item.id)
    before = _snap(row, LEAD_FIELDS)
    if row is None:
        row = ItemLeadTime(item_id=item.id, flagged=True)
        db.add(row)
    if "lead_weeks" in changes:
        if changes["lead_weeks"] is None:
            row.lead_weeks, row.source, row.source_label, row.quoted_at = None, None, "", None
        else:
            label = (changes.get("source_label") or row.source_label or "").strip()
            if not label:
                raise DomainError("lead_time_source_needed", "Say who quoted this lead time — a supplier, a rep, or a manufacturer.")
            row.lead_weeks, row.source, row.source_label = int(changes["lead_weeks"]), "estimator", label
            row.quoted_at = changes.get("quoted_at") or today
            row.flagged = True
    elif "source_label" in changes and row.lead_weeks is not None:
        row.source_label = (changes["source_label"] or "").strip()
    if "quoted_at" in changes and "lead_weeks" not in changes and row.lead_weeks is not None:
        row.quoted_at = changes["quoted_at"]
    if "flagged" in changes:
        row.flagged = bool(changes["flagged"])
    if "needed_for_stage" in changes:
        row.needed_for_stage = changes["needed_for_stage"]
    row.updated_by_user_id = actor.id
    db.flush()
    db.refresh(row)
    if "lead_weeks" in changes:
        label = f"Set lead time on {item.name} to {row.lead_weeks} weeks" if row.lead_weeks is not None else f"Cleared lead time on {item.name}"
    elif "flagged" in changes:
        label = f"{'Flagged' if row.flagged else 'Unflagged'} {item.name} as long-lead"
    else:
        label = f"Changed lead-time details on {item.name}"
    actions.commit(db, actor=actor, project_id=item.project_id, kind="lead_time_edit", label=label, item_id=item.id,
                   before={"row": before}, after={"row": _snap(row, LEAD_FIELDS)})
    return row


def _write(row, snap: dict | None, fields, decimals=(), dates=()):
    for f in fields:
        v = snap.get(f) if snap else None
        if v is not None and f in decimals:
            v = Decimal(v)
        if v is not None and f in dates:
            v = date.fromisoformat(v)
        setattr(row, f, v)


def apply_undo(db: DbSession, action: Action, direction: str) -> None:
    state = action.before if direction == "before" else action.after
    if action.kind == "phase_line_edit":
        line = db.get(PhaseLine, uuid.UUID(state["line_id"]))
        if line is not None:
            line.hours_override = Decimal(state["hours_override"]) if state["hours_override"] is not None else None
    elif action.kind == "stage_plan_edit":
        row = db.query(PhaseStagePlan).filter_by(phase_id=uuid.UUID(state["phase_id"]), stage=state["stage"]).one_or_none()
        if state["row"] is None:
            if row is not None:
                db.delete(row)
        else:
            if row is None:
                row = PhaseStagePlan(phase_id=uuid.UUID(state["phase_id"]), stage=state["stage"])
                db.add(row)
            _write(row, state["row"], PLAN_FIELDS, decimals=("productive_hours_per_day", "hours_override"), dates=("start_date",))
    elif action.kind == "lead_time_edit":
        row = db.get(ItemLeadTime, action.item_id)
        if state["row"] is None:
            if row is not None:
                db.delete(row)
        else:
            if row is None:
                row = ItemLeadTime(item_id=action.item_id)
                db.add(row)
            _write(row, state["row"], LEAD_FIELDS, dates=("quoted_at",))
            if row.source_label is None:
                row.source_label = ""
    db.flush()
```

- [ ] **Step 4: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_phases.py tests/test_undo_redo.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/schedule/overrides.py api/tests/test_schedule_phases.py
git commit -m "Schedule: the estimator's overrides on lines, stages, and lead times, each its own undoable action

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: The assembled read and the router

**Files:**
- Create: `api/app/schedule/assemble.py`, `api/app/schedule/schemas.py`, `api/app/schedule/router.py`
- Modify: `api/app/main.py` (append `app.include_router(schedule_router)` after the conversation router), `api/app/takeoff/schemas.py` (append fields to `ItemOut`, `ProjectOut`, the project patch body), `api/app/takeoff/snapshot.py` (`_item_out` / `item_out` gain `phase_id` resolved through `phases.phase_of`, and `phase_overridden = item.phase_id is not None`)
- Test: `api/tests/test_schedule_api.py`, `api/tests/test_tenancy.py` (append rows), `api/tests/test_projects.py` (append: the two dates round-trip)

**Interfaces:**
- Consumes: `plan.build_schedule`, `phases.*`, `overrides.*`, `defaults.load_company`, `pricing.resolve_labor`, `totals.countable_items`, `stages.long_lead_class`.
- Produces: `build_schedule_out(db, project, user, today) -> ScheduleOut`; the routes in spec §10.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_schedule_api.py
import uuid
from datetime import date
from decimal import Decimal

from app.takeoff.models import CompanyLaborRate, Item, ReviewStatus


def _rates(db, org):
    db.add(CompanyLaborRate(org_id=org.id, journeyman_rate=Decimal("85"), foreman_rate=Decimal("95"), apprentice_rate=Decimal("55")))
    db.flush()


def test_schedule_of_an_empty_project_has_one_implicit_phase(client, signed_in_user, project, db):
    r = client.get(f"/api/projects/{project.id}/schedule")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["phases"]) == 1 and body["phases"][0]["name"] == "Phase 1"
    assert body["relative"] is True and body["manpower"] == [] and body["leads"] == []
    assert body["unscheduled_count"] == 0 and body["multi_phase"] is False


def test_schedule_uses_resolved_labor_and_reports_unscheduled(client, signed_in_user, project, sheet, item, org, db):
    r = client.get(f"/api/projects/{project.id}/schedule").json()
    assert r["unscheduled_count"] == 1 and r["phases"][0]["bars"] == []
    _rates(db, org)
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.5})
    r = client.get(f"/api/projects/{project.id}/schedule").json()
    bar = {b["stage"]: b for b in r["phases"][0]["bars"]}["rough_in"]
    assert Decimal(bar["hours"]) == Decimal("3.15")     # 14 x 0.5 = 7 h, 45 %
    assert bar["sources"]["hours"] == "computed" and bar["crew"] == {"foreman": 1, "journeyman": 2, "apprentice": 2}
    assert r["defaults_in_use"]["splits"] is True


def test_create_assign_and_item_override_round_trip(client, signed_in_user, project, sheet, item, db):
    first = client.get(f"/api/projects/{project.id}/schedule").json()["phases"][0]
    r = client.post(f"/api/projects/{project.id}/phases", json={"name": "Phase 2", "after_phase_id": first["id"]})
    assert r.status_code == 201, r.text
    second = next(p for p in r.json()["phases"] if p["name"] == "Phase 2")
    r = client.put(f"/api/phases/{second['id']}/sheets", json={"sheet_ids": [str(sheet.id)]})
    assert r.status_code == 200
    snap = client.get(f"/api/projects/{project.id}/snapshot").json()
    row = next(i for i in snap["items"] if i["id"] == str(item.id))
    assert row["phase_id"] == second["id"] and row["phase_overridden"] is False
    r = client.patch(f"/api/items/{item.id}/phase", json={"phase_id": first["id"]})
    assert r.status_code == 200 and r.json()["phase_id"] == first["id"] and r.json()["phase_overridden"] is True
    body = client.get(f"/api/projects/{project.id}/schedule").json()
    assert body["multi_phase"] is True and [p["name"] for p in body["phases"]] == ["Phase 1", "Phase 2"]
    assert body["phases"][1]["sheet_ids"] == [str(sheet.id)] and body["phases"][1]["items_moved_out"] == 1


def test_delete_last_phase_is_409(client, signed_in_user, project):
    first = client.get(f"/api/projects/{project.id}/schedule").json()["phases"][0]
    r = client.delete(f"/api/phases/{first['id']}")
    assert r.status_code == 409 and r.json()["code"] == "last_phase"


def test_stage_plan_and_line_edits(client, signed_in_user, project, sheet, item, org, db):
    _rates(db, org)
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 2})
    first = client.get(f"/api/projects/{project.id}/schedule").json()["phases"][0]
    r = client.put(f"/api/phases/{first['id']}/stages/rough_in", json={"journeyman": 4, "start_date": "2026-10-19"})
    assert r.status_code == 200
    bar = {b["stage"]: b for b in r.json()["phases"][0]["bars"]}["rough_in"]
    assert bar["crew"]["journeyman"] == 4 and bar["sources"]["journeyman"] == "estimator" and bar["start"] == "2026-10-19"
    line = first["lines"][0]
    r = client.patch(f"/api/phases/{first['id']}/lines/{line['id']}", json={"hours": 12})
    assert r.status_code == 200 and r.json()["phases"][0]["lines"][0]["source"] == "estimator"


def test_lead_time_flag_and_order_by(client, signed_in_user, project, sheet, org, db):
    _rates(db, org)
    gear = Item(project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Switchboard MSB-1", system="Power",
                category="Distribution", quantity=1, unit="EA", status=ReviewStatus.READY, x=100, y=100)
    db.add(gear); db.flush()
    client.patch(f"/api/items/{gear.id}/labor", json={"hoursOverride": 42})
    body = client.get(f"/api/projects/{project.id}/schedule").json()
    lead = body["leads"][0]
    assert lead["item_id"] == str(gear.id) and lead["lead_weeks"] is None and lead["order_by"] is None and lead["source_label"] == ""
    r = client.patch(f"/api/items/{gear.id}/lead-time", json={"lead_weeks": 40, "source_label": "Graybar"})
    assert r.status_code == 200
    client.patch(f"/api/projects/{project.id}", json={"mobilization_date": "2027-02-22", "expected_award_date": "2026-12-01"})
    lead = client.get(f"/api/projects/{project.id}/schedule").json()["leads"][0]
    assert lead["order_by"] is not None and lead["passed"] is True and lead["note"].startswith("Order date has passed")


def test_propose_previews_then_applies_as_one_action(client, signed_in_user, project, sheet, db):
    from app.takeoff.models import Sheet
    for n in ("XE-1.0", "XED-1.0"):
        db.add(Sheet(project_id=project.id, number=n, title="", discipline="Electrical", revision="", scale="", scale_options=[], plan=""))
    db.flush()
    r = client.post(f"/api/projects/{project.id}/phases/propose", json={})
    assert r.status_code == 200
    preview = r.json()
    assert [p["name"] for p in preview["phases"]] == ["E sheets", "XE sheets"] or len(preview["phases"]) == 2
    assert client.get(f"/api/projects/{project.id}/schedule").json()["multi_phase"] is False
    r = client.post(f"/api/projects/{project.id}/phases/propose/apply", json=preview)
    assert r.status_code == 200
    body = client.get(f"/api/projects/{project.id}/schedule").json()
    assert body["multi_phase"] is True and len(body["phases"]) == 2
    client.post(f"/api/projects/{project.id}/undo")
    assert client.get(f"/api/projects/{project.id}/schedule").json()["multi_phase"] is False
```

Append to `TENANCY_TABLE` in `test_tenancy.py` (the fixture rows there give `p, s, i`; add a `phase` fixture in `conftest.py` that creates the first phase for `project` through `phases.first_phase(db, project, create=True)` and extend the lambda signature the table uses if it does not already accept extra fixtures — follow how `other_org_project` is threaded):

```python
    ("GET", "/api/projects/{project_id}/schedule", lambda p, s, i: f"/api/projects/{p.id}/schedule", None, None),
    ("POST", "/api/projects/{project_id}/phases", lambda p, s, i: f"/api/projects/{p.id}/phases", lambda p, s, i: {"name": "Phase 2"}, None),
    ("PATCH", "/api/items/{item_id}/phase", lambda p, s, i: f"/api/items/{i.id}/phase", lambda p, s, i: {"phase_id": None}, None),
    ("PATCH", "/api/items/{item_id}/lead-time", lambda p, s, i: f"/api/items/{i.id}/lead-time", lambda p, s, i: {"flagged": True}, None),
    ("POST", "/api/projects/{project_id}/phases/propose", lambda p, s, i: f"/api/projects/{p.id}/phases/propose", lambda p, s, i: {}, None),
    ("POST", "/api/projects/{project_id}/phases/propose/apply", lambda p, s, i: f"/api/projects/{p.id}/phases/propose/apply", lambda p, s, i: {"phases": [], "order": []}, None),
```

and a second small table, `PHASE_TENANCY_TABLE`, for the four phase-id routes (`PATCH /api/phases/{id}`, `DELETE`, `PUT …/sheets`, `PUT …/stages/rough_in`, `PATCH …/lines/{line_id}`) driven by the `phase` fixture, asserting 404 for the rival org exactly as the existing parametrized test does.

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_api.py`
Expected: FAIL — 404 on `/schedule` (no router)

- [ ] **Step 3: Write `schemas.py`**

```python
# api/app/schedule/schemas.py
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class CrewOut(BaseModel):
    foreman: int
    journeyman: int
    apprentice: int


class StageBarOut(BaseModel):
    stage: str
    label: str
    hours: Decimal
    crew: CrewOut
    productive_hours_per_day: Decimal
    duration_days: int
    start: date | None
    end: date | None
    start_week: int
    end_week: int
    sources: dict[str, str]
    needed_crew: int | None
    over_max: bool
    over_max_note: str = ""


class PhaseLineOut(BaseModel):
    id: uuid.UUID
    label: str
    hours: Decimal
    source: str
    percent_of_direct_hours: Decimal


class PhaseOut(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int
    start_date: date | None
    required_finish_date: date | None
    notes: str
    sheet_ids: list[uuid.UUID]
    items_moved_in: int
    items_moved_out: int
    direct_hours: Decimal
    general_conditions_hours: Decimal
    material_total: Decimal
    lines: list[PhaseLineOut]
    bars: list[StageBarOut]
    start: date | None
    end: date | None


class ManpowerWeekOut(BaseModel):
    week: int
    start: date | None
    foreman: int
    journeyman: int
    apprentice: int


class LeadOut(BaseModel):
    item_id: uuid.UUID
    item_name: str
    item_status: str
    phase_id: uuid.UUID
    phase_name: str
    lead_weeks: int | None
    source: str | None            # "supplier_quote" | "estimator" | "company" | None
    source_label: str
    quoted_at: date | None
    needed_for_stage: str
    needed_by: date | None
    order_by: date | None
    order_by_week: int | None
    passed: bool
    stale: bool
    note: str
    warning: dict | None


class ScheduleOut(BaseModel):
    multi_phase: bool
    relative: bool
    phases: list[PhaseOut]
    manpower: list[ManpowerWeekOut]
    peak_crew: int
    average_crew: Decimal
    leads: list[LeadOut]
    unscheduled_count: int
    unscheduled_note: str
    default_split_count: int
    defaults_in_use: dict[str, bool]   # {"splits": bool, "crews": bool}
    expected_award_date: date | None
    mobilization_date: date | None


class PhaseCreateIn(BaseModel):
    name: str = Field(default="", max_length=200)
    after_phase_id: uuid.UUID | None = None


class PhaseEditIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    required_finish_date: date | None = None
    notes: str | None = None
    sort_order: int | None = None


class SheetsIn(BaseModel):
    sheet_ids: list[uuid.UUID]


class ItemPhaseIn(BaseModel):
    phase_id: uuid.UUID | None


class LineIn(BaseModel):
    hours: Decimal | None


class StagePlanIn(BaseModel):
    foreman: int | None = None
    journeyman: int | None = None
    apprentice: int | None = None
    productive_hours_per_day: Decimal | None = None
    hours_override: Decimal | None = None
    start_date: date | None = None
    duration_days: int | None = None


class LeadTimeIn(BaseModel):
    flagged: bool | None = None
    lead_weeks: int | None = None
    source_label: str | None = None
    quoted_at: date | None = None
    needed_for_stage: str | None = None


class ProposedPhase(BaseModel):
    name: str
    sheet_numbers: list[str]
    sheet_ids: list[uuid.UUID]
    evidence: dict | None = None


class ProposeIn(BaseModel):
    phases: list[ProposedPhase] | None = None   # None = detect from sheet numbers


class ProposeOut(BaseModel):
    phases: list[ProposedPhase]
    note: str


class StageSplitOut(BaseModel):
    category_key: str
    category_label: str
    demolition: Decimal
    rough_in: Decimal
    wire_pull: Decimal
    gear: Decimal
    trim: Decimal
    closeout: Decimal
    firm_edited: bool


class StageSplitIn(BaseModel):
    category_label: str
    demolition: Decimal
    rough_in: Decimal
    wire_pull: Decimal
    gear: Decimal
    trim: Decimal
    closeout: Decimal


class StageCrewOut(BaseModel):
    stage: str
    label: str
    foreman: int
    journeyman: int
    apprentice: int
    productive_hours_per_day: Decimal
    productivity_factor: Decimal
    max_crew: int
    firm_edited: bool


class StageCrewIn(BaseModel):
    foreman: int
    journeyman: int
    apprentice: int
    productive_hours_per_day: Decimal
    productivity_factor: Decimal
    max_crew: int


class ScheduleSettingsOut(BaseModel):
    lead_time_stale_days: int


class PhaseLineTemplateOut(BaseModel):
    id: uuid.UUID
    label: str
    percent_of_direct_hours: Decimal
    sort_order: int


class PhaseLineTemplateIn(BaseModel):
    label: str
    percent_of_direct_hours: Decimal
    sort_order: int = 0


class CompanyLeadTimeOut(BaseModel):
    item_class: str
    lead_weeks: int
    source_label: str
    quoted_at: date


class CompanyLeadTimeIn(BaseModel):
    lead_weeks: int
    source_label: str
    quoted_at: date
```

Every `…In` above sets `model_config = {**CAMEL_MODEL_CONFIG, "extra": "forbid"}` (import `CAMEL_MODEL_CONFIG` from `app.takeoff.schemas`; it is `alias_generator = to_camel` with `populate_by_name = True`, so the client's `afterPhaseId` and a test's `after_phase_id` both land). Every `…Out` sets `model_config = MODEL_CONFIG` — snake_case on the wire, as `LaborRowOut` is, which is what `mapSchedule` in Task 9 reads.

- [ ] **Step 4: Write `assemble.py`**

```python
# api/app/schedule/assemble.py
"""Gathers what the pure module needs from the database and shapes its
answer (phases-and-timeline.md §4, §10). The one place the schedule
touches items -- through countable_items and resolve_labor, so a labor
override on the Labor screen moves a bar here."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.schedule import copy as words
from app.schedule import plan
from app.schedule.defaults import load_company
from app.schedule.phases import first_phase, phase_of, phases_for
from app.schedule.schemas import (
    CrewOut, LeadOut, ManpowerWeekOut, PhaseLineOut, PhaseOut, ScheduleOut, StageBarOut,
)
from app.schedule.stages import STAGE_LABELS, long_lead_class
from app.takeoff.models import (
    CompanyLaborHoursOverride, CompanyLaborRate, Item, ItemLeadTime, PhaseLine, PhaseStagePlan, Project,
    ProjectLaborLine, Sheet,
)
from app.takeoff.pricing import resolve_labor
from app.takeoff.totals import countable_items


def _split_rules(tables) -> dict[str, plan.SplitRule]:
    return {k: plan.SplitRule({s: getattr(r, s) for s in plan.STAGES}, r.firm_edited) for k, r in tables.splits.items()}


def _crew_rules(tables) -> dict[str, plan.CrewRule]:
    return {k: plan.CrewRule(c.foreman, c.journeyman, c.apprentice, c.productive_hours_per_day, c.productivity_factor, c.max_crew, c.firm_edited)
            for k, c in tables.crews.items()}


def _phase_inputs(db: DbSession, phases) -> list[plan.PhaseInput]:
    out = []
    for p in phases:
        lines = db.scalars(select(PhaseLine).where(PhaseLine.phase_id == p.id).order_by(PhaseLine.sort_order))
        plans = db.scalars(select(PhaseStagePlan).where(PhaseStagePlan.phase_id == p.id))
        out.append(plan.PhaseInput(
            phase_id=p.id, name=p.name, sort_order=p.sort_order, start_date=p.start_date, required_finish_date=p.required_finish_date,
            line_percents=[(l.id, l.label, l.percent_of_direct_hours, l.hours_override) for l in lines],
            overrides={r.stage: plan.StageOverride(r.foreman, r.journeyman, r.apprentice, r.productive_hours_per_day,
                                                   r.hours_override, r.start_date, r.duration_days) for r in plans},
        ))
    return out


def build_schedule_out(db: DbSession, project: Project, user: User, today: date) -> ScheduleOut:
    first = first_phase(db, project, create=True)
    phases = phases_for(db, project.id)
    tables = load_company(db, project.org_id)
    splits, crews = _split_rules(tables), _crew_rules(tables)

    rates = db.get(CompanyLaborRate, project.org_id)
    rows = db.execute(countable_items(project.id).add_columns(Sheet)).all()
    items_hours: list[plan.ItemHours] = []
    unscheduled = 0
    default_split = 0
    material_by_phase: dict[uuid.UUID, Decimal] = {}
    moved_in: dict[uuid.UUID, int] = {}
    moved_out: dict[uuid.UUID, int] = {}
    leads_in: list[plan.LeadInput] = []
    item_status: dict[uuid.UUID, str] = {}
    item_phase: dict[uuid.UUID, uuid.UUID] = {}
    for item, sheet in rows:
        pid = phase_of(item, sheet, first)
        item_phase[item.id] = pid
        item_status[item.id] = item.status.value
        if item.phase_id is not None and item.phase_id != (sheet.phase_id or first.id):
            moved_in[item.phase_id] = moved_in.get(item.phase_id, 0) + 1
            home = sheet.phase_id or first.id
            moved_out[home] = moved_out.get(home, 0) + 1
        material_by_phase[pid] = material_by_phase.get(pid, Decimal("0")) + (item.material_cost or Decimal("0"))
        override = db.get(ProjectLaborLine, item.id)
        company_hours = db.query(CompanyLaborHoursOverride).filter_by(org_id=project.org_id, item_name=item.name).one_or_none()
        labor = resolve_labor(item, project, override, company_rates=rates, company_hours=company_hours)
        if labor.adjusted_hours is None:
            unscheduled += 1
        else:
            ih = plan.ItemHours(item.id, pid, item.category, labor.adjusted_hours)
            _, fallback = plan.split_hours(ih, splits)
            default_split += 1 if fallback else 0
            items_hours.append(ih)
        lt = db.get(ItemLeadTime, item.id)
        klass = long_lead_class(f"{item.name}\n{item.description}")
        flagged = lt.flagged if lt is not None else klass is not None
        if not flagged:
            continue
        weeks, source, label, quoted = (lt.lead_weeks, lt.source, lt.source_label, lt.quoted_at) if lt and lt.lead_weeks is not None else (None, None, "", None)
        if weeks is None and klass in tables.lead_times:
            c = tables.lead_times[klass]
            weeks, source, label, quoted = c.lead_weeks, "company", c.source_label, c.quoted_at
        leads_in.append(plan.LeadInput(item.id, item.name, pid, True, weeks, source, label or "", quoted,
                                       lt.needed_for_stage if lt else "gear"))

    sched = plan.build_schedule(_phase_inputs(db, phases), items_hours, splits, crews, leads_in,
                                mobilization=project.mobilization_date, expected_award=project.expected_award_date,
                                today=today, stale_days=tables.settings.lead_time_stale_days)

    sheets_by_phase: dict[uuid.UUID, list[uuid.UUID]] = {}
    for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id, Sheet.superseded_at.is_(None)).order_by(Sheet.sort_order)):
        sheets_by_phase.setdefault(s.phase_id or first.id, []).append(s.id)

    by_id = {p.id: p for p in phases}
    phases_out = []
    for pp in sched.phases:
        p = by_id[pp.phase_id]
        phases_out.append(PhaseOut(
            id=p.id, name=p.name, sort_order=p.sort_order, start_date=p.start_date, required_finish_date=p.required_finish_date,
            notes=p.notes, sheet_ids=sheets_by_phase.get(p.id, []),
            items_moved_in=moved_in.get(p.id, 0), items_moved_out=moved_out.get(p.id, 0),
            direct_hours=pp.direct_hours, general_conditions_hours=pp.general_conditions_hours,
            material_total=plan.q(material_by_phase.get(p.id, Decimal("0"))),
            lines=[PhaseLineOut(id=l.line_id, label=l.label, hours=l.hours, source=l.source,
                                percent_of_direct_hours=next(pc for lid, _, pc, _ in _phase_inputs(db, [p])[0].line_percents if lid == l.line_id))
                   for l in pp.lines],
            bars=[StageBarOut(stage=b.stage, label=STAGE_LABELS[b.stage], hours=b.hours,
                              crew=CrewOut(foreman=b.foreman, journeyman=b.journeyman, apprentice=b.apprentice),
                              productive_hours_per_day=b.productive_hours_per_day, duration_days=b.duration_days,
                              start=b.start, end=b.end, start_week=b.start_week, end_week=b.end_week, sources=b.sources,
                              needed_crew=b.needed_crew, over_max=b.over_max,
                              over_max_note=words.over_max_crew(crews[b.stage].max_crew, STAGE_LABELS[b.stage], p.required_finish_date) if b.over_max else "")
                  for b in pp.bars],
            start=pp.start, end=pp.end,
        ))

    leads_out = []
    for L in sched.leads:
        warning = None
        if L.stale and L.quoted_at is not None:
            warning = words.stale_lead_time_warning((today - L.quoted_at).days, L.source_label)
        leads_out.append(LeadOut(item_id=L.item_id, item_name=L.item_name, item_status=item_status[L.item_id],
                                 phase_id=L.phase_id, phase_name=by_id[L.phase_id].name, lead_weeks=L.lead_weeks,
                                 source=L.source, source_label=L.source_label, quoted_at=L.quoted_at,
                                 needed_for_stage=L.needed_for_stage, needed_by=L.needed_by, order_by=L.order_by,
                                 order_by_week=L.order_by_week, passed=L.passed, stale=L.stale, note=L.note, warning=warning))

    return ScheduleOut(
        multi_phase=len(phases) > 1, relative=sched.relative, phases=phases_out,
        manpower=[ManpowerWeekOut(week=w.week, start=w.start, foreman=w.foreman, journeyman=w.journeyman, apprentice=w.apprentice) for w in sched.manpower],
        peak_crew=sched.peak_crew, average_crew=sched.average_crew, leads=leads_out,
        unscheduled_count=unscheduled, unscheduled_note=words.unscheduled_items(unscheduled) if unscheduled else "",
        default_split_count=default_split,
        defaults_in_use={"splits": not any(s.firm_edited for s in tables.splits.values()),
                         "crews": not any(c.firm_edited for c in tables.crews.values())},
        expected_award_date=project.expected_award_date, mobilization_date=project.mobilization_date,
    )
```

The `percent_of_direct_hours` lookup inside the `lines=` comprehension re-calls `_phase_inputs` per phase; replace it with a dict built once before the loop (`percent_by_line = {l.id: l.percent_of_direct_hours for l in all lines}`) when writing the file — it is written inline above only so every name is visible.

- [ ] **Step 5: Write `router.py`**

```python
# api/app/schedule/router.py
"""The schedule routes (phases-and-timeline.md §10). Tenancy through
load_project / load_item like every neighbour; every write through the
service modules, which commit() an action; db.commit() here."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.schedule import overrides, phases as svc
from app.schedule.assemble import build_schedule_out
from app.schedule.propose import apply_proposal, detect_from_sheet_numbers, preview_proposal
from app.schedule.schemas import (
    ItemPhaseIn, LeadTimeIn, LineIn, PhaseCreateIn, PhaseEditIn, PhaseOut, ProposeIn, ProposeOut, ScheduleOut, SheetsIn, StagePlanIn,
)
from app.takeoff.models import Phase, PhaseLine, Project
from app.takeoff.router import load_item, load_project, not_found
from app.takeoff.schemas import ItemOut

router = APIRouter(prefix="/api", tags=["schedule"])


def load_phase(phase_id: uuid.UUID, db: DbSession, user: User) -> Phase:
    phase = db.get(Phase, phase_id)
    if phase is None:
        raise not_found()
    load_project(phase.project_id, db, user)   # 404, never 403, on another org's phase
    return phase


def _out(db, project, user) -> ScheduleOut:
    return build_schedule_out(db, project, user, date.today())


@router.get("/projects/{project_id}/schedule", response_model=ScheduleOut)
def get_schedule(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    out = _out(db, project, user)
    db.commit()   # the implicit first phase and the org's seeded defaults, if this read created them
    return out


@router.post("/projects/{project_id}/phases", response_model=ScheduleOut, status_code=201)
def create_phase(project_id: uuid.UUID, body: PhaseCreateIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    svc.create_phase(db, actor=user, project=project, name=body.name, after_phase_id=body.after_phase_id)
    db.commit()
    return _out(db, project, user)
```

The create route returns the whole `ScheduleOut` (the test picks the new phase out of it). Continue:

```python
@router.patch("/phases/{phase_id}", response_model=ScheduleOut)
def edit_phase(phase_id: uuid.UUID, body: PhaseEditIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    if "sort_order" in changes:
        svc.reorder_phase(db, actor=user, phase=phase, sort_order=changes.pop("sort_order"))
    if changes:
        svc.edit_phase(db, actor=user, phase=phase, changes=changes)
    db.commit()
    return _out(db, db.get(Project, phase.project_id), user)


@router.delete("/phases/{phase_id}", response_model=ScheduleOut)
def delete_phase(phase_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    project_id = phase.project_id
    svc.delete_phase(db, actor=user, phase=phase)
    db.commit()
    return _out(db, db.get(Project, project_id), user)


@router.put("/phases/{phase_id}/sheets", response_model=ScheduleOut)
def put_sheets(phase_id: uuid.UUID, body: SheetsIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    svc.assign_sheets(db, actor=user, phase=phase, sheet_ids=body.sheet_ids)
    db.commit()
    return _out(db, db.get(Project, phase.project_id), user)


@router.patch("/items/{item_id}/phase", response_model=ItemOut)
def patch_item_phase(item_id: uuid.UUID, body: ItemPhaseIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    item = load_item(item_id, db, user)
    svc.set_item_phase(db, actor=user, item=item, phase_id=body.phase_id)
    db.commit()
    from app.takeoff.snapshot import item_out   # the existing single-item serializer (snapshot.py:136)
    return item_out(db, item)


@router.patch("/phases/{phase_id}/lines/{line_id}", response_model=ScheduleOut)
def patch_line(phase_id: uuid.UUID, line_id: uuid.UUID, body: LineIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    line = db.get(PhaseLine, line_id)
    if line is None or line.phase_id != phase.id:
        raise not_found()
    overrides.set_line_hours(db, actor=user, line=line, hours=body.hours)
    db.commit()
    return _out(db, db.get(Project, phase.project_id), user)


@router.put("/phases/{phase_id}/stages/{stage}", response_model=ScheduleOut)
def put_stage_plan(phase_id: uuid.UUID, stage: str, body: StagePlanIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    phase = load_phase(phase_id, db, user)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    overrides.set_stage_plan(db, actor=user, phase=phase, stage=stage, changes=changes)
    db.commit()
    return _out(db, db.get(Project, phase.project_id), user)


@router.patch("/items/{item_id}/lead-time", response_model=ScheduleOut)
def patch_lead_time(item_id: uuid.UUID, body: LeadTimeIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    item = load_item(item_id, db, user)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    overrides.set_lead_time(db, actor=user, item=item, changes=changes, today=date.today())
    db.commit()
    return _out(db, db.get(Project, item.project_id), user)


@router.post("/projects/{project_id}/phases/propose", response_model=ProposeOut)
def propose(project_id: uuid.UUID, body: ProposeIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    proposed = body.phases if body.phases is not None else detect_from_sheet_numbers(db, project)
    return preview_proposal(db, project, proposed)


@router.post("/projects/{project_id}/phases/propose/apply", response_model=ScheduleOut)
def propose_apply(project_id: uuid.UUID, body: ProposeOut, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    apply_proposal(db, actor=user, project=project, phases=body.phases)
    db.commit()
    return _out(db, project, user)
```

Company routes (`/company/stage-splits`, `/company/stage-crews`, `/company/schedule-settings`, `/company/phase-line-templates`, `/company/lead-times`) follow `put_company_labor_rates` exactly: `_snapshot` before, mutate, `db.flush(); db.refresh(row)`, `_snapshot` after, `record_company_action(kind=…)`, `db.commit()`. `PUT /company/stage-splits/{category_key}` validates the six sum to 100 (`DomainError("split_must_total_100", "The six stages have to add up to 100 percent.")`) before the flush so the check constraint is never what answers, and sets `firm_edited = True`; the same for crews. Import `record_company_action` and `_snapshot` from `app.takeoff.pricing_router`.

- [ ] **Step 6: Write `propose.py`**

```python
# api/app/schedule/propose.py
"""Phases proposed, never created without a press (phases-and-timeline.md
§9). detect_from_sheet_numbers is this stream's one detector -- sheet
families by the letters before the first digit -- and is what stream F's
plan record replaces as the input; preview and apply stay."""
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.schedule.phases import _add_template_lines, _lines_snapshot, _snapshot_phase, first_phase, phases_for
from app.schedule.schemas import ProposedPhase, ProposeOut
from app.takeoff import actions
from app.takeoff.models import Phase, Project, Sheet

_FAMILY = re.compile(r"^\s*([A-Za-z]+)")


def _family(number: str) -> str:
    m = _FAMILY.match(number or "")
    return m.group(1).upper() if m else ""


def detect_from_sheet_numbers(db: DbSession, project: Project) -> list[ProposedPhase]:
    sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id, Sheet.superseded_at.is_(None), Sheet.kind == "plan")))
    families: dict[str, list[Sheet]] = {}
    for s in sheets:
        families.setdefault(_family(s.number), []).append(s)
    families.pop("", None)
    if len(families) < 2:
        return []
    out = []
    for fam in sorted(families, key=lambda f: (len(f), f)):
        rows = sorted(families[fam], key=lambda s: s.number)
        out.append(ProposedPhase(name=f"{fam} sheets", sheet_numbers=[s.number for s in rows], sheet_ids=[s.id for s in rows], evidence=None))
    return out


def preview_proposal(db: DbSession, project: Project, phases: list[ProposedPhase]) -> ProposeOut:
    if not phases:
        return ProposeOut(phases=[], note="No phasing found in the sheet numbers. Add phases by hand, or assign sheets to one.")
    known = {s.id for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id))}
    for p in phases:
        if any(sid not in known for sid in p.sheet_ids):
            raise DomainError("sheet_not_found", "One of those sheets isn't on this project.")
    n = sum(len(p.sheet_ids) for p in phases)
    return ProposeOut(phases=phases, note=f"{len(phases)} phases from {n} sheets. Nothing changes until you confirm.")


def apply_proposal(db: DbSession, *, actor: User, project: Project, phases: list[ProposedPhase]) -> None:
    if not phases:
        raise DomainError("nothing_to_apply", "There are no phases to apply.")
    first = first_phase(db, project, create=True)
    existing = phases_for(db, project.id)
    sheets_before = {str(s.id): (str(s.phase_id) if s.phase_id else None) for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id))}
    created: list[Phase] = []
    sheets_after: dict[str, str | None] = {}
    # The first proposed phase renames the implicit first phase rather than adding beside it.
    for i, p in enumerate(phases):
        if i == 0 and len(existing) == 1 and existing[0].name == "Phase 1":
            phase = existing[0]
            phase.name = p.name
            target = None
        else:
            phase = Phase(project_id=project.id, name=p.name, sort_order=len(existing) + len(created))
            db.add(phase); db.flush()
            _add_template_lines(db, project.org_id, phase)
            created.append(phase)
            target = str(phase.id)
        for sid in p.sheet_ids:
            sheet = db.get(Sheet, sid)
            sheet.phase_id = None if target is None else phase.id
            sheets_after[str(sid)] = target
    db.flush()
    order_after = [str(p.id) for p in phases_for(db, project.id)]
    actions.commit(db, actor=actor, project_id=project.id, kind="phase_propose_apply",
                   label=f"Set up {len(phases)} phases from the drawings",
                   before={"sheets": {k: sheets_before[k] for k in sheets_after}, "order": [str(p.id) for p in existing],
                           "first_name": existing[0].name if existing else "Phase 1"},
                   after={"phases": [_snapshot_phase(c) | {"lines": _lines_snapshot(db, c.id)} for c in created],
                          "sheets": sheets_after, "order": order_after, "first_name": phases[0].name})
```

`schedule/undo_apply.py`'s `phase_propose_apply` branch also restores `first_name` onto the first phase in each direction (add `db.get(Phase, uuid(order[0])).name = state["first_name"]` after `_apply_order`).

- [ ] **Step 7: Wire `ItemOut` and the project dates**

In `takeoff/schemas.py` append to `ItemOut`: `phase_id: uuid.UUID | None = None`, `phase_overridden: bool = False`; to `ProjectOut` and the project patch/create bodies: `expected_award_date: date | None = None`, `mobilization_date: date | None = None`. In `takeoff/snapshot.py`, `_item_out(item, warnings, approved_by_name)` (line 103) builds every `ItemOut`; give it two more parameters, `phase_id` and `phase_overridden`, and have its two callers pass `phases.phase_of(item, sheet, first)` — `first = phases.first_phase(db, project)` computed once per snapshot, None when no phase row exists yet (the client treats None as "the only phase") — and `item.phase_id is not None`. `item_out(db, item)` (line 136) does the same for one item. The project PATCH route copies the two dates like `postal_code`.

- [ ] **Step 8: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_schedule_api.py tests/test_tenancy.py tests/test_projects.py tests/test_api_import_boundary.py`
Expected: PASS. The import-boundary test must still pass: `app.schedule` imports nothing from `app.engine` or `app.worker`.

- [ ] **Step 9: Commit**

```bash
git add api/app/schedule api/app/main.py api/app/takeoff/schemas.py api/app/takeoff/snapshot.py api/app/takeoff/router.py api/tests/test_schedule_api.py api/tests/test_tenancy.py api/tests/test_projects.py api/tests/conftest.py
git commit -m "Schedule: the read that assembles every bar, the routes, and phases proposed from sheet families

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The supplier's lead time on the price sheet

**Files:**
- Modify: `api/app/market/price_sheet.py` (`HEADER`, `ParsedRow`, `parse_price_sheet`; the request writer), `api/app/worker/price_sheet_job.py` (the preview's matched rows carry `lead_weeks`), `api/app/takeoff/price_sheet_router.py::apply_price_sheet` (writes `ItemLeadTime` per ticked row that carries weeks), `api/app/takeoff/undo_apply.py` (`supplier_quote_apply` replays `lead_time` per row)
- Test: `api/tests/test_market_price_sheet.py`, `api/tests/test_worker_price_sheet.py`, `api/tests/test_pricing_endpoints.py` (append to each)

**Interfaces:**
- `ParsedRow` gains `lead_weeks: int | None` and `lead_error: str | None`; the preview's matched rows gain `lead_weeks`; `supplier_quote_apply`'s per-row `before`/`after` gain `"lead_time": {…} | None` beside the material-price snapshot — the row shape becomes `{"price": <snapshot>, "lead_time": <snapshot | None>}`. Because that changes the shape `undo_apply` reads for an existing kind, the replay accepts both: a row that is a flat snapshot (pre-change actions) and a row with `price`/`lead_time` keys.

- [ ] **Step 1: Write the failing tests**

```python
# append to api/tests/test_market_price_sheet.py
from app.market.price_sheet import HEADER, build_price_request, parse_price_sheet


def test_request_has_a_blank_lead_time_column():
    assert HEADER.index("Lead time (weeks)") == HEADER.index("Supplier part no.") + 1


def _csv(rows):
    return ("\n".join(",".join(r) for r in rows)).encode()


def test_lead_time_is_optional_and_parsed_as_whole_weeks():
    data = _csv([["Item", "Unit price", "Lead time (weeks)", "Row key"],
                 ["Switchboard MSB-1", "12000", "40", "k1"],
                 ["Panel LP-2", "900", "", "k2"]])
    rows = parse_price_sheet(data, "quote.csv").rows
    assert rows[0].lead_weeks == 40 and rows[0].lead_error is None
    assert rows[1].lead_weeks is None and rows[1].lead_error is None


def test_a_sheet_without_the_column_still_parses():
    data = _csv([["Item", "Unit price", "Row key"], ["Panel LP-2", "900", "k2"]])
    parsed = parse_price_sheet(data, "quote.csv")
    assert parsed.refused is None and parsed.rows[0].lead_weeks is None


def test_non_numeric_lead_time_is_named_by_row():
    data = _csv([["Item", "Unit price", "Lead time (weeks)", "Row key"], ["Switchboard MSB-1", "12000", "12 wks", "k1"]])
    rows = parse_price_sheet(data, "quote.csv").rows
    assert rows[0].lead_weeks is None and rows[0].lead_error == "Row 2: the lead time isn't a number of weeks"
```

Stream A's per-row `unreadable` group is where `lead_error` lands in the preview: a row with a good price and a bad lead time is *matched* (its price applies) and also listed under `unreadable` with the lead-time reason — never dropped. In `test_worker_price_sheet.py`, append a test that a matched row with `lead_weeks = 40` in the sheet shows `"lead_weeks": 40` in the preview's matched entry. In `test_pricing_endpoints.py`, append:

```python
def test_apply_writes_lead_time_and_undo_removes_it(client, signed_in_user, project, item, db, monkeypatch):
    # Reuse the file's existing helper that stores a preview on a price_sheet job for `project`; give the
    # matched row for `item` "new_unit_price": "12000.00" and "lead_weeks": 40.
    ...
    r = client.post(f"/api/projects/{project.id}/material-pricing/price-sheets/{doc_id}/apply",
                    json={"itemIds": [str(item.id)], "supplierName": "Graybar", "quoteDate": "2026-09-12"})
    assert r.status_code == 200
    lt = db.get(ItemLeadTime, item.id)
    assert (lt.lead_weeks, lt.source, lt.source_label, str(lt.quoted_at)) == (40, "supplier_quote", "Graybar", "2026-09-12")
    client.post(f"/api/projects/{project.id}/undo")
    db.expire_all()
    assert db.get(ItemLeadTime, item.id) is None
```

(The `...` is the file's own preview-seeding helper — find it by `grep -n "preview" api/tests/test_pricing_endpoints.py` and call it the way the existing apply test does.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_market_price_sheet.py -k lead`
Expected: FAIL — `ValueError: 'Lead time (weeks)' is not in tuple`

- [ ] **Step 3: Change the parser**

In `price_sheet.py`:

```python
HEADER = ("Item", "Description", "Qty", "Unit", "Unit price", "Supplier part no.", "Lead time (weeks)", "Notes", "Row key")
_LEAD_RE = re.compile(r"^\s*(\d{1,3})\s*$")


def _lead(cell, line: int) -> tuple[int | None, str | None]:
    if cell is None or str(cell).strip() == "":
        return None, None
    s = str(cell).strip()
    if isinstance(cell, (int, float)) and float(cell).is_integer() and 0 <= cell < 1000:
        return int(cell), None
    m = _LEAD_RE.match(s)
    if m:
        return int(m.group(1)), None
    return None, f"Row {line}: the lead time isn't a number of weeks"
```

`ParsedRow` gains `lead_weeks: int | None = None` and `lead_error: str | None = None`; in `parse_price_sheet` add `lead_weeks, lead_error = _lead(cell("Lead time (weeks)"), n)` and pass both. `build_price_request` writes the column blank in the position `HEADER` gives it (the hidden `Row key` column index moves by one — `_KEY_COL` is derived from `HEADER`, so nothing else changes).

- [ ] **Step 4: Carry it through the preview and apply**

`price_sheet_job.py`: the matched row dict gains `"lead_weeks": row.lead_weeks`; a row with `lead_error` also appends `{"line": row.line, "reason": row.lead_error}` to the `unreadable` group. `apply_price_sheet`: after the material row is written for `item_id`, if `by_id[item_id].get("lead_weeks") is not None`:

```python
        lead_before = _snapshot(ItemLeadTime, iid, db)
        lt = db.get(ItemLeadTime, iid) or ItemLeadTime(item_id=iid)
        lt.flagged, lt.lead_weeks, lt.source = True, int(by_id[item_id]["lead_weeks"]), "supplier_quote"
        lt.source_label, lt.quoted_at, lt.updated_by_user_id = body.supplier_name, body.quote_date, user.id
        db.add(lt); db.flush(); db.refresh(lt)
        before[item_id] = {"price": before[item_id], "lead_time": lead_before}
        after[item_id] = {"price": after[item_id], "lead_time": _snapshot(ItemLeadTime, iid, db)}
```

and rows without weeks keep the flat shape. In `takeoff/undo_apply.apply`'s `supplier_quote_apply` branch:

```python
        for item_id, row_state in (state.get("rows") or {}).items():
            price_state = row_state.get("price") if isinstance(row_state, dict) and "price" in row_state else row_state
            _apply_sparse_pricing_row(db, ProjectMaterialPrice, uuid.UUID(item_id), MATERIAL_PRICE_SNAPSHOT_TYPES, price_state)
            if isinstance(row_state, dict) and "lead_time" in row_state:
                _apply_sparse_pricing_row(db, ItemLeadTime, uuid.UUID(item_id), LEAD_TIME_SNAPSHOT_TYPES, row_state["lead_time"])
```

with `LEAD_TIME_SNAPSHOT_TYPES = {"quoted_at": "date", "updated_at": "datetime", "item_id": "uuid", "updated_by_user_id": "uuid"}` next to `MATERIAL_PRICE_SNAPSHOT_TYPES` (same encoding convention that file already uses).

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_market_price_sheet.py tests/test_worker_price_sheet.py tests/test_pricing_endpoints.py tests/test_undo_redo.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/market/price_sheet.py api/app/worker/price_sheet_job.py api/app/takeoff/price_sheet_router.py api/app/takeoff/undo_apply.py api/tests/test_market_price_sheet.py api/tests/test_worker_price_sheet.py api/tests/test_pricing_endpoints.py
git commit -m "Price sheet: a lead-time column the supplier fills, applied to the item with the quote's name and date

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: The client store surface, the stage vocabulary, and the copy

**Files:**
- Create: `src/components/schedule/stages.js`, `src/components/schedule/scheduleCopy.js`
- Modify: `src/lib/store/api-mapping.js` (append `mapSchedule`, `mapStageSplit`, `mapStageCrew`, `mapCompanyLeadTime`), `src/lib/store/api.js` (append the functions and export them), `src/lib/store/api-mapping.test.js` (or the file's neighbour)
- Test: `src/components/schedule/stages.test.js`, `src/lib/store/api-mapping.schedule.test.js`

**Interfaces:**
- Produces on `store` (all return mapped shapes; every mutation returns the mapped `ScheduleOut` except `setItemPhase`, which returns the mapped item):

```js
getSchedule(projectId)
createPhase(projectId, { name, afterPhaseId })
editPhase(phaseId, changes)                 // name, startDate, requiredFinishDate, notes, sortOrder
deletePhase(phaseId)
setPhaseSheets(phaseId, sheetIds)
setItemPhase(itemId, phaseId | null)
setPhaseLine(phaseId, lineId, hours | null)
setStagePlan(phaseId, stage, changes)       // any of foreman, journeyman, apprentice, productiveHoursPerDay, hoursOverride, startDate, durationDays; null clears
setLeadTime(itemId, changes)                // flagged, leadWeeks, sourceLabel, quotedAt, neededForStage
proposePhases(projectId, phases | null)
applyProposedPhases(projectId, proposal)
getStageSplits(), setStageSplit(categoryKey, values), deleteStageSplit(categoryKey)
getStageCrews(), setStageCrew(stage, values)
getScheduleSettings(), setScheduleSettings(values)
getPhaseLineTemplates(), setPhaseLineTemplate(id | null, values), deletePhaseLineTemplate(id)
getCompanyLeadTimes(), setCompanyLeadTime(itemClass, values), deleteCompanyLeadTime(itemClass)
```

- [ ] **Step 1: Write the failing tests**

```js
// src/components/schedule/stages.test.js
import { describe, expect, it } from "vitest";
import { STAGES, STAGE_LABELS, stageLabel } from "./stages.js";

describe("stages", () => {
  it("has the six stages in order, mirroring api/app/schedule/stages.py", () => {
    expect(STAGES).toEqual(["demolition", "rough_in", "wire_pull", "gear", "trim", "closeout"]);
    expect(STAGE_LABELS.rough_in).toBe("Rough-in");
    expect(stageLabel("closeout")).toBe("Close-out");
    expect(stageLabel("painting")).toBe("painting");
  });
});
```

```js
// src/lib/store/api-mapping.schedule.test.js
import { describe, expect, it } from "vitest";
import { mapSchedule } from "./api-mapping.js";

const wire = {
  multi_phase: true, relative: false, peak_crew: 6, average_crew: "4.50", unscheduled_count: 2,
  unscheduled_note: "2 items aren't in the schedule yet — they need labor hours", default_split_count: 1,
  defaults_in_use: { splits: true, crews: false }, expected_award_date: null, mobilization_date: "2026-10-05",
  manpower: [{ week: 1, start: "2026-10-05", foreman: 1, journeyman: 2, apprentice: 2 }],
  leads: [{ item_id: "i1", item_name: "Switchboard MSB-1", item_status: "ready", phase_id: "p1", phase_name: "Phase 1",
            lead_weeks: null, source: null, source_label: "", quoted_at: null, needed_for_stage: "gear", needed_by: "2026-10-14",
            order_by: null, order_by_week: null, passed: false, stale: false, note: "", warning: null }],
  phases: [{ id: "p1", name: "Phase 1", sort_order: 0, start_date: null, required_finish_date: null, notes: "", sheet_ids: ["s1"],
             items_moved_in: 0, items_moved_out: 0, direct_hours: "100.00", general_conditions_hours: "7.00", material_total: "0.00",
             lines: [{ id: "l1", label: "Final and daily cleanup", hours: "3.00", source: "computed", percent_of_direct_hours: "3.00" }],
             bars: [{ stage: "rough_in", label: "Rough-in", hours: "48.15", crew: { foreman: 1, journeyman: 2, apprentice: 2 },
                      productive_hours_per_day: "6.00", duration_days: 2, start: "2026-10-05", end: "2026-10-06", start_week: 1, end_week: 1,
                      sources: { hours: "computed", journeyman: "estimator" }, needed_crew: null, over_max: false, over_max_note: "" }],
             start: "2026-10-05", end: "2026-10-14" }],
};

describe("mapSchedule", () => {
  it("camelCases, numbers the decimals, and keeps dates as ISO strings", () => {
    const s = mapSchedule(wire);
    expect(s.multiPhase).toBe(true);
    expect(s.averageCrew).toBe(4.5);
    expect(s.phases[0].bars[0].hours).toBe(48.15);
    expect(s.phases[0].bars[0].crew).toEqual({ foreman: 1, journeyman: 2, apprentice: 2 });
    expect(s.phases[0].bars[0].sources.journeyman).toBe("estimator");
    expect(s.phases[0].lines[0].percentOfDirectHours).toBe(3);
    expect(s.leads[0].leadWeeks).toBeNull();
    expect(s.leads[0].neededBy).toBe("2026-10-14");
    expect(s.manpower[0].crew).toBe(5);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/components/schedule/stages.test.js src/lib/store/api-mapping.schedule.test.js`
Expected: FAIL — cannot resolve `./stages.js`; `mapSchedule` is not exported

- [ ] **Step 3: Write `stages.js` and `scheduleCopy.js`**

```js
// src/components/schedule/stages.js
/* The six stages, mirroring api/app/schedule/stages.py. The order is
   the order work runs per area; the labels are the only words the
   screen uses for a stage. */
export const STAGES = ["demolition", "rough_in", "wire_pull", "gear", "trim", "closeout"];

export const STAGE_LABELS = {
  demolition: "Demolition",
  rough_in: "Rough-in",
  wire_pull: "Wire pull",
  gear: "Gear",
  trim: "Trim",
  closeout: "Close-out",
};

export function stageLabel(key) {
  return STAGE_LABELS[key] ?? key;
}

export const ROLES = [
  { key: "foreman", label: "Foreman", short: "F" },
  { key: "journeyman", label: "Journeyman", short: "J" },
  { key: "apprentice", label: "Apprentice", short: "A" },
];

/** "1F 2J 2A" — the crew as the bar labels it. */
export function crewText(crew) {
  return ROLES.map((r) => `${crew[r.key] ?? 0}${r.short}`).join(" ");
}
```

```js
// src/components/schedule/scheduleCopy.js
/* Every string on the schedule screen, one place (spec §5). Sentence
   case; no "AI", no confidence, no "recommended". Numbers of weeks come
   from rows, never from here. */
export const COPY = {
  title: "Phases and schedule",
  intro: "Hours from the takeoff, placed in time. Every computed value is a starting point you can change.",
  computed: "Computed",
  yours: "Yours",
  defaultSplit: "Default split — set yours in Company settings",
  defaultCrew: "Default crew — set yours in Company settings",
  defaultSplitCount: (n) => `${n} item${n === 1 ? "" : "s"} use${n === 1 ? "s" : ""} the default split`,
  relativeAxis: "Weeks are relative — add a mobilization date in Project settings to see calendar dates.",
  nothingToSchedule: "Nothing to schedule yet. Labor hours come from the Labor workspace.",
  noDemolition: "No demolition items yet",
  addPhase: "Add phase",
  assignSheets: "Assign sheets",
  deletePhase: "Remove phase",
  deletePhaseConfirm: (name, target) => `Remove ${name}? Its sheets move to ${target}. This can be undone.`,
  lastPhase: "A project keeps at least one phase. Rename this one instead.",
  proposeFromSheets: "Propose phases from sheet numbers",
  proposeNothing: "No phasing found in the sheet numbers. Add phases by hand, or assign sheets to one.",
  confirmProposal: "Set up these phases",
  resetToComputed: "Reset to computed",
  toFinishBy: (n, stage, date) => `To finish by ${date}: ${n} on ${stage.toLowerCase()}`,
  peakAverage: (peak, week, avg) => `Peak ${peak} on site in week ${week}; average ${avg}`,
  notYetQuoted: "Not yet quoted",
  notYetQuotedFix: "Ask the supplier for a lead time, or upload their price sheet with the lead-time column filled.",
  typeLeadTime: "Type a lead time",
  whoSaidSo: "Who quoted it",
  flagLongLead: "Flag as long-lead",
  unflagLongLead: "Not long-lead",
  neededFor: "Needed for",
  orderBy: "Order by",
  sourceTag: (source, label, date) =>
    source === "company" ? `Company: ${label}, ${date}` : `${label}, ${date}`,
  generalConditions: "General conditions",
  directHours: "Direct hours",
  movedIn: (n) => `${n} item${n === 1 ? "" : "s"} moved in`,
  movedOut: (n) => `${n} item${n === 1 ? "" : "s"} moved out`,
  phaseField: "Phase",
  phaseInherited: "From its sheet",
  phaseMoved: (from) => `moved from ${from}`,
};
```

- [ ] **Step 4: The mapping and the store functions**

Append to `api-mapping.js`:

```js
const num = (v) => (v == null ? null : Number(v));

function mapBar(b) {
  return {
    stage: b.stage, label: b.label, hours: num(b.hours), crew: { ...b.crew },
    productiveHoursPerDay: num(b.productive_hours_per_day), durationDays: b.duration_days,
    start: b.start ?? null, end: b.end ?? null, startWeek: b.start_week, endWeek: b.end_week,
    sources: { ...(b.sources || {}) }, neededCrew: b.needed_crew ?? null, overMax: Boolean(b.over_max), overMaxNote: b.over_max_note ?? "",
  };
}

function mapPhase(p) {
  return {
    id: p.id, name: p.name, sortOrder: p.sort_order, startDate: p.start_date ?? null, requiredFinishDate: p.required_finish_date ?? null,
    notes: p.notes ?? "", sheetIds: p.sheet_ids ?? [], itemsMovedIn: p.items_moved_in ?? 0, itemsMovedOut: p.items_moved_out ?? 0,
    directHours: num(p.direct_hours), generalConditionsHours: num(p.general_conditions_hours), materialTotal: num(p.material_total),
    lines: (p.lines || []).map((l) => ({ id: l.id, label: l.label, hours: num(l.hours), source: l.source, percentOfDirectHours: num(l.percent_of_direct_hours) })),
    bars: (p.bars || []).map(mapBar), start: p.start ?? null, end: p.end ?? null,
  };
}

function mapLead(l) {
  return {
    itemId: l.item_id, itemName: l.item_name, itemStatus: l.item_status, phaseId: l.phase_id, phaseName: l.phase_name,
    leadWeeks: l.lead_weeks ?? null, source: l.source ?? null, sourceLabel: l.source_label ?? "", quotedAt: l.quoted_at ?? null,
    neededForStage: l.needed_for_stage, neededBy: l.needed_by ?? null, orderBy: l.order_by ?? null, orderByWeek: l.order_by_week ?? null,
    passed: Boolean(l.passed), stale: Boolean(l.stale), note: l.note ?? "", warning: l.warning ?? null,
  };
}

/** Wire ScheduleOut -> store shape. Decimal strings become numbers; dates stay ISO strings. */
export function mapSchedule(s) {
  return {
    multiPhase: Boolean(s.multi_phase), relative: Boolean(s.relative),
    phases: (s.phases || []).map(mapPhase),
    manpower: (s.manpower || []).map((w) => ({ week: w.week, start: w.start ?? null, foreman: w.foreman, journeyman: w.journeyman, apprentice: w.apprentice, crew: w.foreman + w.journeyman + w.apprentice })),
    peakCrew: s.peak_crew ?? 0, averageCrew: num(s.average_crew) ?? 0,
    leads: (s.leads || []).map(mapLead),
    unscheduledCount: s.unscheduled_count ?? 0, unscheduledNote: s.unscheduled_note ?? "",
    defaultSplitCount: s.default_split_count ?? 0, defaultsInUse: { splits: Boolean(s.defaults_in_use?.splits), crews: Boolean(s.defaults_in_use?.crews) },
    expectedAwardDate: s.expected_award_date ?? null, mobilizationDate: s.mobilization_date ?? null,
  };
}

export function mapStageSplit(r) {
  return { categoryKey: r.category_key, categoryLabel: r.category_label, demolition: num(r.demolition), roughIn: num(r.rough_in), wirePull: num(r.wire_pull), gear: num(r.gear), trim: num(r.trim), closeout: num(r.closeout), firmEdited: Boolean(r.firm_edited) };
}

export function mapStageCrew(r) {
  return { stage: r.stage, label: r.label, foreman: r.foreman, journeyman: r.journeyman, apprentice: r.apprentice, productiveHoursPerDay: num(r.productive_hours_per_day), productivityFactor: num(r.productivity_factor), maxCrew: r.max_crew, firmEdited: Boolean(r.firm_edited) };
}

export function mapCompanyLeadTime(r) {
  return { itemClass: r.item_class, leadWeeks: r.lead_weeks, sourceLabel: r.source_label, quotedAt: r.quoted_at };
}
```

Append to `api.js`, inside the store factory next to `getLaborRows` (the wire is camelCase for bodies, as `setLaborLine` sends `hoursOverride`; check `request()`'s body handling and the API's alias config from Task 7 and match it):

```js
  async function getSchedule(projectId) {
    return mapSchedule(await request(`/api/projects/${projectId}/schedule`));
  }
  async function createPhase(projectId, { name = "", afterPhaseId = null } = {}) {
    return mapSchedule(await request(`/api/projects/${projectId}/phases`, { method: "POST", body: { name, afterPhaseId } }));
  }
  async function editPhase(phaseId, changes) {
    return mapSchedule(await request(`/api/phases/${phaseId}`, { method: "PATCH", body: changes }));
  }
  async function deletePhase(phaseId) {
    return mapSchedule(await request(`/api/phases/${phaseId}`, { method: "DELETE" }));
  }
  async function setPhaseSheets(phaseId, sheetIds) {
    return mapSchedule(await request(`/api/phases/${phaseId}/sheets`, { method: "PUT", body: { sheetIds } }));
  }
  async function setItemPhase(itemId, phaseId) {
    return mapItem(await request(`/api/items/${itemId}/phase`, { method: "PATCH", body: { phaseId } }));
  }
  async function setPhaseLine(phaseId, lineId, hours) {
    return mapSchedule(await request(`/api/phases/${phaseId}/lines/${lineId}`, { method: "PATCH", body: { hours } }));
  }
  async function setStagePlan(phaseId, stage, changes) {
    return mapSchedule(await request(`/api/phases/${phaseId}/stages/${stage}`, { method: "PUT", body: changes }));
  }
  async function setLeadTime(itemId, changes) {
    return mapSchedule(await request(`/api/items/${itemId}/lead-time`, { method: "PATCH", body: changes }));
  }
  async function proposePhases(projectId, phases = null) {
    return request(`/api/projects/${projectId}/phases/propose`, { method: "POST", body: { phases } });
  }
  async function applyProposedPhases(projectId, proposal) {
    return mapSchedule(await request(`/api/projects/${projectId}/phases/propose/apply`, { method: "POST", body: proposal }));
  }
  async function getStageSplits() { return (await request("/api/company/stage-splits")).map(mapStageSplit); }
  async function setStageSplit(categoryKey, values) { return mapStageSplit(await request(`/api/company/stage-splits/${encodeURIComponent(categoryKey)}`, { method: "PUT", body: values })); }
  async function deleteStageSplit(categoryKey) { return request(`/api/company/stage-splits/${encodeURIComponent(categoryKey)}`, { method: "DELETE" }); }
  async function getStageCrews() { return (await request("/api/company/stage-crews")).map(mapStageCrew); }
  async function setStageCrew(stage, values) { return mapStageCrew(await request(`/api/company/stage-crews/${stage}`, { method: "PUT", body: values })); }
  async function getScheduleSettings() { return request("/api/company/schedule-settings"); }
  async function setScheduleSettings(values) { return request("/api/company/schedule-settings", { method: "PUT", body: values }); }
  async function getPhaseLineTemplates() { return request("/api/company/phase-line-templates"); }
  async function setPhaseLineTemplate(id, values) { return request(`/api/company/phase-line-templates/${id ?? "new"}`, { method: "PUT", body: values }); }
  async function deletePhaseLineTemplate(id) { return request(`/api/company/phase-line-templates/${id}`, { method: "DELETE" }); }
  async function getCompanyLeadTimes() { return (await request("/api/company/lead-times")).map(mapCompanyLeadTime); }
  async function setCompanyLeadTime(itemClass, values) { return mapCompanyLeadTime(await request(`/api/company/lead-times/${itemClass}`, { method: "PUT", body: values })); }
  async function deleteCompanyLeadTime(itemClass) { return request(`/api/company/lead-times/${itemClass}`, { method: "DELETE" }); }
```

and add every name to the returned object. `mapItem` (the existing item mapper) gains `phaseId: r.phase_id ?? null, phaseOverridden: Boolean(r.phase_overridden)`; the project mapper gains `expectedAwardDate`, `mobilizationDate`.

- [ ] **Step 5: Run the tests**

Run: `npx vitest run src/components/schedule src/lib/store`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/components/schedule/stages.js src/components/schedule/stages.test.js src/components/schedule/scheduleCopy.js src/lib/store/api.js src/lib/store/api-mapping.js src/lib/store/api-mapping.schedule.test.js
git commit -m "Schedule: the client's stage vocabulary, its copy, and the store surface for every schedule route

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: The workspace, the phase list, the route and the nav entry

**Files:**
- Create: `src/components/schedule/ScheduleWorkspace.jsx`, `src/components/schedule/PhaseList.jsx`, `src/components/schedule/useSchedule.js`
- Modify: `src/routes.jsx` (append `<Route path="schedule" element={<ScheduleWorkspace />} />` after `pricing`), `src/components/shell/ProjectNav.jsx` (append `{ slug: "schedule", label: "Phases and schedule", built: true, Icon: CalendarRange }` to the Cost group after `labor`), `src/styles.css` (append `/* ==== schedule ==== */`)
- Test: `src/components/schedule/ScheduleWorkspace.test.jsx`, `src/components/shell/nav.test.jsx` (append: the entry is built and in the Cost group)

**Interfaces:**
- `useSchedule()` — the screen's one data hook: `{ schedule, loadError, reload, mutate(fn, label) }` where `mutate` runs `fn()` through `runMutation`, replaces `schedule` with the `ScheduleOut` the call returns, and shows `label` as the toast (with Undo through the shared stack, which then `reload()`s — the same shape as `LaborWorkspace`).
- `PhaseList` props: `{ schedule, sheets, onAddPhase(name, afterPhaseId), onRename(phaseId, name), onDates(phaseId, {startDate, requiredFinishDate}), onReorder(phaseId, sortOrder), onDelete(phaseId), onAssignSheets(phaseId, sheetIds), onLineHours(phaseId, lineId, hours|null), onPropose() }`.

- [ ] **Step 1: Write the failing tests**

```jsx
// src/components/schedule/ScheduleWorkspace.test.jsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ScheduleWorkspace from "./ScheduleWorkspace.jsx";

vi.mock("../project/useWorkspaceContext.js", () => ({ useWorkspaceContext: () => ctx }));

const onePhase = {
  multiPhase: false, relative: true, phases: [{ id: "p1", name: "Phase 1", sortOrder: 0, startDate: null, requiredFinishDate: null, notes: "",
    sheetIds: ["s1"], itemsMovedIn: 0, itemsMovedOut: 0, directHours: 0, generalConditionsHours: 0, lines: [], bars: [], start: null, end: null, materialTotal: 0 }],
  manpower: [], peakCrew: 0, averageCrew: 0, leads: [], unscheduledCount: 0, unscheduledNote: "", defaultSplitCount: 0,
  defaultsInUse: { splits: true, crews: true }, expectedAwardDate: null, mobilizationDate: null,
};
let ctx;

function setup(schedule = onePhase) {
  const store = { getSchedule: vi.fn().mockResolvedValue(schedule), createPhase: vi.fn().mockResolvedValue({ ...schedule, multiPhase: true }) };
  ctx = {
    store, projectId: "proj", snapshot: { sheets: [{ id: "s1", number: "E-1.0", title: "Power plan" }], items: [] },
    saved: { state: "saved", at: 0 }, toast: null, dismissToast: vi.fn(), undo: vi.fn(),
    runMutation: (fn) => fn(), showToast: vi.fn(),
  };
  return store;
}

describe("ScheduleWorkspace", () => {
  it("shows the empty state with a link to Labor when nothing is scheduled", async () => {
    setup();
    render(<ScheduleWorkspace />);
    expect(await screen.findByText(/Nothing to schedule yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Labor/ })).toHaveAttribute("href", expect.stringContaining("/labor"));
  });

  it("hides the phase column affordances with one phase and adds a phase on request", async () => {
    const store = setup();
    render(<ScheduleWorkspace />);
    await screen.findByText("Phase 1");
    expect(screen.queryByText(/moved in/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add phase" }));
    await userEvent.type(screen.getByLabelText("Phase name"), "Phase 2{enter}");
    await waitFor(() => expect(store.createPhase).toHaveBeenCalledWith("proj", { name: "Phase 2", afterPhaseId: "p1" }));
    expect(ctx.showToast).toHaveBeenCalledWith("Added Phase 2");
  });

  it("says weeks are relative when nothing is dated", async () => {
    setup({ ...onePhase, phases: [{ ...onePhase.phases[0], bars: [{ stage: "rough_in", label: "Rough-in", hours: 36, crew: { foreman: 1, journeyman: 2, apprentice: 2 },
      productiveHoursPerDay: 6, durationDays: 2, start: null, end: null, startWeek: 1, endWeek: 1, sources: {}, neededCrew: null, overMax: false, overMaxNote: "" }] }] });
    render(<ScheduleWorkspace />);
    expect(await screen.findByText(/Weeks are relative/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/components/schedule/ScheduleWorkspace.test.jsx`
Expected: FAIL — cannot resolve `./ScheduleWorkspace.jsx`

- [ ] **Step 3: Write `useSchedule.js`**

```js
// src/components/schedule/useSchedule.js
/* The schedule screen's one data hook. The schedule is not part of the
   polled review snapshot (a phase edit never changes the takeoff), so
   the screen fetches it itself and, after a write, keeps the ScheduleOut
   the call returned -- every schedule mutation answers with the whole
   thing, because a crew change moves every later bar. Undo goes through
   the shared stack and reloads. */
import { useCallback, useEffect, useState } from "react";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";

export function useSchedule() {
  const { store, projectId, runMutation, showToast } = useWorkspaceContext();
  const [schedule, setSchedule] = useState(null);
  const [loadError, setLoadError] = useState(null);

  const reload = useCallback(() => {
    setLoadError(null);
    return store
      .getSchedule(projectId)
      .then(setSchedule)
      .catch((err) => setLoadError(err?.message || "Couldn't load the schedule. Check your connection and try again."));
  }, [store, projectId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const mutate = useCallback(
    async (fn, label) => {
      try {
        const next = await runMutation(fn);
        if (next && next.phases) setSchedule(next);
        if (label) showToast(label);
        return next;
      } catch (err) {
        setLoadError(err?.message || "This change could not be saved.");
        return null;
      }
    },
    [runMutation, showToast],
  );

  return { schedule, loadError, reload, mutate };
}
```

- [ ] **Step 4: Write `ScheduleWorkspace.jsx`**

```jsx
// src/components/schedule/ScheduleWorkspace.jsx
/* ============================================================
   ScheduleWorkspace.jsx — Phases and schedule (docs/specs/phases-and-
   timeline.md §6). Renders what GET /schedule returns and derives no
   number of its own: a duration, a date, a crew, an order-by all come
   from the API. The screen's job is to show them, say which are
   computed and which are the estimator's, and route every change
   through the store.
   ============================================================ */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import { saveStateText } from "../../lib/format.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";
import { useSchedule } from "./useSchedule.js";
import PhaseList from "./PhaseList.jsx";
import StageBars from "./StageBars.jsx";
import StageEditor from "./StageEditor.jsx";
import ManpowerChart from "./ManpowerChart.jsx";
import LongLeadList from "./LongLeadList.jsx";
import { COPY } from "./scheduleCopy.js";

export default function ScheduleWorkspace() {
  const { store, projectId, snapshot, saved, toast, dismissToast, undo } = useWorkspaceContext();
  const { schedule, loadError, reload, mutate } = useSchedule();
  const [selectedBar, setSelectedBar] = useState(null); // { phaseId, stage }

  const sheets = snapshot?.sheets ?? [];
  const hasBars = useMemo(() => Boolean(schedule?.phases.some((p) => p.bars.length > 0)), [schedule]);

  const actions = {
    onAddPhase: (name, afterPhaseId) => mutate(() => store.createPhase(projectId, { name, afterPhaseId }), `Added ${name || "a phase"}`),
    onRename: (phaseId, name) => mutate(() => store.editPhase(phaseId, { name }), `Renamed to ${name}`),
    onDates: (phaseId, dates) => mutate(() => store.editPhase(phaseId, dates), "Changed phase dates"),
    onReorder: (phaseId, sortOrder) => mutate(() => store.editPhase(phaseId, { sortOrder }), "Moved phase"),
    onDelete: (phaseId) => mutate(() => store.deletePhase(phaseId), "Removed phase"),
    onAssignSheets: (phaseId, sheetIds) => mutate(() => store.setPhaseSheets(phaseId, sheetIds), "Moved sheets"),
    onLineHours: (phaseId, lineId, hours) => mutate(() => store.setPhaseLine(phaseId, lineId, hours), hours == null ? "Reset to computed" : `Set to ${hours} hours`),
    onStagePlan: (phaseId, stage, changes) => mutate(() => store.setStagePlan(phaseId, stage, changes), "Changed stage"),
    onLeadTime: (itemId, changes) => mutate(() => store.setLeadTime(itemId, changes), changes.leadWeeks === null ? "Cleared lead time" : "Changed lead time"),
    onPropose: async () => {
      const proposal = await store.proposePhases(projectId, null);
      if (!proposal.phases.length) return proposal;
      return proposal;
    },
    onApplyProposal: (proposal) => mutate(() => store.applyProposedPhases(projectId, proposal), `Set up ${proposal.phases.length} phases`),
  };

  const selected = selectedBar && schedule
    ? schedule.phases.find((p) => p.id === selectedBar.phaseId)?.bars.find((b) => b.stage === selectedBar.stage)
    : null;

  return (
    <div className="workspace workspace--schedule">
      <AppTopBar title={COPY.title} saveState={saveStateText(saved)} toast={toast} onDismissToast={dismissToast} onUndo={undo} />
      <p className="muted">{COPY.intro}</p>
      {loadError ? <p role="alert" className="error-line">{loadError}</p> : null}
      {schedule ? (
        <>
          <PhaseList schedule={schedule} sheets={sheets} {...actions} />
          {schedule.unscheduledCount > 0 ? (
            <p className="schedule-note tabular">{schedule.unscheduledNote} — <Link to={`/projects/${projectId}/labor`}>Labor</Link></p>
          ) : null}
          {hasBars ? (
            <>
              {schedule.relative ? <p className="muted">{COPY.relativeAxis}</p> : null}
              {schedule.defaultsInUse.splits ? <p className="muted">{COPY.defaultSplit}</p> : null}
              <div className="schedule-body">
                <StageBars schedule={schedule} selected={selectedBar} onSelect={setSelectedBar} />
                {selected ? (
                  <StageEditor phase={schedule.phases.find((p) => p.id === selectedBar.phaseId)} bar={selected}
                               onChange={(changes) => actions.onStagePlan(selectedBar.phaseId, selectedBar.stage, changes)}
                               onClose={() => setSelectedBar(null)} />
                ) : null}
              </div>
              <ManpowerChart schedule={schedule} />
            </>
          ) : (
            <p className="empty-state">{COPY.nothingToSchedule} <Link to={`/projects/${projectId}/labor`}>Labor</Link></p>
          )}
          <LongLeadList schedule={schedule} items={snapshot?.items ?? []} onLeadTime={actions.onLeadTime} />
        </>
      ) : null}
    </div>
  );
}
```

Check `AppTopBar`'s real props in `src/components/shell/AppTopBar.jsx` and pass what `LaborWorkspace` passes; the names above follow its usage. `StageBars`, `StageEditor`, `ManpowerChart`, `LongLeadList` are Tasks 11–12; for this task's tests to pass, create each as a file exporting a component that returns `null` and fill them in their own tasks.

- [ ] **Step 5: Write `PhaseList.jsx`**

```jsx
// src/components/schedule/PhaseList.jsx
/* One row per phase: name, the sheets it owns, its dates, its hours, and
   its general-conditions lines. Add / rename / reorder / delete, and
   sheet assignment. Nothing about phases shows on this screen or any
   other until a second phase exists -- a single-phase bid sees one
   plain row and the Add button. */
import { useState } from "react";
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { COPY } from "./scheduleCopy.js";

function PhaseRow({ phase, phases, sheets, multi, onRename, onDates, onReorder, onDelete, onAssignSheets, onLineHours }) {
  const [editingName, setEditingName] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [picked, setPicked] = useState(new Set(phase.sheetIds));
  const idx = phases.findIndex((p) => p.id === phase.id);
  const neighbour = idx > 0 ? phases[idx - 1] : phases[1];
  const ownedSheets = sheets.filter((s) => phase.sheetIds.includes(s.id));

  return (
    <li className="phase-row">
      <div className="phase-row__head">
        {editingName ? (
          <input aria-label="Phase name" defaultValue={phase.name} autoFocus
                 onBlur={(e) => { setEditingName(false); if (e.target.value.trim() && e.target.value !== phase.name) onRename(phase.id, e.target.value.trim()); }}
                 onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setEditingName(false); }} />
        ) : (
          <button type="button" className="phase-row__name" onClick={() => setEditingName(true)}>{phase.name}</button>
        )}
        {multi ? (
          <span className="phase-row__controls">
            <button type="button" aria-label={`Move ${phase.name} up`} disabled={idx === 0} onClick={() => onReorder(phase.id, idx - 1)}><ArrowUp size={16} /></button>
            <button type="button" aria-label={`Move ${phase.name} down`} disabled={idx === phases.length - 1} onClick={() => onReorder(phase.id, idx + 1)}><ArrowDown size={16} /></button>
            <button type="button" aria-label={`${COPY.deletePhase} ${phase.name}`}
                    onClick={() => { if (window.confirm(COPY.deletePhaseConfirm(phase.name, neighbour?.name ?? ""))) onDelete(phase.id); }}><Trash2 size={16} /></button>
          </span>
        ) : null}
      </div>
      <div className="phase-row__sheets">
        {ownedSheets.map((s) => <span key={s.id} className="pill pill--neutral">{s.number}</span>)}
        {multi ? <button type="button" className="link" onClick={() => setAssigning((v) => !v)}>{COPY.assignSheets}</button> : null}
        {multi && phase.itemsMovedIn ? <span className="muted tabular">{COPY.movedIn(phase.itemsMovedIn)}</span> : null}
        {multi && phase.itemsMovedOut ? <span className="muted tabular">{COPY.movedOut(phase.itemsMovedOut)}</span> : null}
      </div>
      {assigning ? (
        <fieldset className="phase-row__assign">
          <legend>Sheets in {phase.name}</legend>
          {sheets.map((s) => (
            <label key={s.id}>
              <input type="checkbox" checked={picked.has(s.id)}
                     onChange={(e) => { const next = new Set(picked); e.target.checked ? next.add(s.id) : next.delete(s.id); setPicked(next); }} />
              {s.number} {s.title}
            </label>
          ))}
          <button type="button" className="btn btn--primary" onClick={() => { onAssignSheets(phase.id, [...picked]); setAssigning(false); }}>Move sheets</button>
        </fieldset>
      ) : null}
      <div className="phase-row__dates">
        <label>Start <input type="date" value={phase.startDate ?? ""} onChange={(e) => onDates(phase.id, { startDate: e.target.value || null })} /></label>
        <label>Required finish <input type="date" value={phase.requiredFinishDate ?? ""} onChange={(e) => onDates(phase.id, { requiredFinishDate: e.target.value || null })} /></label>
        <span className="tabular">{COPY.directHours}: {phase.directHours.toFixed(2)}</span>
      </div>
      <details className="phase-row__lines">
        <summary className="tabular">{COPY.generalConditions}: {phase.generalConditionsHours.toFixed(2)} h</summary>
        {phase.lines.map((line) => (
          <div key={line.id} className="phase-line">
            <span>{line.label}</span>
            <input type="text" inputMode="decimal" aria-label={`${line.label} hours`} defaultValue={line.hours.toFixed(2)}
                   onBlur={(e) => { const v = e.target.value.trim(); if (v === "") onLineHours(phase.id, line.id, null); else if (Number(v) !== line.hours) onLineHours(phase.id, line.id, Number(v)); }} />
            <span className={`pill pill--neutral`}>{line.source === "estimator" ? COPY.yours : COPY.computed}</span>
            {line.source === "estimator" ? <button type="button" className="link" onClick={() => onLineHours(phase.id, line.id, null)}>{COPY.resetToComputed}</button> : null}
          </div>
        ))}
      </details>
    </li>
  );
}

export default function PhaseList({ schedule, sheets, onAddPhase, onPropose, onApplyProposal, ...rowActions }) {
  const [adding, setAdding] = useState(false);
  const [proposal, setProposal] = useState(null);
  const phases = schedule.phases;
  const multi = schedule.multiPhase;

  return (
    <section className="phase-list" aria-label="Phases">
      <ul>
        {phases.map((p) => <PhaseRow key={p.id} phase={p} phases={phases} sheets={sheets} multi={multi} {...rowActions} />)}
      </ul>
      <div className="phase-list__actions">
        {adding ? (
          <input aria-label="Phase name" autoFocus placeholder={`Phase ${phases.length + 1}`}
                 onKeyDown={(e) => { if (e.key === "Enter") { onAddPhase(e.target.value.trim(), phases[phases.length - 1].id); setAdding(false); } if (e.key === "Escape") setAdding(false); }} />
        ) : (
          <button type="button" className="btn" onClick={() => setAdding(true)}>{COPY.addPhase}</button>
        )}
        {!multi ? <button type="button" className="btn" onClick={async () => setProposal(await onPropose())}>{COPY.proposeFromSheets}</button> : null}
      </div>
      {proposal ? (
        <div className="proposal-card" role="dialog" aria-label="Proposed phases">
          <p>{proposal.note}</p>
          <ul>{proposal.phases.map((p) => <li key={p.name}><strong>{p.name}</strong> — {p.sheet_numbers.join(", ")}</li>)}</ul>
          {proposal.phases.length ? <button type="button" className="btn btn--primary" onClick={() => { onApplyProposal(proposal); setProposal(null); }}>{COPY.confirmProposal}</button> : null}
          <button type="button" className="btn" onClick={() => setProposal(null)}>Dismiss</button>
        </div>
      ) : null}
    </section>
  );
}
```

The `window.confirm` for delete uses the repo's `Modal.jsx` if a confirm pattern already exists there (check `MiscModals.jsx`); if so use it — the copy stays `COPY.deletePhaseConfirm`.

- [ ] **Step 6: Route, nav, styles**

`src/routes.jsx`: import `ScheduleWorkspace` and append `<Route path="schedule" element={<ScheduleWorkspace />} />`. `ProjectNav.jsx`: import `CalendarRange` from `lucide-react` and append the entry to the Cost group after `labor`. `src/styles.css`, appended at the end:

```css
/* ==== schedule ==== */
.workspace--schedule { padding: 16px 24px; display: flex; flex-direction: column; gap: 16px; }
.phase-list ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.phase-row { border: 1px solid var(--line-1); border-radius: var(--r-sm); background: var(--surface); padding: 12px; display: grid; gap: 8px; }
.phase-row__head { display: flex; align-items: center; justify-content: space-between; }
.phase-row__name { font-weight: 600; font-size: 1rem; background: none; border: 0; padding: 4px 0; cursor: text; color: var(--ink-1); }
.phase-row__controls button { background: none; border: 1px solid var(--line-2); border-radius: var(--r-sm); padding: 4px; margin-left: 4px; color: var(--ink-2); }
.phase-row__sheets, .phase-row__dates { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.phase-row__assign { display: grid; gap: 4px; border: 1px solid var(--line-2); border-radius: var(--r-sm); padding: 8px; }
.phase-line { display: grid; grid-template-columns: 1fr 96px auto auto; gap: 8px; align-items: center; padding: 4px 0; }
.phase-line input { width: 96px; text-align: right; }
.schedule-note { color: var(--ink-2); }
.schedule-body { display: grid; grid-template-columns: 1fr 320px; gap: 16px; align-items: start; }
.proposal-card { border: 1px solid var(--blue-line); background: var(--blue-tint); border-radius: var(--r-sm); padding: 12px; display: grid; gap: 8px; }
```

- [ ] **Step 7: Run the tests and the build**

Run: `npx vitest run src/components/schedule src/components/shell && npm run build`
Expected: PASS; build succeeds.

- [ ] **Step 8: Commit**

```bash
git add src/components/schedule/ScheduleWorkspace.jsx src/components/schedule/ScheduleWorkspace.test.jsx src/components/schedule/PhaseList.jsx src/components/schedule/useSchedule.js src/components/schedule/StageBars.jsx src/components/schedule/StageEditor.jsx src/components/schedule/ManpowerChart.jsx src/components/schedule/LongLeadList.jsx src/routes.jsx src/components/shell/ProjectNav.jsx src/components/shell/nav.test.jsx src/styles.css
git commit -m "Schedule: the Phases and schedule workspace, its phase list, and its place in the project nav

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Stage bars, the bar editor, and the manpower chart

**Files:**
- Modify: `src/components/schedule/StageBars.jsx`, `StageEditor.jsx`, `ManpowerChart.jsx` (replace the stubs), `src/styles.css` (append)
- Test: `src/components/schedule/StageBars.test.jsx`, `src/components/schedule/StageEditor.test.jsx`, `src/components/schedule/ManpowerChart.test.jsx`

**Interfaces:**
- `StageBars({ schedule, selected, onSelect })` — a week grid from week 1 to the schedule's last week (`max(endWeek)` over every bar, and `orderByWeek` over leads); one row per phase; a `<button>` per bar labeled `"<stage> — <hours> h, <crewText>, <days> days"`; order-by markers as `<span role="img" aria-label="Order by <date>: <item>">` above the phase row, with the attention icon when `stale` and the `note` inline when `passed`.
- `StageEditor({ phase, bar, onChange, onClose })` — fields: foreman, journeyman, apprentice (integers), productive hours/day (decimal), hours (decimal), start (date), duration (days); each shows `Computed` or `Yours` from `bar.sources` and a per-field "Reset to computed" that calls `onChange({ [field]: null })`. The reverse solve: when `bar.neededCrew != null` show `COPY.toFinishBy(neededCrew, label, phase.requiredFinishDate)` and, if `!bar.overMax`, an "Apply" button that calls `onChange({ journeyman: neededCrew - foreman - apprentice })` (never more than the max); if `overMax`, show `bar.overMaxNote` and no button.
- `ManpowerChart({ schedule })` — an inline SVG bar per week, stacked by role, `role="img"` with an `aria-label` that reads the peak and average; beside it the text `COPY.peakAverage(peak, peakWeek, average)`. Colours: three tints of `--blue` via CSS classes, never inline hex; a text table (`<table class="sr-only">`) mirrors the numbers for screen readers.

- [ ] **Step 1: Write the failing tests**

```jsx
// src/components/schedule/StageBars.test.jsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import StageBars from "./StageBars.jsx";

const bar = (stage, extra = {}) => ({ stage, label: stage, hours: 36, crew: { foreman: 1, journeyman: 2, apprentice: 2 }, productiveHoursPerDay: 6,
  durationDays: 2, start: null, end: null, startWeek: 1, endWeek: 1, sources: {}, neededCrew: null, overMax: false, overMaxNote: "", ...extra });
const schedule = {
  relative: true, multiPhase: true,
  phases: [{ id: "p1", name: "Phase 1", bars: [bar("rough_in", { label: "Rough-in" }), bar("trim", { label: "Trim", startWeek: 2, endWeek: 3, sources: { journeyman: "estimator" } })] }],
  leads: [{ itemId: "i1", itemName: "Switchboard MSB-1", phaseId: "p1", orderBy: "2026-05-25", orderByWeek: -20, passed: true, stale: true, note: "Order date has passed — 40 weeks lead, gear starts Feb 24" }],
};

describe("StageBars", () => {
  it("draws a button per bar with hours, crew, and days, and marks overrides", async () => {
    const onSelect = vi.fn();
    render(<StageBars schedule={schedule} selected={null} onSelect={onSelect} />);
    const rough = screen.getByRole("button", { name: /Rough-in — 36 h, 1F 2J 2A, 2 days/ });
    await userEvent.click(rough);
    expect(onSelect).toHaveBeenCalledWith({ phaseId: "p1", stage: "rough_in" });
    expect(screen.getByRole("button", { name: /Trim/ })).toHaveTextContent("Yours");
  });

  it("shows the order-by marker with its note when the date has passed", () => {
    render(<StageBars schedule={schedule} selected={null} onSelect={() => {}} />);
    expect(screen.getByRole("img", { name: /Order by .*Switchboard MSB-1/ })).toBeInTheDocument();
    expect(screen.getByText(/Order date has passed/)).toBeInTheDocument();
  });
});
```

```jsx
// src/components/schedule/StageEditor.test.jsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import StageEditor from "./StageEditor.jsx";

const bar = { stage: "rough_in", label: "Rough-in", hours: 36, crew: { foreman: 1, journeyman: 2, apprentice: 2 }, productiveHoursPerDay: 6, durationDays: 2,
  start: "2026-10-05", end: "2026-10-06", startWeek: 1, endWeek: 1, sources: { journeyman: "estimator", hours: "computed" }, neededCrew: 5, overMax: false, overMaxNote: "" };
const phase = { id: "p1", name: "Phase 1", requiredFinishDate: "2026-10-09" };

describe("StageEditor", () => {
  it("shows each field with its source and resets one field to computed", async () => {
    const onChange = vi.fn();
    render(<StageEditor phase={phase} bar={bar} onChange={onChange} onClose={() => {}} />);
    expect(screen.getByLabelText("Journeyman")).toHaveValue(2);
    await userEvent.click(screen.getByRole("button", { name: "Reset journeyman to computed" }));
    expect(onChange).toHaveBeenCalledWith({ journeyman: null });
  });

  it("offers the crew that meets the window and applies it as journeymen", async () => {
    const onChange = vi.fn();
    render(<StageEditor phase={phase} bar={bar} onChange={onChange} onClose={() => {}} />);
    expect(screen.getByText(/To finish by/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Apply 5/ }));
    expect(onChange).toHaveBeenCalledWith({ journeyman: 2 });   // 5 - 1 foreman - 2 apprentices
  });

  it("says the window is too tight and offers nothing when over the max", () => {
    render(<StageEditor phase={phase} bar={{ ...bar, neededCrew: 9, overMax: true, overMaxNote: "More than 6 on rough-in to finish by Oct 9 — the window is tighter than one crew can meet" }} onChange={() => {}} onClose={() => {}} />);
    expect(screen.getByText(/tighter than one crew/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply/ })).not.toBeInTheDocument();
  });
});
```

```jsx
// src/components/schedule/ManpowerChart.test.jsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ManpowerChart from "./ManpowerChart.jsx";

describe("ManpowerChart", () => {
  it("states peak and average in text and draws one column per week", () => {
    const schedule = { relative: false, peakCrew: 10, averageCrew: 7.5,
      manpower: [{ week: 1, start: "2026-10-05", foreman: 2, journeyman: 4, apprentice: 4, crew: 10 }, { week: 2, start: "2026-10-12", foreman: 1, journeyman: 2, apprentice: 2, crew: 5 }] };
    render(<ManpowerChart schedule={schedule} />);
    expect(screen.getByText("Peak 10 on site in week 1; average 7.5")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Manpower by week/ })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3);   // header + 2 weeks in the mirrored table
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/components/schedule/StageBars.test.jsx src/components/schedule/StageEditor.test.jsx src/components/schedule/ManpowerChart.test.jsx`
Expected: FAIL — the stubs render nothing

- [ ] **Step 3: Write `StageBars.jsx`**

```jsx
// src/components/schedule/StageBars.jsx
/* One row per phase, one bar per stage, on a week grid. Every number on
   a bar came from the API; this file positions and labels. Ring, not
   fill, for selection; "Yours" as a tier tag, never a status pill. */
import { AlertTriangle } from "lucide-react";
import { crewText } from "./stages.js";
import { COPY } from "./scheduleCopy.js";

function weekSpan(schedule) {
  const bars = schedule.phases.flatMap((p) => p.bars);
  const last = Math.max(1, ...bars.map((b) => b.endWeek), ...schedule.leads.map((l) => l.orderByWeek ?? 1));
  const first = Math.min(1, ...schedule.leads.map((l) => l.orderByWeek ?? 1));
  return { first, last };
}

function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function StageBars({ schedule, selected, onSelect }) {
  const { first, last } = weekSpan(schedule);
  const weeks = [];
  for (let w = first; w <= last; w += 1) weeks.push(w);
  const col = (w) => w - first + 2; // column 1 is the phase name

  return (
    <div className="stage-bars" role="group" aria-label="Stage bars by phase">
      <div className="stage-bars__grid" style={{ gridTemplateColumns: `160px repeat(${weeks.length}, minmax(48px, 1fr))` }}>
        <div className="stage-bars__corner" />
        {weeks.map((w) => (
          <div key={w} className="stage-bars__week tabular" style={{ gridColumn: col(w) }}>
            {schedule.relative || w < 1 ? `Week ${w}` : shortDate(schedule.manpower.find((m) => m.week === w)?.start)}
          </div>
        ))}
        {schedule.phases.map((phase, rowIdx) => {
          const leads = schedule.leads.filter((l) => l.phaseId === phase.id && l.orderByWeek != null);
          const markerRow = rowIdx * 2 + 2;
          const barRow = markerRow + 1;
          return [
            ...leads.map((l) => (
              <span key={`m-${l.itemId}`} role="img" className={`order-marker${l.stale ? " order-marker--stale" : ""}${l.passed ? " order-marker--passed" : ""}`}
                    style={{ gridRow: markerRow, gridColumn: col(l.orderByWeek) }}
                    aria-label={`${COPY.orderBy} ${shortDate(l.orderBy)}: ${l.itemName}`} title={`${l.itemName} — ${COPY.orderBy} ${shortDate(l.orderBy)}`}>
                {l.stale ? <AlertTriangle size={12} /> : null}◆
              </span>
            )),
            ...leads.filter((l) => l.passed).map((l) => (
              <span key={`n-${l.itemId}`} className="order-marker__note" style={{ gridRow: markerRow, gridColumn: `${col(Math.max(l.orderByWeek, first))} / span 6` }}>{l.itemName}: {l.note}</span>
            )),
            <div key={`name-${phase.id}`} className="stage-bars__phase" style={{ gridRow: barRow, gridColumn: 1 }}>{phase.name}</div>,
            ...phase.bars.map((b) => {
              const yours = Object.values(b.sources).some((s) => s === "estimator");
              const isSelected = selected && selected.phaseId === phase.id && selected.stage === b.stage;
              return (
                <button key={b.stage} type="button" className={`stage-bar stage-bar--${b.stage}${isSelected ? " stage-bar--selected" : ""}`}
                        style={{ gridRow: barRow, gridColumn: `${col(b.startWeek)} / ${col(b.endWeek) + 1}` }}
                        aria-pressed={Boolean(isSelected)} onClick={() => onSelect({ phaseId: phase.id, stage: b.stage })}
                        aria-label={`${b.label} — ${b.hours} h, ${crewText(b.crew)}, ${b.durationDays} days`}>
                  <span className="stage-bar__label">{b.label}</span>
                  <span className="stage-bar__meta tabular">{b.hours} h · {crewText(b.crew)} · {b.durationDays} d</span>
                  {yours ? <span className="tier-tag">{COPY.yours}</span> : null}
                </button>
              );
            }),
            phase.bars.length === 0 ? <span key={`empty-${phase.id}`} className="muted" style={{ gridRow: barRow, gridColumn: `2 / span ${weeks.length}` }}>{COPY.nothingToSchedule}</span> : null,
          ];
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Write `StageEditor.jsx`**

```jsx
// src/components/schedule/StageEditor.jsx
/* One bar's fields, each with where it came from and a way back to
   computed. The reverse solve is shown, never applied on its own. */
import { X } from "lucide-react";
import { COPY } from "./scheduleCopy.js";

const FIELDS = [
  { key: "foreman", label: "Foreman", kind: "int", read: (b) => b.crew.foreman },
  { key: "journeyman", label: "Journeyman", kind: "int", read: (b) => b.crew.journeyman },
  { key: "apprentice", label: "Apprentice", kind: "int", read: (b) => b.crew.apprentice },
  { key: "productiveHoursPerDay", label: "Productive hours per day", kind: "decimal", read: (b) => b.productiveHoursPerDay, source: "productive_hours_per_day" },
  { key: "hoursOverride", label: "Hours", kind: "decimal", read: (b) => b.hours, source: "hours" },
  { key: "startDate", label: "Start", kind: "date", read: (b) => b.start ?? "", source: "start" },
  { key: "durationDays", label: "Duration (working days)", kind: "int", read: (b) => b.durationDays, source: "duration_days" },
];

function shortDate(iso) {
  return iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
}

export default function StageEditor({ phase, bar, onChange, onClose }) {
  const commit = (field, raw) => {
    if (raw === "" || raw == null) return onChange({ [field.key]: null });
    const value = field.kind === "date" ? raw : Number(raw);
    if (field.kind !== "date" && (!Number.isFinite(value) || value < 0)) return;
    if (field.kind === "int" && !Number.isInteger(value)) return;
    if (value !== field.read(bar)) onChange({ [field.key]: value });
  };
  const suggested = bar.neededCrew;
  const journeymenForSuggested = suggested != null ? Math.max(0, suggested - bar.crew.foreman - bar.crew.apprentice) : null;

  return (
    <aside className="stage-editor" aria-label={`${bar.label} on ${phase.name}`}>
      <header className="stage-editor__head">
        <h3>{bar.label} — {phase.name}</h3>
        <button type="button" aria-label="Close" onClick={onClose}><X size={16} /></button>
      </header>
      {FIELDS.map((f) => {
        const source = bar.sources[f.source ?? f.key] ?? "computed";
        const id = `stage-${bar.stage}-${f.key}`;
        return (
          <div key={f.key} className="stage-editor__field">
            <label htmlFor={id}>{f.label}</label>
            <input id={id} type={f.kind === "date" ? "date" : "text"} inputMode={f.kind === "int" ? "numeric" : "decimal"} className="tabular"
                   defaultValue={f.read(bar)} key={`${id}-${f.read(bar)}`}
                   onBlur={(e) => commit(f, e.target.value.trim())} onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); }} />
            <span className="tier-tag">{source === "estimator" ? COPY.yours : COPY.computed}</span>
            {source === "estimator" ? (
              <button type="button" className="link" aria-label={`Reset ${f.label.toLowerCase()} to computed`} onClick={() => onChange({ [f.key]: null })}>{COPY.resetToComputed}</button>
            ) : null}
          </div>
        );
      })}
      {suggested != null && phase.requiredFinishDate ? (
        <div className="stage-editor__solve">
          {bar.overMax ? (
            <p>{bar.overMaxNote}</p>
          ) : (
            <>
              <p>{COPY.toFinishBy(suggested, bar.label, shortDate(phase.requiredFinishDate))}</p>
              <button type="button" className="btn" onClick={() => onChange({ journeyman: journeymenForSuggested })}>Apply {suggested} as the crew</button>
            </>
          )}
        </div>
      ) : null}
    </aside>
  );
}
```

- [ ] **Step 5: Write `ManpowerChart.jsx`**

```jsx
// src/components/schedule/ManpowerChart.jsx
/* The GC's chart: people on site per week, stacked by role, summed from
   the same bars the grid draws. Inline SVG with class-based fills; a
   mirrored table carries the numbers for anyone reading by ear. */
import { COPY } from "./scheduleCopy.js";
import { ROLES } from "./stages.js";

const H = 120;
const W_COL = 28;

export default function ManpowerChart({ schedule }) {
  const weeks = schedule.manpower;
  if (!weeks.length) return null;
  const peak = Math.max(1, schedule.peakCrew);
  const peakWeek = weeks.find((w) => w.crew === schedule.peakCrew)?.week ?? weeks[0].week;
  const width = weeks.length * W_COL + 8;
  const label = COPY.peakAverage(schedule.peakCrew, peakWeek, schedule.averageCrew);

  return (
    <section className="manpower" aria-label="Manpower by week">
      <p className="tabular">{label}</p>
      <svg role="img" aria-label={`Manpower by week. ${label}`} viewBox={`0 0 ${width} ${H + 16}`} className="manpower__svg">
        {weeks.map((w, i) => {
          let y = H;
          return (
            <g key={w.week} transform={`translate(${i * W_COL + 4},0)`}>
              {ROLES.map((r) => {
                const h = (w[r.key] / peak) * H;
                y -= h;
                return <rect key={r.key} className={`manpower__bar manpower__bar--${r.key}`} x={2} y={y} width={W_COL - 4} height={h} />;
              })}
              <text x={W_COL / 2} y={H + 12} textAnchor="middle" className="manpower__week tabular">{w.week}</text>
            </g>
          );
        })}
      </svg>
      <table className="sr-only">
        <thead><tr><th>Week</th>{ROLES.map((r) => <th key={r.key}>{r.label}</th>)}<th>Total</th></tr></thead>
        <tbody>{weeks.map((w) => <tr key={w.week}><td>{w.week}</td>{ROLES.map((r) => <td key={r.key}>{w[r.key]}</td>)}<td>{w.crew}</td></tr>)}</tbody>
      </table>
    </section>
  );
}
```

Append to `src/styles.css`:

```css
.stage-bars__grid { display: grid; gap: 4px 2px; align-items: center; overflow-x: auto; }
.stage-bars__week { font-size: 0.75rem; color: var(--ink-3); text-align: center; padding: 4px 0; border-bottom: 1px solid var(--line-1); }
.stage-bars__phase { font-weight: 600; padding-right: 8px; }
.stage-bar { display: grid; gap: 2px; text-align: left; border: 1px solid var(--blue-line); background: var(--blue-tint); color: var(--ink-1); border-radius: var(--r-sm); padding: 4px 8px; min-height: 40px; cursor: pointer; }
.stage-bar--selected { outline: 2px solid var(--blue); outline-offset: 1px; }
.stage-bar__label { font-weight: 600; font-size: 0.85rem; }
.stage-bar__meta { font-size: 0.75rem; color: var(--ink-2); }
.tier-tag { display: inline-block; font-size: 0.7rem; color: var(--slate); background: var(--slate-tint); border: 1px solid var(--slate-line); border-radius: 999px; padding: 0 6px; }
.order-marker { color: var(--blue); font-size: 0.9rem; text-align: center; }
.order-marker--stale { color: var(--amber); }
.order-marker--passed { color: var(--red); }
.order-marker__note { font-size: 0.75rem; color: var(--red); padding-left: 18px; white-space: nowrap; }
.stage-editor { border: 1px solid var(--line-1); border-radius: var(--r-sm); background: var(--surface); padding: 12px; display: grid; gap: 8px; }
.stage-editor__head { display: flex; justify-content: space-between; align-items: center; }
.stage-editor__field { display: grid; grid-template-columns: 1fr 96px auto auto; gap: 8px; align-items: center; }
.stage-editor__field input { width: 96px; text-align: right; }
.stage-editor__solve { border-top: 1px solid var(--line-1); padding-top: 8px; }
.manpower__svg { width: 100%; max-width: 720px; height: auto; }
.manpower__bar--foreman { fill: var(--blue-600); }
.manpower__bar--journeyman { fill: var(--blue); }
.manpower__bar--apprentice { fill: var(--blue-line); }
.manpower__week { font-size: 9px; fill: var(--ink-3); }
```

(`.sr-only` exists in `styles.css` already; if not, add the standard clip rule under this banner.)

- [ ] **Step 6: Run the tests and the build**

Run: `npx vitest run src/components/schedule && npm run build`
Expected: PASS; build succeeds.

- [ ] **Step 7: Commit**

```bash
git add src/components/schedule/StageBars.jsx src/components/schedule/StageBars.test.jsx src/components/schedule/StageEditor.jsx src/components/schedule/StageEditor.test.jsx src/components/schedule/ManpowerChart.jsx src/components/schedule/ManpowerChart.test.jsx src/styles.css
git commit -m "Schedule: stage bars on a week grid, the bar editor with a way back to computed, and the manpower chart

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: The long-lead list, the item panel, and the spreadsheet

**Files:**
- Modify: `src/components/schedule/LongLeadList.jsx` (replace the stub), `src/components/ItemDetailPanel.jsx` (a Phase field when the project has more than one phase; a Long-lead block), `src/components/takeoff/spreadsheetColumns.js` and `TakeoffSpreadsheet.jsx` (a Phase column and group-by-phase when more than one phase), `src/lib/useReviewStore.js` (expose `setItemPhase` through `runItemMutation` so the item patch lands like an edit)
- Test: `src/components/schedule/LongLeadList.test.jsx`, `src/components/ItemDetailPanel.phase.test.jsx`, `src/components/takeoff/spreadsheetColumns.test.js` (append)

**Interfaces:**
- `LongLeadList({ schedule, items, onLeadTime })` — one row per `schedule.leads` entry: name, phase (when multi-phase), the item's status through the existing `Pill`, lead weeks with its source tag (`COPY.sourceTag`) or `COPY.notYetQuoted`, needed-for stage (a `<select>` over `STAGES`), order-by date or "—", the stale warning's title with the four fields in a `<details>`, and "Type a lead time" (weeks + who quoted it + date, defaulting to today) and "Not long-lead". A search input over `items` (name contains) adds a flag to any item: `onLeadTime(itemId, { flagged: true })`.
- The item panel reads `schedule` only through `snapshot.items[i].phaseId` / `phaseOverridden` and the phase names it needs from `store.getSchedule` cached in the layout (`ProjectWorkspaceLayout` gains `phases` — `[{id, name}]` — loaded once and refreshed after any phase mutation; pass it through the outlet context). When `phases.length > 1` the panel shows a `<select aria-label="Phase">` with the item's resolved phase, and `COPY.phaseMoved(from)` when overridden; changing it calls `setItemPhase(itemId, phaseId)` (a `null` option "From its sheet" clears it).
- The spreadsheet's Phase column renders `phases.find(p => p.id === item.phaseId)?.name` and is hidden when `phases.length <= 1`; "Group by phase" joins the existing group-by options under the same condition.

- [ ] **Step 1: Write the failing tests**

```jsx
// src/components/schedule/LongLeadList.test.jsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import LongLeadList from "./LongLeadList.jsx";

const lead = (extra = {}) => ({ itemId: "i1", itemName: "Switchboard MSB-1", itemStatus: "ready", phaseId: "p1", phaseName: "Phase 1", leadWeeks: null, source: null,
  sourceLabel: "", quotedAt: null, neededForStage: "gear", neededBy: "2027-02-24", orderBy: null, orderByWeek: null, passed: false, stale: false, note: "", warning: null, ...extra });

describe("LongLeadList", () => {
  it("shows a flagged item without weeks as not yet quoted and with no date", () => {
    render(<LongLeadList schedule={{ multiPhase: false, leads: [lead()] }} items={[]} onLeadTime={() => {}} />);
    expect(screen.getByText("Not yet quoted")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "—" })).toBeInTheDocument();
  });

  it("types a lead time with who quoted it", async () => {
    const onLeadTime = vi.fn();
    render(<LongLeadList schedule={{ multiPhase: false, leads: [lead()] }} items={[]} onLeadTime={onLeadTime} />);
    await userEvent.click(screen.getByRole("button", { name: "Type a lead time" }));
    await userEvent.type(screen.getByLabelText("Weeks"), "40");
    await userEvent.type(screen.getByLabelText("Who quoted it"), "Eaton rep");
    await userEvent.click(screen.getByRole("button", { name: "Save lead time" }));
    expect(onLeadTime).toHaveBeenCalledWith("i1", expect.objectContaining({ leadWeeks: 40, sourceLabel: "Eaton rep" }));
  });

  it("shows the stale warning's four fields and the company source tag", () => {
    const warning = { title: "Lead time may be out of date", found: "f", why: "w", fix: "x", where: "e" };
    render(<LongLeadList schedule={{ multiPhase: false, leads: [lead({ leadWeeks: 40, source: "company", sourceLabel: "Eaton rep", quotedAt: "2026-06-01", orderBy: "2026-05-20", stale: true, warning })] }} items={[]} onLeadTime={() => {}} />);
    expect(screen.getByText(/Company: Eaton rep/)).toBeInTheDocument();
    expect(screen.getByText("Lead time may be out of date")).toBeInTheDocument();
    for (const t of ["f", "w", "x", "e"]) expect(screen.getByText(t)).toBeInTheDocument();
  });

  it("flags any item from the search field", async () => {
    const onLeadTime = vi.fn();
    render(<LongLeadList schedule={{ multiPhase: false, leads: [] }} items={[{ id: "i9", name: "Custom pendant fixture" }]} onLeadTime={onLeadTime} />);
    await userEvent.type(screen.getByLabelText("Flag an item as long-lead"), "pendant");
    await userEvent.click(screen.getByRole("button", { name: /Custom pendant fixture/ }));
    expect(onLeadTime).toHaveBeenCalledWith("i9", { flagged: true });
  });
});
```

```jsx
// src/components/ItemDetailPanel.phase.test.jsx  — follow ItemDetailPanel.decision.test.jsx's render helper
it("shows no phase field with one phase and a select with two", () => { /* render with phases=[{id:"p1",name:"Phase 1"}] -> queryByLabelText("Phase") is null; with two phases -> getByLabelText("Phase") has value "p1" */ });
it("moving an item to another phase calls setItemPhase and shows where it came from", async () => { /* select "Phase 2" -> setItemPhase("i1", "p2"); with phaseOverridden true, text matches /moved from Phase 1/ */ });
```

Write those two as real tests using the helper the decision test file already uses to mount the panel with a snapshot and a fake store; the comments above are the assertions, not placeholders for later.

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/components/schedule/LongLeadList.test.jsx src/components/ItemDetailPanel.phase.test.jsx`
Expected: FAIL — the stub renders nothing; no Phase select

- [ ] **Step 3: Write `LongLeadList.jsx`**

```jsx
// src/components/schedule/LongLeadList.jsx
/* Every flagged item and what is known about its lead time. A number
   of weeks appears only when a row carries it -- a supplier's quote,
   the estimator's own dated entry, or the firm's table -- and an
   order-by date only when there are weeks. The item's own status
   renders through Pill; the source is a tier tag. */
import { useState } from "react";
import Pill from "../Pill.jsx";
import { COPY } from "./scheduleCopy.js";
import { STAGES, stageLabel } from "./stages.js";

function shortDate(iso) {
  return iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
}

function LeadTimeForm({ lead, onSave, onCancel }) {
  const [weeks, setWeeks] = useState(lead.leadWeeks ?? "");
  const [who, setWho] = useState(lead.source === "estimator" ? lead.sourceLabel : "");
  const [when, setWhen] = useState(new Date().toISOString().slice(0, 10));
  return (
    <form className="lead-form" onSubmit={(e) => { e.preventDefault(); onSave({ leadWeeks: Number(weeks), sourceLabel: who.trim(), quotedAt: when }); }}>
      <label>Weeks <input type="text" inputMode="numeric" className="tabular" value={weeks} onChange={(e) => setWeeks(e.target.value.replace(/\D/g, ""))} /></label>
      <label>{COPY.whoSaidSo} <input type="text" value={who} onChange={(e) => setWho(e.target.value)} /></label>
      <label>Quoted on <input type="date" value={when} onChange={(e) => setWhen(e.target.value)} /></label>
      <button type="submit" className="btn btn--primary" disabled={!weeks || !who.trim()}>Save lead time</button>
      <button type="button" className="btn" onClick={onCancel}>Cancel</button>
    </form>
  );
}

export default function LongLeadList({ schedule, items, onLeadTime }) {
  const [editing, setEditing] = useState(null);
  const [query, setQuery] = useState("");
  const flagged = new Set(schedule.leads.map((l) => l.itemId));
  const matches = query.trim().length >= 2 ? items.filter((i) => !flagged.has(i.id) && i.name.toLowerCase().includes(query.toLowerCase())).slice(0, 8) : [];

  return (
    <section className="long-lead" aria-label="Long-lead items">
      <h2>Long-lead items</h2>
      <table className="long-lead__table">
        <thead>
          <tr><th>Item</th>{schedule.multiPhase ? <th>Phase</th> : null}<th>Status</th><th>Lead time</th><th>{COPY.neededFor}</th><th>{COPY.orderBy}</th><th></th></tr>
        </thead>
        <tbody>
          {schedule.leads.map((l) => (
            <tr key={l.itemId} className={l.passed ? "long-lead__row--passed" : ""}>
              <td>{l.itemName}</td>
              {schedule.multiPhase ? <td>{l.phaseName}</td> : null}
              <td><Pill status={l.itemStatus} /></td>
              <td className="tabular">
                {l.leadWeeks == null ? (
                  <><span className="muted">{COPY.notYetQuoted}</span><div className="muted small">{COPY.notYetQuotedFix}</div></>
                ) : (
                  <>{l.leadWeeks} wk <span className="tier-tag">{COPY.sourceTag(l.source, l.sourceLabel, shortDate(l.quotedAt))}</span></>
                )}
                {l.warning ? (
                  <details className="warning-details">
                    <summary>{l.warning.title}</summary>
                    <p>{l.warning.found}</p><p>{l.warning.why}</p><p>{l.warning.fix}</p><p className="muted">{l.warning.where}</p>
                  </details>
                ) : null}
                {editing === l.itemId ? <LeadTimeForm lead={l} onSave={(v) => { onLeadTime(l.itemId, v); setEditing(null); }} onCancel={() => setEditing(null)} /> : null}
              </td>
              <td>
                <select aria-label={`${COPY.neededFor} ${l.itemName}`} value={l.neededForStage} onChange={(e) => onLeadTime(l.itemId, { neededForStage: e.target.value })}>
                  {STAGES.map((s) => <option key={s} value={s}>{stageLabel(s)}</option>)}
                </select>
              </td>
              <td className="tabular">{l.orderBy ? <>{shortDate(l.orderBy)}{l.passed ? <div className="small error-text">{l.note}</div> : null}</> : "—"}</td>
              <td>
                <button type="button" className="link" onClick={() => setEditing(l.itemId)}>{COPY.typeLeadTime}</button>
                {l.leadWeeks != null && l.source === "estimator" ? <button type="button" className="link" onClick={() => onLeadTime(l.itemId, { leadWeeks: null })}>Clear</button> : null}
                <button type="button" className="link" onClick={() => onLeadTime(l.itemId, { flagged: false })}>{COPY.unflagLongLead}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <label className="long-lead__search">{COPY.flagLongLead}
        <input type="search" aria-label="Flag an item as long-lead" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      {matches.length ? (
        <ul className="long-lead__matches">
          {matches.map((i) => <li key={i.id}><button type="button" className="link" onClick={() => { onLeadTime(i.id, { flagged: true }); setQuery(""); }}>{i.name}</button></li>)}
        </ul>
      ) : null}
    </section>
  );
}
```

Check `Pill`'s real props in `src/components/Pill.jsx` (it may take `status` as the four-label key or a label object) and pass what it expects. The `"—"` cell: give the `<td>` `aria-label="—"` only if the test's `getByRole("cell", { name: "—" })` does not resolve from its text content — it should.

- [ ] **Step 4: The item panel and the spreadsheet**

`ProjectWorkspaceLayout.jsx`: add `const [phases, setPhases] = useState([])`, load `store.getSchedule(projectId).then((s) => setPhases(s.phases.map((p) => ({ id: p.id, name: p.name }))))` on mount and expose `phases` and `reloadPhases` in the outlet context. `useSchedule.mutate` calls `reloadPhases()` after a successful write so the panel's select stays current. `useReviewStore.js`: add `const setItemPhase = useCallback((id, phaseId) => runItemMutation(id, () => store.setItemPhase(id, phaseId)), [...])` and return it; because `store.setItemPhase` returns the mapped item (not `{item, version}`), have `api.js`'s `setItemPhase` return `{ item, version: item.version, label: … }` in the same shape `editItem` returns — read `editItem` in `api.js` and match it exactly.

In `ItemDetailPanel.jsx`, in the metadata block where "Sheet and location" renders, add:

```jsx
{phases.length > 1 ? (
  <div className="field">
    <label htmlFor="item-phase">{COPY.phaseField}</label>
    <select id="item-phase" value={item.phaseOverridden ? item.phaseId : ""} onChange={(e) => setItemPhase(item.id, e.target.value || null)}>
      <option value="">{COPY.phaseInherited} ({phases.find((p) => p.id === sheetPhaseId)?.name ?? ""})</option>
      {phases.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
    </select>
    {item.phaseOverridden ? <span className="muted">{COPY.phaseMoved(phases.find((p) => p.id === sheetPhaseId)?.name ?? "")}</span> : null}
  </div>
) : null}
```

where `sheetPhaseId` is the sheet's `phaseId` (add `phaseId` to the sheet mapper in `api-mapping.js`) falling back to `phases[0].id`. Import `COPY` from `./schedule/scheduleCopy.js`.

`spreadsheetColumns.js`: append `{ key: "phase", label: "Phase", render: (row, ctx) => ctx.phaseName(row.phaseId), visibleWhen: (ctx) => ctx.phases.length > 1 }` and a `phase` entry in the group-by list under the same `visibleWhen`; `TakeoffSpreadsheet.jsx` passes `{ phases, phaseName }` in the column context it already passes and filters columns by `visibleWhen` (add the filter if the columns array has no such hook yet — one `.filter((c) => !c.visibleWhen || c.visibleWhen(ctx))`).

- [ ] **Step 5: Run the tests and the build**

Run: `npx vitest run src/components/schedule src/components/ItemDetailPanel.phase.test.jsx src/components/takeoff && npm run build`
Expected: PASS; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add src/components/schedule/LongLeadList.jsx src/components/schedule/LongLeadList.test.jsx src/components/schedule/useSchedule.js src/components/ItemDetailPanel.jsx src/components/ItemDetailPanel.phase.test.jsx src/components/project/ProjectWorkspaceLayout.jsx src/lib/useReviewStore.js src/lib/store/api.js src/lib/store/api-mapping.js src/components/takeoff/spreadsheetColumns.js src/components/takeoff/spreadsheetColumns.test.js src/components/takeoff/TakeoffSpreadsheet.jsx src/styles.css
git commit -m "Schedule: the long-lead list, a phase on the item panel and the spreadsheet once a second phase exists

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Company and project settings

**Files:**
- Modify: `src/components/settings/CompanySettings.jsx` (two tabs: `crews` "Crews and stages", `leadtimes` "Lead times"), `src/components/settings/ProjectSettings.jsx` (expected award, mobilization)
- Test: `src/components/settings/CompanySettings.test.jsx` (append), `src/components/settings/ProjectSettings.test.jsx` (append)

**Interfaces:**
- Tabs appended to `TABS`: `{ id: "crews", label: "Crews and stages", intro: "How hours divide across the stages of a job, and the crew the firm puts on each." }`, `{ id: "leadtimes", label: "Lead times", intro: "Lead times your suppliers or reps have quoted, with who said so and when." }`.
- "Crews and stages" renders two grids through the existing `DataGrid` (the pricing grid): the split table (rows = categories, six percent columns, a computed "Total" column that turns `error-text` when not 100, an "Add category" row, delete per row) and the crew table (rows = the six stages, columns foreman / journeyman / apprentice / productive hours per day / productivity factor / max crew). A row not yet `firmEdited` shows the `Default` tier tag; the first edit clears it. Above both: `lead_time_stale_days` as one labeled number field ("Lead times count as out of date after N days").
- "Lead times" renders one row per long-lead class (the eight from `stages.py`, listed in `scheduleCopy.js` as `LONG_LEAD_CLASSES` with labels): weeks, who quoted it, quoted on; blank until entered; clear per row. No default numbers anywhere on this tab — a blank row reads "Not entered".
- Project settings gain two date fields beside the ZIP: "Expected award" and "Mobilization", saved through the project PATCH like `postalCode` (read `ProjectSettings.jsx:55-110` and copy the pattern: local state, saved value, `store.updateProject`, a toast).

- [ ] **Step 1: Write the failing tests**

```jsx
// append to src/components/settings/CompanySettings.test.jsx — use the file's existing render helper and fake store
it("Crews and stages shows the split rows with Default until edited and refuses a row that does not total 100", async () => {
  // store.getStageSplits resolves [{ categoryKey: "devices", categoryLabel: "Devices", demolition: 0, roughIn: 45, wirePull: 25, gear: 0, trim: 25, closeout: 5, firmEdited: false }]
  // open the tab; expect getByText("Default"); edit trim to 20; expect the row's Total cell to have class error-text and store.setStageSplit not called
});
it("Lead times shows Not entered for a class with no row and saves a dated entry", async () => {
  // store.getCompanyLeadTimes resolves []; expect getAllByText("Not entered").length === 8; fill switchboard weeks 52, who "Eaton rep", date; expect store.setCompanyLeadTime("switchboard", { leadWeeks: 52, sourceLabel: "Eaton rep", quotedAt: "<date>" })
});
```

```jsx
// append to src/components/settings/ProjectSettings.test.jsx
it("saves expected award and mobilization dates through the project patch", async () => {
  // type 2026-12-01 into "Expected award", blur; expect store.updateProject(projectId, { expectedAwardDate: "2026-12-01" })
});
```

Write the three as complete tests against the helpers those files already have.

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/components/settings`
Expected: FAIL — no such tab, no such field

- [ ] **Step 3: Build the tabs and the fields**

Follow the labor-rates tab's structure in `CompanySettings.jsx` (its store-backed section with load / edit / save and the `DataGrid` columns pattern from `labor/laborColumns.jsx`). Percent cells are `inputmode="decimal"` text editors; the row saves on the last cell's commit only when the six total 100, otherwise the Total cell shows `error-text` and the row is held locally with a one-line note "The six stages have to add up to 100 percent." Crew cells are integers except the two decimals. Every save calls the store, replaces the row from the response, and shows a toast without Undo (company edits are not undoable — say "Saved" in the toast, as the labor-rates tab does).

The "Lead times" tab is a plain table (no `DataGrid`): eight rows keyed by class, each with weeks / who / date inputs and a Save button enabled when all three are filled, a Clear button when a row exists.

Project settings: two `<input type="date">` fields with persistent labels, saved on change through the same code path as the ZIP.

- [ ] **Step 4: Run the tests and the build**

Run: `npx vitest run src/components/settings && npm run build`
Expected: PASS; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add src/components/settings/CompanySettings.jsx src/components/settings/CompanySettings.test.jsx src/components/settings/ProjectSettings.jsx src/components/settings/ProjectSettings.test.jsx src/components/schedule/scheduleCopy.js src/styles.css
git commit -m "Settings: the firm's crews, stage splits, and lead times; the project's award and mobilization dates

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: Export rolls up per phase

**Files:**
- Modify: `src/components/export/ExportPreview.jsx`
- Test: `src/components/export/ExportPreview.test.jsx` (append)

**Interfaces:**
- The preview loads `store.getSchedule(projectId)` alongside the snapshot. When `schedule.multiPhase`: a "Summary by phase" table (Phase, Qty `1`, Unit `LS`, Total labor hours = `directHours + generalConditionsHours`, Material = `materialTotal`) above the columns preview, and the CSV gains those rows first, then a heading row per phase, then that phase's general-conditions lines (label, `1`, `LS`, hours), then its items (rows filtered by `item.phaseId`). When single-phase: the general-conditions lines under one heading, then the rows as today. When `schedule.leads.length`: a "Long-lead items" table (Item, Phase when multi, Lead weeks, Source, Needed for, Order by or "Not yet quoted") and the same as CSV rows after the items. The approved totals block and the blocking rules are untouched.

- [ ] **Step 1: Write the failing tests**

```jsx
// append to src/components/export/ExportPreview.test.jsx — reuse the file's render helper and fake store; add getSchedule to the store
it("single-phase export has no phase summary and no phase column", async () => {
  // getSchedule -> multiPhase false, one phase with two lines, leads []
  // expect queryByText("Summary by phase") null; the CSV (capture the Blob the download builds, as the existing tests do) contains "Final and daily cleanup,1,LS," and no "Phase 1" summary row
});
it("multi-phase export carries one lump-sum row per phase and groups rows by phase", async () => {
  // two phases, items i1 (phaseId p1) and i2 (phaseId p2)
  // expect getByText("Summary by phase"); CSV lines include "Phase 1,1,LS,<hours>" and "Phase 2,1,LS,<hours>" before any item row; i1's row appears after the "Phase 1" heading and before "Phase 2"
});
it("long-lead rows list weeks, source, and order-by or Not yet quoted", async () => {
  // leads: one with weeks 40 source supplier_quote "Graybar" orderBy 2026-05-25; one without weeks
  // expect getByText("Long-lead items"); CSV has "Switchboard MSB-1,40,Graybar,Gear,2026-05-25" and ",Not yet quoted" for the other
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run src/components/export`
Expected: FAIL — "Summary by phase" not found

- [ ] **Step 3: Build it**

In `ExportPreview.jsx`, after `exportRows` is built: load the schedule (`useEffect` + `useState`, same load pattern as `LaborWorkspace`); build `summaryRows`, `sectionedRows`, and `leadRows` as plain arrays of strings; the CSV is `[...summaryRows, ...sectionedRows, ...leadRows]` when the schedule has loaded and the flat `exportRows` until then (the button is disabled while loading, with the copy "Preparing the export"). Render the two new tables under the existing "Columns in the export" section with the same table markup. Group items by `item.phaseId` matched to `schedule.phases[].id`; an item whose `phaseId` is null (a project with no phase row) belongs to the first phase.

- [ ] **Step 4: Run the tests and the build**

Run: `npx vitest run src/components/export && npm run build`
Expected: PASS; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add src/components/export/ExportPreview.jsx src/components/export/ExportPreview.test.jsx
git commit -m "Export: one lump-sum row per phase, sections per phase, and the long-lead items stated in the bid

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 15: Invariants, the full suites, and the integration notes

**Files:**
- Create: `api/tests/test_schedule_invariants.py`
- Test: everything

- [ ] **Step 1: Write the invariant tests**

```python
# api/tests/test_schedule_invariants.py
"""The three promises the spec makes about what this feature does not
touch (phases-and-timeline.md §13, Invariants)."""
from decimal import Decimal

from app.schedule import phases as svc
from app.takeoff.models import CompanyLaborRate
from app.takeoff.totals import approved_totals


def _labor_rows(client, project):
    return client.get(f"/api/projects/{project.id}/labor").json()


def _material_rows(client, project):
    return client.get(f"/api/projects/{project.id}/material-pricing").json()


def test_a_single_phase_project_is_byte_identical_before_and_after_its_first_phase_row(client, signed_in_user, project, sheet, item, org, db):
    db.add(CompanyLaborRate(org_id=org.id, journeyman_rate=Decimal("85"), foreman_rate=Decimal("95"), apprentice_rate=Decimal("55"))); db.flush()
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.5})
    before = (approved_totals(db, project.id), _labor_rows(client, project), _material_rows(client, project),
              client.get(f"/api/projects/{project.id}/snapshot").json()["items"])
    client.get(f"/api/projects/{project.id}/schedule")          # creates the implicit first phase
    after = (approved_totals(db, project.id), _labor_rows(client, project), _material_rows(client, project),
             client.get(f"/api/projects/{project.id}/snapshot").json()["items"])
    for a, b in zip(before[:3], after[:3]):
        assert a == b
    # The snapshot's items gain phase_id once the phase exists; everything else is identical.
    for a, b in zip(before[3], after[3]):
        a.pop("phase_id", None); b.pop("phase_id", None)
        assert a == b


def test_assigning_every_sheet_to_a_second_phase_changes_no_total_status_or_labor_row(client, signed_in_user, project, sheet, item, org, db, dana):
    db.add(CompanyLaborRate(org_id=org.id, journeyman_rate=Decimal("85"), foreman_rate=Decimal("95"), apprentice_rate=Decimal("55"))); db.flush()
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.5})
    client.post(f"/api/items/{item.id}/approve", headers={"If-Match": "2"})
    totals, labor = approved_totals(db, project.id), _labor_rows(client, project)
    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id]); db.commit()
    assert approved_totals(db, project.id) == totals
    assert _labor_rows(client, project) == labor
    db.refresh(item)
    assert item.status.value == "approved"
```

The `If-Match` version in the approve call is whatever the item's version is after the labor patch — read it from the snapshot rather than hard-coding `"2"` if the labor patch does not bump `Item.version` (it should not; check `test_optimistic_concurrency.py` for the convention and use `item.version` from a fresh `db.refresh(item)`).

- [ ] **Step 2: Run both suites in full**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q`
Expected: PASS, every file.

Run: `npx vitest run && npm run build`
Expected: PASS; build succeeds.

- [ ] **Step 3: Copy check**

Run: `grep -rn "recommended\|industry standard\|AI \|confidence" src/components/schedule api/app/schedule --include=*.js --include=*.jsx --include=*.py`
Expected: no matches in user-facing strings (a match inside a code comment is fine; a match inside `COPY` or `copy.py` is a failure — fix it).

Run: `grep -rnE "\b(35|40|50|52|60|62|80)\s*(weeks|wk)" src/components/schedule/scheduleCopy.js api/app/schedule/copy.py`
Expected: no matches — no published lead-time number lives in a string.

- [ ] **Step 4: Commit**

```bash
git add api/tests/test_schedule_invariants.py
git commit -m "Schedule: the invariants — a single-phase project is unchanged, and a phase moves no total

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Notes for the integration commit (not this branch)**

`CLAUDE.md`, `README.md`, and `docs/README.md` are edited only in the merge commit (`workstreams-2026-09.md` §4). Leave this text in the plan for whoever merges:

- `CLAUDE.md` architecture tree: add `api/app/schedule/` (one line per module, as `api/app/market/` is listed) and `src/components/schedule/`; under *Known scope limits* add: "Phases and schedule is built: every item belongs to a phase, stage bars and the manpower chart are derived from resolved labor hours and the firm's crew tables, and long-lead order-by dates draw only from a supplier's quote or the firm's own dated entry. Not built: holidays, dependencies across phases, dragging bars, the GC's schedule import (docs/specs/phases-and-timeline.md §12)."
- `README.md` project structure: the same two directories; *Known limitations*: the §12 list in one sentence.
- `docs/README.md`: the spec and plan under their sections; move this plan to `docs/plans/done/` once merged.
- Renumber `0026_phases_and_schedule.py` behind whatever landed first and say so in the merge message, as `bbd9757` did.

---

## Self-review against the spec

| Spec section | Task |
|---|---|
| §3.1 phases, implicit first, `phase_of`, delete moves sheets | 1, 5 |
| §3.2 phase lines, computed vs typed | 1, 2, 3, 6 |
| §3.3 stages, split table, crews, seeds, "default" labelling | 1, 2, 3, 13 |
| §3.4 line templates | 2, 13 |
| §3.5 per-phase overrides | 1, 6, 11 |
| §3.6 project dates | 1, 7, 13 |
| §3.7 lead times: flag by word list, two sources, company table, staleness | 1, 4, 6, 7, 8, 12, 13 |
| §4 arithmetic 1–8 | 3, 4, 7 |
| §5 status and language, the stale warning | 4, 11, 12, 15 |
| §6 the screen and its parts | 10, 11, 12 |
| §7 price sheet column, firm entry, precedence | 8, 12, 13, 7 |
| §8 export | 14 |
| §9 propose / apply, the F handoff | 7, 10 |
| §10 API surface, action kinds, undo | 5, 6, 7 |
| §11 migration, delete snapshot, merge untouched | 1, 5 |
| §13 tests, invariants | every task; 15 |

Known simplifications in this plan, each a deliberate reading of the spec rather than a gap: `PhaseOut.material_total` sums `Item.material_cost` (the engine's stored figure) rather than the pricing resolution, matching what the export reads today (`estimate-first-pricing.md` §5's "until one pricing truth lands"); the reverse solve apportions the window's working days across bars in proportion to hours before sizing each crew (§4.6 says "the same stage proportions"); and a project whose only dates are on a later phase renders the earlier phases relatively — the spec's "with no date anywhere" case generalised to "no date reaching this phase".

---

## Integration notes (written after the branch was built)

`main` moved while this stream ran: stream A (pricing hardening) and
stream B (the spreadsheet grid) merged at `54b2f14`. Two things follow.

**No migration renumbering.** `main`'s head is still `0025_market_pricing`,
so `0026_phases_and_schedule` chains cleanly. Check again at merge time —
streams C and F merge ahead of D in the planned order.

**One real conflict, in the price sheet (Task 8).** Both branches add an
`unreadable` group to the preview, and — fortunately — with the same
shape, `[{line, reason}]`:

| File | `main` (stream A) | This branch (Task 8) |
|---|---|---|
| `market/price_sheet.py` | adds `ParsedSheet.unreadable`, filled by a per-row `try/except` around the price cell | adds `"Lead time (weeks)"` to `HEADER`, and `ParsedRow.lead_weeks` / `.lead_error` |
| `worker/price_sheet_job.py` | `"unreadable": [... for line, reason in parsed.unreadable]` | builds the same list in the row loop from `r.lead_error` |
| `takeoff/schemas.py` | `unreadable: list[dict] = []` on `PriceSheetPreviewOut` | the same field, same type |

Resolve it by keeping **main's mechanism** and feeding this branch's
lead-time errors into it: have `parse_price_sheet` append
`(row.line, row.lead_error)` to `ParsedSheet.unreadable` where this
branch currently sets `ParsedRow.lead_error`, then drop the job-loop
collection added here and keep main's single `parsed.unreadable`
comprehension. Take either copy of the `schemas.py` field — they are
identical. The tests from both branches then pass unchanged: main's
assert a bad price is named by row, this branch's assert a bad lead time
is (`"Row 3: the lead time isn't a number of weeks"`).

`price_sheet.py`'s `HEADER` gains the lead-time column from this branch
only — main does not touch it — but note the **row key moves from column
8 to 9**, which is why `test_market_price_sheet.py` and
`test_pricing_endpoints.py` here derive it from `HEADER` rather than
hard-coding it. Keep those derived versions.
