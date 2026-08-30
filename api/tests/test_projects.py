"""app/takeoff/models.py's Project -- the dashboard fields spec §5.1's
projects table renders. task-1-brief.md.
"""

import datetime
import uuid

import pytest
from sqlalchemy import select

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


# --- POST /api/projects: creation from the guided form (task-3-brief.md) ---
#
# `client` alone is not signed in -- POST /api/projects sits behind
# `current_user` like every other takeoff route, so each test below also
# takes `signed_in_user` to log the client in first. The brief's draft
# tests only listed `client`, which conftest.py's actual current_user
# dependency (cookie-or-401) would fail; `signed_in_user` is the fixture
# task-2-brief.md's own list tests already use for the same reason.


def test_create_project_requires_only_name_and_location(client, signed_in_user):
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


def test_create_project_rejects_blank_name(client, signed_in_user):
    res = client.post("/api/projects", json={"name": "   ", "location": "Modesto, CA"})
    assert res.status_code == 422


def test_created_project_belongs_to_the_callers_org(client, signed_in_user, db):
    res = client.post("/api/projects", json={"name": "Oakview High School", "location": "Modesto, CA"})
    created = db.get(Project, uuid.UUID(res.json()["id"]))
    assert created.org_id == signed_in_user.org_id


def test_created_project_appears_in_the_list(client, signed_in_user):
    client.post("/api/projects", json={"name": "Oakview High School", "location": "Modesto, CA"})
    names = {row["name"] for row in client.get("/api/projects").json()}
    assert "Oakview High School" in names


def test_create_project_accepts_camel_case_keys(client, signed_in_user):
    """ProjectOut is camelCase-native on the wire, so the client sends
    bidDueDate and estimatorUserId, not their snake_case names.
    test_create_project_requires_only_name_and_location above only posts
    name/location, which are spelled identically in both conventions and
    would pass even if ProjectCreateIn only accepted snake_case.

    This also doubles as the "same-org estimatorUserId is accepted"
    case: `signed_in_user` is in the caller's own org, and `estimatorName`
    coming back proves the id round-tripped rather than being silently
    dropped. See test_create_project_rejects_a_foreign_estimator below
    for the cross-org case."""
    res = client.post(
        "/api/projects",
        json={
            "name": "Oakview High School",
            "location": "Modesto, CA",
            "bidDueDate": "2026-09-14",
            "estimatorUserId": str(signed_in_user.id),
        },
    )

    assert res.status_code == 201
    body = res.json()
    assert body["bidDueDate"] == "2026-09-14"
    assert body["estimatorName"] == signed_in_user.name


@pytest.fixture
def foreign_estimator(db):
    """A user in a different org than `signed_in_user`'s -- for proving
    POST /api/projects rejects a cross-org estimator_user_id rather than
    accepting it on the strength of the foreign key alone. `users.id` is
    globally unique, so the FK by itself would happily accept this user;
    only an explicit org check (projects.py::create_project) catches it.
    Local to this file rather than conftest.py because
    test_tenancy.py's `rival` fixture already covers the same shape for
    project/item/sheet probes and there was no shared need for a third
    copy until this test."""
    from app.auth.passwords import hash_password
    from app.identity.models import Org, User

    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    user = User(
        org_id=other_org.id, email="foreign-estimator@example.com",
        password_hash=hash_password("hunter2"), name="Foreign Estimator", color="#a8412c",
    )
    db.add(user)
    db.flush()
    return user


def test_create_project_rejects_a_foreign_estimator(client, signed_in_user, db, foreign_estimator):
    """A caller who supplies another org's user id as estimator must be
    refused, not silently ignored -- and no project should be left behind
    half-created. 404, matching create_project's `_estimator_not_found()`:
    the same status whether the id doesn't exist at all or belongs to
    another org, so the response can't be used to confirm a guessed id
    exists somewhere else."""
    res = client.post(
        "/api/projects",
        json={
            "name": "Oakview High School",
            "location": "Modesto, CA",
            "estimatorUserId": str(foreign_estimator.id),
        },
    )

    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "estimator_not_found"
    assert db.scalars(select(Project).where(Project.name == "Oakview High School")).first() is None


# --- "Updated" column: final-review fix 2 -----------------------------
#
# Project.updated_at only moves when the `projects` row itself is
# UPDATEd (its `onupdate=func.now()`), and nothing in the review flow
# ever writes that row -- approvals, edits, and every other mutation
# write `items` and `actions` instead. Left alone, GET /api/projects'
# "Updated" column (and its default sort) freezes at project-creation
# time the moment review actually starts. list_projects() is expected to
# report the later of the project row's own updated_at and its most
# recent action's created_at, so the column reflects real activity.


