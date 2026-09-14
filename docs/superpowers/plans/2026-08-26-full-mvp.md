# Full MVP Implementation Plan

> **For agentic workers:** Sections are ordered for the fastest path to a complete, demoable loop. Each section ends with something you can show. Calibrated to a tight time box: task-level granularity, not per-step TDD.

**Goal:** Turn the working estimate engine into a full MVP an estimator drives end to end — upload multiple files, watch them process, review the real takeoff, and export a location-priced estimate — reusing the review UI already built.

**Architecture:** The standalone estimate service (`api/estimate_service.py`, no Docker/Postgres) does PDF → JSON. The frontend maps that JSON into the **existing seed store** (localStorage) as a real project's sheets + items. This makes the whole review workspace, spreadsheet, drawer totals, approve/edit/reject, undo, and export work with **real engine data** — no backend rewrite. The blueprint canvas over the real PDF page is the one genuinely new frontend piece and is scoped last.

**Tech Stack:** React 18 + Vite (frontend), FastAPI + PyMuPDF + Anthropic SDK (engine service), plain CSS tokens, seed store over localStorage.

## Global Constraints

- No Docker/Postgres in the MVP path — the estimate service stays standalone on `localhost:8100`.
- Status vocabulary stays the four labels; `rejected` is a flag. Green only on approved. No AI/model/confidence framing in the UI.
- Sample/seed data stays clearly labeled; real engine data is never mixed with the Meridian fixture.
- Engine stops at total direct cost — no markup/overhead/profit.
- The deterministic fallback must keep the flow working with no API key.
- `npm run build` clean and the existing test suite green after each section.

---

## File structure

```
api/
  estimate_service.py        + POST /estimate/full — per-sheet items + coords + cost, for store injection
  app/engine/
    estimate.py              + full_takeoff(): richer, per-sheet output (not consolidated)
    documents.py             + page dimensions on DetectedSheet (already has region)
src/
  lib/
    engineClient.js          NEW — fetch wrapper for the estimate service
    store/
      seed-ingest.js         NEW — map engine JSON -> store sheets+items; attachEngineTakeoff(projectId, payload)
      seed.js                + expose attachEngineTakeoff (mirrors attachSampleTakeoff)
  components/
    documents/
      UploadDocuments.jsx    MODIFY — multiple files already supported; wire "Start" to real processing
      ProcessingStatus.jsx   MODIFY — call the engine, real progress, land takeoff in store
    takeoff/
      spreadsheetColumns.js  + material / labor-hours / total-cost columns
    export/
      ExportPreview.jsx      + cost totals (material, labor, total direct cost) + location
    projects/
      NewProject.jsx         + location already collected; ensure it flows to processing
    canvas (stretch)
      BlueprintCanvas.jsx    MODIFY — render the sheet PNG behind markers (Section 6)
```

---

## Section 1 — Engine: richer per-sheet output

**Why first:** everything downstream consumes this shape.

**Files:** `api/app/engine/estimate.py` (add `full_takeoff`), `api/estimate_service.py` (add `POST /estimate/full`), `api/app/engine/documents.py` (add `width_pt`/`height_pt` — already present on DetectedSheet).

**Produces:** `POST /estimate/full` returning:
```json
{
  "location": "...", "labor_rate": 98.0, "material_factor": 1.35, "location_note": "...", "source": "llm",
  "sheets": [{"number":"E2.1","page":85,"width_pt":2448,"height_pt":1584,"unreadable":null}],
  "items": [
    {"name":"20A duplex receptacle","system":"Power","category":"Devices","unit":"ea",
     "quantity":6,"status":"ready","sheet":"E2.1","page":85,"tag":"R",
     "x":812,"y":540,"placements":[[812,540],...],
     "material_cost":97.0,"labor_hours":3.0,"labor_cost":294.0,"total_cost":391.0,
     "warning":{...}|null}
  ],
  "totals":{"material":..., "labor_hours":..., "labor_cost":..., "total_direct_cost":..., "item_count":..., "attention_count":...}
}
```
Key difference from `/estimate`: items are **per-cluster (per sheet) with coordinates**, not consolidated by name — the store needs one item per placement group with a position.

**Done when:** `curl POST /estimate/full` on the Unalaska drawings returns per-sheet items with `x,y` and cost, and `sheets[]` carry page dimensions.

---

## Section 2 — Multi-file upload

**Files:** `src/components/documents/UploadDocuments.jsx` (already accepts multiple files and per-file type). 

**Scope:** confirm multi-file works (it does — `addFiles` loops), keep the document-type dropdown (Drawings/Specs/Addendum/Scope/Other). Only files typed **Drawings** are sent to the engine; the rest are attached as context (listed, not parsed — honest). "Review detected drawings" / "Start takeoff" carries the set forward.

**Done when:** an estimator can drop several PDFs, set each type, and only drawings are queued for processing; specs/addenda are listed as attached.

---

## Section 3 — Processing with real loading

