# Blueprint backdrop and real evidence

## Why

The canvas currently tries to show the estimator their actual drawing by
streaming a full page image from the engine's in-memory PDF store and
stretching it under the markers. Investigating it surfaced three separate
problems, not one:

1. **The drawing disappears.** `estimate_service.py` keeps uploaded PDFs
   in a 6-entry in-memory LRU (`_PDF_STORE`). Two of the three takeoffs in
   the current dev database already 404 on `/sheet-image` — evicted or
   gone after a restart. Markers are then drawn on blank paper with no
   indication anything is missing.
2. **The sheet number is wrong.** `_sheet_number()` in `documents.py`
   picks whichever E-number repeats most *anywhere in the page's text*,
   so a callout bubble referencing another sheet can outvote the title
   block. Verified against a real set: page 86 is labeled E5.1 in the
   sheet rail; the page itself is E1.2, a demolition plan. An estimator
   navigating to "E5.1" lands on the wrong drawing.
3. **"Source evidence" doesn't exist today.** `Item.evidence` (the JSONB
   column `ItemDetailPanel.jsx` reads as `sel.evidence.detail` /
   `sel.evidence.sheet`) is never written anywhere in the backend —
   confirmed by grep, no writer exists. Every real item has `evidence:
   null`, so the "View evidence" button never renders, and the decorative
   sketch in `MiscModals.jsx`'s evidence dialog is unreachable dead code.
   CLAUDE.md is explicit that "every quantity needs traceable evidence,"
   and today there is none.

Chasing full-page fidelity (correct aspect, adequate DPI at deep zoom,
persistent storage so it survives eviction) is real platform work —
`ROADMAP.md` §2.1/§2.2 already lists page tiling and document storage as
unbuilt Track 2 infrastructure. This spec does not build that. Instead it
separates two jobs the single background image was trying to do at once:

- **Orientation** — knowing roughly where an item sits while scanning the
  sheet. Real marker coordinates already provide this; no backdrop image
  is required to serve it.
- **Proof** — confirming a specific count against the actual drawing.
  This is what "evidence" is for, and it only needs a small, exact crop
  around the item in question, not the whole page.

## Scope

**In:**
- Drop the whole-sheet raster background from the canvas.
- Generate a real per-item evidence image (a crop of the source PDF page)
  during processing, while the file is still open, and persist it
  independently of the ephemeral full-PDF cache.
- Serve that crop from a new endpoint; wire it into the item panel and
  evidence dialog, replacing the placeholder sketch.
- Populate `Item.evidence` for the first time, so the button that has
  never rendered for real data starts doing so.
- Fix `_sheet_number()` to read only the title-block region.
- Remove code that no longer has a caller once the raster background is
  gone (`/sheet-image`, the two dead `render_page_png*` variants, the
  `_PDF_STORE` LRU, and — found during investigation — `WarehousePlan`
  and `OfficePlan` in `PlanDrawing.jsx`, seed-only fixtures that no data
  path can reach since `sheet.plan` is always `""` for an ingested sheet).

**Out:**
- Persistent document storage, page tiling, or anything that keeps the
  full PDF around after the request that processed it. Track 2 work.
- Evidence for measured/polyline items. No current engine output ever
  populates `Item.path` — homerun/conduit measurement isn't built
  (`ROADMAP.md` §2.1) — so there is nothing to crop for a run today. The
  crop function only handles point/cluster items.
- Any change to `WarningReason`, the warning schema, or the four-field
  warning UI. Untouched.

## What the canvas backdrop becomes

No new component work here — an honest blank surface already exists.
`PlanDrawing.jsx`'s `IngestedSheetSurface` (reached whenever `sheet.plan
=== ""`, which is every real sheet) already renders nothing but the sheet
number centered on the paper. It's simply covered today by the raster
`<image>` layer. Removing that layer is enough:

- `BlueprintCanvas.jsx`: delete the `sheetImageUrl` prop and the
  conditional `<image href={sheetImageUrl} .../>` block. `PlanDrawing`
  stays exactly where it is, underneath the markers.
- `CanvasPane.jsx` / `Workspace.jsx`: stop constructing
  `http://localhost:8100/sheet-image?...` and stop passing
  `sheetImageUrl` down.
