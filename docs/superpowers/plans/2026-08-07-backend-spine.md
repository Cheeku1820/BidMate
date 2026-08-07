# Backend Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the prototype's browser-only storage with a FastAPI + Postgres backend, real accounts, and a server that enforces the review rules — then port the existing review workspace onto it without touching the canvas components.

**Architecture:** One FastAPI application split into `auth`, `identity`, `takeoff`, and `collab` modules. Routers do HTTP only; a service layer owns every rule and is the only thing that writes; every mutation appends to an `actions` table the database itself refuses to update or delete. The React client gains a domain-level store adapter with two implementations — seed (today's `localStorage`) and API — chosen by an environment variable.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, PostgreSQL 16, pytest, Docker Compose. Client stays React 18 + Vite; Vitest added for the store contract test.

## Global Constraints

- **Status enum has exactly four values:** `ready`, `attention`, `missing`, `approved`. Adding a fifth requires a deliberate migration. `rejected` is NOT a status — it is `rejected_at` + `rejected_by_user_id` on the item.
- **Warning rows are optional; warning content is not.** `title`, `found`, `why`, `fix`, `where` are all NOT NULL on the `warnings` table.
- **Routers never enforce rules.** Parsing and serialization only. Every rule lives in a service function.
- **Dependencies point one direction:** `router → service → models`. A service never imports a router. Nothing imports `main`.
- **No file over ~300 lines.** Split when it grows.
- **The action log is append-only.** No code path updates or deletes `actions`; a Postgres trigger enforces it.
- **Every mutation is attributable.** `commit()` requires an actor; there is no write path around it.
- **Layer toggles have no server representation.** Do not add an endpoint for visibility.
- **Tests run against real Postgres**, never SQLite.
- **Copy rules for any user-facing string:** sentence case, no exclamation marks, no "successfully", no "please", never "Something went wrong" alone. Error copy names a recovery action.
- **Never expose processing internals** — no confidence scores, model names, or pipeline stage names in any response.
- **Components `BlueprintCanvas.jsx`, `PlanDrawing.jsx`, `Symbols.jsx` must not be modified.**

---

## File Structure

**Infrastructure**

| Path | Responsibility |
|---|---|
| `docker-compose.yml` | postgres, api, web services |
| `api/Dockerfile` | api image |
| `api/requirements.txt` | pinned dependencies |
| `api/alembic.ini`, `api/migrations/` | schema migrations |

**Application core**

| Path | Responsibility |
|---|---|
| `api/app/config.py` | settings from environment |
| `api/app/db.py` | engine, `Base`, `get_db` dependency |
| `api/app/errors.py` | `DomainError` and its handler |
| `api/app/observability.py` | request id middleware, JSON logging |
| `api/app/main.py` | app assembly, router registration |

**Modules** — each is `models` / `schemas` / `service` / `router`

| Path | Responsibility |
|---|---|
| `api/app/identity/` | orgs, users |
| `api/app/auth/` | passwords, sessions, `current_user` |
| `api/app/takeoff/models.py` | projects, sheets, items, warnings, actions |
| `api/app/takeoff/service.py` | mutations and rules; owns `commit()` |
| `api/app/takeoff/undo.py` | undo/redo derivation over the action log |
| `api/app/takeoff/totals.py` | the single totals query |
| `api/app/takeoff/snapshot.py` | the poll payload and its version |
| `api/app/takeoff/router.py` | HTTP layer |
| `api/app/collab/` | presence |
| `api/app/seed.py` | demo org, user, project from the prototype fixture |

**Client**

| Path | Responsibility |
|---|---|
| `src/lib/store/index.js` | picks an implementation from `VITE_DATA_SOURCE` |
| `src/lib/store/seed.js` | today's localStorage + BroadcastChannel behaviour |
| `src/lib/store/api.js` | fetch + polling against the API |
| `src/lib/store/contract.test.js` | both implementations satisfy one interface |
| `src/components/Login.jsx` | email/password screen |
| `src/App.jsx` | modified — calls store methods instead of `read`/`write` |
| `src/lib/sync.js` | deleted; its internals move into `store/seed.js` |

---

## Task 1: Compose, Postgres, and a FastAPI skeleton that answers

**Files:**
- Create: `docker-compose.yml`, `api/Dockerfile`, `api/.dockerignore`, `api/requirements.txt`
- Create: `api/app/__init__.py`, `api/app/config.py`, `api/app/db.py`, `api/app/main.py`
- Test: `api/tests/conftest.py`, `api/tests/test_health.py`

**Interfaces:**
- Consumes: nothing
- Produces: `app.config.Settings` with `database_url: str`, `session_ttl_hours: int = 12`, `cookie_secure: bool = False`; `app.db.Base`; `app.db.get_db() -> Iterator[Session]`; `app.main.app`; pytest fixture `client -> TestClient`; pytest fixture `db -> Session`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_health.py
def test_health_reports_database_connectivity(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `docker compose run --rm api pytest tests/test_health.py -v`
Expected: FAIL — no `api` service or no `/api/health` route.

- [ ] **Step 3: Write `api/requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
sqlalchemy==2.0.36
alembic==1.14.0
psycopg[binary]==3.2.3
pydantic==2.10.4
pydantic-settings==2.7.0
argon2-cffi==23.1.0
python-multipart==0.0.20
pytest==8.3.4
httpx==0.28.1
```

- [ ] **Step 4: Write `api/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

And `api/.dockerignore`:

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
```

- [ ] **Step 5: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: takeoff
      POSTGRES_PASSWORD: takeoff
      POSTGRES_DB: takeoff
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U takeoff"]
      interval: 3s
      timeout: 3s
      retries: 20

  api:
    build: ./api
    environment:
      DATABASE_URL: postgresql+psycopg://takeoff:takeoff@postgres:5432/takeoff
      TEST_DATABASE_URL: postgresql+psycopg://takeoff:takeoff@postgres:5432/takeoff_test
    volumes: ["./api:/srv"]
    ports: ["8000:8000"]
    depends_on:
      postgres: {condition: service_healthy}

volumes:
  pgdata:
```

- [ ] **Step 6: Write `api/app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str = ""
    session_ttl_hours: int = 12
    cookie_secure: bool = False


settings = Settings()
```

- [ ] **Step 7: Write `api/app/db.py`**

```python
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 8: Write `api/app/main.py`**

```python
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

app = FastAPI(title="Takeoff API")


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("select 1"))
    return {"status": "ok", "database": "ok"}
```

- [ ] **Step 9: Write `api/tests/conftest.py`**

```python
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
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("drop database if exists takeoff_test"))
        conn.execute(text("create database takeoff_test"))
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
```

- [ ] **Step 10: Run the test to verify it passes**

Run: `docker compose up -d postgres && docker compose run --rm api pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add docker-compose.yml api/
git commit -m "Add API container, Postgres, and a health check with a passing test"
```

---

## Task 2: Alembic and the identity tables

**Files:**
- Create: `api/alembic.ini`, `api/migrations/env.py`, `api/migrations/script.py.mako`
- Create: `api/app/identity/__init__.py`, `api/app/identity/models.py`
- Create: `api/migrations/versions/0001_identity.py`
- Test: `api/tests/test_identity.py`

**Interfaces:**
- Consumes: `app.db.Base`
- Produces: `app.identity.models.Org(id: UUID, name: str, created_at: datetime)`; `app.identity.models.User(id: UUID, org_id: UUID, email: str, password_hash: str, name: str, color: str, external_id: str | None, created_at: datetime, deactivated_at: datetime | None)`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_identity.py
import pytest
from sqlalchemy.exc import IntegrityError

from app.identity.models import Org, User


def test_email_is_unique_across_the_system(db):
    org = Org(name="Meridian Electric")
    db.add(org)
    db.flush()

    db.add(User(org_id=org.id, email="dana@example.com", password_hash="x", name="Dana", color="#23528f"))
    db.flush()

    db.add(User(org_id=org.id, email="dana@example.com", password_hash="y", name="Other", color="#1c6f47"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_external_id_is_nullable_so_an_identity_provider_can_map_later(db):
    org = Org(name="Meridian Electric")
    db.add(org)
    db.flush()

    user = User(org_id=org.id, email="dana@example.com", password_hash="x", name="Dana", color="#23528f")
    db.add(user)
    db.flush()

    assert user.external_id is None
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `docker compose run --rm api pytest tests/test_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: app.identity`

- [ ] **Step 3: Write `api/app/identity/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(200))
    color: Mapped[str] = mapped_column(String(9))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Create `api/app/identity/__init__.py` as an empty file.

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose run --rm api pytest tests/test_identity.py -v`
Expected: PASS (the `db` fixture calls `create_all`, so this passes before migrations exist)

- [ ] **Step 5: Initialise Alembic**

Run: `docker compose run --rm api alembic init -t async migrations`, then replace the generated `migrations/env.py` target metadata block with:

```python
from app.db import Base
from app.identity import models as identity_models  # noqa: F401

target_metadata = Base.metadata
```

Set `sqlalchemy.url` in `alembic.ini` to an empty string and resolve it in `env.py`:

```python
from app.config import settings

config.set_main_option("sqlalchemy.url", settings.database_url)
```

- [ ] **Step 6: Generate and inspect the migration**

Run: `docker compose run --rm api alembic revision --autogenerate -m "identity"`
Rename the generated file to `0001_identity.py`. Read it — confirm it creates `orgs` and `users` with the unique constraints on `users.email` and `users.external_id`.

- [ ] **Step 7: Apply the migration and verify the schema matches the models**

Run: `docker compose run --rm api alembic upgrade head && docker compose run --rm api alembic check`
Expected: `No new upgrade operations detected.`

- [ ] **Step 8: Commit**

```bash
git add api/alembic.ini api/migrations api/app/identity api/tests/test_identity.py
git commit -m "Add Alembic and the orgs and users tables"
```

---

## Task 3: Password hashing, sessions, and the current_user boundary

**Files:**
- Create: `api/app/auth/__init__.py`, `api/app/auth/passwords.py`, `api/app/auth/models.py`, `api/app/auth/service.py`, `api/app/auth/dependencies.py`, `api/app/auth/schemas.py`, `api/app/auth/router.py`
- Create: `api/app/errors.py`
- Create: `api/migrations/versions/0002_sessions.py`
- Modify: `api/app/main.py`
- Test: `api/tests/test_auth.py`

**Interfaces:**
- Consumes: `app.identity.models.User`, `app.db.get_db`
- Produces: `app.auth.passwords.hash_password(raw: str) -> str`; `app.auth.passwords.verify_password(raw: str, hashed: str) -> bool`; `app.auth.models.Session(id: UUID, user_id: UUID, expires_at: datetime, revoked_at: datetime | None)`; `app.auth.service.login(db, email: str, password: str) -> Session`; `app.auth.service.logout(db, session_id: UUID) -> None`; `app.auth.dependencies.current_user(request, db) -> User`; `app.errors.DomainError(code: str, message: str, status: int = 400)`; cookie name `takeoff_session`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_auth.py
import pytest

from app.auth.passwords import hash_password
from app.identity.models import Org, User


@pytest.fixture
def dana(db):
    org = Org(name="Meridian Electric")
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id,
        email="dana@example.com",
        password_hash=hash_password("correct-horse"),
        name="Dana Whitfield",
        color="#23528f",
    )
    db.add(user)
    db.flush()
    return user


def test_login_sets_a_session_cookie_and_returns_the_user(client, dana):
    response = client.post("/api/auth/login", json={"email": "dana@example.com", "password": "correct-horse"})

    assert response.status_code == 200
    assert response.json()["name"] == "Dana Whitfield"
    assert "takeoff_session" in response.cookies


def test_login_with_a_wrong_password_is_refused_without_saying_which_field_was_wrong(client, dana):
    response = client.post("/api/auth/login", json={"email": "dana@example.com", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"
    assert "password" not in response.json()["detail"]["message"].lower()


def test_me_requires_a_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_logout_revokes_the_session(client, dana):
    client.post("/api/auth/login", json={"email": "dana@example.com", "password": "correct-horse"})
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: app.auth`

- [ ] **Step 3: Write `api/app/errors.py`**

```python
from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Raised by service functions when a rule refuses an operation."""

    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"detail": {"code": exc.code, "message": exc.message}},
    )
```

- [ ] **Step 4: Write `api/app/auth/passwords.py`**

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, raw)
    except VerifyMismatchError:
        return False
```

- [ ] **Step 5: Write `api/app/auth/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 6: Write `api/app/auth/service.py`**

```python
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.models import Session
from app.auth.passwords import verify_password
from app.config import settings
from app.errors import DomainError
from app.identity.models import User

INVALID = DomainError("invalid_credentials", "That email and password combination was not recognised.", status=401)


def login(db: DbSession, email: str, password: str) -> Session:
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if user is None or user.deactivated_at is not None:
        raise INVALID
    if not verify_password(password, user.password_hash):
        raise INVALID

    session = Session(user_id=user.id, expires_at=datetime.utcnow() + timedelta(hours=settings.session_ttl_hours))
    db.add(session)
    db.flush()
    return session


def logout(db: DbSession, session_id: uuid.UUID) -> None:
    session = db.get(Session, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.utcnow()
        db.flush()


def user_for_session(db: DbSession, session_id: uuid.UUID) -> User | None:
    session = db.get(Session, session_id)
    if session is None or session.revoked_at is not None or session.expires_at < datetime.utcnow():
        return None
    return db.get(User, session.user_id)
```

- [ ] **Step 7: Write `api/app/auth/dependencies.py`**

```python
import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session as DbSession

from app.auth.service import user_for_session
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User

COOKIE_NAME = "takeoff_session"

NOT_SIGNED_IN = DomainError("not_signed_in", "Sign in to continue.", status=401)


def current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise NOT_SIGNED_IN
    try:
        session_id = uuid.UUID(raw)
    except ValueError:
        raise NOT_SIGNED_IN
    user = user_for_session(db, session_id)
    if user is None:
        raise NOT_SIGNED_IN
    return user
```

- [ ] **Step 8: Write `api/app/auth/schemas.py` and `api/app/auth/router.py`**

```python
# schemas.py
import uuid

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    name: str
    email: EmailStr
    color: str

    model_config = {"from_attributes": True}
```

```python
# router.py
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session as DbSession

from app.auth import service
from app.auth.dependencies import COOKIE_NAME, current_user
from app.auth.schemas import LoginRequest, UserOut
from app.config import settings
from app.db import get_db
from app.identity.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: DbSession = Depends(get_db)) -> User:
    session = service.login(db, body.email, body.password)
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        str(session.id),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_hours * 3600,
    )
    return db.get(User, session.user_id)


@router.post("/logout", status_code=204)
def logout(response: Response, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> None:
    import uuid as _uuid

    from fastapi import Request  # noqa: F401

    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user
```

Note: `logout` needs the session id, which lives on the request. Replace the body with a version that reads it directly:

```python
@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)) -> None:
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        try:
            service.logout(db, uuid.UUID(raw))
            db.commit()
        except ValueError:
            pass
    response.delete_cookie(COOKIE_NAME)
```

with `import uuid` and `from fastapi import Request` at the top of the file, and the earlier placeholder version removed.

- [ ] **Step 9: Register the router and the error handler in `api/app/main.py`**

```python
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.router import router as auth_router
from app.db import get_db
from app.errors import DomainError, domain_error_handler

app = FastAPI(title="Takeoff API")
app.add_exception_handler(DomainError, domain_error_handler)
app.include_router(auth_router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("select 1"))
    return {"status": "ok", "database": "ok"}
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_auth.py -v`
Expected: 4 passed

- [ ] **Step 11: Generate the migration and verify it is clean**

Run: `docker compose run --rm api alembic revision --autogenerate -m "sessions"`, rename to `0002_sessions.py`, then `alembic upgrade head && alembic check`
Expected: `No new upgrade operations detected.`

- [ ] **Step 12: Commit**

```bash
git add api/app/auth api/app/errors.py api/app/main.py api/migrations api/tests/test_auth.py
git commit -m "Add password auth with server-side sessions behind a current_user dependency"
```

---

## Task 4: The takeoff tables

**Files:**
- Create: `api/app/takeoff/__init__.py`, `api/app/takeoff/models.py`
- Create: `api/migrations/versions/0003_takeoff.py`
- Test: `api/tests/test_takeoff_models.py`

**Interfaces:**
- Consumes: `app.db.Base`, `app.identity.models.User`
- Produces: `ReviewStatus` enum with members `READY = "ready"`, `ATTENTION = "attention"`, `MISSING = "missing"`, `APPROVED = "approved"`; models `Project(id, org_id, name, revision_set_label)`, `Sheet(id, project_id, number, title, discipline, revision, revision_date, scale, scale_options, plan, superseded_at, sort_order)`, `Item(id, project_id, sheet_id, symbol, name, description, system, category, quantity, unit, status, approved_by_user_id, approved_at, rejected_at, rejected_by_user_id, x, y, path, notes, evidence)`, `Warning(id, item_id, sheet_id, title, found, why, fix, where_)`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_takeoff_models.py
import pytest
from sqlalchemy.exc import DataError, IntegrityError

from app.takeoff.models import Item, Project, ReviewStatus, Sheet, Warning


def test_review_status_has_exactly_four_members():
    assert [s.value for s in ReviewStatus] == ["ready", "attention", "missing", "approved"]


def test_an_invented_status_is_rejected_by_the_database(db, project, sheet):
    db.execute(
        Item.__table__.insert().values(
            project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="x",
            system="Power", category="Devices", quantity=1, unit="EA", status="in_review",
        )
    )
    with pytest.raises((DataError, IntegrityError)):
        db.flush()


def test_a_warning_cannot_be_written_with_a_missing_field(db, project, sheet, item):
    db.add(Warning(item_id=item.id, title="Scale needs confirmation", found="two labels",
                   why="lengths may be wrong", fix="select the scale", where_=None))
    with pytest.raises(IntegrityError):
        db.flush()


def test_rejection_is_a_field_not_a_status(db, item):
    assert item.rejected_at is None
    assert hasattr(item, "rejected_by_user_id")
```

Add shared fixtures to `api/tests/conftest.py`:

```python
from app.takeoff.models import Item, Project, ReviewStatus, Sheet


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
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_takeoff_models.py -v`
Expected: FAIL — `ModuleNotFoundError: app.takeoff`

- [ ] **Step 3: Write `api/app/takeoff/models.py`**

```python
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReviewStatus(enum.Enum):
    READY = "ready"
    ATTENTION = "attention"
    MISSING = "missing"
    APPROVED = "approved"


status_enum = Enum(ReviewStatus, name="review_status", values_callable=lambda e: [m.value for m in e])


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    revision_set_label: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sheet(Base):
    __tablename__ = "sheets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(300))
    discipline: Mapped[str] = mapped_column(String(100))
    revision: Mapped[str] = mapped_column(String(50))
    revision_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    scale: Mapped[str] = mapped_column(String(50))
    scale_options: Mapped[list] = mapped_column(JSONB, default=list)
    plan: Mapped[str] = mapped_column(String(50))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)

    symbol: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    system: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    unit: Mapped[str] = mapped_column(String(10))

    status: Mapped[ReviewStatus] = mapped_column(status_enum, default=ReviewStatus.READY, index=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    path: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Warning(Base):
    """Optional per item — but a row that exists is never partial."""

    __tablename__ = "warnings"
    __table_args__ = (
        CheckConstraint("(item_id is not null) or (sheet_id is not null)", name="warning_has_a_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), nullable=True, index=True)
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    found: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    fix: Mapped[str] = mapped_column(Text, nullable=False)
    where_: Mapped[str] = mapped_column("where", Text, nullable=False)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_takeoff_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Generate the migration and confirm it is clean**

Run: `docker compose run --rm api alembic revision --autogenerate -m "takeoff"`, rename to `0003_takeoff.py`, then `alembic upgrade head && alembic check`
Expected: `No new upgrade operations detected.`

- [ ] **Step 6: Commit**

```bash
git add api/app/takeoff api/migrations api/tests
git commit -m "Add projects, sheets, items, and warnings with a four-value status enum"
```

---

## Task 5: The action log and its append-only trigger

**Files:**
- Modify: `api/app/takeoff/models.py`
- Create: `api/app/takeoff/service.py`
- Create: `api/migrations/versions/0004_actions.py`
- Test: `api/tests/test_action_log.py`

**Interfaces:**
- Consumes: `app.takeoff.models`, `app.identity.models.User`
- Produces: `Action(id, project_id, kind, item_id, sheet_id, actor_user_id, label, before, after, undoes_action_id, created_at)`; `app.takeoff.service.commit(db, *, actor: User, project_id: UUID, kind: str, label: str, before: dict, after: dict, item_id: UUID | None = None, sheet_id: UUID | None = None, undoes_action_id: UUID | None = None) -> Action`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_action_log.py
import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError, ProgrammingError

from app.takeoff import service
from app.takeoff.models import Action


def test_commit_records_the_actor_and_a_label(db, dana, project, item):
    action = service.commit(
        db, actor=dana, project_id=project.id, kind="approve", label="Approved 20A duplex receptacle",
        before={"status": "ready"}, after={"status": "approved"}, item_id=item.id,
    )
    db.flush()

    assert action.actor_user_id == dana.id
    assert action.label == "Approved 20A duplex receptacle"
    assert action.before == {"status": "ready"}


def test_the_database_refuses_to_update_an_action(db, dana, project, item):
    action = service.commit(db, actor=dana, project_id=project.id, kind="approve", label="Approved",
                            before={}, after={}, item_id=item.id)
    db.flush()

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("update actions set label = 'rewritten' where id = :id"), {"id": action.id})


def test_the_database_refuses_to_delete_an_action(db, dana, project, item):
    action = service.commit(db, actor=dana, project_id=project.id, kind="approve", label="Approved",
                            before={}, after={}, item_id=item.id)
    db.flush()

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("delete from actions where id = :id"), {"id": action.id})
```

Add a `dana` fixture to `conftest.py`:

```python
@pytest.fixture
def dana(db, org):
    from app.auth.passwords import hash_password
    from app.identity.models import User

    u = User(org_id=org.id, email="dana@example.com", password_hash=hash_password("correct-horse"),
             name="Dana Whitfield", color="#23528f")
    db.add(u)
    db.flush()
    return u
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_action_log.py -v`
Expected: FAIL — `cannot import name 'Action'`

- [ ] **Step 3: Add the `Action` model to `api/app/takeoff/models.py`**

```python
class Action(Base):
    """Append-only. Undo appends a compensating row; nothing is ever rewritten."""

    __tablename__ = "actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(String(300))
    before: Mapped[dict] = mapped_column(JSONB, default=dict)
    after: Mapped[dict] = mapped_column(JSONB, default=dict)
    undoes_action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("actions.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
```

Note `item_id` and `sheet_id` are plain columns without foreign keys — a deleted item must not take its history with it.

- [ ] **Step 4: Write `api/app/takeoff/service.py` with `commit` only**

```python
import uuid

from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.models import Action


def commit(
    db: DbSession,
    *,
    actor: User,
    project_id: uuid.UUID,
    kind: str,
    label: str,
    before: dict,
    after: dict,
    item_id: uuid.UUID | None = None,
    sheet_id: uuid.UUID | None = None,
    undoes_action_id: uuid.UUID | None = None,
) -> Action:
    """The only way anything in this module records a change.

    Every mutation routes through here so attribution and the audit trail
    cannot be forgotten by a future endpoint.
    """
    action = Action(
        project_id=project_id, kind=kind, label=label, before=before, after=after,
        item_id=item_id, sheet_id=sheet_id, actor_user_id=actor.id, undoes_action_id=undoes_action_id,
    )
    db.add(action)
    return action
```

- [ ] **Step 5: Write the migration with the trigger**

Generate with `alembic revision --autogenerate -m "actions"`, rename to `0004_actions.py`, then add to its `upgrade()`:

```python
    op.execute(
        """
        create or replace function actions_are_append_only() returns trigger as $$
        begin
            raise exception 'actions is append-only: % is not permitted', tg_op;
        end;
        $$ language plpgsql;

        create trigger actions_no_update before update on actions
            for each statement execute function actions_are_append_only();

        create trigger actions_no_delete before delete on actions
            for each statement execute function actions_are_append_only();
        """
    )
```

and to its `downgrade()`:

```python
    op.execute(
        """
        drop trigger if exists actions_no_update on actions;
        drop trigger if exists actions_no_delete on actions;
        drop function if exists actions_are_append_only();
        """
    )
```

- [ ] **Step 6: Make the test fixture create the trigger too**

The `db` fixture uses `create_all`, which does not run migrations. Add to `conftest.py`, inside the `db` fixture immediately after `Base.metadata.create_all(test_engine)`:

```python
    with test_engine.begin() as conn:
        conn.execute(text("""
            create or replace function actions_are_append_only() returns trigger as $$
            begin
                raise exception 'actions is append-only: % is not permitted', tg_op;
            end;
            $$ language plpgsql;
            drop trigger if exists actions_no_update on actions;
            drop trigger if exists actions_no_delete on actions;
            create trigger actions_no_update before update on actions
                for each statement execute function actions_are_append_only();
            create trigger actions_no_delete before delete on actions
                for each statement execute function actions_are_append_only();
        """))
```

with `from sqlalchemy import text` imported at the top.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_action_log.py -v`
Expected: 3 passed

- [ ] **Step 8: Apply the migration and confirm it is clean**

Run: `docker compose run --rm api alembic upgrade head && docker compose run --rm api alembic check`
Expected: `No new upgrade operations detected.`

- [ ] **Step 9: Commit**

```bash
git add api/app/takeoff api/migrations api/tests/test_action_log.py api/tests/conftest.py
git commit -m "Add an append-only action log enforced by a Postgres trigger"
```

---

## Task 6: The single totals query

**Files:**
- Create: `api/app/takeoff/totals.py`
- Test: `api/tests/test_totals.py`

**Interfaces:**
- Consumes: `app.takeoff.models`
- Produces: `app.takeoff.totals.approved_totals(db, project_id: UUID) -> TotalsResult` where `TotalsResult` is a dataclass with `by_system: dict[str, Decimal]`, `approved_count: int`, `remaining_count: int`, `attention_count: int`, `missing_count: int`, `approved_units: Decimal`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_totals.py
from decimal import Decimal

from app.takeoff.models import Item, ReviewStatus
from app.takeoff.totals import approved_totals


def _item(project, sheet, **kw):
    base = dict(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="x",
                system="Power", category="Devices", quantity=Decimal("10"), unit="EA",
                status=ReviewStatus.APPROVED)
    base.update(kw)
    return Item(**base)


def test_totals_count_only_approved_items(db, project, sheet):
    db.add(_item(project, sheet))
    db.add(_item(project, sheet, status=ReviewStatus.READY))
    db.flush()

    result = approved_totals(db, project.id)

    assert result.approved_units == Decimal("10")
    assert result.approved_count == 1
    assert result.remaining_count == 1


def test_superseded_sheets_never_contribute(db, project, sheet):
    from datetime import datetime

    db.add(_item(project, sheet))
    db.flush()
    sheet.superseded_at = datetime.utcnow()
    db.flush()

    assert approved_totals(db, project.id).approved_units == Decimal("0")


def test_rejected_items_never_contribute(db, project, sheet, dana):
    from datetime import datetime

    db.add(_item(project, sheet, rejected_at=datetime.utcnow(), rejected_by_user_id=dana.id))
    db.flush()

    assert approved_totals(db, project.id).approved_units == Decimal("0")


def test_totals_group_by_system(db, project, sheet):
    db.add(_item(project, sheet, system="Power", quantity=Decimal("14")))
    db.add(_item(project, sheet, system="Lighting", quantity=Decimal("38")))
    db.flush()

    by_system = approved_totals(db, project.id).by_system

    assert by_system == {"Power": Decimal("14"), "Lighting": Decimal("38")}
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_totals.py -v`
Expected: FAIL — `ModuleNotFoundError: app.takeoff.totals`

- [ ] **Step 3: Write `api/app/takeoff/totals.py`**

```python
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import Item, ReviewStatus, Sheet


@dataclass
class TotalsResult:
    by_system: dict[str, Decimal] = field(default_factory=dict)
    approved_count: int = 0
    remaining_count: int = 0
    attention_count: int = 0
    missing_count: int = 0
    approved_units: Decimal = Decimal("0")


def _countable(project_id: uuid.UUID):
    """Every consumer of totals starts here.

    Superseded sheets and rejected items are excluded inside this clause
    rather than by callers remembering to filter.
    """
    return (
        select(Item)
        .join(Sheet, Sheet.id == Item.sheet_id)
        .where(Item.project_id == project_id, Sheet.superseded_at.is_(None), Item.rejected_at.is_(None))
    )


def approved_totals(db: DbSession, project_id: uuid.UUID) -> TotalsResult:
    rows = db.execute(
        _countable(project_id)
        .with_only_columns(Item.system, Item.status, func.sum(Item.quantity), func.count())
        .group_by(Item.system, Item.status)
    ).all()

    result = TotalsResult()
    for system, status, quantity, count in rows:
        if status is ReviewStatus.APPROVED:
            result.by_system[system] = result.by_system.get(system, Decimal("0")) + quantity
            result.approved_units += quantity
            result.approved_count += count
        else:
            result.remaining_count += count
            if status is ReviewStatus.ATTENTION:
                result.attention_count += count
            elif status is ReviewStatus.MISSING:
                result.missing_count += count
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_totals.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/totals.py api/tests/test_totals.py
git commit -m "Add the single totals query excluding superseded sheets and rejected items"
```

---

## Task 7: Review mutations and the blocking rule

**Files:**
- Modify: `api/app/takeoff/service.py`
- Test: `api/tests/test_review_state_machine.py`

**Interfaces:**
- Consumes: `service.commit`, `app.errors.DomainError`
- Produces: `service.approve_item(db, actor, item) -> Action`; `service.reject_item(db, actor, item) -> Action`; `service.unreject_item(db, actor, item) -> Action`; `service.edit_item(db, actor, item, changes: dict) -> Action`; `service.delete_item(db, actor, item) -> Action`. `changes` accepts keys `system`, `category`, `quantity`, `notes`, `symbol` only.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_review_state_machine.py
import pytest

from app.errors import DomainError
from app.takeoff import service
from app.takeoff.models import ReviewStatus


def test_approving_records_who_approved_it(db, dana, item):
    service.approve_item(db, dana, item)
    db.flush()

    assert item.status is ReviewStatus.APPROVED
    assert item.approved_by_user_id == dana.id
    assert item.approved_at is not None


def test_a_missing_information_item_cannot_be_approved(db, dana, item):
    item.status = ReviewStatus.MISSING
    db.flush()

    with pytest.raises(DomainError) as caught:
        service.approve_item(db, dana, item)

    assert caught.value.code == "missing_information_blocks_approval"
    assert item.status is ReviewStatus.MISSING


def test_a_needs_attention_item_can_be_approved(db, dana, item):
    item.status = ReviewStatus.ATTENTION
    db.flush()

    service.approve_item(db, dana, item)

    assert item.status is ReviewStatus.APPROVED


def test_rejecting_leaves_the_review_status_intact(db, dana, item):
    item.status = ReviewStatus.ATTENTION
    db.flush()

    service.reject_item(db, dana, item)
    db.flush()

    assert item.rejected_at is not None
    assert item.status is ReviewStatus.ATTENTION, "rejection must not destroy the review state"


def test_unrejecting_restores_the_item_without_guessing_a_status(db, dana, item):
    item.status = ReviewStatus.ATTENTION
    service.reject_item(db, dana, item)
    db.flush()

    service.unreject_item(db, dana, item)
    db.flush()

    assert item.rejected_at is None
    assert item.status is ReviewStatus.ATTENTION


def test_editing_an_unclassified_item_moves_it_to_ready(db, dana, item):
    item.status = ReviewStatus.ATTENTION
    item.category = "Unclassified"
    db.flush()

    service.edit_item(db, dana, item, {"category": "Devices"})
    db.flush()

    assert item.status is ReviewStatus.READY


def test_editing_rejects_a_field_that_is_not_editable(db, dana, item):
    with pytest.raises(DomainError) as caught:
        service.edit_item(db, dana, item, {"status": "approved"})

    assert caught.value.code == "field_not_editable"
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_review_state_machine.py -v`
Expected: FAIL — `module 'app.takeoff.service' has no attribute 'approve_item'`

- [ ] **Step 3: Add the mutations to `api/app/takeoff/service.py`**

```python
from datetime import datetime
from decimal import Decimal

from app.errors import DomainError
from app.takeoff.models import Item, ReviewStatus

EDITABLE_FIELDS = {"system", "category", "quantity", "notes", "symbol"}


def approve_item(db: DbSession, actor: User, item: Item) -> Action:
    if item.status is ReviewStatus.MISSING:
        raise DomainError(
            "missing_information_blocks_approval",
            "This item is missing evidence it needs, so it cannot be approved yet. "
            "Resolve the warning on the sheet first.",
            status=409,
        )

    before = {"status": item.status.value, "approved_by_user_id": str(item.approved_by_user_id or "") or None}
    item.status = ReviewStatus.APPROVED
    item.approved_by_user_id = actor.id
    item.approved_at = datetime.utcnow()
    after = {"status": item.status.value, "approved_by_user_id": str(actor.id)}

    return commit(db, actor=actor, project_id=item.project_id, kind="approve",
                  label=f"Approved {item.name}", before=before, after=after, item_id=item.id)


def reject_item(db: DbSession, actor: User, item: Item) -> Action:
    before = {"rejected_at": None}
    item.rejected_at = datetime.utcnow()
    item.rejected_by_user_id = actor.id
    after = {"rejected_at": item.rejected_at.isoformat()}

    return commit(db, actor=actor, project_id=item.project_id, kind="reject",
                  label=f"Rejected {item.name}", before=before, after=after, item_id=item.id)


def unreject_item(db: DbSession, actor: User, item: Item) -> Action:
    before = {"rejected_at": item.rejected_at.isoformat() if item.rejected_at else None}
    item.rejected_at = None
    item.rejected_by_user_id = None

    return commit(db, actor=actor, project_id=item.project_id, kind="unreject",
                  label=f"Restored {item.name}", before=before, after={"rejected_at": None}, item_id=item.id)


def edit_item(db: DbSession, actor: User, item: Item, changes: dict) -> Action:
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise DomainError("field_not_editable", f"These fields cannot be edited here: {', '.join(sorted(unknown))}.")

    before = {key: _json_safe(getattr(item, key)) for key in changes}
    for key, value in changes.items():
        setattr(item, key, Decimal(str(value)) if key == "quantity" else value)

    if item.status is ReviewStatus.ATTENTION and before.get("category") == "Unclassified" \
            and changes.get("category") != "Unclassified":
        before["status"] = item.status.value
        item.status = ReviewStatus.READY

    after = {key: _json_safe(getattr(item, key)) for key in before}
    return commit(db, actor=actor, project_id=item.project_id, kind="edit",
                  label=f"Edited {item.name}", before=before, after=after, item_id=item.id)


def delete_item(db: DbSession, actor: User, item: Item) -> Action:
    snapshot = {c.name: _json_safe(getattr(item, c.name)) for c in Item.__table__.columns}
    action = commit(db, actor=actor, project_id=item.project_id, kind="delete",
                    label=f"Deleted {item.name}", before=snapshot, after={}, item_id=item.id)
    db.delete(item)
    return action


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, ReviewStatus):
        return value.value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_review_state_machine.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/service.py api/tests/test_review_state_machine.py
git commit -m "Add review mutations with missing-information approval blocked server-side"
```

---

## Task 8: Bulk approval, restricted to Ready to review

**Files:**
- Modify: `api/app/takeoff/service.py`
- Test: `api/tests/test_bulk_approve.py`

**Interfaces:**
- Consumes: `service.approve_item`, `service.commit`
- Produces: `service.bulk_approve(db, actor, project_id, item_ids: list[UUID]) -> BulkApproveResult` — a dataclass with `approved: list[UUID]`, `skipped: dict[UUID, str]` mapping id to reason code, and `action: Action | None`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_bulk_approve.py
from app.takeoff import service
from app.takeoff.models import Item, ReviewStatus


def _extra(db, project, sheet, status):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="switch", name=f"item {status.value}",
             system="Lighting", category="Devices", quantity=1, unit="EA", status=status)
    db.add(i)
    db.flush()
    return i


def test_only_ready_items_are_approved(db, dana, project, sheet):
    ready = _extra(db, project, sheet, ReviewStatus.READY)
    attention = _extra(db, project, sheet, ReviewStatus.ATTENTION)
    missing = _extra(db, project, sheet, ReviewStatus.MISSING)

    result = service.bulk_approve(db, dana, project.id, [ready.id, attention.id, missing.id])
    db.flush()

    assert result.approved == [ready.id]
    assert result.skipped[attention.id] == "not_ready_to_review"
    assert result.skipped[missing.id] == "not_ready_to_review"
    assert attention.status is ReviewStatus.ATTENTION
    assert missing.status is ReviewStatus.MISSING


def test_bulk_approval_writes_one_action_not_one_per_item(db, dana, project, sheet):
    a = _extra(db, project, sheet, ReviewStatus.READY)
    b = _extra(db, project, sheet, ReviewStatus.READY)

    result = service.bulk_approve(db, dana, project.id, [a.id, b.id])
    db.flush()

    assert result.action is not None
    assert result.action.kind == "bulk_approve"
    assert result.action.label == "Approved 2 items"


def test_bulk_approval_ignores_items_from_another_project(db, dana, project, sheet, org):
    from app.takeoff.models import Project

    other = Project(org_id=org.id, name="Other project")
    db.add(other)
    db.flush()
    mine = _extra(db, project, sheet, ReviewStatus.READY)

    result = service.bulk_approve(db, dana, other.id, [mine.id])

    assert result.approved == []
    assert result.skipped[mine.id] == "not_in_project"
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_bulk_approve.py -v`
Expected: FAIL — `module 'app.takeoff.service' has no attribute 'bulk_approve'`

- [ ] **Step 3: Add `bulk_approve` to `api/app/takeoff/service.py`**

```python
from dataclasses import dataclass, field

from sqlalchemy import select


@dataclass
class BulkApproveResult:
    approved: list[uuid.UUID] = field(default_factory=list)
    skipped: dict[uuid.UUID, str] = field(default_factory=dict)
    action: Action | None = None


def bulk_approve(db: DbSession, actor: User, project_id: uuid.UUID, item_ids: list[uuid.UUID]) -> BulkApproveResult:
    """Approves only Ready to review items and reports every skip with a reason.

    Never approves Needs attention or Missing information, no matter how
    convenient the caller finds it.
    """
    result = BulkApproveResult()
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(item_ids)))}

    for item_id in item_ids:
        item = items.get(item_id)
        if item is None or item.project_id != project_id:
            result.skipped[item_id] = "not_in_project"
        elif item.rejected_at is not None:
            result.skipped[item_id] = "rejected"
        elif item.status is not ReviewStatus.READY:
            result.skipped[item_id] = "not_ready_to_review"
        else:
            item.status = ReviewStatus.APPROVED
            item.approved_by_user_id = actor.id
            item.approved_at = datetime.utcnow()
            result.approved.append(item_id)

    if result.approved:
        count = len(result.approved)
        result.action = commit(
            db, actor=actor, project_id=project_id, kind="bulk_approve",
            label=f"Approved {count} item{'s' if count != 1 else ''}",
            before={"item_ids": [str(i) for i in result.approved], "status": "ready"},
            after={"item_ids": [str(i) for i in result.approved], "status": "approved"},
        )
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_bulk_approve.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/service.py api/tests/test_bulk_approve.py
git commit -m "Add bulk approval restricted to Ready to review items"
```

---

## Task 9: Scale confirmation as one compound action

**Files:**
- Modify: `api/app/takeoff/service.py`
- Test: `api/tests/test_scale.py`

**Interfaces:**
- Consumes: `service.commit`
- Produces: `service.set_scale(db, actor, sheet, value: str) -> Action` — sets the sheet scale and re-derives every *Missing information* item on that sheet to *Ready to review*, clearing its warning, as a single action

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_scale.py
from app.takeoff import service
from app.takeoff.models import Item, ReviewStatus, Warning


def _blocked(db, project, sheet):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="run", name='2" EMT conduit run',
             system="Power", category="Conduit and wire", quantity=184, unit="LF",
             status=ReviewStatus.MISSING, path=[[186, 226], [186, 430]])
    db.add(i)
    db.flush()
    db.add(Warning(item_id=i.id, title="Missing scale reference", found="No scale label was found.",
                   why="This run could not be measured.", fix="Set the drawing scale.", where_="E1.1 title block"))
    db.flush()
    return i


def test_setting_the_scale_releases_every_blocked_item_on_that_sheet(db, dana, project, sheet):
    one, two = _blocked(db, project, sheet), _blocked(db, project, sheet)

    service.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert sheet.scale == '1/8" = 1\'-0"'
    assert one.status is ReviewStatus.READY
    assert two.status is ReviewStatus.READY


def test_the_warnings_on_released_items_are_cleared(db, dana, project, sheet):
    item = _blocked(db, project, sheet)

    service.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert db.query(Warning).filter(Warning.item_id == item.id).count() == 0


def test_it_is_one_action_naming_how_many_items_moved(db, dana, project, sheet):
    _blocked(db, project, sheet)
    _blocked(db, project, sheet)

    action = service.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert action.kind == "scale"
    assert "2 measured items" in action.label
    assert len(action.before["items"]) == 2


def test_items_on_another_sheet_are_untouched(db, dana, project, sheet):
    from app.takeoff.models import Sheet

    other = Sheet(project_id=project.id, number="E1.1", title="Lighting plan", discipline="Electrical",
                  revision="Rev 3", scale="none", scale_options=[], plan="office")
    db.add(other)
    db.flush()
    elsewhere = _blocked(db, project, other)

    service.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert elsewhere.status is ReviewStatus.MISSING
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_scale.py -v`
Expected: FAIL — no attribute `set_scale`

- [ ] **Step 3: Add `set_scale` to `api/app/takeoff/service.py`**

```python
from app.takeoff.models import Sheet, Warning


def set_scale(db: DbSession, actor: User, sheet: Sheet, value: str) -> Action:
    """Compound: the sheet's scale and every item blocked by it move together.

    One action, so an estimator who regrets it gets one undo rather than
    fourteen.
    """
    blocked = list(db.scalars(
        select(Item).where(Item.sheet_id == sheet.id, Item.status == ReviewStatus.MISSING)
    ))

    before = {
        "scale": sheet.scale,
        "items": [{"id": str(i.id), "status": i.status.value} for i in blocked],
    }

    sheet.scale = value
    for item in blocked:
        item.status = ReviewStatus.READY
    db.query(Warning).filter(Warning.item_id.in_([i.id for i in blocked])).delete(synchronize_session=False)

    after = {"scale": value, "items": [{"id": str(i.id), "status": "ready"} for i in blocked]}
    count = len(blocked)

    return commit(
        db, actor=actor, project_id=sheet.project_id, kind="scale",
        label=f"Set scale on {sheet.number} — {count} measured item{'s' if count != 1 else ''} recalculated",
        before=before, after=after, sheet_id=sheet.id,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_scale.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/service.py api/tests/test_scale.py
git commit -m "Add scale confirmation as one compound undoable action"
```

---

## Task 10: Undo and redo derived from the action log

**Files:**
- Create: `api/app/takeoff/undo.py`
- Test: `api/tests/test_undo_redo.py`

**Interfaces:**
- Consumes: `app.takeoff.models.Action`, `service.commit`
- Produces: `undo.undo_head(db, project_id) -> Action | None`; `undo.redo_head(db, project_id) -> Action | None`; `undo.undo(db, actor, project_id) -> Action | None`; `undo.redo(db, actor, project_id) -> Action | None`

**Design note for the implementer:** nothing is deleted. Undoing action `A` appends an action of kind `undo` whose `undoes_action_id` is `A.id`. Redo appends kind `redo` pointing at the undo action. An action counts as live when no *live* action targets it — a short recursive walk, evaluated in Python over the project's actions, which is honest at this scale and documented as a future indexing concern.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_undo_redo.py
from app.takeoff import service, undo
from app.takeoff.models import ReviewStatus


def test_undo_restores_the_previous_status(db, dana, project, item):
    service.approve_item(db, dana, item)
    db.flush()

    undo.undo(db, dana, project.id)
    db.flush()

    assert item.status is ReviewStatus.READY


def test_undo_appends_rather_than_deleting_history(db, dana, project, item):
    from app.takeoff.models import Action

    service.approve_item(db, dana, item)
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()

    assert db.query(Action).count() == 2


def test_redo_reapplies_the_action(db, dana, project, item):
    service.approve_item(db, dana, item)
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()

    undo.redo(db, dana, project.id)
    db.flush()

    assert item.status is ReviewStatus.APPROVED


def test_undo_merges_only_the_fields_the_action_touched(db, dana, project, item):
    """B undoing A's approval must not clobber an unrelated quantity edit."""
    service.approve_item(db, dana, item)
    db.flush()
    service.edit_item(db, dana, item, {"quantity": 99})
    db.flush()

    # undo the edit, then the approval
    undo.undo(db, dana, project.id)
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()

    assert item.status is ReviewStatus.READY


def test_undoing_a_scale_reverses_both_halves_together(db, dana, project, sheet):
    from app.takeoff.models import Item

    blocked = Item(project_id=project.id, sheet_id=sheet.id, symbol="run", name="run",
                   system="Power", category="Conduit and wire", quantity=184, unit="LF",
                   status=ReviewStatus.MISSING)
    db.add(blocked)
    db.flush()
    service.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    undo.undo(db, dana, project.id)
    db.flush()

    assert sheet.scale == "mixed"
    assert blocked.status is ReviewStatus.MISSING


def test_undo_head_is_none_on_a_project_with_no_actions(db, project):
    assert undo.undo_head(db, project.id) is None
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_undo_redo.py -v`
Expected: FAIL — `ModuleNotFoundError: app.takeoff.undo`

- [ ] **Step 3: Write `api/app/takeoff/undo.py`**

```python
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.models import Action, Item, ReviewStatus, Sheet
from app.takeoff.service import commit

REVERSIBLE = {"approve", "reject", "unreject", "edit", "scale"}


def _actions(db: DbSession, project_id: uuid.UUID) -> list[Action]:
    return list(db.scalars(select(Action).where(Action.project_id == project_id).order_by(Action.created_at)))


def _live(actions: list[Action]) -> dict[uuid.UUID, bool]:
    """An action is live when no live action targets it."""
    targeted: dict[uuid.UUID, list[Action]] = {}
    for a in actions:
        if a.undoes_action_id:
            targeted.setdefault(a.undoes_action_id, []).append(a)

    live: dict[uuid.UUID, bool] = {}

    def resolve(action: Action) -> bool:
        if action.id in live:
            return live[action.id]
        live[action.id] = True  # provisional, breaks cycles
        live[action.id] = not any(resolve(t) for t in targeted.get(action.id, []))
        return live[action.id]

    for a in actions:
        resolve(a)
    return live


def undo_head(db: DbSession, project_id: uuid.UUID) -> Action | None:
    actions = _actions(db, project_id)
    live = _live(actions)
    for action in reversed(actions):
        if action.kind in REVERSIBLE and live[action.id]:
            return action
    return None


def redo_head(db: DbSession, project_id: uuid.UUID) -> Action | None:
    actions = _actions(db, project_id)
    live = _live(actions)
    for action in reversed(actions):
        if action.kind == "undo" and live[action.id]:
            return action
    return None


def undo(db: DbSession, actor: User, project_id: uuid.UUID) -> Action | None:
    target = undo_head(db, project_id)
    if target is None:
        return None
    _apply(db, target, target.before)
    return commit(db, actor=actor, project_id=project_id, kind="undo",
                  label=f"Undid: {target.label}", before=target.after, after=target.before,
                  item_id=target.item_id, sheet_id=target.sheet_id, undoes_action_id=target.id)


def redo(db: DbSession, actor: User, project_id: uuid.UUID) -> Action | None:
    target = redo_head(db, project_id)
    if target is None:
        return None
    original = db.get(Action, target.undoes_action_id)
    _apply(db, original, original.after)
    return commit(db, actor=actor, project_id=project_id, kind="redo",
                  label=f"Redid: {original.label}", before=original.before, after=original.after,
                  item_id=original.item_id, sheet_id=original.sheet_id, undoes_action_id=target.id)


def _apply(db: DbSession, action: Action, state: dict) -> None:
    """Merges only the fields the action touched — never a full-state restore."""
    if action.kind == "scale":
        sheet = db.get(Sheet, action.sheet_id)
        sheet.scale = state["scale"]
        for row in state.get("items", []):
            item = db.get(Item, uuid.UUID(row["id"]))
            if item is not None:
                item.status = ReviewStatus(row["status"])
        return

    item = db.get(Item, action.item_id)
    if item is None:
        return
    for key, value in state.items():
        if key == "status":
            item.status = ReviewStatus(value)
        elif key == "quantity":
            item.quantity = Decimal(str(value))
        elif key == "rejected_at":
            item.rejected_at = None if value is None else item.rejected_at
        elif key in {"system", "category", "notes", "symbol"}:
            setattr(item, key, value)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_undo_redo.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/undo.py api/tests/test_undo_redo.py
git commit -m "Derive undo and redo from the append-only action log"
```

---

## Task 11: Read endpoints, the snapshot, and its version

**Files:**
- Create: `api/app/takeoff/schemas.py`, `api/app/takeoff/snapshot.py`, `api/app/takeoff/router.py`
- Modify: `api/app/main.py`
- Test: `api/tests/test_snapshot.py`

**Interfaces:**
- Consumes: everything above
- Produces: `snapshot.build(db, project_id) -> SnapshotOut`; `snapshot.version(db, project_id) -> str`; endpoints `GET /api/projects`, `GET /api/projects/{id}`, `GET /api/projects/{id}/snapshot`, `GET /api/projects/{id}/totals`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_snapshot.py
def _sign_in(client):
    client.post("/api/auth/login", json={"email": "dana@example.com", "password": "correct-horse"})


def test_snapshot_returns_sheets_items_and_the_undo_head(client, dana, project, sheet, item):
    _sign_in(client)

    body = client.get(f"/api/projects/{project.id}/snapshot").json()

    assert [s["number"] for s in body["sheets"]] == ["E2.1"]
    assert body["items"][0]["name"] == "20A duplex receptacle"
    assert body["undo"]["can_undo"] is False


def test_an_unchanged_project_answers_304(client, dana, project, sheet, item):
    _sign_in(client)
    first = client.get(f"/api/projects/{project.id}/snapshot")
    etag = first.headers["etag"]

    again = client.get(f"/api/projects/{project.id}/snapshot", headers={"If-None-Match": etag})

    assert again.status_code == 304


def test_the_version_changes_after_a_mutation(client, dana, project, sheet, item):
    _sign_in(client)
    etag = client.get(f"/api/projects/{project.id}/snapshot").headers["etag"]

    client.post(f"/api/items/{item.id}/approve")
    again = client.get(f"/api/projects/{project.id}/snapshot", headers={"If-None-Match": etag})

    assert again.status_code == 200


def test_no_response_field_exposes_processing_internals(client, dana, project, sheet, item):
    _sign_in(client)
    body = client.get(f"/api/projects/{project.id}/snapshot").text.lower()

    for forbidden in ("confidence", "model", "score", "pipeline"):
        assert forbidden not in body
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_snapshot.py -v`
Expected: FAIL — 404 on the snapshot route

- [ ] **Step 3: Write `api/app/takeoff/schemas.py`**

Response models are explicit — ORM objects are never returned directly, which is what keeps internals from leaking by accident.

```python
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

MODEL_CONFIG = {"from_attributes": True}


class WarningOut(BaseModel):
    title: str
    found: str
    why: str
    fix: str
    where: str

    model_config = MODEL_CONFIG


class ItemOut(BaseModel):
    id: uuid.UUID
    sheet_id: uuid.UUID
    symbol: str
    name: str
    description: str
    system: str
    category: str
    quantity: Decimal
    unit: str
    status: str
    approved_by: str | None = None
    rejected: bool = False
    x: int | None = None
    y: int | None = None
    path: list | None = None
    notes: str
    evidence: dict | None = None
    warning: WarningOut | None = None

    model_config = MODEL_CONFIG


class SheetOut(BaseModel):
    id: uuid.UUID
    number: str
    title: str
    discipline: str
    revision: str
    scale: str
    scale_options: list[str]
    plan: str
    superseded: bool = False

    model_config = MODEL_CONFIG


class UndoOut(BaseModel):
    can_undo: bool
    can_redo: bool
    undo_label: str | None = None
    undo_by: str | None = None
    redo_label: str | None = None


class TotalsOut(BaseModel):
    by_system: dict[str, Decimal]
    approved_count: int
    remaining_count: int
    attention_count: int
    missing_count: int
    approved_units: Decimal


class PresenceOut(BaseModel):
    user_id: uuid.UUID
    name: str
    color: str
    sheet_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    seen_at: datetime


class SnapshotOut(BaseModel):
    version: str
    sheets: list[SheetOut]
    items: list[ItemOut]
    totals: TotalsOut
    undo: UndoOut
    presence: list[PresenceOut]
```

- [ ] **Step 4: Write `api/app/takeoff/snapshot.py`**

```python
import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff import undo as undo_module
from app.takeoff.models import Action, Item, Sheet, Warning
from app.takeoff.schemas import ItemOut, SheetOut, SnapshotOut, TotalsOut, UndoOut, WarningOut
from app.takeoff.totals import approved_totals


def version(db: DbSession, project_id: uuid.UUID) -> str:
    latest, count = db.execute(
        select(func.max(Action.created_at), func.count()).where(Action.project_id == project_id)
    ).one()
    raw = f"{project_id}:{latest}:{count}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def build(db: DbSession, project_id: uuid.UUID, presence: list) -> SnapshotOut:
    sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project_id).order_by(Sheet.sort_order)))
    items = list(db.scalars(select(Item).where(Item.project_id == project_id)))
    warnings = {w.item_id: w for w in db.scalars(select(Warning).where(Warning.item_id.isnot(None)))}
    names = {u.id: u.name for u in db.scalars(select(User))}

    head = undo_module.undo_head(db, project_id)
    redo_head = undo_module.redo_head(db, project_id)

    return SnapshotOut(
        version=version(db, project_id),
        sheets=[SheetOut(**{**s.__dict__, "superseded": s.superseded_at is not None}) for s in sheets],
        items=[
            ItemOut(
                **{**i.__dict__,
                   "status": i.status.value,
                   "rejected": i.rejected_at is not None,
                   "approved_by": names.get(i.approved_by_user_id),
                   "warning": WarningOut(**{**w.__dict__, "where": w.where_}) if (w := warnings.get(i.id)) else None}
            )
            for i in items
        ],
        totals=TotalsOut(**approved_totals(db, project_id).__dict__),
        undo=UndoOut(
            can_undo=head is not None,
            can_redo=redo_head is not None,
            undo_label=head.label if head else None,
            undo_by=names.get(head.actor_user_id) if head else None,
            redo_label=redo_head.label if redo_head else None,
        ),
        presence=presence,
    )
```

- [ ] **Step 5: Write `api/app/takeoff/router.py` with the read endpoints**

```python
import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.takeoff import snapshot as snapshot_module
from app.takeoff.models import Project
from app.takeoff.schemas import SnapshotOut, TotalsOut
from app.takeoff.totals import approved_totals

router = APIRouter(prefix="/api", tags=["takeoff"])

NOT_FOUND = DomainError("project_not_found", "That project is not available to your account.", status=404)


def load_project(project_id: uuid.UUID, db: DbSession, user: User) -> Project:
    """The single tenancy gate for every project-scoped route."""
    project = db.get(Project, project_id)
    if project is None or project.org_id != user.org_id:
        raise NOT_FOUND
    return project


@router.get("/projects")
def list_projects(user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> list[dict]:
    projects = db.scalars(select(Project).where(Project.org_id == user.org_id).order_by(Project.created_at))
    return [{"id": str(p.id), "name": p.name, "revision_set_label": p.revision_set_label} for p in projects]


@router.get("/projects/{project_id}/snapshot", response_model=SnapshotOut)
def get_snapshot(
    project_id: uuid.UUID, request: Request, response: Response,
    user: User = Depends(current_user), db: DbSession = Depends(get_db),
):
    project = load_project(project_id, db, user)
    etag = snapshot_module.version(db, project.id)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)

    from app.collab.service import active_presence

    response.headers["ETag"] = etag
    return snapshot_module.build(db, project.id, active_presence(db, project.id, exclude=user.id))


@router.get("/projects/{project_id}/totals", response_model=TotalsOut)
def get_totals(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    return TotalsOut(**approved_totals(db, project.id).__dict__)
```

- [ ] **Step 6: Register the router in `api/app/main.py`**

Add `from app.takeoff.router import router as takeoff_router` and `app.include_router(takeoff_router)`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_snapshot.py -v`
Expected: 4 passed (Task 12 supplies `active_presence`; until then, stub it as `def active_presence(db, project_id, exclude): return []` in `app/collab/service.py`)

- [ ] **Step 8: Commit**

```bash
git add api/app/takeoff api/app/collab api/app/main.py api/tests/test_snapshot.py
git commit -m "Add read endpoints and an ETagged snapshot for polling"
```

---

## Task 12: Presence

**Files:**
- Create: `api/app/collab/__init__.py`, `api/app/collab/models.py`, `api/app/collab/service.py`, `api/app/collab/router.py`
- Create: `api/migrations/versions/0005_presence.py`
- Test: `api/tests/test_presence.py`

**Interfaces:**
- Consumes: `app.identity.models.User`
- Produces: `Presence(user_id, project_id, sheet_id, item_id, seen_at)`; `collab.service.heartbeat(db, user, project_id, sheet_id, item_id) -> Presence`; `collab.service.active_presence(db, project_id, exclude) -> list[PresenceOut]`; endpoint `PUT /api/presence`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_presence.py
from datetime import datetime, timedelta

from app.collab.service import active_presence, heartbeat


def test_a_heartbeat_shows_up_for_other_reviewers(db, dana, project, sheet):
    heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()

    seen = active_presence(db, project.id, exclude=None)

    assert seen[0].name == "Dana Whitfield"
    assert seen[0].sheet_id == sheet.id


def test_your_own_presence_is_excluded(db, dana, project, sheet):
    heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()

    assert active_presence(db, project.id, exclude=dana.id) == []


def test_stale_presence_disappears(db, dana, project, sheet):
    presence = heartbeat(db, dana, project.id, sheet.id, None)
    presence.seen_at = datetime.utcnow() - timedelta(seconds=60)
    db.flush()

    assert active_presence(db, project.id, exclude=None) == []
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_presence.py -v`
Expected: FAIL — `cannot import name 'heartbeat'`

- [ ] **Step 3: Write `api/app/collab/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Presence(Base):
    __tablename__ = "presence"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
```

- [ ] **Step 4: Write `api/app/collab/service.py`**

Replace the Task 11 stub entirely.

```python
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.collab.models import Presence
from app.identity.models import User
from app.takeoff.schemas import PresenceOut

ACTIVE_WINDOW = timedelta(seconds=14)


def heartbeat(db: DbSession, user: User, project_id: uuid.UUID,
              sheet_id: uuid.UUID | None, item_id: uuid.UUID | None) -> Presence:
    presence = db.get(Presence, {"user_id": user.id, "project_id": project_id})
    if presence is None:
        presence = Presence(user_id=user.id, project_id=project_id)
        db.add(presence)
    presence.sheet_id = sheet_id
    presence.item_id = item_id
    presence.seen_at = datetime.utcnow()
    return presence


def active_presence(db: DbSession, project_id: uuid.UUID, exclude: uuid.UUID | None) -> list[PresenceOut]:
    cutoff = datetime.utcnow() - ACTIVE_WINDOW
    rows = db.execute(
        select(Presence, User).join(User, User.id == Presence.user_id)
        .where(Presence.project_id == project_id, Presence.seen_at >= cutoff)
    ).all()
    return [
        PresenceOut(user_id=p.user_id, name=u.name, color=u.color,
                    sheet_id=p.sheet_id, item_id=p.item_id, seen_at=p.seen_at)
        for p, u in rows if p.user_id != exclude
    ]
```

- [ ] **Step 5: Write `api/app/collab/router.py`**

```python
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.collab.service import heartbeat
from app.db import get_db
from app.identity.models import User
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["collab"])


class PresenceIn(BaseModel):
    project_id: uuid.UUID
    sheet_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None


@router.put("/presence", status_code=204)
def put_presence(body: PresenceIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> None:
    project = load_project(body.project_id, db, user)
    heartbeat(db, user, project.id, body.sheet_id, body.item_id)
    db.commit()
```

Register it in `main.py`, generate migration `0005_presence.py`, run `alembic upgrade head && alembic check`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_presence.py tests/test_snapshot.py -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add api/app/collab api/app/main.py api/migrations api/tests/test_presence.py
git commit -m "Add presence with a fourteen second active window"
```

---

## Task 13: Mutation endpoints and proven tenancy isolation

**Files:**
- Modify: `api/app/takeoff/router.py`
- Test: `api/tests/test_tenancy.py`, `api/tests/test_mutation_endpoints.py`

**Interfaces:**
- Consumes: every service function, `load_project`
- Produces: `PATCH /api/items/{id}`, `POST /api/items/{id}/approve|reject|unreject`, `DELETE /api/items/{id}`, `POST /api/projects/{id}/items/bulk-approve`, `POST /api/sheets/{id}/scale`, `POST /api/projects/{id}/undo|redo`; helper `load_item(item_id, db, user) -> Item`

- [ ] **Step 1: Write the failing tenancy tests**

```python
# api/tests/test_tenancy.py
import pytest

from app.auth.passwords import hash_password
from app.identity.models import Org, User


@pytest.fixture
def rival(db):
    org = Org(name="Rival Electric")
    db.add(org)
    db.flush()
    user = User(org_id=org.id, email="rival@example.com", password_hash=hash_password("hunter2"),
                name="Rival Estimator", color="#a8412c")
    db.add(user)
    db.flush()
    return user


def _sign_in_as(client, email, password):
    client.post("/api/auth/login", json={"email": email, "password": password})


def test_another_org_cannot_read_your_snapshot(client, dana, rival, project, sheet, item):
    _sign_in_as(client, "rival@example.com", "hunter2")

    assert client.get(f"/api/projects/{project.id}/snapshot").status_code == 404


def test_another_org_cannot_approve_your_item(client, dana, rival, project, sheet, item):
    _sign_in_as(client, "rival@example.com", "hunter2")

    response = client.post(f"/api/items/{item.id}/approve")

    assert response.status_code == 404
    db_status = client.app  # item untouched
    assert item.status.value == "ready"


def test_another_org_cannot_undo_your_action(client, dana, rival, project, sheet, item):
    _sign_in_as(client, "dana@example.com", "correct-horse")
    client.post(f"/api/items/{item.id}/approve")
    client.post("/api/auth/logout")

    _sign_in_as(client, "rival@example.com", "hunter2")
    assert client.post(f"/api/projects/{project.id}/undo").status_code == 404


def test_a_project_from_another_org_is_absent_from_your_list(client, rival, project):
    _sign_in_as(client, "rival@example.com", "hunter2")

    assert client.get("/api/projects").json() == []
```

And the endpoint behaviour tests:

```python
# api/tests/test_mutation_endpoints.py
def _sign_in(client):
    client.post("/api/auth/login", json={"email": "dana@example.com", "password": "correct-horse"})


def test_approving_a_missing_information_item_is_refused_by_the_server(client, dana, project, sheet, item, db):
    from app.takeoff.models import ReviewStatus

    item.status = ReviewStatus.MISSING
    db.flush()
    _sign_in(client)

    response = client.post(f"/api/items/{item.id}/approve")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "missing_information_blocks_approval"


def test_the_refusal_copy_names_a_recovery_action(client, dana, project, sheet, item, db):
    from app.takeoff.models import ReviewStatus

    item.status = ReviewStatus.MISSING
    db.flush()
    _sign_in(client)

    message = client.post(f"/api/items/{item.id}/approve").json()["detail"]["message"]

    assert "Resolve the warning" in message
    assert "something went wrong" not in message.lower()
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker compose run --rm api pytest tests/test_tenancy.py tests/test_mutation_endpoints.py -v`
Expected: FAIL — routes do not exist

- [ ] **Step 3: Add the mutation endpoints to `api/app/takeoff/router.py`**

```python
from pydantic import BaseModel

from app.takeoff import service, undo as undo_module
from app.takeoff.models import Item, Sheet


def load_item(item_id: uuid.UUID, db: DbSession, user: User) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise NOT_FOUND
    load_project(item.project_id, db, user)
    return item


class EditIn(BaseModel):
    system: str | None = None
    category: str | None = None
    quantity: float | None = None
    notes: str | None = None
    symbol: str | None = None


class BulkApproveIn(BaseModel):
    item_ids: list[uuid.UUID]


class ScaleIn(BaseModel):
    value: str


@router.post("/items/{item_id}/approve")
def approve(item_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> dict:
    item = load_item(item_id, db, user)
    action = service.approve_item(db, user, item)
    db.commit()
    return {"label": action.label}


@router.post("/items/{item_id}/reject")
def reject(item_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> dict:
    item = load_item(item_id, db, user)
    action = service.reject_item(db, user, item)
    db.commit()
    return {"label": action.label}


@router.post("/items/{item_id}/unreject")
def unreject(item_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> dict:
    item = load_item(item_id, db, user)
    action = service.unreject_item(db, user, item)
    db.commit()
    return {"label": action.label}


@router.patch("/items/{item_id}")
def edit(item_id: uuid.UUID, body: EditIn, user: User = Depends(current_user),
         db: DbSession = Depends(get_db)) -> dict:
    item = load_item(item_id, db, user)
    action = service.edit_item(db, user, item, body.model_dump(exclude_none=True))
    db.commit()
    return {"label": action.label}


@router.delete("/items/{item_id}")
def delete(item_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> dict:
    item = load_item(item_id, db, user)
    action = service.delete_item(db, user, item)
    db.commit()
    return {"label": action.label}


@router.post("/projects/{project_id}/items/bulk-approve")
def bulk_approve(project_id: uuid.UUID, body: BulkApproveIn, user: User = Depends(current_user),
                 db: DbSession = Depends(get_db)) -> dict:
    project = load_project(project_id, db, user)
    result = service.bulk_approve(db, user, project.id, body.item_ids)
    db.commit()
    return {
        "approved": [str(i) for i in result.approved],
        "skipped": {str(k): v for k, v in result.skipped.items()},
        "label": result.action.label if result.action else None,
    }


@router.post("/sheets/{sheet_id}/scale")
def set_scale(sheet_id: uuid.UUID, body: ScaleIn, user: User = Depends(current_user),
              db: DbSession = Depends(get_db)) -> dict:
    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise NOT_FOUND
    load_project(sheet.project_id, db, user)
    action = service.set_scale(db, user, sheet, body.value)
    db.commit()
    return {"label": action.label}


@router.post("/projects/{project_id}/undo")
def undo(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> dict:
    project = load_project(project_id, db, user)
    action = undo_module.undo(db, user, project.id)
    db.commit()
    return {"label": action.label if action else None}


@router.post("/projects/{project_id}/redo")
def redo(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> dict:
    project = load_project(project_id, db, user)
    action = undo_module.redo(db, user, project.id)
    db.commit()
    return {"label": action.label if action else None}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm api pytest tests/ -v`
Expected: the whole suite passes

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/router.py api/tests
git commit -m "Add mutation endpoints with tenancy proven by test"
```

---

## Task 14: Observability and the seed command

**Files:**
- Create: `api/app/observability.py`, `api/app/seed.py`
- Modify: `api/app/main.py`
- Test: `api/tests/test_observability.py`

**Interfaces:**
- Consumes: `app.identity.models`, `app.takeoff.models`
- Produces: `observability.RequestIdMiddleware`; `seed.run(db, email: str, password: str) -> Project` creating one org, one user, and the twelve-item demo project

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_observability.py
def test_every_response_carries_a_request_id(client):
    response = client.get("/api/health")

    assert response.headers["x-request-id"]


def test_an_unexpected_error_reports_an_id_the_user_can_quote(client, monkeypatch):
    from app import main

    @main.app.get("/api/boom")
    def boom():
        raise RuntimeError("kaboom")

    response = client.get("/api/boom")

    assert response.status_code == 500
    assert response.json()["detail"]["request_id"] == response.headers["x-request-id"]
    assert "kaboom" not in response.text
```

- [ ] **Step 2: Run to confirm it fails**

Run: `docker compose run --rm api pytest tests/test_observability.py -v`
Expected: FAIL — no `x-request-id` header

- [ ] **Step 3: Write `api/app/observability.py`**

```python
import json
import logging
import sys
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": request_id_var.get(),
        })


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_var.set(request_id)
        try:
            response = await call_next(request)
        except Exception:
            logging.exception("unhandled error")
            response = JSONResponse(
                status_code=500,
                content={"detail": {
                    "code": "unexpected_error",
                    "message": "That did not complete. Try again, and quote this reference if it keeps happening.",
                    "request_id": request_id,
                }},
            )
        response.headers["X-Request-Id"] = request_id
        return response
```

Wire it in `main.py` with `configure_logging()` and `app.add_middleware(RequestIdMiddleware)`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose run --rm api pytest tests/test_observability.py -v`
Expected: 2 passed

- [ ] **Step 5: Write `api/app/seed.py`**

Port the twelve items and three sheets from `src/lib/data.js` verbatim — same names, quantities, systems, positions, warnings, and evidence — into one project named "Meridian Distribution Center". Structure it as:

```python
def run(db: DbSession, email: str, password: str) -> Project:
    """Creates the demo org, one user, and the prototype's seed takeoff."""
```

with a `if __name__ == "__main__":` block reading `SEED_EMAIL` and `SEED_PASSWORD` from the environment. Item positions must match `data.js` exactly or markers will not land on the plan geometry drawn by `PlanDrawing.jsx`.

- [ ] **Step 6: Run the seed and confirm it is idempotent**

Run: `docker compose run --rm api python -m app.seed` twice.
Expected: second run exits without creating a duplicate project.

- [ ] **Step 7: Commit**

```bash
git add api/app/observability.py api/app/seed.py api/app/main.py api/tests/test_observability.py
git commit -m "Add request-id logging and a seed command carrying the prototype fixture"
```

---

## Task 15: The client store adapter and its seed implementation

**Files:**
- Create: `src/lib/store/index.js`, `src/lib/store/seed.js`, `src/lib/store/contract.test.js`
- Modify: `package.json`, `vite.config.js`
- Delete: `src/lib/sync.js` (its internals move into `store/seed.js`)

**Interfaces:**
- Consumes: `src/lib/data.js`
- Produces: a store object with `me()`, `getSnapshot()`, `subscribe(fn)`, `setPresence({sheetId, itemId})`, `approveItem(id)`, `rejectItem(id)`, `unrejectItem(id)`, `editItem(id, changes)`, `deleteItem(id)`, `setScale(sheetId, value)`, `undo()`, `redo()`. `getSnapshot()` resolves to `{ version, sheets, items, totals, undo, presence }`.

- [ ] **Step 1: Add Vitest**

```bash
npm install --save-dev vitest@2.1.8 jsdom@25.0.1
```

Add to `package.json` scripts: `"test": "vitest run"`. Add to `vite.config.js`: `test: { environment: "jsdom" }`.

- [ ] **Step 2: Write the failing contract test**

```javascript
// src/lib/store/contract.test.js
import { describe, expect, it, beforeEach } from "vitest";
import { createSeedStore } from "./seed.js";

const METHODS = [
  "me", "getSnapshot", "subscribe", "setPresence",
  "approveItem", "rejectItem", "unrejectItem", "editItem",
  "deleteItem", "setScale", "undo", "redo",
];

describe("seed store", () => {
  let store;
  beforeEach(() => {
    localStorage.clear();
    store = createSeedStore();
  });

  it("implements every method in the store interface", () => {
    for (const method of METHODS) expect(typeof store[method]).toBe("function");
  });

  it("returns a snapshot shaped like the API's", async () => {
    const snapshot = await store.getSnapshot();
    expect(Object.keys(snapshot).sort()).toEqual(
      ["items", "presence", "sheets", "totals", "undo", "version"]
    );
  });

  it("refuses to approve a missing information item", async () => {
    const { items } = await store.getSnapshot();
    const blocked = items.find((i) => i.status === "missing");
    await expect(store.approveItem(blocked.id)).rejects.toMatchObject({
      code: "missing_information_blocks_approval",
    });
  });

  it("does not count rejected items in totals", async () => {
    const before = (await store.getSnapshot()).totals.approvedUnits;
    const { items } = await store.getSnapshot();
    const approved = items.find((i) => i.status === "approved");
    await store.rejectItem(approved.id);
    const after = (await store.getSnapshot()).totals.approvedUnits;
    expect(after).toBeLessThan(before);
  });

  it("setting a scale releases the blocked items on that sheet only", async () => {
    const { items, sheets } = await store.getSnapshot();
    const sheet = sheets.find((s) => s.scale === "none");
    await store.setScale(sheet.id, '1/8" = 1\'-0"');
    const updated = (await store.getSnapshot()).items;
    const onSheet = updated.filter((i) => i.sheetId === sheet.id);
    expect(onSheet.every((i) => i.status !== "missing")).toBe(true);
  });
});
```

- [ ] **Step 3: Run to confirm it fails**

Run: `npm test`
Expected: FAIL — cannot resolve `./seed.js`

- [ ] **Step 4: Write `src/lib/store/seed.js`**

Move the `localStorage`, `BroadcastChannel`, and `identity()` internals from `src/lib/sync.js` into this module, and express the same rules the server enforces — approving a *Missing information* item rejects with `{ code: "missing_information_blocks_approval" }`, rejected items and superseded sheets are excluded from totals, and `setScale` releases only blocked items on that sheet as one undoable entry. Export `createSeedStore()`.

The rules are duplicated here on purpose: seed mode has no server, and the prototype's value is that the rules are visible. The API implementation trusts the server instead.

- [ ] **Step 5: Write `src/lib/store/index.js`**

```javascript
import { createSeedStore } from "./seed.js";
import { createApiStore } from "./api.js";

/** Swap implementations with VITE_DATA_SOURCE. Removing seed mode later
 *  is deleting seed.js and the branch below. */
export function createStore() {
  return import.meta.env.VITE_DATA_SOURCE === "api" ? createApiStore() : createSeedStore();
}
```

Create `src/lib/store/api.js` in this task as a stub exporting `createApiStore` that throws `new Error("API store arrives in the next task")`, so the module resolves.

- [ ] **Step 6: Run the test to verify it passes**

Run: `npm test`
Expected: 5 passed

- [ ] **Step 7: Delete `src/lib/sync.js` and confirm nothing imports it**

Run: `grep -rn "lib/sync" src/ || echo "no references"`
Expected: `no references` (App.jsx is ported in Task 16 — if it still imports `sync.js`, keep the file until then and delete it at the end of Task 16)

- [ ] **Step 8: Commit**

```bash
git add src/lib/store package.json vite.config.js
git commit -m "Add a domain-level store adapter with the seed implementation behind it"
```

---

## Task 16: The API store, the login screen, and the port

**Files:**
- Modify: `src/lib/store/api.js`, `src/App.jsx`, `vite.config.js`, `docker-compose.yml`, `README.md`
- Create: `src/components/Login.jsx`
- Delete: `src/lib/sync.js`
- Test: extend `src/lib/store/contract.test.js`

**Interfaces:**
- Consumes: the API from Tasks 1–14, the store interface from Task 15
- Produces: `createApiStore()` satisfying the same interface; `<Login onSignedIn={fn} />`

- [ ] **Step 1: Extend the contract test to cover both implementations**

```javascript
// append to src/lib/store/contract.test.js
import { createApiStore } from "./api.js";

describe("api store", () => {
  it("implements every method in the store interface", () => {
    const store = createApiStore();
    for (const method of METHODS) expect(typeof store[method]).toBe("function");
  });
});
```

- [ ] **Step 2: Run to confirm it fails**

Run: `npm test`
Expected: FAIL — `createApiStore` throws

- [ ] **Step 3: Write `src/lib/store/api.js`**

Every method is a `fetch` against the endpoints from Task 13 with `credentials: "include"`. `getSnapshot()` sends `If-None-Match` with the last version and returns the cached snapshot unchanged on `304`. `subscribe(fn)` starts a three second poll and returns an unsubscribe function. `setPresence` beats every five seconds. A non-2xx response rejects with the parsed `{ code, message }` so callers see the same error shape the seed store produces.

- [ ] **Step 4: Add the Vite proxy so the session cookie is same-origin**

```javascript
// vite.config.js
server: {
  proxy: {
    "/api": { target: "http://localhost:8000", changeOrigin: false },
  },
},
```

- [ ] **Step 5: Write `src/components/Login.jsx`**

Email and password fields with persistent visible labels, a visible focus ring, and error copy adjacent to the fields. Sentence case, no "please". On success call `onSignedIn(user)`.

- [ ] **Step 6: Port `src/App.jsx`**

Replace `read`/`write`/`subscribe`/`identity` from `sync.js` with the store. `commit()` disappears — mutations call store methods and re-render from the returned snapshot. Toast text comes from the response `label`. The top bar shows `Saving…` while a mutation is in flight and `Couldn't save — retrying` on failure. If `me()` rejects with 401, render `<Login />`.

`BlueprintCanvas.jsx`, `PlanDrawing.jsx`, and `Symbols.jsx` must not be edited. If a prop shape no longer matches, adapt it in `App.jsx`.

- [ ] **Step 7: Add the web service to `docker-compose.yml`**

```yaml
  web:
    image: node:20-alpine
    working_dir: /srv
    command: sh -c "npm install && npm run dev -- --host 0.0.0.0"
    environment:
      VITE_DATA_SOURCE: api
    volumes: ["./:/srv", "/srv/node_modules"]
    ports: ["5174:5173"]
    depends_on: [api]
```

Port 5174 on the host because 5173 is occupied by an unrelated service on this machine.

- [ ] **Step 8: Verify both modes by hand**

Run: `docker compose up`, open `http://localhost:5174`, sign in with the seeded account. Approve an item in two browser windows and confirm the change and the presence avatar appear in both within a poll cycle. Then run `npm run dev` with no `VITE_DATA_SOURCE` and confirm seed mode still works with the API stopped.

- [ ] **Step 9: Run everything**

Run: `docker compose run --rm api pytest tests/ -v && npm test && npm run build`
Expected: all green

- [ ] **Step 10: Update `README.md`**

Add a "Run the full stack" section covering `docker compose up`, the seeded login, and the note that `npm run dev` alone still runs seed mode. Keep the existing quick-look section accurate.

- [ ] **Step 11: Commit**

```bash
git rm src/lib/sync.js
git add src/ vite.config.js docker-compose.yml README.md
git commit -m "Port the review workspace onto the API behind a login screen"
```

---

## Self-review

**Spec coverage.** Every section of the design maps to a task: architecture and Compose (1), identity (2), auth and the replaceable boundary (3), the four-value enum and NOT NULL warnings (4), the append-only log and its trigger (5), the single totals query (6), the blocking rule (7), bulk approval (8), compound scale (9), undo semantics (10), the ETagged snapshot (11), presence (12), tenancy proven by test (13), observability and seed (14), the removable adapter (15), the port (16). The seven required test areas are covered by tasks 3, 5, 6, 7, 8, 10, and 13.

**Known gaps, deliberately left.** Tasks 14 step 5, 15 step 4, 16 steps 3, 5, and 6 describe behaviour and constraints rather than showing complete code — they are ports of code that already exists in this repo (`data.js`, `sync.js`, `App.jsx`), and transcribing hundreds of lines into a plan would be less accurate than pointing at the source of truth. Every one names its file, its interface, and its acceptance test.

**Type consistency.** `commit()` keeps one signature across tasks 5, 7, 8, 9, and 10. `ReviewStatus` members are `READY`/`ATTENTION`/`MISSING`/`APPROVED` throughout. `load_project` and `load_item` are defined once in task 11 and 13 and reused. The store interface method list in task 15 matches the calls in task 16.

**Watch item for the implementer.** Task 11's router imports `active_presence` from `app.collab.service`, which task 12 writes. The stub is called out in task 11 step 7 — do not skip it or the snapshot tests fail for a confusing reason.

