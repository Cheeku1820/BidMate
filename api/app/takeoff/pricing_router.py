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
from app.takeoff.pricing import resolve_labor, resolve_material_price
from app.takeoff.router import load_item, load_project, not_found
from app.takeoff.schemas import (
    CompanyLaborHoursOverrideIn,
    CompanyLaborHoursOverrideOut,
    CompanyLaborRatesIn,
    CompanyLaborRatesOut,
    CompanyMaterialPriceIn,
    CompanyMaterialPriceOut,
    LaborLineUpdateIn,
    LaborListOut,
    LaborRowOut,
    MaterialListOut,
    MaterialPriceUpdateIn,
    MaterialRowOut,
)
from app.takeoff.totals import countable_items

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


@router.get("/projects/{project_id}/labor", response_model=LaborListOut)
def get_labor(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    items = list(db.scalars(countable_items(project.id)))
    lines = {row.item_id: row for row in db.scalars(
        select(ProjectLaborLine).where(ProjectLaborLine.item_id.in_([i.id for i in items]))
    )}
    company_rates = db.get(CompanyLaborRate, user.org_id)
    names = {i.name for i in items}
    company_hours = {
        row.item_name: row
        for row in db.scalars(
            select(CompanyLaborHoursOverride).where(
                CompanyLaborHoursOverride.org_id == user.org_id,
                CompanyLaborHoursOverride.item_name.in_(names),
            )
        )
    }

    rows = []
    for item in items:
        resolution = resolve_labor(
            item, project, lines.get(item.id),
            company_rates=company_rates, company_hours=company_hours.get(item.name),
        )
        rows.append(LaborRowOut(
            item_id=item.id, item_name=item.name, quantity=item.quantity,
            hours_per_unit=resolution.hours_per_unit, hours_source_label=resolution.hours_source_label,
            rate=resolution.rate, rate_source_label=resolution.rate_source_label,
            adjusted_hours=resolution.adjusted_hours, labor_cost=resolution.labor_cost,
            status=resolution.status, basis_note=resolution.basis_note,
        ))
    return LaborListOut(pricing_source=project.pricing_source, pricing_note=project.pricing_note, rows=rows)


@router.get("/projects/{project_id}/material-pricing", response_model=MaterialListOut)
def get_material_pricing(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    items = list(db.scalars(countable_items(project.id)))
    overrides = {row.item_id: row for row in db.scalars(
        select(ProjectMaterialPrice).where(ProjectMaterialPrice.item_id.in_([i.id for i in items]))
    )}
    names = {i.name for i in items}
    company_prices = {
        row.item_name: row
        for row in db.scalars(
            select(CompanyMaterialPrice).where(
                CompanyMaterialPrice.org_id == user.org_id,
                CompanyMaterialPrice.item_name.in_(names),
            )
        )
    }

    rows = []
    for item in items:
        resolution = resolve_material_price(item, project, overrides.get(item.id), company_prices.get(item.name))
        rows.append(MaterialRowOut(
            item_id=item.id, item_name=item.name, quantity=item.quantity,
            unit_price=resolution.unit_price, source_label=resolution.source_label,
            status=resolution.status, basis_note=resolution.basis_note,
        ))
    return MaterialListOut(pricing_source=project.pricing_source, pricing_note=project.pricing_note, rows=rows)


@router.get("/company/labor-rates", response_model=CompanyLaborRatesOut)
def get_company_labor_rates(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.get(CompanyLaborRate, user.org_id)
    if row is None:
        return CompanyLaborRatesOut(journeyman_rate=0, foreman_rate=0, apprentice_rate=0, productivity_factor=1)
    return row


@router.put("/company/labor-rates", response_model=CompanyLaborRatesOut)
def put_company_labor_rates(body: CompanyLaborRatesIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.get(CompanyLaborRate, user.org_id)
    if row is None:
        row = CompanyLaborRate(org_id=user.org_id)
        db.add(row)
    row.journeyman_rate = body.journeyman_rate
    row.foreman_rate = body.foreman_rate
    row.apprentice_rate = body.apprentice_rate
    row.productivity_factor = body.productivity_factor
    row.updated_by_user_id = user.id
    db.commit()
    db.refresh(row)
    return row


@router.get("/company/material-prices", response_model=list[CompanyMaterialPriceOut])
def get_company_material_prices(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return list(db.scalars(select(CompanyMaterialPrice).where(CompanyMaterialPrice.org_id == user.org_id)))


@router.put("/company/material-prices/{item_name}", response_model=CompanyMaterialPriceOut)
def put_company_material_price(item_name: str, body: CompanyMaterialPriceIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyMaterialPrice).where(
        CompanyMaterialPrice.org_id == user.org_id, CompanyMaterialPrice.item_name == item_name,
    )).one_or_none()
    if row is None:
        row = CompanyMaterialPrice(org_id=user.org_id, item_name=item_name, unit_price=body.unit_price, effective_date=body.effective_date)
        db.add(row)
    else:
        row.unit_price = body.unit_price
        row.effective_date = body.effective_date
    row.updated_by_user_id = user.id
    db.commit()
    db.refresh(row)
    return row


@router.delete("/company/material-prices/{item_name}", status_code=204)
def delete_company_material_price(item_name: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyMaterialPrice).where(
        CompanyMaterialPrice.org_id == user.org_id, CompanyMaterialPrice.item_name == item_name,
    )).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()


@router.get("/company/labor-hours-overrides", response_model=list[CompanyLaborHoursOverrideOut])
def get_company_labor_hours_overrides(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return list(db.scalars(select(CompanyLaborHoursOverride).where(CompanyLaborHoursOverride.org_id == user.org_id)))


@router.put("/company/labor-hours-overrides/{item_name}", response_model=CompanyLaborHoursOverrideOut)
def put_company_labor_hours_override(item_name: str, body: CompanyLaborHoursOverrideIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyLaborHoursOverride).where(
        CompanyLaborHoursOverride.org_id == user.org_id, CompanyLaborHoursOverride.item_name == item_name,
    )).one_or_none()
    if row is None:
        row = CompanyLaborHoursOverride(org_id=user.org_id, item_name=item_name, hours_per_unit=body.hours_per_unit)
        db.add(row)
    else:
        row.hours_per_unit = body.hours_per_unit
    row.updated_by_user_id = user.id
    db.commit()
    db.refresh(row)
    return row


@router.delete("/company/labor-hours-overrides/{item_name}", status_code=204)
def delete_company_labor_hours_override(item_name: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyLaborHoursOverride).where(
        CompanyLaborHoursOverride.org_id == user.org_id, CompanyLaborHoursOverride.item_name == item_name,
    )).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()