- `PlanDrawing.jsx`: delete `WarehousePlan`, `OfficePlan`, and their
  private helpers (`GridBubble`, `DimString`, etc., if nothing else uses
  them) — dead since the seed store was removed. Keep
  `IngestedSheetSurface` as the sole export path.

Markers, glyphs, status rings, warning badges, layer toggles, the
minimap, and the legend are untouched — none of them depended on the
image.

## Real evidence: architecture

### Where the crop is generated

The source PDF only exists on disk during the request that processes it
(`estimate_project_endpoint`'s temp file, deleted in its `finally`
block). The crop must be produced synchronously during that same
request, while `path` is still valid — there is no later chance.

Add to `api/app/engine/documents.py`:

```python
EVIDENCE_POINT_RADIUS_PT = 90
EVIDENCE_CLUSTER_MARGIN_PT = 40
EVIDENCE_MAX_BBOX_PT = 600      # beyond this, keep every placement in
                                 # frame and let zoom shrink instead of
                                 # cropping placements out
EVIDENCE_MAX_PX = 640           # longest output edge
EVIDENCE_MIN_ZOOM = 0.5

def render_evidence_crop(
    path: str, page_index: int, page_width_pt: float, page_height_pt: float,
    placements: list[tuple[float, float]],
) -> bytes | None:
    """A tight PNG crop of the source page around one item's counted
    location(s), for the item panel's evidence view. Point items get a
    fixed radius around their one coordinate; a multi-placement cluster
    gets the bounding box of every placement plus a margin, so the crop
    shows the group Counting actually found rather than one instance of
    it. Returns None on any failure -- a missing crop must never fail
    the takeoff (same principle as the vision pass beside it)."""
```

Implementation: bounding box from `placements` (radius-expanded for a
single point), clamped to `[0, 0, page_width_pt, page_height_pt]`, capped
at `EVIDENCE_MAX_BBOX_PT` per side without discarding any placement,
zoom computed as
`clamp(EVIDENCE_MAX_PX / max(bbox_w, bbox_h), EVIDENCE_MIN_ZOOM, 4.0)`,
rendered with `page.get_pixmap(clip=..., matrix=pymupdf.Matrix(zoom,
zoom))`. Wrapped in `try/except -> None`.

A cluster spread across most of a sheet (rare — `counting.py`'s
`MIN_PLACEMENTS` and tag-locality already favor compact groups) renders
at low zoom in its own crop. Same legibility ceiling full-page rendering
had, scoped to one item instead of the whole product surface. Accepted
for this pass.

### Wiring through the engine

`estimate.py`'s `_compute()` already holds `path` and builds one row per
cluster in `_row_from_spec` / `_row_from_catalog`. After building `rows`
(still inside `_compute`, before it returns), add one pass that calls
`render_evidence_crop` per row using that row's `sheet_page_index` /
`placements`, and sets:

```python
r["evidence_png_b64"] = base64.b64encode(png).decode("ascii") if png else None
```

Only `full_takeoff()` (the per-cluster path that feeds the real review
store) needs this — `estimate()` (the consolidated Instant-estimate
summary) has no canvas and no per-item panel, so it does not carry crops.

### Storage: a separate table, not a new `Item` column

`Item` rows are already snapshotted wholesale on delete —
`snapshots._column_snapshot()` walks *every* mapped column via
`sa_inspect`, and this codebase has already hit "a new `Item` column
breaks `decode_snapshot()`" twice during the API-only-foundation work.
Raw PNG bytes on `Item` would also bloat every `Action.before`/`after`
JSONB row on every edit/approve/reject, not just deletes, and isn't
JSON-encodable without new handling in `encode_snapshot`.

Instead, a new one-row-per-item table that the snapshot/undo machinery
never touches, because nothing about it is ever undone — it's a cache of
what the drawing showed, not reviewable state:

