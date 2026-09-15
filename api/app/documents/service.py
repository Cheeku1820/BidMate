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