**Files:** `src/components/documents/ProcessingStatus.jsx` (MODIFY), `src/lib/engineClient.js` (NEW), `src/lib/store/seed-ingest.js` (NEW), `src/lib/store/seed.js` (add `attachEngineTakeoff`).

**Scope:**
- `engineClient.js`: `estimateFull(file, location) -> payload` (POST /estimate/full, multipart), with a clear error if the service is down.
- `ProcessingStatus.jsx`: instead of the simulated sample loop, POST the drawings file(s) to the engine. Show a **real multi-stage loading UI**: "Uploading… → Reading sheets → Counting devices → Classifying & pricing (this uses the model, ~10–20s) → Done." Because the engine call is one request, drive the stages on a timer that resolves when the response lands (honest: the stages are indicative, the completion is real). Handle errors (service down, unreadable) with recovery copy.
- On success: `attachEngineTakeoff(projectId, payload)` writes real sheets+items into the project's scoped store keys (mirroring `attachSampleTakeoff`), marks the project stage `review`, stores location/rate/totals on the project row. Then route to review.

**Interfaces:**
- `seed-ingest.mapPayload(payload) -> { sheets:[storeSheet], items:[storeItem] }` — maps engine JSON to the store shape: item `{id,sheetId,symbol,name,description,system,category,quantity,unit,status,x,y,rejected:false,warnings:[warning?],version:1, material_cost,labor_hours,total_cost}`; sheet `{id,number,title,discipline,revision,scale,scaleOptions:[],superseded:false, widthPt,heightPt, pageIndex}`.
- `seed.attachEngineTakeoff(projectId, payload)` — like `attachSampleTakeoff` but from real data; sets `sample:false`, stores `location`, `labor_rate`, `material_factor` on the created project row.

**Done when:** uploading the real drawings shows a genuine loading sequence and lands you in the review workspace with the real takeoff for that project (no sample banner).

---

## Section 4 — Review the real takeoff (spreadsheet + drawer)

**Files:** `src/components/takeoff/spreadsheetColumns.js` (add cost columns), `src/lib/useReviewStore.js` (drawer cost totals), `src/components/SummaryDrawer.jsx` (show cost).

**Scope:**
- Add optional columns to the spreadsheet: **Material $**, **Labor hrs**, **Total $** (only render when items carry them — real projects do, the seed fixture doesn't, so nothing breaks there).
- The review workspace already renders items on the blueprint canvas; for real projects **without** a rendered PDF yet, the spreadsheet is the primary review surface (Section 6 adds the canvas). Approve/edit/reject/undo already work through the store — verify they operate on real items.
- Bottom drawer / a small cost strip shows material + labor + **total direct cost** for approved items, using the project's stored `labor_rate`/`material_factor`.

**Done when:** the spreadsheet shows the real priced items with status, the estimator can approve/reject/edit, and the drawer shows a running total direct cost.

---

## Section 5 — Estimate & export

**Files:** `src/components/export/ExportPreview.jsx` (MODIFY).

**Scope:** the export preview already reconciles quantities; add **cost**: material total, labor hours + cost at the project's rate, and **total direct cost**, plus the location and pricing basis (Claude vs regional). The CSV export gains cost columns. Blocking rules unchanged (Missing info blocks).

**Done when:** finishing review lands on an export preview showing the real location-priced total direct cost that reconciles with the drawer, and the CSV carries per-item cost.

---

## Section 6 — Blueprint canvas over the real PDF (stretch)

**Files:** `api/estimate_service.py` (add `GET /sheet-image?...` serving `documents.render_page_png`), `src/components/BlueprintCanvas.jsx` + `PlanDrawing.jsx` (MODIFY).

**Scope:** for a real project, render the sheet's PNG (from the engine) as the canvas background instead of the drawn SVG geometry, and place markers at the real `x,y` (normalized from page points to the image). This is the signature view; it's last because it's the only genuinely new rendering work and the spreadsheet already makes the takeoff reviewable.

**Done when:** selecting a real sheet shows the actual drawing with device markers on it, click-selectable, synced to the spreadsheet.

---

## Cross-cutting (folded into the sections above)

- **Location** is collected at project creation (`NewProject.jsx` already has the field) and passed to the engine in Section 3.
- **Labor rate**: the engine returns a location rate; if the project has a Company/Project settings override, pass it as the `labor_rate` the engine uses (Section 3 sends it; the service already accepts location — extend to accept an optional rate).
- **Loading states** everywhere the engine is called (Section 3) and while the store injects (instant).
- **Errors**: service-down, unreadable sheets, no drawings typed — each with recovery copy (Sections 2–3).

## Self-review notes

- Spec coverage: multi-file upload (S2), loading screens (S3), full loop review→export (S4–S5), section-by-section ordering (all). Blueprint-on-real-PDF is S6 (stretch).
- The keystone is `attachEngineTakeoff` mirroring the tested `attachSampleTakeoff` — low risk, reuses the isolation already proven.
- Fallback: no API key → deterministic pricing still flows through the identical path.
