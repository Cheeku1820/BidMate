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
