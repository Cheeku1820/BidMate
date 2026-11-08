"""The estimator's override of one assumption.

docs/specs/rom-estimate.md. The product assumed a ceiling height at 14
feet; the estimator knows it is 16. Typing 16 here does three things,
and all three matter:

- The number becomes theirs. `source` flips to `estimator`, which is
  what makes the next run leave it alone (`app.estimate.write`) -- the
  engine never discards a person's judgment.
- The line stops reading as assumed. It was derived; now somebody
  measured it, and `where` says who and when so a reader can ask them.
- It lands in the action log as one undoable action, attributed, through
  the same `commit()` path every manual edit takes. No new mechanism:
  undo, the audit trail, and attribution all work because nothing was
  invented.

What this is deliberately NOT: approval. There is no approval on a ROM,
and an override is a correction to a number rather than a person
standing behind the document. The two are different acts and the ROM
only has the first.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.estimate.basis import BASIS
from app.identity.models import User
from app.takeoff import actions
from app.takeoff.models import Assumption
from app.takeoff.router import load_project, not_found

# A value the estimator typed is their own measurement or their own
# price, so it stops carrying a derived basis's width in the budget
# range. Keeping the original basis would widen the range on a number a
# person measured, and would print "inferred from context" beside a
# ceiling height somebody went and looked at.
OVERRIDE_BASIS = "estimator_entered"

_MAX_VALUE = 100   # mirrors Assumption.value's String(100)
_MAX_UNIT = 20     # mirrors Assumption.unit's String(20)


def load_assumption(assumption_id: uuid.UUID, db: DbSession, user: User) -> Assumption:
    """The tenancy gate. Resolve the row, then defer to `load_project`
    for the org check -- same shape as `scope.service.load_statement`
    and `takeoff.router.load_item`: 404 whether the assumption is
    missing or belongs to another org, never a 403."""
    row = db.get(Assumption, assumption_id)
    if row is None:
        raise not_found()
    load_project(row.project_id, db, user)
    return row


def _snapshot(row: Assumption) -> dict:
    """Only the columns an override touches.

    `section` and `title` identify the assumption and are not
    snapshotted: an undo that restored them could move a disclosure into
    a different section. `basis` is snapshotted, because the override
    replaces it. `assumption_id` rides along so
    `undo_apply._apply_assumption` knows which row to put back --
    `Action` has an `item_id` and a `sheet_id` but no assumption column,
    and adding one for a single action kind would be a migration for a
    pointer the payload can carry.
    """
    return {
        "assumption_id": str(row.id),
        "value": row.value,
        "unit": row.unit,
        "found": row.found,
        "where": row.where,
        "basis": row.basis,
        "source": row.source,
        "created_by_user_id": str(row.created_by_user_id) if row.created_by_user_id else None,
    }


def override(db: DbSession, *, row: Assumption, actor: User,
             value: str | None, unit: str | None = None) -> Assumption:
    """Replace an assumed number with one the estimator entered."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise DomainError(
            "invalid_override",
            "Enter the value this line should carry. Clearing it would leave the line with no number "
            "and no assumption behind it.",
            status=422,
        )
    if len(cleaned) > _MAX_VALUE:
        raise DomainError(
            "invalid_override",
            f"A value can be at most {_MAX_VALUE} characters.",
            status=422,
        )
    cleaned_unit = (unit if unit is not None else row.unit or "").strip() or None
    if cleaned_unit and len(cleaned_unit) > _MAX_UNIT:
        raise DomainError(
            "invalid_override",
            f"A unit can be at most {_MAX_UNIT} characters.",
            status=422,
        )
    if row.basis == "standard_exclusion":
        raise DomainError(
            "invalid_override",
            "A scope exclusion is changed by stating the scope, not by typing a number. "
            "Add or edit the scope statement, and the estimate follows it.",
            status=422,
        )

    before = _snapshot(row)
    stamped = datetime.now(timezone.utc)

    row.value = cleaned
    row.unit = cleaned_unit
    row.source = "estimator"
    row.created_by_user_id = actor.id
    # The line is no longer derived, and the document has to say who to
    # ask about it instead of which table it came from.
    row.found = f"Entered by {actor.name}."
    row.where = f"Entered by {actor.name}, {stamped:%b %-d, %Y}"
    row.basis = OVERRIDE_BASIS
    db.flush()

    label = f"Entered {row.title.lower()} as {cleaned}{f' {cleaned_unit}' if cleaned_unit else ''}"
    actions.commit(
        db, actor=actor, project_id=row.project_id, kind="assumption_edit",
        label=label, before=before, after=_snapshot(row),
    )
    db.flush()
    return row


def basis_label(key: str) -> str:
    spec = BASIS.get(key)
    return spec.label if spec else key
