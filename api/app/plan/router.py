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
