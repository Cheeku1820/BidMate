"""Thin HTTP layer for documents. router -> service -> models."""

import logging
import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DbSession
from starlette.background import BackgroundTask

from app.auth.dependencies import current_user
from app.db import get_db
from app.documents import service
from app.documents.blobstore import BlobStore, get_blob_store
from app.documents.schemas import DocumentOut, DocumentTypeIn
from app.identity.models import User
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["documents"])
logger = logging.getLogger(__name__)

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
    characters stripped, for a user agent that ignores the star form.

    `attachment`, not `inline`: these bytes are a drawing set that
    frequently arrives under a general contractor's NDA (ROADMAP.md
    §3.3), and an inline PDF renders inside whatever page framed it.
    Every in-product path to this route reads the body itself (the
    client fetches it as a File) rather than pointing a viewer at the
    URL, so nothing in the interface depends on inline rendering."""
    ascii_fallback = _HEADER_UNSAFE.sub("", filename.encode("ascii", "ignore").decode("ascii")) or "document.pdf"
    encoded = quote(filename, safe="")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


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
    key = service.delete_document(db, actor=user, document=document)
    db.commit()
    try:
        store.delete(key)
    except Exception:  # noqa: BLE001 -- the row is gone; an orphan blob is the harmless outcome
        logger.warning("blob delete failed after row delete", extra={"storage_key": key})


@router.get("/documents/{document_id}/content")
def get_content(document_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db), store: BlobStore = Depends(get_blob_store)) -> StreamingResponse:
    document = service.load_document(document_id, db, user)
    body = service.open_content(document, store)
    return StreamingResponse(
        iter(lambda: body.read(1024 * 1024), b""),
        media_type="application/pdf",
        headers={
            "Content-Disposition": _content_disposition(document.filename),
            "Content-Length": str(document.size_bytes),
            # The bytes are a PDF and are served as one. `nosniff` stops
            # a user agent from deciding otherwise from the content --
            # an uploaded file is untrusted input, and content sniffing
            # is how it gets to choose its own type.
            "X-Content-Type-Options": "nosniff",
        },
        # botocore's StreamingBody holds an open connection from the
        # pool. Without this it is released only when the object is
        # collected, which under load leaks the pool dry; a client that
        # disconnects mid-stream never reaches the end of the iterator
        # at all.
        background=BackgroundTask(body.close),
    )
