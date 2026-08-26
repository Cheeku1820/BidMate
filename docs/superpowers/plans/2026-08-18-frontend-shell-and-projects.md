# Frontend shell and projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-screen review prototype into a multi-project application with a navigation shell, a projects dashboard, project creation, and a project overview — with the existing review workspace re-homed inside it as one workspace among thirteen.

**Architecture:** The client gains client-side routing (`react-router-dom`) and a three-part shell: a company-level left navigation, a project-level workspace navigation, and an application-wide top bar that hosts save state, undo/redo, presence, and a per-workspace primary action slot. The API's `projects` table gains the fields the dashboard columns require, and `GET /projects` returns them plus per-project review counts in one aggregate query rather than N+1. Both store implementations gain `listProjects()` and `createProject()` behind the existing adapter, so seed mode keeps working with no API.

**Tech Stack:** React 18, Vite 5, `react-router-dom` 6, `lucide-react`, plain CSS with tokens; FastAPI, SQLAlchemy 2.0, Alembic, Postgres 16; Vitest + `@testing-library/react` on the client, pytest + httpx on the API.

## Global Constraints

These come from `CLAUDE.md`, `docs/superpowers/specs/2026-08-16-bidmate-frontend-product-design.md`, and `README.md`. Every task's requirements implicitly include this section.

- **Status is never colour alone.** Always hue + icon + text label.
- **Green appears only on estimator-approved content.** Not on "done processing," not on a successful upload, not on a completed project row.
- **The four status labels are fixed:** `Ready to review`, `Needs attention`, `Missing information`, `Estimator approved`. Do not add a fifth, rename one, or invent screen-local language.
- **Never surface model names, confidence percentages, or processing internals** anywhere in the interface.
- **No save buttons.** Everything autosaves; save state lives in the top bar as `Saving…`, `Saved [time]`, or `Couldn't save — retrying`.
- **Plain CSS with tokens at the top of `src/styles.css`.** No Tailwind, no CSS-in-JS. Add new colours as tokens, never as inline hex.
- **Use the stylesheet's actual conventions.** There is **no spacing scale** — `src/styles.css` uses literal px, so `var(--space-N)` does not exist. Tokens are `--paper-0/1`, `--surface`, `--canvas`, `--sheet`; `--line-1/2/3` for borders; `--ink-1/2/3` for text; `--blue`, `--green`, `--amber`, `--red` each with `-tint` and `-line` variants; `--r-sm/md/lg` for radii. Buttons are `.btn` plus `.btn--primary`, `.btn--danger`, `.btn--block`. **`.field` is already the input element itself** — never redefine it as a wrapper; new form wrappers are `.formfield`. A global `:focus-visible` rule already applies the focus ring, so do not add per-component focus outlines. Body text is 13–13.5px, labels and secondary text 12.5px — not rem.
- **React function components with hooks. No state library.** Shared state comes from the store through `src/lib/useReviewStore.js`.
- **`lucide-react` for interface icons.**
- **Tabular numerals** (`className="tabular"`) on every quantity, count, total, and date.
- **Sentence case for all interface copy.** No exclamation marks, no "successfully," no "please."
- **Seed mode never imports from the API path.** `src/lib/store/seed*.js` must not import `api.js` or `api-mapping.js`; deleting seed mode later must remain a matter of deleting those files and the branch in `src/lib/store/index.js`.
- **Desktop only.** Optimised at 1440px, usable at 1280px. Below 1024px the blueprint workspace shows a "use a larger screen to review drawings" message; the dashboard and overview may reflow but are not a mobile target.
- **WCAG 2.2 AA.** Visible focus rings on every control, persistent visible labels on every form field, `aria-label`s naming an element and its status, `prefers-reduced-motion` respected.
- **Single-key shortcuts are suppressed while focus is in a text field.**
- **`npm run build` must pass before every commit.**

---

## File Structure

**API — new and modified**

| File | Responsibility |
|---|---|
| `api/migrations/versions/0009_project_fields.py` | Create: adds the dashboard columns to `projects` |
| `api/app/takeoff/models.py` | Modify: `Project` gains the new columns |
| `api/app/takeoff/schemas.py` | Modify: `ProjectOut` gains dashboard fields; new `ProjectCreateIn`, `ProjectSummaryOut` |
| `api/app/takeoff/projects.py` | Create: the project list query with counts, and project creation |
| `api/app/takeoff/router.py` | Modify: `GET /projects` uses the new query; `POST /projects` added |
| `api/app/seed.py` | Modify: seed project carries the new fields |
| `api/tests/test_projects.py` | Create: list shape, count correctness, creation, tenancy |

**Client — new and modified**

| File | Responsibility |
|---|---|
| `src/App.jsx` | Modify: auth gate only, then hand to the router |
| `src/routes.jsx` | Create: the route table, one place |
| `src/components/shell/AppShell.jsx` | Create: the persistent frame — company nav, top bar, outlet |
| `src/components/shell/CompanyNav.jsx` | Create: left navigation (§4.1) |
| `src/components/shell/ProjectNav.jsx` | Create: the thirteen workspace tabs (§4.2) |
| `src/components/shell/AppTopBar.jsx` | Create: app-wide top bar with a primary-action slot (§4.3) |
| `src/components/projects/ProjectsDashboard.jsx` | Create: the projects table (§5.1) |
| `src/components/projects/ProjectsFilters.jsx` | Create: search, filter chips, sort |
| `src/components/projects/NewProject.jsx` | Create: the guided creation form (§6.1) |
| `src/components/projects/ProjectOverview.jsx` | Create: the project home (§6.2) |
| `src/components/Workspace.jsx` | Modify: takes `projectId` from the route; loses its own top bar |
| `src/components/TopBar.jsx` | Modify: becomes the review workspace's primary-action content |
| `src/lib/store/seed-projects.js` | Create: seed mode's project list and creation |
| `src/lib/store/seed.js` | Modify: spreads in `seed-projects` |
| `src/lib/store/api.js` | Modify: `listProjects`, `createProject`; project id comes from the route |
| `src/lib/store/api-mapping.js` | Modify: maps the new project wire shape |
| `src/lib/store/contract.test.js` | Modify: both stores assert the new methods |
| `src/lib/projectStage.js` | Create: derives stage and review progress from counts |
| `src/lib/projectStage.test.js` | Create |
| `src/styles.css` | Modify: shell, table, and form tokens and styles |

---

### Task 1: Project fields — migration, model, seed

**Files:**
- Create: `api/migrations/versions/0009_project_fields.py`
- Modify: `api/app/takeoff/models.py:66-73`
- Modify: `api/app/seed.py:254-256`
- Test: `api/tests/test_projects.py`

**Interfaces:**
- Consumes: nothing — this is the first task.
- Produces: `Project` model columns `number: str`, `customer: str`, `location: str`, `bid_due_date: date | None`, `estimator_user_id: uuid.UUID | None`, `stage: str`, `archived_at: datetime | None`, `updated_at: datetime`. Stage values are exactly `"setup" | "documents" | "processing" | "review" | "pricing" | "export" | "complete"`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_projects.py
import datetime
import uuid

from app.takeoff.models import Project


def test_project_carries_dashboard_fields(db_session, org):
    """The dashboard columns in spec §5.1 need somewhere to live. A project
    with no bid date and no assigned estimator is valid -- both are optional
    at creation (spec §6.1) -- so the columns are nullable rather than
    defaulted to a fake date."""
    project = Project(
        org_id=org.id,
        name="Riverside Medical Center - Bldg C",
        number="26-0418",
        customer="Hensel Phelps",
        location="Sacramento, CA",
        bid_due_date=datetime.date(2026, 9, 14),
        estimator_user_id=None,
        stage="review",
    )
    db_session.add(project)
    db_session.flush()

    assert project.number == "26-0418"
    assert project.customer == "Hensel Phelps"
    assert project.location == "Sacramento, CA"
    assert project.bid_due_date == datetime.date(2026, 9, 14)
    assert project.estimator_user_id is None
    assert project.stage == "review"
    assert project.archived_at is None
    assert project.updated_at is not None


def test_project_defaults_are_empty_not_null(db_session, org):
    """A project created from the minimal form (name and address only) must
    still render every dashboard column without the table printing 'None'.
    Empty string beats NULL for the text columns for exactly that reason."""
    project = Project(org_id=org.id, name="Untitled bid")
    db_session.add(project)
    db_session.flush()

    assert project.number == ""
    assert project.customer == ""
    assert project.location == ""
    assert project.stage == "setup"
    assert project.bid_due_date is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm api pytest tests/test_projects.py -v`
Expected: FAIL with `TypeError: 'number' is an invalid keyword argument for Project`

- [ ] **Step 3: Add the columns to the model**

In `api/app/takeoff/models.py`, replace the `Project` class body:

```python
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    revision_set_label: Mapped[str] = mapped_column(String(300), default="")
    # Spec §5.1's dashboard columns. Text columns default to "" rather than
    # NULL so the table never has to render a null guard per cell; the two
    # genuinely optional facts (bid date, assigned estimator) stay nullable
    # because spec §6.1 makes both optional at creation and a fabricated
    # date would read as real.
    number: Mapped[str] = mapped_column(String(100), default="", server_default="")
    customer: Mapped[str] = mapped_column(String(300), default="", server_default="")
    location: Mapped[str] = mapped_column(String(300), default="", server_default="")
    bid_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The workflow position from spec §1's workspace list, collapsed to the
    # filter set spec §5.1 names. Not a status label -- the four review
    # labels describe items, this describes a project, and conflating them
    # is how a fifth status gets invented.
    stage: Mapped[str] = mapped_column(String(50), default="setup", server_default="setup")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Add `Date` and `date` to the existing imports at the top of the file if they are not already present (`Sheet` already uses both, so they should be).

- [ ] **Step 4: Write the migration**

```python
# api/migrations/versions/0009_project_fields.py
"""Project dashboard fields

Adds the columns spec §5.1's projects table renders. Text columns get a
server_default of '' so the migration is safe against existing rows
without a data backfill step.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("number", sa.String(100), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("customer", sa.String(300), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("location", sa.String(300), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("bid_due_date", sa.Date(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("estimator_user_id", postgresql_uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_estimator_user_id",
        "projects",
        "users",
        ["estimator_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_projects_estimator_user_id", "projects", ["estimator_user_id"])
    op.add_column(
        "projects",
        sa.Column("stage", sa.String(50), nullable=False, server_default="setup"),
    )
    op.add_column("projects", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "updated_at")
    op.drop_column("projects", "archived_at")
    op.drop_column("projects", "stage")
    op.drop_index("ix_projects_estimator_user_id", table_name="projects")
    op.drop_constraint("fk_projects_estimator_user_id", "projects", type_="foreignkey")
    op.drop_column("projects", "estimator_user_id")
    op.drop_column("projects", "bid_due_date")
    op.drop_column("projects", "location")
    op.drop_column("projects", "customer")
    op.drop_column("projects", "number")


def postgresql_uuid():
    from sqlalchemy.dialects.postgresql import UUID

    return UUID(as_uuid=True)
```

