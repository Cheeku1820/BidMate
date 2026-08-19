"""app/takeoff/models.py's Project -- the dashboard fields spec §5.1's
projects table renders. task-1-brief.md.
"""

import datetime

from app.takeoff.models import Item, Project, Sheet


def test_project_carries_dashboard_fields(db, org):
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
    db.add(project)
    db.flush()

    assert project.number == "26-0418"
    assert project.customer == "Hensel Phelps"
    assert project.location == "Sacramento, CA"
    assert project.bid_due_date == datetime.date(2026, 9, 14)
    assert project.estimator_user_id is None
    assert project.stage == "review"
    assert project.archived_at is None
    assert project.updated_at is not None


def test_project_defaults_are_empty_not_null(db, org):
    """A project created from the minimal form (name and address only) must
    still render every dashboard column without the table printing 'None'.
    Empty string beats NULL for the text columns for exactly that reason."""
    project = Project(org_id=org.id, name="Untitled bid")
    db.add(project)
    db.flush()

    assert project.number == ""
    assert project.customer == ""
    assert project.location == ""
    assert project.stage == "setup"
    assert project.bid_due_date is None


# --- GET /api/projects: dashboard columns and counts (task-2-brief.md) ---


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
    assert row["estimatorName"] == "Dana Whitfield"
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


def test_projects_list_counts_ignore_superseded_sheets_and_rejected_items(db, org, project, sheet, item):
    """ROADMAP.md invariant 2 -- superseded sheets never contribute to
    totals -- binds this query exactly as it binds totals.py's, and
    projects.py's own module docstring claims to enforce it. None of the
    three tests above happen to exercise a superseded sheet or a rejected
    item, so this checks the claim directly against list_projects rather
    than trusting the docstring."""
    from app.takeoff.models import ReviewStatus
    from app.takeoff.projects import list_projects

    # `item` (from conftest) is READY on `sheet` and is the one item that
    # should still count.
    superseded_sheet = Sheet(
        project_id=project.id, number="E2.1-old", title="Power plan (prior rev)", discipline="Electrical",
        revision="Rev 1", scale="mixed", scale_options=[], plan="warehouse",
        superseded_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(superseded_sheet)
    db.flush()
    db.add(Item(
        project_id=project.id, sheet_id=superseded_sheet.id, symbol="receptacle", name="Superseded item",
        system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY, x=1, y=1,
    ))
    db.add(Item(
        project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="Rejected item",
        system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY, x=1, y=1,
        rejected_at=datetime.datetime.now(datetime.timezone.utc),
    ))
    db.flush()

    rows = list_projects(db, org.id)

    assert len(rows) == 1
    assert rows[0].items_total == 1
