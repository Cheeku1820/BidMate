# B3 — The Drawing Behind the Markers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-09-16 · **Spec:** `docs/specs/drawing-behind-the-markers.md` · **Branch:** `feat/drawing-behind-markers` (worktree `.worktrees/drawing-behind-markers`), off `main`.

**Goal:** The real page behind the review canvas's markers — every detected sheet rendered at ingest into a tile pyramid in object storage, served through authenticated cacheable routes, drawn at its true aspect with markers rescaled at draw time so nothing counted moves.

**Architecture:** A fourth job kind, `render`, one per sheet, queued by the `read` job; `engine/tiles.py` cuts 512 px PNG tiles per zoom level with PyMuPDF (one `get_pixmap(clip=…)` per tile); the worker uploads them under a content-addressed prefix and flips `sheets.render_status`. Two org-scoped routes stream tiles and thumbnails with `private, max-age, immutable`. On the client, `sheetGeometry.js` owns the stored-1000×750 → real-aspect-paper mapping, and `TileLayer.jsx` replaces the blank-paper base layer.

**Tech Stack:** FastAPI, SQLAlchemy 2 + Alembic, PyMuPDF, boto3/MinIO via `BlobStore`, React 18 + Vitest.

**Environment for every task:** backend from `api/` with `../.enginevenv/bin/python -m pytest … -q` (Postgres up via `docker compose up -d postgres` at the worktree root; URLs in `api/.env`); frontend `npm test -- --run <file>` and `npm run build` from the worktree root (`node_modules` and `bid_examples` are symlinks). Worker tests run inline (`WORKER_INLINE=1`, `app.db.SessionLocal` monkeypatched to the test session, `app.worker.blobs.get_blob_store` monkeypatched to a `MemoryBlobStore`) — `tests/test_worker_read.py` exports `_pdf`, `_stored`, `_run_all`, and the `inline` fixture. Commit after every task with the attribution line `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Global Constraints

- **Closed sets, DB-enforced:** `sheets.render_status ∈ {pending, rendered, failed}` (`ck_sheets_render_status`); `jobs.kind ∈ {read, classify, sheet, render}` (`ck_jobs_kind` updated; `JOB_KINDS` is the one Python source). Migration `0022_sheet_render`, reversible; `create_all` parity with the migration.
- **Tiles:** 512 px PNG; level 0 = the page's long edge fits one tile; each level doubles; levels continue until the long edge reaches ≥ 150 dpi (`scale_z = 512·2^z / long_edge_pt`, stop at the first z with `72·scale_z ≥ 150`); filenames `{z}/{x}_{y}.png`, thumbnail `thumb.png` 240 px wide; all in PyMuPDF's visual frame (`page.rect`, `get_pixmap(clip=…)`).
- **Keys:** `orgs/{org_id}/projects/{project_id}/sheets/{sheet_id}/{sha256[:16]}/` — `sha256` is the document's; `render_key` stores the prefix. A re-read whose prefix already matches queues nothing.
- **Job:** `timeout_for("render")` = 300 s; failure → `render_status = failed`, `render_error = copy.RENDER_FAILED = "Couldn't draw this sheet. The takeoff still counts it."`; the takeoff never depends on rendering.
- **Routes:** `GET /api/sheets/{id}/tiles/{z}/{x}/{y}.png`, `GET /api/sheets/{id}/thumb.png`; org-scoped through `load_sheet` → 404 never 403; 404 when not rendered / `z > max_zoom` / out of grid; `Cache-Control: private, max-age=604800, immutable` on these two only; `Vary: Cookie` kept; both in the tenancy tables.
- **Wire:** sheet gains `render_status`, `render_error`, `max_zoom` (`renderStatus`, `renderError`, `maxZoom`); never `render_key`, never a storage key, never a job id.
- **Geometry:** `paperSize(sheet) = {w: 1000, h: round(1000·heightPt/widthPt)}` (`{1000, 750}` when a dimension is 0); `toPaper` scales y by `h/750`; `fromPaper` inverts. Markers stay stored in 1000×750; totals are byte-identical before and after.
- **Copy:** "Drawing the sheet…" (pending), the `RENDER_FAILED` sentence (failed). Sentence case; no "!", "please", "successfully", "AI", model names. `render_status` never renders as a pill; status is never colour alone.
- **Boundaries:** `app.main` imports no engine/pymupdf; `app.worker` imports no router (existing subprocess tests stay green).
- Process: TDD per task; full suites before each commit; the engine never touches storage (`tiles.py` writes to a directory the worker hands it).

## File map

```
api/app/engine/tiles.py                 render_sheet(path, page_index, out_dir) -> TileSet   (new)
api/app/engine/contracts.py             + Level, TileSet
api/app/worker/render_job.py            the render handler                                     (new)
api/app/worker/read_job.py              queues render jobs after upsert
api/app/worker/handlers.py              imports render_job
api/app/jobs/queue.py                   enqueue_render, mark_failed sets render_status
api/app/jobs/schemas.py                 JOB_KINDS + "render", timeout 300
api/app/jobs/copy.py                    RENDER_FAILED
api/app/tiles/__init__.py, router.py    the two routes                                         (new)
api/app/main.py                         mount; cache header override
api/app/takeoff/models.py               Sheet.render_key/render_status/render_error/max_zoom
api/app/takeoff/schemas.py, snapshot.py SheetOut fields
api/migrations/versions/0022_sheet_render.py
src/lib/sheetGeometry.js                paperSize, toPaper, fromPaper, distanceInPoints        (new)
src/lib/store/api-mapping.js            renderStatus, renderError, maxZoom
src/components/TileLayer.jsx            visibleTiles, levelFor, the layer                      (new; PlanDrawing.jsx deleted)
src/components/BlueprintCanvas.jsx      paper size, y rescale everywhere, TileLayer
src/components/SheetsRail.jsx           thumbnail
src/styles.css                          .tilelayer, .tile, .sheetpaper--pending
```

---

### Task 1: The three parked B2 residuals

**Files:**
- Modify: `api/app/documents/service.py` (`set_doc_type`), `api/tests/test_processing_api.py`
- Modify: `src/components/notes/NotesWorkspace.jsx`, `src/components/notes/NotesWorkspace.test.jsx`
- Modify: `src/components/documents/ConfirmDrawings.jsx`, `src/components/documents/ConfirmDrawings.test.jsx`

**Interfaces:** none new. `queue.in_flight_run(db, project_id) -> Job | None` and `copy.REMOVE_DURING_RUN` exist.

- [ ] **Step 1: Failing backend test** — in `api/tests/test_processing_api.py` (reuse its `_processed_drawing` helper and `blob_store` fixture):

```python
def test_retyping_a_document_is_refused_while_a_run_is_in_flight(client, db, project, dana, signed_in_user):
    d = _processed_drawing(db, project, dana)
    client.post(f"/api/projects/{project.id}/takeoff")
    res = client.patch(f"/api/documents/{d.id}", json={"doc_type": "Specifications"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "run_in_flight"
    assert res.json()["detail"]["message"] == "Wait for the takeoff to finish before changing a document's type."
    db.refresh(d)
    assert d.doc_type == "Drawings"
```

- [ ] **Step 2: Run** `pytest tests/test_processing_api.py -q -k retyping` — FAIL (200).

- [ ] **Step 3: Implement** — in `app/jobs/copy.py` add `RETYPE_DURING_RUN = "Wait for the takeoff to finish before changing a document's type."`; in `service.set_doc_type`, before anything else:

```python
    if queue.in_flight_run(db, document.project_id) is not None:
        raise DomainError("run_in_flight", copy.RETYPE_DURING_RUN, status=409)
```

- [ ] **Step 4: Run** the test — PASS.

- [ ] **Step 5: Failing frontend tests**

`NotesWorkspace.test.jsx` — find the existing Apply-and-re-run test and add beside it:

```jsx
it("says a takeoff is already running when the re-run is refused, and does not claim a start", async () => {
  const store = makeStore({ startTakeoff: vi.fn().mockRejectedValue({ code: "run_in_flight", message: "already running" }) });
  renderScreen(store);
  await userEvent.click(await screen.findByRole("button", { name: /apply and re-run/i }));
  expect(await screen.findByText("A takeoff is already running. Apply the notes again once it finishes.")).toBeInTheDocument();
  expect(screen.queryByText(/re-run started/i)).not.toBeInTheDocument();
});
```

`ConfirmDrawings.test.jsx`:

```jsx
it("keeps Start enabled while a specification is still being read, and disables it only for drawings", async () => {
  const store = makeStore({ getProcessing: vi.fn().mockResolvedValue({ documents: [
    { id: "d1", filename: "E.pdf", docType: "Drawings", state: "read", reason: "", sheetCount: 3, sheets: [] },
    { id: "d2", filename: "spec.pdf", docType: "Specifications", state: "reading", reason: "", sheetCount: 0, sheets: [] },
  ], run: null }) });
  renderScreen(store);
  expect(await screen.findByRole("button", { name: "Start takeoff" })).toBeEnabled();
});
```

(Use the files' actual helper names.)

- [ ] **Step 6: Run** both files — FAIL.

- [ ] **Step 7: Implement** — `NotesWorkspace.jsx`: on `run_in_flight`, set the apply message to `"A takeoff is already running. Apply the notes again once it finishes."` and do not start polling or show the progress list. `ConfirmDrawings.jsx`: `anyReading = rows.some((r) => r.state === "reading" && r.docType === "Drawings")`; helper copy stays "A drawing set is still being read…".

- [ ] **Step 8:** Both files green; full `npm test -- --run`; `npm run build`; full backend suite. **Step 9: Commit** — `git commit -m "Close the three B2 residuals: retype gate, honest re-run message, drawings-only Start gate"`

---

### Task 2: Migration 0022, models, the `render` kind

**Files:**
- Modify: `api/app/takeoff/models.py` (Sheet), `api/app/jobs/schemas.py`, `api/app/jobs/copy.py`, `api/app/takeoff/schemas.py` (`SheetOut`), `api/app/takeoff/snapshot.py`, `src/lib/store/api-mapping.js`
- Create: `api/migrations/versions/0022_sheet_render.py`
- Test: `api/tests/test_render_model.py`, `src/lib/store/api-mapping.test.js` (or the file that tests `mapSheet`)

**Interfaces:**
- Produces: `RENDER_STATUSES = ("pending", "rendered", "failed")` in `app.jobs.schemas`; `JOB_KINDS` includes `"render"`; `timeout_for("render") == 300`; `copy.RENDER_FAILED`; `Sheet.render_key: str | None`, `render_status: str` (default `"pending"`), `render_error: str`, `max_zoom: int | None`; `SheetOut.render_status/render_error/max_zoom`; client `sheet.renderStatus/renderError/maxZoom`.

- [ ] **Step 1: Failing tests**

```python
# api/tests/test_render_model.py
import pytest
from sqlalchemy.exc import IntegrityError

from app.jobs.schemas import JOB_KINDS, RENDER_STATUSES, timeout_for
from app.takeoff.models import Job, Sheet


def test_render_is_a_job_kind_with_its_own_timeout():
    assert "render" in JOB_KINDS
    assert timeout_for("render") == 300


def test_render_status_defaults_to_pending_and_is_closed(db, project, sheet):
    assert sheet.render_status == "pending" and sheet.render_key is None and sheet.max_zoom is None
    sheet.render_status = "drawn"
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert RENDER_STATUSES == ("pending", "rendered", "failed")


def test_a_render_job_row_is_accepted(db, project, sheet):
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="render", sheet_id=sheet.id, status="queued"))
    db.flush()