- [ ] **Step 5: Run the migration and the test**

```bash
docker compose run --rm api alembic upgrade head
docker compose run --rm api pytest tests/test_projects.py -v
```

Expected: migration reports `Running upgrade 0008 -> 0009`; both tests PASS.

- [ ] **Step 6: Give the seed project real values**

In `api/app/seed.py`, replace the `Project(...)` construction:

```python
    project = Project(
        id=PROJECT_ID,
        org_id=org.id,
        name="Meridian Distribution Center",
        number="26-0207",
        customer="Bellweather Construction",
        location="Stockton, CA",
        bid_due_date=date.today() + timedelta(days=21),
        stage="review",
        revision_set_label="E1.1 Rev 3 · E2.1 Rev 2 · E3.1 Rev 1",
    )
```

Add `from datetime import date, timedelta` to `api/app/seed.py`'s imports if not present. A relative bid date keeps the seed honest however long after seeding it is opened — a hardcoded date silently becomes a project that was due last year.

- [ ] **Step 7: Verify the seed still runs**

```bash
docker compose run --rm -e SEED_EMAIL="you@example.com" -e SEED_PASSWORD="choose-a-password" api python -m app.seed
```

Expected: completes without error. Then `docker compose run --rm api pytest tests/test_seed.py -v` PASSES.

- [ ] **Step 8: Commit**

```bash
git add api/migrations/versions/0009_project_fields.py api/app/takeoff/models.py api/app/seed.py api/tests/test_projects.py
git commit -m "Add the project dashboard fields the projects table renders"
```

---

### Task 2: The projects list query

**Files:**
- Create: `api/app/takeoff/projects.py`
- Modify: `api/app/takeoff/schemas.py:100-108`
- Modify: `api/app/takeoff/router.py`
- Test: `api/tests/test_projects.py`

**Interfaces:**
- Consumes: `Project` columns from Task 1.
- Produces: `list_projects(db, org_id, *, include_archived: bool = False) -> list[ProjectRow]`, where `ProjectRow` is a dataclass carrying every `Project` column plus `items_total: int`, `items_approved: int`, `warnings_open: int`, `missing_info: int`, `estimator_name: str | None`. `GET /api/projects` returns `list[ProjectOut]` with those fields in camelCase.

- [ ] **Step 1: Write the failing test**

```python
# append to api/tests/test_projects.py

def test_projects_list_returns_counts_in_one_query(client, seeded_org, capture_queries):
    """Review progress and outstanding warnings are dashboard columns
    (spec §5.1), so they must come back with the list. The count assertion
    is the point of the test: a per-row follow-up query is invisible with
    one seeded project and quadratic with fifty."""
    with capture_queries() as queries:
        res = client.get("/api/projects")

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    row = body[0]

    assert row["name"] == "Meridian Distribution Center"
    assert row["number"] == "26-0207"
    assert row["customer"] == "Bellweather Construction"
    assert row["location"] == "Stockton, CA"
    assert row["stage"] == "review"
    assert row["itemsTotal"] == 12
    assert row["itemsApproved"] == 0
    assert row["missingInfo"] >= 1

    select_count = sum(1 for q in queries if q.lower().lstrip().startswith("select"))
    assert select_count <= 2, f"expected one list query (plus the session lookup), got {select_count}"


def test_projects_list_excludes_other_orgs(client, other_org_project):
    """Tenancy is enforced at the data layer, not by the caller remembering
    to filter (ROADMAP.md §2.3)."""
    res = client.get("/api/projects")
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()}
    assert str(other_org_project.id) not in ids


def test_projects_list_excludes_archived_by_default(client, archived_project):
    res = client.get("/api/projects")
    assert str(archived_project.id) not in {row["id"] for row in res.json()}

    res = client.get("/api/projects?includeArchived=true")
    assert str(archived_project.id) in {row["id"] for row in res.json()}
```

Add a `capture_queries` fixture to `api/tests/conftest.py`:

```python
import contextlib

import pytest
from sqlalchemy import event


@pytest.fixture
def capture_queries(db_engine):
    """Records the SQL a block issues, so a test can assert that a list
    endpoint did not fall into N+1."""

    @contextlib.contextmanager
    def _capture():
        statements: list[str] = []

        def before_cursor_execute(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        event.listen(db_engine, "before_cursor_execute", before_cursor_execute)
        try:
            yield statements
        finally:
            event.remove(db_engine, "before_cursor_execute", before_cursor_execute)

    return _capture
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm api pytest tests/test_projects.py -v -k "list"`
Expected: FAIL with `KeyError: 'number'` — `ProjectOut` still carries only id, name, and revision label.

- [ ] **Step 3: Write the query module**

```python
# api/app/takeoff/projects.py
"""The projects list, assembled in one query.

Spec §5.1's dashboard renders review progress and outstanding warnings per
row. Those are aggregates over `items`, and fetching them per project is
the classic N+1 -- invisible against the one seeded project, quadratic
against a firm with fifty live bids. So the counts are computed with
correlated scalar subqueries in the same statement as the list.

The counts deliberately mirror the item-level rules rather than
reimplementing them: `items_approved` counts `status = 'approved'`, which
is the same predicate the totals query uses, and a rejected item is
excluded everywhere because rejection means "not in this takeoff" rather
than "not yet reviewed".
"""

from __future__ import annotations

import dataclasses
import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.identity.models import User
from app.takeoff.models import Item, Project, Sheet


@dataclasses.dataclass(frozen=True)
class ProjectRow:
    id: uuid.UUID
    name: str
    number: str
    customer: str
    location: str
    bid_due_date: datetime.date | None
    stage: str
    revision_set_label: str
    archived_at: datetime.datetime | None
    updated_at: datetime.datetime
    estimator_name: str | None
    items_total: int
    items_approved: int
    warnings_open: int
    missing_info: int


def _live_items(project_id_column):
    """Items that belong to a project's current takeoff: not rejected, and
    not on a superseded sheet. ROADMAP.md invariant 2 -- superseded sheets
    never contribute -- applies to these counts exactly as it does to
    totals, and enforcing it here rather than in the caller is the whole
    reason that invariant is written down."""
    return (
        select(Item.id)
        .join(Sheet, Sheet.id == Item.sheet_id)
        .where(
            Sheet.project_id == project_id_column,
            Sheet.superseded_at.is_(None),
            Item.rejected_at.is_(None),
        )
    )


def list_projects(
    db: Session, org_id: uuid.UUID, *, include_archived: bool = False
) -> list[ProjectRow]:
    live = _live_items(Project.id)

    items_total = select(func.count()).select_from(live.subquery()).scalar_subquery()
    items_approved = (
        select(func.count())
        .select_from(live.where(Item.status == "approved").subquery())
        .scalar_subquery()
    )
    warnings_open = (
        select(func.count())
        .select_from(live.where(Item.status == "attention").subquery())
        .scalar_subquery()
    )
    missing_info = (
        select(func.count())
        .select_from(live.where(Item.status == "missing").subquery())
        .scalar_subquery()
    )

    stmt = (
        select(
            Project,
            User.display_name.label("estimator_name"),
            items_total.label("items_total"),
            items_approved.label("items_approved"),
            warnings_open.label("warnings_open"),
            missing_info.label("missing_info"),
        )
        .outerjoin(User, User.id == Project.estimator_user_id)
        .where(Project.org_id == org_id)
        .order_by(Project.updated_at.desc())
    )
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))

    rows = []
    for project, estimator_name, total, approved, attention, missing in db.execute(stmt):
        rows.append(
            ProjectRow(
                id=project.id,
                name=project.name,
                number=project.number,
                customer=project.customer,
                location=project.location,
                bid_due_date=project.bid_due_date,
                stage=project.stage,
                revision_set_label=project.revision_set_label,
                archived_at=project.archived_at,
                updated_at=project.updated_at,
                estimator_name=estimator_name,
                items_total=total,
                items_approved=approved,
                warnings_open=attention,
                missing_info=missing,
            )
        )
    return rows
```

If `User` has no `display_name` column, use the column that already carries a human name; check `api/app/identity/models.py` and use that name consistently in the schema and tests.

- [ ] **Step 4: Extend the schema**

In `api/app/takeoff/schemas.py`, replace `ProjectOut`:

```python
class ProjectOut(BaseModel):
    """The row shape for `GET /projects` -- spec §5.1's dashboard columns,
    plus the counts that back the review-progress and warnings columns.
    Deliberately not the project's full detail; that is ProjectDetailOut."""

    id: uuid.UUID
    name: str
    number: str
    customer: str
    location: str
    bid_due_date: date | None
    stage: str
    revision_set_label: str
    archived_at: datetime | None
    updated_at: datetime
    estimator_name: str | None
    items_total: int
    items_approved: int
    warnings_open: int
    missing_info: int

    model_config = MODEL_CONFIG
```

`MODEL_CONFIG` already carries the camelCase alias generator used elsewhere in this file; confirm it does, and if it does not, add `alias_generator=to_camel, populate_by_name=True` to this model so the client receives `bidDueDate`, `itemsTotal`, and the rest in camelCase. The store contract is camelCase throughout (`src/lib/store/contract.test.js`).

Add `date` to the `datetime` imports at the top of the file if absent.

- [ ] **Step 5: Wire the route**

In `api/app/takeoff/router.py`, replace the `GET /projects` handler:

```python
@router.get("/projects", response_model=list[ProjectOut])
def get_projects(
    includeArchived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ProjectOut]:
    rows = list_projects(db, user.org_id, include_archived=includeArchived)
    return [ProjectOut.model_validate(row, from_attributes=True) for row in rows]
```

Add `from app.takeoff.projects import list_projects` to the imports.

- [ ] **Step 6: Run the tests**

Run: `docker compose run --rm api pytest tests/test_projects.py -v`
Expected: all PASS, including the `select_count <= 2` assertion.

- [ ] **Step 7: Run the whole API suite**

Run: `docker compose run --rm api pytest -q`
Expected: PASS. `tests/test_tenancy.py` and `tests/test_snapshot.py` exercise the same router and must not regress.

- [ ] **Step 8: Commit**

```bash
git add api/app/takeoff/projects.py api/app/takeoff/schemas.py api/app/takeoff/router.py api/tests/test_projects.py api/tests/conftest.py
git commit -m "Return the projects list with review counts in one query"
```

---

### Task 3: Project creation

**Files:**
- Modify: `api/app/takeoff/projects.py`
- Modify: `api/app/takeoff/schemas.py`
- Modify: `api/app/takeoff/router.py`
- Test: `api/tests/test_projects.py`

**Interfaces:**
- Consumes: `ProjectRow`, `list_projects` from Task 2.
- Produces: `create_project(db, org_id, data: ProjectCreateIn, *, by_user_id) -> Project`, and `POST /api/projects` returning `ProjectOut` with status 201.

