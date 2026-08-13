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

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.identity.models import User
from app.takeoff import bulk, review
from app.takeoff import scale as scale_module
from app.takeoff import snapshot as snapshot_module
from app.takeoff import undo as undo_module
from app.takeoff.router import load_item, load_project, load_sheet
from app.takeoff.schemas import BulkApproveOut, ItemMutationOut, ScaleMutationOut, SkippedItemOut, UndoRedoOut

router = APIRouter(prefix="/api", tags=["takeoff-mutations"])


class EditIn(BaseModel):
    """The `PATCH /items/{id}` body.

    All five fields default to `None` so the endpoint can tell "this
    field was not sent" from "this field was sent as null" via
    `model_fields_set`, rather than `body.model_dump(exclude_none=True)`
    (the sketch's approach, correction 2) -- `exclude_none=True` strips
    an explicit `notes: null` before `review._validate_edit()` ever sees
    it, silently turning its "notes cannot be removed entirely" refusal
    into a no-op success. See `edit()` below for where that distinction
    is actually applied.

    `quantity` accepts a JSON *string* only ("184.55"), never a bare JSON
    number (correction 1). `Item.quantity` is `Numeric(12, 2)` and this
    application computes bid totals from it; the validator below refuses
    a float (or int, or bool) before pydantic's own Decimal coercion ever
    runs, rather than trusting that coercion to stay lossless for every
    value a client might send. `review._validate_edit()` still does its
    own `Decimal(str(value))` parsing and `is_finite()`/bounds checks
    downstream -- this validator only keeps a float from ever entering
    the path, it does not replace that validation.
    """

    system: str | None = None
    category: str | None = None
    quantity: Decimal | None = None
    notes: str | None = None
    symbol: str | None = None

    @field_validator("quantity", mode="before")
    @classmethod
    def _quantity_must_be_a_string(cls, value):
        if value is None or isinstance(value, (str, Decimal)):
            return value
        raise ValueError('quantity must be sent as a JSON string, such as "184.55", not a number')


class BulkApproveIn(BaseModel):
    item_ids: list[uuid.UUID]


class ScaleIn(BaseModel):
    value: str


# Estimator-facing copy for bulk.py's four skip codes (correction 4,
# carried forward from Task 8's "skip codes have no estimator-facing copy
# yet; the endpoint task must give each one a recovery action"). Sentence
# case, no "please", no "successfully", no processing internals -- the
# same register every other warning and refusal in this codebase uses.
# `already_approved` names no action because none is needed; the other
# three each say what to do next.
_SKIP_COPY = {
    bulk.NOT_IN_PROJECT: (
        "This item is no longer part of this project — it may have been deleted "
        "or moved. Refresh the sheet to see its current items."
    ),
    bulk.REJECTED: (
        "This item was rejected, so bulk approval skipped it. Restore it, then approve it on its own."
    ),
    bulk.ALREADY_APPROVED: "A colleague already approved this item.",
    bulk.NOT_READY_TO_REVIEW: (
        "This item needs attention or is missing information, so bulk approval skipped it. "
        "Open it, resolve what it is waiting on, then approve it."
    ),
}


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
def approve(item_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    action = review.approve_item(db, user, item)
    db.commit()
    return _item_mutation_response(db, project_id, action, item)


@router.post("/items/{item_id}/reject", response_model=ItemMutationOut)
def reject(item_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    action = review.reject_item(db, user, item)
    db.commit()
    return _item_mutation_response(db, project_id, action, item)


@router.post("/items/{item_id}/unreject", response_model=ItemMutationOut)
def unreject(item_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    action = review.unreject_item(db, user, item)
    db.commit()
    return _item_mutation_response(db, project_id, action, item)


@router.patch("/items/{item_id}", response_model=ItemMutationOut)
def edit(
    item_id: uuid.UUID, body: EditIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)
) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    # Only the fields actually present in the request, explicit null
    # included -- see EditIn's docstring for why `model_fields_set`
    # replaces the sketch's `exclude_none=True`.
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    action = review.edit_item(db, user, item, changes)
    db.commit()
    return _item_mutation_response(db, project_id, action, item)


@router.delete("/items/{item_id}", response_model=ItemMutationOut)
def delete(item_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> ItemMutationOut:
    item = load_item(item_id, db, user)
    project_id = item.project_id
    action = review.delete_item(db, user, item)
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
            SkippedItemOut(item_id=item_id, code=code, message=_SKIP_COPY[code])
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