def test_snapshot_carries_render_fields_and_never_the_key(client, db, project, sheet, signed_in_user):
    sheet.render_key = "orgs/x/projects/y/sheets/z/abcd/"
    sheet.render_status, sheet.max_zoom = "rendered", 3
    db.flush()
    body = client.get(f"/api/projects/{project.id}/snapshot").json()
    s = next(x for x in body["sheets"] if x["id"] == str(sheet.id))
    assert (s["render_status"], s["render_error"], s["max_zoom"]) == ("rendered", "", 3)
    assert "render_key" not in s and "orgs/" not in str(body)
```

Frontend, in the mapping test file: `mapSheet({ …, render_status: "rendered", render_error: "", max_zoom: 3 })` → `{ renderStatus: "rendered", renderError: "", maxZoom: 3 }`; missing fields → `"pending"`, `""`, `null`.

The `db.rollback()` in the closed-set test wipes fixture rows on the shared session — use `db.begin_nested()` around the failing flush as `test_jobs_model.py` does.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** — `schemas.py`: `JOB_KINDS = ("read", "classify", "sheet", "render")`, `_DEFAULT_TIMEOUTS["render"] = 300`, `RENDER_STATUSES`. `copy.py`: `RENDER_FAILED`. Model:

```python
    # The rendered page behind the markers (B3). `render_status` is a sheet
    # property on its own axis, like `kind` -- never a review label.
    render_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    render_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    render_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    max_zoom: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

with `CheckConstraint("render_status in ('pending', 'rendered', 'failed')", name="ck_sheets_render_status")` in `Sheet.__table_args__` (built from `RENDER_STATUSES`). Migration `0022`: add the four columns with `server_default='pending'`/`''`, create the check constraint, and replace `ck_jobs_kind` (`op.drop_constraint` then `op.create_constraint` with the four-kind literal list); `downgrade` reverses all of it (restore the three-kind constraint). `SheetOut`: `render_status: str = "pending"`, `render_error: str = ""`, `max_zoom: int | None = None`; `snapshot._sheet_out` passes them. Mapping: `renderStatus: s.render_status ?? "pending"`, `renderError: s.render_error ?? ""`, `maxZoom: s.max_zoom ?? null`.

