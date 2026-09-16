# B1 — Documents Stored Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every uploaded file lands in MinIO and a `documents` row through the authenticated API before anything reads it, and a page reload no longer loses an estimator's upload.

**Architecture:** A `BlobStore` protocol with an S3 implementation (MinIO) and an in-memory fake; a `documents` table; a `documents` service + router that streams, hashes and records but never opens a PDF; the client's screen C becomes a view onto the API; the processing and notes screens fetch bytes back from the API for the interim engine call. The browser-held `uploadedFiles.js` is deleted.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic; `boto3` against MinIO; React 18 + Vitest; Docker Compose.

**Spec:** `docs/specs/documents-stored.md`. Read §1 and §4 before Task 1.

## Global Constraints

- **The API never opens a PDF.** No `pymupdf`, no `app.engine` import anywhere under `api/app/` except `api/app/engine/`. `tests/test_api_import_boundary.py` enforces it and must stay green; `boto3` is allowed.
- **Storage keys:** `orgs/{org_id}/projects/{project_id}/documents/{document_id}.pdf`. No code path builds a key from anything but the caller's org and the project it owns.
- **Duplicate = same `sha256` in the same project → `409`** naming the existing file. **Never** compared across projects or orgs. `UniqueConstraint(project_id, sha256)` on the table.
- **Unsupported = not a PDF by both extension and declared content type → `415`**, decided without parsing.
- **Org isolation: `404`, never `403`.** Every document route goes through `router.load_project`.
- **`doc_type` closed set:** `Drawings`, `Specifications`, `Addendum`, `Scope`, `Other`. **`status` closed set:** `uploaded` (B1), `processing`, `processed`, `failed` (B2 writes them; the column accepts them now).
- **Audit:** upload, type change and delete recorded through `actions.commit()` with `kind` in `document_add` / `document_type` / `document_delete`, estimator-worded labels, `before`/`after` carrying row fields, **never bytes**. Not undoable. (Spec §5 names upload and delete; type change is audited too under `ROADMAP.md` invariant 8 — amend §5 in Task 4.)
- **Content responses:** `Cache-Control: private, no-store` (the global middleware already sets it; assert it).
- **Copy:** sentence case; no "please", "successfully", exclamation marks; no "bucket", "S3", "hash", "object storage", "MinIO" in anything an estimator sees. Errors name the file and the recovery.
- **Settings** come from `app.config.settings`; dev values in `docker-compose.yml`, placeholders in `api/.env.example`; nothing secret committed.
- Backend tests run from `api/` with `DATABASE_URL` and `TEST_DATABASE_URL` set; the engine venv is `/Users/nikhit/Documents/takeoff-review/.enginevenv/bin/python`. Frontend: `npm test -- --run`, `npm run build`.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File structure

| File | Responsibility |
|---|---|
| `api/app/documents/__init__.py` (new) | package |
| `api/app/documents/blobstore.py` (new) | `BlobStore` protocol, `S3BlobStore`, `MemoryBlobStore`, `BlobNotFound`, `get_blob_store()` dependency |
| `api/app/documents/service.py` (new) | `store_upload`, `list_documents`, `set_doc_type`, `delete_document`, `open_content`, `load_document`; the rules; audit |
| `api/app/documents/router.py` (new) | the five routes; thin |
| `api/app/documents/schemas.py` (new) | `DocumentOut`, `DocumentTypeIn`, `DOC_TYPES`, `DOC_STATUSES` |
| `api/app/takeoff/models.py` | `Document` model (lives with the other project-scoped tables) |
| `api/migrations/versions/0019_documents.py` (new) | the table |
| `api/app/config.py` | five `blob_*` settings |
| `api/app/main.py` | include the router |
| `api/requirements.txt`, `docker-compose.yml`, `api/.env.example`, `.github/workflows/ci.yml` | `boto3`; `minio` + `minio-init` services; env; CI service container |
| `src/lib/store/api.js`, `api-mapping.js` | `listDocuments`, `uploadDocument`, `setDocumentType`, `deleteDocument`, `fetchDocumentFile`; `mapDocument` |
| `src/components/documents/UploadDocuments.jsx` | screen C onto the API |
| `src/components/documents/ConfirmDrawings.jsx`, `ProcessingStatus.jsx`, `src/components/notes/NotesWorkspace.jsx` | read the persisted list; fetch bytes for the interim engine call |
| `src/routes.jsx` | pass `store` to `UploadDocuments` and `ConfirmDrawings` |
| `src/lib/uploadedFiles.js` | **deleted** |
| `README.md`, `docs/README.md`, `docs/specs/documents-stored.md` | run instructions; index; §5 amendment |

---

### Task 1: `BlobStore` — protocol, S3 and memory implementations, MinIO in compose

**Files:**
- Create: `api/app/documents/__init__.py`, `api/app/documents/blobstore.py`
- Modify: `api/app/config.py`, `api/requirements.txt`, `docker-compose.yml`, `.github/workflows/ci.yml:9-26`
- Create: `api/.env.example`
- Test: `api/tests/test_blobstore.py`

**Interfaces:**
- Produces: `BlobStore` (Protocol: `put(key, stream, content_type, size)`, `open(key) -> BinaryIO`, `delete(key)`, `exists(key) -> bool`); `MemoryBlobStore()`; `S3BlobStore(endpoint, access_key, secret_key, bucket, region)`; `BlobNotFound(Exception)`; `get_blob_store() -> BlobStore` (FastAPI dependency, module-level singleton, overridable); settings `blob_endpoint`, `blob_access_key`, `blob_secret_key`, `blob_bucket`, `blob_region`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_blobstore.py
"""The storage boundary. MemoryBlobStore is what every service test uses;
S3BlobStore is exercised against MinIO when it is reachable (compose
locally, a service container in CI) and skipped with a reason otherwise."""

import io
import os
import uuid

import pytest

from app.documents import blobstore


def test_memory_store_round_trips_and_forgets():
    store = blobstore.MemoryBlobStore()
    key = "orgs/o/projects/p/documents/d.pdf"
    assert not store.exists(key)
    store.put(key, io.BytesIO(b"%PDF-1.4 hello"), "application/pdf", 14)
    assert store.exists(key)
    assert store.open(key).read() == b"%PDF-1.4 hello"
    store.delete(key)
    assert not store.exists(key)
    with pytest.raises(blobstore.BlobNotFound):
        store.open(key)


def test_memory_store_delete_is_idempotent():
    store = blobstore.MemoryBlobStore()
    store.delete("never-there")  # no raise


def _minio_reachable() -> bool:
    import socket
    from urllib.parse import urlparse
    from app.config import settings
    u = urlparse(settings.blob_endpoint)
    try:
        with socket.create_connection((u.hostname, u.port or 9000), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _minio_reachable(), reason="MinIO not reachable at settings.blob_endpoint")
def test_s3_store_round_trips_against_minio():
    from app.config import settings
    store = blobstore.S3BlobStore(
        settings.blob_endpoint, settings.blob_access_key, settings.blob_secret_key,
        settings.blob_bucket, settings.blob_region,
    )
    key = f"tests/{uuid.uuid4().hex}.pdf"
    assert not store.exists(key)
    store.put(key, io.BytesIO(b"%PDF-1.4 minio"), "application/pdf", 14)
    assert store.exists(key)
    assert store.open(key).read() == b"%PDF-1.4 minio"
    store.delete(key)
    assert not store.exists(key)
    with pytest.raises(blobstore.BlobNotFound):
        store.open(key)


def test_get_blob_store_is_a_singleton():
    a = blobstore.get_blob_store()
    b = blobstore.get_blob_store()
    assert a is b
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && DATABASE_URL=… TEST_DATABASE_URL=… …pytest tests/test_blobstore.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.documents'`

