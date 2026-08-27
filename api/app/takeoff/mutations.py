"""Mutation endpoints: approve/reject/unreject/edit/delete, bulk-approve,
scale confirmation, undo/redo -- the nine writes the review workspace needs
(task-13-brief.md's "what you are building").

Split from `router.py` rather than added to it (correction 7): reads plus
nine mutation endpoints and their request/response models would have
pushed one file well past this project's ~300-line guideline. Shares
`load_project`, `load_item`, `load_sheet`, and `not_found` from
`router.py` instead of redefining them -- there is exactly one tenancy
gate, and every route here calls into it before touching a service
function, which is what keeps `CrossOrgActionError` unreachable over HTTP
(correction 8's cousin: the service layer's own org check is defence in
depth, never the thing a route relies on).

Commit convention, set by Task 12 and repeated here for all nine routes
rather than inventing a second one (correction, "Committing" in
task-12-brief.md): call the service function, then `db.commit()` in the
handler. `get_db` never commits on its own.
"""

import re
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.takeoff import bulk, review
from app.takeoff import scale as scale_module
from app.takeoff import snapshot as snapshot_module
from app.takeoff import undo as undo_module
from app.takeoff.ingest_service import ingest_takeoff
from app.takeoff.router import load_item, load_project, load_sheet
from app.takeoff.schemas import (
    BulkApproveOut, ItemMutationOut, ScaleMutationOut, SkippedItemOut, TakeoffIngestIn, TakeoffIngestOut, UndoRedoOut,
)

router = APIRouter(prefix="/api", tags=["takeoff-mutations"])


# A quantity string must look like a plain decimal literal -- optional
# leading minus, digits, optional ".digits" -- and nothing else. Python's
# `Decimal()` is far more permissive: it honours PEP 515 underscore
# grouping ("14_0" -> 140, a silent 10x), strips surrounding whitespace
# ("  14 " -> 14), and accepts scientific notation ("1e-40" -> rounds to
# 0.00). A quantity string is a wire contract for a bid number, not a
# general-purpose numeric literal parser, so this is deliberately
# narrower than what `Decimal` itself accepts. `\Z` rather than `$`,
# since Python's `$` also matches just before a trailing newline.
_QUANTITY_LITERAL = re.compile(r"^-?\d+(\.\d+)?\Z")


class EditIn(BaseModel):
    """The `PATCH /items/{id}` body.

    `extra="forbid"` (review finding): the default `extra="ignore"`
    silently drops any key that isn't one of the five fields below, so
    `{"unit": "LF", "status": "approved"}` -- neither editable -- reduced
    to an empty `changes` dict and produced a phantom no-op edit: 200, a
    permanent row in the append-only action log, a version bump forcing
    every reviewer to re-fetch, and a no-op step on the *shared* undo
    stack naming an edit that never happened. `extra="forbid"` turns an
    unknown key into an immediate 422 instead; `edit()` below separately
    refuses a body with zero *known* fields (`PATCH {}`), which
    `extra="forbid"` alone doesn't catch since `{}` has no unknown keys.

    All five fields default to `None` so the endpoint can tell "not
    sent" from "sent as null" via `model_fields_set`, rather than
    `body.model_dump(exclude_none=True)` (the sketch's approach,
    correction 2) -- `exclude_none=True` strips an explicit `notes: null`
    before `edit_validation.validate_edit()` ever sees it, turning its "notes
    cannot be removed entirely" refusal into a silent no-op success.

    `quantity` accepts a JSON *string* only ("184.55"), never a bare JSON
    number (correction 1) -- `Item.quantity` is `Numeric(12, 2)` and this
    application computes bid totals from it, so the validator below
    refuses a float/int/bool before pydantic's own Decimal coercion ever
    runs. It also matches the string against `_QUANTITY_LITERAL` (a
    second review finding: a syntactically "valid" `Decimal` string can
    still silently change the number -- see that pattern's comment).
    `edit_validation.validate_edit()` still does its own parsing and
    finiteness/sign/magnitude/scale checks downstream; this validator
    only narrows the wire format, it doesn't replace that validation.
    """

    model_config = ConfigDict(extra="forbid")

    system: str | None = None
    category: str | None = None
    quantity: Decimal | None = None
    notes: str | None = None
    symbol: str | None = None

    @field_validator("quantity", mode="before")
    @classmethod
    def _quantity_must_be_a_plain_decimal_string(cls, value):
        if value is None or isinstance(value, Decimal):
            return value
        if not isinstance(value, str):
            raise ValueError('quantity must be sent as a JSON string, such as "184.55", not a number')
        if not _QUANTITY_LITERAL.match(value):
            raise ValueError(
                'quantity must be a plain decimal number written as a string, such as "184.55" -- '
                "no underscores, whitespace, scientific notation, or leading plus sign"
            )
        return value


