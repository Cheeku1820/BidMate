"""pricing_router.py -- Labor and Material Pricing (labor-material-pricing
plan). Split from mutations.py rather than added to it, the same reason
mutations.py was split from router.py: this adds a real block of new
endpoints and mutations.py is already at this project's file-size
convention.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.documents import service as doc_service
from app.documents.blobstore import get_blob_store
from app.errors import DomainError
from app.identity.models import User
from app.jobs import queue
from app.market.copy import warning_for
from app.market.price_sheet import build_request_workbook
from app.takeoff import actions
from app.takeoff.actions import encode_snapshot
from app.takeoff.models import (
    CompanyAction,
    CompanyLaborHoursOverride,
    CompanyLaborRate,
    CompanyMaterialPrice,
    Document,
    ItemMarketPrice,
    Job,
    MarketLookup,
    Project,
    ProjectLaborLine,
    ProjectMaterialPrice,
    Sheet,
)
from app.takeoff.pricing import resolve_labor, resolve_material_price
from app.takeoff.router import load_item, load_project
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
    PriceSheetApplyIn,
    PriceSheetPreviewOut,
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


def record_company_action(db: DbSession, *, actor: User, kind: str, label: str, before: dict, after: dict) -> CompanyAction:
    """Append one row to the org-level audit log for a company pricing
    edit. Deliberately not `actions.commit()` -- that table is
    project-scoped and doubles as the undo stack; a company edit belongs
    to neither. See `CompanyAction`'s docstring for the full reasoning.

    `before`/`after` are expected already JSON-safe -- callers here build
    them with `_snapshot()`, which applies `encode_snapshot()` itself, so
    this does not encode a second time."""
    action = CompanyAction(
        org_id=actor.org_id,
        actor_user_id=actor.id,
        kind=kind,
        label=label,
        before=before,
        after=after,
    )
    db.add(action)
    return action


def _labor_row_out(item, resolution, line) -> LaborRowOut:
    """One place a labor row is shaped, for the list route and the PATCH
    route both -- the grid patches a single row from the PATCH response,
    so the two must never drift."""
    return LaborRowOut(
        item_id=item.id, item_name=item.name, quantity=item.quantity,
        hours_per_unit=resolution.hours_per_unit, hours_source_label=resolution.hours_source_label,
        rate=resolution.rate, rate_source_label=resolution.rate_source_label,
        adjusted_hours=resolution.adjusted_hours, labor_cost=resolution.labor_cost,
        adjustment_percent=line.adjustment_percent if line is not None else None,
        adjustment_reason=line.adjustment_reason if line is not None else "",
        status=resolution.status, basis_note=resolution.basis_note,
    )


def labor_row_for(item, project, db: DbSession, user: User) -> LaborRowOut:
    """The resolved labor row for one item, read fresh after a write."""
    line = db.get(ProjectLaborLine, item.id)
    company_rates = db.get(CompanyLaborRate, user.org_id)
    company_hours = db.scalars(
        select(CompanyLaborHoursOverride).where(
            CompanyLaborHoursOverride.org_id == user.org_id,
            CompanyLaborHoursOverride.item_name == item.name,
        )
    ).one_or_none()
    resolution = resolve_labor(item, project, line, company_rates=company_rates, company_hours=company_hours)
    return _labor_row_out(item, resolution, line)


def _evidence(market: ItemMarketPrice | None, lookup: MarketLookup | None) -> list[dict]:
    """The seller/catalog evidence behind a priced market estimate. No
    vendor name on the row otherwise -- this is the one place sellers
    surface, and only once the outcome is "priced"."""
    if market is None or lookup is None or market.outcome != "priced":
        return []
    r = lookup.result or {}
    if market.source == "shopping":
        return [{"seller": s.get("seller", ""), "price": s.get("price"), "link": s.get("link")} for s in r.get("sellers") or []]
    m = r.get("matched") or {}
    return [{"name": m.get("name", ""), "uom": m.get("uom", "")}] if m else []


def _material_row_out(item, resolution, override, market=None, lookup=None, sheet_number="") -> MaterialRowOut:
    warning = None
    if resolution.status == "missing" and market is not None:
        warning = warning_for(market.outcome, query=market.query, sheet_number=sheet_number, description=item.description or "")
    return MaterialRowOut(
        item_id=item.id, item_name=item.name, quantity=item.quantity,
        unit_price=resolution.unit_price,
        source=override.source if override is not None else None,
        source_label=resolution.source_label,
        reason=override.reason if override is not None else "",
        status=resolution.status, basis_note=resolution.basis_note,
        price_low=resolution.price_low, price_high=resolution.price_high,
        market_outcome=resolution.market_outcome, market_warning=warning,
        market_evidence=_evidence(market, lookup),
        fetched_at=market.fetched_at if market is not None else None,
        supplier_name=override.supplier_name if override is not None else "",
        quote_date=override.quote_date if override is not None else None,
    )


def material_row_for(item, project, db: DbSession, user: User) -> MaterialRowOut:
    """The resolved material row for one item, read fresh after a write."""
    override = db.get(ProjectMaterialPrice, item.id)
    company_price = db.scalars(
        select(CompanyMaterialPrice).where(
            CompanyMaterialPrice.org_id == user.org_id,
            CompanyMaterialPrice.item_name == item.name,
        )
    ).one_or_none()
    market = db.get(ItemMarketPrice, item.id)
    lookup = db.get(MarketLookup, market.lookup_id) if market and market.lookup_id else None
    sheet = db.get(Sheet, item.sheet_id)
    resolution = resolve_material_price(item, project, override, company_price, market=market)
    return _material_row_out(item, resolution, override, market, lookup, sheet.number if sheet else "")


@router.patch("/items/{item_id}/labor", response_model=LaborRowOut)
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

    # These two columns are NOT NULL with a "" default. The schema types
    # them optional so they can be omitted, but a caller sending an
    # explicit null means "clear it," and the empty string is what
    # clearing looks like in this table -- an IntegrityError on flush is
    # not.
    for key in ("adjustment_reason", "notes"):
        if key in changes and changes[key] is None:
            changes[key] = ""

    before = _snapshot(ProjectLaborLine, item_id, db)
    row = db.get(ProjectLaborLine, item_id)
    if row is None:
        row = ProjectLaborLine(item_id=item_id)
        db.add(row)
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by_user_id = user.id
    db.flush()
    db.refresh(row)  # normalize Numeric precision before snapshotting -- see put_company_labor_rates
    after = _snapshot(ProjectLaborLine, item_id, db)

    actions.commit(
        db, actor=user, project_id=item.project_id, kind="labor_edit",
        label=f"Updated labor for {item.name}", item_id=item_id,
        before=before or {}, after=after,
    )
    db.commit()
    project = db.get(Project, item.project_id)
    return labor_row_for(item, project, db, user)


@router.patch("/items/{item_id}/material-price", response_model=MaterialRowOut)
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
    db.refresh(row)  # normalize Numeric precision before snapshotting -- see put_company_labor_rates
    after = _snapshot(ProjectMaterialPrice, item_id, db)

    actions.commit(
        db, actor=user, project_id=item.project_id, kind="material_price_edit",
        label=f"Updated material price for {item.name}", item_id=item_id,
        before=before or {}, after=after,
    )
    db.commit()
    project = db.get(Project, item.project_id)
    return material_row_for(item, project, db, user)


@router.delete("/items/{item_id}/material-price", response_model=MaterialRowOut)
def delete_material_price(
    item_id: uuid.UUID,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Clear the estimator's price entry so the row falls back to the
    company price, the regional baseline, or Missing information.

    Returns the fallen-back row rather than 204: the grid renders it and
    words the toast from its new source label. Recorded as
    material_price_edit with an empty `after` -- undo_apply's
    _apply_sparse_pricing_row already reads an empty state as "this row
    should not exist", so undo and redo of a clear need nothing new."""
    item = load_item(item_id, db, user)
    row = db.get(ProjectMaterialPrice, item_id)
    if row is None:
        raise DomainError("no_material_price_to_clear", "This item has no price entry to clear.", status=404)
    before = _snapshot(ProjectMaterialPrice, item_id, db)
    db.delete(row)
    db.flush()
    actions.commit(
        db, actor=user, project_id=item.project_id, kind="material_price_edit",
        label=f"Cleared material price for {item.name}", item_id=item_id,
        before=before, after={},
    )
    db.commit()
    project = db.get(Project, item.project_id)
    return material_row_for(item, project, db, user)


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
        rows.append(_labor_row_out(item, resolution, lines.get(item.id)))
    return LaborListOut(pricing_source=project.pricing_source, pricing_note=project.pricing_note, rows=rows)