- [ ] **Step 4: Run** tests; `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` clean; full suites. **Step 5: Commit** — `git commit -m "Add the render job kind and the sheet render columns"`

---

### Task 3: `engine/tiles.py`

**Files:**
- Create: `api/app/engine/tiles.py`; Modify: `api/app/engine/contracts.py`
- Test: `api/tests/test_engine_tiles.py`

**Interfaces:**
- Produces: `contracts.Level(z: int, cols: int, rows: int, scale: float)`, `contracts.TileSet(levels: list[Level], thumb: str, files: list[str], width_pt: float, height_pt: float)` — `files` are paths relative to `out_dir` (`"0/0_0.png"`, `"thumb.png"`); `tiles.render_sheet(path: str, page_index: int, out_dir: str) -> TileSet`; `tiles.levels_for(width_pt: float, height_pt: float) -> list[Level]` (pure); constants `TILE = 512`, `TARGET_DPI = 150`, `THUMB_W = 240`.

- [ ] **Step 1: Failing tests**

```python
import math
import os

import pymupdf
import pytest

from app.engine import tiles


def _pdf(tmp_path, w_in, h_in, rotate=0):
    doc = pymupdf.open()
    page = doc.new_page(width=w_in * 72, height=h_in * 72)
    page.draw_rect(pymupdf.Rect(36, 36, w_in * 72 - 36, h_in * 72 - 36), color=(0, 0, 0), width=2)
    # a filled square in the visual top-left quadrant, so a test can find it in a tile
    page.draw_rect(pymupdf.Rect(72, 72, 144, 144), color=(0, 0, 0), fill=(0, 0, 0))
    if rotate:
        page.set_rotation(rotate)
    p = tmp_path / "t.pdf"
    doc.save(p)
    return str(p)


def test_level_zero_fits_one_tile_and_levels_double_to_150_dpi():
    lv = tiles.levels_for(36 * 72, 24 * 72)      # ARCH D, landscape
    assert lv[0].cols == 1 and lv[0].rows == 1
    for a, b in zip(lv, lv[1:]):
        assert math.isclose(b.scale, a.scale * 2)
    assert 72 * lv[-1].scale >= tiles.TARGET_DPI
    assert 72 * lv[-2].scale < tiles.TARGET_DPI
    assert lv[-1].cols == math.ceil(36 * 72 * lv[-1].scale / tiles.TILE)


def test_e_size_reaches_150_dpi_at_a_deeper_level_than_d_size():
    assert len(tiles.levels_for(48 * 72, 36 * 72)) > len(tiles.levels_for(24 * 72, 18 * 72))


def test_render_writes_every_tile_and_the_thumbnail(tmp_path):
    out = tmp_path / "out"
    ts = tiles.render_sheet(_pdf(tmp_path, 36, 24), 0, str(out))
    assert ts.width_pt == 36 * 72 and ts.height_pt == 24 * 72
    assert "thumb.png" in ts.files
    for lv in ts.levels:
        for x in range(lv.cols):
            for y in range(lv.rows):
                f = f"{lv.z}/{x}_{y}.png"
                assert f in ts.files and (out / f).exists()
    interior = pymupdf.Pixmap(str(out / f"{ts.levels[-1].z}/0_0.png"))
    assert (interior.width, interior.height) == (tiles.TILE, tiles.TILE)
    thumb = pymupdf.Pixmap(str(out / "thumb.png"))
    assert thumb.width == tiles.THUMB_W
    assert len(ts.files) == 1 + sum(lv.cols * lv.rows for lv in ts.levels)


def test_edge_tiles_are_clipped_not_padded(tmp_path):
    out = tmp_path / "out"
    ts = tiles.render_sheet(_pdf(tmp_path, 36, 24), 0, str(out))
    lv = ts.levels[-1]
    edge = pymupdf.Pixmap(str(out / f"{lv.z}/{lv.cols - 1}_{lv.rows - 1}.png"))
    expected_w = round(36 * 72 * lv.scale) - (lv.cols - 1) * tiles.TILE
    assert abs(edge.width - expected_w) <= 1 and edge.width < tiles.TILE


def test_a_rotated_page_renders_in_the_visual_frame(tmp_path):
    out = tmp_path / "out"
    ts = tiles.render_sheet(_pdf(tmp_path, 24, 36, rotate=90), 0, str(out))
    assert ts.width_pt == 36 * 72 and ts.height_pt == 24 * 72     # visual: landscape
    # the filled square drawn at unrotated (72..144, 72..144) lands, after a 90° rotation,
    # in the visual top-RIGHT; level 0 is one tile, so sample it there
    pix = pymupdf.Pixmap(str(out / "0/0_0.png"))
    s = ts.levels[0].scale
    x, y = int((36 * 72 - 108) * s), int(108 * s)
    assert pix.pixel(x, y)[0] < 128        # dark
    assert pix.pixel(int(108 * s), int(108 * s))[0] > 200   # top-left is white


def test_a_page_that_cannot_render_raises(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"%PDF-1.4 nope")
    with pytest.raises(Exception):
        tiles.render_sheet(str(p), 0, str(tmp_path / "out"))
```

If the rotation assertion's expected quadrant is wrong for PyMuPDF's convention, determine the correct one empirically in the test's own comment and keep the assertion strict — the point is that the render is the visual frame the engine's placements use.

- [ ] **Step 2: Run** — FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
# contracts.py
@dataclass
class Level:
    z: int
    cols: int
    rows: int
    scale: float  # page points -> pixels at this level


@dataclass
class TileSet:
    levels: list[Level]
    thumb: str
    files: list[str]
    width_pt: float
    height_pt: float
```

```python
# tiles.py
"""The rendered page behind the markers: a tile pyramid per sheet, cut
with PyMuPDF in the visual frame -- the same frame the engine's
placements are in (page_frame.py), so a stored marker maps to a tile
pixel exactly. No storage here: the worker uploads what this writes."""
from __future__ import annotations

import math
import os

import pymupdf

from .contracts import Level, TileSet
from .documents import _open_checked

TILE = 512
TARGET_DPI = 150
THUMB_W = 240


def levels_for(width_pt: float, height_pt: float) -> list[Level]:
    long_edge = max(width_pt, height_pt)
    levels: list[Level] = []
    z = 0
    while True:
        scale = TILE * (2 ** z) / long_edge
        levels.append(Level(z=z, cols=math.ceil(width_pt * scale / TILE), rows=math.ceil(height_pt * scale / TILE), scale=scale))
        if 72 * scale >= TARGET_DPI:
            return levels
        z += 1