class BulkApproveIn(BaseModel):
    item_ids: list[uuid.UUID]


class ScaleIn(BaseModel):
    value: str


def require_expected_version(
    if_match: int = Header(
        alias="If-Match",
        description="The Item.version the client last saw for this item, so a stale write can be refused.",
    ),
) -> int:
    """Header, not a body field, for all five single-item mutations
    (task-13b-report.md has the full reasoning): this API already runs
    the read half of RFC 7232's conditional-request family
    (`GET /snapshot`'s `ETag`/`If-None-Match`, in `router.py`), so
    `If-Match` on writes extends one idiom instead of inventing a second
    "expected version" convention that only some endpoints carry. It
    also applies uniformly regardless of whether an endpoint already had
    a body (`PATCH`) or never did (`approve`/`reject`/`unreject`/
    `DELETE`), sidestepping httpx's refusal to send a JSON body on
    `Client.delete()`. Required, not optional: FastAPI returns 422 on
    its own when the header is missing or not an integer.
    """
    return if_match


# Estimator-facing copy for bulk.py's skip codes (correction 4, carried
# forward from Task 8's "skip codes have no estimator-facing copy yet;
# the endpoint task must give each one a recovery action"). Sentence
# case, no "please", no "successfully", no processing internals.
# `already_approved` names no action because none is needed; the rest
# each say what to do next.
#
# `needs_attention` / `missing_information` are two codes, not the one
# `not_ready_to_review` this shipped with initially (a review finding):
# collapsing them lost the distinction CLAUDE.md's status vocabulary
# treats as the spine -- one is a resolvable judgment call, the other is
# blocked with no override. Screen G (bulk approval's home) is exactly
# where that distinction has to survive, so `bulk.py` reports the two
# separately and this echoes the same language `review._apply_approve()`
# already uses for the item-level Missing information refusal.
_SKIP_COPY = {
    bulk.NOT_IN_PROJECT: (
        "This item is no longer part of this project — it may have been deleted "
        "or moved. Refresh the sheet to see its current items."
    ),
    bulk.REJECTED: (
        "This item was rejected, so bulk approval skipped it. Restore it, then approve it on its own."
    ),
    bulk.ALREADY_APPROVED: "A colleague already approved this item.",
    bulk.NEEDS_ATTENTION: (
        "This item needs attention, so bulk approval skipped it. Open it, resolve the "
        "conflicting or uncertain information, then approve it."
    ),
    bulk.MISSING_INFORMATION: (
        "This item is missing information it needs, such as a scale or a legend entry, "
        "so bulk approval skipped it. Resolve the warning on its sheet, then approve it."
    ),
}

# A fifth skip code landing in bulk.py without a matching entry here must
# fail loudly at import/collection time, not as a bare KeyError raised
# after the batch's approvals have already committed (a review finding:
# `_SKIP_COPY[code]` was indexed directly, downstream of `db.commit()`).
# `_skip_message()` below is the runtime guard -- `.get()` with a generic
# fallback, so even if this assertion were bypassed, a request still
# gets a response rather than an unhandled exception after a real write.
assert set(_SKIP_COPY) == bulk.SKIP_CODES, (
    f"_SKIP_COPY is missing copy for: {bulk.SKIP_CODES - set(_SKIP_COPY)}"
)

_GENERIC_SKIP_MESSAGE = "This item was skipped. Refresh the sheet to see its current state."


def _skip_message(code: str) -> str:
    return _SKIP_COPY.get(code, _GENERIC_SKIP_MESSAGE)


def _item_mutation_response(db: DbSession, project_id: uuid.UUID, action, item) -> ItemMutationOut:
    """Shared tail for approve/reject/unreject/edit/delete: compute the
    version once, after the commit, and attach the item's current shape
    -- or `None` for delete, where `item` is passed as `None` because
    there is no longer a row `item_out()` could read.
    """
    version = snapshot_module.version(db, project_id)
    return ItemMutationOut(
        label=action.label,
        version=version,
        item=snapshot_module.item_out(db, item) if item is not None else None,
    )