- [ ] **Step 3: Settings, requirements, compose, env example, CI**

`api/app/config.py` — add after `cookie_secure`:

```python
    # Object storage for uploaded documents (MinIO locally, S3 in
    # deployment). Keys are tenant-scoped by construction -- see
    # app/documents/service.py. Dev values live in docker-compose.yml;
    # nothing here has a default that would silently point at a real bucket.
    blob_endpoint: str = "http://localhost:9000"
    blob_access_key: str = ""
    blob_secret_key: str = ""
    blob_bucket: str = "bidmate-documents"
    blob_region: str = "us-east-1"
```

`api/requirements.txt` — add after `python-multipart==0.0.20`: `boto3==1.35.90`.

`api/.env.example` (new):

```
DATABASE_URL=postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff
TEST_DATABASE_URL=postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test
# Object storage. These are the MinIO dev credentials from docker-compose.yml.
BLOB_ENDPOINT=http://localhost:9000
BLOB_ACCESS_KEY=bidmate
BLOB_SECRET_KEY=bidmate-dev-secret
BLOB_BUCKET=bidmate-documents
BLOB_REGION=us-east-1
```

`docker-compose.yml` — add two services after `postgres`, and the env to `api`:

```yaml
  # Object storage for uploaded documents. The console on 9001 is for
  # looking at what was stored; the API talks to 9000. Credentials here
  # are dev-only and match api/.env.example.
  minio:
    image: minio/minio:RELEASE.2025-04-22T22-12-26Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: bidmate
      MINIO_ROOT_PASSWORD: bidmate-dev-secret
    ports: ["9000:9000", "9001:9001"]
    volumes: ["miniodata:/data"]
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 3s
      timeout: 3s
      retries: 20

  # One-shot: create the bucket, then exit. `mc mb --ignore-existing` makes
  # a second `compose up` a no-op.
  minio-init:
    image: minio/mc:RELEASE.2025-04-16T18-13-26Z
    depends_on:
      minio: {condition: service_healthy}
    entrypoint: >
      /bin/sh -c "mc alias set local http://minio:9000 bidmate bidmate-dev-secret
      && mc mb --ignore-existing local/bidmate-documents"
```

In `api.environment` add:

```yaml
      BLOB_ENDPOINT: http://minio:9000
      BLOB_ACCESS_KEY: bidmate
      BLOB_SECRET_KEY: bidmate-dev-secret
      BLOB_BUCKET: bidmate-documents
      BLOB_REGION: us-east-1
```

and to `api.depends_on` add `minio-init: {condition: service_completed_successfully}`. Add `miniodata:` under `volumes:`.

`.github/workflows/ci.yml` — in the `backend` job's `services:` add:

```yaml
      minio:
        image: minio/minio:RELEASE.2025-04-22T22-12-26Z
        env:
          MINIO_ROOT_USER: bidmate
          MINIO_ROOT_PASSWORD: bidmate-dev-secret
        ports: ["9000:9000"]
        # GitHub service containers cannot take a `command`; this image's
        # default entrypoint needs one, so the bucket is created in a step.
        options: >-
          --health-cmd "curl -f http://localhost:9000/minio/health/live"
          --health-interval 3s --health-timeout 3s --health-retries 20
```

Then a step before "Run tests":

```yaml
      - name: Create the documents bucket
        run: |
          curl -sSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc && chmod +x /usr/local/bin/mc
          mc alias set local http://localhost:9000 bidmate bidmate-dev-secret
          mc mb --ignore-existing local/bidmate-documents
```

and to the job `env:` add `BLOB_ENDPOINT: http://localhost:9000`, `BLOB_ACCESS_KEY: bidmate`, `BLOB_SECRET_KEY: bidmate-dev-secret`, `BLOB_BUCKET: bidmate-documents`, `BLOB_REGION: us-east-1`.

**Verify the MinIO image runs with `command: server /data --console-address ":9001"` under GitHub's service-container model** — if the container exits because the image's entrypoint expects a subcommand, switch the CI service to `image: bitnami/minio:2025` (which defaults to `server`) and say so in the commit. Do not leave CI red.

- [ ] **Step 4: Write the module**

```python
# api/app/documents/blobstore.py
"""Where uploaded documents live.

A `BlobStore` is the only thing the rest of the API knows about storage.
`S3BlobStore` talks to MinIO locally and to S3 in deployment through the
same API; `MemoryBlobStore` is what tests use. The interface exists so a
presigned direct-to-storage upload can be a second `put` path later
rather than a redesign (docs/specs/documents-stored.md §5).

Keys are built by app/documents/service.py from the caller's org and
the project it owns -- never from anything the client sends -- which is
what makes storage tenant-scoped by construction rather than by policy.
"""

from __future__ import annotations

import io
from typing import BinaryIO, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings


class BlobNotFound(Exception):
    """`open()` on a key that holds nothing."""


class BlobStore(Protocol):
    def put(self, key: str, stream: BinaryIO, content_type: str, size: int) -> None: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class MemoryBlobStore:
    """In-process store for tests. Holds bytes; forgets on delete."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, stream: BinaryIO, content_type: str, size: int) -> None:
        self.blobs[key] = (stream.read(), content_type)

    def open(self, key: str) -> BinaryIO:
        try:
            return io.BytesIO(self.blobs[key][0])
        except KeyError:
            raise BlobNotFound(key) from None

    def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.blobs


class S3BlobStore:
    """MinIO or S3. Path-style addressing because MinIO's default is
    path-style and a virtual-host bucket name would not resolve against
    a compose alias."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, region: str) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    def put(self, key: str, stream: BinaryIO, content_type: str, size: int) -> None:
        self.client.upload_fileobj(stream, self.bucket, key, ExtraArgs={"ContentType": content_type})

    def open(self, key: str) -> BinaryIO:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise BlobNotFound(key) from None
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise


_store: BlobStore | None = None


def get_blob_store() -> BlobStore:
    """FastAPI dependency. One client per process; tests override it with
    `app.dependency_overrides[get_blob_store] = lambda: MemoryBlobStore()`."""
    global _store
    if _store is None:
        _store = S3BlobStore(
            settings.blob_endpoint, settings.blob_access_key, settings.blob_secret_key,
            settings.blob_bucket, settings.blob_region,
        )
    return _store
```

`api/app/documents/__init__.py`: empty.

- [ ] **Step 5: Install, bring MinIO up, run**

```
cd api && /Users/nikhit/Documents/takeoff-review/.enginevenv/bin/pip install boto3==1.35.90
cd .. && docker compose up -d minio minio-init && docker compose ps minio
cd api && BLOB_ACCESS_KEY=bidmate BLOB_SECRET_KEY=bidmate-dev-secret DATABASE_URL=… TEST_DATABASE_URL=… …pytest tests/test_blobstore.py -v -rs
```

Expected: 4 passed, 0 skipped (MinIO reachable on 9000). Then `tests/test_api_import_boundary.py` — still passes (`boto3` is not on its deny list).

- [ ] **Step 6: Commit**

