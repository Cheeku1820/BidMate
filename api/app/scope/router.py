"""Thin HTTP layer for scope statements. router -> service -> models."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.identity.models import User
from app.scope import service
from app.scope.schemas import ScopeDecisionIn, ScopeStatementOut
from app.takeoff.models import Document, ScopeStatement
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["scope"])


def _out(statement: ScopeStatement, document_filename: str) -> ScopeStatementOut:
    """page is 1-based on the wire; `page_index` (0-based) never crosses
    the boundary, same reasoning as everything else CLAUDE.md's
    "nothing on the wire that names internals" covers -- an estimator
    reads "page 3," never "page_index 2.\""""
    return ScopeStatementOut(
        id=statement.id, kind=statement.kind, text=statement.text, edited_text=statement.edited_text,
        status=statement.status, document_id=statement.document_id, document_filename=document_filename,
        page=statement.page_index + 1, quote=statement.quote,
    )


@router.get("/projects/{project_id}/scope", response_model=list[ScopeStatementOut])
def get_scope(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> list[ScopeStatementOut]:
    project = load_project(project_id, db, user)
    statements = service.list_statements(db, project)
    # One query for every document filename in the project rather than
    # one per statement -- the same shape mutations.py's get_notes uses
    # for author names, for the same reason.
    filenames = {d.id: d.filename for d in db.scalars(select(Document).where(Document.project_id == project.id))}
    return [_out(s, filenames.get(s.document_id, "")) for s in statements]


@router.patch("/scope/{statement_id}", response_model=ScopeStatementOut)
def patch_scope(statement_id: uuid.UUID, payload: ScopeDecisionIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> ScopeStatementOut:
    statement = service.load_statement(statement_id, db, user)
    service.decide(db, actor=user, statement=statement, status=payload.status, edited_text=payload.edited_text)
    db.commit()
    document = db.get(Document, statement.document_id)
    return _out(statement, document.filename if document else "")
