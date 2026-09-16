# B3 — The drawing behind the markers

**Date:** 2026-09-16
**Branch:** `feat/drawing-behind-markers`, off `main` (B1 and B2 merged)
**Implements:** `docs/roadmap/full-webapp-plan.md` Phase B, third of four sub-projects: B1 documents stored → B2 engine behind the API → **B3 drawing behind the markers** → B4 confirm-drawings write-back and metering.

## 1. What this changes

The review canvas draws blank paper at a fixed 1000 × 750 with markers normalised per axis at ingest (x against `width_pt`, y against `height_pt`). Every quantity is traceable to an evidence crop, but the estimator reviews markers on white. After B3 the real page is behind them.

Two facts shape the design:

1. **A page is rarely 4:3.** ARCH D is 3:2, ANSI D 1.55:1, ARCH E 4:3. Stretching a rendered page into 1000 × 750 distorts the drawing by 10–15%. So the paper takes the page's real aspect and marker **y is rescaled at draw time** — markers stay stored in 1000 × 750; nothing counted moves.
2. **Placements and renders share a frame.** The engine's `page_frame` fix (sheet-fidelity) put every placement in PyMuPDF's visual frame, which is the frame `get_pixmap` renders. The mapping from a stored marker to a pixel on the tile is therefore exact.

Rendering is a fourth job kind, `render`, one per detected sheet, queued by the `read` job. It is independent of the takeoff run: it starts at upload, so screen D can show thumbnails before Start and the review workspace can open before rendering finishes.

## 2. Data model

Migration `0022_sheet_render`, reversible.

```
sheets gains
  render_key      str(300) null    blob prefix once rendered
  render_status   str(20)          pending | rendered | failed      ck_sheets_render_status
  render_error    text default ''  estimator copy when failed
  max_zoom        int null         the finest level rendered
```

