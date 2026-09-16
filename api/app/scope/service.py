"""Scope statements: what the documents say the electrical work is,
found by the worker's read job (B2), settled by a person.

Every decision goes through actions.commit(), same as notes.py --
attributed and in the append-only audit trail. Like a note, a scope
decision is NOT undoable: `scope_decide` is deliberately absent from
`undo.REVERSIBLE`, for the same reason `note_add`/`note_edit`/
`note_delete` are -- reversing it would mean restoring prior field
values from a snapshot, which is its own feature, not a side effect of
this one."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.scope.schemas import SCOPE_STATUSES
from app.takeoff import actions
from app.takeoff.models import Project, ScopeStatement
from app.takeoff.router import load_project, not_found

# Mirrors ScopeStatement.text/edited_text's own String(500) column
# length (app/takeoff/models.py) -- the same limit enforced twice, once
# at the database and once here with an estimator-facing message,
# rather than surfacing an IntegrityError.
_MAX_TEXT = 500


def list_statements(db: DbSession, project: Project) -> list[ScopeStatement]:
    return list(
        db.scalars(
            select(ScopeStatement)
            .where(ScopeStatement.project_id == project.id)
            .order_by(ScopeStatement.created_at, ScopeStatement.id)
        )
    )


def load_statement(statement_id: uuid.UUID, db: DbSession, user: User) -> ScopeStatement:
    """The tenancy gate for the one statement-scoped route -- resolve the
    row, then defer to load_project for the org check. Same shape as
    documents.service.load_document and takeoff.router.load_item: 404
    whether the statement is missing or belongs to another org, never a
    403."""
    statement = db.get(ScopeStatement, statement_id)
    if statement is None:
        raise not_found()
    load_project(statement.project_id, db, user)
    return statement


def _snapshot(statement: ScopeStatement) -> dict:
    return {"status": statement.status, "edited_text": statement.edited_text}


def decide(
    db: DbSession,
    *,
    actor: User,
    statement: ScopeStatement,
    status: str | None = None,
    edited_text: str | None = None,
) -> ScopeStatement:
    """Settle one statement: confirm it, dismiss it, correct its text, or
    reopen it back to `found`. Exactly one of `status`/`edited_text` is
    expected per call -- the PATCH body is `{"status": ...}` or
    `{"edited_text": ...}`, never both and never neither, so a client
    that means to do two things makes two requests, each its own audited
    action.

    `status="found"` is the estimator un-deciding a statement they
    settled too quickly -- allowed, not just tolerated, and labeled
    "Reopened" rather than reusing "Confirmed"/"Dismissed" so the audit
    trail reads as what actually happened.
    """
    if (status is None) == (edited_text is None):
        raise DomainError(
            "invalid_scope_decision",
            "Send either a status or a corrected statement, not both and not neither.",
            status=422,
        )

    before = _snapshot(statement)

    if status is not None:
        if status not in SCOPE_STATUSES:
            raise DomainError(
                "invalid_scope_status",
                f"Status must be one of {', '.join(SCOPE_STATUSES)}.",
                status=422,
            )
        statement.status = status
        shown = statement.edited_text or statement.text
        label = {
            "confirmed": f"Confirmed: {shown}",
            "dismissed": f"Dismissed: {shown}",
            "found": f"Reopened: {shown}",
        }[status]
    else:
        cleaned = edited_text.strip()
        if not cleaned or len(cleaned) > _MAX_TEXT:
            raise DomainError(
                "invalid_scope_text",
                f"The corrected statement can't be empty and must be {_MAX_TEXT} characters or fewer.",
                status=422,
            )
        statement.edited_text = cleaned
        label = f"Changed: {cleaned}"

    statement.decided_by = actor.id
    statement.decided_at = datetime.now(timezone.utc)
    db.flush()

    actions.commit(
        db, actor=actor, project_id=statement.project_id, kind="scope_decide",
        label=label, before=before, after=_snapshot(statement),
    )
    return statement
