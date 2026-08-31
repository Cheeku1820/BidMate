"""Tenancy proven for every project-scoped route -- task-13-brief.md,
correction 5. The plan's sketch tests four routes (snapshot, approve, undo,
list); the brief estimated "roughly fifteen" project-scoped routes once
Task 13's nine mutation endpoints land -- the actual count, verified by
enumerating `app.routes` below, is 13 (3 reads + 9 mutations + presence).
This file:

1. Keeps the plan's four scenario-shaped tests, since they read naturally
   and one (the undo test) exercises a real cross-request sequence a
   table-driven case can't express as cleanly.
2. Adds a single parametrized test walking a table of every project-scoped
   route -- method, path, body -- asserting a rival-org caller gets 404.
3. Adds the same table for unauthenticated callers, asserting 401.
4. Adds a guard test that enumerates `app.routes` at runtime and fails if
   any `/api/*` route is neither in the tenancy table nor on the short,
   explicit exemption list of routes that are not project-scoped at all
   (health, auth, the org-scoped project list). This is the test that
   keeps the table honest after this task: the next endpoint that forgets
   to register itself here fails loudly instead of shipping ungated.
"""

import pytest
from sqlalchemy import text

from app.auth.passwords import hash_password
from app.identity.models import Org, User
from app.main import app
from app.takeoff.models import Note


@pytest.fixture
def note(db, project, dana):
    n = Note(
        project_id=project.id, scope="project", title="Existing panel to remain",
        body="Panel LP-1 is existing to remain, per the demo plan.",
        category="existing_condition", author_user_id=dana.id,
    )
    db.add(n)
    db.flush()
    return n


@pytest.fixture
def rival(db):
    org = Org(name="Rival Electric")
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id, email="rival@example.com", password_hash=hash_password("hunter2"),
        name="Rival Estimator", color="#a8412c",
    )
    db.add(user)
    db.flush()
    return user