- [ ] **Step 1: Write the failing test**

```python
# append to api/tests/test_projects.py

def test_create_project_requires_only_name_and_location(client):
    """Spec §6.1: name and address required, everything else optional.
    A form that demands a bid date before an estimator has one is a form
    they route around."""
    res = client.post("/api/projects", json={"name": "Oakview High School", "location": "Modesto, CA"})

    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Oakview High School"
    assert body["stage"] == "setup"
    assert body["number"] == ""
    assert body["bidDueDate"] is None
    assert body["itemsTotal"] == 0


def test_create_project_rejects_blank_name(client):
    res = client.post("/api/projects", json={"name": "   ", "location": "Modesto, CA"})
    assert res.status_code == 422


def test_created_project_belongs_to_the_callers_org(client, signed_in_user, db_session):
    res = client.post("/api/projects", json={"name": "Oakview High School", "location": "Modesto, CA"})
    created = db_session.get(Project, uuid.UUID(res.json()["id"]))
    assert created.org_id == signed_in_user.org_id


def test_created_project_appears_in_the_list(client):
    client.post("/api/projects", json={"name": "Oakview High School", "location": "Modesto, CA"})
    names = {row["name"] for row in client.get("/api/projects").json()}
    assert "Oakview High School" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm api pytest tests/test_projects.py -v -k create`
Expected: FAIL with 405 Method Not Allowed — `POST /api/projects` does not exist.

- [ ] **Step 3: Add the input schema**

In `api/app/takeoff/schemas.py`:

```python
class ProjectCreateIn(BaseModel):
    """Spec §6.1's guided form. Advanced labor and pricing settings are
    deliberately absent -- the spec excludes them from creation, and a
    field here is a field an estimator has to answer before they can start."""

    name: str = Field(min_length=1, max_length=300)
    location: str = Field(min_length=1, max_length=300)
    number: str = Field(default="", max_length=100)
    customer: str = Field(default="", max_length=300)
    bid_due_date: date | None = None
    estimator_user_id: uuid.UUID | None = None
    construction_type: str = Field(default="", max_length=100)

    @field_validator("name", "location")
    @classmethod
    def not_only_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    model_config = MODEL_CONFIG
```

Add `Field` and `field_validator` to the `pydantic` imports.

`construction_type` is accepted and ignored for now — spec §6.1 lists it with a "Not sure" option, and accepting it from the first version means the form does not change shape when it gains a column.

- [ ] **Step 4: Write the creation function**

Append to `api/app/takeoff/projects.py`:

```python
def create_project(
    db: Session,
    org_id: uuid.UUID,
    *,
    name: str,
    location: str,
    number: str = "",
    customer: str = "",
    bid_due_date: datetime.date | None = None,
    estimator_user_id: uuid.UUID | None = None,
) -> Project:
    """Creates a project in the caller's org. Stage starts at 'setup'
    because no document has been uploaded yet -- spec §1's workspace order
    starts at Overview, and a project claiming to be in review before it
    has a sheet would misreport on the dashboard."""
    project = Project(
        org_id=org_id,
        name=name,
        location=location,
        number=number,
        customer=customer,
        bid_due_date=bid_due_date,
        estimator_user_id=estimator_user_id,
        stage="setup",
    )
    db.add(project)
    db.flush()
    return project


def project_row(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> ProjectRow:
    """A single row in the same shape the list returns, so creation can
    respond with exactly what the dashboard will later render rather than a
    second, subtly different project shape."""
    for row in list_projects(db, org_id, include_archived=True):
        if row.id == project_id:
            return row
    raise LookupError(project_id)
```

- [ ] **Step 5: Wire the route**

In `api/app/takeoff/router.py`:

```python
@router.post("/projects", response_model=ProjectOut, status_code=201)
def post_project(
    payload: ProjectCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ProjectOut:
    project = create_project(
        db,
        user.org_id,
        name=payload.name,
        location=payload.location,
        number=payload.number,
        customer=payload.customer,
        bid_due_date=payload.bid_due_date,
        estimator_user_id=payload.estimator_user_id,
    )
    db.commit()
    row = project_row(db, user.org_id, project.id)
    return ProjectOut.model_validate(row, from_attributes=True)
```

Add `create_project, project_row` to the `app.takeoff.projects` import and `ProjectCreateIn` to the schemas import.

- [ ] **Step 6: Run the tests**

Run: `docker compose run --rm api pytest tests/test_projects.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add api/app/takeoff/projects.py api/app/takeoff/schemas.py api/app/takeoff/router.py api/tests/test_projects.py
git commit -m "Add project creation behind the guided form's field set"
```

---

### Task 4: Store methods — listProjects and createProject

**Files:**
- Create: `src/lib/store/seed-projects.js`
- Modify: `src/lib/store/seed.js:172-181`
- Modify: `src/lib/store/api.js:281-294`
- Modify: `src/lib/store/api-mapping.js`
- Modify: `src/lib/store/api.fakebackend.js`
- Test: `src/lib/store/contract.test.js`

**Interfaces:**
- Consumes: `GET /api/projects`, `POST /api/projects` from Tasks 2 and 3.
- Produces: on both stores, `listProjects({ includeArchived = false } = {}) -> Promise<Project[]>` and `createProject({ name, location, number, customer, bidDueDate, estimatorUserId }) -> Promise<Project>`. A `Project` is `{ id, name, number, customer, location, bidDueDate, stage, revisionSetLabel, archivedAt, updatedAt, estimatorName, itemsTotal, itemsApproved, warningsOpen, missingInfo }` — camelCase, `bidDueDate` an ISO date string or `null`, every count a number.

- [ ] **Step 1: Write the failing test**

Append to `src/lib/store/contract.test.js`, inside the block that runs against both stores:

```js
describe("projects", () => {
  it("lists projects with camelCase fields and numeric counts", async () => {
    const projects = await store.listProjects();

    expect(Array.isArray(projects)).toBe(true);
    expect(projects.length).toBeGreaterThan(0);

    const project = projects[0];
    expect(typeof project.id).toBe("string");
    expect(typeof project.name).toBe("string");
    expect(typeof project.number).toBe("string");
    expect(typeof project.customer).toBe("string");
    expect(typeof project.location).toBe("string");
    expect(typeof project.stage).toBe("string");
    // Counts are numbers, not strings. The dashboard does arithmetic on
    // them (approved / total) and a string here produces "012" rather
    // than a percentage.
    expect(typeof project.itemsTotal).toBe("number");
    expect(typeof project.itemsApproved).toBe("number");
    expect(typeof project.warningsOpen).toBe("number");
    expect(typeof project.missingInfo).toBe("number");
    // Null, never a fabricated date -- an invented bid deadline is worse
    // than a blank cell.
    expect(project.bidDueDate === null || typeof project.bidDueDate === "string").toBe(true);
  });

  it("counts never exceed the total", async () => {
    for (const project of await store.listProjects()) {
      expect(project.itemsApproved).toBeLessThanOrEqual(project.itemsTotal);
      expect(project.warningsOpen).toBeLessThanOrEqual(project.itemsTotal);
      expect(project.missingInfo).toBeLessThanOrEqual(project.itemsTotal);
    }
  });

  it("creates a project that then appears in the list", async () => {
    const created = await store.createProject({
      name: "Oakview High School",
      location: "Modesto, CA",
    });

    expect(created.id).toBeTruthy();
    expect(created.name).toBe("Oakview High School");
    expect(created.stage).toBe("setup");
    expect(created.itemsTotal).toBe(0);

    const names = (await store.listProjects()).map((p) => p.name);
    expect(names).toContain("Oakview High School");
  });
});
```

Add `"listProjects", "createProject"` to the `METHODS` array at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- contract`
Expected: FAIL with `store.listProjects is not a function`.

- [ ] **Step 3: Write the seed implementation**

```js
// src/lib/store/seed-projects.js
/* ============================================================
   seed-projects.js — the projects list for seed mode.

   The seed fixture is one project (src/lib/store/seed-fixture.js), and
   before this file the seed store had no concept of a project at all.
   Rather than invent a second fixture, the seeded project is derived
   from the snapshot that already exists, so its counts cannot drift
   from what the review workspace shows for the same project.

   Projects created here live in localStorage alongside the rest of seed
   state. They have no sheets and no items, which is honest: seed mode
   has no ingestion, so a new project genuinely is empty.

   Imports nothing from api.js or api-mapping.js -- deleting seed mode
   must stay a matter of deleting these files (CLAUDE.md, "Sync is
   single-machine").
   ============================================================ */

import { storageRead, storageWrite } from "./local-transport.js";

const CREATED_KEY = "takeoff.seed.projects";
const SEED_PROJECT_ID = "seed-project";

function readCreated() {
  const raw = storageRead(CREATED_KEY);
  return Array.isArray(raw) ? raw : [];
}

function emptyCounts() {
  return { itemsTotal: 0, itemsApproved: 0, warningsOpen: 0, missingInfo: 0 };
}

/** The one fixture project, with its counts read off the live snapshot so
 *  the dashboard and the review workspace can never disagree. */
function fixtureProject(snapshot) {
  const live = snapshot.items.filter((item) => !item.rejected);
  return {
    id: SEED_PROJECT_ID,
    name: snapshot.project?.name ?? "Meridian Distribution Center",
    number: "26-0207",
    customer: "Bellweather Construction",
    location: "Stockton, CA",
    bidDueDate: null,
    stage: "review",
    revisionSetLabel: snapshot.project?.revisionSetLabel ?? "",
    archivedAt: null,
    updatedAt: new Date().toISOString(),
    estimatorName: null,
    itemsTotal: live.length,
    itemsApproved: live.filter((item) => item.status === "approved").length,
    warningsOpen: live.filter((item) => item.status === "attention").length,
    missingInfo: live.filter((item) => item.status === "missing").length,
  };
}

export function createSeedProjects({ getSnapshot }) {
  async function listProjects({ includeArchived = false } = {}) {
    const snapshot = await getSnapshot();
    const created = readCreated().filter((p) => includeArchived || !p.archivedAt);
    return [fixtureProject(snapshot), ...created];
  }

  async function createProject({
    name,
    location,
    number = "",
    customer = "",
    bidDueDate = null,
    estimatorUserId = null,
  }) {
    if (!name?.trim()) throw { code: "invalid_request", message: "Enter a project name." };
    if (!location?.trim()) throw { code: "invalid_request", message: "Enter a project address." };

    const project = {
      id: `seed-${crypto.randomUUID()}`,
      name: name.trim(),
      number,
      customer,
      location: location.trim(),
      bidDueDate,
      stage: "setup",
      revisionSetLabel: "",
      archivedAt: null,
      updatedAt: new Date().toISOString(),
      estimatorName: null,
      estimatorUserId,
      ...emptyCounts(),
    };
    storageWrite(CREATED_KEY, [...readCreated(), project]);
    return project;
  }

  return { listProjects, createProject };
}
```

Check `local-transport.js` for the exact names of its read and write helpers and use those; the names above are the expected ones but the file is the authority.

- [ ] **Step 4: Wire it into the seed store**

In `src/lib/store/seed.js`, import and spread it:

```js
import { createSeedProjects } from "./seed-projects.js";
```

and in the returned object:

```js
  const projects = createSeedProjects({ getSnapshot });

  return {
    me,
    getSnapshot,
    subscribe,
    setPresence,
    ...review,
    ...scale,
    ...undoing,
    ...projects,
  };
