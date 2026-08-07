import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app

test_engine = create_engine(settings.test_database_url or settings.database_url)
TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def create_test_database():
    # Dispose any pooled connections on the test engine before dropping the
    # database — Postgres refuses to drop a database with open connections,
    # and this fixture may run after other session-scoped setup has already
    # touched test_engine.
    test_engine.dispose()
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("drop database if exists takeoff_test"))
        conn.execute(text("create database takeoff_test"))
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