@router.post("/items/{item_id}/approve", response_model=ItemMutationOut)
def approve(
    item_id: uuid.UUID,
    expected_version: int = Depends(require_expected_version),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    action = review.approve_item(db, user, item, expected_version)
    db.commit()
    return _item_mutation_response(db, project_id, action, item)


@router.post("/items/{item_id}/reject", response_model=ItemMutationOut)
def reject(
    item_id: uuid.UUID,
    expected_version: int = Depends(require_expected_version),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    action = review.reject_item(db, user, item, expected_version)
    db.commit()
    return _item_mutation_response(db, project_id, action, item)


@router.post("/items/{item_id}/unreject", response_model=ItemMutationOut)
def unreject(
    item_id: uuid.UUID,
    expected_version: int = Depends(require_expected_version),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    action = review.unreject_item(db, user, item, expected_version)
    db.commit()
    return _item_mutation_response(db, project_id, action, item)


@router.patch("/items/{item_id}", response_model=ItemMutationOut)
def edit(
    item_id: uuid.UUID,
    body: EditIn,
    expected_version: int = Depends(require_expected_version),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    # Only the fields actually present in the request, explicit null
    # included -- see EditIn's docstring for why `model_fields_set`
    # replaces the sketch's `exclude_none=True`.
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    if not changes:
        # A review finding: review._apply_edit() happily accepts an
        # empty changes dict and writes a real phantom Action (before={},
        # after={}) -- a 200, a permanent append-only log row, a version
        # bump forcing every reviewer to re-fetch, and a no-op step on
        # the shared undo stack. Refused here rather than teaching the
        # service layer about "empty" as a special case.
        raise DomainError(
            "no_changes_to_apply",
            "This edit has no changes. Include at least one field to update, such as quantity or notes.",
        )
    action = review.edit_item(db, user, item, changes, expected_version)
    db.commit()
    return _item_mutation_response(db, project_id, action, item)


@router.delete("/items/{item_id}", response_model=ItemMutationOut)
def delete(
    item_id: uuid.UUID,
    expected_version: int = Depends(require_expected_version),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    action = review.delete_item(db, user, item, expected_version)
    db.commit()
    return _item_mutation_response(db, project_id, action, None)


@router.post("/projects/{project_id}/items/bulk-approve", response_model=BulkApproveOut)
def bulk_approve(
    project_id: uuid.UUID, body: BulkApproveIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)
) -> BulkApproveOut:
    project = load_project(project_id, db, user)
    result = bulk.bulk_approve(db, user, project.id, body.item_ids)
    db.commit()
    version = snapshot_module.version(db, project.id)
    return BulkApproveOut(
        approved=result.approved,
        skipped=[
            SkippedItemOut(item_id=item_id, code=code, message=_skip_message(code))
            for item_id, code in result.skipped.items()
        ],
        snapshot=snapshot_module.build(db, user, project.id, version),
    )


@router.post("/sheets/{sheet_id}/scale", response_model=ScaleMutationOut)
def set_scale(
    sheet_id: uuid.UUID, body: ScaleIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)
) -> ScaleMutationOut:
    sheet = load_sheet(sheet_id, db, user)
    project_id = sheet.project_id
    action = scale_module.set_scale(db, user, sheet, body.value)
    db.commit()
    version = snapshot_module.version(db, project_id)
    return ScaleMutationOut(label=action.label, snapshot=snapshot_module.build(db, user, project_id, version))


@router.post("/projects/{project_id}/takeoff", response_model=TakeoffIngestOut)
def post_takeoff(
    project_id: uuid.UUID,
    payload: TakeoffIngestIn,
    db: DbSession = Depends(get_db),
    user: User = Depends(current_user),
) -> TakeoffIngestOut:
    project = load_project(project_id, db, user)
    result = ingest_takeoff(
        db, actor=user, project=project,
        payload=payload.payload, confirm_replace=payload.confirm_replace,
    )
    db.commit()
    return TakeoffIngestOut(**result)


@router.post("/projects/{project_id}/undo", response_model=UndoRedoOut)
def undo(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> UndoRedoOut:
    project = load_project(project_id, db, user)
    action = undo_module.undo(db, user, project.id)
    db.commit()
    if action is None:
        return UndoRedoOut(performed=False)
    version = snapshot_module.version(db, project.id)
    return UndoRedoOut(
        performed=True, label=action.label, snapshot=snapshot_module.build(db, user, project.id, version)
    )


@router.post("/projects/{project_id}/redo", response_model=UndoRedoOut)
def redo(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> UndoRedoOut:
    project = load_project(project_id, db, user)
    action = undo_module.redo(db, user, project.id)
    db.commit()
    if action is None:
        return UndoRedoOut(performed=False)
    version = snapshot_module.version(db, project.id)
    return UndoRedoOut(
        performed=True, label=action.label, snapshot=snapshot_module.build(db, user, project.id, version)
    )