```bash
git add api/app/documents api/app/config.py api/requirements.txt api/.env.example docker-compose.yml .github/workflows/ci.yml api/tests/test_blobstore.py
git commit -m "Add the storage boundary: BlobStore over MinIO, with a memory fake for tests

One interface the API sees; S3BlobStore for MinIO locally and S3 in
deployment; MemoryBlobStore for tests. MinIO joins compose with a
one-shot bucket init, and CI gets a service container so the S3 tests
run there rather than skipping.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The `documents` table

**Files:**
- Modify: `api/app/takeoff/models.py` (after `Sheet`, before `Item`)
- Create: `api/migrations/versions/0019_documents.py`, `api/app/documents/schemas.py`
- Test: `api/tests/test_documents_model.py`

**Interfaces:**
- Produces: `Document` model; `DOC_TYPES = ("Drawings", "Specifications", "Addendum", "Scope", "Other")`; `DOC_STATUSES = ("uploaded", "processing", "processed", "failed")`; `DocumentOut`; `DocumentTypeIn`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_documents_model.py
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.takeoff.models import Document


def test_document_row_round_trips(db, project, dana):
    d = Document(
        project_id=project.id, filename="E-set.pdf", doc_type="Drawings",
        content_type="application/pdf", size_bytes=1234, sha256="a" * 64,
        storage_key=f"orgs/{project.org_id}/projects/{project.id}/documents/x.pdf",
        uploaded_by=dana.id,
    )
    db.add(d)
    db.flush()
    got = db.get(Document, d.id)
    assert got.status == "uploaded" and got.error == "" and got.created_at is not None


def test_same_hash_twice_in_one_project_is_refused_by_the_database(db, project, dana):
    for _ in range(2):
        db.add(Document(
            project_id=project.id, filename="E-set.pdf", doc_type="Drawings",
            content_type="application/pdf", size_bytes=1, sha256="b" * 64,
            storage_key=f"k/{uuid.uuid4()}", uploaded_by=dana.id,
        ))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
```

- [ ] **Step 2: Run to verify it fails**

Run: `…pytest tests/test_documents_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'Document'`

- [ ] **Step 3: Model, migration, schemas**

`api/app/takeoff/models.py` — add after the `Sheet` class:

```python
class Document(Base):
    """An uploaded file, as stored. The API streams and hashes it; it
    never opens it -- page count, dimensions and whether it is even a
    readable PDF are the worker's to find out (B2). `status` and `error`
    are where the worker reports back. docs/specs/documents-stored.md."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("project_id", "sha256", name="uq_document_project_sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(20))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="uploaded", server_default="uploaded")
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Add `BigInteger` to the `sqlalchemy` import at the top of `models.py` if absent.

```python
# api/migrations/versions/0019_documents.py
"""documents

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-15 00:00:00.000000

The table behind B1 (docs/specs/documents-stored.md): one row per
uploaded file, with the hash the within-project duplicate rule keys on
and the storage key the blob lives under. `status`/`error` are written
by the worker from B2 on; B1 only ever writes 'uploaded'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0019'
down_revision: Union[str, None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'documents',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(length=300), nullable=False),
        sa.Column('doc_type', sa.String(length=20), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('storage_key', sa.String(length=300), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='uploaded'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('uploaded_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'sha256', name='uq_document_project_sha256'),
    )
    op.create_index('ix_documents_project_id', 'documents', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_documents_project_id', table_name='documents')
    op.drop_table('documents')
```

```python
# api/app/documents/schemas.py
"""Wire shapes for documents. snake_case, like the takeoff schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

DOC_TYPES = ("Drawings", "Specifications", "Addendum", "Scope", "Other")
DOC_STATUSES = ("uploaded", "processing", "processed", "failed")


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    doc_type: str
    size_bytes: int
    sha256: str
    status: str
    error: str
    created_at: datetime


class DocumentTypeIn(BaseModel):
    doc_type: str

    @field_validator("doc_type")
    @classmethod
    def _closed_set(cls, v: str) -> str:
        if v not in DOC_TYPES:
            raise ValueError(f"doc_type must be one of {', '.join(DOC_TYPES)}")
        return v
```

- [ ] **Step 4: Migrate up/down/up; run**

```
cd api && DATABASE_URL=… …alembic upgrade head && …alembic downgrade -1 && …alembic upgrade head && …alembic current
…pytest tests/test_documents_model.py -v
```
Expected: `0019 (head)`, clean reversal, 2 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/models.py api/migrations/versions/0019_documents.py api/app/documents/schemas.py api/tests/test_documents_model.py
git commit -m "Add the documents table

One row per uploaded file; the within-project duplicate rule is a
unique constraint on (project_id, sha256), not only a check in the
endpoint. status and error exist for the worker to write from B2 on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Upload and list — the service, the rules, the audit

**Files:**
- Create: `api/app/documents/service.py`, `api/app/documents/router.py`
- Modify: `api/app/main.py:94-98` (include router)
- Test: `api/tests/test_documents_upload.py`

**Interfaces:**
- Consumes: `BlobStore`, `get_blob_store`, `Document`, `DOC_TYPES`, `router.load_project`, `router.not_found`, `actions.commit`.
- Produces: `service.store_upload(db, *, actor, project, upload, doc_type, store) -> Document`; `service.list_documents(db, project) -> list[Document]`; `service.load_document(document_id, db, user) -> Document`; `service.storage_key(project, document_id) -> str`; routes `POST /api/projects/{id}/documents`, `GET /api/projects/{id}/documents`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_documents_upload.py
"""Upload rules, verified through the HTTP layer with a memory store:
stored bytes and row; duplicate within a project refused by name; the
same bytes in another project stored again; unsupported refused without
parsing; other org's project 404; the audit row carries no bytes."""

import hashlib
import io

import pytest
from sqlalchemy import select

from app.documents import blobstore
from app.main import app
from app.takeoff.models import Action, Document, Project

PDF = b"%PDF-1.4\n%fake but enough for a hash\n"


@pytest.fixture
def store():
    s = blobstore.MemoryBlobStore()
    app.dependency_overrides[blobstore.get_blob_store] = lambda: s
    yield s
    app.dependency_overrides.pop(blobstore.get_blob_store, None)


def _upload(client, project_id, name="E-set.pdf", data=PDF, doc_type="Drawings", ctype="application/pdf"):
    return client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": (name, io.BytesIO(data), ctype)},
        data={"doc_type": doc_type},
    )


def test_upload_stores_bytes_and_a_row(client, signed_in_user, project, db, store):
    r = _upload(client, project.id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "E-set.pdf" and body["doc_type"] == "Drawings" and body["status"] == "uploaded"
    assert body["sha256"] == hashlib.sha256(PDF).hexdigest() and body["size_bytes"] == len(PDF)
    row = db.get(Document, body["id"])
    assert row.storage_key == f"orgs/{project.org_id}/projects/{project.id}/documents/{row.id}.pdf"
    assert store.open(row.storage_key).read() == PDF


def test_second_identical_upload_in_the_same_project_is_refused_by_name(client, signed_in_user, project, db, store):
    assert _upload(client, project.id, name="first.pdf").status_code == 201
    r = _upload(client, project.id, name="second.pdf")
    assert r.status_code == 409
    assert "first.pdf" in r.json()["detail"]["message"]
    assert db.scalar(select(Document).where(Document.project_id == project.id, Document.filename == "second.pdf")) is None
    assert len(store.blobs) == 1


def test_same_bytes_in_another_project_are_stored_again(client, signed_in_user, project, org, db, store):
    other = Project(org_id=org.id, name="Another job", revision_set_label="")
    db.add(other)
    db.flush()
    assert _upload(client, project.id).status_code == 201
    assert _upload(client, other.id).status_code == 201
    assert len(store.blobs) == 2


def test_a_non_pdf_is_refused_without_being_stored(client, signed_in_user, project, db, store):
    r = _upload(client, project.id, name="notes.docx", data=b"PK\x03\x04", ctype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert r.status_code == 415
    assert "notes.docx" in r.json()["detail"]["message"] and "PDF" in r.json()["detail"]["message"]
    assert store.blobs == {}


def test_a_pdf_extension_with_a_non_pdf_content_type_is_refused(client, signed_in_user, project, store):
    r = _upload(client, project.id, name="sneaky.pdf", ctype="text/plain")
    assert r.status_code == 415


def test_an_unknown_doc_type_is_refused(client, signed_in_user, project, store):
    r = _upload(client, project.id, doc_type="Photos")
    assert r.status_code == 422


def test_other_orgs_project_is_not_found_not_forbidden(client, other_org_project, store):
    assert _upload(client, other_org_project.id).status_code == 404
    assert client.get(f"/api/projects/{other_org_project.id}/documents").status_code == 404


def test_list_returns_the_projects_documents_oldest_first(client, signed_in_user, project, store):
    _upload(client, project.id, name="a.pdf", data=PDF + b"a")
    _upload(client, project.id, name="b.pdf", data=PDF + b"b")
    r = client.get(f"/api/projects/{project.id}/documents")
    assert r.status_code == 200
    assert [d["filename"] for d in r.json()] == ["a.pdf", "b.pdf"]


def test_upload_is_audited_without_bytes(client, signed_in_user, project, db, store):
    _upload(client, project.id)
    action = db.scalar(select(Action).where(Action.project_id == project.id, Action.kind == "document_add"))
    assert action is not None
    assert action.label == "Uploaded E-set.pdf as Drawings"
    assert action.after["filename"] == "E-set.pdf" and "content" not in action.after
    assert PDF.decode("latin-1") not in str(action.after)
```