```

- [ ] **Step 5: Write the API implementation**

In `src/lib/store/api-mapping.js`, add:

```js
/** Wire shape -> store shape for a project row. The API already returns
 *  camelCase (schemas.py's alias generator), so this is a field allow-list
 *  rather than a rename: it keeps a field the API adds later from silently
 *  reaching the client before anything is designed to render it. */
export function mapProject(raw) {
  return {
    id: raw.id,
    name: raw.name,
    number: raw.number ?? "",
    customer: raw.customer ?? "",
    location: raw.location ?? "",
    bidDueDate: raw.bidDueDate ?? null,
    stage: raw.stage,
    revisionSetLabel: raw.revisionSetLabel ?? "",
    archivedAt: raw.archivedAt ?? null,
    updatedAt: raw.updatedAt,
    estimatorName: raw.estimatorName ?? null,
    itemsTotal: Number(raw.itemsTotal ?? 0),
    itemsApproved: Number(raw.itemsApproved ?? 0),
    warningsOpen: Number(raw.warningsOpen ?? 0),
    missingInfo: Number(raw.missingInfo ?? 0),
  };
}
```

In `src/lib/store/api.js`, add the two methods and export them:

```js
  async function listProjects({ includeArchived = false } = {}) {
    const query = includeArchived ? "?includeArchived=true" : "";
    const raw = await request(`/api/projects${query}`);
    return Array.isArray(raw) ? raw.map(mapProject) : [];
  }

  async function createProject({
    name,
    location,
    number = "",
    customer = "",
    bidDueDate = null,
    estimatorUserId = null,
  }) {
    const raw = await request("/api/projects", {
      method: "POST",
      body: {
        name,
        location,
        number,
        customer,
        bidDueDate,
        estimatorUserId,
      },
    });
    return mapProject(raw);
  }
```

Add `listProjects, createProject` to the returned object and `mapProject` to the `api-mapping.js` import.

- [ ] **Step 6: Teach the fake backend the new routes**

In `src/lib/store/api.fakebackend.js`, add handlers for `GET /api/projects` and `POST /api/projects` that delegate to the same seed store the file already wraps, converting the store's camelCase project back to the wire shape. The existing handlers in this file show the pattern; follow it exactly rather than inventing a second one.

- [ ] **Step 7: Run the tests**

Run: `npm test`
Expected: all PASS, including both stores through the shared `describe("projects")` block.

- [ ] **Step 8: Commit**

```bash
git add src/lib/store/
git commit -m "Add listProjects and createProject to both store implementations"
```

---

### Task 5: Stage and progress derivation

**Files:**
- Create: `src/lib/projectStage.js`
- Test: `src/lib/projectStage.test.js`

**Interfaces:**
- Consumes: the `Project` shape from Task 4.
- Produces: `STAGES` (ordered array of `{ key, label }`), `stageLabel(key) -> string`, `reviewProgress(project) -> { approved, total, percent }`, and `matchesFilter(project, filterKey) -> boolean` where `filterKey` is one of `"active" | "processing" | "needsReview" | "readyToExport" | "complete" | "archived"`.

- [ ] **Step 1: Write the failing test**

```js
// src/lib/projectStage.test.js
/* ============================================================
   projectStage.test.js — the dashboard's derived values.

   These live in a module rather than inside the table component because
   the same numbers appear on the project overview (spec §6.2) and would
   otherwise be computed twice and drift. Same reasoning as ROADMAP.md
   invariant 1 applied one level down.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { STAGES, matchesFilter, reviewProgress, stageLabel } from "./projectStage.js";

const project = (over = {}) => ({
  stage: "review",
  archivedAt: null,
  itemsTotal: 12,
  itemsApproved: 3,
  warningsOpen: 2,
  missingInfo: 1,
  ...over,
});

describe("reviewProgress", () => {
  it("reports approved out of total with a rounded percentage", () => {
    expect(reviewProgress(project())).toEqual({ approved: 3, total: 12, percent: 25 });
  });

  it("reports zero rather than NaN for an empty project", () => {
    // A project created but not yet processed has no items. Dividing by
    // zero here renders "NaN%" in a table column, which reads as a bug to
    // an estimator and is one.
    expect(reviewProgress(project({ itemsTotal: 0, itemsApproved: 0 }))).toEqual({
      approved: 0,
      total: 0,
      percent: 0,
    });
  });
});

describe("stageLabel", () => {
  it("returns sentence-case labels for every stage", () => {
    for (const stage of STAGES) {
      expect(stageLabel(stage.key)).toBe(stage.label);
      expect(stage.label[0]).toBe(stage.label[0].toUpperCase());
      expect(stage.label.slice(1)).toBe(stage.label.slice(1).toLowerCase());
    }
  });

  it("falls back to the raw key rather than throwing on an unknown stage", () => {
    // A stage added server-side before the client knows about it must not
    // blank the column.
    expect(stageLabel("negotiation")).toBe("negotiation");
  });
});

describe("matchesFilter", () => {
  it("excludes archived projects from every filter except archived", () => {
    const archived = project({ archivedAt: "2026-07-01T00:00:00Z" });
    expect(matchesFilter(archived, "active")).toBe(false);
    expect(matchesFilter(archived, "needsReview")).toBe(false);
    expect(matchesFilter(archived, "archived")).toBe(true);
  });

  it("treats needsReview as any unapproved work, not just the review stage", () => {
    expect(matchesFilter(project({ stage: "review" }), "needsReview")).toBe(true);
    expect(
      matchesFilter(project({ stage: "pricing", itemsApproved: 12, itemsTotal: 12 }), "needsReview"),
    ).toBe(false);
  });

  it("holds readyToExport back while any missing information remains", () => {
    // Missing information blocks completion with no override (CLAUDE.md).
    // A dashboard that says "ready to export" over a blocking item is
    // telling the estimator something the finish-review dialog will
    // immediately contradict.
    const blocked = project({ stage: "export", itemsApproved: 11, itemsTotal: 12, missingInfo: 1 });
    expect(matchesFilter(blocked, "readyToExport")).toBe(false);

    const clear = project({ stage: "export", itemsApproved: 12, itemsTotal: 12, missingInfo: 0 });
    expect(matchesFilter(clear, "readyToExport")).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- projectStage`
Expected: FAIL with `Failed to resolve import "./projectStage.js"`.

- [ ] **Step 3: Write the module**

```js
// src/lib/projectStage.js
/* ============================================================
   projectStage.js — derived dashboard values.

   The projects table (spec §5.1) and the project overview (spec §6.2)
   both show stage, review progress, and outstanding warnings. Deriving
   them in one place is the same discipline ROADMAP.md invariant 1
   applies to totals: two implementations of one number drift, and the
   estimator has no way to tell which is right.
   ============================================================ */

/** Spec §1's workspace order, collapsed to the positions a project can
 *  actually be reported at. Sentence case, per CLAUDE.md. */
export const STAGES = [
  { key: "setup", label: "Setup" },
  { key: "documents", label: "Documents" },
  { key: "processing", label: "Processing" },
  { key: "review", label: "Review" },
  { key: "pricing", label: "Pricing" },
  { key: "export", label: "Export" },
  { key: "complete", label: "Complete" },
];

const BY_KEY = new Map(STAGES.map((stage) => [stage.key, stage.label]));

/** Unknown stages return their own key rather than throwing or blanking:
 *  the server may learn a stage before this client does, and an empty
 *  column reads as a bug. */
export function stageLabel(key) {
  return BY_KEY.get(key) ?? key;
}

export function reviewProgress(project) {
  const total = project.itemsTotal ?? 0;
  const approved = project.itemsApproved ?? 0;
  return {
    approved,
    total,
    percent: total === 0 ? 0 : Math.round((approved / total) * 100),
  };
}

export function matchesFilter(project, filterKey) {
  const archived = Boolean(project.archivedAt);
  if (filterKey === "archived") return archived;
  if (archived) return false;

  const { approved, total } = reviewProgress(project);
  const fullyApproved = total > 0 && approved === total;

  switch (filterKey) {
    case "active":
      return project.stage !== "complete";
    case "processing":
      return project.stage === "processing";
    case "needsReview":
      return total > 0 && !fullyApproved;
    case "readyToExport":
      // Missing information blocks completion with no override
      // (CLAUDE.md), so a project carrying any is not ready to export no
      // matter what stage it claims.
      return fullyApproved && (project.missingInfo ?? 0) === 0;
    case "complete":
      return project.stage === "complete";
    default:
      return true;
  }
}
```

- [ ] **Step 4: Run the tests**

Run: `npm test -- projectStage`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib/projectStage.js src/lib/projectStage.test.js
git commit -m "Derive project stage, progress, and filters in one place"
```

---

### Task 6: Routing and the application shell

**Files:**
- Modify: `package.json`
- Create: `src/routes.jsx`
- Create: `src/components/shell/AppShell.jsx`
- Create: `src/components/shell/CompanyNav.jsx`
- Create: `src/components/shell/AppTopBar.jsx`
- Modify: `src/App.jsx`
- Modify: `src/components/Workspace.jsx`
- Modify: `src/styles.css`
- Test: `src/routes.test.jsx`

**Interfaces:**
- Consumes: `store.me()` and `store.listProjects()` from Task 4.
- Produces: routes `/projects`, `/projects/new`, `/projects/:projectId`, `/projects/:projectId/takeoff`; `<AppShell store={store} me={me} onSignedOut={fn} />` rendering `<Outlet />`; `useProjectId()` returning the current route's project id.

- [ ] **Step 1: Add the dependencies**

```bash
npm install react-router-dom@^6.26.0
npm install --save-dev @testing-library/react@^16.0.0 @testing-library/jest-dom@^6.5.0
```

`react-router-dom` rather than a hand-rolled router: thirteen project workspaces plus company-level screens is past the point where a bespoke matcher is the smaller thing to maintain, and back/forward and deep links to a specific project workspace are requirements (§4.2 keeps the current stage visible, which means it has to be addressable).

- [ ] **Step 2: Write the failing test**

