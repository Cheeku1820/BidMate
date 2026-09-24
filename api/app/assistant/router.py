# api/app/assistant/router.py
"""Two routes. Both org-scoped through load_project, so a cross-org
probe gets the same 404 as every other project route."""

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DbSession

from app.assistant import llm, service
from app.assistant.models import ConversationMessage
from app.assistant.schemas import ConversationOut, MessageIn, MessageOut, ProposalDecisionIn
from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.takeoff.router import load_project, not_found

router = APIRouter(prefix="/api", tags=["conversation"])


@router.get("/projects/{project_id}/conversation", response_model=ConversationOut)
def get_conversation(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> ConversationOut:
    project = load_project(project_id, db, user)
    rows = service.thread_view(db, project)
    # thread_view can reach plan_service.build_plan (through a plan-kind
    # proposal's staleness check), which stages a project-stage advance --
    # see its own docstring. A read must never write, so roll back
    # whatever that recompute staged before responding.
    db.rollback()
    return ConversationOut(messages=[MessageOut(**row) for row in rows])


@router.post("/projects/{project_id}/conversation/messages")
def post_message(project_id: uuid.UUID, payload: MessageIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    if not llm.available():
        raise DomainError("not_configured", "The conversation panel isn't set up on this server", status=503)
    bundle_text, messages, screen = service.prepare(db, actor=user, project=project, text=payload.text, screen=payload.screen)
    body = service.answer_events(project_id=project.id, actor_id=user.id, bundle_text=bundle_text, messages=messages,
                                 message_text=payload.text, screen=screen)
    return StreamingResponse(body, media_type="text/event-stream",
                             headers={"Cache-Control": "private, no-store", "X-Accel-Buffering": "no"})


@router.patch("/projects/{project_id}/conversation/messages/{message_id}/proposal", response_model=MessageOut)
def patch_proposal(project_id: uuid.UUID, message_id: uuid.UUID, payload: ProposalDecisionIn,
                   user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> MessageOut:
    """Bookkeeping: what became of a card. It never touches a takeoff
    record -- the change itself went through the record's own endpoint --
    so nothing here is audited and nothing enters the undo stack."""
    project = load_project(project_id, db, user)
    row = db.get(ConversationMessage, message_id)
    if row is None or row.project_id != project.id or row.proposal is None:
        raise not_found()
    if row.proposal_status != "offered":
        raise DomainError("proposal_settled", f"That card was already {row.proposal_status}.", status=409)
    row.proposal_status = payload.status
    db.commit()
    return MessageOut(id=row.id, role=row.role, text=row.text, screen=row.screen, created_at=row.created_at,
                      proposal=row.proposal, proposal_status=row.proposal_status)