- [ ] **Step 2: Run to verify they fail**

Run: `…pytest tests/test_documents_upload.py -v`
Expected: FAIL — `404` on every POST (no route) / `ModuleNotFoundError` on the import.

- [ ] **Step 3: Service and router**

```python
# api/app/documents/service.py
"""Documents: stored, listed, retyped, removed, streamed. The API never
opens one -- it streams bytes, hashes them, records them. Opening an
untrusted PDF is the worker's job (B2); see docs/specs/documents-stored.md §1.

Every mutation goes through actions.commit() so it is attributed and in
the audit log. None is undoable: a deleted blob cannot be replayed from
a row, which is why the client asks before deleting."""

from __future__ import annotations

import hashlib
import uuid
from typing import BinaryIO

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.documents.blobstore import BlobStore
from app.documents.schemas import DOC_TYPES
from app.errors import DomainError
from app.identity.models import User
from app.takeoff import actions
from app.takeoff.models import Document, Project
from app.takeoff.router import load_project, not_found

_CHUNK = 1024 * 1024


def storage_key(project: Project, document_id: uuid.UUID) -> str:
    """Tenant-scoped by construction: built from the project the caller
    owns, never from anything the client sent."""
    return f"orgs/{project.org_id}/projects/{project.id}/documents/{document_id}.pdf"


def _row_fields(d: Document) -> dict:
    return {
        "id": str(d.id), "filename": d.filename, "doc_type": d.doc_type,
        "size_bytes": d.size_bytes, "sha256": d.sha256, "status": d.status,
    }


def _is_pdf(filename: str, content_type: str) -> bool:
    return filename.lower().endswith(".pdf") and content_type == "application/pdf"


def store_upload(db: DbSession, *, actor: User, project: Project, upload: UploadFile, doc_type: str, store: BlobStore) -> Document:
    filename = upload.filename or "document.pdf"
    content_type = upload.content_type or ""
    if doc_type not in DOC_TYPES:
        raise DomainError("invalid_doc_type", f"Document type must be one of {', '.join(DOC_TYPES)}.", status=422)
    if not _is_pdf(filename, content_type):
        raise DomainError(
            "unsupported_document",
            f"{filename} isn't a PDF. Upload PDF drawings, specifications, addenda, and scope documents.",
            status=415,
        )

    # Hash and size in one pass over the upload's spooled file, then
    # rewind for storage. The duplicate check runs before anything is
    # stored so a refused upload leaves no blob behind.
    digest = hashlib.sha256()
    size = 0
    upload.file.seek(0)
    while chunk := upload.file.read(_CHUNK):
        digest.update(chunk)
        size += len(chunk)
    sha = digest.hexdigest()
    upload.file.seek(0)

    existing = db.scalar(select(Document).where(Document.project_id == project.id, Document.sha256 == sha))
    if existing is not None:
        raise DomainError(
            "duplicate_document",
            f"This appears to be the same file as {existing.filename}, uploaded earlier. Remove one copy or upload a different file.",
            status=409,
        )

    document = Document(
        id=uuid.uuid4(), project_id=project.id, filename=filename, doc_type=doc_type,
        content_type="application/pdf", size_bytes=size, sha256=sha, storage_key="",
        uploaded_by=actor.id,
    )
    document.storage_key = storage_key(project, document.id)
    store.put(document.storage_key, upload.file, "application/pdf", size)
    db.add(document)
    db.flush()
    actions.commit(
        db, actor=actor, project_id=project.id, kind="document_add",
        label=f"Uploaded {filename} as {doc_type}", before={}, after=_row_fields(document),
    )
    return document


def list_documents(db: DbSession, project: Project) -> list[Document]:
    return list(db.scalars(select(Document).where(Document.project_id == project.id).order_by(Document.created_at, Document.id)))


def load_document(document_id: uuid.UUID, db: DbSession, user: User) -> Document:
    """The tenancy gate for document routes: 404 whether the document is
    missing or belongs to another org, via load_project's own rule."""
    document = db.get(Document, document_id)
    if document is None:
        raise not_found()
    load_project(document.project_id, db, user)
    return document
```

```python
# api/app/documents/router.py
"""Thin HTTP layer for documents. router -> service -> models."""

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.documents import service
from app.documents.blobstore import BlobStore, get_blob_store
from app.documents.schemas import DocumentOut
from app.identity.models import User
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["documents"])


@router.post("/projects/{project_id}/documents", response_model=DocumentOut, status_code=201)
def post_document(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
    store: BlobStore = Depends(get_blob_store),
) -> DocumentOut:
    project = load_project(project_id, db, user)
    document = service.store_upload(db, actor=user, project=project, upload=file, doc_type=doc_type, store=store)
    db.commit()
    return DocumentOut.model_validate(document)


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
def get_documents(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> list[DocumentOut]:
    project = load_project(project_id, db, user)
    return [DocumentOut.model_validate(d) for d in service.list_documents(db, project)]
```

`api/app/main.py` — import `from app.documents.router import router as documents_router` beside the other router imports and add `app.include_router(documents_router)` after `pricing_router`. The explicit `db.commit()` in the route matches the existing convention: `get_db` only yields, and `mutations.py`'s routes call the service then `db.commit()` themselves.

- [ ] **Step 4: Run**

Run: `…pytest tests/test_documents_upload.py tests/test_api_import_boundary.py -v`
Expected: 9 passed + boundary green. If `test_upload_is_audited_without_bytes` fails on the label, the `label` is the spec's copy verbatim — fix the code, not the test.

- [ ] **Step 5: Commit**