@router.get("/projects/{project_id}/material-pricing", response_model=MaterialListOut)
def get_material_pricing(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    items = list(db.scalars(countable_items(project.id)))
    ids = [i.id for i in items]
    overrides = {row.item_id: row for row in db.scalars(
        select(ProjectMaterialPrice).where(ProjectMaterialPrice.item_id.in_(ids))
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
    markets = {m.item_id: m for m in db.scalars(select(ItemMarketPrice).where(ItemMarketPrice.item_id.in_(ids)))}
    lookup_ids = {m.lookup_id for m in markets.values() if m.lookup_id}
    lookups = {l.id: l for l in db.scalars(select(MarketLookup).where(MarketLookup.id.in_(lookup_ids)))}
    sheet_numbers = {s.id: s.number for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id))}

    rows = []
    for item in items:
        override = overrides.get(item.id)
        market = markets.get(item.id)
        lookup = lookups.get(market.lookup_id) if market is not None and market.lookup_id else None
        resolution = resolve_material_price(item, project, override, company_prices.get(item.name), market=market)
        rows.append(_material_row_out(
            item, resolution, override, market, lookup, sheet_numbers.get(item.sheet_id, "")
        ))
    job = db.scalars(select(Job).where(Job.kind == "price", Job.project_id == project.id,
                                       Job.status.in_(("queued", "running")))).first()
    return MaterialListOut(pricing_source=project.pricing_source, pricing_note=project.pricing_note, rows=rows,
                           market_job=job.status if job is not None else None)


@router.get("/projects/{project_id}/material-pricing/price-request")
def get_price_request(project_id: uuid.UUID, only: str | None = None,
                      user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    rows = get_material_pricing(project_id, user, db).rows   # the resolved rows, so `only=missing` uses the real status
    if only == "missing":
        rows = [r for r in rows if r.status == "missing"]
    items = {i.id: i for i in db.scalars(countable_items(project.id))}
    data = build_request_workbook([{"item_id": r.item_id, "item_name": r.item_name,
                                    "description": items[r.item_id].description, "quantity": float(r.quantity),
                                    "unit": items[r.item_id].unit} for r in rows])
    name = f"{project.name} - price request - {date.today():%Y-%m-%d}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/projects/{project_id}/material-pricing/price-sheets", status_code=202)
def post_price_sheet(project_id: uuid.UUID, file: UploadFile = File(...),
                     user: User = Depends(current_user), db: DbSession = Depends(get_db), store=Depends(get_blob_store)):
    project = load_project(project_id, db, user)
    document = doc_service.store_upload(db, actor=user, project=project, upload=file, doc_type="Pricing", store=store)
    queue.enqueue_price_sheet(db, document, user.id)
    db.commit()
    return {"document_id": str(document.id)}


def _preview_job(db, project, document_id) -> tuple[Document, Job | None]:
    document = db.get(Document, document_id)
    if document is None or document.project_id != project.id or document.doc_type != "Pricing":
        raise DomainError("price_sheet_not_found", "That price sheet isn't on this project.", status=404)
    job = db.scalars(select(Job).where(Job.kind == "price_sheet", Job.document_id == document.id)
                     .order_by(Job.queued_at.desc())).first()
    return document, job


@router.get("/projects/{project_id}/material-pricing/price-sheets/{document_id}/preview", response_model=PriceSheetPreviewOut)
def get_price_sheet_preview(project_id: uuid.UUID, document_id: uuid.UUID,
                            user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    project = load_project(project_id, db, user)
    _, job = _preview_job(db, project, document_id)
    if job is None or job.status in ("queued", "running"):
        return PriceSheetPreviewOut(state="reading")
    if job.status == "failed":
        return PriceSheetPreviewOut(state="failed", error=job.error)
    return PriceSheetPreviewOut(state="ready", **(job.payload or {}).get("preview", {}))


@router.post("/projects/{project_id}/material-pricing/price-sheets/{document_id}/apply", response_model=MaterialListOut)
def apply_price_sheet(project_id: uuid.UUID, document_id: uuid.UUID, body: PriceSheetApplyIn,
                      user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """One commit() for every ticked row (estimate-first-pricing §6).
    `before`/`after` carry a snapshot per item ({} = no row), which is
    what undo_apply replays row by row."""
    project = load_project(project_id, db, user)
    _, job = _preview_job(db, project, document_id)
    preview = ((job.payload if job else None) or {}).get("preview") or {}
    by_id = {m["item_id"]: m for m in preview.get("matched", [])}
    wanted = [str(i) for i in body.item_ids]
    if not wanted or any(i not in by_id for i in wanted):
        raise DomainError("price_sheet_rows", "Choose rows from the price sheet preview to apply.", status=422)
    before, after = {}, {}
    for item_id in wanted:
        iid = uuid.UUID(item_id)
        item = load_item(iid, db, user)
        before[item_id] = _snapshot(ProjectMaterialPrice, iid, db) or {}
        row = db.get(ProjectMaterialPrice, iid) or ProjectMaterialPrice(item_id=iid, price_override=0, source="supplier_quote")
        row.price_override = Decimal(by_id[item_id]["new_unit_price"])
        row.source, row.reason = "supplier_quote", ""
        row.supplier_name, row.quote_date, row.updated_by_user_id = body.supplier_name, body.quote_date, user.id
        db.add(row)
        db.flush(); db.refresh(row)
        after[item_id] = _snapshot(ProjectMaterialPrice, iid, db)
        if body.save_to_company:
            existing = db.scalars(select(CompanyMaterialPrice).where(
                CompanyMaterialPrice.org_id == user.org_id, CompanyMaterialPrice.item_name == item.name)).one_or_none()
            if existing is None:
                cp = CompanyMaterialPrice(org_id=user.org_id, item_name=item.name, unit_price=row.price_override,
                                          effective_date=body.quote_date, updated_by_user_id=user.id)
                db.add(cp); db.flush(); db.refresh(cp)
                record_company_action(db, actor=user, kind="company_material_price_edit",
                                      label=f"Added company price for {item.name} from {body.supplier_name}",
                                      before={}, after=_snapshot(CompanyMaterialPrice, cp.id, db))
    n = len(wanted)
    actions.commit(db, actor=user, project_id=project.id, kind="supplier_quote_apply",
                   label=f"Applied supplier pricing from {body.supplier_name} for {n} item{'' if n == 1 else 's'}",
                   before={"rows": before}, after={"rows": after})
    db.commit()
    return get_material_pricing(project_id, user, db)


@router.post("/projects/{project_id}/market-pricing/refresh", status_code=202)
def refresh_market_pricing(project_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Queue a price job. Not a mutation of anything an estimator owns,
    so not through commit(); the job writes only item_market_prices."""
    project = load_project(project_id, db, user)
    job = queue.enqueue_price(db, project, user.id)
    db.commit()
    return {"queued": job is not None}


@router.get("/company/market-pricing/usage")
def get_market_usage(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    from datetime import datetime, timezone

    from sqlalchemy import func

    from app.config import settings

    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(MarketLookup).where(
        MarketLookup.org_id == user.org_id, MarketLookup.billed.is_(True), MarketLookup.fetched_at >= start)) or 0
    return {"used": used, "cap": settings.market_lookup_monthly_cap}


@router.get("/company/labor-rates", response_model=CompanyLaborRatesOut)
def get_company_labor_rates(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.get(CompanyLaborRate, user.org_id)
    if row is None:
        return CompanyLaborRatesOut(journeyman_rate=0, foreman_rate=0, apprentice_rate=0, productivity_factor=1)
    return row


@router.put("/company/labor-rates", response_model=CompanyLaborRatesOut)
def put_company_labor_rates(body: CompanyLaborRatesIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    before = _snapshot(CompanyLaborRate, user.org_id, db)
    row = db.get(CompanyLaborRate, user.org_id)
    if row is None:
        row = CompanyLaborRate(org_id=user.org_id)
        db.add(row)
    row.journeyman_rate = body.journeyman_rate
    row.foreman_rate = body.foreman_rate
    row.apprentice_rate = body.apprentice_rate
    row.productivity_factor = body.productivity_factor
    row.updated_by_user_id = user.id
    db.flush()
    # Postgres normalizes the Numeric columns to their column scale (72 ->
    # 72.00); the in-memory attribute still holds whatever precision the
    # request body carried until the row is refreshed. Without this, the
    # "after" snapshot would record "72" for a rate the row actually
    # stores as "72.00" -- a cosmetic mismatch in a table whose whole job
    # is being an exact record.
    db.refresh(row)
    after = _snapshot(CompanyLaborRate, user.org_id, db)

    record_company_action(
        db, actor=user, kind="company_labor_rates_edit",
        label="Changed labor rates", before=before or {}, after=after,
    )
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
    before = _snapshot(CompanyMaterialPrice, row.id, db) if row is not None else None
    if row is None:
        row = CompanyMaterialPrice(org_id=user.org_id, item_name=item_name, unit_price=body.unit_price, effective_date=body.effective_date)
        db.add(row)
    else:
        row.unit_price = body.unit_price
        row.effective_date = body.effective_date
    row.updated_by_user_id = user.id
    db.flush()
    db.refresh(row)  # normalize Numeric precision before snapshotting -- see put_company_labor_rates
    after = _snapshot(CompanyMaterialPrice, row.id, db)

    record_company_action(
        db, actor=user, kind="company_material_price_edit",
        label=f"Changed the material price for {item_name}", before=before or {}, after=after,
    )
    db.commit()
    db.refresh(row)
    return row


@router.delete("/company/material-prices/{item_name}", status_code=204)
def delete_company_material_price(item_name: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyMaterialPrice).where(
        CompanyMaterialPrice.org_id == user.org_id, CompanyMaterialPrice.item_name == item_name,
    )).one_or_none()
    if row is not None:
        before = _snapshot(CompanyMaterialPrice, row.id, db)
        db.delete(row)
        db.flush()
        record_company_action(
            db, actor=user, kind="company_material_price_delete",
            label=f"Removed the material price for {item_name}", before=before or {}, after={},
        )
        db.commit()


@router.get("/company/labor-hours-overrides", response_model=list[CompanyLaborHoursOverrideOut])
def get_company_labor_hours_overrides(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return list(db.scalars(select(CompanyLaborHoursOverride).where(CompanyLaborHoursOverride.org_id == user.org_id)))


@router.put("/company/labor-hours-overrides/{item_name}", response_model=CompanyLaborHoursOverrideOut)
def put_company_labor_hours_override(item_name: str, body: CompanyLaborHoursOverrideIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyLaborHoursOverride).where(
        CompanyLaborHoursOverride.org_id == user.org_id, CompanyLaborHoursOverride.item_name == item_name,
    )).one_or_none()
    before = _snapshot(CompanyLaborHoursOverride, row.id, db) if row is not None else None
    if row is None:
        row = CompanyLaborHoursOverride(org_id=user.org_id, item_name=item_name, hours_per_unit=body.hours_per_unit)
        db.add(row)
    else:
        row.hours_per_unit = body.hours_per_unit
    row.updated_by_user_id = user.id
    db.flush()
    db.refresh(row)  # normalize Numeric precision before snapshotting -- see put_company_labor_rates
    after = _snapshot(CompanyLaborHoursOverride, row.id, db)

    record_company_action(
        db, actor=user, kind="company_labor_hours_override_edit",
        label=f"Changed the labor hours override for {item_name}", before=before or {}, after=after,
    )
    db.commit()
    db.refresh(row)
    return row


@router.delete("/company/labor-hours-overrides/{item_name}", status_code=204)
def delete_company_labor_hours_override(item_name: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    row = db.scalars(select(CompanyLaborHoursOverride).where(
        CompanyLaborHoursOverride.org_id == user.org_id, CompanyLaborHoursOverride.item_name == item_name,
    )).one_or_none()
    if row is not None:
        before = _snapshot(CompanyLaborHoursOverride, row.id, db)
        db.delete(row)
        db.flush()
        record_company_action(
            db, actor=user, kind="company_labor_hours_override_delete",
            label=f"Removed the labor hours override for {item_name}", before=before or {}, after={},
        )
        db.commit()