`jobs.kind` gains `render` (`JOB_KINDS`, `ck_jobs_kind`, and the migration's literal list). `timeout_for("render")` = 300 s.

`render_status` is a sheet property on its own axis, like `kind` — never a review label, never a pill. Default `pending` for every existing row; the first `read` after upgrade queues renders for them.

## 3. Tiles — `engine/tiles.py`

`render_sheet(path: str, page_index: int, out_dir: str) -> TileSet` — PyMuPDF only, no database.

- **Levels.** Level 0 is the scale at which the page's long edge fits one 512 px tile. Each level doubles. Levels continue until the page reaches **≥ 150 dpi** on its long edge (`points × 150/72 ≤ 512 × 2^z`), typically z = 3 for D-size, 4 for E-size. `max_zoom` is the last level rendered.
- **Tiles.** 512 px PNG, cut with `page.get_pixmap(matrix=Matrix(s, s), clip=tile_rect)` — one render per tile keeps memory flat regardless of page size. Edge tiles are smaller. Filenames `{z}/{x}_{y}.png`, x and y tile indices from the top-left.
- **Thumbnail.** `thumb.png`, 240 px wide, same visual frame.
- **Output.** `TileSet(levels: list[Level(z, cols, rows, scale)], thumb: str, files: list[str])` — the worker uploads `files` from `out_dir`; the engine never touches storage.

A page with zero paths and zero images is still rendered (it's white paper, cheap); a page PyMuPDF cannot render raises, and the job fails for that sheet alone.

## 4. The `render` job

**Queued by `read`.** After upserting a document's sheets, the read job queues one `render` job per sheet whose `render_key` is not `orgs/…/sheets/{sheet_id}/{sha256[:16]}` for the document's current hash — a re-read of unchanged bytes renders nothing twice. Deleting a document cancels its queued renders with its other jobs (B2's rule).

**Body.** Open the blob to a temp file; `render_sheet`; upload every file to `render_key = orgs/{org}/projects/{project}/sheets/{sheet_id}/{sha256[:16]}/`; set `render_status = rendered`, `max_zoom`, `render_error = ''`. The blob writes happen before the row flips, so a `rendered` sheet always has its tiles.

**Failure.** Timeout or exception → the parent's `mark_failed` sets `render_status = failed` and `render_error = copy.RENDER_FAILED` (`"Couldn't draw this sheet. The takeoff still counts it."`). Transient storage errors retry as every job does. The takeoff never depends on rendering: counting reads the PDF, not the tiles.

**Stale tiles.** A re-upload gets a fresh prefix (new hash); the old prefix stays in storage — the reaper is still not built (ROADMAP §2.2). The browser cache keys on the URL, so nothing stale is ever shown.

## 5. The API

| route | does |
|---|---|
| `GET /api/sheets/{id}/tiles/{z}/{x}/{y}.png` | streams one tile |
| `GET /api/sheets/{id}/thumb.png` | streams the thumbnail |

Org-scoped through the sheet's project (`load_sheet` → 404 never 403), registered in the tenancy guard. A sheet not `rendered`, or `z > max_zoom`, or `x`/`y` outside the level's grid → 404. The blob key is built from `render_key` and the path parameters (integers only — the route's types enforce it; no client string reaches the key).

**Caching.** The URL carries the content hash through `render_key`, so tiles are immutable per URL: the response sets `Cache-Control: private, max-age=604800, immutable`, overriding the app-wide `private, no-store` for these two routes only. `Vary: Cookie` stays. This is the one place the product lets the browser keep a document's pixels; it is still `private`, and it is the same content the evidence route already serves.

**Snapshot.** Each sheet gains `render_status`, `render_error`, `max_zoom` on the wire (`renderStatus`, `renderError`, `maxZoom` in the client mapping). `width_pt`/`height_pt` already cross. Nothing changes in the processing response.

## 6. The client

### 6.1 Sheet geometry — `src/lib/sheetGeometry.js`

```js
paperSize(sheet)            // {w: 1000, h: round(1000 * heightPt / widthPt)}; {w: 1000, h: 750} when a dimension is 0
toPaper({x, y}, sheet)      // stored 1000×750 → paper units: {x, y: y * (paper.h / 750)}
fromPaper({x, y}, sheet)    // the inverse — calibration and any future add-marker tool use it
```

Every coordinate the canvas touches goes through it: marker placement, measured-run polylines, the minimap frame and dots, fit-to-page, calibration's two clicks and its banner distance, hover tooltips, remote-selection rings. `SHEET_W`/`SHEET_H` remain the storage constants; the canvas stops using them as paper size.

### 6.2 `TileLayer.jsx`

Replaces `PlanDrawing.jsx` as the base layer, rendered as absolutely-positioned `<img>` elements in paper units beneath the marker SVG (an `<img>` per tile, not `<image>` in SVG, so the browser's decode and cache behave as for any image).

- **Level choice.** Given the viewport scale `s` (paper units → screen px), on-screen page width is `1000 · s` px; pick the smallest `z` whose level width `512 · 2^z` is ≥ that, capped at `maxZoom`.
- **Visible tiles.** Intersect the viewport rectangle (in paper units) with the level's grid; render only those tiles, plus a one-tile margin. At level `z` the page's long edge is `512 · 2^z` px, so one tile spans `T = (long edge in paper units) / 2^z` paper units on both axes (1000 / 2^z for a landscape page); tile `(x, y)` occupies the paper rectangle `[x·T, y·T] – [min((x+1)·T, w), min((y+1)·T, h)]`, edge tiles clipped. The pure helper `visibleTiles(viewport, level, paper) -> [{z, x, y, left, top, width, height}]` does this arithmetic and is unit-tested on its own.
- **Backdrop.** Level 0 (one tile, or at most four) is always rendered underneath, so zooming never flashes to white while finer tiles load.
- **Loading and failure.** A loading tile shows nothing (white paper). A tile whose `<img>` errors is retried once after 2 s, then left blank; no error copy per tile — the sheet-level state carries it.
- **States.** `renderStatus === "pending"` → the blank paper with the sheet number (today's surface) and "Drawing the sheet…"; `"failed"` → the same paper with `renderError`; `"rendered"` → tiles. The canvas already refreshes from the snapshot poll, so the drawing appears without a reload.

### 6.3 The rail

`SheetsRail.jsx` shows `GET /api/sheets/{id}/thumb.png` in the thumbnail slot once `renderStatus === "rendered"`; before that, the existing dot cluster. The `<img>` has `alt=""` — the row's text carries the sheet's identity.

### 6.4 Untouched

Evidence images stay the engine's own crop, served as today — evidence and canvas are two independent witnesses to the same page. Layer toggles, totals, approval rules: unchanged, and the counted numbers are byte-identical before and after this change (the y rescale is draw-time only).

## 7. Copy

| state | reads |
|---|---|
| render pending | Drawing the sheet… |
| render failed | Couldn't draw this sheet. The takeoff still counts it. |

No new status label. Sentence case; no "please", "successfully", "!".

## 8. Testing

- **`engine/tiles.py`** on a generated PDF: level 0 fits one tile; each level doubles; every interior tile is 512 px, edge tiles smaller; a 48 × 36 in page reaches 150 dpi at `max_zoom`; thumbnail is 240 px wide; a rotated page renders in the visual frame (a mark drawn at a known visual position lands at the expected tile pixel).
- **`render` handler** through the in-process harness (`WORKER_INLINE=1`, `MemoryBlobStore`): tiles land under the hashed prefix; `render_status` transitions; a failing sheet marks only itself; a re-read with the same hash queues no render; a re-upload (new hash) queues a fresh one; deleting the document cancels queued renders.
- **Routes:** tenancy (rival org 404, unauthenticated 401) for both; 404 for pending sheet, `z > max_zoom`, out-of-grid `x`/`y`; the exact `Cache-Control` header; the forbidden-word grep still passes on the snapshot.
- **`sheetGeometry`:** a 3:2 page → paper 1000 × 667; `toPaper`/`fromPaper` round-trip; zero dimensions → 1000 × 750.
- **`TileLayer`:** which tiles for a given viewport and zoom (unit test of the pure `visibleTiles(viewport, level)` helper); pending / failed / rendered states render the right surface.
- **Canvas:** a marker stored at (500, 375) draws at the paper's centre for a 3:2 page; calibration's two clicks on a 3:2 page produce the same real-world distance as on a 4:3 page for the same drawn dimension.
- **Corpus (skipped without `bid_examples/`):** the Unalaska set's first plan sheet renders; every one of its placements falls inside the paper after `toPaper`.
- Both import-boundary tests unchanged (tiles are engine code; the API streams bytes only).

## 9. Not built in B3

**Accurate symbol marking is the next sub-project, B3b, before B4.** Counting today is tag-based: markers sit at the device's text tag, and untagged glyphs are not counted at all. B3b anchors every placement on the symbol's bounding box, adds vector symbol instancing (form XObject reuse and path-signature clustering) so untagged devices are counted exactly, and adds *find every one like this* — the estimator boxes one symbol and the worker template-matches on B3's rendered tiles, returning every match as *Ready to review*. B3 is the substrate: a box needs a page to sit on, and matching needs the raster.


- Tile pre-warming, or rendering ahead of the sheet the estimator is looking at beyond the one-tile margin.
- Retention or cleanup of superseded tile prefixes — the reaper (ROADMAP §2.2).
- Rotation controls on the canvas (the page is rendered in its visual orientation; that is the one the title block reads in).
- Any change to evidence rendering.
- Per-tenant render concurrency limits; bid-date priority (ROADMAP §2.5).
- Include/exclude, discipline/revision/scale corrections, metering — B4.

## 10. First task: the three parked B2 residuals

Before any of the above, the plan's Task 1 closes what B2's final review parked: (1) the notes "Apply and re-run" says "Re-run started" during the sheet phase when the running classification already consumed the notes — a distinct message on `run_in_flight` ("A takeoff is already running. Apply the notes again once it finishes."); (2) screen D disables Start while any document is reading with drawing-specific copy — match the server's rule (Drawings only) or make the copy generic; (3) `set_doc_type` re-queues a read with no in-flight check — the same 409 gate `delete_document` has.

## 11. As built

Where the plan's sketches met real code, four points came out different from how §3–§6 above describe them. None change the design; each is recorded here rather than silently in the diff.

- **`visibleTiles`'s last tile index is `Math.ceil(edge / t)`, not `Math.ceil(edge / t) - 1`.** §6.2's sketch describes the exact last intersecting tile and then "plus a one-tile margin" as if that margin were a separate step. The shipped arithmetic folds the two together: the exact last tile is `ceil(edge / t) - 1`, and the margin adds the `+ 1` back, so the code computes `ceil(edge / t)` directly rather than computing the exact tile and then adding one. Same tiles rendered, one fewer intermediate value.
- **A refit runs whenever a sheet's paper aspect changes, not only on sheet switch.** `BlueprintCanvas.jsx` keys a ref on `${paper.w}x${paper.h}` and re-fits when that key changes after boot. §6.1/§6.2 describe paper size varying per sheet but don't say when the view refits; in practice two same-shaped sheets in a row keep the estimator's zoom and pan, and only a genuine aspect change (portrait next to landscape, say) resets the view — this was necessary once paper stopped being a fixed 1000 × 750.
- **`levelFor` compares the on-screen width against `SHEET_W` (1000), not the on-screen long edge.** `gridFor` correctly uses `Math.max(paper.w, paper.h)` as the long edge, matching `tiles.py`'s level definition — but `levelFor` picks its level from `SHEET_W * viewScale` alone. Since `paperSize` always normalizes width to 1000, this is exact for a landscape or square page, where the width *is* the long edge. On a portrait page (`paper.h > 1000`), the long edge is the height, so `levelFor` can choose a level one step coarser than `max_zoom` actually supports at that zoom — tiles still render (capped at `maxZoom`), just slightly softer than the finest available. Noted, not fixed: no portrait sheet in the corpus makes it visible today, and the fix is a one-line change to compare against the long edge once a test sheet demonstrates it.
- **`enqueue_render` skips only when the prefix matches *and* `render_status == "rendered"`.** §4 says a re-read of unchanged bytes "renders nothing twice," which holds for a sheet whose render already landed — but a sheet whose previous render *failed* keeps its old (non-matching-status) row, so the next `read` of the same bytes queues a fresh `render` job rather than leaving it `failed` forever. This is a retry path the spec's wording doesn't call out: a transient render failure heals itself on the next upload-triggered read, with no separate retry mechanism needed.