```bash
git add api/app/documents api/app/main.py api/tests/test_documents_upload.py
git commit -m "Store an upload through the API: hashed in flight, refused as duplicate or unsupported, audited

The API streams the bytes to the blob store and never opens the file.
A duplicate is refused by hash within the project and named; the same
bytes in another project are stored again; a non-PDF is refused before
anything is stored. Every upload is one action in the log, without
bytes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Retype, delete, and stream content

**Files:**
- Modify: `api/app/documents/service.py`, `api/app/documents/router.py`, `docs/specs/documents-stored.md` (§5 audit line)
- Test: `api/tests/test_documents_manage.py`

**Interfaces:**
- Produces: `service.set_doc_type(db, *, actor, document, doc_type) -> Document`; `service.delete_document(db, *, actor, document, store) -> None`; `service.open_content(document, store) -> BinaryIO`; routes `PATCH /api/documents/{id}`, `DELETE /api/documents/{id}`, `GET /api/documents/{id}/content`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_documents_manage.py
import io

import pytest
from sqlalchemy import select

from app.documents import blobstore
from app.main import app
from app.takeoff.models import Action, Document

PDF = b"%PDF-1.4\n%manage\n"


@pytest.fixture
def store():
    s = blobstore.MemoryBlobStore()
    app.dependency_overrides[blobstore.get_blob_store] = lambda: s
    yield s
    app.dependency_overrides.pop(blobstore.get_blob_store, None)


@pytest.fixture
def uploaded(client, signed_in_user, project, store):
    r = client.post(f"/api/projects/{project.id}/documents",
                    files={"file": ("E-set.pdf", io.BytesIO(PDF), "application/pdf")}, data={"doc_type": "Drawings"})
    assert r.status_code == 201, r.text
    return r.json()


def test_patch_changes_the_type_and_is_audited(client, uploaded, db, project):
    r = client.patch(f"/api/documents/{uploaded['id']}", json={"doc_type": "Addendum"})
    assert r.status_code == 200 and r.json()["doc_type"] == "Addendum"
    a = db.scalar(select(Action).where(Action.project_id == project.id, Action.kind == "document_type"))
    assert a.label == "Changed E-set.pdf to Addendum" and a.before["doc_type"] == "Drawings" and a.after["doc_type"] == "Addendum"


def test_patch_refuses_an_unknown_type(client, uploaded):
    assert client.patch(f"/api/documents/{uploaded['id']}", json={"doc_type": "Photos"}).status_code == 422


def test_delete_removes_blob_and_row_and_is_audited_not_undoable(client, uploaded, db, project, store):
    key = db.get(Document, uploaded["id"]).storage_key
    assert store.exists(key)
    r = client.delete(f"/api/documents/{uploaded['id']}")
    assert r.status_code == 204
    assert not store.exists(key)
    assert db.get(Document, uploaded["id"]) is None
    a = db.scalar(select(Action).where(Action.project_id == project.id, Action.kind == "document_delete"))
    assert a.label == "Removed E-set.pdf"
    undo = client.post(f"/api/projects/{project.id}/undo")
    assert undo.status_code == 200 and undo.json()["performed"] is False


def test_content_streams_the_exact_bytes_privately(client, uploaded):
    r = client.get(f"/api/documents/{uploaded['id']}/content")
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"].startswith("application/pdf")
    assert "no-store" in r.headers["cache-control"]


def test_document_routes_are_org_scoped(client, uploaded, db, other_org_project, store):
    """A document under another org's project: 404 on every route."""
    from app.takeoff.models import Document as D
    foreign = D(project_id=other_org_project.id, filename="theirs.pdf", doc_type="Drawings",
                content_type="application/pdf", size_bytes=1, sha256="c" * 64,
                storage_key="orgs/x/projects/y/documents/z.pdf", uploaded_by=db.get(D, uploaded["id"]).uploaded_by)
    db.add(foreign)
    db.flush()
    assert client.get(f"/api/documents/{foreign.id}/content").status_code == 404
    assert client.patch(f"/api/documents/{foreign.id}", json={"doc_type": "Other"}).status_code == 404
    assert client.delete(f"/api/documents/{foreign.id}").status_code == 404
```

The undo endpoint answers `{"performed": false, "label": null, "snapshot": null}` when there is nothing to undo (`test_mutation_endpoints.py::test_undo_with_nothing_to_undo_says_so_explicitly`). A document delete must leave nothing on the undo stack.

- [ ] **Step 2: Run to verify they fail**

Run: `…pytest tests/test_documents_manage.py -v`
Expected: FAIL — `405`/`404` on PATCH, DELETE, GET content.

- [ ] **Step 3: Service and routes**

Append to `service.py`:

```python
def set_doc_type(db: DbSession, *, actor: User, document: Document, doc_type: str) -> Document:
    if doc_type not in DOC_TYPES:
        raise DomainError("invalid_doc_type", f"Document type must be one of {', '.join(DOC_TYPES)}.", status=422)
    before = _row_fields(document)
    document.doc_type = doc_type
    db.flush()
    actions.commit(
        db, actor=actor, project_id=document.project_id, kind="document_type",
        label=f"Changed {document.filename} to {doc_type}", before=before, after=_row_fields(document),
    )
    return document


def delete_document(db: DbSession, *, actor: User, document: Document, store: BlobStore) -> None:
    """Blob first, then row: a row without a blob is a visible lie in the
    list; a blob without a row is unreachable and harmless."""
    before = _row_fields(document)
    project_id, filename, key = document.project_id, document.filename, document.storage_key
    store.delete(key)
    db.delete(document)
    db.flush()
    actions.commit(
        db, actor=actor, project_id=project_id, kind="document_delete",
        label=f"Removed {filename}", before=before, after={},
    )


def open_content(document: Document, store: BlobStore) -> BinaryIO:
    return store.open(document.storage_key)
```

Append to `router.py`:

```python
from fastapi.responses import StreamingResponse
from app.documents.schemas import DocumentTypeIn


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def patch_document(document_id: uuid.UUID, body: DocumentTypeIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> DocumentOut:
    document = service.load_document(document_id, db, user)
    document = service.set_doc_type(db, actor=user, document=document, doc_type=body.doc_type)
    db.commit()
    return DocumentOut.model_validate(document)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db), store: BlobStore = Depends(get_blob_store)) -> None:
    document = service.load_document(document_id, db, user)
    service.delete_document(db, actor=user, document=document, store=store)
    db.commit()


@router.get("/documents/{document_id}/content")
def get_content(document_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db), store: BlobStore = Depends(get_blob_store)) -> StreamingResponse:
    document = service.load_document(document_id, db, user)
    body = service.open_content(document, store)
    return StreamingResponse(
        iter(lambda: body.read(1024 * 1024), b""),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{document.filename}"', "Content-Length": str(document.size_bytes)},
    )
```

Spec amendment — `docs/specs/documents-stored.md` §5 **Audit**: "Upload and delete are recorded" → "Upload, type change and delete are recorded (`document_add` / `document_type` / `document_delete`) — a type change decides which files the engine reads as drawings, so it is a mutation worth attributing (`ROADMAP.md` invariant 8)".

- [ ] **Step 4: Run**

Run: `…pytest tests/test_documents_manage.py tests/test_documents_upload.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/documents docs/specs/documents-stored.md api/tests/test_documents_manage.py
git commit -m "Retype, remove and stream a document, each org-scoped and audited

Delete takes the blob before the row so a failure leaves nothing a
list would show and nothing reachable. Content streams under the
global no-store policy. A type change is audited too: it decides which
files the engine reads as drawings.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The client store — documents methods with upload progress

**Files:**
- Modify: `src/lib/store/api.js` (add five methods, export them in the returned object), `src/lib/store/api-mapping.js` (`mapDocument`)
- Test: `src/lib/store/api-documents.test.js` (new)

**Interfaces:**
- Produces: `store.listDocuments(projectId) -> Document[]`; `store.uploadDocument(projectId, file, docType, { onProgress }) -> Document` (rejects with `{code, message, status}`); `store.setDocumentType(id, docType) -> Document`; `store.deleteDocument(id) -> null`; `store.fetchDocumentFile(doc) -> File`; `mapDocument(raw) -> { id, projectId, filename, docType, sizeBytes, sha256, status, error, createdAt }`.

- [ ] **Step 1: Write the failing tests**

```js
// src/lib/store/api-documents.test.js
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { createApiStore } from "./api.js";
import { mapDocument } from "./api-mapping.js";