```python
class ItemEvidenceImage(Base):
    __tablename__ = "item_evidence_images"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    png: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

Migration `0013_item_evidence_images.py`. `ON DELETE CASCADE` means
deleting an item (or undoing its way back through a delete, which
recreates the `Item` row with a new/reused id via `undo_apply.py`) does
not restore a lost evidence image — the row starts with none, same as
any item that had none to begin with. Documented limitation, not a
correctness bug: nothing about the image is reviewable state, so its
absence after an undo round-trip reads the same as "no evidence
recorded," which is always an honest state for this column.

### `ingest.py`: decode, and populate `evidence` for the first time

`map_payload()` currently builds each item dict without ever touching
`evidence`. Add:

```python
png_b64 = raw.get("evidence_png_b64")
n_places = len([p for p in (raw.get("placements") or []) if isinstance(p, (list, tuple)) and len(p) >= 2]) or 1
```

and, in the same dict literal the loop already builds (after `"warning":
...`, using the sheet number already resolved earlier in the same loop
iteration for `"sheet_key"`):

```python
"evidence": {
    "detail": f"Counted from the drawing at {n_places} location{'s' if n_places != 1 else ''}",
    "sheet": next(s["number"] for s in sheets if s["key"] == key),
    "has_image": bool(png_b64),
},
"evidence_png": base64.b64decode(png_b64) if png_b64 else None,
```

`evidence_png` is consumed by the insert layer (below), not stored on
`Item` itself — `MappedTakeoff.items` stays a plain list of dicts, so
this is just one more transient key the caller pops off before
constructing the `Item` row.

### Insert layer: one shared upsert, called from both ingest paths

Both first-time ingest (`ingest_service.py`) and a re-run's merge
(`reprocess.py`, both the "insert new" and the "`_overwrite()` matched
item in place" branches) need the same behavior: after an `Item` row has
its id, replace whatever evidence image row existed for it.

```python
def upsert_evidence_image(db: Session, item_id: uuid.UUID, png: bytes | None) -> None:
    """Replace item_id's evidence image, or clear it if `png` is None
    (a re-run whose crop failed this time must not leave a stale image
    from a previous run silently misrepresenting the current takeoff)."""
    db.query(ItemEvidenceImage).filter_by(item_id=item_id).delete()
    if png is not None:
        db.add(ItemEvidenceImage(item_id=item_id, png=png))
```

Call it once per item, right after that item's row is flushed (both on
first ingest and inside `reprocess._overwrite()`), passing the
`evidence_png` bytes popped out of the mapped dict.

### Serving it

New route, `api/app/takeoff/mutations.py` (alongside the other
`/items/{item_id}/...` routes):

```python
@router.get("/items/{item_id}/evidence-image")
def get_item_evidence_image(item_id: uuid.UUID, db: DbSession, user: User):
    item = load_item(item_id, db, user)  # tenancy gate, existing helper
    row = db.get(ItemEvidenceImage, item.id)
    if row is None:
        raise not_found()
    return Response(content=row.png, media_type="image/png",
                     headers={"Cache-Control": "max-age=86400, immutable"})
```

Immutable cache lifetime is safe: an image is only ever replaced by
`upsert_evidence_image`, which is a brand new resource from the
browser's point of view only if the frontend also busts the URL on
re-run (see below).

### Frontend

- `src/lib/store/api.js` / `api-mapping.js`: no new fields needed beyond
  what `mapItem` already carries (`evidence`) — that key was already
  wired through, it was just always `null`. Add a helper that builds the
  image URL from the item id, e.g. `evidenceImageUrl(item)` returning
  `${API_BASE}/items/${item.id}/evidence-image` when
  `item.evidence?.has_image` when present, else `null` (the wire dict is
  passed through unmodified today, same as `detail`/`sheet` already are —
  no key renaming). Because a re-run can replace an item's image while
  its id persists across an approval-preserving merge, append a cache-
  busting query param (`?v=<item.updatedAt>`, which already changes on
  any server-side rewrite) rather than relying on browser revalidation.
- `ItemDetailPanel.jsx`: unchanged gating logic (`sel.evidence ? ... :
  "No evidence recorded"`) — it starts rendering today because
  `evidence` is finally non-null for classified items.
- `MiscModals.jsx`'s evidence dialog: replace the fabricated `<svg>`
  sketch with `<img src={evidenceImageUrl(item)} alt={...} />` inside the
  existing modal chrome. On image load failure (network hiccup, or an
  item whose crop generation failed this run despite `has_image` being
  stale — shouldn't happen given the upsert-clears-on-None behavior
  above, but the UI should not break if it does), fall back to the same
  "No evidence recorded for this item" text the panel already uses
  elsewhere, via `onError`.

## Sheet number fix

`documents.py`'s `_sheet_number()` searches the whole page's text.
Change it to search only the title-block region first, falling back to
the whole page only if the title block yields nothing (some sets don't
have machine-readable text in a consistent title-block box):

```python
TITLE_BLOCK_STRIP = 0.18  # right-hand fraction of the page width

