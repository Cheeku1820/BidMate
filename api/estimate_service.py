"""Standalone estimate service for the demo.

A lightweight FastAPI app (no database, no auth) that accepts a drawing
PDF plus a project location and returns a priced Division 26 takeoff, run
through app.engine. Deliberately separate from the main API so the demo
needs no Postgres.

    cd api
    ANTHROPIC_API_KEY=sk-... uvicorn estimate_service:app --port 8100

The frontend's Estimate page posts to POST /estimate. Without a key it
still works, using the deterministic classifier and regional pricing.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections import OrderedDict

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.engine import documents as documents_mod
from app.engine import estimate as estimate_mod
from app.engine import llm

# Keeps the source PDF bytes for the last few takeoffs, so the canvas can
# fetch one sheet image at a time (GET /sheet-image) without the whole
# set living in the browser's localStorage. Capped so memory stays bounded.
_PDF_STORE: "OrderedDict[str, bytes]" = OrderedDict()
_PDF_STORE_CAP = 6


def _remember_pdf(data: bytes) -> str:
    takeoff_id = uuid.uuid4().hex
    _PDF_STORE[takeoff_id] = data
    while len(_PDF_STORE) > _PDF_STORE_CAP:
        _PDF_STORE.popitem(last=False)
    return takeoff_id

app = FastAPI(title="Takeoff estimate service")

# Local demo: the Vite dev server (5173/5199) calls this directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "llm_pricing": llm.available()}


async def _run(file: UploadFile, location: str, fn):
    if not (file.filename or "").lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "Upload a PDF drawing set."})
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        result = fn(path, location)
        result["filename"] = file.filename
        return result
    except Exception as exc:  # noqa: BLE001 -- surface a clean error to the UI
        return JSONResponse(status_code=500, content={"error": f"Couldn't read the drawings: {type(exc).__name__}."})
    finally:
        os.unlink(path)


@app.post("/estimate")
async def estimate_endpoint(file: UploadFile = File(...), location: str = Form("")):
    """Consolidated estimate (one row per catalog item) for the Instant estimate page."""
    return await _run(file, location, estimate_mod.estimate)


@app.post("/estimate/full")
async def estimate_full_endpoint(file: UploadFile = File(...), location: str = Form("")):
    """Per-sheet takeoff with coordinates and page dimensions, for the full
    review workflow. Also keeps the PDF bytes so the canvas can fetch sheet
    images (the returned takeoff_id addresses them)."""
    if not (file.filename or "").lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "Upload a PDF drawing set."})
    data = await file.read()
    takeoff_id = _remember_pdf(data)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        result = estimate_mod.full_takeoff(path, location)
        result["filename"] = file.filename
        result["takeoff_id"] = takeoff_id
        return result
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": f"Couldn't read the drawings: {type(exc).__name__}."})
    finally:
        os.unlink(path)


def _totals(items: list[dict]) -> dict:
    s = lambda f: round(sum(i.get(f, 0) or 0 for i in items), 2)  # noqa: E731
    material, labor = s("material_cost"), s("labor_cost")
    return {
        "material": material,
        "labor_hours": s("labor_hours"),
        "labor_cost": labor,
        "total_direct_cost": round(material + labor, 2),
        "item_count": len(items),
        "attention_count": sum(1 for i in items if i.get("status") == "attention"),
    }


@app.post("/estimate/project")
async def estimate_project_endpoint(
    files: list[UploadFile] = File(...),
    types: list[str] = Form(...),
    location: str = Form(""),
):
    """Process the whole document set: every Drawings PDF goes through the
    engine (merged), and every other document (specs, addenda, scope) has
    its electrical-relevant text extracted as context so the classifier can
    read schedules that live outside the drawings. Each sheet keeps its own
    takeoff_id, so the canvas fetches the right page image per drawing."""
    drawings: list[tuple[str, str, str]] = []  # (takeoff_id, temp_path, filename)
    context_parts: list[str] = []
    try:
        for f, t in zip(files, types):
            data = await f.read()
            name = (f.filename or "").lower()
            if not name.endswith(".pdf"):
                continue
            if t == "Drawings":
                takeoff_id = _remember_pdf(data)
                fd, path = tempfile.mkstemp(suffix=".pdf")
                with os.fdopen(fd, "wb") as tmp:
                    tmp.write(data)
                drawings.append((takeoff_id, path, f.filename))
            else:
                try:
                    text = documents_mod.extract_context(data)
                    if text:
                        context_parts.append(f"[{f.filename}]\n{text}")
                except Exception:  # noqa: BLE001 -- a doc we can't read is just skipped
                    pass

        if not drawings:
            return JSONResponse(status_code=400, content={"error": "Include at least one file typed Drawings."})

        context = "\n\n".join(context_parts)[:12000]

        merged_sheets: list[dict] = []
        merged_items: list[dict] = []
        meta: dict | None = None
        for takeoff_id, path, _fname in drawings:
            payload = estimate_mod.full_takeoff(path, location, context)
            if meta is None:
                meta = {k: payload[k] for k in ("location", "location_note", "labor_rate", "material_factor", "source")}
            for sheet in payload["sheets"]:
                merged_sheets.append({**sheet, "id": f"{takeoff_id}:{sheet['id']}", "takeoff_id": takeoff_id})
            for item in payload["items"]:
                merged_items.append({**item, "sheet_id": f"{takeoff_id}:{item['sheet_id']}"})

        return {
            **(meta or {"location": location, "labor_rate": 78.0, "material_factor": 1.0, "source": "deterministic", "location_note": ""}),
            "sheets": merged_sheets,
            "items": merged_items,
            "totals": _totals(merged_items),
            "document_count": len(files),
            "context_documents": len(context_parts),
        }
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": f"Couldn't process the documents: {type(exc).__name__}."})
    finally:
        for _tid, path, _f in drawings:
            try:
                os.unlink(path)
            except OSError:
                pass


@app.get("/sheet-image")
def sheet_image_endpoint(takeoff_id: str, page: int):
    """Rendered PNG of one sheet (1-based page), for the canvas background."""
    data = _PDF_STORE.get(takeoff_id)
    if data is None:
        return JSONResponse(status_code=404, content={"error": "takeoff not found — reprocess the drawings"})
    try:
        png = documents_mod.render_page_png_bytes(data, page - 1)
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": "couldn't render that page"})
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})