const raw = { id: "d1", project_id: "p1", filename: "E-set.pdf", doc_type: "Drawings", size_bytes: 10, sha256: "ab", status: "uploaded", error: "", created_at: "2026-09-15T00:00:00Z" };

describe("mapDocument", () => {
  test("renames to camelCase and keeps the closed-set values", () => {
    expect(mapDocument(raw)).toEqual({ id: "d1", projectId: "p1", filename: "E-set.pdf", docType: "Drawings", sizeBytes: 10, sha256: "ab", status: "uploaded", error: "", createdAt: "2026-09-15T00:00:00Z" });
  });
});

/** A stand-in XMLHttpRequest that records what was sent and lets a test
 *  fire progress and completion by hand. */
class FakeXHR {
  static last = null;
  constructor() { this.upload = {}; this.status = 0; this.responseText = ""; FakeXHR.last = this; }
  open(method, url) { this.method = method; this.url = url; }
  send(form) { this.form = form; }
  setRequestHeader() {}
}

describe("uploadDocument", () => {
  let store;
  beforeEach(() => { vi.stubGlobal("XMLHttpRequest", FakeXHR); store = createApiStore(); });
  afterEach(() => vi.unstubAllGlobals());

  test("posts multipart with credentials, reports progress, resolves the mapped document", async () => {
    const onProgress = vi.fn();
    const p = store.uploadDocument("p1", new File([new Uint8Array(4)], "E-set.pdf", { type: "application/pdf" }), "Drawings", { onProgress });
    const xhr = FakeXHR.last;
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/projects/p1/documents");
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.form.get("doc_type")).toBe("Drawings");
    expect(xhr.form.get("file").name).toBe("E-set.pdf");
    xhr.upload.onprogress({ lengthComputable: true, loaded: 2, total: 4 });
    expect(onProgress).toHaveBeenCalledWith(50);
    xhr.status = 201; xhr.responseText = JSON.stringify(raw); xhr.onload();
    await expect(p).resolves.toMatchObject({ id: "d1", docType: "Drawings" });
  });

  test("rejects with the server's code and message on a duplicate", async () => {
    const p = store.uploadDocument("p1", new File([1], "x.pdf", { type: "application/pdf" }), "Drawings");
    const xhr = FakeXHR.last;
    xhr.status = 409; xhr.responseText = JSON.stringify({ detail: { code: "duplicate_document", message: "This appears to be the same file as first.pdf, uploaded earlier." } }); xhr.onload();
    await expect(p).rejects.toMatchObject({ code: "duplicate_document", status: 409 });
  });

  test("rejects readably when the network fails", async () => {
    const p = store.uploadDocument("p1", new File([1], "x.pdf", { type: "application/pdf" }), "Drawings");
    FakeXHR.last.onerror();
    await expect(p).rejects.toMatchObject({ code: "network" });
  });
});

describe("the other document methods", () => {
  let store;
  beforeEach(() => { store = createApiStore(); });
  afterEach(() => vi.unstubAllGlobals());

  test("listDocuments maps every row", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([raw]), { status: 200 })));
    const docs = await store.listDocuments("p1");
    expect(fetch).toHaveBeenCalledWith("/api/projects/p1/documents", expect.objectContaining({ credentials: "include" }));
    expect(docs[0].docType).toBe("Drawings");
  });

  test("setDocumentType PATCHes and deleteDocument DELETEs", async () => {
    const f = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ ...raw, doc_type: "Addendum" }), { status: 200 }))
                     .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", f);
    expect((await store.setDocumentType("d1", "Addendum")).docType).toBe("Addendum");
    expect(f.mock.calls[0][1].method).toBe("PATCH");
    await store.deleteDocument("d1");
    expect(f.mock.calls[1][0]).toBe("/api/documents/d1");
    expect(f.mock.calls[1][1].method).toBe("DELETE");
  });

  test("fetchDocumentFile returns a File named after the document", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Blob([new Uint8Array(3)]), { status: 200 })));
    const file = await store.fetchDocumentFile(mapDocument(raw));
    expect(file).toBeInstanceOf(File);
    expect(file.name).toBe("E-set.pdf");
    expect(file.type).toBe("application/pdf");
    expect(fetch).toHaveBeenCalledWith("/api/documents/d1/content", expect.objectContaining({ credentials: "include" }));
  });
});
```

The factory is `createApiStore()` (`api.js:113`).

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -- --run src/lib/store/api-documents.test.js`
Expected: FAIL — `mapDocument is not a function` / `store.uploadDocument is not a function`.

- [ ] **Step 3: Implement**

`api-mapping.js` — append:

```js
/** Wire DocumentOut -> store shape. snake_case on the wire, like items. */
export function mapDocument(raw) {
  return {
    id: raw.id,
    projectId: raw.project_id,
    filename: raw.filename,
    docType: raw.doc_type,
    sizeBytes: Number(raw.size_bytes ?? 0),
    sha256: raw.sha256,
    status: raw.status,
    error: raw.error ?? "",
    createdAt: raw.created_at,
  };
}
```

`api.js` — import `mapDocument`; add inside the factory, beside `attachEngineTakeoff`:

```js
  async function listDocuments(projectId) {
    const rows = await request(`/api/projects/${projectId}/documents`);
    return (rows || []).map(mapDocument);
  }

  /** Multipart upload over XMLHttpRequest rather than fetch, because only
   *  XHR reports upload progress -- and a 96 MB drawing set with no
   *  progress bar reads as a hung page. Rejects with the same
   *  {code, message} shape request() produces, plus the status. */
  function uploadDocument(projectId, file, docType, { onProgress } = {}) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const form = new FormData();
      form.append("file", file);
      form.append("doc_type", docType || "Other");
      xhr.open("POST", `/api/projects/${projectId}/documents`);
      xhr.withCredentials = true;
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((100 * e.loaded) / e.total));
      };
      xhr.onload = () => {
        let body = null;
        try { body = xhr.responseText ? JSON.parse(xhr.responseText) : null; } catch { body = null; }
        if (xhr.status >= 200 && xhr.status < 300) return resolve(mapDocument(body));
        const detail = body?.detail;
        if (detail && typeof detail === "object" && typeof detail.code === "string") {
          return reject({ code: detail.code, message: detail.message, status: xhr.status });
        }
        reject({ code: "request_failed", message: `The upload failed (status ${xhr.status}). Try again.`, status: xhr.status });
      };
      xhr.onerror = () => reject({ code: "network", message: "Couldn't reach the server. Check the connection and try again.", status: 0 });
      xhr.send(form);
    });
  }

  async function setDocumentType(documentId, docType) {
    return mapDocument(await request(`/api/documents/${documentId}`, { method: "PATCH", body: { doc_type: docType } }));
  }

  async function deleteDocument(documentId) {
    return request(`/api/documents/${documentId}`, { method: "DELETE" });
  }

  /** The stored bytes back as a File, for the interim engine call that
   *  still runs in the browser until B2 moves the engine behind the API. */
  async function fetchDocumentFile(doc) {
    const res = await fetch(`/api/documents/${doc.id}/content`, { credentials: "include" });
    if (!res.ok) throw await parseErrorBody(res);
    return new File([await res.blob()], doc.filename, { type: "application/pdf" });
  }
```

and add the five names to the returned object.

- [ ] **Step 4: Run**

Run: `npm test -- --run src/lib/store/api-documents.test.js src/lib/store/api.test.js src/lib/store/api-mapping.test.js`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/lib/store/api.js src/lib/store/api-mapping.js src/lib/store/api-documents.test.js
git commit -m "Give the client store the five document methods, with upload progress over XHR

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Screen C onto the API

