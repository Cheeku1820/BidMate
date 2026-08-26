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

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.engine import estimate as estimate_mod
from app.engine import llm

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
    review workflow (the frontend injects this into its store)."""
    return await _run(file, location, estimate_mod.full_takeoff)


@app.get("/sheet-image")
def sheet_image_endpoint():
    """Placeholder for Section 6 (rendered sheet PNG for the canvas).
    Wired later so the frontend contract is stable."""
    return JSONResponse(status_code=501, content={"error": "not implemented yet"})