def render_sheet(path: str, page_index: int, out_dir: str) -> TileSet:
    doc = _open_checked(path)
    try:
        page = doc[page_index]
        rect = page.rect  # visual frame
        w, h = rect.width, rect.height
        levels = levels_for(w, h)
        files: list[str] = []
        for lv in levels:
            os.makedirs(os.path.join(out_dir, str(lv.z)), exist_ok=True)
            tile_pt = TILE / lv.scale
            for x in range(lv.cols):
                for y in range(lv.rows):
                    clip = pymupdf.Rect(rect.x0 + x * tile_pt, rect.y0 + y * tile_pt,
                                        min(rect.x0 + (x + 1) * tile_pt, rect.x1), min(rect.y0 + (y + 1) * tile_pt, rect.y1))
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(lv.scale, lv.scale), clip=clip, alpha=False)
                    rel = f"{lv.z}/{x}_{y}.png"
                    pix.save(os.path.join(out_dir, rel))
                    files.append(rel)
        ts = THUMB_W / w
        page.get_pixmap(matrix=pymupdf.Matrix(ts, ts), alpha=False).save(os.path.join(out_dir, "thumb.png"))
        files.append("thumb.png")
        return TileSet(levels=levels, thumb="thumb.png", files=files, width_pt=w, height_pt=h)
    finally:
        doc.close()