def _sheet_number(page: pymupdf.Page, text: str) -> str:
    w, h = page.rect.width, page.rect.height
    tb_text = page.get_text("text", clip=pymupdf.Rect(w * (1 - TITLE_BLOCK_STRIP), 0, w, h))
    ids = SHEET_ID.findall(tb_text)
    if not ids:
        ids = SHEET_ID.findall(text)
    if not ids:
        return ""
    return max(set(ids), key=ids.count)
```

Callers pass `page` now, not just `text` — `detect_sheets()` already has
`page` in scope at both call sites.

## `estimate_service.py` cleanup

Once nothing calls it:
- Delete `/sheet-image` (the route), `_PDF_STORE`, `_PDF_STORE_CAP`,
  `_remember_pdf`.
- Delete `documents.render_page_png` (already has zero callers today —
  found during investigation, unrelated pre-existing dead code) and
  `documents.render_page_png_bytes` (caller removed by this spec).
- `_read_sheets_with_vision` still needs the raw PDF bytes for the
  vision pass, but only within the single request that produced them —
  it no longer needs a module-level, cross-request cache to get them.
  Change `estimate_project_endpoint` to build a local `dict[takeoff_id,
  bytes]` for the duration of the request and pass it directly into
  `_read_sheets_with_vision(merged_sheets, pdf_bytes_by_id)`, replacing
  the `_PDF_STORE.get(...)` lookup inside it. `takeoff_id` stays on each
  sheet (still needed to keep drawings distinct when merging documents,
  per the existing `merged_sheets` comment) — only the global store goes
  away.

## Testing

**Backend:**
- `documents.render_evidence_crop`: point-item radius crop, multi-
  placement bounding-box crop, oversized-bbox zoom-down behavior, clamp
  to page rect at a corner/edge, `None` on a bad page index.
- `documents._sheet_number`: a synthetic page where a callout bubble's
  reference number appears more often in body text than the title
  block's own number — assert the title block wins (this is the exact
  failure mode found in the real set: E5.1 in the rail, E1.2 on the
  page).
- `ingest.map_payload`: `evidence` populated with correct `detail`/
  `sheet`/`has_image`; `evidence_png` correctly base64-decoded, absent
  key producing `None` rather than a `KeyError`.
- `ingest_service` / `reprocess`: `upsert_evidence_image` called on
  first ingest and on both reprocess branches (insert + overwrite-in-
  place); a re-run whose crop failed clears a previously-set image
  rather than leaving the old one.
- New endpoint: 200 with correct bytes and content-type for an item that
  has one, 404 for an item that doesn't, 404 (via `load_item`'s existing
  cross-org check) for another org's item id.
- `snapshots.py` / undo: confirm `ItemEvidenceImage` is *not* part of
  `ITEM_SNAPSHOT_TYPES` and that deleting-then-undoing an item does not
  attempt to touch it (no crash, item comes back with no image).

**Frontend:**
- `BlueprintCanvas.test.jsx` (or wherever it lives): no `sheetImageUrl`
  prop, no `<image>` element, `IngestedSheetSurface`'s sheet-number text
  renders.
- `PlanDrawing` tests: `WarehousePlan`/`OfficePlan` paths removed;
  confirm nothing regresses for `sheet.plan === ""`.
- `ItemDetailPanel` / evidence modal: renders the evidence button when
  `evidence` is present, renders the fallback text when absent, shows an
  `<img>` with the right `src` when `has_image` is true, falls back to
  text on `onError`.
- Re-grep `ProjectOverview.test.jsx` and `shell/nav.test.jsx` (both
  matched "evidence" in an initial repo-wide search) before this work
  starts — likely incidental matches on unrelated copy, but confirm
  before assuming so.

## Known limitations after this ships

- The full-page backdrop is gone, not fixed. A future page-rendering /
  tiling feature (Track 2) can reintroduce it against persistent
  document storage; this spec deliberately does not attempt a smaller
  version of that.
- Evidence crops exist only for items the engine produced with real
  placement coordinates. An item added or edited by hand (no engine
  origin) has no image, same as it has no coordinates today.
- An evidence image lost via delete + undo is not restored (see the
  `ON DELETE CASCADE` note above).
- Measured/polyline evidence stays unbuilt, matching `Item.path` staying
  unpopulated by any current engine output.
