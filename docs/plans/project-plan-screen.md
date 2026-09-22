# Project plan screen — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Written 2026-09-21. Spec: [`docs/specs/project-plan-screen.md`](../specs/project-plan-screen.md). Read it first; every rule below comes from it.

**Goal:** A new screen between Confirm drawings and Processing that says what the documents state — scope, Division 26/27/28 spec sections, schedules, phasing, exclusions, open questions — each line quoted and linked to its page, each confirmable, nothing counted.

**Architecture:** Plan lines are *derived* on every `GET /api/projects/{id}/plan` from rows the read job already stores (`Sheet`, `Document`, `ScopeStatement`), by pure functions in `api/app/plan/detect.py`. Only the estimator's decisions persist, in `plan_decisions` keyed by a stable entry key, plus `plan_phases` for phases the estimator adds. Every write is audited through `actions.commit()` and none is undoable. The screen is `src/components/plan/PlanWorkspace.jsx`, a child of `ProjectWorkspaceLayout`, and it owns *Start takeoff*; screen D's primary button becomes *Review the plan*.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic + pytest (backend, `cd api && ../.enginevenv/bin/python -m pytest -q`); React 18 + react-router 6 + vitest + testing-library (frontend, `npm test -- --run`); plain CSS tokens.

## Global constraints

- Worktree: `/Users/nikhit/Documents/takeoff-review/.claude/worktrees/relaxed-shtern-e88960`. Run everything from there. Dev server port **5175**. Never `git stash`; never `git add -A` (the `bid_examples` and `.enginevenv` symlinks must never be committed — always `git add` named paths).
- Commit messages: a plain sentence, blank line, then `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Files this stream owns: `api/app/plan/**`, `api/app/scope/**`, `api/app/engine/scope.py`, `src/components/plan/**`, `src/lib/projectStage.js`, and their tests. Shared files are **append-only** (never reorder or edit existing lines): `api/app/main.py`, `api/migrations/env.py`, `src/routes.jsx`, `src/components/shell/ProjectNav.jsx`, `api/tests/test_tenancy.py`, `src/lib/store/api.js`, `src/lib/store/api-mapping.js`, `src/components/conversation/screenContext.jsx`, `api/app/assistant/schemas.py`. `src/styles.css`: append at the END under `/* ==== stream F: plan ==== */`. `src/components/documents/ConfirmDrawings.jsx` gets the minimal edit Task 13 describes and nothing else.
- Do not edit `CLAUDE.md`, `README.md`, `docs/README.md`, anything under `src/components/pricing/`, `src/components/grid/`, `api/app/worker/`, `api/app/market/`, `api/app/takeoff/models.py`.
- Migration is `0026_plan.py`, `revision = '0026'`, `down_revision = '0025'`. Constants spelled out, nothing imported from `app`.
- `api/app/plan/` imports nothing from `app.engine` (the boundary test `test_api_import_boundary.py` forbids the file-opening modules; keep the whole package out to be safe). No PDF is opened.
- Copy rules (CLAUDE.md): sentence case; no exclamation marks, no "successfully", no "please"; never a model name, vendor, confidence, run id, attempt count, or pattern name on the wire or the screen. A plan line's status words are `found` / `confirmed` / `dismissed` / `answered` — never the four review labels, never `Pill.jsx`, drawn with `.note-status`.
- Every question carries `title`, `found`, `why`, `fix`, `where`, all non-empty.
- Nothing on the plan screen is counted: no quantities, no item counts.
- `tabular` class on every number rendered.

## File map

| File | Responsibility |
|---|---|
| `api/migrations/versions/0026_plan.py` | the two tables |
| `api/app/plan/__init__.py` | empty |
| `api/app/plan/models.py` | `PlanDecision`, `PlanPhase` |
| `api/app/plan/detect.py` | pure derivation: `spec_sections`, `schedules`, `phases`, `questions`, input dataclasses |
| `api/app/plan/copy.py` | the six questions' words |
| `api/app/plan/schemas.py` | `PlanOut`, `PlanLineOut`, `QuestionOut`, `PlaceOut`, `LineDecisionIn`, `AnswerIn`, `PhaseIn`; `PLAN_STATUSES` |
| `api/app/plan/service.py` | `build_plan`, `decide`, `answer`, `add_phase`, `remove_phase` |
| `api/app/plan/router.py` | the five routes |
| `api/tests/test_plan_detect.py`, `test_plan_corpus.py`, `test_plan_api.py` | backend tests |
| `src/lib/projectStage.js` | gains the `plan` stage |
| `src/lib/store/api.js`, `api-mapping.js` | `getPlan`, `decidePlanLine`, `answerPlanQuestion`, `addPlanPhase`, `removePlanPhase`; `mapPlan` |
| `src/components/plan/PlanLine.jsx` | one row: status, text, correction, cite + page link, source, decision controls |
| `src/components/plan/PlanSection.jsx` | heading, description, empty sentence, list |
| `src/components/plan/ScopeSection.jsx` | moved from `documents/`, rendered through `PlanLine`, controlled or self-fetching |
| `src/components/plan/QuestionLine.jsx` | four fields, Answer form, Dismiss |
| `src/components/plan/PhaseSection.jsx` | detected + added phases, Add a phase |
| `src/components/plan/PlanWorkspace.jsx` | the screen, polling, Start takeoff |
| `src/components/plan/pageLink.js` | `documentPageHref(documentId, page)` |

---

### Task 1: Migration and models

**Files:**
- Create: `api/migrations/versions/0026_plan.py`, `api/app/plan/__init__.py`, `api/app/plan/models.py`
- Modify (append one line): `api/migrations/env.py`
- Test: `api/tests/test_plan_models.py`

**Interfaces:**
- Produces: `app.plan.models.PlanDecision(project_id, entry_key, status, edited_text, note_id, decided_by, decided_at)` and `PlanPhase(project_id, name, created_by, created_at)`; `PLAN_STATUSES = ("found", "confirmed", "dismissed", "answered")` lives in `app/plan/schemas.py` (Task 4) — the models module spells the tuple inline for its check constraint, the way `takeoff/models.py` does for scope.

- [ ] **Step 1: Write the failing test**

`api/tests/test_plan_models.py`:

```python
"""plan_decisions and plan_phases: one row per decision a person made on
the plan, one per phase they stated. Nothing derived is stored here."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.plan.models import PlanDecision, PlanPhase


def test_a_decision_is_unique_per_project_and_key(db, project, dana):
    db.add(PlanDecision(project_id=project.id, entry_key="spec:x:260519", status="confirmed",
                        decided_by=dana.id, decided_at=datetime.now(timezone.utc)))
    db.flush()
    db.add(PlanDecision(project_id=project.id, entry_key="spec:x:260519", status="dismissed",
                        decided_by=dana.id, decided_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        db.flush()


def test_status_is_a_closed_set(db, project, dana):
    db.add(PlanDecision(project_id=project.id, entry_key="k", status="approved",
                        decided_by=dana.id, decided_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        db.flush()


def test_an_added_phase_belongs_to_its_project(db, project, dana):
    p = PlanPhase(project_id=project.id, name="Phase 2", created_by=dana.id)
    db.add(p); db.flush()
    row = db.execute(text("select name from plan_phases where id = :id"), {"id": str(p.id)}).scalar_one()
    assert row == "Phase 2"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_models.py -q`
Expected: ImportError on `app.plan.models`.

- [ ] **Step 3: Write the models**

`api/app/plan/__init__.py`: empty file.

`api/app/plan/models.py`:

```python
"""The plan's own rows: decisions a person made on derived lines, and
phases a person stated. Everything else on the plan screen is derived
on read from sheets, documents and scope statements (docs/specs/
project-plan-screen.md, "Why derive"), so nothing here mirrors a line.

Kept out of app/takeoff/models.py on purpose: nothing there needs a
foreign key to these, and this stream owns this package alone. The
status set is spelled inline for the check constraint, as
takeoff/models.py does for scope statements; app/plan/schemas.py
carries the same tuple for the wire."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
import app.takeoff.models  # noqa: E402, F401 -- notes, users, projects must be registered for the FKs below