**Files:**
- Modify: `src/components/documents/UploadDocuments.jsx`, `src/routes.jsx:48`
- Rewrite: `src/components/documents/UploadDocuments.test.jsx`

**Interfaces:**
- Consumes: `store.listDocuments`, `store.uploadDocument`, `store.setDocumentType`, `store.deleteDocument`.
- Produces: `UploadDocuments({ store })` — takes the store as a prop (routed standalone, outside the workspace layout, like `ProcessingStatus`). Row state: `uploading` (with `progress`), `ready`, `duplicate`, `unsupported`, `failed` — the words are the state.

- [ ] **Step 1: Rewrite the test file**

Replace `src/components/documents/UploadDocuments.test.jsx` with:

```jsx
/* ============================================================
   UploadDocuments.test.jsx — screen C as a view onto the API.
   A reload shows what was uploaded; a drop uploads with progress; the
   server's duplicate and unsupported copy lands on the row; remove asks
   first; the primary action needs a Drawings document.
   ============================================================ */
import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import UploadDocuments from "./UploadDocuments.jsx";

const pdf = (name, size = 1024) => new File([new Uint8Array(size)], name, { type: "application/pdf" });
const doc = (over = {}) => ({ id: "d1", projectId: "p1", filename: "E-set.pdf", docType: "Drawings", sizeBytes: 1024, sha256: "a", status: "uploaded", error: "", createdAt: "2026-09-15T00:00:00Z", ...over });

function makeStore(over = {}) {
  return {
    listDocuments: vi.fn().mockResolvedValue([]),
    uploadDocument: vi.fn(),
    setDocumentType: vi.fn(),
    deleteDocument: vi.fn().mockResolvedValue(null),
    ...over,
  };
}

const renderUpload = (store) =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/documents"]}>
      <Routes>
        <Route path="/projects/:projectId/documents" element={<UploadDocuments store={store} />} />
        <Route path="/projects/:projectId/documents/confirm" element={<p>confirm screen</p>} />
      </Routes>
    </MemoryRouter>,
  );

function drop(files) {
  const input = document.querySelector('input[type="file"]');
  Object.defineProperty(input, "files", { value: files, configurable: true });
  act(() => { input.dispatchEvent(new Event("change", { bubbles: true })); });
}

describe("UploadDocuments", () => {
  it("shows what was already uploaded, from the API, on mount", async () => {
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc()]) });
    renderUpload(store);
    expect(await screen.findByText("E-set.pdf")).toBeInTheDocument();
    expect(screen.getByText("Uploaded")).toBeInTheDocument();
    expect(store.listDocuments).toHaveBeenCalledWith("p1");
  });

  it("uploads a dropped PDF with progress and settles to Uploaded", async () => {
    let progress;
    const store = makeStore({
      uploadDocument: vi.fn((projectId, file, docType, opts) => { progress = opts.onProgress; return new Promise(() => {}); }),
    });
    renderUpload(store);
    drop([pdf("E-set.pdf")]);
    expect(await screen.findByText(/Uploading/)).toBeInTheDocument();
    act(() => progress(42));
    expect(screen.getByText("Uploading… 42%")).toBeInTheDocument();
    expect(store.uploadDocument).toHaveBeenCalledWith("p1", expect.any(File), "Drawings", expect.any(Object));
  });

  it("shows the server's duplicate copy on the row and does not list it as uploaded", async () => {
    const store = makeStore({
      uploadDocument: vi.fn().mockRejectedValue({ code: "duplicate_document", message: "This appears to be the same file as first.pdf, uploaded earlier. Remove one copy or upload a different file.", status: 409 }),
    });
    renderUpload(store);
    drop([pdf("second.pdf")]);
    expect(await screen.findByText(/same file as first.pdf/)).toBeInTheDocument();
    expect(screen.queryByText("Uploaded")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /review detected drawings/i })).toBeDisabled();
  });

  it("refuses a non-PDF before calling the API", async () => {
    const store = makeStore();
    renderUpload(store);
    drop([new File([1], "notes.docx", { type: "text/plain" })]);
    expect(await screen.findByText(/isn't a PDF/)).toBeInTheDocument();
    expect(store.uploadDocument).not.toHaveBeenCalled();
  });

  it("changes the type through the API", async () => {
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([doc()]),
      setDocumentType: vi.fn().mockResolvedValue(doc({ docType: "Addendum" })),
    });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    fireEvent.change(screen.getByLabelText(/type for E-set.pdf/i), { target: { value: "Addendum" } });
    await waitFor(() => expect(store.setDocumentType).toHaveBeenCalledWith("d1", "Addendum"));
  });

  it("asks before removing, then deletes through the API", async () => {
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc()]) });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    fireEvent.click(screen.getByRole("button", { name: /remove E-set.pdf/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/remove E-set.pdf/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /^remove$/i }));
    await waitFor(() => expect(store.deleteDocument).toHaveBeenCalledWith("d1"));
    await waitFor(() => expect(screen.queryByText("E-set.pdf")).not.toBeInTheDocument());
  });

  it("blocks continuing until at least one document is typed Drawings", async () => {
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc({ docType: "Specifications" })]) });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    expect(screen.getByRole("button", { name: /review detected drawings/i })).toBeDisabled();
  });

  it("continues to confirm when a Drawings document exists", async () => {
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc()]) });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    fireEvent.click(screen.getByRole("button", { name: /review detected drawings/i }));
    expect(await screen.findByText("confirm screen")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -- --run src/components/documents/UploadDocuments.test.jsx`
Expected: FAIL — `store` is undefined / `listDocuments` never called.

- [ ] **Step 3: Rewrite the component**

Rewrite `UploadDocuments.jsx` keeping its layout, tabs, `formatSize`, `detectDocTypeInfo`, the dropzone markup and the summary line, and changing its data source. The shape:

```jsx
export default function UploadDocuments({ store }) {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [rows, setRows] = useState([]);       // persisted docs + in-flight uploads, one list
  const [confirming, setConfirming] = useState(null);  // a row awaiting delete confirmation
  const [dragging, setDragging] = useState(false);
  const [tab, setTab] = useState("all");

  useEffect(() => {
    let live = true;
    store.listDocuments(projectId).then((docs) => {
      if (live) setRows(docs.map((d) => ({ ...d, state: "ready", progress: 100, key: d.id })));
    });
    return () => { live = false; };
  }, [store, projectId]);
```

`addFiles(fileList)`: for each file — if `!name.endsWith(".pdf") || type !== "application/pdf"` push a row `{ key, filename, sizeBytes, docType, state: "unsupported", message: `${name} isn't a PDF. Upload PDF drawings, specifications, addenda, and scope documents.` }` and do not call the API; otherwise push `{ key, filename, sizeBytes, docType: detected.type, typeAuto: true, state: "uploading", progress: 0 }` and call `store.uploadDocument(projectId, file, docType, { onProgress: (p) => update(key, { progress: p }) })` → on resolve replace the row with `{ ...doc, state: "ready", progress: 100, key: doc.id }`; on reject set `state: err.code === "duplicate_document" ? "duplicate" : err.code === "unsupported_document" ? "unsupported" : "failed"`, `message: err.message`. Keep the existing `classifyDoc` content sniff for a `typeAuto` row whose detected source was `default`, applied to the persisted row through `store.setDocumentType` only if the row is still `typeAuto` when it returns.

