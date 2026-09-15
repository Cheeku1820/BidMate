"""Thin HTTP layer for documents. router -> service -> models."""

import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.documents import service
from app.documents.blobstore import BlobStore, get_blob_store
from app.documents.schemas import DocumentOut, DocumentTypeIn
from app.identity.models import User
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["documents"])

# Characters that would break or split a Content-Disposition header line:
# a quote (closes the quoted-string early), or a raw CR/LF (a multipart
# filename is otherwise ordinary request data -- nothing stops a crafted
# one from carrying either).
_HEADER_UNSAFE = re.compile(r'["\r\n\x00-\x1f\x7f]')


def _content_disposition(filename: str) -> str:
    """RFC 6266 `Content-Disposition`, safe for a filename containing a
    quote or a raw CR/LF. `filename*` (RFC 5987) percent-encodes the
    exact name so nothing in it can be interpreted as a header
    delimiter; `filename` is an ASCII-only fallback, quotes and control
    characters stripped, for a user agent that ignores the star form."""
    ascii_fallback = _HEADER_UNSAFE.sub("", filename.encode("ascii", "ignore").decode("ascii")) or "document.pdf"
    encoded = quote(filename, safe="")
    return f'inline; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


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
        headers={"Content-Disposition": _content_disposition(document.filename), "Content-Length": str(document.size_bytes)},
    )
