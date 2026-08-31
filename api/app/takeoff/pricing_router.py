"""pricing_router.py -- Labor and Material Pricing (labor-material-pricing
plan). Split from mutations.py rather than added to it, the same reason
mutations.py was split from router.py: this adds a real block of new
endpoints and mutations.py is already at this project's file-size
convention.
"""
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.errors import DomainError
from app.identity.models import User
from app.takeoff import actions
from app.takeoff.actions import encode_snapshot
from app.takeoff.models import (
    CompanyLaborHoursOverride,
    CompanyLaborRate,
    CompanyMaterialPrice,
    Item,
    ProjectLaborLine,
    ProjectMaterialPrice,
)
from app.takeoff.router import load_item, load_project, not_found
from app.takeoff.schemas import LaborLineUpdateIn, MaterialPriceUpdateIn

router = APIRouter(prefix="/api", tags=["pricing"])


def _snapshot(model_cls, pk_value, db: DbSession) -> dict | None:
    """A JSON-safe column snapshot for actions.commit()'s before/after.
    encode_snapshot() is required here, not optional -- both
    ProjectLaborLine and ProjectMaterialPrice carry Decimal, UUID, and
    datetime columns (hours_override, item_id, updated_at, ...), none of
    which json.dumps can serialize directly. This mirrors
    review._apply_edit()'s own `encode_snapshot(_column_snapshot(item))`
    call for the same reason."""
    row = db.get(model_cls, pk_value)
    if row is None:
        return None
    mapper = row.__class__.__mapper__
    raw = {attr.key: getattr(row, attr.key) for attr in mapper.column_attrs}
    return encode_snapshot(raw)


@router.patch("/items/{item_id}/labor")
def patch_labor(
    item_id: uuid.UUID,
    body: LaborLineUpdateIn,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    item = load_item(item_id, db, user)
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    if not changes:
        raise DomainError(
            "no_changes_to_apply",
            "This update has no changes. Include at least one field, such as hours or a crew count.",
        )

    before = _snapshot(ProjectLaborLine, item_id, db)
    row = db.get(ProjectLaborLine, item_id)
    if row is None:
        row = ProjectLaborLine(item_id=item_id)
        db.add(row)
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by_user_id = user.id
    db.flush()
    after = _snapshot(ProjectLaborLine, item_id, db)

    actions.commit(
        db, actor=user, project_id=item.project_id, kind="labor_edit",
        label=f"Updated labor for {item.name}", item_id=item_id,
        before=before or {}, after=after,
    )
    db.commit()
    return {"itemId": str(item_id)}


@router.patch("/items/{item_id}/material-price")
def patch_material_price(
    item_id: uuid.UUID,
    body: MaterialPriceUpdateIn,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    item = load_item(item_id, db, user)

    before = _snapshot(ProjectMaterialPrice, item_id, db)
    row = db.get(ProjectMaterialPrice, item_id)
    if row is None:
        row = ProjectMaterialPrice(item_id=item_id, price_override=body.price_override, source=body.source)
        db.add(row)
    else:
        row.price_override = body.price_override
        row.source = body.source
    row.reason = body.reason
    row.updated_by_user_id = user.id
    db.flush()
    after = _snapshot(ProjectMaterialPrice, item_id, db)

    actions.commit(
        db, actor=user, project_id=item.project_id, kind="material_price_edit",
        label=f"Updated material price for {item.name}", item_id=item_id,
        before=before or {}, after=after,
    )
    db.commit()
    return {"itemId": str(item_id)}