Row rendering: the state column reads `Uploading… {progress}%` / `Uploaded` / the server's `message` for `duplicate`, `unsupported`, `failed` — the words are the state, with `tone` classes as before. The type `<select>` has `aria-label={`Type for ${row.filename}`}` and on change calls `store.setDocumentType(row.id, value)` for a persisted row (local-only for a row still uploading — the type it uploads with). The remove button has `aria-label={`Remove ${row.filename}`}` and sets `confirming = row`; the confirmation is the existing `Modal` (`../Modal.jsx`) with title `Remove ${row.filename}?`, body "It will be removed from this project. Upload it again if you need it back.", and foot buttons **Cancel** / **Remove**; **Remove** calls `store.deleteDocument(row.id)` then drops the row. A row that never reached the server (duplicate/unsupported/failed) is removed locally with no dialog.

`canContinue = rows.some((r) => r.state === "ready" && r.docType === "Drawings")`; the primary button navigates to `/projects/${projectId}/documents/confirm` — **nothing is stashed** anymore. Delete the `setUploadedFiles` import.

`src/routes.jsx:48` → `<UploadDocuments store={store} />`.

- [ ] **Step 4: Run**

Run: `npm test -- --run src/components/documents/UploadDocuments.test.jsx && npm run build`
Expected: 8 passed; build clean. If the test selector for the type `<select>` fails, the `aria-label` is `Type for E-set.pdf` — fix the markup, not the test.

- [ ] **Step 5: Commit**

```bash
git add src/components/documents/UploadDocuments.jsx src/components/documents/UploadDocuments.test.jsx src/routes.jsx
git commit -m "Make screen C a view onto the API: uploads persist, progress is real, the server's copy lands on the row

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: The interim engine path reads from the API; `uploadedFiles.js` is deleted

**Files:**
- Modify: `src/components/documents/ConfirmDrawings.jsx`, `src/components/documents/ProcessingStatus.jsx`, `src/components/notes/NotesWorkspace.jsx`, `src/routes.jsx:49`
- Modify: `src/components/documents/ConfirmDrawings.test.jsx`, `ProcessingStatus.test.jsx`, `src/components/notes/NotesWorkspace.test.jsx`
- Delete: `src/lib/uploadedFiles.js`
- Modify: `README.md` ("Run it"), `docs/README.md` (live/done table)

**Interfaces:**
- Consumes: `store.listDocuments`, `store.fetchDocumentFile`, `store.setDocumentType`.
- Produces: `ConfirmDrawings({ store })`; the engine call's `uploaded` list is built as `await Promise.all(docs.map(async (d) => ({ file: await store.fetchDocumentFile(d), docType: d.docType })))`.

- [ ] **Step 1: Change the tests first**

In each of the three test files, remove the `uploadedFiles.js` import and every `setUploadedFiles` / `clearUploadedFiles` call. Where a test set files, instead give the mocked store `listDocuments: vi.fn().mockResolvedValue([{ id: "d1", projectId, filename: "e1.1.pdf", docType: "Drawings", sizeBytes: 1024, sha256: "a", status: "uploaded", error: "", createdAt: "…" }])` and `fetchDocumentFile: vi.fn().mockResolvedValue(new File([new Uint8Array(1024)], "e1.1.pdf", { type: "application/pdf" }))`. `ConfirmDrawings.test.jsx` renders `<ConfirmDrawings store={store} />`. Add to `ProcessingStatus.test.jsx`:

```jsx
  it("feeds the engine the stored documents, fetched back from the API, not browser memory", async () => {
    // (mock estimateProject as the file already does)
    render(...);
    await waitFor(() => expect(store.fetchDocumentFile).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(estimateProject).toHaveBeenCalledWith(
      [expect.objectContaining({ docType: "Drawings", file: expect.any(File) })], expect.anything(), expect.anything(),
    ));
  });

  it("says so when the project has no documents", async () => {
    // listDocuments resolves []
    expect(await screen.findByText(/No documents have been uploaded/)).toBeInTheDocument();
  });
```

Match the existing test file's render helper and its `estimateProject` mock exactly — read the file first.

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -- --run src/components/documents src/components/notes`
Expected: FAIL — components still import `uploadedFiles.js` / never call `fetchDocumentFile`.

- [ ] **Step 3: Implement**

`ConfirmDrawings.jsx`: accept `{ store }`; on mount `store.listDocuments(projectId)` → rows `{ id, name: filename, size: sizeBytes, docType, included: true }`; `setType` calls `store.setDocumentType(id, docType)`; keep the `classifyDoc` sniff by fetching the file through `store.fetchDocumentFile` only for rows whose filename was uninformative; remove `getUploadedFiles` / `setUploadedFiles` and the `file` field. The "Start takeoff" action navigates to processing — nothing to stash.

`ProcessingStatus.jsx`: replace `getUploadedFiles(projectId)` with

```js
      const docs = await store.listDocuments(projectId);
      if (docs.length === 0) { setError("No documents have been uploaded for this project yet. Upload a drawing set to start a takeoff."); return; }
      const uploaded = await Promise.all(docs.map(async (d) => ({ file: await store.fetchDocumentFile(d), docType: d.docType })));
```

and delete `clearUploadedFiles`. Update the header comment: the browser fetches stored bytes back for the interim engine call; B2 replaces this with a job.

`NotesWorkspace.jsx` (~line 263): same replacement for the re-run.

`src/routes.jsx:49` → `<ConfirmDrawings store={store} />`.

Delete `src/lib/uploadedFiles.js`. `grep -rn uploadedFiles src` must return nothing.

`README.md` "Run it": `docker compose up -d postgres minio minio-init api` (MinIO console at `http://localhost:9001`, dev credentials in `docker-compose.yml`); a sentence that uploads are stored in MinIO and survive a reload; the engine still runs on the host until B2. `docs/README.md`: B1 row → `plans/documents-stored.md`, state "branch `feat/document-pipeline`".

- [ ] **Step 4: Run everything**

Run: `npm test -- --run && npm run build` and, from `api/`, the full backend suite `…pytest -q -rs` (MinIO up).
Expected: frontend green, build clean; backend green with the S3 tests running (not skipped).

- [ ] **Step 5: Commit**

```bash
git add src README.md docs/README.md
git commit -m "Feed the engine from stored documents and delete the browser-held file map

A reload no longer loses an upload: the processing screen and the notes
re-run fetch each document's bytes back from the API and post them to
the engine as before. uploadedFiles.js is gone. This is the interim
until B2 puts the engine behind the API and deletes the browser call.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** §2 storage/MinIO/BlobStore/keys → Task 1, 3. §3 table → Task 2. §4 duplicate / cross-project / unsupported / corrupt deferred / org isolation → Task 3, 4. §5 endpoints + audit → Task 3, 4 (spec amended for type change). §6 client, `uploadedFiles.js` deleted, interim engine path → Task 5, 6, 7. §7 copy → the labels and messages in Tasks 3, 4, 6 are the spec's sentences. §8 tests → each task; boundary test asserted in Task 1 and 3. §9 out of scope → nothing here parses a PDF; no presigned path; no size limit. §10 dependencies → Task 1.

**Placeholders.** None.

**Type consistency.** `store_upload(db, *, actor, project, upload, doc_type, store)` (Task 3) ↔ router call (Task 3). `load_document(document_id, db, user)` (Task 3) ↔ Task 4 routes. `DocumentOut` fields (Task 2) ↔ `mapDocument` (Task 5) ↔ test `raw` (Task 5, 6). `uploadDocument(projectId, file, docType, { onProgress })` (Task 5) ↔ Task 6 call. `fetchDocumentFile(doc)` (Task 5) ↔ Task 7. `UploadDocuments({ store })`, `ConfirmDrawings({ store })` ↔ `routes.jsx` (Tasks 6, 7).

**Facts verified against the code before writing:** the undo response shape (`performed`), the `db.commit()`-in-route convention, the store factory name. Nothing is left for the implementer to look up that the plan could have looked up.