def _sign_in_as(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


# --- The plan's four (adjusted per correction 6: prove the database was
# untouched with a fresh read, not a stale in-session attribute) ---


def test_another_org_cannot_read_your_snapshot(client, dana, rival, project, sheet, item):
    _sign_in_as(client, "rival@example.com", "hunter2")

    assert client.get(f"/api/projects/{project.id}/snapshot").status_code == 404


def test_another_org_cannot_approve_your_item(client, dana, rival, project, sheet, item, db):
    _sign_in_as(client, "rival@example.com", "hunter2")

    response = client.post(f"/api/items/{item.id}/approve", headers={"If-Match": str(item.version)})

    assert response.status_code == 404
    # A fresh read of the actual row, not the fixture's in-session
    # attribute -- the client and the `db` fixture share one session in
    # this test harness, so checking `item.status` alone would pass even
    # if some code path mutated the row in memory without flushing, or
    # flushed and rolled back. Reading the column back with raw SQL
    # proves the persisted state, not just a Python object's belief
    # about it.
    row = db.execute(text("select status from items where id = :id"), {"id": str(item.id)}).scalar_one()
    assert row == "ready", "the item must be untouched"


def test_another_org_cannot_undo_your_action(client, dana, rival, project, sheet, item):
    _sign_in_as(client, "dana@example.com", "correct-horse")
    client.post(f"/api/items/{item.id}/approve", headers={"If-Match": str(item.version)})
    client.post("/api/auth/logout")

    _sign_in_as(client, "rival@example.com", "hunter2")
    assert client.post(f"/api/projects/{project.id}/undo").status_code == 404


def test_a_project_from_another_org_is_absent_from_your_list(client, rival, project):
    _sign_in_as(client, "rival@example.com", "hunter2")

    assert client.get("/api/projects").json() == []


# --- Table-driven: every project-scoped route, one rival-org probe each ---
#
# Each row is (method, path_template, path(project, sheet, item), body).
# `path_template` is the literal FastAPI path -- used only by the guard
# test below, to match against `app.routes`. `path` builds the real URL
# for this test's fixtures.

# A fifth column, `headers_fn`, carries the `If-Match` header the five
# single-item mutations now require (task-13b-brief.md) -- without it, a
# rival-org or unauthenticated request to one of those five would fail
# FastAPI's own header validation (422) before ever reaching the tenancy
# gate this table exists to prove, which would silently stop testing
# what these rows are actually for. `i.version` is a placeholder value on
# every row here: the fixture item always starts at version 1, and these
# requests are expected to be refused by tenancy or auth before the
# service layer ever compares it against anything.
TENANCY_TABLE = [
    ("GET", "/api/projects/{project_id}",
     lambda p, s, i: f"/api/projects/{p.id}", None, None),
    ("GET", "/api/projects/{project_id}/snapshot",
     lambda p, s, i: f"/api/projects/{p.id}/snapshot", None, None),
    ("GET", "/api/projects/{project_id}/totals",
     lambda p, s, i: f"/api/projects/{p.id}/totals", None, None),
    ("PATCH", "/api/items/{item_id}",
     lambda p, s, i: f"/api/items/{i.id}", lambda p, s, i: {"notes": "test"},
     lambda p, s, i: {"If-Match": str(i.version)}),
    ("POST", "/api/items/{item_id}/approve",
     lambda p, s, i: f"/api/items/{i.id}/approve", None,
     lambda p, s, i: {"If-Match": str(i.version)}),
    ("POST", "/api/items/{item_id}/reject",
     lambda p, s, i: f"/api/items/{i.id}/reject", None,
     lambda p, s, i: {"If-Match": str(i.version)}),
    ("POST", "/api/items/{item_id}/unreject",
     lambda p, s, i: f"/api/items/{i.id}/unreject", None,
     lambda p, s, i: {"If-Match": str(i.version)}),
    ("DELETE", "/api/items/{item_id}",
     lambda p, s, i: f"/api/items/{i.id}", None,
     lambda p, s, i: {"If-Match": str(i.version)}),
    ("GET", "/api/items/{item_id}/evidence-image",
     lambda p, s, i: f"/api/items/{i.id}/evidence-image", None, None),
    ("PATCH", "/api/items/{item_id}/labor",
     lambda p, s, i: f"/api/items/{i.id}/labor", lambda p, s, i: {"hoursOverride": 1}, None),
    ("PATCH", "/api/items/{item_id}/material-price",
     lambda p, s, i: f"/api/items/{i.id}/material-price",
     lambda p, s, i: {"priceOverride": 15.5, "source": "project_price"}, None),
    ("POST", "/api/projects/{project_id}/items/bulk-approve",
     lambda p, s, i: f"/api/projects/{p.id}/items/bulk-approve",
     lambda p, s, i: {"item_ids": [str(i.id)]}, None),
    ("POST", "/api/sheets/{sheet_id}/scale",
     lambda p, s, i: f"/api/sheets/{s.id}/scale", lambda p, s, i: {"value": "1/4\" = 1'-0\""}, None),
    ("POST", "/api/projects/{project_id}/undo",
     lambda p, s, i: f"/api/projects/{p.id}/undo", None, None),
    ("POST", "/api/projects/{project_id}/redo",
     lambda p, s, i: f"/api/projects/{p.id}/redo", None, None),
    ("POST", "/api/projects/{project_id}/takeoff",
     lambda p, s, i: f"/api/projects/{p.id}/takeoff",
     lambda p, s, i: {"payload": {"sheets": [], "items": []}}, None),
    ("POST", "/api/projects/{project_id}/reprocess",
     lambda p, s, i: f"/api/projects/{p.id}/reprocess",
     lambda p, s, i: {"payload": {"sheets": [], "items": []}}, None),
    ("PUT", "/api/presence",
     lambda p, s, i: "/api/presence", lambda p, s, i: {"project_id": str(p.id)}, None),
    ("GET", "/api/projects/{project_id}/notes",
     lambda p, s, i: f"/api/projects/{p.id}/notes", None, None),
    ("POST", "/api/projects/{project_id}/notes",
     lambda p, s, i: f"/api/projects/{p.id}/notes",
     lambda p, s, i: {"title": "t", "body": "b", "category": "existing_condition"}, None),
]

TENANCY_IDS = [f"{method} {template}" for method, template, _, _, _ in TENANCY_TABLE]

# The two note routes keyed by note_id rather than project_id -- same
# shape as the item-scoped rows above (`PATCH /items/{item_id}`, etc.),
# but those reuse the `item` fixture the main table's path_fn already
# closes over via (p, s, i). A note row needs its own fixture (`note`,
# above) that the main table's lambdas were never written to accept, so
# rather than widen every existing row's signature for two new routes,
# these get their own small table and their own pair of test functions
# below, following the same rival-404 / unauthenticated-401 pattern.
NOTE_TENANCY_TABLE = [
    ("PATCH", "/api/notes/{note_id}",
     lambda n: f"/api/notes/{n.id}", lambda n: {"status": "confirmed"}, None),
    ("DELETE", "/api/notes/{note_id}",
     lambda n: f"/api/notes/{n.id}", None, None),
]

NOTE_TENANCY_IDS = [f"{method} {template}" for method, template, _, _, _ in NOTE_TENANCY_TABLE]

# Routes that are deliberately not project-scoped, so the guard test
# below must not demand a tenancy-table row for them. Not limited to
# `/api/*` -- see `_live_api_routes()`'s docstring for why the guard
# stopped filtering by prefix.
NON_PROJECT_SCOPED_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    # Org-scoped by the caller's session, not by a project id in the
    # path or body -- neither route takes a project id, so there is no
    # rival project id for this table's probe to target. This exemption
    # is about the *path*, not the body: POST /api/projects still takes
    # tenant-sensitive fields in its body (estimator_user_id), and that
    # is covered separately -- test_projects.py's
    # test_create_project_rejects_a_foreign_estimator, not this table,
    # since the thing being probed there is a user id, not a project id.
    ("GET", "/api/projects"),
    ("POST", "/api/projects"),
    # FastAPI's own framework routes -- docs UI, its OAuth2 redirect
    # target, the OpenAPI schema, and ReDoc. None of these take a
    # project id or touch tenant data; they exist the moment `FastAPI()`
    # is constructed, regardless of any router this app registers.
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/openapi.json"),
    ("GET", "/redoc"),
}