class PlanDecision(Base):
    __tablename__ = "plan_decisions"
    __table_args__ = (
        UniqueConstraint("project_id", "entry_key", name="uq_plan_decisions_project_key"),
        CheckConstraint("status in ('found', 'confirmed', 'dismissed', 'answered')", name="ck_plan_decisions_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    entry_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="found", server_default="found")
    edited_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notes.id", ondelete="SET NULL"), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanPhase(Base):
    __tablename__ = "plan_phases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`api/migrations/versions/0026_plan.py`:

```python
"""plan

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-21 00:00:00.000000

docs/specs/project-plan-screen.md: the two tables the project plan
owns. plan_decisions holds one row per derived line a person decided,
keyed by the line's stable entry key; plan_phases holds phases a person
stated. Nothing derived is stored. Statuses are spelled out here rather
than imported, per 0020/0021's convention.

Numbered 0026 on this branch; renumber at integration if another
stream's migration lands first (the repo has done this twice).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0026'
down_revision: Union[str, None] = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUSES = "'found', 'confirmed', 'dismissed', 'answered'"


def upgrade() -> None:
    op.create_table(
        'plan_decisions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entry_key', sa.String(length=300), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='found'),
        sa.Column('edited_text', sa.String(length=500), nullable=True),
        sa.Column('note_id', UUID(as_uuid=True), sa.ForeignKey('notes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('project_id', 'entry_key', name='uq_plan_decisions_project_key'),
        sa.CheckConstraint(f"status in ({_STATUSES})", name='ck_plan_decisions_status'),
    )
    op.create_index('ix_plan_decisions_project_id', 'plan_decisions', ['project_id'])

    op.create_table(
        'plan_phases',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_plan_phases_project_id', 'plan_phases', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_plan_phases_project_id', table_name='plan_phases')
    op.drop_table('plan_phases')
    op.drop_index('ix_plan_decisions_project_id', table_name='plan_decisions')
    op.drop_table('plan_decisions')
```

Append to `api/migrations/env.py`, directly after the line `from app.takeoff import models as takeoff_models  # noqa: F401`:

```python
from app.plan import models as plan_models  # noqa: F401
```

- [ ] **Step 4: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_models.py tests/test_worker_import_boundary.py tests/test_api_import_boundary.py -q`
Expected: all pass. (The `db` fixture runs `Base.metadata.create_all`; `conftest` imports `app.main`, which does not yet import `app.plan` — the test file's own import registers the models, which is enough.)

- [ ] **Step 5: Check the migration applies and reverts on a scratch database**

```bash
cd api && TEST_DB=$(grep TEST_DATABASE_URL .env | cut -d= -f2-) && DATABASE_URL="$TEST_DB" ../.enginevenv/bin/alembic upgrade head && DATABASE_URL="$TEST_DB" ../.enginevenv/bin/alembic downgrade 0025 && DATABASE_URL="$TEST_DB" ../.enginevenv/bin/alembic upgrade head
```

Expected: no errors. (If `alembic` reads its URL from another variable, check `api/migrations/env.py` and `app/config.py` for the name and use that one.)

- [ ] **Step 6: Commit**

```bash
git add api/migrations/versions/0026_plan.py api/migrations/env.py api/app/plan/__init__.py api/app/plan/models.py api/tests/test_plan_models.py
git commit -m "Plan: the two tables a project plan owns — decisions and stated phases (migration 0026)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Derivation — `detect.py` and `copy.py`

**Files:**
- Create: `api/app/plan/detect.py`, `api/app/plan/copy.py`
- Test: `api/tests/test_plan_detect.py`

**Interfaces:**
- Produces (all in `app.plan.detect`):
  - `@dataclass(frozen=True) DocIn(id: str, filename: str, doc_type: str, status: str, context_text: str, page_count: int | None)`
  - `@dataclass(frozen=True) SheetIn(id: str, document_id: str, number: str, title: str, kind: str, page_index: int, scale: str, scale_options: tuple, unreadable_reason: str, schedule_text: str)`
  - `@dataclass(frozen=True) Place(document_id: str, document_filename: str, page: int | None, quote: str)`
  - `@dataclass Line(key: str, kind: str, text: str, place: Place, division: str | None = None, sheet_number: str | None = None, places: list[Place] = [])`
  - `@dataclass Question(key: str, rule: str, title: str, found: str, why: str, fix: str, where: str, document_id: str | None)`
  - `spec_sections(docs: list[DocIn]) -> list[Line]`
  - `schedules(sheets: list[SheetIn], docs: list[DocIn]) -> list[Line]`
  - `phases(sheets: list[SheetIn], docs: list[DocIn]) -> list[Line]`
  - `questions(sheets, docs, *, scope_count: int, phase_count: int, schedule_count: int) -> list[Question]`
  - `normalise_phase(label: str) -> str` (`"phase 1"` → `"PHASE 1"`), `phase_display(norm: str) -> str` (`"PHASE 1"` → `"Phase 1"`)
- `app.plan.copy`: `scanned(filename, unreadable, total) -> dict`, `no_specs() -> dict`, `no_scope() -> dict`, `no_scale(sheet_number, title) -> dict`, `no_phasing() -> dict`, `no_schedule() -> dict` — each returns `{"title", "found", "why", "fix", "where"}`.

- [ ] **Step 1: Write the failing tests**

`api/tests/test_plan_detect.py`:

```python
"""The plan's derivation is pure: stored text in, typed lines out. No
database, no PDF. Every rule here is asserted on synthetic text; the
corpus assertions live in test_plan_corpus.py."""

from app.plan import copy
from app.plan.detect import DocIn, SheetIn, phases, questions, schedules, spec_sections


def doc(**o):
    d = dict(id="d1", filename="Spec.pdf", doc_type="Specifications", status="processed", context_text="", page_count=10)
    d.update(o)
    return DocIn(**d)


def sheet(**o):
    s = dict(id="s1", document_id="dd", number="E2.1", title="Power plan", kind="plan", page_index=3,
             scale='1/8" = 1\'-0"', scale_options=(), unreadable_reason="", schedule_text="")
    s.update(o)
    return SheetIn(**s)


DRAWINGS = doc(id="dd", filename="E-set.pdf", doc_type="Drawings")


# --- spec sections ---

def test_each_number_form_is_one_section():
    text = "SECTION 26 05 19 - LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES\nblah\n260533 RACEWAYS AND BOXES\n27-15-00 Communications horizontal cabling\n28 31 00\nFIRE DETECTION AND ALARM\n"
    lines = spec_sections([doc(context_text=text)])
    assert [(l.division, l.text) for l in lines] == [
        ("26", "26 05 19 — LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES"),
        ("26", "26 05 33 — RACEWAYS AND BOXES"),
        ("27", "27 15 00 — Communications horizontal cabling"),
        ("28", "28 31 00 — FIRE DETECTION AND ALARM"),
    ]
    assert lines[0].key == "spec:d1:260519"
    assert lines[0].place.quote == "SECTION 26 05 19 - LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES"
    assert lines[0].place.page is None and lines[0].place.document_filename == "Spec.pdf"


def test_a_repeated_section_is_one_line_and_other_divisions_are_ignored():
    text = "26 05 19 CONDUCTORS\n23 05 00 HVAC\n26 05 19 CONDUCTORS (continued)\n"
    lines = spec_sections([doc(context_text=text)])
    assert [l.key for l in lines] == ["spec:d1:260519"]
    assert lines[0].place.quote == "26 05 19 CONDUCTORS"


def test_drawings_and_unprocessed_documents_contribute_no_sections():
    assert spec_sections([doc(doc_type="Drawings", context_text="26 05 19 X")]) == []
    assert spec_sections([doc(status="processing", context_text="26 05 19 X")]) == []


def test_a_bare_number_with_no_title_anywhere_is_dropped():
    assert spec_sections([doc(context_text="26 05 19\n\n")]) == []


# --- schedules ---

def test_schedule_and_legend_sheets_are_lines_and_plan_sheets_with_a_heading_are_too():
    rows = [
        sheet(id="a", number="E0.1", title="Luminaire schedule", kind="schedule", page_index=0),
        sheet(id="b", number="E0.2", title="Symbols legend", kind="legend", page_index=1),
        sheet(id="c", number="E4.1", title="Power plan", kind="plan", page_index=4,
              schedule_text="PANEL SCHEDULE LP-1\n... PANEL SCHEDULE LP-2"),
        sheet(id="d", number="E5.1", title="Lighting plan", kind="plan", page_index=5),
    ]
    lines = schedules(rows, [DRAWINGS])
    assert [(l.key, l.text, l.sheet_number, l.place.page) for l in lines] == [
        ("schedule:sheet:a", "Luminaire schedule", "E0.1", 1),
        ("schedule:sheet:b", "Symbols legend", "E0.2", 2),
        ("schedule:heading:c:PANEL SCHEDULE", "Panel schedule on E4.1", "E4.1", 5),
    ]
    assert lines[2].place.quote == "PANEL SCHEDULE LP-1"


def test_an_unreadable_sheet_is_never_a_schedule():
    rows = [sheet(id="a", kind="other", title="Scanned sheet", unreadable_reason="scan")]
    assert schedules(rows, [DRAWINGS]) == []


# --- phases ---

def test_phases_group_across_titles_notes_and_specs():
    rows = [
        sheet(id="a", number="D1", title="Phase 1 demolition plan", page_index=0),
        sheet(id="b", number="E2", title="PHASE 1 POWER PLAN", page_index=1),
        sheet(id="c", number="E3", title="Power plan", page_index=2, schedule_text="WORK IN PHASE II SHALL FOLLOW..."),
    ]
    spec = doc(context_text="Phase A work is limited to the north wing.\nThe next phase of the work...")
    lines = phases(rows, [DRAWINGS, spec])
    assert [(l.key, l.text) for l in lines] == [
        ("phase:PHASE 1", "Phase 1"), ("phase:PHASE II", "Phase II"), ("phase:PHASE A", "Phase A"),
    ]
    first = lines[0]
    assert first.place.quote == "Phase 1 demolition plan" and first.place.page == 1
    assert [p.page for p in first.places] == [1, 2]
    # "the next phase of" carries no number or letter, so it is not a phase.
    assert all("of" not in l.text for l in lines)


# --- questions ---

def q(rule, rows, docs, **counts):
    counts = {"scope_count": 0, "phase_count": 0, "schedule_count": 0, **counts}
    return [x for x in questions(rows, docs, **counts) if x.rule == rule]


def test_every_question_has_four_non_empty_fields():
    rows = [sheet(id="a", kind="other", title="Scanned sheet", unreadable_reason="scan"),
            sheet(id="b", number="E2.1", scale="", scale_options=())]
    for x in questions(rows, [DRAWINGS], scope_count=0, phase_count=0, schedule_count=0):
        assert x.title and x.found and x.why and x.fix and x.where


def test_scanned_counts_pages_per_document():
    rows = [sheet(id="a", document_id="dd", kind="other", unreadable_reason="scan", page_index=0),
            sheet(id="b", document_id="dd", kind="plan", page_index=1)]
    [x] = q("scanned", rows, [DRAWINGS])
    assert x.key == "question:scanned:dd" and x.document_id == "dd"
    assert x.found.startswith("1 of 2 pages in E-set.pdf")
    assert q("scanned", [sheet()], [DRAWINGS]) == []


def test_no_specs_no_scope_no_phasing_no_schedule_fire_on_the_project():
    rows = [sheet()]
    assert [x.key for x in q("no_specs", rows, [DRAWINGS])] == ["question:no_specs:project"]
    assert q("no_specs", rows, [DRAWINGS, doc()]) == []
    assert [x.key for x in q("no_scope", rows, [DRAWINGS])] == ["question:no_scope:project"]
    assert q("no_scope", rows, [DRAWINGS], scope_count=2) == []
    assert q("no_scope", rows, []) == []
    assert [x.key for x in q("no_phasing", rows, [DRAWINGS])] == ["question:no_phasing:project"]
    assert q("no_phasing", rows, [DRAWINGS], phase_count=1) == []
    assert [x.key for x in q("no_schedule", rows, [DRAWINGS])] == ["question:no_schedule:project"]
    assert q("no_schedule", rows, [DRAWINGS], schedule_count=1) == []
    # No readable plan sheet: neither phasing nor schedule is asked.
    scanned = [sheet(kind="other", unreadable_reason="scan")]
    assert q("no_phasing", scanned, [DRAWINGS]) == [] and q("no_schedule", scanned, [DRAWINGS]) == []


def test_no_scale_fires_per_readable_plan_sheet_without_a_scale():
    rows = [sheet(id="a", number="E2.1", scale="", scale_options=()),
            sheet(id="b", number="E2.2", scale="", scale_options=('1/8"',)),
            sheet(id="c", number="E0.1", kind="schedule", scale="")]
    [x] = q("no_scale", rows, [DRAWINGS])
    assert x.key == "question:no_scale:a" and "E2.1" in x.found and "E2.1" in x.where


def test_keys_are_stable_across_calls_and_quote_changes():
    a = spec_sections([doc(context_text="26 05 19 CONDUCTORS")])
    b = spec_sections([doc(context_text="SECTION 26 05 19 - CONDUCTORS AND CABLES")])
    assert a[0].key == b[0].key


def test_copy_never_names_internals():
    for words in (copy.scanned("x.pdf", 2, 2), copy.no_specs(), copy.no_scope(), copy.no_scale("E1", "Plan"),
                  copy.no_phasing(), copy.no_schedule()):
        joined = " ".join(words.values()).lower()
        assert not any(w in joined for w in ("model", "confidence", "llm", "ocr", "regex", "pattern"))
        assert "!" not in joined and "please" not in joined
```

- [ ] **Step 2: Run to see it fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_detect.py -q`
Expected: ImportError.

- [ ] **Step 3: Write `copy.py`**

`api/app/plan/copy.py`:

```python
"""The words for each open question the plan can ask. Four fields each
-- what was found, why it matters, what to check, where -- the warning
shape CLAUDE.md requires. An estimator's words: no file internals, no
mention of how the reading was done."""

from __future__ import annotations


def scanned(filename: str, unreadable: int, total: int) -> dict:
    pages = "page" if total == 1 else "pages"
    return {
        "title": "Pages that could not be read",
        "found": f"{unreadable} of {total} {pages} in {filename} are scanned images with no readable text.",
        "why": "Nothing on those pages was read, so the takeoff will count nothing on them and no scope, schedule, or phasing was taken from them.",
        "fix": "Upload a version exported from the drafting software, or state the scope and phasing here as answers.",
        "where": f"{filename}, every page that could not be read.",
    }


def no_specs() -> dict:
    return {
        "title": "No specification was uploaded",
        "found": "The documents include drawings but no specification.",
        "why": "Fixture types, wiring methods, and what is by others are usually stated in Division 26 of the specification, not on the drawings.",
        "fix": "Upload the project manual or the Division 26, 27, and 28 sections, or state here that the drawings are the whole bid set.",
        "where": "Documents.",
    }


def no_scope() -> dict:
    return {
        "title": "No scope language was found",
        "found": "None of the uploaded documents state what the electrical work includes, excludes, or leaves to others.",
        "why": "Without a scope statement the takeoff counts everything electrical on every sheet, including work that may be by others.",
        "fix": "Upload the scope letter or bid instructions if there is one, or state the scope here as an answer.",
        "where": "Every uploaded document was read for scope language.",
    }


def no_scale(sheet_number: str, title: str) -> dict:
    return {
        "title": f"No scale on {sheet_number}",
        "found": f"{sheet_number} ({title}) has no scale in its title block.",
        "why": "Measured runs on this sheet cannot be given a length until a scale is set, and will show as missing information in review.",
        "fix": "Set the scale on the blueprint from the title block, or calibrate against a known dimension.",
        "where": f"{sheet_number}, title block.",
    }


def no_phasing() -> dict:
    return {
        "title": "No phasing was stated",
        "found": "The documents do not name any phase.",
        "why": "A phased job is priced as one estimate per phase, each with its own general conditions and demolition.",
        "fix": "If the bid instructions or the owner split the work into phases, add them here. Otherwise answer that the job is one phase.",
        "where": "Sheet titles, general notes, and the specification were read for phase names.",
    }


def no_schedule() -> dict:
    return {
        "title": "No schedule or legend was found",
        "found": "No sheet in the set is a luminaire, panel, or equipment schedule, and no legend sheet was found.",
        "why": "Without a schedule, fixture and panel types on the plans cannot be matched to a description, and every one will need attention in review.",
        "fix": "Check whether the schedules are on a sheet that was not uploaded, or in the specification, and upload it.",
        "where": "Every sheet in the drawing set.",
    }
```

- [ ] **Step 4: Write `detect.py`**

`api/app/plan/detect.py`:

```python
"""What the plan derives from what the read job stored -- pure functions
over plain values, no database and no file. docs/specs/
project-plan-screen.md, "Derivation".

Keys are what a decision is stored against, so they name the thing
found (a section number, a sheet, a phase label) rather than where in
the text it sat: the same section quoted from a different line next
read keeps its decision. Nothing on a Line or Question says how it was
found."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.plan import copy

CONTEXT_DOC_TYPES = ("Specifications", "Addendum", "Scope", "Other")

# A Division 26/27/28 section number at the start of a line, in any of
# the forms a project manual uses: "26 05 19", "260519", "26-05-19",
# with or without a leading SECTION. The title is the rest of the line,
# or the next non-empty line when the number stands alone.
_SECTION = re.compile(r"^\s*(?:SECTION\s+)?(26|27|28)[\s\-]?(\d\d)[\s\-]?(\d\d)\b[\s\-–—:.]*(.*)$", re.IGNORECASE)

# The schedule headings sheet_kind looks for when it classifies a sheet.
# Spelled here rather than imported: app.plan stays out of app.engine.
SCHEDULE_HEADINGS = ("PANEL SCHEDULE", "LUMINAIRE SCHEDULE", "FIXTURE SCHEDULE", "EQUIPMENT SCHEDULE", "MECHANICAL SCHEDULE")

# "PHASE 1", "Phase A", "PHASE II". The number or letter is required, so
# "the next phase of the work" is not a phase.
_PHASE = re.compile(r"\bPHASE\s+(\d{1,2}|[A-Z]|I{1,3}|IV|V)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DocIn:
    id: str
    filename: str
    doc_type: str
    status: str
    context_text: str
    page_count: int | None


@dataclass(frozen=True)
class SheetIn:
    id: str
    document_id: str
    number: str
    title: str
    kind: str
    page_index: int
    scale: str
    scale_options: tuple
    unreadable_reason: str
    schedule_text: str


@dataclass(frozen=True)
class Place:
    document_id: str
    document_filename: str
    page: int | None
    quote: str


@dataclass
class Line:
    key: str
    kind: str
    text: str
    place: Place
    division: str | None = None
    sheet_number: str | None = None
    places: list[Place] = field(default_factory=list)


@dataclass
class Question:
    key: str
    rule: str
    title: str
    found: str
    why: str
    fix: str
    where: str
    document_id: str | None


def _readable(s: SheetIn) -> bool:
    return not s.unreadable_reason


def _filenames(docs: list[DocIn]) -> dict[str, str]:
    return {d.id: d.filename for d in docs}


def spec_sections(docs: list[DocIn]) -> list[Line]:
    out: list[Line] = []
    for d in docs:
        if d.doc_type not in CONTEXT_DOC_TYPES or d.status != "processed" or not d.context_text:
            continue
        seen: set[str] = set()
        lines = d.context_text.splitlines()
        for i, raw in enumerate(lines):
            m = _SECTION.match(raw)
            if not m:
                continue
            division, a, b, title = m.group(1), m.group(2), m.group(3), m.group(4).strip()
            if not title:
                nxt = next((l.strip() for l in lines[i + 1:i + 3] if l.strip()), "")
                if not nxt or _SECTION.match(nxt):
                    continue
                title = nxt
            number = f"{division}{a}{b}"
            if number in seen:
                continue
            seen.add(number)
            out.append(Line(
                key=f"spec:{d.id}:{number}", kind="spec_section",
                text=f"{division} {a} {b} — {title.rstrip(' .:-')}",
                place=Place(d.id, d.filename, None, raw.strip()[:600]), division=division,
            ))
    return out


def _heading_label(heading: str) -> str:
    return heading[0] + heading[1:].lower()


def schedules(sheets: list[SheetIn], docs: list[DocIn]) -> list[Line]:
    names = _filenames(docs)
    out: list[Line] = []
    for s in sheets:
        if not _readable(s):
            continue
        fn = names.get(s.document_id, "")
        page = s.page_index + 1
        if s.kind in ("schedule", "legend"):
            out.append(Line(key=f"schedule:sheet:{s.id}", kind="schedule", text=s.title,
                            place=Place(s.document_id, fn, page, s.title), sheet_number=s.number))
            continue
        upper = s.schedule_text.upper()
        for heading in SCHEDULE_HEADINGS:
            if heading in upper:
                quote = next((l.strip() for l in s.schedule_text.splitlines() if heading in l.upper()), heading)
                out.append(Line(key=f"schedule:heading:{s.id}:{heading}", kind="schedule",
                                text=f"{_heading_label(heading)} on {s.number}",
                                place=Place(s.document_id, fn, page, quote[:600]), sheet_number=s.number))
    return out


def normalise_phase(label: str) -> str:
    return "PHASE " + label.strip().upper()


def phase_display(norm: str) -> str:
    return "Phase " + norm[len("PHASE "):]


def _phase_key(norm: str) -> tuple:
    token = norm[len("PHASE "):]
    return (0, int(token)) if token.isdigit() else (1, token)


def phases(sheets: list[SheetIn], docs: list[DocIn]) -> list[Line]:
    names = _filenames(docs)
    found: dict[str, list[Place]] = {}

    def add(label: str, place: Place) -> None:
        found.setdefault(normalise_phase(label), []).append(place)

    for s in sheets:
        if not _readable(s):
            continue
        fn = names.get(s.document_id, "")
        page = s.page_index + 1
        for m in _PHASE.finditer(s.title):
            add(m.group(1), Place(s.document_id, fn, page, s.title))
        for raw in s.schedule_text.splitlines():
            for m in _PHASE.finditer(raw):
                add(m.group(1), Place(s.document_id, fn, page, raw.strip()[:600]))
    for d in docs:
        if d.doc_type not in CONTEXT_DOC_TYPES or d.status != "processed":
            continue
        for raw in d.context_text.splitlines():
            for m in _PHASE.finditer(raw):
                add(m.group(1), Place(d.id, d.filename, None, raw.strip()[:600]))

    out = []
    for norm in sorted(found, key=_phase_key):
        places = []
        for p in found[norm]:
            if p not in places:
                places.append(p)
        out.append(Line(key=f"phase:{norm}", kind="phase", text=phase_display(norm), place=places[0], places=places))
    return out


def questions(sheets: list[SheetIn], docs: list[DocIn], *, scope_count: int, phase_count: int, schedule_count: int) -> list[Question]:
    out: list[Question] = []
    processed = [d for d in docs if d.status == "processed"]
    drawings = [d for d in processed if d.doc_type == "Drawings"]

    for d in drawings:
        pages = [s for s in sheets if s.document_id == d.id]
        unreadable = [s for s in pages if not _readable(s)]
        if unreadable:
            total = d.page_count if d.page_count else len(pages)
            out.append(Question(key=f"question:scanned:{d.id}", rule="scanned", document_id=d.id,
                                **copy.scanned(d.filename, len(unreadable), total)))

    if drawings and not any(d.doc_type == "Specifications" for d in processed):
        out.append(Question(key="question:no_specs:project", rule="no_specs", document_id=None, **copy.no_specs()))
    if processed and scope_count == 0:
        out.append(Question(key="question:no_scope:project", rule="no_scope", document_id=None, **copy.no_scope()))

    for s in sheets:
        if s.kind == "plan" and _readable(s) and not s.scale and not s.scale_options:
            out.append(Question(key=f"question:no_scale:{s.id}", rule="no_scale", document_id=s.document_id,
                                **copy.no_scale(s.number, s.title)))

    readable_plans = any(s.kind == "plan" and _readable(s) for s in sheets)
    if readable_plans and phase_count == 0:
        out.append(Question(key="question:no_phasing:project", rule="no_phasing", document_id=None, **copy.no_phasing()))
    if readable_plans and schedule_count == 0:
        out.append(Question(key="question:no_schedule:project", rule="no_schedule", document_id=None, **copy.no_schedule()))
    return out
```

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_detect.py -q`
Expected: all pass. If `test_each_number_form_is_one_section` fails on the `28 31 00` line, the next-line lookahead is wrong — it must skip blank lines and take `FIRE DETECTION AND ALARM`.

- [ ] **Step 6: Commit**

```bash
git add api/app/plan/detect.py api/app/plan/copy.py api/tests/test_plan_detect.py
git commit -m "Plan: derive spec sections, schedules, phases and open questions from what the read job stored

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Corpus assertions

**Files:**
- Test: `api/tests/test_plan_corpus.py`

**Interfaces:**
- Consumes: `app.engine.documents.read(path, doc_type) -> DocumentReading` (`.sheets: list[DetectedSheet]` with `page_index, number, title, kind, scale, unreadable_reason, schedule_text`; `.context_text`; `.page_count`; `.scope`), `tests/bid_set.py`'s `RASTER_SETS`, `VECTOR_SETS`, `corpus_path`. Task 2's `detect` functions.

- [ ] **Step 1: Write the test**

`api/tests/test_plan_corpus.py`:

```python
"""What the plan says about the real bid sets. Both raster sets produce
nothing but the scanned question; a vector set produces schedules; a set
with a specification produces Division 26 sections. Runs the engine's
read in-process, as test_corpus_sheets.py does, then feeds the stored
shapes into the plan's derivation."""

import os

import pytest

from app.plan.detect import DocIn, SheetIn, phases, questions, schedules, spec_sections
from tests.bid_set import RASTER_SETS, VECTOR_SETS, corpus_path


def _read(rel, doc_type):
    path = corpus_path(rel)
    if not os.path.exists(path):
        pytest.skip(f"corpus set not present: {rel}")
    from app.engine import documents
    reading = documents.read(path, doc_type)
    doc = DocIn(id="d", filename=os.path.basename(path), doc_type=doc_type, status="processed",
                context_text=reading.context_text, page_count=reading.page_count)
    sheets = [SheetIn(id=f"s{s.page_index}", document_id="d", number=s.number, title=s.title, kind=s.kind,
                      page_index=s.page_index, scale=s.scale, scale_options=(), unreadable_reason=s.unreadable_reason,
                      schedule_text=s.schedule_text) for s in reading.sheets]
    return doc, sheets, reading


@pytest.mark.parametrize("name", sorted(RASTER_SETS))
def test_a_scanned_set_is_one_question_and_nothing_else(name):
    doc, sheets, reading = _read(RASTER_SETS[name], "Drawings")
    assert schedules(sheets, [doc]) == [] and phases(sheets, [doc]) == []
    qs = questions(sheets, [doc], scope_count=len(reading.scope), phase_count=0, schedule_count=0)
    assert [q.rule for q in qs] == ["scanned", "no_specs", "no_scope"]
    assert qs[0].found.startswith(f"{len(sheets)} of {reading.page_count} pages")


def test_unalaska_has_a_schedule_and_no_scanned_question():
    doc, sheets, _ = _read(VECTOR_SETS["unalaska"], "Drawings")
    assert schedules(sheets, [doc]), "the Unalaska set carries luminaire and panel schedules"
    assert not [q for q in questions(sheets, [doc], scope_count=1, phase_count=0, schedule_count=1) if q.rule == "scanned"]


def test_a_specification_yields_division_26_sections():
    folder = corpus_path("Kittles Saxony/SPECS")
    if not os.path.isdir(folder):
        pytest.skip("corpus set not present: Kittles Saxony/SPECS")
    pdfs = [f for f in sorted(os.listdir(folder)) if f.lower().endswith(".pdf")]
    if not pdfs:
        pytest.skip("no spec PDF in Kittles Saxony/SPECS")
    found = []
    for f in pdfs:
        doc, _, _ = _read(f"Kittles Saxony/SPECS/{f}", "Specifications")
        found += spec_sections([doc])
    assert any(l.division == "26" for l in found), [l.text for l in found]
```

- [ ] **Step 2: Run it**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_corpus.py -q -p no:cacheprovider`
Expected: three pass (or skip where a set is absent). The read of a full set takes tens of seconds; that is normal for the corpus tests.

If the Kittles spec produces no Division 26 section, print `doc.context_text[:2000]` in the test to see the heading form the manual uses and extend `_SECTION` in `detect.py` for it (then re-run `test_plan_detect.py`). The most common miss is a title line like `SECTION 260519` with the title on the following line, which the lookahead already covers.

- [ ] **Step 3: Commit**

```bash
git add api/tests/test_plan_corpus.py api/app/plan/detect.py
git commit -m "Plan: corpus assertions — scanned sets ask one question, vector sets find schedules and spec sections

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Wire shapes, `build_plan`, and `GET /plan`

**Files:**
- Create: `api/app/plan/schemas.py`, `api/app/plan/service.py`, `api/app/plan/router.py`
- Modify (append): `api/app/main.py` (one import line next to the other router imports, one `include_router` line after `app.include_router(conversation_router)`), `api/tests/test_tenancy.py` (rows at the end of `TENANCY_TABLE`)
- Test: `api/tests/test_plan_api.py`

**Interfaces:**
- Consumes: Task 1 models; Task 2 `detect` + `copy`; `app.scope.service.list_statements(db, project)`; `app.scope.router._out(statement, filename)`; `app.takeoff.router.load_project`, `not_found`; `app.takeoff.models.Document, Sheet, Project`.
- Produces: `service.build_plan(db, project) -> PlanOut`; `service.LineNotFound` is not a class — a missing key raises `not_found()`; the wire shapes below, used by Tasks 5–7 and the client.

- [ ] **Step 1: Write the failing tests**

`api/tests/test_plan_api.py` (this file grows in Tasks 5–7; start it here):

```python
"""The plan routes. The plan is derived on every GET from what the read
job stored; only decisions and stated phases persist. Nothing on the
wire names how a line was produced."""

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.plan.models import PlanDecision, PlanPhase
from app.takeoff.models import Action, Document, Note, ScopeStatement, Sheet

SPEC_TEXT = "SECTION 26 05 19 - LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES\nPhase 2 work follows.\n"


def _doc(db, project, dana, filename="Spec.pdf", doc_type="Specifications", status="processed", context_text="", page_count=4):
    d = Document(project_id=project.id, filename=filename, doc_type=doc_type, content_type="application/pdf", size_bytes=1,
                 sha256=uuid.uuid4().hex * 2, storage_key="k", uploaded_by=dana.id, status=status,
                 context_text=context_text, page_count=page_count)
    db.add(d); db.flush(); return d


def _sheet(db, project, doc, **over):
    fields = dict(project_id=project.id, number="E2.1", title="Power plan", discipline="Electrical", revision="",
                  scale='1/8" = 1\'-0"', scale_options=[], plan="", takeoff_id=str(doc.id), page_index=0, kind="plan",
                  unreadable_reason="", schedule_text="")
    fields.update(over)
    s = Sheet(**fields)
    db.add(s); db.flush(); return s


def _scope(db, project, doc, **over):
    fields = dict(org_id=project.org_id, project_id=project.id, document_id=doc.id, page_index=1, kind="excluded",
                  text="Site lighting.", quote="- Site lighting.", status="found", run_id=uuid.uuid4())
    fields.update(over)
    s = ScopeStatement(**fields)
    db.add(s); db.flush(); return s


@pytest.fixture
def seeded(db, project, dana):
    """A project with one spec, one drawing set of three sheets (a
    schedule, a plan with a phase in its title, a plan with no scale),
    and one scope statement."""
    spec = _doc(db, project, dana, context_text=SPEC_TEXT)
    drawings = _doc(db, project, dana, filename="E-set.pdf", doc_type="Drawings", page_count=3)
    sched = _sheet(db, project, drawings, number="E0.1", title="Luminaire schedule", kind="schedule", page_index=0, scale="")
    p1 = _sheet(db, project, drawings, number="E2.1", title="Phase 1 power plan", page_index=1)
    p2 = _sheet(db, project, drawings, number="E2.2", title="Lighting plan", page_index=2, scale="")
    scope = _scope(db, project, drawings)
    return dict(spec=spec, drawings=drawings, sched=sched, p1=p1, p2=p2, scope=scope)


def test_get_assembles_every_section(client, db, project, dana, signed_in_user, seeded):
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["reading"] is False and plan["has_drawings"] is True and plan["read_at"] is not None
    assert [s["text"] for s in plan["scope"]] == ["Site lighting."]
    assert [s["text"] for s in plan["specs"]] == ["26 05 19 — LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES"]
    assert plan["specs"][0]["page"] is None and plan["specs"][0]["document_filename"] == "Spec.pdf"
    assert [s["text"] for s in plan["schedules"]] == ["Luminaire schedule"]
    assert plan["schedules"][0]["page"] == 1 and plan["schedules"][0]["sheet_number"] == "E0.1"
    assert [p["text"] for p in plan["phases"]] == ["Phase 1", "Phase 2"]
    assert plan["phases"][0]["places"][0]["quote"] == "Phase 1 power plan"
    assert [q["key"] for q in plan["questions"]] == [f"question:no_scale:{seeded['p2'].id}"]
    assert plan["undecided"] == 1 + 1 + 1 + 2 + 1  # scope + spec + schedule + phases + question
    for line in plan["specs"] + plan["schedules"] + plan["phases"]:
        assert line["status"] == "found" and line["edited_text"] is None and line["found_text"] == line["text"]
    assert not any(w in json.dumps(plan).lower() for w in ("attempt", "llm", "confidence", "model", "run_id", "rule"))


def test_get_on_a_scanned_set_is_one_question_per_document(client, db, project, dana, signed_in_user):
    d = _doc(db, project, dana, filename="Gerber.pdf", doc_type="Drawings", page_count=2)
    _sheet(db, project, d, number="", title="Scanned sheet", kind="other", page_index=0, unreadable_reason="scan", scale="")
    _sheet(db, project, d, number="", title="Scanned sheet", kind="other", page_index=1, unreadable_reason="scan", scale="")
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["specs"] == [] and plan["schedules"] == [] and plan["phases"] == []
    rules = [q["title"] for q in plan["questions"]]
    assert rules[0] == "Pages that could not be read"
    assert plan["questions"][0]["found"].startswith("2 of 2 pages in Gerber.pdf")
    for q in plan["questions"]:
        assert q["title"] and q["found"] and q["why"] and q["fix"] and q["where"]


def test_get_reports_reading_while_a_drawing_set_is_still_being_read(client, db, project, dana, signed_in_user):
    _doc(db, project, dana, filename="E.pdf", doc_type="Drawings", status="processing")
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["reading"] is True and plan["has_drawings"] is True


def test_get_moves_the_stage_to_plan_once_and_never_backward(client, db, project, dana, signed_in_user, seeded):
    assert project.stage == "setup"
    client.get(f"/api/projects/{project.id}/plan")
    db.refresh(project)
    assert project.stage == "plan"
    project.stage = "review"; db.flush()
    client.get(f"/api/projects/{project.id}/plan")
    db.refresh(project)
    assert project.stage == "review"


def test_get_does_not_move_the_stage_while_drawings_are_reading(client, db, project, dana, signed_in_user):
    _doc(db, project, dana, filename="E.pdf", doc_type="Drawings", status="processing")
    client.get(f"/api/projects/{project.id}/plan")
    db.refresh(project)
    assert project.stage == "setup"
```

- [ ] **Step 2: Run to see it fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_api.py -q`
Expected: 404s (route absent).

- [ ] **Step 3: Write `schemas.py`**

`api/app/plan/schemas.py`:

```python
"""Wire shapes for the project plan. snake_case, like scope and notes.

`status` is a plan line's own vocabulary -- found, confirmed, dismissed,
and for a question answered -- never the four review labels (CLAUDE.md:
a note's status is not an item's status). Nothing here names how a line
was produced: no rule, source, attempt, model, confidence, or run id
reaches the wire."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.scope.schemas import ScopeStatementOut

PLAN_STATUSES = ("found", "confirmed", "dismissed", "answered")
LINE_STATUSES = ("found", "confirmed", "dismissed")


class PlaceOut(BaseModel):
    document_id: uuid.UUID | None
    document_filename: str
    page: int | None
    quote: str


class PlanLineOut(BaseModel):
    key: str
    kind: str
    text: str
    found_text: str
    edited_text: str | None
    status: str
    document_id: uuid.UUID | None
    document_filename: str | None
    page: int | None
    quote: str | None
    division: str | None = None
    sheet_number: str | None = None
    added: bool = False
    phase_id: uuid.UUID | None = None
    places: list[PlaceOut] = Field(default_factory=list)


class QuestionOut(BaseModel):
    key: str
    status: str
    title: str = Field(min_length=1)
    found: str = Field(min_length=1)
    why: str = Field(min_length=1)
    fix: str = Field(min_length=1)
    where: str = Field(min_length=1)
    document_id: uuid.UUID | None
    document_filename: str | None
    note_id: uuid.UUID | None


class PlanOut(BaseModel):
    read_at: datetime | None
    reading: bool
    has_drawings: bool
    undecided: int
    scope: list[ScopeStatementOut]
    specs: list[PlanLineOut]
    schedules: list[PlanLineOut]
    phases: list[PlanLineOut]
    questions: list[QuestionOut]


class LineDecisionIn(BaseModel):
    """Exactly one of the two; service.decide enforces it with the
    estimator-facing sentence, the way scope.service.decide does."""

    status: str | None = None
    edited_text: str | None = None


class AnswerIn(BaseModel):
    body: str = ""


class PhaseIn(BaseModel):
    name: str = ""
```

- [ ] **Step 4: Write `service.py` with `build_plan`**

`api/app/plan/service.py`:

```python
"""The project plan: derived lines with the decisions a person made on
them. build_plan is the one place the plan is assembled; every write
goes through actions.commit() and none is undoable (docs/specs/
project-plan-screen.md, "Audited, not undoable")."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.plan import detect
from app.plan.models import PlanDecision, PlanPhase
from app.plan.schemas import PlaceOut, PlanLineOut, PlanOut, QuestionOut
from app.scope import service as scope_service
from app.scope.router import _out as scope_out
from app.takeoff import actions
from app.takeoff.models import Document, Note, Project, Sheet
from app.takeoff.router import not_found

_MAX_TEXT = 500
_MAX_PHASE = 100


def _inputs(db: DbSession, project: Project) -> tuple[list[detect.DocIn], list[detect.SheetIn], list[Document]]:
    docs = list(db.scalars(select(Document).where(Document.project_id == project.id).order_by(Document.created_at)))
    doc_in = [detect.DocIn(id=str(d.id), filename=d.filename, doc_type=d.doc_type, status=d.status,
                           context_text=d.context_text or "", page_count=d.page_count) for d in docs]
    sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id, Sheet.superseded_at.is_(None))
                             .order_by(Sheet.sort_order, Sheet.page_index)))
    sheet_in = [detect.SheetIn(id=str(s.id), document_id=s.takeoff_id, number=s.number, title=s.title, kind=s.kind,
                               page_index=s.page_index, scale=s.scale or "", scale_options=tuple(s.scale_options or ()),
                               unreadable_reason=s.unreadable_reason or "", schedule_text=s.schedule_text or "")
                for s in sheets]
    return doc_in, sheet_in, docs


def _decisions(db: DbSession, project: Project) -> dict[str, PlanDecision]:
    return {d.entry_key: d for d in db.scalars(select(PlanDecision).where(PlanDecision.project_id == project.id))}


def _uuid_or_none(value: str) -> uuid.UUID | None:
    """A sheet's takeoff_id is the document id as text; a sheet created
    outside the read job (a fixture, an older row) may carry none."""
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


def _line_out(line: detect.Line, decision: PlanDecision | None) -> PlanLineOut:
    status = decision.status if decision and decision.status in ("found", "confirmed", "dismissed") else "found"
    edited = decision.edited_text if decision else None
    return PlanLineOut(
        key=line.key, kind=line.kind, text=edited or line.text, found_text=line.text, edited_text=edited, status=status,
        document_id=_uuid_or_none(line.place.document_id), document_filename=line.place.document_filename,
        page=line.place.page, quote=line.place.quote, division=line.division, sheet_number=line.sheet_number,
        places=[PlaceOut(document_id=_uuid_or_none(p.document_id), document_filename=p.document_filename, page=p.page, quote=p.quote)
                for p in line.places],
    )


def _added_phase_out(phase: PlanPhase, decision: PlanDecision | None) -> PlanLineOut:
    status = decision.status if decision and decision.status in ("found", "confirmed", "dismissed") else "found"
    edited = decision.edited_text if decision else None
    return PlanLineOut(key=f"phase:added:{phase.id}", kind="phase", text=edited or phase.name, found_text=phase.name,
                       edited_text=edited, status=status, document_id=None, document_filename=None, page=None, quote=None,
                       added=True, phase_id=phase.id)


def _question_out(q: detect.Question, decision: PlanDecision | None, filenames: dict[str, str]) -> QuestionOut:
    status = "found"
    note_id = None
    if decision:
        if decision.status == "answered" and decision.note_id is not None:
            status, note_id = "answered", decision.note_id
        elif decision.status == "dismissed":
            status = "dismissed"
    return QuestionOut(key=q.key, status=status, title=q.title, found=q.found, why=q.why, fix=q.fix, where=q.where,
                       document_id=_uuid_or_none(q.document_id) if q.document_id else None,
                       document_filename=filenames.get(q.document_id) if q.document_id else None, note_id=note_id)


def derive(db: DbSession, project: Project):
    """Everything derived, before decisions are applied. Shared by
    build_plan and the write paths, which need to know whether a key
    still exists."""
    doc_in, sheet_in, docs = _inputs(db, project)
    scope = scope_service.list_statements(db, project)
    specs = detect.spec_sections(doc_in)
    scheds = detect.schedules(sheet_in, doc_in)
    phase_lines = detect.phases(sheet_in, doc_in)
    added = list(db.scalars(select(PlanPhase).where(PlanPhase.project_id == project.id).order_by(PlanPhase.created_at)))
    qs = detect.questions(sheet_in, doc_in, scope_count=len(scope), phase_count=len(phase_lines) + len(added),
                          schedule_count=len(scheds))
    return docs, scope, specs, scheds, phase_lines, added, qs


def build_plan(db: DbSession, project: Project) -> PlanOut:
    docs, scope, specs, scheds, phase_lines, added, qs = derive(db, project)
    decisions = _decisions(db, project)
    filenames = {str(d.id): d.filename for d in docs}

    drawings = [d for d in docs if d.doc_type == "Drawings"]
    reading = any(d.status in ("uploaded", "processing") for d in drawings)
    processed = [d for d in docs if d.status == "processed"]
    read_at = max((d.created_at for d in processed), default=None)

    out = PlanOut(
        read_at=read_at, reading=reading, has_drawings=bool(drawings), undecided=0,
        scope=[scope_out(s, filenames.get(str(s.document_id), "")) for s in scope],
        specs=[_line_out(l, decisions.get(l.key)) for l in specs],
        schedules=[_line_out(l, decisions.get(l.key)) for l in scheds],
        phases=[_line_out(l, decisions.get(l.key)) for l in phase_lines]
               + [_added_phase_out(p, decisions.get(f"phase:added:{p.id}")) for p in added],
        questions=[_question_out(q, decisions.get(q.key), filenames) for q in qs],
    )
    out.undecided = (sum(1 for s in out.scope if s.status == "found")
                     + sum(1 for l in out.specs + out.schedules + out.phases if l.status == "found")
                     + sum(1 for q in out.questions if q.status == "found"))

    # The stage moves forward once, here, because this is the one place
    # that knows the project has reached the plan. Never backward.
    if project.stage in ("setup", "documents") and drawings and not reading and any(d.status == "processed" for d in drawings):
        project.stage = "plan"
        db.flush()
    return out
```

- [ ] **Step 5: Write `router.py` with the GET, and mount it**

`api/app/plan/router.py`:

```python
"""Thin HTTP layer for the project plan. router -> service -> models.
Every route goes through load_project first, so a rival org's probe is
refused with project_not_found before any key is looked at."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.identity.models import User
from app.plan import service
from app.plan.schemas import AnswerIn, LineDecisionIn, PhaseIn, PlanLineOut, PlanOut, QuestionOut
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["plan"])


@router.get("/projects/{project_id}/plan", response_model=PlanOut)
def get_plan(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> PlanOut:
    project = load_project(project_id, db, user)
    plan = service.build_plan(db, project)
    db.commit()
    return plan
```

In `api/app/main.py`: find the block of router imports (the line importing `conversation_router`) and append, on the line after it:

```python
from app.plan.router import router as plan_router
```

and after `app.include_router(conversation_router)` append:

```python
app.include_router(plan_router)
```

Append to `TENANCY_TABLE` in `api/tests/test_tenancy.py` (before the closing `]`; these are the last rows — Tasks 5–7 add nothing more here because all five rows go in now):

```python
    ("GET", "/api/projects/{project_id}/plan",
     lambda p, s, i: f"/api/projects/{p.id}/plan", None, None),
    ("PATCH", "/api/projects/{project_id}/plan/lines/{key}",
     lambda p, s, i: f"/api/projects/{p.id}/plan/lines/spec:x:260519", lambda p, s, i: {"status": "confirmed"}, None),
    ("POST", "/api/projects/{project_id}/plan/questions/{key}/answer",
     lambda p, s, i: f"/api/projects/{p.id}/plan/questions/question:no_specs:project/answer", lambda p, s, i: {"body": "One phase."}, None),
    ("POST", "/api/projects/{project_id}/plan/phases",
     lambda p, s, i: f"/api/projects/{p.id}/plan/phases", lambda p, s, i: {"name": "Phase 2"}, None),
    ("DELETE", "/api/projects/{project_id}/plan/phases/{phase_id}",
     lambda p, s, i: f"/api/projects/{p.id}/plan/phases/{uuid.uuid4()}", None, None),
```

(Check `uuid` is imported at the top of `test_tenancy.py` — it is, the `scope_statement` fixture uses it.) The tenancy guard test compares templates against `app.routes`, so the four routes not yet written will fail that guard until Tasks 5–7 land — run the guard only at the end of Task 7. If the guard complains earlier, that is expected.

- [ ] **Step 6: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_api.py tests/test_scope_api.py tests/test_api_import_boundary.py -q`
Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add api/app/plan/schemas.py api/app/plan/service.py api/app/plan/router.py api/app/main.py api/tests/test_plan_api.py api/tests/test_tenancy.py
git commit -m "Plan: GET /projects/{id}/plan assembles scope, specs, schedules, phases and questions from what was read

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Deciding a line — `PATCH /plan/lines/{key}`

**Files:**
- Modify: `api/app/plan/service.py` (add `decide`), `api/app/plan/router.py` (add the route)
- Test: `api/tests/test_plan_api.py` (append)

**Interfaces:**
- Produces: `service.decide(db, *, actor, project, key, status=None, edited_text=None) -> PlanLineOut | QuestionOut`. Raises `not_found()` for a key the current derivation does not produce (a scope statement id included); `DomainError(422)` for a bad body.

- [ ] **Step 1: Append the failing tests**

Append to `api/tests/test_plan_api.py`:

```python
# --- deciding a line ---

def _key(client, project, section, index=0):
    return client.get(f"/api/projects/{project.id}/plan").json()[section][index]["key"]


def test_confirm_correct_dismiss_and_reopen_are_audited_and_not_undoable(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "specs")
    url = f"/api/projects/{project.id}/plan/lines/{key}"
    assert client.patch(url, json={"status": "confirmed"}).json()["status"] == "confirmed"
    r = client.patch(url, json={"edited_text": "26 05 19 — Conductors and cables"}).json()
    assert r["edited_text"] == "26 05 19 — Conductors and cables" and r["text"] == r["edited_text"] and r["found_text"].endswith("CABLES")
    assert client.patch(url, json={"status": "dismissed"}).json()["status"] == "dismissed"
    assert client.patch(url, json={"status": "found"}).json()["status"] == "found"
    labels = [a.label for a in db.scalars(select(Action).where(Action.kind == "plan_decide").order_by(Action.seq))]
    assert labels == [
        "Confirmed: 26 05 19 — LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES",
        "Changed: 26 05 19 — Conductors and cables",
        "Dismissed: 26 05 19 — Conductors and cables",
        "Reopened: 26 05 19 — Conductors and cables",
    ]
    [row] = db.scalars(select(PlanDecision).where(PlanDecision.project_id == project.id))
    assert row.entry_key == key and row.decided_by == dana.id and row.status == "found"
    # Not undoable: the undo endpoint finds nothing to reverse.
    undo = client.post(f"/api/projects/{project.id}/undo")
    assert undo.status_code in (200, 409)
    assert not any(a.kind == "undo" for a in db.scalars(select(Action).where(Action.project_id == project.id)))


def test_a_decision_shows_on_the_next_get_and_counts_as_decided(client, db, project, dana, signed_in_user, seeded):
    before = client.get(f"/api/projects/{project.id}/plan").json()["undecided"]
    key = _key(client, project, "schedules")
    client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"status": "confirmed"})
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["schedules"][0]["status"] == "confirmed" and plan["undecided"] == before - 1