def test_projects_list_updated_at_reflects_latest_action_not_just_the_project_row(db, org, dana):
    """A project whose row has not been touched since creation, but which
    has since had review activity recorded in the append-only action log,
    must report that activity's timestamp -- not the stale creation-time
    value Project.updated_at is stuck at."""
    from app.takeoff.models import Action
    from app.takeoff.projects import list_projects

    project = Project(org_id=org.id, name="Riverside Medical Center", revision_set_label="")
    db.add(project)
    db.flush()
    stale_row_updated_at = project.updated_at

    later = stale_row_updated_at + datetime.timedelta(hours=3)
    db.add(Action(
        project_id=project.id, kind="approve", actor_user_id=dana.id, label="Approved 20A duplex receptacle",
        before={}, after={}, created_at=later,
    ))
    db.flush()

    rows = list_projects(db, org.id)
    row = next(r for r in rows if r.id == project.id)

    assert row.updated_at == later
    assert row.updated_at > stale_row_updated_at


def test_projects_list_sorts_by_latest_activity_including_actions(db, org, dana):
    """The default sort (most recently active project first) must follow
    the same derived timestamp the column shows, not the project row's
    own updated_at alone -- otherwise the column and the sort it drives
    would disagree about what "most recent" means."""
    from app.takeoff.models import Action
    from app.takeoff.projects import list_projects

    older_project = Project(org_id=org.id, name="Older bid, but active today", revision_set_label="")
    newer_project = Project(org_id=org.id, name="Newer bid, untouched since creation", revision_set_label="")
    db.add(older_project)
    db.add(newer_project)
    db.flush()
    # Force a real ordering between the two rows' own updated_at, since
    # both would otherwise share the same func.now() from this flush.
    older_project.updated_at = newer_project.updated_at - datetime.timedelta(days=2)
    db.flush()

    db.add(Action(
        project_id=older_project.id, kind="approve", actor_user_id=dana.id, label="Approved something",
        before={}, after={}, created_at=newer_project.updated_at + datetime.timedelta(hours=1),
    ))
    db.flush()

    rows = list_projects(db, org.id)
    ids_in_order = [r.id for r in rows]

    assert ids_in_order.index(older_project.id) < ids_in_order.index(newer_project.id)


def test_created_project_records_who_created_it(client, signed_in_user, db):
    """ROADMAP.md invariant 8 -- every mutation is attributable. Project
    creation is the one mutation with no home in the action log, because
    that log is project-scoped and a creation has no project to belong to
    yet, so the attribution lives on the row instead."""
    response = client.post(
        "/api/projects", json={"name": "Oakview High School", "location": "Modesto, CA"}
    )
    assert response.status_code == 201, response.text

    created = db.get(Project, uuid.UUID(response.json()["id"]))
    assert created.created_by_user_id == signed_in_user.id


def test_create_project_cannot_be_called_unattributed(db, org):
    """`created_by_user_id` is keyword-only with no default, so forgetting
    it is a TypeError at the call site rather than a silently anonymous
    project. The invariant is enforced by the signature rather than by
    whoever writes the next caller remembering it."""
    from app.takeoff.projects import create_project

    with pytest.raises(TypeError):
        create_project(db, org.id, name="Oakview High School", location="Modesto, CA")


def test_dashboard_counts_are_per_project_not_org_wide(db, org, signed_in_user, client):
    """Each project's counts describe THAT project.

    The counts are correlated scalar subqueries against the outer Project
    row. Wrapping a correlated select in `.subquery()` de-correlates it,
    which turned every row's count into the org-wide total: a brand-new
    project reported the same item count as the busiest one. That is a
    wrong number on the dashboard, and it also silently disabled document
    processing, because the processing screen reads `itemsTotal > 0` to
    mean "this project already has a takeoff, do not re-run".
    """
    import uuid as _uuid

    from app.takeoff.models import Item, Project, ReviewStatus, Sheet

    busy = Project(id=_uuid.uuid4(), org_id=org.id, name="Has a takeoff", stage="review")
    empty = Project(id=_uuid.uuid4(), org_id=org.id, name="Nothing uploaded yet", stage="setup")
    db.add_all([busy, empty])
    db.flush()

    sheet = Sheet(id=_uuid.uuid4(), project_id=busy.id, number="E2.1", title="Power",
                  discipline="Electrical", revision="", scale="", scale_options=[], plan="")
    db.add(sheet)
    db.flush()
    for status in (ReviewStatus.READY, ReviewStatus.APPROVED, ReviewStatus.ATTENTION):
        db.add(Item(id=_uuid.uuid4(), project_id=busy.id, sheet_id=sheet.id, symbol="receptacle",
                    name="20A duplex receptacle", system="Power", category="Devices",
                    quantity=1, unit="ea", status=status))
    db.commit()

    rows = {p["name"]: p for p in client.get("/api/projects").json()}

    assert rows["Has a takeoff"]["itemsTotal"] == 3
    assert rows["Has a takeoff"]["itemsApproved"] == 1
    assert rows["Has a takeoff"]["warningsOpen"] == 1
    # The whole point: an untouched project reports its own emptiness.
    assert rows["Nothing uploaded yet"]["itemsTotal"] == 0
    assert rows["Nothing uploaded yet"]["itemsApproved"] == 0
    assert rows["Nothing uploaded yet"]["warningsOpen"] == 0