@pytest.mark.parametrize("method, path_template, path_fn, body_fn, headers_fn", TENANCY_TABLE, ids=TENANCY_IDS)
def test_a_rival_org_gets_404_never_403_or_500_on_every_project_scoped_route(
    client, dana, rival, project, sheet, item, method, path_template, path_fn, body_fn, headers_fn
):
    _sign_in_as(client, "rival@example.com", "hunter2")
    path = path_fn(project, sheet, item)
    body = body_fn(project, sheet, item) if body_fn else None
    headers = headers_fn(project, sheet, item) if headers_fn else None

    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == 404, (
        f"{method} {path} leaked status {response.status_code} to a rival org, expected 404"
    )
    assert response.json()["detail"]["code"] == "project_not_found"


# Reads are already covered by test_snapshot.py's
# test_unauthenticated_requests_get_401_on_every_read_route; this covers
# the nine mutation routes plus presence, per correction 5's "Also assert
# the same for unauthenticated callers (401) on every mutation."
MUTATION_TABLE = [row for row in TENANCY_TABLE if row[0] != "GET"]
MUTATION_IDS = [f"{method} {template}" for method, template, _, _, _ in MUTATION_TABLE]


@pytest.mark.parametrize("method, path_template, path_fn, body_fn, headers_fn", MUTATION_TABLE, ids=MUTATION_IDS)
def test_an_unauthenticated_caller_gets_401_on_every_mutation_route(
    client, project, sheet, item, method, path_template, path_fn, body_fn, headers_fn
):
    path = path_fn(project, sheet, item)
    body = body_fn(project, sheet, item) if body_fn else None
    headers = headers_fn(project, sheet, item) if headers_fn else None

    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == 401, f"{method} {path} did not require a session: {response.status_code}"


# --- The note routes, keyed by note_id rather than project_id ---