def test_a_question_can_be_dismissed_through_the_same_route(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    r = client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"status": "dismissed"})
    assert r.status_code == 200 and r.json()["status"] == "dismissed" and r.json()["title"]
    assert client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"edited_text": "x"}).status_code == 422


def test_bad_bodies_and_stale_keys_are_refused(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "specs")
    url = f"/api/projects/{project.id}/plan/lines/{key}"
    assert client.patch(url, json={}).status_code == 422
    assert client.patch(url, json={"status": "confirmed", "edited_text": "x"}).status_code == 422
    assert client.patch(url, json={"status": "approved"}).status_code == 422
    assert client.patch(url, json={"edited_text": "   "}).status_code == 422
    assert client.patch(url, json={"edited_text": "x" * 501}).status_code == 422
    assert client.patch(f"/api/projects/{project.id}/plan/lines/spec:gone:000000", json={"status": "confirmed"}).status_code == 404
    assert client.patch(f"/api/projects/{project.id}/plan/lines/{seeded['scope'].id}", json={"status": "confirmed"}).status_code == 404


def test_a_decision_survives_a_re_read_that_finds_the_same_line(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "specs")
    client.patch(f"/api/projects/{project.id}/plan/lines/{key}", json={"status": "confirmed"})
    seeded["spec"].context_text = "260519 LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES (reissued)\n"
    db.flush()
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["specs"][0]["key"] == key and plan["specs"][0]["status"] == "confirmed"
    seeded["spec"].context_text = ""
    db.flush()
    assert client.get(f"/api/projects/{project.id}/plan").json()["specs"] == []
