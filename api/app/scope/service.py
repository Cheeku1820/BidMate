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
from app.scope.schemas import SCOPE_KINDS, SCOPE_STATUSES
from app.jobs import queue
from app.takeoff import actions
from app.takeoff.models import Project, ScopeStatement
from app.takeoff.router import load_project, not_found

# Mirrors ScopeStatement.text/edited_text's own String(500) column
# length (app/takeoff/models.py) -- the same limit enforced twice, once
# at the database and once here with an estimator-facing message,
# rather than surfacing an IntegrityError.
_MAX_TEXT = 500

# The audit label's words for each direction. Construction terms, not
# the wire values: an action log entry reading "Set to by_others" is the
# schema talking rather than the product.
_KIND_WORDS = {
    "included": "included in this price",
    "excluded": "excluded",
    "by_others": "by others",
    "alternate": "an alternate",
}


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
    return {"status": statement.status, "edited_text": statement.edited_text,
            "kind": statement.kind}


def decide(
    db: DbSession,
    *,
    actor: User,
    statement: ScopeStatement,
    status: str | None = None,
    edited_text: str | None = None,
    kind: str | None = None,
) -> ScopeStatement:
    """Settle one statement: confirm it, dismiss it, correct its text,
    correct its direction, or reopen it back to `found`. Exactly one of
    `status`/`edited_text`/`kind` is expected per call -- the PATCH body
    carries one of them, never two and never none, so a client that
    means to do two things makes two requests, each its own audited
    action.

    `status="found"` is the estimator un-deciding a statement they
    settled too quickly -- allowed, not just tolerated, and labeled
    "Reopened" rather than reusing "Confirmed"/"Dismissed" so the audit
    trail reads as what actually happened.

    `kind` is the direction, and it is settable for a money reason: the
    ROM reads it to decide what scope removes from the number. Before
    this, an estimator who saw "Fire alarm by others" read wrong could
    reword the sentence -- which the ROM's keyword match does see -- but
    not the direction the ROM acts on, so the estimate kept removing the
    fire alarm work and quoted the corrected, inclusive sentence as its
    justification.
    """
    given = [f for f in (status, edited_text, kind) if f is not None]
    if len(given) != 1:
        raise DomainError(
            "invalid_scope_decision",
            "Send one of a status, a corrected statement, or a direction -- exactly one per change.",
            status=422,
        )

    before = _snapshot(statement)

    if kind is not None:
        if kind not in SCOPE_KINDS:
            raise DomainError(
                "invalid_scope_kind",
                f"Direction must be one of {', '.join(SCOPE_KINDS)}.",
                status=422,
            )
        statement.kind = kind
        shown = statement.edited_text or statement.text
        label = f"Set to {_KIND_WORDS[kind]}: {shown}"
    elif status is not None:
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

    # A scope decision changes what the estimate covers, so the ROM's
    # exclusions have to be worked out again (rom-estimate.md, "scope
    # filters the number"). Without this, confirming that work the
    # documents excluded is actually included left the stored exclusion
    # subtracting money until somebody happened to start another
    # takeoff. Queued, not run inline: generation is a batch walk over
    # every item on the project and a PATCH should not wait on it.
    project = db.get(Project, statement.project_id)
    if project is not None:
        queue.enqueue_estimate(db, project, actor.id)
    return statement