```jsx
// src/routes.test.jsx
/* ============================================================
   routes.test.jsx — the route table resolves, and the shell renders
   around it. Not a rendering-detail test: the point is that adding a
   fourteenth workspace later is a row in one table rather than a change
   in four files.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes } from "react-router-dom";
import { appRoutes } from "./routes.jsx";

const store = {
  me: async () => ({ id: "u1", name: "Dana Whitfield" }),
  listProjects: async () => [],
  subscribe: () => () => {},
};

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>{appRoutes({ store, me: { id: "u1", name: "Dana Whitfield" }, onSignedOut: () => {} })}</Routes>
    </MemoryRouter>,
  );
}

describe("appRoutes", () => {
  it("renders the company navigation on a company-level route", async () => {
    renderAt("/projects");
    expect(await screen.findByRole("navigation", { name: /main/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /projects/i })).toBeTruthy();
  });

  it("redirects the root path to the projects dashboard", async () => {
    renderAt("/");
    expect(await screen.findByRole("heading", { name: /projects/i })).toBeTruthy();
  });

  it("shows a recovery path rather than a blank screen for an unknown route", async () => {
    // Spec §20: error copy names the user's recovery action. "Something
    // went wrong" alone is explicitly disallowed.
    renderAt("/projects/does-not-exist/nowhere");
    expect(await screen.findByRole("link", { name: /back to projects/i })).toBeTruthy();
  });
});
```

Add `setupFiles` to `vite.config.js`'s `test` block pointing at a new `src/setupTests.js` containing `import "@testing-library/jest-dom";`.

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- routes`
Expected: FAIL with `Failed to resolve import "./routes.jsx"`.

- [ ] **Step 4: Write the shell**

```jsx
// src/components/shell/CompanyNav.jsx
/* ============================================================
   CompanyNav.jsx — spec §4.1's persistent left navigation.

   Text labels alongside icons, never icon-only: spec §4.1 forbids
   hiding essential destinations behind icons, and CLAUDE.md's users are
   described as often uncomfortable with unfamiliar software. An
   unlabelled icon rail is exactly the kind of interface that costs them
   ten minutes and a phone call.
   ============================================================ */

import { NavLink } from "react-router-dom";
import { BookOpen, HelpCircle, LayoutGrid, Plug, Settings, Target } from "lucide-react";

const DESTINATIONS = [
  { to: "/projects", label: "Projects", Icon: LayoutGrid },
  { to: "/accuracy", label: "Accuracy", Icon: Target },
  { to: "/library", label: "Company library", Icon: BookOpen },
  { to: "/integrations", label: "Integrations", Icon: Plug },
  { to: "/settings", label: "Company settings", Icon: Settings },
  { to: "/help", label: "Help", Icon: HelpCircle },
];