```

- [ ] **Step 2: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_api.py -q -k "decid or dismiss or refused or survives"`
Expected: 404/405.

- [ ] **Step 3: Add `decide` to `service.py`**

Append to `api/app/plan/service.py`:

```python
def _find_line(db: DbSession, project: Project, key: str):
    """The derived line or question behind a key, or not_found(). A
    scope statement id is not a key: scope has its own write path."""
    docs, _scope, specs, scheds, phase_lines, added, qs = derive(db, project)
    for line in specs + scheds + phase_lines:
        if line.key == key:
            return "line", line, docs
    for phase in added:
        if f"phase:added:{phase.id}" == key:
            return "added", phase, docs
    for q in qs:
        if q.key == key:
            return "question", q, docs
    raise not_found()


def _decision_row(db: DbSession, project: Project, key: str) -> PlanDecision:
    row = db.scalar(select(PlanDecision).where(PlanDecision.project_id == project.id, PlanDecision.entry_key == key))
    if row is None:
        row = PlanDecision(project_id=project.id, entry_key=key, status="found")
        db.add(row)
    return row


def _snapshot(row: PlanDecision) -> dict:
    return {"status": row.status, "edited_text": row.edited_text, "note_id": str(row.note_id) if row.note_id else None}


def decide(db: DbSession, *, actor: User, project: Project, key: str, status: str | None = None,
           edited_text: str | None = None):
    if (status is None) == (edited_text is None):
        raise DomainError("invalid_plan_decision", "Send either a status or a corrected line, not both and not neither.", status=422)
    what, target, docs = _find_line(db, project, key)
    if what == "question" and edited_text is not None:
        raise DomainError("invalid_plan_decision", "A question can be answered or dismissed, not reworded.", status=422)
    if status is not None and status not in ("found", "confirmed", "dismissed"):
        raise DomainError("invalid_plan_status", "Status must be one of found, confirmed, dismissed.", status=422)

    row = _decision_row(db, project, key)
    before = _snapshot(row)
    if what == "question":
        shown = target.title
    else:
        found_text = target.name if what == "added" else target.text
        shown = row.edited_text or found_text

    if status is not None:
        row.status = status
        if what == "question":
            row.note_id = None
        label = {"confirmed": f"Confirmed: {shown}", "dismissed": f"Dismissed: {shown}", "found": f"Reopened: {shown}"}[status]
    else:
        cleaned = edited_text.strip()
        if not cleaned or len(cleaned) > _MAX_TEXT:
            raise DomainError("invalid_plan_text", f"The corrected line can't be empty and must be {_MAX_TEXT} characters or fewer.", status=422)
        row.edited_text = cleaned
        label = f"Changed: {cleaned}"

    row.decided_by = actor.id
    row.decided_at = datetime.now(timezone.utc)
    db.flush()
    actions.commit(db, actor=actor, project_id=project.id, kind="plan_decide", label=label, before=before, after=_snapshot(row))

    filenames = {str(d.id): d.filename for d in docs}
    if what == "question":
        return _question_out(target, row, filenames)
    if what == "added":
        return _added_phase_out(target, row)
    return _line_out(target, row)
```

- [ ] **Step 4: Add the route**

Append to `api/app/plan/router.py`:

```python
@router.patch("/projects/{project_id}/plan/lines/{key}", response_model=PlanLineOut | QuestionOut)
def patch_line(project_id: uuid.UUID, key: str, payload: LineDecisionIn, user: User = Depends(current_user),
               db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    out = service.decide(db, actor=user, project=project, key=key, status=payload.status, edited_text=payload.edited_text)
    db.commit()
    return out
```

If FastAPI refuses the union `response_model`, drop `response_model` from this route and return `out.model_dump(mode="json")` instead.

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_api.py -q`
Expected: pass. If `test_confirm_..._not_undoable` fails on the undo status code, read `api/app/takeoff/undo.py`'s route to see what it answers when there is nothing to undo and adjust the accepted codes — the assertion that matters is that no `undo` action was written.

- [ ] **Step 6: Commit**

```bash
git add api/app/plan/service.py api/app/plan/router.py api/tests/test_plan_api.py
git commit -m "Plan: confirm, correct, dismiss or reopen a line — audited as plan_decide, keyed so it survives a re-read

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Answering a question — `POST /plan/questions/{key}/answer`

**Files:**
- Modify: `api/app/plan/service.py` (add `answer`), `api/app/plan/router.py`
- Test: `api/tests/test_plan_api.py` (append)

