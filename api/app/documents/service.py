"""Documents: stored, listed, retyped, removed, and streamed back. The
API never opens one -- it streams bytes, hashes them, records them.
Opening an untrusted PDF is the worker's job (B2); see
docs/specs/documents-stored.md §1.

Every mutation goes through actions.commit() so it is attributed and in
the audit log. None is undoable: a deleted blob cannot be replayed from
a row, which is why the client asks before deleting."""

from __future__ import annotations

import hashlib
import uuid
from typing import BinaryIO

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.documents.blobstore import BlobNotFound, BlobStore
from app.documents.schemas import DOC_TYPES
from app.errors import DomainError
from app.identity.models import User
from app.takeoff import actions
from app.takeoff.models import Document, Project
from app.takeoff.router import load_project, not_found

_CHUNK = 1024 * 1024
_MAX_FILENAME = 300


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


def _duplicate_error(existing: Document) -> DomainError:
    return DomainError(
        "duplicate_document",
        f"This appears to be the same file as {existing.filename}, uploaded earlier. Remove one copy or upload a different file.",
        status=409,
    )


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
    if len(filename) > _MAX_FILENAME:
        raise DomainError(
            "filename_too_long",
            "The file name is too long to store. Rename it and upload again.",
            status=422,
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

    # This select gives the common case a clean 409 without an exception
    # round-trip. It is not enough on its own: two uploads of the same
    # bytes in flight together (screen C drops files in parallel) can
    # both pass it before either commits, which is what the flush below
    # is for.
    existing = db.scalar(select(Document).where(Document.project_id == project.id, Document.sha256 == sha))
    if existing is not None:
        raise _duplicate_error(existing)

    document = Document(
        id=uuid.uuid4(), project_id=project.id, filename=filename, doc_type=doc_type,
        content_type="application/pdf", size_bytes=size, sha256=sha, storage_key="",
        uploaded_by=actor.id,
    )
    document.storage_key = storage_key(project, document.id)
    db.add(document)
    try:
        db.flush()
    except IntegrityError:
        # The race the pre-flush select can't close: another upload of
        # the same bytes committed between that select and this flush.
        # The database, not the app, is the tiebreaker -- roll back this
        # attempt before it ever touches storage, and name the row that
        # won.
        db.rollback()
        existing = db.scalar(select(Document).where(Document.project_id == project.id, Document.sha256 == sha))
        if existing is not None:
            raise _duplicate_error(existing) from None
        raise

    # Storage is touched only after the row's own insert has cleared the
    # database's uniqueness check. If put() raises, the row is still
    # uncommitted -- the route never reaches its own db.commit() -- so a
    # storage failure never leaves an orphan blob or a half-written
    # document.
    store.put(document.storage_key, upload.file, "application/pdf", size)
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


def delete_document(db: DbSession, *, actor: User, document: Document) -> str:
    """Row first, committed by the route, then the blob -- the route
    deletes the blob only after its own db.commit() succeeds, so a
    storage failure can never leave a row that points at nothing. The
    orphan a failed storage delete leaves is unreachable by any route
    (every key is reached through a row) and is the reaper's problem
    (ROADMAP.md §2.2).

    I3: the previous version called `store.delete` from inside this
    function, before the route's own `db.commit()` -- so a storage
    failure rolled the whole transaction back, and the row's deletion
    never took effect. The estimator's remove looked like it silently
    failed rather than actually removing the document. Returning the
    key instead, and leaving the blob delete to the route, means the
    row is durably gone before storage is ever touched."""
    before = _row_fields(document)
    project_id, filename, key = document.project_id, document.filename, document.storage_key
    db.delete(document)
    db.flush()
    actions.commit(
        db, actor=actor, project_id=project_id, kind="document_delete",
        label=f"Removed {filename}", before=before, after={},
    )
    return key


def open_content(document: Document, store: BlobStore) -> BinaryIO:
    """A row whose blob is gone is the orphan case `delete_document`'s
    ordering is chosen to avoid, but it is reachable another way: a
    storage lifecycle rule, a restore from a database backup taken after
    the blob was removed, a key removed out of band. Telling the
    estimator what to do about it beats a 500 that names storage."""
    try:
        return store.open(document.storage_key)
    except BlobNotFound:
        raise DomainError(
            "document_unavailable",
            f"{document.filename} isn't available any more. Upload it again to include it in this takeoff.",
            status=404,
        ) from None
