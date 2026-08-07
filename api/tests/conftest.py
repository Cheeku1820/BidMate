import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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
