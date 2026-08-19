import contextlib
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.takeoff.actions import ACTION_LOG_GUARD_DDL
from app.takeoff.models import Item, Project, ReviewStatus, Sheet

# The test suite drops and recreates a whole database on every run, so the
# database name it targets must come from TEST_DATABASE_URL — never from a
# hardcoded literal, and never by silently falling back to DATABASE_URL.
# Failing loudly here (at import time, before any fixture runs) is
# deliberate: a missing or misconfigured TEST_DATABASE_URL must never result
# in the development database being dropped.
if not settings.test_database_url:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. The test suite creates and drops a "
        "database on every run and must never fall back to DATABASE_URL — "
        "set TEST_DATABASE_URL to a dedicated test database."
    )

_test_url = make_url(settings.test_database_url)
_app_url = make_url(settings.database_url)

if _test_url.database == _app_url.database:
    raise RuntimeError(
        f"TEST_DATABASE_URL names the same database as DATABASE_URL "
        f"({_test_url.database!r}). Refusing to drop and recreate the "
        "development database on every test run — point TEST_DATABASE_URL "
        "at a differently named database."
    )

TEST_DB_NAME = _test_url.database


def _quote_ident(name: str) -> str:
    """Quote a Postgres identifier for safe interpolation into DDL.

    `text()` bind parameters can only carry values, not identifiers, so the
    database name has to be spliced into the DROP/CREATE statements
    directly. Standard SQL identifier quoting (wrap in double quotes,
    double any embedded double quotes) keeps that safe regardless of what
    TEST_DATABASE_URL names.
    """
    return '"' + name.replace('"', '""') + '"'


test_engine = create_engine(settings.test_database_url)
TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def create_test_database():
    # Dispose any pooled connections on the test engine before dropping the
    # database — Postgres refuses to drop a database with open connections,
    # and this fixture may run after other session-scoped setup has already
    # touched test_engine.
    test_engine.dispose()
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    quoted_name = _quote_ident(TEST_DB_NAME)
    with admin.connect() as conn:
        conn.execute(text(f"drop database if exists {quoted_name}"))
        conn.execute(text(f"create database {quoted_name}"))
    admin.dispose()
    yield


@pytest.fixture
def db():
    Base.metadata.create_all(test_engine)
    # Base.metadata.create_all does not run migrations, so the append-only
    # guard (triggers, ENABLE ALWAYS, the privilege REVOKE) has to be
    # installed here too. Sourced from the same constant the migration
    # executes -- see app.takeoff.actions -- so the two paths cannot drift
    # apart and leave this fixture's tests passing against a table that
    # doesn't actually have the guard.
    with test_engine.begin() as conn:
        conn.execute(text(ACTION_LOG_GUARD_DDL))
    session = TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(test_engine)


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def org(db):
    from app.identity.models import Org

    o = Org(name="Meridian Electric")
    db.add(o)
    db.flush()
    return o


@pytest.fixture
def project(db, org):
    p = Project(org_id=org.id, name="Meridian Distribution Center", revision_set_label="E1.1 Rev 3")
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def sheet(db, project):
    s = Sheet(project_id=project.id, number="E2.1", title="Power plan — warehouse",
              discipline="Electrical", revision="Rev 2", scale="mixed", scale_options=[], plan="warehouse")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def item(db, project, sheet):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle",
             name="20A duplex receptacle", system="Power", category="Devices",
             quantity=14, unit="EA", status=ReviewStatus.READY, x=556, y=508)
    db.add(i)
    db.flush()
    return i


@pytest.fixture
def dana(db, org):
    from app.auth.passwords import hash_password
    from app.identity.models import User

    u = User(org_id=org.id, email="dana@example.com", password_hash=hash_password("correct-horse"),
             name="Dana Whitfield", color="#23528f")
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def signed_in_user(client, dana):
    """Logs `client` in as `dana`, the way `_sign_in()` helpers repeated
    across test_mutation_endpoints.py, test_observability.py, and
    test_presence.py already do -- pulled into a fixture here so the
    projects-list tests (task-2-brief.md) can depend on an authenticated
    client without copying that helper a fourth time."""
    response = client.post("/api/auth/login", json={"email": dana.email, "password": "correct-horse"})
    assert response.status_code == 200, response.text
    return dana


@pytest.fixture
def seeded_org(db, org, signed_in_user):
    """The project GET /api/projects is expected to list: the exact
    dashboard fields from task-1-brief.md's Project columns, plus twelve
    items (task-2-brief.md's count assertion) with one Missing information
    item so `missing_info` has something real to count."""
    from app.takeoff.models import ReviewStatus

    project = Project(
        org_id=org.id,
        name="Meridian Distribution Center",
        number="26-0207",
        customer="Bellweather Construction",
        location="Stockton, CA",
        stage="review",
        revision_set_label="E1.1 Rev 3",
        estimator_user_id=signed_in_user.id,
    )
    db.add(project)
    db.flush()

    sheet = Sheet(
        project_id=project.id, number="E2.1", title="Power plan — warehouse", discipline="Electrical",
        revision="Rev 2", scale="mixed", scale_options=[], plan="warehouse",
    )
    db.add(sheet)
    db.flush()

    for n in range(12):
        status = ReviewStatus.MISSING if n == 0 else ReviewStatus.READY
        db.add(Item(
            project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=f"Item {n}",
            system="Power", category="Devices", quantity=1, unit="EA", status=status, x=100, y=100,
        ))
    db.flush()
    return project


@pytest.fixture
def other_org_project(db, signed_in_user):
    """A project in an org other than `signed_in_user`'s -- the tenancy
    check on GET /api/projects must exclude it at the data layer, not
    because the caller remembered to filter (ROADMAP.md §2.3)."""
    from app.identity.models import Org

    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    p = Project(org_id=other_org.id, name="Ferrovia's own project", revision_set_label="")
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def archived_project(db, org, signed_in_user):
    """A project in `signed_in_user`'s own org, archived -- so the
    archived-by-default filter is exercised on its own, independent of the
    tenancy filter `other_org_project` exercises."""
    p = Project(
        org_id=org.id, name="Superseded bid", revision_set_label="",
        archived_at=datetime.now(timezone.utc),
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def capture_queries():
    """Records the SQL a block issues against the test engine, so a test
    can assert that a list endpoint did not fall into N+1
    (task-2-brief.md). `test_engine` above is a plain module-level engine
    rather than a fixture, so this listens on it directly instead of
    taking a `db_engine` fixture parameter that doesn't exist here."""

    @contextlib.contextmanager
    def _capture():
        statements: list[str] = []

        def before_cursor_execute(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        event.listen(test_engine, "before_cursor_execute", before_cursor_execute)
        try:
            yield statements
        finally:
            event.remove(test_engine, "before_cursor_execute", before_cursor_execute)

    return _capture