export default function CompanyNav() {
  return (
    <nav className="company-nav" aria-label="Main">
      <div className="company-nav-brand">BidMate</div>
      <ul className="company-nav-list">
        {DESTINATIONS.map(({ to, label, Icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) => (isActive ? "company-nav-link is-active" : "company-nav-link")}
            >
              <Icon size={18} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
```

```jsx
// src/components/shell/AppTopBar.jsx
/* ============================================================
   AppTopBar.jsx — spec §4.3's persistent top bar.

   The review workspace already had a top bar carrying save state, undo,
   and presence. Those belong to the application rather than to one
   workspace, so they move here and the workspace supplies only its own
   primary action through the `primaryAction` slot. Save state stays in
   the bar because there are no save buttons anywhere (CLAUDE.md).
   ============================================================ */

export default function AppTopBar({ title, subtitle, saveState, children, primaryAction }) {
  return (
    <header className="app-top-bar">
      <div className="app-top-bar-identity">
        <span className="app-top-bar-title">{title}</span>
        {subtitle ? <span className="app-top-bar-subtitle">{subtitle}</span> : null}
      </div>
      <div className="app-top-bar-tools">
        {saveState ? (
          <span className="save-state" role="status" aria-live="polite">
            {saveState}
          </span>
        ) : null}
        {children}
        {primaryAction}
      </div>
    </header>
  );
}
```

```jsx
// src/components/shell/AppShell.jsx
/* ============================================================
   AppShell.jsx — the frame every signed-in screen renders inside.

   Holds the company navigation and the outlet. It deliberately does not
   own the top bar: a company-level screen and a project workspace put
   different things in it, so each route renders its own AppTopBar rather
   than the shell guessing.
   ============================================================ */

import { Outlet } from "react-router-dom";
import CompanyNav from "./CompanyNav.jsx";

export default function AppShell() {
  return (
    <div className="app-shell">
      <CompanyNav />
      <main className="app-shell-main">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Write the route table**

```jsx
// src/routes.jsx
/* ============================================================
   routes.jsx — one place that knows what URLs exist.

   Adding a workspace is a row here plus a component, not a change in
   four files. Screens that spec §1 lists but that are not built yet
   deliberately do not appear: a nav entry leading to an empty page is
   worse than one that is not there, and spec §20 requires error copy to
   name a recovery action.
   ============================================================ */

import { Navigate, Route } from "react-router-dom";
import AppShell from "./components/shell/AppShell.jsx";
import ProjectsDashboard from "./components/projects/ProjectsDashboard.jsx";
import NewProject from "./components/projects/NewProject.jsx";
import ProjectOverview from "./components/projects/ProjectOverview.jsx";
import Workspace from "./components/Workspace.jsx";
import NotFound from "./components/shell/NotFound.jsx";

export function appRoutes({ store, me, onSignedOut }) {
  return (
    <Route element={<AppShell />}>
      <Route index element={<Navigate to="/projects" replace />} />
      <Route path="/projects" element={<ProjectsDashboard store={store} me={me} onSignedOut={onSignedOut} />} />
      <Route path="/projects/new" element={<NewProject store={store} />} />
      <Route path="/projects/:projectId" element={<ProjectOverview store={store} me={me} />} />
      <Route
        path="/projects/:projectId/takeoff"
        element={<Workspace store={store} me={me} onSignedOut={onSignedOut} />}
      />
      <Route path="*" element={<NotFound />} />
    </Route>
  );
}
```

```jsx
// src/components/shell/NotFound.jsx
import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="empty-state">
      <h1>That page isn't available</h1>
      <p>The link may be out of date, or the project may have been archived.</p>
      <Link className="btn btn--primary" to="/projects">
        Back to projects
      </Link>
    </div>
  );
}
```

- [ ] **Step 6: Rewrite App.jsx as the auth gate plus the router**

```jsx
// src/App.jsx
import { useEffect, useState } from "react";
import { BrowserRouter, Routes } from "react-router-dom";
import { createStore } from "./lib/store/index.js";
import Login from "./components/Login.jsx";
import { appRoutes } from "./routes.jsx";

/* ============================================================
   App.jsx — the auth gate, and nothing else. Once a user is present it
   hands off to the route table in routes.jsx; before this task it handed
   off to a single workspace, which is the change that lets a second
   screen exist at all.
   ============================================================ */

const store = createStore();

export default function App() {
  const [me, setMe] = useState(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    store
      .me()
      .then((user) => {
        if (!cancelled) setMe(user);
      })
      .catch(() => {
        if (!cancelled) setMe(null);
      })
      .finally(() => {
        if (!cancelled) setChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!checked) return null;
  if (!me) return <Login onSignedIn={setMe} />;

  return (
    <BrowserRouter>
      <Routes>{appRoutes({ store, me, onSignedOut: () => setMe(null) })}</Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 7: Take the project id from the route in the API store**

In `src/lib/store/api.js`, replace the "first project" resolution (currently around line 155) so a project id can be supplied:

```js
  // The route owns the project id now. resolveProjectId() keeps its old
  // "first project" behaviour only as the fallback for callers that have
  // not been given one yet, which after this task is nothing on the
  // review path -- Workspace.jsx passes the id from useParams().
  function useProject(id) {
    projectId = id;
  }
```

Export `useProject` from the store object, and have `Workspace.jsx` call `store.useProject(projectId)` from a `useEffect` keyed on the route param before its first snapshot fetch. Seed mode's `useProject` is a no-op, since seed mode has exactly one fixture project.

- [ ] **Step 8: Add the shell styles**

Append to `src/styles.css`, using existing tokens — no new hex values. Add any genuinely new colour as a token in the `:root` block at the top of the file first.

```css
/* ---- Application shell (spec §4) ---- */
.app-shell {
  display: grid;
  grid-template-columns: 232px 1fr;
  min-height: 100vh;
}

.company-nav {
  background: var(--paper-1);
  border-right: 1px solid var(--line-1);
  padding: 16px 12px;
}

.company-nav-brand {
  font-weight: 600;
  padding: 0 12px 16px;
}

.company-nav-list { list-style: none; margin: 0; padding: 0; }

.company-nav-link {
  display: flex;
  align-items: center;
  gap: 10px;
  /* Spec §7 keeps touch targets at 40px minimum even on desktop. */
  min-height: 40px;
  padding: 0 12px;
  font-size: 13.5px;
  border-radius: var(--r-md);
  color: var(--ink-1);
  text-decoration: none;
}

/* Focus is handled by the global :focus-visible rule at the top of this
   file (2px solid var(--blue)); do not restate it per component. */
.company-nav-link:hover { background: var(--paper-0); }
.company-nav-link.is-active { background: var(--paper-0); font-weight: 600; }

.app-shell-main { display: flex; flex-direction: column; min-width: 0; }

.app-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--line-1);
}

.app-top-bar-identity { display: flex; flex-direction: column; min-width: 0; }
.app-top-bar-title { font-weight: 600; }
.app-top-bar-subtitle { color: var(--ink-2); font-size: 12.5px; }
.app-top-bar-tools { display: flex; align-items: center; gap: 10px; }

.empty-state {
  margin: 48px auto;
  max-width: 34rem;
  text-align: center;
}
```

**Style conventions this file already uses — follow them, do not invent alternatives.** There is no spacing scale: `src/styles.css` uses literal px throughout, so `var(--space-N)` does not exist. The tokens are `--paper-0`, `--paper-1`, `--surface`, `--canvas`, `--sheet`; `--line-1/2/3` for borders; `--ink-1/2/3` for text; `--blue`, `--green`, `--amber`, `--red` plus `-tint` and `-line` variants; `--r-sm/md/lg` for radii. Buttons are `.btn` with `.btn--primary`, `.btn--danger`, `.btn--block`. A global `:focus-visible` rule already applies the focus ring — do not add per-component focus outlines. Body text in the existing sheet is 13–13.5px, not rem.

- [ ] **Step 9: Run the tests and the build**

```bash
npm test
npm run build
```

Expected: all tests PASS; build succeeds.

- [ ] **Step 10: Commit**

```bash
git add package.json package-lock.json vite.config.js src/setupTests.js src/App.jsx src/routes.jsx src/routes.test.jsx src/components/shell/ src/styles.css src/lib/store/api.js
git commit -m "Add routing and the application shell around the review workspace"
```

---

### Task 7: Projects dashboard

**Files:**
- Create: `src/components/projects/ProjectsDashboard.jsx`
- Create: `src/components/projects/ProjectsFilters.jsx`
- Modify: `src/styles.css`
- Test: `src/components/projects/ProjectsDashboard.test.jsx`

**Interfaces:**
- Consumes: `store.listProjects()` (Task 4), `STAGES`, `stageLabel`, `reviewProgress`, `matchesFilter` (Task 5), `AppTopBar` (Task 6).
- Produces: `<ProjectsDashboard store={store} me={me} />` at `/projects`.

- [ ] **Step 1: Write the failing test**

```jsx
// src/components/projects/ProjectsDashboard.test.jsx
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import ProjectsDashboard from "./ProjectsDashboard.jsx";

const projects = [
  {
    id: "p1",
    name: "Riverside Medical Center - Bldg C",
    number: "26-0418",
    customer: "Hensel Phelps",
    location: "Sacramento, CA",
    bidDueDate: "2026-09-14",
    stage: "review",
    archivedAt: null,
    updatedAt: "2026-08-17T18:00:00Z",
    estimatorName: "Dana Whitfield",
    itemsTotal: 412,
    itemsApproved: 103,
    warningsOpen: 6,
    missingInfo: 2,
  },
  {
    id: "p2",
    name: "Oakview High School",
    number: "26-0501",
    customer: "Swinerton",
    location: "Modesto, CA",
    bidDueDate: null,
    stage: "setup",
    archivedAt: null,
    updatedAt: "2026-08-16T09:00:00Z",
    estimatorName: null,
    itemsTotal: 0,
    itemsApproved: 0,
    warningsOpen: 0,
    missingInfo: 0,
  },
];

const store = { listProjects: async () => projects };

const renderDashboard = () =>
  render(
    <MemoryRouter>
      <ProjectsDashboard store={store} me={{ id: "u1", name: "Dana Whitfield" }} />
    </MemoryRouter>,
  );

describe("ProjectsDashboard", () => {
  it("renders every spec §5.1 column for each project", async () => {
    renderDashboard();
    await screen.findByText("Riverside Medical Center - Bldg C");

    for (const header of [
      /project/i, /customer/i, /location/i, /bid due/i,
      /estimator/i, /stage/i, /progress/i, /warnings/i, /updated/i,
    ]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeTruthy();
    }

    expect(screen.getByText("Hensel Phelps")).toBeTruthy();
    expect(screen.getByText("26-0418")).toBeTruthy();
  });

  it("shows an unassigned estimator and an absent bid date as blanks with meaning", async () => {
    renderDashboard();
    await screen.findByText("Oakview High School");
    // Never a fabricated date and never the literal string "null".
    expect(screen.queryByText("null")).toBeNull();
    expect(screen.getAllByText("Not set").length).toBeGreaterThan(0);
  });

  it("does not render progress as a percentage alone", async () => {
    // Status is never colour alone and a bare bar is not a label: the
    // count has to be readable as text (CLAUDE.md).
    renderDashboard();
    expect(await screen.findByText("103 of 412 approved")).toBeTruthy();
  });

  it("filters to projects needing review", async () => {
    renderDashboard();
    await screen.findByText("Oakview High School");

    await userEvent.click(screen.getByRole("button", { name: /needs review/i }));

    expect(screen.getByText("Riverside Medical Center - Bldg C")).toBeTruthy();
    expect(screen.queryByText("Oakview High School")).toBeNull();
  });

  it("searches across name, number, and customer", async () => {
    renderDashboard();
    await screen.findByText("Oakview High School");

    await userEvent.type(screen.getByLabelText(/search projects/i), "Swinerton");

    expect(screen.getByText("Oakview High School")).toBeTruthy();
    expect(screen.queryByText("Riverside Medical Center - Bldg C")).toBeNull();
  });

  it("names the recovery action when no project matches", async () => {
    renderDashboard();
    await screen.findByText("Oakview High School");

    await userEvent.type(screen.getByLabelText(/search projects/i), "zzzz");

    expect(screen.getByText(/no projects match/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /clear search/i })).toBeTruthy();
  });

  it("shows an empty state with a create action when there are no projects", async () => {
    render(
      <MemoryRouter>
        <ProjectsDashboard store={{ listProjects: async () => [] }} me={{ id: "u1" }} />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: /new project/i })).toBeTruthy();
  });
});
```

Install `@testing-library/user-event` if not already present: `npm install --save-dev @testing-library/user-event@^14.5.0`.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ProjectsDashboard`
Expected: FAIL with `Failed to resolve import "./ProjectsDashboard.jsx"`.

- [ ] **Step 3: Write the filters component**

```jsx
// src/components/projects/ProjectsFilters.jsx
/* ============================================================
   ProjectsFilters.jsx — spec §5.1's search, filter chips, and sort.

   Filter keys come from projectStage.js rather than being restated here,
   so a filter and the predicate behind it cannot disagree.
   ============================================================ */

const FILTERS = [
  { key: "active", label: "Active" },
  { key: "processing", label: "Processing" },
  { key: "needsReview", label: "Needs review" },
  { key: "readyToExport", label: "Ready to export" },
  { key: "complete", label: "Complete" },
  { key: "archived", label: "Archived" },
];

const SORTS = [
  { key: "updated", label: "Last updated" },
  { key: "bidDate", label: "Bid due date" },
  { key: "name", label: "Project name" },
  { key: "customer", label: "Customer" },
  { key: "estimator", label: "Estimator" },
];

export default function ProjectsFilters({ search, onSearch, filter, onFilter, sort, onSort }) {
  return (
    <div className="projects-filters">
      <div className="formfield">
        <label className="formfield-label" htmlFor="projects-search">
          Search projects
        </label>
        <input
          id="projects-search"
          className="field"
          type="search"
          value={search}
          placeholder="Name, number, or customer"
          onChange={(event) => onSearch(event.target.value)}
        />
      </div>

      <div className="filter-chips" role="group" aria-label="Filter projects">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            className={key === filter ? "chip is-active" : "chip"}
            aria-pressed={key === filter}
            onClick={() => onFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="formfield">
        <label className="formfield-label" htmlFor="projects-sort">
          Sort by
        </label>
        <select
          id="projects-sort"
          className="field"
          value={sort}
          onChange={(event) => onSort(event.target.value)}
        >
          {SORTS.map(({ key, label }) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Write the dashboard**

```jsx
// src/components/projects/ProjectsDashboard.jsx
/* ============================================================
   ProjectsDashboard.jsx — spec §5.1.

   A familiar table, deliberately: the estimator's existing tool is a
   spreadsheet, and the first screen of a new product is the wrong place
   to teach a new layout. Progress reads as text ("103 of 412 approved")
   rather than as a bar alone -- a bar is colour without a label, which
   CLAUDE.md rules out, and it is also unreadable in a grayscale print.
   ============================================================ */

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectsFilters from "./ProjectsFilters.jsx";
import { matchesFilter, reviewProgress, stageLabel } from "../../lib/projectStage.js";

const NOT_SET = "Not set";

function formatDate(iso) {
  if (!iso) return NOT_SET;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function compare(a, b, sort) {
  switch (sort) {
    case "bidDate":
      // Projects with no bid date sort last rather than first: an absent
      // deadline is not an imminent one.
      if (!a.bidDueDate) return b.bidDueDate ? 1 : 0;
      if (!b.bidDueDate) return -1;
      return a.bidDueDate.localeCompare(b.bidDueDate);
    case "name":
      return a.name.localeCompare(b.name);
    case "customer":
      return (a.customer || "").localeCompare(b.customer || "");
    case "estimator":
      return (a.estimatorName || "").localeCompare(b.estimatorName || "");
    default:
      return (b.updatedAt || "").localeCompare(a.updatedAt || "");
  }
}

export default function ProjectsDashboard({ store }) {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("active");
  const [sort, setSort] = useState("updated");

  useEffect(() => {
    let cancelled = false;
    store
      .listProjects({ includeArchived: true })
      .then((rows) => {
        if (!cancelled) setProjects(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || "The project list couldn't be loaded. Try again.");
      });
    return () => {
      cancelled = true;
    };
  }, [store]);

  const visible = useMemo(() => {
    if (!projects) return [];
    const needle = search.trim().toLowerCase();
    return projects
      .filter((project) => matchesFilter(project, filter))
      .filter((project) => {
        if (!needle) return true;
        return [project.name, project.number, project.customer]
          .filter(Boolean)
          .some((field) => field.toLowerCase().includes(needle));
      })
      .sort((a, b) => compare(a, b, sort));
  }, [projects, search, filter, sort]);

  const newProjectLink = (
    <Link className="btn btn--primary" to="/projects/new">
      New project
    </Link>
  );

  return (
    <>
      <AppTopBar title="Projects" primaryAction={newProjectLink} />

      <div className="page">
        <h1 className="page-heading">Projects</h1>

        {error ? (
          <div className="notice notice-blocking" role="alert">
            <p>{error}</p>
            <button type="button" className="btn" onClick={() => window.location.reload()}>
              Reload the page
            </button>
          </div>
        ) : null}

        {projects === null && !error ? <p className="muted">Loading projects…</p> : null}

        {projects?.length === 0 ? (
          <div className="empty-state">
            <h2>Create your first estimate</h2>
            <p>Start a project, then upload the drawing set and specifications for the bid.</p>
            {newProjectLink}
          </div>
        ) : null}

        {projects?.length ? (
          <>
            <ProjectsFilters
              search={search}
              onSearch={setSearch}
              filter={filter}
              onFilter={setFilter}
              sort={sort}
              onSort={setSort}
            />

            {visible.length === 0 ? (
              <div className="empty-state">
                <h2>No projects match</h2>
                <p>Try a different search or filter.</p>
                <button type="button" className="btn" onClick={() => setSearch("")}>
                  Clear search
                </button>
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Project</th>
                    <th scope="col">Customer</th>
                    <th scope="col">Location</th>
                    <th scope="col">Bid due</th>
                    <th scope="col">Estimator</th>
                    <th scope="col">Stage</th>
                    <th scope="col">Progress</th>
                    <th scope="col">Warnings</th>
                    <th scope="col">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((project) => {
                    const progress = reviewProgress(project);
                    const warnings = (project.warningsOpen ?? 0) + (project.missingInfo ?? 0);
                    return (
                      <tr key={project.id}>
                        <th scope="row">
                          <Link to={`/projects/${project.id}`}>{project.name}</Link>
                          {project.number ? (
                            <span className="row-secondary tabular">{project.number}</span>
                          ) : null}
                        </th>
                        <td>{project.customer || NOT_SET}</td>
                        <td>{project.location || NOT_SET}</td>
                        <td className="tabular">{formatDate(project.bidDueDate)}</td>
                        <td>{project.estimatorName || NOT_SET}</td>
                        <td>{stageLabel(project.stage)}</td>
                        <td className="tabular">
                          {progress.total === 0
                            ? "Not started"
                            : `${progress.approved} of ${progress.total} approved`}
                        </td>
                        <td>
                          {warnings === 0 ? (
                            "None"
                          ) : (
                            <span className="warning-count">
                              <AlertTriangle size={14} aria-hidden="true" />
                              <span className="tabular">{warnings}</span>
                            </span>
                          )}
                        </td>
                        <td className="tabular">{formatDate(project.updatedAt)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </>
        ) : null}
      </div>
    </>
  );
}
```

- [ ] **Step 5: Add the table styles**

Append to `src/styles.css`, reusing existing tokens:

```css
/* ---- Projects dashboard (spec §5.1) ---- */
.page { padding: 20px; }
.page-heading { margin: 0 0 16px; }

.projects-filters {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.filter-chips { display: flex; gap: 6px; flex-wrap: wrap; }

.chip {
  min-height: 40px;
  padding: 0 13px;
  font-size: 13.5px;
  border: 1px solid var(--line-2);
  border-radius: 999px;
  background: var(--surface);
  color: var(--ink-1);
  cursor: pointer;
}

.chip:hover { background: var(--paper-1); border-color: var(--line-3); }
.chip.is-active { background: var(--paper-0); font-weight: 600; }

.data-table { width: 100%; border-collapse: collapse; }
.data-table th, .data-table td {
  text-align: left;
  padding: 10px;
  font-size: 13.5px;
  border-bottom: 1px solid var(--line-1);
  vertical-align: top;
}
.data-table thead th { font-size: 12.5px; font-weight: 600; color: var(--ink-2); }
.row-secondary { display: block; color: var(--ink-3); font-size: 12.5px; }

/* Warning count carries an icon as well as a hue, per CLAUDE.md's rule
   that status is never colour alone. */
.warning-count { display: inline-flex; align-items: center; gap: 6px; color: var(--amber); }
```

Same style conventions as Task 6 apply: literal px, the real token names, `.btn` variants, and no per-component focus rules.

- [ ] **Step 6: Run the tests and the build**

```bash
npm test -- ProjectsDashboard
npm run build
```

Expected: all PASS; build succeeds.

- [ ] **Step 7: Commit**

```bash
git add src/components/projects/ src/styles.css package.json package-lock.json
git commit -m "Add the projects dashboard with search, filters, and sort"
```

---

### Task 8: New project form and project overview

**Files:**
- Create: `src/components/projects/NewProject.jsx`
- Create: `src/components/projects/ProjectOverview.jsx`
- Create: `src/components/shell/ProjectNav.jsx`
- Modify: `src/styles.css`
- Test: `src/components/projects/NewProject.test.jsx`
- Test: `src/components/projects/ProjectOverview.test.jsx`

**Interfaces:**
- Consumes: `store.createProject()`, `store.listProjects()` (Task 4); `reviewProgress`, `stageLabel` (Task 5); `AppTopBar` (Task 6).
- Produces: `<NewProject store={store} />` at `/projects/new`; `<ProjectOverview store={store} me={me} />` at `/projects/:projectId`; `<ProjectNav projectId={id} />` rendering the thirteen workspace links with unbuilt ones disabled.

- [ ] **Step 1: Write the failing tests**

```jsx
// src/components/projects/NewProject.test.jsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import NewProject from "./NewProject.jsx";

describe("NewProject", () => {
  it("labels every field visibly and persistently", () => {
    render(
      <MemoryRouter>
        <NewProject store={{ createProject: vi.fn() }} />
      </MemoryRouter>,
    );
    for (const label of [
      /project name/i, /internal number/i, /customer/i,
      /project address/i, /bid due date/i, /construction type/i,
    ]) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
  });

  it("does not expose labor or pricing settings", () => {
    // Spec §6.1: advanced labor and pricing settings do not appear
    // during creation.
    render(
      <MemoryRouter>
        <NewProject store={{ createProject: vi.fn() }} />
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText(/labor rate/i)).toBeNull();
    expect(screen.queryByLabelText(/markup/i)).toBeNull();
  });

  it("blocks submission with a message beside the field when the name is blank", async () => {
    const createProject = vi.fn();
    render(
      <MemoryRouter>
        <NewProject store={{ createProject }} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/project address/i), "Modesto, CA");
    await userEvent.click(screen.getByRole("button", { name: /create project/i }));

    expect(createProject).not.toHaveBeenCalled();
    expect(screen.getByText(/enter a project name/i)).toBeTruthy();
  });

  it("creates the project with the entered values", async () => {
    const createProject = vi.fn().mockResolvedValue({ id: "p9", name: "Oakview High School" });
    render(
      <MemoryRouter>
        <NewProject store={{ createProject }} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/project name/i), "Oakview High School");
    await userEvent.type(screen.getByLabelText(/project address/i), "Modesto, CA");
    await userEvent.type(screen.getByLabelText(/customer/i), "Swinerton");
    await userEvent.click(screen.getByRole("button", { name: /create project/i }));

    expect(createProject).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Oakview High School",
        location: "Modesto, CA",
        customer: "Swinerton",
      }),
    );
  });

  it("keeps the entered values and names a recovery action when creation fails", async () => {
    const createProject = vi.fn().mockRejectedValue({ message: "The project couldn't be created. Try again." });
    render(
      <MemoryRouter>
        <NewProject store={{ createProject }} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/project name/i), "Oakview High School");
    await userEvent.type(screen.getByLabelText(/project address/i), "Modesto, CA");
    await userEvent.click(screen.getByRole("button", { name: /create project/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/try again/i);
    // The form must not clear -- retyping a form after a failed submit is
    // how an estimator loses trust in the first thirty seconds.
    expect(screen.getByLabelText(/project name/i)).toHaveValue("Oakview High School");
  });
});
```

```jsx
// src/components/projects/ProjectOverview.test.jsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectOverview from "./ProjectOverview.jsx";

const project = {
  id: "p1",
  name: "Riverside Medical Center - Bldg C",
  number: "26-0418",
  customer: "Hensel Phelps",
  location: "Sacramento, CA",
  bidDueDate: "2026-09-14",
  stage: "review",
  archivedAt: null,
  updatedAt: "2026-08-17T18:00:00Z",
  estimatorName: "Dana Whitfield",
  itemsTotal: 412,
  itemsApproved: 103,
  warningsOpen: 6,
  missingInfo: 2,
};

const renderOverview = (store) =>
  render(
    <MemoryRouter initialEntries={["/projects/p1"]}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectOverview store={store} me={{ id: "u1" }} />} />
      </Routes>
    </MemoryRouter>,
  );

describe("ProjectOverview", () => {
  it("shows the project details, progress, and unresolved warnings", async () => {
    renderOverview({ listProjects: async () => [project] });

    expect(await screen.findByRole("heading", { name: /riverside medical center/i })).toBeTruthy();
    expect(screen.getByText("Hensel Phelps")).toBeTruthy();
    expect(screen.getByText("103 of 412 approved")).toBeTruthy();
    expect(screen.getByText(/2 items are missing required information/i)).toBeTruthy();
  });

  it("offers a continue action into the review workspace", async () => {
    renderOverview({ listProjects: async () => [project] });
    const link = await screen.findByRole("link", { name: /continue review/i });
    expect(link.getAttribute("href")).toBe("/projects/p1/takeoff");
  });

  it("names a recovery action when the project isn't found", async () => {
    renderOverview({ listProjects: async () => [] });
    expect(await screen.findByRole("link", { name: /back to projects/i })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- NewProject ProjectOverview`
Expected: FAIL with unresolved imports for both components.

- [ ] **Step 3: Write the new-project form**

```jsx
// src/components/projects/NewProject.jsx
/* ============================================================
   NewProject.jsx — spec §6.1's guided form.

   Single column, persistent visible labels, and only the fields the spec
   names. Labor and pricing settings are deliberately absent: the spec
   excludes them, and every field here is one an estimator has to answer
   before they can start the work they came to do.
   ============================================================ */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";

const CONSTRUCTION_TYPES = [
  "Not sure",
  "Warehouse or distribution",
  "Office",
  "Healthcare",
  "Education",
  "Multifamily",
  "Industrial",
  "Retail",
];

export default function NewProject({ store }) {
  const navigate = useNavigate();
  const [values, setValues] = useState({
    name: "",
    number: "",
    customer: "",
    location: "",
    bidDueDate: "",
    constructionType: "Not sure",
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const set = (key) => (event) => setValues({ ...values, [key]: event.target.value });

  async function onSubmit(event) {
    event.preventDefault();

    const errors = {};
    if (!values.name.trim()) errors.name = "Enter a project name.";
    if (!values.location.trim()) errors.location = "Enter a project address.";
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await store.createProject({
        name: values.name.trim(),
        location: values.location.trim(),
        number: values.number.trim(),
        customer: values.customer.trim(),
        bidDueDate: values.bidDueDate || null,
      });
      navigate(`/projects/${created.id}`);
    } catch (err) {
      // Values stay in the form. Spec §20 requires the copy to name a
      // recovery action rather than only reporting failure.
      setSubmitError(err?.message || "The project couldn't be created. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopBar title="New project" subtitle="Step 1 of 6 · Project details" />

      <div className="page page-narrow">
        <h1 className="page-heading">New project</h1>

        {submitError ? (
          <div className="notice notice-blocking" role="alert">
            {submitError}
          </div>
        ) : null}

        <form className="form-column" onSubmit={onSubmit} noValidate>
          <Field
            id="project-name"
            label="Project name"
            required
            value={values.name}
            onChange={set("name")}
            error={fieldErrors.name}
          />
          <Field
            id="project-number"
            label="Internal number"
            hint="Your own job number, if you use one."
            value={values.number}
            onChange={set("number")}
          />
          <Field
            id="project-customer"
            label="Customer or general contractor"
            value={values.customer}
            onChange={set("customer")}
          />
          <Field
            id="project-location"
            label="Project address"
            required
            hint="Used to apply regional labor and pricing."
            value={values.location}
            onChange={set("location")}
            error={fieldErrors.location}
          />
          <Field
            id="project-bid-date"
            label="Bid due date"
            type="date"
            value={values.bidDueDate}
            onChange={set("bidDueDate")}
          />

          <div className="formfield">
            <label className="formfield-label" htmlFor="project-type">
              Construction type
            </label>
            <select
              id="project-type"
              className="field"
              value={values.constructionType}
              onChange={set("constructionType")}
            >
              {CONSTRUCTION_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>

          <div className="form-actions">
            <button type="submit" className="btn btn--primary" disabled={submitting}>
              {submitting ? "Creating…" : "Create project"}
            </button>
            <Link className="btn" to="/projects">
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </>
  );
}

function Field({ id, label, hint, error, required, type = "text", value, onChange }) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className="formfield">
      <label className="formfield-label" htmlFor={id}>
        {label}
        {required ? <span className="formfield-required"> (required)</span> : null}
      </label>
      {hint ? (
        <p className="formfield-hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      <input
        id={id}
        className={error ? "field field--error" : "field"}
        type={type}
        value={value}
        onChange={onChange}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        aria-invalid={error ? "true" : undefined}
      />
      {/* Spec §8 keeps the message adjacent to the field it belongs to. */}
      {error ? (
        <p className="formfield-error" id={errorId}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Write the project navigation**

```jsx
// src/components/shell/ProjectNav.jsx
/* ============================================================
   ProjectNav.jsx — spec §4.2's workspace navigation.

   All thirteen workspaces are listed because spec §4.2 requires the
   current stage, completed stages, and unresolved blockers to stay
   visible -- hiding the ones that are not built yet would hide the shape
   of the workflow. Unbuilt workspaces render as disabled with a reason
   rather than as links to an empty page.
   ============================================================ */

import { NavLink } from "react-router-dom";

const WORKSPACES = [
  { slug: "", label: "Overview", built: true },
  { slug: "documents", label: "Documents", built: false },
  { slug: "notes", label: "Notes & assumptions", built: false },
  { slug: "takeoff", label: "Blueprint takeoff", built: true },
  { slug: "spreadsheet", label: "Takeoff spreadsheet", built: false },
  { slug: "assemblies", label: "Assemblies", built: false },
  { slug: "labor", label: "Labor", built: false },
  { slug: "pricing", label: "Material pricing", built: false },
  { slug: "estimate", label: "Estimate summary", built: false },
  { slug: "revisions", label: "Revisions", built: false },
  { slug: "final-review", label: "Final review", built: false },
  { slug: "export", label: "Export", built: false },
  { slug: "settings", label: "Project settings", built: false },
];

export default function ProjectNav({ projectId }) {
  return (
    <nav className="project-nav" aria-label="Project workspaces">
      <ul className="project-nav-list">
        {WORKSPACES.map(({ slug, label, built }) => {
          const to = slug ? `/projects/${projectId}/${slug}` : `/projects/${projectId}`;
          if (!built) {
            return (
              <li key={label}>
                <span className="project-nav-link is-unavailable" aria-disabled="true" title="Not available yet">
                  {label}
                </span>
              </li>
            );
          }
          return (
            <li key={label}>
              <NavLink
                end={slug === ""}
                to={to}
                className={({ isActive }) => (isActive ? "project-nav-link is-active" : "project-nav-link")}
              >
                {label}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
```

- [ ] **Step 5: Write the project overview**

```jsx
// src/components/projects/ProjectOverview.jsx
/* ============================================================
   ProjectOverview.jsx — spec §6.2, the project home and return point.

   Every card links to the records behind it, per the spec. The warning
   copy states the consequence rather than a count alone: "2 items are
   missing required information" tells an estimator what it will do to
   them at finish-review, which a bare number does not.
   ============================================================ */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectNav from "../shell/ProjectNav.jsx";
import { reviewProgress, stageLabel } from "../../lib/projectStage.js";

function formatDate(iso) {
  if (!iso) return "Not set";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function ProjectOverview({ store }) {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [state, setState] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    store
      .listProjects({ includeArchived: true })
      .then((rows) => {
        if (cancelled) return;
        const found = rows.find((row) => row.id === projectId);
        setProject(found ?? null);
        setState(found ? "ready" : "missing");
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [store, projectId]);

  if (state === "loading") return <p className="muted page">Loading project…</p>;

  if (state !== "ready" || !project) {
    return (
      <div className="empty-state">
        <h1>That project isn't available</h1>
        <p>It may have been archived, or the link may be out of date.</p>
        <Link className="btn btn--primary" to="/projects">
          Back to projects
        </Link>
      </div>
    );
  }

  const progress = reviewProgress(project);

  return (
    <>
      <AppTopBar
        title={project.name}
        subtitle={project.revisionSetLabel || "No drawing set yet"}
        primaryAction={
          <Link className="btn btn--primary" to={`/projects/${project.id}/takeoff`}>
            Continue review
          </Link>
        }
      />
      <ProjectNav projectId={project.id} />

      <div className="page">
        <h1 className="page-heading">{project.name}</h1>

        <div className="card-grid">
          <section className="card">
            <h2>Project details</h2>
            <dl className="detail-list">
              <dt>Customer</dt>
              <dd>{project.customer || "Not set"}</dd>
              <dt>Location</dt>
              <dd>{project.location || "Not set"}</dd>
              <dt>Internal number</dt>
              <dd className="tabular">{project.number || "Not set"}</dd>
              <dt>Bid due</dt>
              <dd className="tabular">{formatDate(project.bidDueDate)}</dd>
              <dt>Assigned estimator</dt>
              <dd>{project.estimatorName || "Not assigned"}</dd>
            </dl>
          </section>

          <section className="card">
            <h2>Review progress</h2>
            <p className="tabular">
              {progress.total === 0
                ? "No items yet. Upload a drawing set to begin."
                : `${progress.approved} of ${progress.total} approved`}
            </p>
            <p className="muted">Current stage: {stageLabel(project.stage)}</p>
            <Link to={`/projects/${project.id}/takeoff`}>Open the blueprint takeoff</Link>
          </section>

          <section className="card">
            <h2>Unresolved</h2>
            {project.missingInfo > 0 ? (
              <p>
                <span className="tabular">{project.missingInfo}</span>{" "}
                {project.missingInfo === 1 ? "item is" : "items are"} missing required information. These block
                finishing the review.
              </p>
            ) : null}
            {project.warningsOpen > 0 ? (
              <p>
                <span className="tabular">{project.warningsOpen}</span>{" "}
                {project.warningsOpen === 1 ? "item needs" : "items need"} attention before they can be
                approved.
              </p>
            ) : null}
            {project.missingInfo === 0 && project.warningsOpen === 0 ? <p>Nothing outstanding.</p> : null}
          </section>
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 6: Add the form and card styles**

Append to `src/styles.css`, reusing existing tokens:

```css
/* ---- Forms and project overview (spec §6) ---- */
.page-narrow { max-width: 40rem; }
.form-column { display: flex; flex-direction: column; gap: 16px; }

/* NOTE: `.field` is already taken -- it is the input element itself,
   used across the review workspace. The wrapper is `.formfield`, and the
   inputs in these forms reuse the existing `.field` class rather than
   defining a second input style. */
.formfield { display: flex; flex-direction: column; gap: 5px; }
.formfield-label { font-weight: 600; font-size: 12.5px; }
.formfield-required { font-weight: 400; color: var(--ink-3); }
.formfield-hint { margin: 0; color: var(--ink-2); font-size: 12.5px; }
.formfield-error { margin: 0; color: var(--red); font-size: 12.5px; }

/* The error state is a border colour plus the adjacent message plus
   aria-invalid -- never the colour alone (CLAUDE.md). */
.field--error { border-color: var(--red); }

.form-actions { display: flex; gap: 10px; }

.project-nav { border-bottom: 1px solid var(--line-1); padding: 0 20px; }
.project-nav-list { display: flex; gap: 2px; list-style: none; margin: 0; padding: 0; overflow-x: auto; }

.project-nav-link {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  padding: 0 10px;
  font-size: 13.5px;
  color: var(--ink-1);
  text-decoration: none;
  white-space: nowrap;
  border-bottom: 2px solid transparent;
}

.project-nav-link.is-active { border-bottom-color: var(--blue); font-weight: 600; }
.project-nav-link.is-unavailable { color: var(--ink-3); cursor: default; }

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
  gap: 16px;
}

.card { border: 1px solid var(--line-1); border-radius: var(--r-md); padding: 16px; background: var(--surface); }
.card h2 { margin: 0 0 10px; font-size: 14px; }

.detail-list { display: grid; grid-template-columns: auto 1fr; gap: 5px 16px; margin: 0; font-size: 13.5px; }
.detail-list dt { color: var(--ink-2); }
.detail-list dd { margin: 0; }
```

Same style conventions as Task 6 apply. Note especially that the form inputs use the **existing** `.field` class from `src/styles.css` — this task adds no second input style.

- [ ] **Step 7: Run the tests and the build**

```bash
npm test
npm run build
```

Expected: all PASS; build succeeds.

- [ ] **Step 8: Verify the whole flow in the browser**

```bash
docker compose up -d postgres api web
```

Open http://localhost:5174, sign in, and confirm: the projects table renders with the seeded project; **New project** creates one and lands on its overview; **Continue review** opens the existing review workspace with its markers, drawer, and shortcuts intact; browser back returns to the overview.

Then confirm seed mode still works with the API stopped: `npm run dev` on the host, which must reach the dashboard without a login screen.

- [ ] **Step 9: Commit**

```bash
git add src/components/ src/styles.css
git commit -m "Add project creation, project overview, and workspace navigation"
```

---

## Self-review

**Spec coverage.** §4.1 company navigation → Task 6. §4.2 project navigation → Task 8. §4.3 top bar → Task 6, with save state and undo carried over from the existing `TopBar.jsx` when `Workspace.jsx` is re-homed. §5.1 projects dashboard columns, controls, filters, sort → Tasks 2, 5, 7. §6.1 new project → Task 3, Task 8. §6.2 project overview → Task 8.

**Deliberately out of this slice, and why:**

- **§4.4 the assistant drawer.** It is part of the shell in the spec, but the Conversation agent it fronts is unbuilt, and a drawer that opens onto nothing is worse than no drawer. It needs its own slice once the agent boundaries from the architecture design have an implementation. **This is the largest known gap in this plan.**
- **§5.1 saved views.** Needs a persistence decision (per user or per company) that nothing here settles.
- **§5.2 Accuracy, §5.3 Company library, §5.4 Integration center.** The nav links to them; the screens are separate slices. `CompanyNav` will route to `NotFound` for these until they exist — acceptable for one slice, but they should not stay that way for long, so make them the next thing or make the nav entries disabled the way `ProjectNav` handles unbuilt workspaces.
- **Archiving a project.** The column and filter exist; no control sets `archived_at` yet.

**Type consistency check.** `listProjects`/`createProject` names match across `contract.test.js`, `seed-projects.js`, `api.js`, and all four screens. `reviewProgress` returns `{ approved, total, percent }` everywhere it is consumed. `ProjectRow` field names match `ProjectOut` field names match the camelCase the client asserts. `stage` values are the same seven strings in `models.py`, `projectStage.js`, and the tests.

**One risk worth stating plainly.** Task 6 changes `src/lib/store/api.js`'s project resolution from "the first project" to "the one in the route." Every existing test in `contract.test.js` and `api.test.js` runs against the single seeded project, so they will keep passing whether or not the wiring is right. Step 8 of Task 8 — opening a second project in the browser and confirming the workspace loads *that* project's sheets — is the only thing in this plan that actually catches a mistake there. Do not skip it.

---

Plan complete and saved to `docs/superpowers/plans/2026-08-18-frontend-shell-and-projects.md`.
