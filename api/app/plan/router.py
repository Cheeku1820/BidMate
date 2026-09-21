"""Thin HTTP layer for the project plan. router -> service -> models.
Every route goes through load_project first, so a rival org's probe is
refused with project_not_found before any key is looked at."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.identity.models import User
from app.plan import service
from app.plan.schemas import AnswerIn, LineDecisionIn, PhaseIn, PlanLineOut, PlanOut, QuestionOut
from app.takeoff.router import load_project

router = APIRouter(prefix="/api", tags=["plan"])


@router.get("/projects/{project_id}/plan", response_model=PlanOut)
def get_plan(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> PlanOut:
    project = load_project(project_id, db, user)
    plan = service.build_plan(db, project)
    db.commit()
    return plan


@router.patch("/projects/{project_id}/plan/lines/{key}", response_model=PlanLineOut | QuestionOut)
def patch_line(project_id: uuid.UUID, key: str, payload: LineDecisionIn, user: User = Depends(current_user),
               db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    out = service.decide(db, actor=user, project=project, key=key, status=payload.status, edited_text=payload.edited_text)
    db.commit()
    return out


@router.post("/projects/{project_id}/plan/questions/{key}/answer", response_model=QuestionOut)
def post_answer(project_id: uuid.UUID, key: str, payload: AnswerIn, user: User = Depends(current_user),
                db: DbSession = Depends(get_db)) -> QuestionOut:
    project = load_project(project_id, db, user)
    out = service.answer(db, actor=user, project=project, key=key, body=payload.body)
    db.commit()
    return out


@router.post("/projects/{project_id}/plan/phases", response_model=PlanLineOut, status_code=201)
def post_phase(project_id: uuid.UUID, payload: PhaseIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> PlanLineOut:
    project = load_project(project_id, db, user)
    out = service.add_phase(db, actor=user, project=project, name=payload.name)
    db.commit()
    return out


@router.delete("/projects/{project_id}/plan/phases/{phase_id}", status_code=204)
def delete_phase(project_id: uuid.UUID, phase_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> None:
    project = load_project(project_id, db, user)
    service.remove_phase(db, actor=user, project=project, phase_id=phase_id)
    db.commit()
