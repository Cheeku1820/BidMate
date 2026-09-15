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
