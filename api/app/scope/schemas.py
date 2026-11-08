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
    """Exactly one of the three is expected -- `service.decide()` is the
    single place that enforces that, with the estimator-facing rejection,
    the same split `documents.schemas.DocumentTypeIn`'s docstring
    explains for `doc_type`: a field validator's message here would be
    field-name-first pydantic phrasing rather than the sentence-case copy
    the product speaks, and leaving the fields unvalidated at the wire
    keeps that one rejection message in one place.

    `kind` is the direction -- whether the statement puts the work in
    the price or out of it. It is settable because the ROM reads it to
    decide what scope removes from the number
    (`app.estimate.generate_scope`), and correcting the sentence was not
    enough: an estimator who edited "Fire alarm by others" to "Fire
    alarm is included" changed only the text, so the estimate went on
    removing the fire alarm and quoted the inclusion as its reason.
    Direction is a fact to set, not a sentence to be parsed -- parsing
    it would be a second classifier beside `app.engine.scope`."""

    status: str | None = None
    edited_text: str | None = None
    kind: str | None = None