@pytest.mark.parametrize("method, path_template, path_fn, body_fn, headers_fn", NOTE_TENANCY_TABLE, ids=NOTE_TENANCY_IDS)
def test_a_rival_org_gets_404_on_every_note_route(
    client, dana, rival, note, method, path_template, path_fn, body_fn, headers_fn
):
    _sign_in_as(client, "rival@example.com", "hunter2")
    path = path_fn(note)
    body = body_fn(note) if body_fn else None
    headers = headers_fn(note) if headers_fn else None

    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == 404, (
        f"{method} {path} leaked status {response.status_code} to a rival org, expected 404"
    )
    assert response.json()["detail"]["code"] == "project_not_found"


@pytest.mark.parametrize("method, path_template, path_fn, body_fn, headers_fn", NOTE_TENANCY_TABLE, ids=NOTE_TENANCY_IDS)
def test_an_unauthenticated_caller_gets_401_on_every_note_route(
    client, note, method, path_template, path_fn, body_fn, headers_fn
):
    path = path_fn(note)
    body = body_fn(note) if body_fn else None
    headers = headers_fn(note) if headers_fn else None

    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == 401, f"{method} {path} did not require a session: {response.status_code}"


# --- The guard: the table above cannot silently fall out of date ---


def _live_api_routes():
    """Every real `(method, path)` pair FastAPI will actually dispatch to,
    across the whole app -- deliberately NOT filtered to `path.startswith
    ("/api")`.

    A review finding on this task: the original version of this function
    filtered to the `/api` prefix, on the assumption that every route in
    this app carries it. That assumption is one forgotten `prefix="/api"`
    kwarg away from being false -- `collab/router.py`'s `APIRouter(prefix
    ="/api", ...)` is no different in shape from any other router
    construction, and a router built without that kwarg would mount its
    routes at `/projects/{project_id}/...` instead of `/api/projects/
    {project_id}/...`. The old filter made such a route invisible to this
    guard entirely: not in `TENANCY_TABLE`, not in
    `NON_PROJECT_SCOPED_ROUTES`, and not even in the set this function
    returned, so `test_every_project_scoped_route_is_covered_by_the_
    tenancy_table` would stay green while a real, reachable, ungated
    route shipped. Falsified directly: adding a throwaway router mounted
    without the `/api` prefix reproduced exactly that silent gap.

    Scanning every route (still skipping only `HEAD`, which FastAPI adds
    automatically alongside every `GET`) means the four framework routes
    FastAPI mounts outside `/api` (`/docs`, `/docs/oauth2-redirect`,
    `/openapi.json`, `/redoc`) now show up here too -- listed in
    `NON_PROJECT_SCOPED_ROUTES` rather than filtered out, so they're an
    explicit, visible exemption instead of an implicit one baked into
    this function's prefix check.
    """
    found = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or methods is None:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            found.add((method, path))
    return found


def test_every_project_scoped_route_is_covered_by_the_tenancy_table():
    """Enumerates the app's real routes rather than trusting this file to
    stay in sync by hand. A route that is neither in TENANCY_TABLE nor in
    NON_PROJECT_SCOPED_ROUTES fails this test -- the next person adding an
    endpoint has to make a deliberate choice, not get a green suite with
    an ungated route.
    """
    covered = (
        {(method, template) for method, template, _, _, _ in TENANCY_TABLE}
        | {(method, template) for method, template, _, _, _ in NOTE_TENANCY_TABLE}
        | NON_PROJECT_SCOPED_ROUTES
    )
    missing = _live_api_routes() - covered

    assert not missing, (
        f"routes with no tenancy-table coverage and no explicit exemption: {sorted(missing)}"
    )


def test_the_tenancy_table_does_not_list_a_route_that_no_longer_exists():
    """The inverse check: a row in the table that doesn't correspond to a
    real route would silently stop testing anything the moment the route
    it was written for got renamed or removed.
    """
    live = _live_api_routes()
    stale = (
        {(method, template) for method, template, _, _, _ in TENANCY_TABLE}
        | {(method, template) for method, template, _, _, _ in NOTE_TENANCY_TABLE}
    ) - live

    assert not stale, f"tenancy-table rows with no matching live route: {sorted(stale)}"
