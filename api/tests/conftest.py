import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app

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
