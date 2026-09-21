"""Wire shapes for the project plan. snake_case, like scope and notes.

`status` is a plan line's own vocabulary -- found, confirmed, dismissed,
and for a question answered -- never the four review labels (CLAUDE.md:
a note's status is not an item's status). Nothing here names how a line
was produced: no rule, source, attempt, model, confidence, or run id
reaches the wire."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.scope.schemas import ScopeStatementOut

PLAN_STATUSES = ("found", "confirmed", "dismissed", "answered")
LINE_STATUSES = ("found", "confirmed", "dismissed")


class PlaceOut(BaseModel):
    document_id: uuid.UUID | None
    document_filename: str
    page: int | None
    quote: str


class PlanLineOut(BaseModel):
    key: str
    kind: str
    text: str
    found_text: str
    edited_text: str | None
    status: str
    document_id: uuid.UUID | None
    document_filename: str | None
    page: int | None
    quote: str | None
    division: str | None = None
    sheet_number: str | None = None
    added: bool = False
    phase_id: uuid.UUID | None = None
    places: list[PlaceOut] = Field(default_factory=list)


class QuestionOut(BaseModel):
    key: str
    status: str
    title: str = Field(min_length=1)
    found: str = Field(min_length=1)
    why: str = Field(min_length=1)
    fix: str = Field(min_length=1)
    where: str = Field(min_length=1)
    document_id: uuid.UUID | None
    document_filename: str | None
    note_id: uuid.UUID | None


class PlanOut(BaseModel):
    read_at: datetime | None
    reading: bool
    has_drawings: bool
    undecided: int
    scope: list[ScopeStatementOut]
    specs: list[PlanLineOut]
    schedules: list[PlanLineOut]
    phases: list[PlanLineOut]
    questions: list[QuestionOut]


class LineDecisionIn(BaseModel):
    """Exactly one of the two; service.decide enforces it with the
    estimator-facing sentence, the way scope.service.decide does."""

    status: str | None = None
    edited_text: str | None = None


class AnswerIn(BaseModel):
    body: str = ""


class PhaseIn(BaseModel):
    name: str = ""
