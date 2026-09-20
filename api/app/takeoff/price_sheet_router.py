"""price_sheet_router.py -- the supplier price-sheet round trip: the
price-request workbook download, the upload that queues a `price_sheet`
job, its preview, and applying ticked rows as one undoable action
(estimate-first-pricing §6).

Split out of `pricing_router.py` rather than added to it, for the same
reason `pricing_router.py` itself was split from `mutations.py`: that
file's own docstring already cites the project's file-size convention,
and this task's four routes plus their helper pushed it well past it.
Shares `_snapshot`, `record_company_action`, and `get_material_pricing`
from `pricing_router` rather than duplicating them -- all three are
already the single place each of those concerns lives."""
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
from app.documents.router import _content_disposition
from app.errors import DomainError
from app.identity.models import User
from app.jobs import queue
from app.market.price_sheet import build_request_workbook
from app.takeoff import actions
from app.takeoff.models import CompanyMaterialPrice, Document, Job, ProjectMaterialPrice
from app.takeoff.pricing_router import _snapshot, get_material_pricing, record_company_action
from app.takeoff.router import load_item, load_project
from app.takeoff.schemas import MaterialListOut, PriceSheetApplyIn, PriceSheetPreviewOut
from app.takeoff.totals import countable_items

router = APIRouter(prefix="/api", tags=["pricing"])


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
    # The project name is estimator-supplied text, not a trusted literal --
    # a quote in it would split this header, and a non-latin-1 character
    # would make Starlette raise encoding it. _content_disposition() (the
    # same one document downloads use) percent-encodes the real name into
    # filename*= and ships an ASCII-safe fallback in filename=, so neither
    # can happen.
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": _content_disposition(name)})


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
