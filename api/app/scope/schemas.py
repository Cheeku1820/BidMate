"""Wire shapes for scope statements. snake_case, like the takeoff and
documents schemas.

`status` here is a scope statement's own vocabulary -- found, confirmed,
dismissed -- not the four review labels (CLAUDE.md: "a note's status is
not an item's status," and a scope statement carries the same
distinction a note does). `ScopeStatementOut` never carries anything
that names how the statement was produced: no `source`, `attempt`,
`llm`, `confidence`, `model`, or `run_id` reaches the wire, and
`decided_by` stays server-side audit detail rather than an interface
field."""

import uuid

from pydantic import BaseModel

SCOPE_KINDS = ("included", "excluded", "by_others", "alternate")
SCOPE_STATUSES = ("found", "confirmed", "dismissed")


class ScopeStatementOut(BaseModel):
    id: uuid.UUID
    kind: str
    text: str
    edited_text: str | None
    status: str
    document_id: uuid.UUID
    document_filename: str
    page: int
    quote: str


class ScopeDecisionIn(BaseModel):
    """Exactly one of the two is expected -- `service.decide()` is the
    single place that enforces that, with the estimator-facing rejection,
    the same split `documents.schemas.DocumentTypeIn`'s docstring
    explains for `doc_type`: a field validator's message here would be
    field-name-first pydantic phrasing rather than the sentence-case copy
    the product speaks, and leaving both fields unvalidated at the wire
    keeps that one rejection message in one place."""

    status: str | None = None
    edited_text: str | None = None
