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

import asyncio
import json
import os
import re
import tempfile
import uuid

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.engine import documents as documents_mod
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


@app.post("/classify")
async def classify_endpoint(file: UploadFile = File(...)):
    """Peek at a document's first pages and guess its type from the
    content, for the upload screen to refine a file whose name didn't say.
    Returns {"type": <DOC_TYPE or null>} -- null means "no strong signal,
    keep your filename guess"."""
    try:
        data = await file.read()
        text = documents_mod.first_pages_text(data)
        return {"type": documents_mod.classify_content(text)}
    except Exception:  # noqa: BLE001 -- best-effort; the client falls back to the filename
        return {"type": None}


@app.post("/estimate/full")
async def estimate_full_endpoint(file: UploadFile = File(...), location: str = Form("")):
    """Per-sheet takeoff with coordinates and page dimensions, for the full
    review workflow."""
    if not (file.filename or "").lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "Upload a PDF drawing set."})
    data = await file.read()
    takeoff_id = uuid.uuid4().hex
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


def _render_and_read(pdf_bytes: bytes, page: int, number: str) -> dict:
    png = documents_mod.render_vision_png_bytes(pdf_bytes, page - 1)
    return llm.read_sheet_image(png, number)


_TAG_IN_NAME = re.compile(r"\btype\s+([A-Z]\d?)\b|\(([A-Z]{1,2}\d?)\)", re.I)


def _tag_of(device_name: str) -> str | None:
    m = _TAG_IN_NAME.search(device_name or "")
    if not m:
        return None
    return (m.group(1) or m.group(2)).upper()


def _reconcile_vision(sheets: list[dict], items: list[dict]) -> None:
    """Feed the vision reading back into the counted takeoff: where Claude
    identified the fixture behind a counted tag (e.g. it read "Type A
    recessed luminaire" for the sheet's A tags), adopt that richer name and,
    since the drawing itself confirmed the type, move the item from Needs
    attention to Ready and clear its fixture-needs-confirmation warning.
    The count and position stay exactly as the deterministic reader found
    them -- vision resolves *what* it is, not *how many*."""
    reading_by_sheet = {s["id"]: s.get("ai_reading") for s in sheets if s.get("ai_reading")}
    for item in items:
        reading = reading_by_sheet.get(item.get("sheet_id"))
        if not reading:
            continue
        tag = (item.get("tag") or "").upper()
        if not tag:
            continue
        for dev in reading.get("devices", []):
            if _tag_of(dev.get("name", "")) == tag:
                item["ai_confirmed"] = True  # the AI saw this device on the drawing
                # Only let vision RENAME + resolve an item the counter was
                # unsure about (a fixture awaiting its schedule). An item the
                # deterministic classifier was already confident about keeps
                # its name -- vision can misread a symbol, and it should not
                # overwrite a good classification, only rescue an uncertain one.
                if item.get("status") == "attention":
                    item["name"] = dev["name"]
                    item["status"] = "ready"
                    item["warning"] = None
                break


async def _read_sheets_with_vision(sheets: list[dict], pdf_bytes_by_id: dict[str, bytes]) -> None:
    if not llm.available():
        return
    targets = [s for s in sheets if not s.get("unreadable") and pdf_bytes_by_id.get(s.get("takeoff_id"))]
    if not targets:
        return
    results = await asyncio.gather(
        *[asyncio.to_thread(_render_and_read, pdf_bytes_by_id[s["takeoff_id"]], s["page"], s.get("number") or f"page {s['page']}") for s in targets],
        return_exceptions=True,
    )
    for sheet, res in zip(targets, results):
        if isinstance(res, dict) and res.get("devices"):
            sheet["ai_reading"] = res


@app.post("/estimate/project")
async def estimate_project_endpoint(
    files: list[UploadFile] = File(...),
    types: list[str] = Form(...),
    location: str = Form(""),
    estimator_notes: str = Form("[]"),
):
    """Process the whole document set: every Drawings PDF goes through the
    engine (merged), and every other document (specs, addenda, scope) has
    its electrical-relevant text extracted as context so the classifier can
    read schedules that live outside the drawings. Each sheet keeps its own
    takeoff_id so several drawing files merge without their sheet
    references colliding, and so the vision pass below can find the right
    document's bytes for each sheet within this same request."""
    drawings: list[tuple[str, str, str]] = []  # (takeoff_id, temp_path, filename)
    pdf_bytes_by_id: dict[str, bytes] = {}
    context_parts: list[str] = []
    try:
        for f, t in zip(files, types):
            data = await f.read()
            name = (f.filename or "").lower()
            if not name.endswith(".pdf"):
                continue
            if t == "Drawings":
                takeoff_id = uuid.uuid4().hex
                pdf_bytes_by_id[takeoff_id] = data
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

        try:
            parsed_notes = json.loads(estimator_notes)
        except (TypeError, ValueError):
            parsed_notes = []
        if not isinstance(parsed_notes, list):
            parsed_notes = []
        # A malformed element (a bare string, a number) must not fail the
        # whole request -- drop it here rather than let it reach the
        # classifier's note formatting, which expects a dict.
        notes = [n for n in parsed_notes if isinstance(n, dict)]

        merged_sheets: list[dict] = []
        merged_items: list[dict] = []
        meta: dict | None = None
        for takeoff_id, path, _fname in drawings:
            payload = estimate_mod.full_takeoff(path, location, context, notes)
            if meta is None:
                meta = {k: payload[k] for k in ("location", "location_note", "labor_rate", "material_factor", "source")}
            for sheet in payload["sheets"]:
                merged_sheets.append({**sheet, "id": f"{takeoff_id}:{sheet['id']}", "takeoff_id": takeoff_id})
            for item in payload["items"]:
                merged_items.append({**item, "sheet_id": f"{takeoff_id}:{item['sheet_id']}"})

        # Vision pass: Claude reads each readable sheet's rendered image and
        # reports the devices it sees, attached to the sheet as `ai_reading`.
        # Purely additive enrichment -- run in parallel, and any failure just
        # leaves a sheet without a reading rather than failing the takeoff.
        await _read_sheets_with_vision(merged_sheets, pdf_bytes_by_id)
        _reconcile_vision(merged_sheets, merged_items)

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
