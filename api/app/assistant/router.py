# api/app/assistant/router.py
"""Two routes. Both org-scoped through load_project, so a cross-org
probe gets the same 404 as every other project route."""

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DbSession

from app.assistant import llm, service
from app.assistant.schemas import ConversationOut, MessageIn, MessageOut
from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["conversation"])


@router.get("/projects/{project_id}/conversation", response_model=ConversationOut)
def get_conversation(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> ConversationOut:
    project = load_project(project_id, db, user)
    rows = service.list_messages(db, project.id)
    return ConversationOut(messages=[
        MessageOut(id=r.id, role=r.role, text=r.text, screen=r.screen, created_at=r.created_at) for r in rows
    ])


@router.post("/projects/{project_id}/conversation/messages")
def post_message(project_id: uuid.UUID, payload: MessageIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    if not llm.available():
        raise DomainError("not_configured", "The conversation panel isn't set up on this server", status=503)
    bundle_text, messages = service.prepare(db, actor=user, project=project, text=payload.text, screen=payload.screen)
    body = service.answer_events(project_id=project.id, actor_id=user.id, bundle_text=bundle_text, messages=messages)
    return StreamingResponse(body, media_type="text/event-stream",
                             headers={"Cache-Control": "private, no-store", "X-Accel-Buffering": "no"})