```

- [ ] **Step 4: Run** — PASS. Full backend suite. **Step 5: Commit** — `git commit -m "Engine: cut a sheet into a 512 px tile pyramid to 150 dpi, in the visual frame"`

---

### Task 4: The `render` job

**Files:**
- Create: `api/app/worker/render_job.py`
- Modify: `api/app/worker/read_job.py`, `api/app/worker/handlers.py` (`_load_handlers`), `api/app/jobs/queue.py` (`enqueue_render`, `mark_failed`), `api/app/documents/service.py` (delete cancels render jobs — verify the existing `delete(Job).where(Job.document_id == …)`; render jobs are keyed by `sheet_id`, so delete by `sheet_id in (the document's sheets)` before `drop_sheets`)
- Test: `api/tests/test_worker_render.py`

**Interfaces:**
- Produces: `queue.render_prefix(project, sheet, sha256) -> str` = `f"orgs/{project.org_id}/projects/{project.id}/sheets/{sheet.id}/{sha256[:16]}/"`; `queue.enqueue_render(db, sheet, prefix) -> Job | None` (None when `sheet.render_key == prefix` or a render for the sheet is already queued/running; sets `render_status = "pending"` otherwise); `render_job.run(db, job)` registered as `HANDLERS["render"]`; `mark_failed` on a `render` job sets the sheet's `render_status = "failed"`, `render_error = error`.
- Consumes: `tiles.render_sheet`, `blobs.blob_to_tempfile`, `get_blob_store().put(key, stream, "image/png", size)`.

- [ ] **Step 1: Failing tests**

```python
import io
import uuid

import pytest
from sqlalchemy import select

from app.jobs import copy, queue
from app.takeoff.models import Job, Sheet
from app.worker import __main__ as worker
from tests.test_worker_read import _pdf, _run_all, _stored, inline  # noqa: F401


def _read(db, project, dana, store, monkeypatch, pages=2):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, store, _pdf("E2.1 POWER PLAN", pages=pages))
    queue.enqueue_read(db, d); _run_all(db)
    return d


def test_read_queues_one_render_per_sheet_and_the_worker_renders_them(db, project, dana, inline, monkeypatch):
    d = _read(db, project, dana, inline, monkeypatch)
    sheets = list(db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))))
    assert sheets and all(s.render_status == "rendered" and s.max_zoom is not None for s in sheets)
    s = sheets[0]
    assert s.render_key == f"orgs/{project.org_id}/projects/{project.id}/sheets/{s.id}/{d.sha256[:16]}/"
    assert inline.exists(s.render_key + "thumb.png") and inline.exists(s.render_key + "0/0_0.png")
    assert inline.exists(s.render_key + f"{s.max_zoom}/0_0.png")


def test_a_reread_of_the_same_bytes_queues_no_render(db, project, dana, inline, monkeypatch):
    d = _read(db, project, dana, inline, monkeypatch)
    before = db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Job).where(Job.kind == "render"))
    queue.enqueue_read(db, d); _run_all(db)
    after = db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Job).where(Job.kind == "render"))
    assert after == before


def test_a_reupload_with_new_bytes_renders_under_a_fresh_prefix(db, project, dana, inline, monkeypatch):
    d = _read(db, project, dana, inline, monkeypatch)
    s = db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))).first()
    old = s.render_key
    data = _pdf("E2.1 POWER PLAN  REV B", pages=2)
    d.sha256 = uuid.uuid4().hex * 2
    inline.put(d.storage_key, io.BytesIO(data), "application/pdf", len(data))
    queue.enqueue_read(db, d); _run_all(db)
    db.refresh(s)
    assert s.render_key != old and s.render_key.endswith(d.sha256[:16] + "/") and s.render_status == "rendered"


def test_a_failing_render_marks_only_its_sheet(db, project, dana, inline, monkeypatch):
    from app.engine import tiles
    real = tiles.render_sheet
    def flaky(path, page_index, out_dir):
        if page_index == 1:
            raise RuntimeError("boom")
        return real(path, page_index, out_dir)
    monkeypatch.setattr(tiles, "render_sheet", flaky)
    d = _read(db, project, dana, inline, monkeypatch)
    by_page = {s.page_index: s for s in db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id)))}
    assert by_page[1].render_status == "rendered"        # page_index is 1-based in the store
    assert by_page[2].render_status == "failed" and by_page[2].render_error == copy.RENDER_FAILED
    assert by_page[2].render_key is None


def test_deleting_a_document_cancels_its_queued_renders(client, db, project, dana, inline, monkeypatch, signed_in_user):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf("E2.1 POWER PLAN", pages=2))
    queue.enqueue_read(db, d); db.commit()
    worker.tick("t")                       # the read runs; renders are queued but not yet run
    db.commit()
    assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Job).where(Job.kind == "render", Job.status == "queued")) >= 1
    assert client.delete(f"/api/documents/{d.id}").status_code == 204
    assert db.scalars(select(Job).where(Job.kind == "render")).all() == []
```

(Check `MemoryBlobStore.exists` exists — B1 gave the Protocol `exists(key)`; if the memory store lacks it, add it.) The read job in `test_worker_read.py` uses a two-page PDF; `_run_all` ticks until no job is claimable, so renders run too.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement**

`queue.py`:

```python
def render_prefix(project: Project, sheet: Sheet, sha256: str) -> str:
    return f"orgs/{project.org_id}/projects/{project.id}/sheets/{sheet.id}/{sha256[:16]}/"


def enqueue_render(db: Session, sheet: Sheet, prefix: str) -> Job | None:
    """One render per sheet per document version. Nothing to do when the
    sheet already carries this prefix, or a render is already queued."""
    if sheet.render_key == prefix and sheet.render_status == "rendered":
        return None
    if db.scalars(select(Job).where(Job.kind == "render", Job.sheet_id == sheet.id, Job.status.in_(_IN_FLIGHT))).first():
        return None
    project = db.get(Project, sheet.project_id)
    sheet.render_status, sheet.render_error = "pending", ""
    job = Job(org_id=project.org_id, project_id=project.id, kind="render", sheet_id=sheet.id,
              payload={"prefix": prefix}, max_attempts=MAX_ATTEMPTS)
    db.add(job)
    db.flush()
    return job
```

and in `mark_failed`, after the `read` branch:

```python
    if job.kind == "render" and job.sheet_id:
        sheet = db.get(Sheet, job.sheet_id)
        if sheet is not None:
            sheet.render_status, sheet.render_error = "failed", error
```

`terminal_copy`: `if job.kind == "render" and message in ("", copy.UNREADABLE): return copy.RENDER_FAILED`.

`read_job.run`, inside the Drawings branch after the loop that sets `schedule_text/region/legend`:

```python
        for sheet in kept.values():
            queue.enqueue_render(db, sheet, queue.render_prefix(project, sheet, doc.sha256))
```

`render_job.py`:

```python
"""render: one sheet's tile pyramid into the blob store. The takeoff never
waits on this; a failure marks one sheet and says so."""
from __future__ import annotations

import os
import tempfile

from sqlalchemy.orm import Session

from app.engine import tiles
from app.takeoff.models import Document, Job, Sheet
from app.worker.blobs import blob_to_tempfile, get_blob_store
from app.worker.handlers import register


@register("render")
def run(db: Session, job: Job) -> None:
    sheet = db.get(Sheet, job.sheet_id)
    if sheet is None:
        return
    doc = db.get(Document, __import__("uuid").UUID(sheet.takeoff_id))
    if doc is None:
        return
    prefix = (job.payload or {}).get("prefix") or ""
    store = get_blob_store()
    with blob_to_tempfile(doc.storage_key, doc.filename) as path, tempfile.TemporaryDirectory() as out:
        ts = tiles.render_sheet(path, sheet.page_index - 1, out)   # the store is 1-based
        for rel in ts.files:
            full = os.path.join(out, rel)
            with open(full, "rb") as fh:
                store.put(prefix + rel, fh, "image/png", os.path.getsize(full))
    sheet.render_key, sheet.render_status, sheet.render_error = prefix, "rendered", ""
    sheet.max_zoom = ts.levels[-1].z
    db.flush()
```

(Resolve `doc` by `takeoff_id` the way `sheet_job` does — copy its lookup.) `handlers._load_handlers` imports `render_job`. `service.delete_document`: before `drop_sheets`, `db.execute(delete(Job).where(Job.sheet_id.in_(sheet_ids), Job.status.in_(("queued", "running"))))` for the document's sheets.

- [ ] **Step 4: Run** `pytest tests/test_worker_render.py tests/test_worker_read.py tests/test_jobs_queue.py tests/test_worker_loop.py -q` — PASS. Full backend suite. **Step 5: Commit** — `git commit -m "Worker: render every detected sheet into tiles, queued by the read"`

---

### Task 5: The tile routes

**Files:**
- Create: `api/app/tiles/__init__.py`, `api/app/tiles/router.py`
- Modify: `api/app/main.py`, `api/tests/test_tenancy.py`
- Test: `api/tests/test_tile_routes.py`

**Interfaces:**
- Produces: `GET /api/sheets/{sheet_id}/tiles/{z}/{x}/{y}.png`, `GET /api/sheets/{sheet_id}/thumb.png`; `tiles.router.CACHE = "private, max-age=604800, immutable"`.

- [ ] **Step 1: Failing tests**

```python
import io

import pytest

from app.documents import blobstore
from app.documents.blobstore import MemoryBlobStore
from app.main import app

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 16


@pytest.fixture
def store():
    s = MemoryBlobStore()
    app.dependency_overrides[blobstore.get_blob_store] = lambda: s
    yield s
    app.dependency_overrides.pop(blobstore.get_blob_store, None)


def _rendered(db, sheet, store, max_zoom=2):
    sheet.render_key = f"orgs/o/projects/p/sheets/{sheet.id}/abcdef0123456789/"
    sheet.render_status, sheet.max_zoom = "rendered", max_zoom
    db.flush()
    for k in ("0/0_0.png", "2/3_1.png", "thumb.png"):
        store.put(sheet.render_key + k, io.BytesIO(PNG), "image/png", len(PNG))


def test_a_tile_streams_with_a_long_private_cache(client, db, sheet, store, signed_in_user):
    _rendered(db, sheet, store)
    res = client.get(f"/api/sheets/{sheet.id}/tiles/2/3/1.png")
    assert res.status_code == 200 and res.content == PNG and res.headers["content-type"] == "image/png"
    assert res.headers["cache-control"] == "private, max-age=604800, immutable"
    assert res.headers["vary"] == "Cookie"


def test_the_thumbnail_streams(client, db, sheet, store, signed_in_user):
    _rendered(db, sheet, store)
    res = client.get(f"/api/sheets/{sheet.id}/thumb.png")
    assert res.status_code == 200 and res.content == PNG


def test_404_when_pending_out_of_zoom_or_missing_tile(client, db, sheet, store, signed_in_user):
    assert client.get(f"/api/sheets/{sheet.id}/tiles/0/0/0.png").status_code == 404   # pending
    _rendered(db, sheet, store, max_zoom=2)
    assert client.get(f"/api/sheets/{sheet.id}/tiles/3/0/0.png").status_code == 404   # z > max_zoom
    assert client.get(f"/api/sheets/{sheet.id}/tiles/1/0/0.png").status_code == 404   # not in store
    assert client.get(f"/api/sheets/{sheet.id}/tiles/0/-1/0.png").status_code == 404  # negative


def test_every_other_route_keeps_no_store(client, project, signed_in_user):
    assert client.get(f"/api/projects/{project.id}/snapshot").headers["cache-control"] == "private, no-store"
```

Tenancy: add both routes to a `SHEET_TENANCY_TABLE` keyed by the `sheet` fixture (rival org → 404, unauthenticated → 401) if the main table's `(p, s, i)` lambdas don't already cover sheet-keyed routes — check how `POST /api/sheets/{sheet_id}/scale` is registered and follow it.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement**

```python
# api/app/tiles/router.py
"""The rendered page, streamed. The URL carries the document's content hash
(through render_key), so a tile is immutable per URL and the browser may
keep it -- the one place this API lets a client cache a document's pixels,
still `private`, and the same content the evidence route serves."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Path
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session as DbSession
from starlette.background import BackgroundTask

from app.auth.deps import current_user            # match the import the other routers use
from app.db import get_db
from app.documents.blobstore import BlobNotFound, BlobStore, get_blob_store
from app.errors import not_found
from app.identity.models import User
from app.takeoff.router import load_sheet

router = APIRouter(prefix="/api", tags=["tiles"])
CACHE = "private, max-age=604800, immutable"


def _stream(store: BlobStore, key: str) -> Response:
    try:
        body = store.open(key)
    except BlobNotFound:
        raise not_found()
    return StreamingResponse(body, media_type="image/png", headers={"Cache-Control": CACHE},
                             background=BackgroundTask(body.close))


@router.get("/sheets/{sheet_id}/tiles/{z}/{x}/{y}.png")
def get_tile(sheet_id: uuid.UUID, z: int = Path(ge=0), x: int = Path(ge=0), y: int = Path(ge=0),
             user: User = Depends(current_user), db: DbSession = Depends(get_db), store: BlobStore = Depends(get_blob_store)) -> Response:
    sheet = load_sheet(sheet_id, db, user)
    if sheet.render_status != "rendered" or not sheet.render_key or sheet.max_zoom is None or z > sheet.max_zoom:
        raise not_found()
    return _stream(store, f"{sheet.render_key}{z}/{x}_{y}.png")


@router.get("/sheets/{sheet_id}/thumb.png")
def get_thumb(sheet_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db),
              store: BlobStore = Depends(get_blob_store)) -> Response:
    sheet = load_sheet(sheet_id, db, user)
    if sheet.render_status != "rendered" or not sheet.render_key:
        raise not_found()
    return _stream(store, f"{sheet.render_key}thumb.png")
```

`Path(ge=0)` makes a negative index a 422 — the test wants 404; either accept 422 there (adjust the test) or validate manually and raise `not_found()`. Choose 404: declare `z: int, x: int, y: int` and check `min(z, x, y) < 0 → not_found()`. Out-of-grid `x`/`y` within range simply miss the store → 404 via `BlobNotFound`.

`main.py`: mount the router; change the middleware so a response that already set `Cache-Control` keeps it:

```python
    if "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"
```

and update its docstring: the tile routes are the one carve-out, and why.

- [ ] **Step 4: Run** `pytest tests/test_tile_routes.py tests/test_tenancy.py tests/test_api_import_boundary.py -q` — PASS. Full suite. **Step 5: Commit** — `git commit -m "Stream sheet tiles and thumbnails, org-scoped, cacheable per content hash"`

---

### Task 6: `sheetGeometry.js`

**Files:**
- Create: `src/lib/sheetGeometry.js`
- Test: `src/lib/sheetGeometry.test.js`

**Interfaces:**
- Produces: `SHEET_W = 1000`, `SHEET_H = 750` (moved here from `BlueprintCanvas.jsx`, which re-exports them); `paperSize(sheet) -> {w, h}`; `toPaper({x, y}, sheet) -> {x, y}`; `fromPaper({x, y}, sheet) -> {x, y}`; `pointToPaper([x, y], sheet) -> [x, y]` (array form for placements/paths); `paperDistanceToPoints(d, sheet) -> number` (paper units → page points, using `widthPt / 1000`).

- [ ] **Step 1: Failing tests**

```js
import { describe, expect, it } from "vitest";
import { paperSize, toPaper, fromPaper, pointToPaper, paperDistanceToPoints } from "./sheetGeometry.js";

const D = { widthPt: 2592, heightPt: 1728 };   // 36 x 24 in, 3:2
const NONE = { widthPt: 0, heightPt: 0 };

describe("sheetGeometry", () => {
  it("gives the paper the page's real aspect", () => {
    expect(paperSize(D)).toEqual({ w: 1000, h: 667 });
    expect(paperSize({ widthPt: 1000, heightPt: 750 })).toEqual({ w: 1000, h: 750 });
    expect(paperSize(NONE)).toEqual({ w: 1000, h: 750 });
  });
  it("rescales only y, and round-trips", () => {
    expect(toPaper({ x: 500, y: 375 }, D)).toEqual({ x: 500, y: 333.5 });
    const p = fromPaper(toPaper({ x: 120, y: 700 }, D), D);
    expect(p.x).toBeCloseTo(120); expect(p.y).toBeCloseTo(700);
    expect(pointToPaper([500, 375], D)).toEqual([500, 333.5]);
    expect(toPaper({ x: 500, y: 375 }, NONE)).toEqual({ x: 500, y: 375 });
  });
  it("converts a paper distance to page points along x", () => {
    expect(paperDistanceToPoints(100, D)).toBeCloseTo(259.2);
    expect(paperDistanceToPoints(100, NONE)).toBe(0);
  });
});
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**

```js
/* sheetGeometry.js — the one place stored marker space meets the paper.
   Markers are stored in a 1000 x 750 sheet space (x normalised against the
   page's width, y against its height -- ingest.py). A page is rarely 4:3,
   so the paper the canvas draws takes the page's real aspect and y is
   rescaled here, at draw time. Nothing counted moves. */
export const SHEET_W = 1000;
export const SHEET_H = 750;

export function paperSize(sheet) {
  const w = Number(sheet?.widthPt || 0), h = Number(sheet?.heightPt || 0);
  if (!w || !h) return { w: SHEET_W, h: SHEET_H };
  return { w: SHEET_W, h: Math.round((SHEET_W * h) / w) };
}
const ky = (sheet) => paperSize(sheet).h / SHEET_H;
export function toPaper(p, sheet) { return { x: p.x, y: p.y * ky(sheet) }; }
export function fromPaper(p, sheet) { return { x: p.x, y: p.y / ky(sheet) }; }
export function pointToPaper([x, y], sheet) { return [x, y * ky(sheet)]; }
export function paperDistanceToPoints(d, sheet) {
  const w = Number(sheet?.widthPt || 0);
  return w ? (d * w) / SHEET_W : 0;
}
```

- [ ] **Step 4:** PASS. **Step 5: Commit** — `git commit -m "Client: one module for stored sheet space versus the paper's real aspect"`

---

### Task 7: `TileLayer.jsx` and the canvas on real paper

**Files:**
- Create: `src/components/TileLayer.jsx`, `src/components/TileLayer.test.jsx`
- Delete: `src/components/PlanDrawing.jsx` (and its test if any)
- Modify: `src/components/BlueprintCanvas.jsx`, `src/components/BlueprintCanvas.test.jsx` (create if absent), `src/styles.css`

**Interfaces:**
- Produces: `levelFor(viewScale, maxZoom) -> z`; `visibleTiles(viewport: {x, y, w, h} in paper units, level: {z, cols, rows}, paper: {w, h}) -> [{z, x, y, left, top, width, height}]`; `TileLayer({ sheet, view, size })` (view = `{scale, tx, ty}`; size = viewport px) rendering `<div className="tilelayer">` beneath the SVG.
- Consumes: Task 6.

- [ ] **Step 1: Failing tests**

```jsx
// TileLayer.test.jsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import TileLayer, { levelFor, visibleTiles, gridFor } from "./TileLayer.jsx";

const D = { id: "s1", number: "E2.1", widthPt: 2592, heightPt: 1728, renderStatus: "rendered", renderError: "", maxZoom: 3 };

describe("levelFor", () => {
  it("picks the smallest level whose width covers the on-screen page, capped", () => {
    expect(levelFor(0.4, 3)).toBe(0);   // 400 px on screen -> level 0 (512)
    expect(levelFor(1.1, 3)).toBe(2);   // 1100 px -> 2048
    expect(levelFor(9, 3)).toBe(3);     // capped
  });
});

describe("gridFor / visibleTiles", () => {
  it("derives the grid from the paper aspect and clips edge tiles", () => {
    const g = gridFor(2, { w: 1000, h: 667 });          // level 2: long edge 2048 px -> 4 cols
    expect(g).toEqual({ z: 2, cols: 4, rows: 3, tilePaper: 250 });
    const tiles = visibleTiles({ x: 0, y: 0, w: 1000, h: 667 }, g, { w: 1000, h: 667 });
    expect(tiles).toHaveLength(12);
    const last = tiles.find((t) => t.x === 3 && t.y === 2);
    expect(last).toMatchObject({ left: 750, top: 500, width: 250, height: 167 });
  });
  it("returns only tiles intersecting the viewport, with a one-tile margin", () => {
    const g = gridFor(3, { w: 1000, h: 667 });          // 8 cols
    const tiles = visibleTiles({ x: 400, y: 300, w: 100, h: 100 }, g, { w: 1000, h: 667 });
    const xs = new Set(tiles.map((t) => t.x));
    expect(Math.min(...xs)).toBe(2); expect(Math.max(...xs)).toBe(4);
  });
});

describe("TileLayer", () => {
  it("renders the backdrop and the visible tiles for a rendered sheet", () => {
    const { container } = render(<TileLayer sheet={D} view={{ scale: 0.8, tx: 0, ty: 0 }} size={{ w: 800, h: 534 }} />);
    const imgs = container.querySelectorAll("img.tile");
    expect(imgs.length).toBeGreaterThan(1);
    expect(imgs[0].getAttribute("src")).toBe("/api/sheets/s1/tiles/0/0/0.png");
    expect(imgs[0].getAttribute("alt")).toBe("");
  });
  it("shows the sheet number and 'Drawing the sheet…' while pending, and the reason when failed", () => {
    render(<TileLayer sheet={{ ...D, renderStatus: "pending" }} view={{ scale: 1, tx: 0, ty: 0 }} size={{ w: 800, h: 600 }} />);
    expect(screen.getByText(/E2\.1/)).toBeInTheDocument();
    expect(screen.getByText("Drawing the sheet…")).toBeInTheDocument();
    render(<TileLayer sheet={{ ...D, renderStatus: "failed", renderError: "Couldn't draw this sheet. The takeoff still counts it." }} view={{ scale: 1, tx: 0, ty: 0 }} size={{ w: 800, h: 600 }} />);
    expect(screen.getByText("Couldn't draw this sheet. The takeoff still counts it.")).toBeInTheDocument();
  });
});
```

Canvas test (`BlueprintCanvas.test.jsx`, minimal render with a stub store-less props set — read how `Workspace` passes props and mock the minimum):

```jsx
it("draws a marker stored at the sheet's centre at the paper's centre on a 3:2 page", () => {
  const sheet = { id: "s1", number: "E2.1", widthPt: 2592, heightPt: 1728, renderStatus: "pending", renderError: "", maxZoom: null, scale: "" };
  const items = [{ id: "i1", sheetId: "s1", x: 500, y: 375, status: "ready", symbol: "receptacle", name: "r", quantity: 1, placements: [[500, 375]] }];
  const { container } = render(<BlueprintCanvas sheet={sheet} items={items} selectedId={null} onSelect={() => {}} layers={{ detected: true, approved: true, rejected: true, measurements: true, warnings: true }} tool="pan" onCalibrate={() => {}} remoteSelections={[]} />);
  const g = container.querySelector('g[transform]');
  expect(g.getAttribute("transform")).toBe("translate(500 333.5)");
  const paper = container.querySelector(".sheetpaper");
  expect(paper.style.height).toBe("667px");
});
```

(Adapt prop names to the component's actual signature.)

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**

```jsx
// TileLayer.jsx
/* The base layer under the markers: the real page, as tiles. Positioned in
   paper units under the same transform as the marker SVG, so a marker
   drawn at (x, y) sits on the pixel the engine counted. */
import { useEffect, useMemo, useState } from "react";
import { paperSize } from "../lib/sheetGeometry.js";

const TILE = 512;
const DIM = "#8a857c";

export function levelFor(viewScale, maxZoom) {
  const onScreen = 1000 * viewScale;
  let z = 0;
  while (TILE * 2 ** z < onScreen && z < (maxZoom ?? 0)) z += 1;
  return Math.min(z, maxZoom ?? 0);
}

export function gridFor(z, paper) {
  const long = Math.max(paper.w, paper.h);
  const tilePaper = long / 2 ** z;                 // paper units per tile
  return { z, cols: Math.ceil(paper.w / tilePaper), rows: Math.ceil(paper.h / tilePaper), tilePaper };
}

export function visibleTiles(viewport, grid, paper) {
  const t = grid.tilePaper;
  const x0 = Math.max(0, Math.floor(viewport.x / t) - 1), x1 = Math.min(grid.cols - 1, Math.floor((viewport.x + viewport.w) / t) + 1);
  const y0 = Math.max(0, Math.floor(viewport.y / t) - 1), y1 = Math.min(grid.rows - 1, Math.floor((viewport.y + viewport.h) / t) + 1);
  const out = [];
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    out.push({ z: grid.z, x, y, left: x * t, top: y * t, width: Math.min(t, paper.w - x * t), height: Math.min(t, paper.h - y * t) });
  }
  return out;
}