**Interfaces:**
- Consumes: `app.takeoff.notes.create_note(db, *, actor, project, fields: dict) -> Note` (fields are `NoteCreateIn`'s: `scope, title, body, category, status, rfi_needed, usage, source_ref, obsolete_after_revision`).
- Produces: `service.answer(db, *, actor, project, key, body) -> QuestionOut`.

- [ ] **Step 1: Append the failing tests**

```python
# --- answering a question ---

def test_an_answer_becomes_a_context_note_and_marks_the_question(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    r = client.post(f"/api/projects/{project.id}/plan/questions/{key}/answer", json={"body": "Use 1/8 inch, same as E2.1."})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "answered" and out["note_id"]
    note = db.get(Note, uuid.UUID(out["note_id"]))
    assert note.usage == "context" and note.scope == "project" and note.status == "confirmed"
    assert note.title == out["title"] and note.body == "Use 1/8 inch, same as E2.1." and note.source_ref == out["where"]
    assert note.category == "existing_condition"
    kinds = [a.kind for a in db.scalars(select(Action).where(Action.project_id == project.id).order_by(Action.seq))]
    assert kinds == ["note_add", "plan_decide"]
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["questions"][0]["status"] == "answered" and plan["undecided"] == 5


def test_deleting_the_note_reopens_the_question(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    out = client.post(f"/api/projects/{project.id}/plan/questions/{key}/answer", json={"body": "One phase."}).json()
    assert client.delete(f"/api/notes/{out['note_id']}").status_code == 204
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert plan["questions"][0]["status"] == "found" and plan["questions"][0]["note_id"] is None


def test_an_empty_answer_and_a_line_key_are_refused(client, db, project, dana, signed_in_user, seeded):
    key = _key(client, project, "questions")
    assert client.post(f"/api/projects/{project.id}/plan/questions/{key}/answer", json={"body": "  "}).status_code == 422
    spec_key = _key(client, project, "specs")
    assert client.post(f"/api/projects/{project.id}/plan/questions/{spec_key}/answer", json={"body": "x"}).status_code == 404


def test_the_note_category_follows_the_question(client, db, project, dana, signed_in_user):
    d = _doc(db, project, dana, filename="Gerber.pdf", doc_type="Drawings", page_count=1)
    _sheet(db, project, d, number="", title="Scanned sheet", kind="other", unreadable_reason="scan", scale="")
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    scanned = next(q for q in plan["questions"] if q["title"] == "Pages that could not be read")
    out = client.post(f"/api/projects/{project.id}/plan/questions/{scanned['key']}/answer", json={"body": "Two phases: shop, office."}).json()
    assert db.get(Note, uuid.UUID(out["note_id"])).category == "customer_instruction"
```

- [ ] **Step 2: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_api.py -q -k answer`
Expected: 404/405.

- [ ] **Step 3: Add `answer` to `service.py`**

Append:

```python
from app.takeoff import notes as notes_service  # noqa: E402 -- keep with the other imports at the top of the file when editing

_NOTE_CATEGORY = {
    "scanned": "customer_instruction", "no_specs": "customer_instruction", "no_scope": "customer_instruction",
    "no_phasing": "customer_instruction", "no_scale": "existing_condition", "no_schedule": "existing_condition",
}


def answer(db: DbSession, *, actor: User, project: Project, key: str, body: str) -> QuestionOut:
    cleaned = (body or "").strip()
    if not cleaned:
        raise DomainError("invalid_plan_answer", "Write the answer before saving it.", status=422)
    what, target, docs = _find_line(db, project, key)
    if what != "question":
        raise not_found()

    note = notes_service.create_note(db, actor=actor, project=project, fields={
        "scope": "project", "scope_ref": None, "title": target.title[:300], "body": cleaned,
        "category": _NOTE_CATEGORY.get(target.rule, "customer_instruction"), "status": "confirmed",
        "rfi_needed": False, "usage": "context", "source_ref": target.where[:300], "obsolete_after_revision": "",
    })

    row = _decision_row(db, project, key)
    before = _snapshot(row)
    row.status, row.note_id = "answered", note.id
    row.decided_by, row.decided_at = actor.id, datetime.now(timezone.utc)
    db.flush()
    actions.commit(db, actor=actor, project_id=project.id, kind="plan_decide", label=f"Answered: {target.title}",
                   before=before, after=_snapshot(row))
    return _question_out(target, row, {str(d.id): d.filename for d in docs})
```

Move the `notes_service` import up with the other imports (the `noqa` line above is only so the snippet is self-contained).

- [ ] **Step 4: Add the route**

```python
@router.post("/projects/{project_id}/plan/questions/{key}/answer", response_model=QuestionOut)
def post_answer(project_id: uuid.UUID, key: str, payload: AnswerIn, user: User = Depends(current_user),
                db: DbSession = Depends(get_db)) -> QuestionOut:
    project = load_project(project_id, db, user)
    out = service.answer(db, actor=user, project=project, key=key, body=payload.body)
    db.commit()
    return out
```

- [ ] **Step 5: Run the tests**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_api.py tests/test_notes.py -q`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add api/app/plan/service.py api/app/plan/router.py api/tests/test_plan_api.py
git commit -m "Plan: an answered question becomes a context note, so the next run reads it

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Stated phases — add and remove

**Files:**
- Modify: `api/app/plan/service.py` (`add_phase`, `remove_phase`), `api/app/plan/router.py`
- Test: `api/tests/test_plan_api.py` (append), then the tenancy guard

**Interfaces:**
- Produces: `service.add_phase(db, *, actor, project, name) -> PlanLineOut`; `service.remove_phase(db, *, actor, project, phase_id) -> None`.

- [ ] **Step 1: Append the failing tests**

```python
# --- stated phases ---

def test_add_and_remove_a_stated_phase(client, db, project, dana, signed_in_user, seeded):
    r = client.post(f"/api/projects/{project.id}/plan/phases", json={"name": "Phase 3 — office"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["added"] is True and out["text"] == "Phase 3 — office" and out["key"] == f"phase:added:{out['phase_id']}"
    assert out["document_id"] is None and out["page"] is None and out["quote"] is None
    plan = client.get(f"/api/projects/{project.id}/plan").json()
    assert [p["text"] for p in plan["phases"]] == ["Phase 1", "Phase 2", "Phase 3 — office"]
    # A stated phase can be confirmed like any line.
    assert client.patch(f"/api/projects/{project.id}/plan/lines/{out['key']}", json={"status": "confirmed"}).json()["status"] == "confirmed"
    assert client.delete(f"/api/projects/{project.id}/plan/phases/{out['phase_id']}").status_code == 204
    assert [p["text"] for p in client.get(f"/api/projects/{project.id}/plan").json()["phases"]] == ["Phase 1", "Phase 2"]
    labels = [a.label for a in db.scalars(select(Action).where(Action.kind.in_(("plan_phase_add", "plan_phase_remove"))).order_by(Action.seq))]
    assert labels == ["Added phase: Phase 3 — office", "Removed phase: Phase 3 — office"]


def test_a_stated_phase_silences_the_no_phasing_question(client, db, project, dana, signed_in_user):
    d = _doc(db, project, dana, filename="E.pdf", doc_type="Drawings", page_count=1)
    _sheet(db, project, d)
    assert any(q["title"] == "No phasing was stated" for q in client.get(f"/api/projects/{project.id}/plan").json()["questions"])
    client.post(f"/api/projects/{project.id}/plan/phases", json={"name": "Phase 1"})
    assert not any(q["title"] == "No phasing was stated" for q in client.get(f"/api/projects/{project.id}/plan").json()["questions"])


def test_phase_names_are_validated_and_unique(client, db, project, dana, signed_in_user, seeded):
    url = f"/api/projects/{project.id}/plan/phases"
    assert client.post(url, json={"name": " "}).status_code == 422
    assert client.post(url, json={"name": "x" * 101}).status_code == 422
    assert client.post(url, json={"name": "phase 1"}).status_code == 422  # detected already
    assert client.post(url, json={"name": "Phase 4"}).status_code == 201
    assert client.post(url, json={"name": "PHASE 4"}).status_code == 422  # stated already


def test_removing_a_detected_phase_or_a_stranger_is_404(client, db, project, dana, signed_in_user, seeded):
    assert client.delete(f"/api/projects/{project.id}/plan/phases/{uuid.uuid4()}").status_code == 404
```

- [ ] **Step 2: Run to see them fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_api.py -q -k phase`
Expected: 404/405.

- [ ] **Step 3: Add `add_phase` and `remove_phase`**

Append to `service.py`:

```python
def add_phase(db: DbSession, *, actor: User, project: Project, name: str) -> PlanLineOut:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > _MAX_PHASE:
        raise DomainError("invalid_plan_phase", f"A phase name can't be empty and must be {_MAX_PHASE} characters or fewer.", status=422)
    _docs, _scope, _specs, _scheds, phase_lines, added, _qs = derive(db, project)
    taken = {l.text.lower() for l in phase_lines} | {p.name.lower() for p in added}
    if cleaned.lower() in taken:
        raise DomainError("duplicate_plan_phase", "That phase is already on the plan.", status=422)
    phase = PlanPhase(project_id=project.id, name=cleaned, created_by=actor.id)
    db.add(phase)
    db.flush()
    actions.commit(db, actor=actor, project_id=project.id, kind="plan_phase_add", label=f"Added phase: {cleaned}",
                   before={}, after={"phase_id": str(phase.id), "name": cleaned})
    return _added_phase_out(phase, None)


def remove_phase(db: DbSession, *, actor: User, project: Project, phase_id: uuid.UUID) -> None:
    phase = db.scalar(select(PlanPhase).where(PlanPhase.project_id == project.id, PlanPhase.id == phase_id))
    if phase is None:
        raise not_found()
    key = f"phase:added:{phase.id}"
    decision = db.scalar(select(PlanDecision).where(PlanDecision.project_id == project.id, PlanDecision.entry_key == key))
    if decision is not None:
        db.delete(decision)
    db.delete(phase)
    db.flush()
    actions.commit(db, actor=actor, project_id=project.id, kind="plan_phase_remove", label=f"Removed phase: {phase.name}",
                   before={"phase_id": str(phase.id), "name": phase.name}, after={})
```

- [ ] **Step 4: Add the routes**

```python
@router.post("/projects/{project_id}/plan/phases", response_model=PlanLineOut, status_code=201)
def post_phase(project_id: uuid.UUID, payload: PhaseIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> PlanLineOut:
    project = load_project(project_id, db, user)
    out = service.add_phase(db, actor=user, project=project, name=payload.name)
    db.commit()
    return out


@router.delete("/projects/{project_id}/plan/phases/{phase_id}", status_code=204)
def delete_phase(project_id: uuid.UUID, phase_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> None:
    project = load_project(project_id, db, user)
    service.remove_phase(db, actor=user, project=project, phase_id=phase_id)
    db.commit()
```

- [ ] **Step 5: Run the plan tests and the tenancy guard**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_plan_api.py tests/test_tenancy.py tests/test_action_log.py -q`
Expected: pass — every one of the five plan routes now has a `TENANCY_TABLE` row (Task 4) and exists in `app.routes`.

- [ ] **Step 6: Commit**

```bash
git add api/app/plan/service.py api/app/plan/router.py api/tests/test_plan_api.py
git commit -m "Plan: a phase the documents don't state can be added and removed, marked as stated by the estimator

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Store functions and mapping

**Files:**
- Modify (append at the end of the relevant blocks): `src/lib/store/api-mapping.js` (add `mapPlanLine`, `mapQuestion`, `mapPlan` at the end of the file), `src/lib/store/api.js` (five functions after `decideScope`, five names appended to the returned object)
- Test: `src/lib/store/api-plan.test.js`

**Interfaces:**
- Produces store methods: `getPlan(projectId) -> Promise<Plan>`, `decidePlanLine(projectId, key, { status } | { editedText }) -> Promise<PlanLine | Question>`, `answerPlanQuestion(projectId, key, body) -> Promise<Question>`, `addPlanPhase(projectId, name) -> Promise<PlanLine>`, `removePlanPhase(projectId, phaseId) -> Promise<null>`.
- Client shapes: `Plan = { readAt, reading, hasDrawings, undecided, scope: ScopeStatement[], specs: PlanLine[], schedules: PlanLine[], phases: PlanLine[], questions: Question[] }`; `PlanLine = { key, kind, text, foundText, editedText, status, documentId, documentFilename, page, quote, division, sheetNumber, added, phaseId, places: [{ documentId, documentFilename, page, quote }] }`; `Question = { key, status, title, found, why, fix, where, documentId, documentFilename, noteId }`. A `ScopeStatement` is `mapScopeStatement`'s shape (`id, kind, text, editedText, status, documentId, documentFilename, page, quote`).

- [ ] **Step 1: Write the failing test**

`src/lib/store/api-plan.test.js`:

```js
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiStore } from "./api.js";
import { mapPlan } from "./api-mapping.js";

const LINE = { key: "spec:d:260519", kind: "spec_section", text: "26 05 19 — Conductors", found_text: "26 05 19 — CONDUCTORS",
  edited_text: "26 05 19 — Conductors", status: "confirmed", document_id: "d", document_filename: "Spec.pdf", page: null,
  quote: "SECTION 26 05 19 CONDUCTORS", division: "26", sheet_number: null, added: false, phase_id: null, places: [] };
const QUESTION = { key: "question:no_specs:project", status: "found", title: "No specification was uploaded", found: "f", why: "w",
  fix: "x", where: "Documents.", document_id: null, document_filename: null, note_id: null };

describe("mapPlan", () => {
  it("maps every section to camelCase, page kept as the 1-based number", () => {
    const out = mapPlan({ read_at: "2026-09-21T10:00:00Z", reading: false, has_drawings: true, undecided: 2,
      scope: [{ id: "x", kind: "excluded", text: "t", edited_text: null, status: "found", document_id: "d", document_filename: "s.pdf", page: 3, quote: "q" }],
      specs: [LINE], schedules: [], phases: [{ ...LINE, key: "phase:PHASE 1", kind: "phase", places: [{ document_id: "d", document_filename: "E.pdf", page: 2, quote: "Phase 1 plan" }] }],
      questions: [QUESTION] });
    expect(out.readAt).toBe("2026-09-21T10:00:00Z");
    expect(out.hasDrawings).toBe(true);
    expect(out.scope[0]).toEqual({ id: "x", kind: "excluded", text: "t", editedText: null, status: "found", documentId: "d", documentFilename: "s.pdf", page: 3, quote: "q" });
    expect(out.specs[0]).toEqual({ key: "spec:d:260519", kind: "spec_section", text: "26 05 19 — Conductors", foundText: "26 05 19 — CONDUCTORS",
      editedText: "26 05 19 — Conductors", status: "confirmed", documentId: "d", documentFilename: "Spec.pdf", page: null,
      quote: "SECTION 26 05 19 CONDUCTORS", division: "26", sheetNumber: null, added: false, phaseId: null, places: [] });
    expect(out.phases[0].places).toEqual([{ documentId: "d", documentFilename: "E.pdf", page: 2, quote: "Phase 1 plan" }]);
    expect(out.questions[0]).toEqual({ key: "question:no_specs:project", status: "found", title: "No specification was uploaded", found: "f",
      why: "w", fix: "x", where: "Documents.", documentId: null, documentFilename: null, noteId: null });
  });
});

describe("plan store methods", () => {
  let store;
  let calls;
  beforeEach(() => {
    calls = [];
    vi.stubGlobal("fetch", vi.fn(async (path, init) => {
      calls.push([path, init]);
      const body = path.endsWith("/plan") ? { read_at: null, reading: false, has_drawings: false, undecided: 0, scope: [], specs: [], schedules: [], phases: [], questions: [] }
        : init.method === "DELETE" ? null : path.includes("/questions/") ? QUESTION : LINE;
      return { ok: true, status: body === null ? 204 : 200, text: async () => (body === null ? "" : JSON.stringify(body)) };
    }));
    store = createApiStore();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("getPlan fetches and maps", async () => {
    const plan = await store.getPlan("p1");
    expect(calls[0][0]).toBe("/api/projects/p1/plan");
    expect(plan.undecided).toBe(0);
  });

  it("decidePlanLine sends exactly one of status or edited_text and encodes the key", async () => {
    await store.decidePlanLine("p1", "phase:PHASE 1", { status: "confirmed" });
    expect(calls[0][0]).toBe("/api/projects/p1/plan/lines/phase%3APHASE%201");
    expect(JSON.parse(calls[0][1].body)).toEqual({ status: "confirmed" });
    await store.decidePlanLine("p1", "spec:d:260519", { editedText: "x" });
    expect(JSON.parse(calls[1][1].body)).toEqual({ edited_text: "x" });
  });

  it("answerPlanQuestion posts the body and maps a question", async () => {
    const out = await store.answerPlanQuestion("p1", "question:no_specs:project", "Drawings are the whole set.");
    expect(calls[0][0]).toBe("/api/projects/p1/plan/questions/question%3Ano_specs%3Aproject/answer");
    expect(JSON.parse(calls[0][1].body)).toEqual({ body: "Drawings are the whole set." });
    expect(out.title).toBe("No specification was uploaded");
  });

  it("addPlanPhase and removePlanPhase", async () => {
    await store.addPlanPhase("p1", "Phase 2");
    expect(calls[0][0]).toBe("/api/projects/p1/plan/phases");
    expect(JSON.parse(calls[0][1].body)).toEqual({ name: "Phase 2" });
    expect(await store.removePlanPhase("p1", "ph1")).toBeNull();
    expect(calls[1][0]).toBe("/api/projects/p1/plan/phases/ph1");
    expect(calls[1][1].method).toBe("DELETE");
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npm test -- --run src/lib/store/api-plan.test.js`
Expected: `mapPlan` is not exported.

- [ ] **Step 3: Append the mappers**

At the END of `src/lib/store/api-mapping.js`:

```js
/** Wire PlanLineOut -> store shape (docs/specs/project-plan-screen.md).
 *  `page` stays the 1-based number the server sends, or null for a spec
 *  section, which cites its document rather than a page. */
export function mapPlanLine(raw) {
  return {
    key: raw.key,
    kind: raw.kind,
    text: raw.text,
    foundText: raw.found_text,
    editedText: raw.edited_text ?? null,
    status: raw.status,
    documentId: raw.document_id ?? null,
    documentFilename: raw.document_filename ?? null,
    page: raw.page ?? null,
    quote: raw.quote ?? null,
    division: raw.division ?? null,
    sheetNumber: raw.sheet_number ?? null,
    added: Boolean(raw.added),
    phaseId: raw.phase_id ?? null,
    places: (raw.places ?? []).map((p) => ({
      documentId: p.document_id ?? null,
      documentFilename: p.document_filename,
      page: p.page ?? null,
      quote: p.quote,
    })),
  };
}

/** Wire QuestionOut -> store shape. The four warning fields cross
 *  verbatim; nothing about how the question was raised does. */
export function mapQuestion(raw) {
  return {
    key: raw.key,
    status: raw.status,
    title: raw.title,
    found: raw.found,
    why: raw.why,
    fix: raw.fix,
    where: raw.where,
    documentId: raw.document_id ?? null,
    documentFilename: raw.document_filename ?? null,
    noteId: raw.note_id ?? null,
  };
}

export function mapPlan(raw) {
  return {
    readAt: raw.read_at ?? null,
    reading: Boolean(raw.reading),
    hasDrawings: Boolean(raw.has_drawings),
    undecided: raw.undecided ?? 0,
    scope: (raw.scope ?? []).map(mapScopeStatement),
    specs: (raw.specs ?? []).map(mapPlanLine),
    schedules: (raw.schedules ?? []).map(mapPlanLine),
    phases: (raw.phases ?? []).map(mapPlanLine),
    questions: (raw.questions ?? []).map(mapQuestion),
  };
}
```

- [ ] **Step 4: Append the store functions**

In `src/lib/store/api.js`, add `mapPlan, mapPlanLine, mapQuestion` to the existing import from `./api-mapping.js` (extend the import list on that one line — the only in-place edit, and it is an addition to a list). Then directly after `decideScope`'s closing brace add:

```js
  /** The project plan: what the documents say, derived server-side on
   *  every read, with the estimator's decisions applied. */
  async function getPlan(projectId) {
    return mapPlan(await request(`/api/projects/${projectId}/plan`));
  }

  /** Exactly one of status / editedText, the same contract as decideScope.
   *  A question comes back as a question (title, found, why, fix, where);
   *  anything else as a line. */
  async function decidePlanLine(projectId, key, changes) {
    const body = {};
    if (Object.prototype.hasOwnProperty.call(changes, "status")) body.status = changes.status;
    if (Object.prototype.hasOwnProperty.call(changes, "editedText")) body.edited_text = changes.editedText;
    const raw = await request(`/api/projects/${projectId}/plan/lines/${encodeURIComponent(key)}`, { method: "PATCH", body });
    return raw && raw.title !== undefined ? mapQuestion(raw) : mapPlanLine(raw);
  }

  async function answerPlanQuestion(projectId, key, body) {
    const raw = await request(`/api/projects/${projectId}/plan/questions/${encodeURIComponent(key)}/answer`, { method: "POST", body: { body } });
    return mapQuestion(raw);
  }

  async function addPlanPhase(projectId, name) {
    return mapPlanLine(await request(`/api/projects/${projectId}/plan/phases`, { method: "POST", body: { name } }));
  }

  async function removePlanPhase(projectId, phaseId) {
    return request(`/api/projects/${projectId}/plan/phases/${phaseId}`, { method: "DELETE" });
  }
```

And append the five names to the object `createApiStore` returns — after the last existing name in that list, before the closing `};`:

```js
    getPlan,
    decidePlanLine,
    answerPlanQuestion,
    addPlanPhase,
    removePlanPhase,
```

- [ ] **Step 5: Run the tests**

Run: `npm test -- --run src/lib/store`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/lib/store/api.js src/lib/store/api-mapping.js src/lib/store/api-plan.test.js
git commit -m "Plan: store methods and mappers for the project plan

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: The `plan` stage, route, nav item, and screen name

**Files:**
- Modify: `src/lib/projectStage.js` (insert one row), `src/routes.jsx` (one import, one `<Route>`), `src/components/shell/ProjectNav.jsx` (one nav item + one icon import), `src/components/conversation/screenContext.jsx` (three appends), `api/app/assistant/schemas.py` (two appends), `api/app/assistant/context.py` (one row appended to `_SECTIONS`)
- Create: `src/components/plan/PlanWorkspace.jsx` as a placeholder so the route resolves (Task 12 replaces it)
- Test: `src/lib/projectStage.test.js` (append), `src/components/conversation/screenContext.test.jsx` (the closed-set assertion gains `"plan"` and one path case), `api/tests/test_assistant_context.py` (`test_screen_names_are_the_closed_set` gains `"plan"`)

**Interfaces:**
- Produces: `STAGES` contains `{ key: "plan", label: "Plan" }` between `documents` and `processing`; route `/projects/:projectId/plan` under `ProjectWorkspaceLayout`; screen name `"plan"` on both sides, with the same context sections as `confirm` (documents, sheets, document texts) because the plan is a view over the same material.

- [ ] **Step 1: Write and extend the failing tests**

Append to `src/lib/projectStage.test.js`:

```js
describe("the plan stage", () => {
  it("sits between documents and processing and reads as Plan", () => {
    const keys = STAGES.map((s) => s.key);
    expect(keys.indexOf("plan")).toBe(keys.indexOf("documents") + 1);
    expect(keys.indexOf("processing")).toBe(keys.indexOf("plan") + 1);
    expect(stageLabel("plan")).toBe("Plan");
  });

  it("is an active project, neither processing nor complete", () => {
    expect(matchesFilter(project({ stage: "plan", itemsTotal: 0, itemsApproved: 0 }), "active")).toBe(true);
    expect(matchesFilter(project({ stage: "plan" }), "processing")).toBe(false);
    expect(matchesFilter(project({ stage: "plan" }), "complete")).toBe(false);
  });
});
```

In `src/components/conversation/screenContext.test.jsx`, the `expect(SCREEN_NAMES).toEqual([...])` array gains `"plan"` as its last entry, and after the `settings` line append:

```js
    expect(screenNameFromPath("/projects/p1/plan")).toBe("plan");
```

In `api/tests/test_assistant_context.py`, `test_screen_names_are_the_closed_set`'s tuple gains `"plan"` as its last entry. (These two are the mirror's own closed-set assertions — extending them is the point of the test, not a workaround.)

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/lib/projectStage.test.js src/components/conversation/screenContext.test.jsx && cd api && ../.enginevenv/bin/python -m pytest tests/test_assistant_context.py -q`
Expected: the plan stage tests and both closed-set tests fail.

- [ ] **Step 3: Make the edits**

`src/lib/projectStage.js` — insert after the `documents` row of `STAGES`:

```js
  { key: "plan", label: "Plan" },
```

`src/components/plan/PlanWorkspace.jsx` (placeholder, replaced in Task 12):

```jsx
export default function PlanWorkspace() {
  return <p className="page">Project plan</p>;
}
```

`src/routes.jsx` — after the `import ExportPreview ...` line append:

```jsx
import PlanWorkspace from "./components/plan/PlanWorkspace.jsx";
```

and inside the `ProjectWorkspaceLayout` route's children, after `<Route path="export" element={<ExportPreview />} />` append:

```jsx
        <Route path="plan" element={<PlanWorkspace />} />
```

`src/components/shell/ProjectNav.jsx` — add `ListChecks` to the `lucide-react` import list (an addition to that list, alphabetical position is fine), and in `GROUPS`, in the *Evidence* group's `items` array, after the `notes` row append:

```js
      { slug: "plan", label: "Project plan", built: true, Icon: ListChecks },
```

`src/components/conversation/screenContext.jsx` — append `"plan"` at the end of `SCREEN_NAMES`; append `plan: "Project plan",` at the end of `SCREEN_LABELS`; append `plan: "plan",` at the end of `BY_SUFFIX`.

`api/app/assistant/schemas.py` — append `"plan"` at the end of the `SCREEN_NAMES` tuple and at the end of the `ScreenName` `Literal[...]`.

`api/app/assistant/context.py` — append to `_SECTIONS`, after the `"settings": (),` row:

```python
    "plan": ("documents", "sheets", "document_texts"),
```

- [ ] **Step 4: Run the tests and the build**

Run: `npm test -- --run src/lib/projectStage.test.js src/components/conversation src/components/shell && npm run build && cd api && ../.enginevenv/bin/python -m pytest tests/test_assistant_context.py tests/test_assistant_router.py tests/test_assistant_prompt.py -q`
Expected: pass; build clean.

- [ ] **Step 5: Commit**

```bash
git add src/lib/projectStage.js src/lib/projectStage.test.js src/routes.jsx src/components/shell/ProjectNav.jsx src/components/conversation/screenContext.jsx src/components/conversation/screenContext.test.jsx api/app/assistant/schemas.py api/app/assistant/context.py api/tests/test_assistant_context.py src/components/plan/PlanWorkspace.jsx
git commit -m "Plan: the plan stage, its route under the project workspace, its nav item, and its screen name on both sides

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: `PlanLine` and the moved `ScopeSection`

**Files:**
- Create: `src/components/plan/pageLink.js`, `src/components/plan/PlanLine.jsx`, `src/components/plan/PlanLine.test.jsx`
- Move (with `git mv`): `src/components/documents/ScopeSection.jsx` → `src/components/plan/ScopeSection.jsx`, `src/components/documents/ScopeSection.test.jsx` → `src/components/plan/ScopeSection.test.jsx`; then rewrite `ScopeSection.jsx`'s row to use `PlanLine`, and give it a controlled mode.

**Interfaces:**
- Produces: `documentPageHref(documentId, page) -> string` (`/api/documents/<id>/content#page=<n>`, or without the fragment when page is null; `""` when documentId is null).
- `PlanLine` props: `line` (`{ id?, key?, status, text, editedText, quote, documentId, documentFilename, page, places?, added? }` — a scope statement or a plan line; the row uses `line.editedText ?? line.text` as the current text and shows `Original:` when `editedText` differs), `onDecide(change) -> Promise` where `change` is `{ status }` or `{ editedText }`, optional `onRemove() -> Promise` (renders a Remove button), optional `children` (rendered under the text — the phase's places list). Buttons: `Confirm` (hidden when confirmed), `Correct` (opens a textarea labelled `Statement`; `Save` / `Cancel`), `Dismiss` (hidden when dismissed), `Reopen` (shown when confirmed or dismissed), `View source` (toggles the blockquote + cite), and the cite is a link `Open page` / `Open document` to `documentPageHref`. Status pill through `.note-status.note-status--<status>` with an icon.
- `ScopeSection` props: `store`, `projectId` (self-fetching, as before) **or** `statements`, `onDecided(updated)` (controlled — no fetch; decisions still go through `store.decideScope` and the result is handed up), plus optional `kinds` (default all four), `title` (default *Scope stated in the documents*), `description`, `headingId` (default `scope-heading`).

- [ ] **Step 1: Move the files**

```bash
mkdir -p src/components/plan
git mv src/components/documents/ScopeSection.jsx src/components/plan/ScopeSection.jsx
git mv src/components/documents/ScopeSection.test.jsx src/components/plan/ScopeSection.test.jsx
```

Then, in `src/components/documents/ConfirmDrawings.jsx`, change the import line `import ScopeSection from "./ScopeSection.jsx";` to `import ScopeSection from "../plan/ScopeSection.jsx";` so the build stays green until Task 13 removes it.

- [ ] **Step 2: Write the failing `PlanLine` test**

`src/components/plan/PlanLine.test.jsx`:

```jsx
/* PlanLine — one line of the plan: its status in the note-status
   vocabulary, its text (corrected or as found), the page it came from,
   and the decision controls. Shared by scope statements and every
   derived line, so the same words appear on every row. */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlanLine from "./PlanLine.jsx";
import { documentPageHref } from "./pageLink.js";

const line = (o) => ({
  key: "schedule:sheet:s1", status: "found", text: "Luminaire schedule", editedText: null,
  quote: "LUMINAIRE SCHEDULE", documentId: "d1", documentFilename: "E-set.pdf", page: 2, ...o,
});

describe("documentPageHref", () => {
  it("opens the document at the page, or the document alone", () => {
    expect(documentPageHref("d1", 3)).toBe("/api/documents/d1/content#page=3");
    expect(documentPageHref("d1", null)).toBe("/api/documents/d1/content");
    expect(documentPageHref(null, 3)).toBe("");
  });
});

describe("PlanLine", () => {
  it("shows the text, the cite with a page link, and the source on demand", async () => {
    render(<PlanLine line={line()} onDecide={vi.fn()} />);
    expect(screen.getByText("Luminaire schedule")).toBeInTheDocument();
    expect(screen.getByText("Found")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open page" });
    expect(link).toHaveAttribute("href", "/api/documents/d1/content#page=2");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByText("E-set.pdf, page 2")).toBeInTheDocument();
    expect(screen.queryByText("LUMINAIRE SCHEDULE")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "View source" }));
    expect(screen.getByText("LUMINAIRE SCHEDULE")).toBeInTheDocument();
  });

  it("cites the document alone when there is no page, and nothing when there is no document", () => {
    const { rerender } = render(<PlanLine line={line({ page: null, documentFilename: "Spec.pdf" })} onDecide={vi.fn()} />);
    expect(screen.getByText("Spec.pdf")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open document" })).toHaveAttribute("href", "/api/documents/d1/content");
    rerender(<PlanLine line={line({ documentId: null, documentFilename: null, page: null, quote: null, added: true })} onDecide={vi.fn()} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button", { name: "View source" })).toBeNull();
    expect(screen.getByText("Stated by you")).toBeInTheDocument();
  });

  it("confirms, corrects, dismisses and reopens through onDecide", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<PlanLine line={line()} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onDecide).toHaveBeenCalledWith({ status: "confirmed" });
    await userEvent.click(screen.getByRole("button", { name: "Correct" }));
    const box = screen.getByRole("textbox", { name: "Statement" });
    await userEvent.clear(box);
    await userEvent.type(box, "Luminaire schedule (sheet E0.1)");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onDecide).toHaveBeenCalledWith({ editedText: "Luminaire schedule (sheet E0.1)" });
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDecide).toHaveBeenCalledWith({ status: "dismissed" });
    rerender(<PlanLine line={line({ status: "dismissed", editedText: "Luminaire schedule (sheet E0.1)" })} onDecide={onDecide} />);
    expect(screen.getByText("Luminaire schedule (sheet E0.1)")).toBeInTheDocument();
    expect(screen.getByText("Original: Luminaire schedule")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Reopen" }));
    expect(onDecide).toHaveBeenCalledWith({ status: "found" });
  });

  it("keeps the row as it was and says so when a decision fails, and cancels an edit without writing", async () => {
    const onDecide = vi.fn().mockRejectedValue({ message: "down" });
    render(<PlanLine line={line()} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Correct" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Statement" }), " more");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onDecide).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Couldn't save that decision. Try again.")).toBeInTheDocument();
    expect(screen.getByText("Found")).toBeInTheDocument();
  });

  it("renders a Remove control and children when given", async () => {
    const onRemove = vi.fn().mockResolvedValue(undefined);
    render(
      <PlanLine line={line({ added: true, documentId: null, page: null, quote: null })} onDecide={vi.fn()} onRemove={onRemove}>
        <p>Also on E2.2</p>
      </PlanLine>,
    );
    expect(screen.getByText("Also on E2.2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onRemove).toHaveBeenCalled();
  });

  it("renders status as icon plus label, never the review-status classes", () => {
    const { container } = render(<PlanLine line={line({ status: "confirmed" })} onDecide={vi.fn()} />);
    expect(container.querySelector(".pill--approved, .pill--ready, .pill--attention, .pill--missing")).toBeNull();
    const pill = container.querySelector(".note-status.note-status--confirmed");
    expect(pill).not.toBeNull();
    expect(pill.querySelector("svg")).not.toBeNull();
  });
});
```

- [ ] **Step 3: Run to see it fail**

Run: `npm test -- --run src/components/plan/PlanLine.test.jsx`
Expected: module not found.

- [ ] **Step 4: Write `pageLink.js` and `PlanLine.jsx`**

`src/components/plan/pageLink.js`:

```js
/* The page a plan line came from, as the document's own content at
   that page. The API streams the stored file (documents/router.py
   get_content) and the session cookie carries auth, so a plain link
   works and the browser's viewer opens at the fragment's page. */

export function documentPageHref(documentId, page) {
  if (!documentId) return "";
  const base = `/api/documents/${documentId}/content`;
  return page ? `${base}#page=${page}` : base;
}
```

`src/components/plan/PlanLine.jsx`:

```jsx
/* ============================================================
   PlanLine.jsx — one line of the project plan.

   Scope statements and every derived line (spec section, schedule,
   phase) share this row, so the words and controls are the same on
   every one: a status in the note-status vocabulary (found, confirmed,
   dismissed -- never the four review labels, never Pill.jsx), the text
   as found or as corrected with the original beneath it, the page it
   came from as a link into the document, the verbatim source on
   demand, and Confirm / Correct / Dismiss / Reopen.

   Every decision goes through `onDecide` and the row follows its
   caller's answer. A refused decision leaves the row exactly as it was,
   with the failure stated on the row, so the estimator is never looking
   at a decision the server never took. The quote is document text: it
   is rendered as data, in a blockquote, and nothing here interprets it.
   ============================================================ */

import { useState } from "react";
import { Check, ExternalLink, RotateCcw, Search, X } from "lucide-react";
import { documentPageHref } from "./pageLink.js";

const STATUS = {
  found: { label: "Found", Icon: Search },
  confirmed: { label: "Confirmed", Icon: Check },
  dismissed: { label: "Dismissed", Icon: X },
};

export const DECIDE_FAILED = "Couldn't save that decision. Try again.";

export function LineStatus({ status }) {
  const { label, Icon } = STATUS[status] ?? STATUS.found;
  return (
    <span className={`note-status note-status--${status}`}>
      <Icon size={12} strokeWidth={2.6} aria-hidden="true" />
      {label}
    </span>
  );
}

/** "E-set.pdf, page 2" with a link, or "Spec.pdf" alone, or nothing. */
export function Cite({ documentId, documentFilename, page }) {
  if (!documentFilename) return null;
  const href = documentPageHref(documentId, page);
  const text = page ? `${documentFilename}, page ${page}` : documentFilename;
  return (
    <span className="plan-cite tabular">
      {text}
      {href ? (
        <a className="plan-cite__link" href={href} target="_blank" rel="noopener noreferrer">
          <ExternalLink size={12} aria-hidden="true" />
          {page ? "Open page" : "Open document"}
        </a>
      ) : null}
    </span>
  );
}

export default function PlanLine({ line, onDecide, onRemove = null, children = null }) {
  const [showSource, setShowSource] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const current = line.editedText ?? line.text;
  const edited = line.editedText != null && line.editedText !== line.text;
  const id = line.key ?? line.id;

  const run = (promise) => {
    setSaving(true);
    setError("");
    return promise
      .then(() => {
        setSaving(false);
        return true;
      })
      .catch(() => {
        setSaving(false);
        setError(DECIDE_FAILED);
        return false;
      });
  };
  const decide = (change) => run(onDecide(change));

  const save = () => {
    decide({ editedText: draft }).then((ok) => {
      if (ok) setEditing(false);
    });
  };

  const textareaId = `plan-text-${id}`;

  return (
    <li className="scope-row plan-line">
      <div className="scope-row__head">
        <LineStatus status={line.status} />
        {line.added ? <span className="plan-line__stated">Stated by you</span> : null}
        <Cite documentId={line.documentId} documentFilename={line.documentFilename} page={line.page} />
      </div>

      {editing ? (
        <div className="scope-row__edit">
          <label className="formfield-label" htmlFor={textareaId}>
            Statement
          </label>
          <textarea
            id={textareaId}
            className="field scope-row__textarea"
            rows={3}
            value={draft}
            disabled={saving}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="scope-row__actions">
            <button type="button" className="btn btn--primary" disabled={saving || !draft.trim()} onClick={save}>
              Save
            </button>
            <button type="button" className="btn" disabled={saving} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="scope-row__text">{current}</p>
          {edited ? <p className="scope-row__original muted">Original: {line.text}</p> : null}
          {children}
          <div className="scope-row__actions">
            {line.status !== "confirmed" ? (
              <button type="button" className="btn" disabled={saving} onClick={() => decide({ status: "confirmed" })}>
                Confirm
              </button>
            ) : null}
            <button type="button" className="btn" disabled={saving} onClick={() => { setDraft(current); setEditing(true); }}>
              Correct
            </button>
            {line.status !== "dismissed" ? (
              <button type="button" className="btn" disabled={saving} onClick={() => decide({ status: "dismissed" })}>
                Dismiss
              </button>
            ) : null}
            {line.status !== "found" ? (
              <button type="button" className="btn" disabled={saving} onClick={() => decide({ status: "found" })}>
                <RotateCcw size={14} aria-hidden="true" />
                Reopen
              </button>
            ) : null}
            {onRemove ? (
              <button type="button" className="btn" disabled={saving} onClick={() => run(onRemove())}>
                Remove
              </button>
            ) : null}
            {line.quote ? (
              <button type="button" className="btn" aria-expanded={showSource} onClick={() => setShowSource((v) => !v)}>
                View source
              </button>
            ) : null}
          </div>
        </>
      )}

      {showSource && line.quote ? (
        <figure className="scope-row__source">
          <blockquote className="scope-row__quote">{line.quote}</blockquote>
          <figcaption className="scope-row__cite tabular">
            {line.page ? `${line.documentFilename}, page ${line.page}` : line.documentFilename}
          </figcaption>
        </figure>
      ) : null}

      <p className="scope-row__error" aria-live="polite">
        {error || null}
      </p>
    </li>
  );
}
```

- [ ] **Step 5: Rewrite `ScopeSection.jsx` over `PlanLine`, with a controlled mode**

Replace the whole of `src/components/plan/ScopeSection.jsx` with:

```jsx
/* ============================================================
   ScopeSection.jsx — what the documents say the electrical work is,
   settled by a person before the takeoff runs. Lives on the project
   plan (docs/specs/project-plan-screen.md); it used to sit on Confirm
   drawings.

   The worker reads every uploaded file and lifts out scope statements:
   included, excluded, by others, or an alternate, each quoted verbatim
   from its source page. Nothing here is a takeoff item. A statement's
   status -- found, confirmed, dismissed -- is its own vocabulary, the
   same separation notes keep (CLAUDE.md: "a note's status is not an
   item's status"), drawn by PlanLine with .note-status, never Pill.jsx.

   Two ways to mount it. Self-fetching -- `store` + `projectId` -- loads
   the statements itself. Controlled -- `statements` + `onDecided` --
   renders what the plan screen already holds (the plan GET carries the
   scope array), so Scope and Exclusions on that screen are two views
   of one list and a decision in either updates both. Both modes write
   through store.decideScope: there is one write path per record.
   ============================================================ */

import { useEffect, useRef, useState } from "react";
import PlanLine from "./PlanLine.jsx";

export const KIND_ORDER = ["included", "excluded", "by_others", "alternate"];
export const KIND_LABELS = { included: "Included", excluded: "Excluded", by_others: "By others", alternate: "Alternates" };

function plural(n, word) {
  return `${n} ${n === 1 ? word : `${word}s`}`;
}

export default function ScopeSection({
  store,
  projectId,
  statements: controlled = null,
  onDecided = null,
  kinds = KIND_ORDER,
  title = "Scope stated in the documents",
  description = "What the documents say the electrical work includes and leaves out, quoted from the page it came from. Confirm each one, correct its wording, or dismiss it.",
  headingId = "scope-heading",
  emptyText = "No scope statements were found in the documents.",
}) {
  const isControlled = controlled !== null;
  const [fetched, setFetched] = useState(null);
  const [state, setState] = useState(isControlled ? "loaded" : "loading");

  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (isControlled) return;
    setState("loading");
    store
      .listScope(projectId)
      .then((rows) => {
        if (!aliveRef.current) return;
        setFetched(rows);
        setState("loaded");
      })
      .catch(() => {
        if (!aliveRef.current) return;
        setState("failed");
      });
  }, [store, projectId, isControlled]);

  const all = isControlled ? controlled : fetched;
  const statements = (all ?? []).filter((s) => kinds.includes(s.kind));

  const decide = (id, change) =>
    store.decideScope(id, change).then((updated) => {
      if (!aliveRef.current) return updated;
      if (isControlled) onDecided?.(updated);
      else setFetched((prev) => prev.map((s) => (s.id === id ? updated : s)));
      return updated;
    });

  let body;
  if (state === "loading") {
    body = <p className="muted scope-state">Loading scope statements…</p>;
  } else if (state === "failed") {
    body = (
      <p className="scope-state scope-state--failed" role="alert">
        Couldn't load the scope statements. Check the connection and try again.
      </p>
    );
  } else if (statements.length === 0) {
    body = <p className="muted scope-state">{emptyText}</p>;
  } else {
    const confirmed = statements.filter((s) => s.status === "confirmed").length;
    const dismissed = statements.filter((s) => s.status === "dismissed").length;
    const groups = kinds.map((kind) => ({ kind, rows: statements.filter((s) => s.kind === kind) })).filter((g) => g.rows.length > 0);
    body = (
      <>
        <p className="scope-summary tabular">
          {plural(statements.length, "statement")} found · {confirmed} confirmed · {dismissed} dismissed
        </p>
        {groups.map((g) => (
          <div key={g.kind} className="scope-group">
            <h3 className="scope-group__title">{KIND_LABELS[g.kind]}</h3>
            <ul className="scope-list">
              {g.rows.map((s) => (
                <PlanLine key={s.id} line={s} onDecide={(change) => decide(s.id, change)} />
              ))}
            </ul>
          </div>
        ))}
      </>
    );
  }

  return (
    <section className="scope-card" aria-labelledby={headingId}>
      <header className="scope-head">
        <h2 id={headingId}>{title}</h2>
        <p className="muted">{description}</p>
      </header>
      {body}
    </section>
  );
}
```

- [ ] **Step 6: Update `ScopeSection.test.jsx`**

The moved test file keeps every case. Three edits: (a) every `{ name: "Edit" }` becomes `{ name: "Correct" }`; (b) in the first test, after the `View source` click, also assert the page link: `expect(screen.getByRole("link", { name: "Open page" })).toHaveAttribute("href", "/api/documents/d/content#page=3");`; (c) append one controlled-mode case:

```jsx
  it("renders a given list without fetching, filters by kind, and hands a decision up", async () => {
    const decideScope = vi.fn().mockResolvedValue(stmt({ status: "confirmed" }));
    const onDecided = vi.fn();
    const store = { listScope: vi.fn(), decideScope };
    render(
      <ScopeSection
        store={store}
        projectId="p"
        statements={[stmt(), stmt({ id: "s2", kind: "included", text: "Provide all lighting." })]}
        onDecided={onDecided}
        kinds={["excluded", "by_others"]}
        title="Exclusions"
        headingId="exclusions-heading"
      />,
    );
    expect(store.listScope).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Exclusions" })).toBeInTheDocument();
    expect(screen.queryByText("Provide all lighting.")).toBeNull();
    expect(screen.getByText("1 statement found · 0 confirmed · 0 dismissed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onDecided).toHaveBeenCalledWith(stmt({ status: "confirmed" })));
  });
```

- [ ] **Step 7: Run the tests and the build**

Run: `npm test -- --run src/components/plan src/components/documents && npm run build`
Expected: pass; build clean (ConfirmDrawings still imports the moved section from its new path).

- [ ] **Step 8: Commit**

```bash
git add src/components/plan/pageLink.js src/components/plan/PlanLine.jsx src/components/plan/PlanLine.test.jsx src/components/plan/ScopeSection.jsx src/components/plan/ScopeSection.test.jsx src/components/documents/ConfirmDrawings.jsx
git commit -m "Plan: one row for every line of the plan, and the scope section moved onto it with a controlled mode

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: `PlanSection`, `QuestionLine`, `PhaseSection`

**Files:**
- Create: `src/components/plan/PlanSection.jsx`, `src/components/plan/QuestionLine.jsx`, `src/components/plan/PhaseSection.jsx`
- Test: `src/components/plan/QuestionLine.test.jsx`, `src/components/plan/PhaseSection.test.jsx`

**Interfaces:**
- `PlanSection` props: `id` (heading id), `title`, `description`, `emptyText`, `children` — renders `<section className="scope-card plan-section" aria-labelledby={id}>` with the header, then `emptyText` in `<p className="muted scope-state">` when `children` is null/false/an empty array, else `<ul className="scope-list">{children}</ul>`.
- `QuestionLine` props: `question` (the `Question` shape), `onAnswer(body) -> Promise`, `onDismiss() -> Promise`, `onReopen() -> Promise`, `notesHref`. Renders the four fields in a `.warncard` with `warncard__found` / `warncard__why` / `warncard__fix` / `warncard__where` paragraphs; controls `Answer` (opens a textarea labelled `Your answer`, `Save answer` / `Cancel`) and `Dismiss` while `found`; `Answered` status with a `See the note` link to `notesHref` when answered; `Reopen` when dismissed or answered.
- `PhaseSection` props: `phases: PlanLine[]`, `onDecide(key, change)`, `onAdd(name) -> Promise`, `onRemove(phaseId) -> Promise`. Renders each phase as a `PlanLine` (a detected phase lists every place it appears under the row; an added one shows *Stated by you* and Remove), then *Add a phase*: a text field labelled `Phase name` and an `Add phase` button, refusal shown inline.

- [ ] **Step 1: Write the failing tests**

`src/components/plan/QuestionLine.test.jsx`:

```jsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import QuestionLine from "./QuestionLine.jsx";

const q = (o) => ({
  key: "question:no_phasing:project", status: "found", title: "No phasing was stated",
  found: "The documents do not name any phase.", why: "A phased job is priced per phase.",
  fix: "Add the phases here, or answer that the job is one phase.", where: "Sheet titles and the specification.",
  documentId: null, documentFilename: null, noteId: null, ...o,
});

function mount(question, handlers = {}) {
  const h = { onAnswer: vi.fn().mockResolvedValue(undefined), onDismiss: vi.fn().mockResolvedValue(undefined), onReopen: vi.fn().mockResolvedValue(undefined), ...handlers };
  render(<MemoryRouter><QuestionLine question={question} notesHref="/projects/p1/notes" {...h} /></MemoryRouter>);
  return h;
}

describe("QuestionLine", () => {
  it("shows the four fields and the two controls", () => {
    mount(q());
    expect(screen.getByRole("heading", { name: "No phasing was stated" })).toBeInTheDocument();
    for (const text of ["The documents do not name any phase.", "A phased job is priced per phase.",
      "Add the phases here, or answer that the job is one phase.", "Sheet titles and the specification."]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Answer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("saves an answer through onAnswer and refuses an empty one", async () => {
    const h = mount(q());
    await userEvent.click(screen.getByRole("button", { name: "Answer" }));
    const save = screen.getByRole("button", { name: "Save answer" });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Your answer" }), "One phase, whole shop at once.");
    await userEvent.click(save);
    expect(h.onAnswer).toHaveBeenCalledWith("One phase, whole shop at once.");
  });

  it("reads Answered with a link to the note, and offers Reopen", async () => {
    const h = mount(q({ status: "answered", noteId: "n1" }));
    expect(screen.getByText("Answered")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See the note" })).toHaveAttribute("href", "/projects/p1/notes");
    expect(screen.queryByRole("button", { name: "Answer" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Reopen" }));
    expect(h.onReopen).toHaveBeenCalled();
  });

  it("dismisses, and says so when a write fails", async () => {
    const h = mount(q(), { onDismiss: vi.fn().mockRejectedValue({ message: "down" }) });
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(h.onDismiss).toHaveBeenCalled();
    expect(await screen.findByText("Couldn't save that decision. Try again.")).toBeInTheDocument();
    expect(screen.getByText("Found")).toBeInTheDocument();
  });

  it("never uses the review-status classes", () => {
    const { container } = render(<MemoryRouter><QuestionLine question={q({ status: "dismissed" })} notesHref="/n" onAnswer={vi.fn()} onDismiss={vi.fn()} onReopen={vi.fn()} /></MemoryRouter>);
    expect(container.querySelector(".pill--approved, .pill--ready, .pill--attention, .pill--missing")).toBeNull();
    expect(container.querySelector(".note-status--dismissed")).not.toBeNull();
  });
});
```

`src/components/plan/PhaseSection.test.jsx`:

```jsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PhaseSection from "./PhaseSection.jsx";

const detected = { key: "phase:PHASE 1", kind: "phase", text: "Phase 1", foundText: "Phase 1", editedText: null, status: "found",
  documentId: "d", documentFilename: "E-set.pdf", page: 2, quote: "Phase 1 demolition plan", division: null, sheetNumber: null,
  added: false, phaseId: null, places: [
    { documentId: "d", documentFilename: "E-set.pdf", page: 2, quote: "Phase 1 demolition plan" },
    { documentId: "d", documentFilename: "E-set.pdf", page: 5, quote: "PHASE 1 POWER PLAN" },
  ] };
const added = { ...detected, key: "phase:added:ph1", text: "Phase 3 — office", foundText: "Phase 3 — office", documentId: null,
  documentFilename: null, page: null, quote: null, added: true, phaseId: "ph1", places: [] };

describe("PhaseSection", () => {
  it("lists detected phases with every place they appear, and added ones as stated by you", () => {
    render(<PhaseSection phases={[detected, added]} onDecide={vi.fn()} onAdd={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText("Phase 1")).toBeInTheDocument();
    expect(screen.getByText("E-set.pdf, page 5")).toBeInTheDocument();
    expect(screen.getByText("Phase 3 — office")).toBeInTheDocument();
    expect(screen.getByText("Stated by you")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
  });

  it("says so when the documents state no phase", () => {
    render(<PhaseSection phases={[]} onDecide={vi.fn()} onAdd={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText("The documents do not name any phase.")).toBeInTheDocument();
  });

  it("adds a phase by name, clears the field, and shows a refusal inline", async () => {
    const onAdd = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce({ message: "That phase is already on the plan." });
    render(<PhaseSection phases={[]} onDecide={vi.fn()} onAdd={onAdd} onRemove={vi.fn()} />);
    const field = screen.getByRole("textbox", { name: "Phase name" });
    const button = screen.getByRole("button", { name: "Add phase" });
    expect(button).toBeDisabled();
    await userEvent.type(field, "Phase 2");
    await userEvent.click(button);
    expect(onAdd).toHaveBeenCalledWith("Phase 2");
    expect(field).toHaveValue("");
    await userEvent.type(field, "Phase 2");
    await userEvent.click(screen.getByRole("button", { name: "Add phase" }));
    expect(await screen.findByText("That phase is already on the plan.")).toBeInTheDocument();
  });

  it("routes a decision and a removal to the right handler", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    const onRemove = vi.fn().mockResolvedValue(undefined);
    render(<PhaseSection phases={[detected, added]} onDecide={onDecide} onAdd={vi.fn()} onRemove={onRemove} />);
    await userEvent.click(screen.getAllByRole("button", { name: "Confirm" })[0]);
    expect(onDecide).toHaveBeenCalledWith("phase:PHASE 1", { status: "confirmed" });
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onRemove).toHaveBeenCalledWith("ph1");
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/plan/QuestionLine.test.jsx src/components/plan/PhaseSection.test.jsx`
Expected: modules not found.

- [ ] **Step 3: Write `PlanSection.jsx`**

```jsx
/* One section of the plan: a heading, one sentence, and either the
   lines or the sentence that says there are none. Every section stays
   on the page when empty so the shape of the plan is visible even when
   most of it is -- the scanned-set case. */

export default function PlanSection({ id, title, description, emptyText, children }) {
  const items = Array.isArray(children) ? children.filter(Boolean) : children ? [children] : [];
  return (
    <section className="scope-card plan-section" aria-labelledby={id}>
      <header className="scope-head">
        <h2 id={id}>{title}</h2>
        {description ? <p className="muted">{description}</p> : null}
      </header>
      {items.length === 0 ? <p className="muted scope-state">{emptyText}</p> : <ul className="scope-list">{items}</ul>}
    </section>
  );
}
```

- [ ] **Step 4: Write `QuestionLine.jsx`**

```jsx
/* ============================================================
   QuestionLine.jsx — one thing the documents did not answer.

   Four fields, always: what was found, why it matters, what to check,
   where the evidence lives -- the same shape a warning has (CLAUDE.md),
   rendered with the warncard styles the item panel already uses.
   Answering saves a context note (the plan screen's onAnswer calls the
   store; the note then feeds the next run and lives on Notes &
   assumptions, which is where "See the note" goes). A question's
   status -- found, answered, dismissed -- is its own vocabulary, never
   the four review labels.
   ============================================================ */

import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, HelpCircle, RotateCcw, X } from "lucide-react";
import { DECIDE_FAILED } from "./PlanLine.jsx";

const STATUS = {
  found: { label: "Found", Icon: HelpCircle },
  answered: { label: "Answered", Icon: Check },
  dismissed: { label: "Dismissed", Icon: X },
};

export default function QuestionLine({ question, onAnswer, onDismiss, onReopen, notesHref }) {
  const [answering, setAnswering] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const { label, Icon } = STATUS[question.status] ?? STATUS.found;
  const textareaId = `plan-answer-${question.key}`;

  const run = (promise) => {
    setSaving(true);
    setError("");
    return promise
      .then(() => {
        setSaving(false);
        return true;
      })
      .catch((err) => {
        setSaving(false);
        setError(err?.message && err.code && err.code !== "network" ? err.message : DECIDE_FAILED);
        return false;
      });
  };

  const save = () =>
    run(onAnswer(draft.trim())).then((ok) => {
      if (ok) {
        setAnswering(false);
        setDraft("");
      }
    });

  return (
    <li className="plan-question">
      <div className="warncard warncard--question">
        <div className="scope-row__head">
          <span className={`note-status note-status--${question.status}`}>
            <Icon size={12} strokeWidth={2.6} aria-hidden="true" />
            {label}
          </span>
          {question.documentFilename ? <span className="plan-cite tabular">{question.documentFilename}</span> : null}
        </div>
        <h4>{question.title}</h4>
        <p className="warncard__found">{question.found}</p>
        <p className="warncard__why">{question.why}</p>
        <p className="warncard__fix">{question.fix}</p>
        <p className="warncard__where">{question.where}</p>

        {answering ? (
          <div className="scope-row__edit">
            <label className="formfield-label" htmlFor={textareaId}>
              Your answer
            </label>
            <textarea id={textareaId} className="field scope-row__textarea" rows={3} value={draft} disabled={saving}
                      onChange={(e) => setDraft(e.target.value)} />
            <div className="scope-row__actions">
              <button type="button" className="btn btn--primary" disabled={saving || !draft.trim()} onClick={save}>
                Save answer
              </button>
              <button type="button" className="btn" disabled={saving} onClick={() => setAnswering(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="scope-row__actions">
            {question.status === "found" ? (
              <>
                <button type="button" className="btn btn--primary" disabled={saving} onClick={() => setAnswering(true)}>
                  Answer
                </button>
                <button type="button" className="btn" disabled={saving} onClick={() => run(onDismiss())}>
                  Dismiss
                </button>
              </>
            ) : (
              <>
                {question.status === "answered" ? (
                  <Link className="btn" to={notesHref}>
                    See the note
                  </Link>
                ) : null}
                <button type="button" className="btn" disabled={saving} onClick={() => run(onReopen())}>
                  <RotateCcw size={14} aria-hidden="true" />
                  Reopen
                </button>
              </>
            )}
          </div>
        )}
        <p className="scope-row__error" aria-live="polite">
          {error || null}
        </p>
      </div>
    </li>
  );
}
```

- [ ] **Step 5: Write `PhaseSection.jsx`**

```jsx
/* ============================================================
   PhaseSection.jsx — the phasing the documents call for, and the
   phases the estimator states.

   A detected phase is one line per label across the whole set, with
   every place it appeared listed under the row. An added phase is one
   the documents don't state -- the Gerber case, where the split came
   from the GC's bid instructions -- marked "Stated by you", with Remove.
   Stream D turns confirmed phases into the phase model; here they stop
   at names.
   ============================================================ */

import { useState } from "react";
import PlanLine, { Cite } from "./PlanLine.jsx";
import PlanSection from "./PlanSection.jsx";

const ADD_FAILED = "Couldn't add that phase. Try again.";

export default function PhaseSection({ phases, onDecide, onAdd, onRemove }) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const add = () => {
    const cleaned = name.trim();
    if (!cleaned) return;
    setSaving(true);
    setError("");
    onAdd(cleaned)
      .then(() => {
        setSaving(false);
        setName("");
      })
      .catch((err) => {
        setSaving(false);
        setError(err?.code && err.code !== "network" && err.message ? err.message : ADD_FAILED);
      });
  };

  return (
    <>
      <PlanSection
        id="plan-phases-heading"
        title="Phasing"
        description="Every phase the documents name, and where. Confirm the ones this bid is split by, or add a phase the documents don't state."
        emptyText="The documents do not name any phase."
      >
        {phases.map((p) => (
          <PlanLine
            key={p.key}
            line={p}
            onDecide={(change) => onDecide(p.key, change)}
            onRemove={p.added ? () => onRemove(p.phaseId) : null}
          >
            {p.places.length > 1 ? (
              <ul className="plan-places">
                {p.places.slice(1).map((place, i) => (
                  <li key={i}>
                    <Cite documentId={place.documentId} documentFilename={place.documentFilename} page={place.page} />
                    <span className="muted"> — {place.quote}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </PlanLine>
        ))}
      </PlanSection>
      <form
        className="plan-add-phase"
        onSubmit={(e) => {
          e.preventDefault();
          add();
        }}
      >
        <label className="formfield-label" htmlFor="plan-add-phase-name">
          Phase name
        </label>
        <div className="plan-add-phase__row">
          <input id="plan-add-phase-name" className="field" value={name} disabled={saving} maxLength={100}
                 onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="btn" disabled={saving || !name.trim()}>
            Add phase
          </button>
        </div>
        <p className="scope-row__error" aria-live="polite">
          {error || null}
        </p>
      </form>
    </>
  );
}
```

- [ ] **Step 6: Run the tests**

Run: `npm test -- --run src/components/plan`
Expected: pass. In `PhaseSection.test.jsx`'s first case, `getByText("E-set.pdf, page 5")` finds the second place's `Cite` (the first place is the row's own cite: `E-set.pdf, page 2`). If `getByText` complains about multiple matches on `"Phase 1"`, the quote inside the places list is the duplicate — assert with `getAllByText("Phase 1")[0]` instead.

- [ ] **Step 7: Commit**

```bash
git add src/components/plan/PlanSection.jsx src/components/plan/QuestionLine.jsx src/components/plan/PhaseSection.jsx src/components/plan/QuestionLine.test.jsx src/components/plan/PhaseSection.test.jsx
git commit -m "Plan: sections, the open question with its four fields and an answer form, and the phasing section with Add a phase

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: `PlanWorkspace` — the screen, with Start takeoff

**Files:**
- Replace: `src/components/plan/PlanWorkspace.jsx` (the Task 9 placeholder)
- Modify (append at the end): `src/styles.css`
- Test: `src/components/plan/PlanWorkspace.test.jsx`

**Interfaces:**
- Consumes: `useWorkspaceContext()` → `{ store, projectId, project }`; store methods from Task 8 plus `store.startTakeoff(projectId)` and `store.decideScope`; `AppTopBar({ title, breadcrumb, primaryAction, children })`; `formatTimestamp(iso)` from `src/lib/format.js`; Tasks 10–11 components.
- Produces: the screen at `/projects/:id/plan`.

- [ ] **Step 1: Write the failing test**

`src/components/plan/PlanWorkspace.test.jsx`:

```jsx
/* PlanWorkspace — modeled on NotesWorkspace.test.jsx: the layout's
   context is mocked, the screen fetches the plan itself. */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import PlanWorkspace from "./PlanWorkspace.jsx";

const SCOPE = { id: "s1", kind: "excluded", text: "Site lighting.", editedText: null, status: "found", documentId: "d2", documentFilename: "E-set.pdf", page: 2, quote: "- Site lighting." };
const SPEC = { key: "spec:d1:260519", kind: "spec_section", text: "26 05 19 — Conductors", foundText: "26 05 19 — Conductors", editedText: null, status: "found",
  documentId: "d1", documentFilename: "Spec.pdf", page: null, quote: "SECTION 26 05 19", division: "26", sheetNumber: null, added: false, phaseId: null, places: [] };
const SCHED = { ...SPEC, key: "schedule:sheet:sh1", kind: "schedule", text: "Luminaire schedule", foundText: "Luminaire schedule", documentId: "d2", documentFilename: "E-set.pdf", page: 1, quote: "Luminaire schedule", division: null, sheetNumber: "E0.1" };
const PHASE = { ...SCHED, key: "phase:PHASE 1", kind: "phase", text: "Phase 1", foundText: "Phase 1", page: 3, quote: "Phase 1 power plan", sheetNumber: null,
  places: [{ documentId: "d2", documentFilename: "E-set.pdf", page: 3, quote: "Phase 1 power plan" }] };
const QUESTION = { key: "question:no_scale:sh2", status: "found", title: "No scale on E2.2", found: "E2.2 (Lighting plan) has no scale in its title block.",
  why: "Measured runs can't be given a length.", fix: "Set the scale on the blueprint.", where: "E2.2, title block.", documentId: "d2", documentFilename: "E-set.pdf", noteId: null };

const plan = (o = {}) => ({ readAt: "2026-09-21T10:00:00Z", reading: false, hasDrawings: true, undecided: 5,
  scope: [SCOPE], specs: [SPEC], schedules: [SCHED], phases: [PHASE], questions: [QUESTION], ...o });

const scanned = () => plan({ undecided: 1, scope: [], specs: [], schedules: [], phases: [], questions: [{ ...QUESTION, key: "question:scanned:d2",
  title: "Pages that could not be read", found: "12 of 12 pages in Gerber.pdf are scanned images with no readable text." }] });

function makeStore(p = plan()) {
  return {
    getPlan: vi.fn().mockResolvedValue(p),
    decidePlanLine: vi.fn().mockImplementation((_pid, key, change) => Promise.resolve({ ...[SPEC, SCHED, PHASE].find((l) => l.key === key), ...change, status: change.status ?? "found" })),
    decideScope: vi.fn().mockImplementation((id, change) => Promise.resolve({ ...SCOPE, ...change, status: change.status ?? "found" })),
    answerPlanQuestion: vi.fn().mockResolvedValue({ ...QUESTION, status: "answered", noteId: "n1" }),
    addPlanPhase: vi.fn().mockResolvedValue({ ...PHASE, key: "phase:added:ph1", text: "Phase 2", foundText: "Phase 2", added: true, phaseId: "ph1", documentId: null, documentFilename: null, page: null, quote: null, places: [] }),
    removePlanPhase: vi.fn().mockResolvedValue(null),
    startTakeoff: vi.fn().mockResolvedValue({ runId: "r1" }),
  };
}

let context;
vi.mock("../project/useWorkspaceContext.js", () => ({ useWorkspaceContext: () => context }));

function mount(store = makeStore()) {
  context = { store, projectId: "p1", project: { id: "p1", name: "Gerber" }, me: { id: "u1", name: "Dana" }, snapshot: { sheets: [], items: [] } };
  render(
    <MemoryRouter initialEntries={["/projects/p1/plan"]}>
      <Routes>
        <Route path="/projects/:projectId/plan" element={<PlanWorkspace />} />
        <Route path="/projects/:projectId/processing" element={<p>processing</p>} />
      </Routes>
    </MemoryRouter>,
  );
  return store;
}

afterEach(() => vi.clearAllMocks());

describe("PlanWorkspace", () => {
  it("renders the six sections, the undecided count, and no quantities", async () => {
    mount();
    expect(await screen.findByRole("heading", { name: "Scope stated in the documents" })).toBeInTheDocument();
    for (const name of ["Specification sections", "Schedules and legends", "Phasing", "Exclusions", "Open questions"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("5 lines not yet decided")).toBeInTheDocument();
    expect(screen.getByText("26 05 19 — Conductors")).toBeInTheDocument();
    expect(screen.getByText("Luminaire schedule")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No scale on E2.2" })).toBeInTheDocument();
    // Exclusions is a second view of the excluded scope line.
    expect(screen.getAllByText("Site lighting.")).toHaveLength(2);
    expect(screen.queryByText(/\bEA\b|\bLF\b|quantity/i)).toBeNull();
  });

  it("renders the scanned-set case as five empty sentences and one question", async () => {
    mount(makeStore(scanned()));
    expect(await screen.findByText("No scope statements were found in the documents.")).toBeInTheDocument();
    expect(screen.getByText("No specification sections were found in the uploaded documents.")).toBeInTheDocument();
    expect(screen.getByText("No schedule or legend sheet was found in the drawing set.")).toBeInTheDocument();
    expect(screen.getByText("The documents do not name any phase.")).toBeInTheDocument();
    expect(screen.getByText("The documents do not state anything as excluded or by others.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pages that could not be read" })).toBeInTheDocument();
    expect(screen.getByText("12 of 12 pages in Gerber.pdf are scanned images with no readable text.")).toBeInTheDocument();
  });

  it("starts the takeoff and goes to processing; a run in flight counts as started", async () => {
    const store = mount();
    await userEvent.click(await screen.findByRole("button", { name: "Start takeoff" }));
    expect(store.startTakeoff).toHaveBeenCalledWith("p1");
    expect(await screen.findByText("processing")).toBeInTheDocument();
  });

  it("disables Start takeoff while a drawing set is reading, with the help copy, and polls", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const store = makeStore(plan({ reading: true }));
    store.getPlan.mockResolvedValueOnce(plan({ reading: true })).mockResolvedValue(plan());
    mount(store);
    const button = await screen.findByRole("button", { name: "Start takeoff" });
    expect(button).toBeDisabled();
    expect(screen.getByText("A drawing set is still being read. Wait for it to finish before starting the takeoff.")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(store.getPlan).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Start takeoff" })).toBeEnabled());
    vi.useRealTimers();
  });

  it("shows the server's refusal next to the button", async () => {
    const store = makeStore();
    store.startTakeoff.mockRejectedValue({ code: "drawings_still_reading", message: "A drawing set is still being read." });
    mount(store);
    await userEvent.click(await screen.findByRole("button", { name: "Start takeoff" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A drawing set is still being read.");
    expect(screen.queryByText("processing")).toBeNull();
  });

  // Every write is followed by a re-read (store.getPlan), so each of the
  // next four cases sets what that re-read answers before acting.
  it("a decision follows the server's answer and the undecided count drops", async () => {
    const store = mount();
    const specs = await screen.findByRole("region", { name: "Specification sections" });
    store.getPlan.mockResolvedValue(plan({ undecided: 4, specs: [{ ...SPEC, status: "confirmed" }] }));
    await userEvent.click(within(specs).getByRole("button", { name: "Confirm" }));
    expect(store.decidePlanLine).toHaveBeenCalledWith("p1", "spec:d1:260519", { status: "confirmed" });
    expect(await within(specs).findByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText("4 lines not yet decided")).toBeInTheDocument();
  });

  it("a scope decision made under Exclusions shows under Scope too", async () => {
    const store = mount();
    const exclusions = await screen.findByRole("region", { name: "Exclusions" });
    store.getPlan.mockResolvedValue(plan({ undecided: 4, scope: [{ ...SCOPE, status: "confirmed" }] }));
    await userEvent.click(within(exclusions).getByRole("button", { name: "Confirm" }));
    expect(store.decideScope).toHaveBeenCalledWith("s1", { status: "confirmed" });
    const scope = screen.getByRole("region", { name: "Scope stated in the documents" });
    expect(await within(scope).findByText("Confirmed")).toBeInTheDocument();
  });

  it("answers a question through the store and links to the note", async () => {
    const store = mount();
    store.getPlan.mockResolvedValue(plan({ undecided: 4, questions: [{ ...QUESTION, status: "answered", noteId: "n1" }] }));
    await userEvent.click(await screen.findByRole("button", { name: "Answer" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Your answer" }), "Use 1/8 inch.");
    await userEvent.click(screen.getByRole("button", { name: "Save answer" }));
    expect(store.answerPlanQuestion).toHaveBeenCalledWith("p1", "question:no_scale:sh2", "Use 1/8 inch.");
    expect(await screen.findByRole("link", { name: "See the note" })).toHaveAttribute("href", "/projects/p1/notes");
  });

  it("adds and removes a phase through the store", async () => {
    const store = mount();
    const ADDED = { ...PHASE, key: "phase:added:ph1", text: "Phase 2", foundText: "Phase 2", added: true, phaseId: "ph1",
      documentId: null, documentFilename: null, page: null, quote: null, places: [] };
    store.getPlan.mockResolvedValue(plan({ phases: [PHASE, ADDED] }));
    await userEvent.type(await screen.findByRole("textbox", { name: "Phase name" }), "Phase 2");
    await userEvent.click(screen.getByRole("button", { name: "Add phase" }));
    expect(store.addPlanPhase).toHaveBeenCalledWith("p1", "Phase 2");
    expect(await screen.findByText("Stated by you")).toBeInTheDocument();
    store.getPlan.mockResolvedValue(plan());
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(store.removePlanPhase).toHaveBeenCalledWith("p1", "ph1");
    await waitFor(() => expect(screen.queryByText("Stated by you")).toBeNull());
  });

  it("says to upload documents when there are none", async () => {
    mount(makeStore(plan({ hasDrawings: false, readAt: null, undecided: 0, scope: [], specs: [], schedules: [], phases: [], questions: [] })));
    expect(await screen.findByRole("link", { name: "Upload documents to build the plan" })).toHaveAttribute("href", "/projects/p1/documents");
    expect(screen.getByRole("button", { name: "Start takeoff" })).toBeDisabled();
  });

  it("says so when the plan can't be loaded", async () => {
    const store = makeStore();
    store.getPlan.mockRejectedValue({ code: "network", message: "down" });
    mount(store);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load the plan. Check the connection and try again.");
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npm test -- --run src/components/plan/PlanWorkspace.test.jsx`
Expected: most cases fail against the placeholder.

- [ ] **Step 3: Write `PlanWorkspace.jsx`**

```jsx
/* ============================================================
   PlanWorkspace.jsx — the project plan: what the documents say, for an
   electrical sub. docs/specs/project-plan-screen.md.

   Sits after Confirm drawings and before Processing, and owns Start
   takeoff. Everything on it is derived server-side on every read from
   what the read job stored; this screen fetches store.getPlan, polls
   while a drawing set is still being read (same 3 s screen D uses),
   and re-fetches after any write so the undecided count and the
   questions (which depend on the other sections) stay true.

   Six sections, one row shape (PlanLine). Scope and Exclusions are two
   views of the plan's one scope array -- a decision in either updates
   both. Nothing here is counted; no quantity appears.

   Start takeoff carries screen D's exact rules: disabled while a
   drawing set is reading (READING_HELP, the sentence the server also
   answers with), a run already in flight is treated as started, any
   other refusal is shown next to the button.
   ============================================================ */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";
import { formatTimestamp } from "../../lib/format.js";
import PlanLine from "./PlanLine.jsx";
import PlanSection from "./PlanSection.jsx";
import PhaseSection from "./PhaseSection.jsx";
import QuestionLine from "./QuestionLine.jsx";
import ScopeSection from "./ScopeSection.jsx";

const READ_POLL_MS = 3000;
const READING_HELP = "A drawing set is still being read. Wait for it to finish before starting the takeoff.";
const LOAD_FAILED = "Couldn't load the plan. Check the connection and try again.";

export default function PlanWorkspace() {
  const { store, projectId } = useWorkspaceContext();
  const navigate = useNavigate();
  const [plan, setPlan] = useState(null);
  const [state, setState] = useState("loading"); // loading | loaded | failed
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");

  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const load = useCallback(
    () =>
      store
        .getPlan(projectId)
        .then((p) => {
          if (!aliveRef.current) return;
          setPlan(p);
          setState("loaded");
        })
        .catch(() => {
          if (!aliveRef.current) return;
          setState((s) => (s === "loaded" ? s : "failed"));
        }),
    [store, projectId],
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!plan?.reading) return undefined;
    const t = setInterval(load, READ_POLL_MS);
    return () => clearInterval(t);
  }, [plan?.reading, load]);

  // Every write is followed by a re-read: a decision changes the
  // undecided count, an added phase silences a question, an answer
  // creates a note. The server is the one place the plan is assembled.
  const after = (promise) => promise.then((r) => load().then(() => r));

  const decideLine = (key, change) => after(store.decidePlanLine(projectId, key, change));
  const onScopeDecided = (updated) => {
    setPlan((p) => (p ? { ...p, scope: p.scope.map((s) => (s.id === updated.id ? updated : s)) } : p));
    load();
  };

  const canStart = state === "loaded" && plan.hasDrawings && !plan.reading && !starting;
  const start = () => {
    if (!canStart) return;
    setStarting(true);
    setStartError("");
    store
      .startTakeoff(projectId)
      .then(() => {
        if (!aliveRef.current) return;
        navigate(`/projects/${projectId}/processing`);
      })
      .catch((err) => {
        if (!aliveRef.current) return;
        if (err?.code === "run_in_flight") {
          navigate(`/projects/${projectId}/processing`);
          return;
        }
        setStarting(false);
        setStartError(err?.message || "Couldn't start the takeoff. Check the connection and try again.");
      });
  };

  const startButton = (
    <button type="button" className="btn btn--primary" disabled={!canStart}
            aria-describedby={plan?.reading ? "plan-start-help" : undefined} onClick={start}>
      Start takeoff
    </button>
  );

  let body;
  if (state === "loading") {
    body = <p className="muted">Reading the documents…</p>;
  } else if (state === "failed") {
    body = <p className="scope-state scope-state--failed" role="alert">{LOAD_FAILED}</p>;
  } else if (!plan.hasDrawings && plan.scope.length === 0 && plan.questions.length === 0) {
    body = (
      <p className="muted">
        <Link to={`/projects/${projectId}/documents`}>Upload documents to build the plan</Link>
      </p>
    );
  } else {
    body = (
      <>
        <ScopeSection store={store} projectId={projectId} statements={plan.scope} onDecided={onScopeDecided} />

        <PlanSection id="plan-specs-heading" title="Specification sections"
                     description="Every Division 26, 27, and 28 section found in the uploaded specifications and addenda."
                     emptyText="No specification sections were found in the uploaded documents.">
          {plan.specs.map((l) => <PlanLine key={l.key} line={l} onDecide={(c) => decideLine(l.key, c)} />)}
        </PlanSection>

        <PlanSection id="plan-schedules-heading" title="Schedules and legends"
                     description="Each schedule or legend sheet in the drawing set, and each schedule found on a plan sheet."
                     emptyText="No schedule or legend sheet was found in the drawing set.">
          {plan.schedules.map((l) => <PlanLine key={l.key} line={l} onDecide={(c) => decideLine(l.key, c)} />)}
        </PlanSection>

        <PhaseSection phases={plan.phases} onDecide={decideLine}
                      onAdd={(name) => after(store.addPlanPhase(projectId, name))}
                      onRemove={(phaseId) => after(store.removePlanPhase(projectId, phaseId))} />

        <ScopeSection store={store} projectId={projectId} statements={plan.scope} onDecided={onScopeDecided}
                      kinds={["excluded", "by_others"]} title="Exclusions" headingId="plan-exclusions-heading"
                      description="What the documents leave out of this bid, or leave to others. The same lines as under Scope; a decision here is the same decision."
                      emptyText="The documents do not state anything as excluded or by others." />

        <PlanSection id="plan-questions-heading" title="Open questions"
                     description="What the documents did not answer. An answer is saved as a note and read by the next takeoff run."
                     emptyText="Nothing is open.">
          {plan.questions.map((q) => (
            <QuestionLine key={q.key} question={q} notesHref={`/projects/${projectId}/notes`}
                          onAnswer={(body) => after(store.answerPlanQuestion(projectId, q.key, body))}
                          onDismiss={() => decideLine(q.key, { status: "dismissed" })}
                          onReopen={() => decideLine(q.key, { status: "found" })} />
          ))}
        </PlanSection>
      </>
    );
  }

  const undecided = plan?.undecided ?? 0;

  return (
    <>
      <AppTopBar title="Project plan" primaryAction={startButton}>
        <Link className="btn" to={`/projects/${projectId}/documents/confirm`}>Back to confirm drawings</Link>
      </AppTopBar>
      <div className="workspace-body">
        <div className="page plan-page">
          <p className="muted page-intro">
            What the documents say this bid is. Confirm each line, correct it, or dismiss it; the takeoff reads what you leave standing.
          </p>
          {state === "loaded" ? (
            <p className="plan-status tabular">
              {`${undecided} ${undecided === 1 ? "line" : "lines"} not yet decided`}
              {plan.readAt ? ` · Read ${formatTimestamp(plan.readAt)}` : null}
            </p>
          ) : null}
          <p id="plan-start-help" className="footer-help">{plan?.reading ? READING_HELP : null}</p>
          {startError ? <p className="scope-state scope-state--failed" role="alert">{startError}</p> : null}
          {body}
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 4: Append the styles**

At the END of `src/styles.css`:

```css
/* ==== stream F: plan ==== */
.plan-page { max-width: 960px; }
.plan-status { margin: 0 0 12px; font-size: 13px; color: var(--ink-2); }
.plan-section { margin-top: 16px; }
.plan-line .scope-row__head { flex-wrap: wrap; }
.plan-line__stated { font-size: 12px; color: var(--plum); }
.plan-cite { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-3); margin-left: auto; }
.plan-cite__link { display: inline-flex; align-items: center; gap: 3px; color: var(--blue); text-decoration: none; }
.plan-cite__link:hover, .plan-cite__link:focus-visible { text-decoration: underline; }
.plan-places { list-style: none; margin: 0 0 8px; padding: 0; font-size: 12.5px; display: flex; flex-direction: column; gap: 2px; }
.plan-places .plan-cite { margin-left: 0; }
.plan-question { list-style: none; }
.plan-question .warncard { margin: 0 0 10px; }
.warncard--question { border-color: var(--line-2); background: var(--paper-0); }
.plan-add-phase { margin: 8px 0 0; display: flex; flex-direction: column; gap: 6px; max-width: 420px; }
.plan-add-phase__row { display: flex; gap: 8px; }
.plan-add-phase__row .field { flex: 1; }
```

Check that `--blue`, `--plum`, `--ink-2`, `--ink-3`, `--line-2`, `--paper-0` exist at the top of `styles.css` (`grep -n "^  --blue\|^  --plum:\|^  --paper-0\|^  --line-2" src/styles.css`); if the primary hue is named differently (e.g. `--accent`), use that token. Never an inline hex.

- [ ] **Step 5: Run the tests and the build**

Run: `npm test -- --run src/components/plan && npm run build`
Expected: pass; build clean. If the `region` role queries fail, `<section aria-labelledby>` needs the heading to resolve — `PlanSection` and `ScopeSection` both set it; check the heading ids are unique on the page (`scope-heading` for Scope, `plan-exclusions-heading` for Exclusions).

- [ ] **Step 6: Look at it**

Start the dev server on port 5175 (`.claude/launch.json` may already have an entry; otherwise add one with `runtimeExecutable: "npm"`, `runtimeArgs: ["run", "dev", "--", "--port", "5175"]`, `port: 5175`), sign in, open a project with documents, and visit `/projects/<id>/plan`. Confirm: six sections render; a decision changes the count; a page link opens the PDF in a new tab at the page; the scanned case (upload one of the two raster sets) shows one question and five empty sentences. Take a screenshot for the final report.

- [ ] **Step 7: Commit**

```bash
git add src/components/plan/PlanWorkspace.jsx src/components/plan/PlanWorkspace.test.jsx src/styles.css
git commit -m "Plan: the project plan screen — six sections over one row shape, Start takeoff, polling while a set is read

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Confirm drawings hands off to the plan

**Files:**
- Modify: `src/components/documents/ConfirmDrawings.jsx`, `src/components/documents/ConfirmDrawings.test.jsx`

**Interfaces:**
- Consumes: nothing new. Produces: screen D's primary button *Review the plan* → `/projects/:id/plan`; no scope section on D; no Start takeoff on D.

- [ ] **Step 1: Update the tests first**

In `src/components/documents/ConfirmDrawings.test.jsx` (helpers: `makeStore(docs)` builds the store, `renderConfirm(store)` renders inside a router with a `/projects/:projectId/processing` route):

- Add a route next to the processing one: `<Route path="/projects/:projectId/plan" element={<p>plan</p>} />`.
- Remove `listScope` and `decideScope` from `makeStore`.
- Delete these cases outright — they test Start takeoff or the scope section, which now live on the plan and are covered by `PlanWorkspace.test.jsx` and `plan/ScopeSection.test.jsx`: *"disables Start while a document is still being read, and says why beneath it"*, *"keeps Start enabled while a specification is still being read, and disables it only for drawings"*, *"stays and shows the server's message when a start is refused because a set is still being read"*, *"mounts the scope section above the table"*, *"starts the takeoff through the store, then goes to processing"*, *"treats a run already in flight as started -- goes to processing, no error"*, *"stays and shows the server's message when nothing in the set could be read"*, *"shows any other failure's message inline and stays"*.
- Rename and adapt *"lists the uploaded documents and can start when a drawing set is present"* → *"lists the uploaded documents and hands off to the plan"*: its button assertion becomes `{ name: "Review the plan" }` (a link, so `getByRole("link", ...)`), and add at the end:

```jsx
    await userEvent.click(screen.getByRole("link", { name: "Review the plan" }));
    expect(await screen.findByText("plan")).toBeInTheDocument();
    expect(store.startTakeoff).not.toHaveBeenCalled();
```

- Adapt *"blocks starting when nothing is typed Drawings"* → *"still offers the plan when nothing is typed Drawings, and says what is missing"*: the *Review the plan* link is present and enabled (the plan itself says what is missing), the "No drawing set" warncard assertion stays. The case *"blocks processing, rather than merely flagging it, when nothing is a drawing set"* keeps its warncard `aria-label` assertion; drop any `toBeDisabled` on the button.
- Any remaining `{ name: "Start takeoff" }` becomes `{ name: "Review the plan" }` with role `link`.

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/documents/ConfirmDrawings.test.jsx`
Expected: the new case fails (button not found).

- [ ] **Step 3: Make the edit**

In `src/components/documents/ConfirmDrawings.jsx`:
- Remove the `import ScopeSection ...` line and the `<ScopeSection store={store} projectId={projectId} />` element.
- Remove `READING_HELP`, `starting`, `startError`, `canStart`, and the `start` function; remove the `useNavigate` import and `const navigate = useNavigate();` if nothing else uses them (check with grep before deleting).
- Both places that render the *Start takeoff* button (the `AppTopBar` `primaryAction` and the footer's `footer-primary` block) become:

```jsx
<Link className="btn btn--primary" to={`/projects/${projectId}/plan`}>
  Review the plan
</Link>
```

and the footer's `<p id="start-takeoff-help" ...>` element goes with them. Keep `drawingsReading` if the checklist or the reading indicator still uses it; otherwise remove it.
- In the header comment, replace the paragraph beginning `"Start takeoff" asks the server to start a run` with:

```
   "Review the plan" goes to the project plan (src/components/plan/),
   which owns Start takeoff and the rules that used to live here -- a
   drawing set still being read holds Start back there, with the same
   sentence the server answers with. The scope statements this screen
   used to show above the table live on the plan too, alongside the
   spec sections, schedules, phasing and open questions the plan
   derives from the same read.
```

- [ ] **Step 4: Run the tests and the build**

Run: `npm test -- --run src/components/documents && npm run build`
Expected: pass; build clean.

- [ ] **Step 5: Commit**

```bash
git add src/components/documents/ConfirmDrawings.jsx src/components/documents/ConfirmDrawings.test.jsx
git commit -m "Confirm drawings hands off to the project plan, which now owns Start takeoff and the scope statements

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: Full verification and the report

**Files:** none new.

- [ ] **Step 1: Backend suite**

Run: `cd api && ../.enginevenv/bin/python -m pytest -q 2>&1 | tail -15`
Expected: all green (baseline was all green; ~6 minutes). Any failure in a file this stream did not touch is still this stream's to explain — read it before deciding it is unrelated.

- [ ] **Step 2: Frontend suite and build**

Run: `npm test -- --run 2>&1 | tail -15 && npm run build 2>&1 | tail -5`
Expected: all green; build clean.

- [ ] **Step 3: Confirm nothing stray is staged and the branch is clean**

Run: `git status --short`
Expected: only `?? .enginevenv` and `?? bid_examples` (the symlinks, never added).

- [ ] **Step 4: Spec touch-up**

If anything in the build diverged from `docs/specs/project-plan-screen.md` (a field added to the wire, a copy change), edit the spec to match and commit it as `Spec: project plan — <what changed>`. Known divergences to record from this plan: the plan record carries `has_drawings` (the client's Start button needs it) and `PlanLineOut` carries `added` / `phase_id`; a question can be dismissed and reopened through the same PATCH as a line.

- [ ] **Step 5: Report**

Stop. Do not merge. In the final message list: what was built (one paragraph), the migration's revision id (`0026`, revising `0025`), every commit SHA on the branch since `895b7ae` (`git log --oneline 895b7ae..HEAD`), the test results, and the screenshot from Task 12.