function Tile({ sheet, t }) {
  const [attempt, setAttempt] = useState(0);
  const src = `/api/sheets/${sheet.id}/tiles/${t.z}/${t.x}/${t.y}.png${attempt ? `?r=${attempt}` : ""}`;
  return (
    <img className="tile" alt="" src={src} draggable={false}
         style={{ left: t.left, top: t.top, width: t.width, height: t.height }}
         onError={() => { if (attempt === 0) setTimeout(() => setAttempt(1), 2000); }} />
  );
}

export default function TileLayer({ sheet, view, size }) {
  const paper = paperSize(sheet);
  if (sheet.renderStatus !== "rendered") {
    return (
      <div className="tilelayer tilelayer--blank" style={{ width: paper.w, height: paper.h }}>
        <div className="tilelayer__note" style={{ color: DIM }}>
          <div>{sheet.number}{sheet.title ? ` — ${sheet.title}` : ""}</div>
          <div>{sheet.renderStatus === "failed" ? sheet.renderError : "Drawing the sheet…"}</div>
        </div>
      </div>
    );
  }
  const z = levelFor(view.scale, sheet.maxZoom);
  const viewport = { x: -view.tx / view.scale, y: -view.ty / view.scale, w: size.w / view.scale, h: size.h / view.scale };
  const tiles = visibleTiles(viewport, gridFor(z, paper), paper);
  const backdrop = visibleTiles({ x: 0, y: 0, w: paper.w, h: paper.h }, gridFor(0, paper), paper);
  return (
    <div className="tilelayer" style={{ width: paper.w, height: paper.h }}>
      {backdrop.map((t) => <Tile key={`b${t.x}_${t.y}`} sheet={sheet} t={t} />)}
      {z > 0 && tiles.map((t) => <Tile key={`${t.z}_${t.x}_${t.y}`} sheet={sheet} t={t} />)}
    </div>
  );
}
```

CSS: `.tilelayer { position: absolute; inset: 0; background: var(--paper, #fff); }` `.tile { position: absolute; image-rendering: auto; pointer-events: none; }` `.tilelayer__note { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; font-size: 12px; }`. Use existing tokens (`--paper` if defined, else the token the `.sheetpaper` background uses).

`BlueprintCanvas.jsx`: import `paperSize`, `toPaper`, `pointToPaper`, `fromPaper`, `paperDistanceToPoints` and re-export `SHEET_W/SHEET_H` from `sheetGeometry`; compute `const paper = paperSize(sheet)` once; fit-to-page uses `paper.w/paper.h`; `.sheetpaper` and the `<svg viewBox>` use `paper.w × paper.h`; `<TileLayer sheet view size>` replaces `<PlanDrawing>` and sits as a sibling `<div>` *before* the SVG inside `.sheetpaper` (the SVG gets `position: absolute; inset: 0`); every draw site converts: marker `translate` via `toPaper({x: it.x, y: it.y})`, placement circles and `path` polylines via `pointToPaper`, the hover tooltip and remote rings likewise, the minimap frame/dots divide by `paper.w/paper.h`, `toSheet(clientX, clientY)` returns paper coordinates and calibration stores paper points — `onCalibrate(paperDistanceToPoints(pathLength(next), sheet))` so the distance handed up is in page points (the modal's own units stay what they were; if it expects sheet units, pass `fromPaper` instead and say which in the report). Delete `PlanDrawing.jsx`.

- [ ] **Step 4:** `npm test -- --run src/components` green; `npm run build`; then run the stack (`docker compose up -d postgres minio minio-init api worker`, `npm run dev`), open a project with a rendered set, zoom in and confirm tiles sharpen and markers stay on their symbols/tags. **Step 5: Commit** — `git commit -m "Canvas: the real page under the markers, at its true aspect"`

---

### Task 8: The rail thumbnail, the corpus check, docs

**Files:**
- Modify: `src/components/SheetsRail.jsx`, `src/components/SheetsRail.test.jsx`
- Create: `api/tests/test_corpus_render.py`
- Modify: `README.md`, `CLAUDE.md`, `ROADMAP.md` (§2.1 rendering line), `docs/README.md` (B3 row), `docs/roadmap/full-webapp-plan.md` (Phase B rendering box), `docs/specs/drawing-behind-the-markers.md` (an "As built" section with any deviation the tasks produced)

- [ ] **Step 1: Failing tests**

```jsx
// SheetsRail.test.jsx (add)
it("shows the thumbnail once a sheet is rendered, and the dots before", () => {
  const sheets = [
    { id: "a", number: "E1", title: "t", renderStatus: "rendered", kind: "plan" },
    { id: "b", number: "E2", title: "t", renderStatus: "pending", kind: "plan" },
  ];
  const { container } = render(<SheetsRail sheets={sheets} items={[]} sheetId="a" onSelectSheet={() => {}} />);
  const img = container.querySelector('img[src="/api/sheets/a/thumb.png"]');
  expect(img).toBeTruthy(); expect(img.getAttribute("alt")).toBe("");
  expect(container.querySelectorAll(".sheetrow__thumb svg")).toHaveLength(1);
});
```

```python
# api/tests/test_corpus_render.py
"""The real thing: the Unalaska set's first plan renders, and every counted
placement falls inside the paper after the draw-time rescale."""
import pytest

from app.engine import counting, documents, tiles
from tests.bid_set import first_vector_set


def test_first_plan_renders_and_placements_fall_inside_the_paper(tmp_path):
    path = first_vector_set()
    reading = documents.read(path, "Drawings")
    plan = next(s for s in reading.sheets if s.kind == "plan" and not s.unreadable_reason)
    ts = tiles.render_sheet(path, plan.page_index, str(tmp_path))
    assert ts.width_pt == plan.width_pt and ts.height_pt == plan.height_pt
    assert 72 * ts.levels[-1].scale >= tiles.TARGET_DPI
    clusters = counting.count_sheet(path, plan)
    paper_h = round(1000 * plan.height_pt / plan.width_pt)
    for c in clusters:
        for p in c.placements:
            x = p.x / plan.width_pt * 1000
            y = (p.y / plan.height_pt * 750) * (paper_h / 750)
            assert 0 <= x <= 1000 and 0 <= y <= paper_h
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** the rail: when `s.renderStatus === "rendered"`, render `<img className="sheetrow__img" alt="" src={`/api/sheets/${s.id}/thumb.png`} />` in the thumb slot instead of the SVG. Docs: README "What's in the drawing" now describes the rendered page and the evidence crop as two witnesses; CLAUDE.md "Known scope limits" drops "The blueprint is drawn SVG geometry, not a rendered PDF" and the architecture tree adds `TileLayer.jsx`, `lib/sheetGeometry.js`, `app/tiles/`, `app/worker/render_job.py`, `engine/tiles.py`; ROADMAP §2.1 "Page rendering and tiling" → built (B3); `docs/README.md` B3 row; full-webapp-plan tick "Page rendering at ingest"; spec "As built".

- [ ] **Step 4:** All suites + build green; the verification grep `grep -rn "PlanDrawing\|drawn SVG geometry" src README.md CLAUDE.md` returns nothing. **Step 5: Commit** — `git commit -m "Rail thumbnails, the corpus render check, and the docs"`

---

## Self-review

**Spec coverage.** §2 data → Task 2; §3 tiles → Task 3; §4 render job (queue, prefix, failure, cancel) → Task 4; §5 routes, cache, snapshot → Tasks 2, 5; §6.1 geometry → Task 6; §6.2 TileLayer + canvas → Task 7; §6.3 rail → Task 8; §7 copy → Tasks 2, 7; §8 tests → each task + Task 8 corpus; §9 not built → Task 8 docs; §10 residuals → Task 1.

**Placeholders.** None; every step has its code or its exact assertions. Task 7's calibration note leaves one documented choice (points vs sheet units for the modal) to the implementer with instructions to report which.

**Type consistency.** `Level(z, cols, rows, scale)` and `TileSet(levels, thumb, files, width_pt, height_pt)` — same in Tasks 3, 4, 8. `render_prefix(project, sheet, sha256)` / `enqueue_render(db, sheet, prefix)` — Task 4 only. `paperSize/toPaper/fromPaper/pointToPaper/paperDistanceToPoints` — same names in Tasks 6, 7. `levelFor/gridFor/visibleTiles` — Task 7 only. Wire keys `render_status/render_error/max_zoom` ↔ `renderStatus/renderError/maxZoom` — Tasks 2, 7, 8.
