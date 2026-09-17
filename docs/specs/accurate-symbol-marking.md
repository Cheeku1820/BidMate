# B3b — Accurate symbol marking

**Date:** 2026-09-16
**Branch:** `feat/accurate-symbol-marking`, off `main` (B1, B2, B3 merged)
**Implements:** the B3b sub-project named in `docs/specs/drawing-behind-the-markers.md` §9, between B3 and B4. Roadmap: Counting on exploded vector geometry (ROADMAP §2.1 "Symbol detection"; BUILD-STAGES "Counting method", stage 2 column) and *find every one like this* (BUILD-STAGES stage 1).

## 1. What this changes

Counting today is tag-based (`engine/counting.py`): it finds device tags in the text layer (`TAG = ^[A-Z]{1,3}\d{0,2}$`, three or more placements), so a marker sits on the tag's text, not on the symbol beside it, and a device drawn without a tag is never counted. On the corpus that is most of them: every vector set is Tier B — exploded geometry, no reusable symbol definitions (`page.get_xobjects()` is empty on all of them), 300–4,600 small path fragments per plan sheet. Unalaska E1.1 has ~1,900 small glyph fragments and zero tagged devices; today it counts nothing.

Three changes, one idea. A **symbol signature** — a hash of a small group of paths after normalising position, scale-independent quantisation, and orientation — identifies identical glyphs exactly, the way a block reference would on a Tier A set.

1. **Every placement carries the glyph's box.** The marker ring sits on the symbol, the evidence crop is the symbol, and a selected item outlines every one of its instances.
2. **Counting emits shape clusters beside tag clusters**, links them where a tag labels a glyph, and hands untagged clusters to Classification like any other. Counting still does not know what anything is.
3. **Find every one like this.** The estimator boxes one symbol on the canvas; a `match` job finds every instance — by signature on a vector sheet, by normalised cross-correlation on B3's render otherwise — and the estimator names the result before anything is counted.

Nothing about totals, statuses, or layer toggles changes. Counting stays tested, not trained: every rule below is a constant with a fixture asserting it, never a learned weight.

## 2. Data model

Migration `0023_symbol_matches`, reversible (the downgrade deletes `match` jobs before dropping the kind, as 0022 does for `render`).

**Placements.** `Item.placements` (JSONB) entries become `[x, y, w, h]` in sheet units — centre and extent, ingest-normalised per axis exactly as `x, y` are today (`map_payload`; `w` against `width_pt` × 1000, `h` against `height_pt` × 750, rounded to int, minimum 1). Existing `[x, y]` rows stay valid: every reader treats a two-element entry as a point with no box. No backfill; the next Start takeoff rewrites the rows through `merge_sheet`. `Item.x/y` remain the first placement's centre.

**Contracts.** `Placement` gains `w: int = 0` and `h: int = 0` (page points, 0 = point only). `DeviceCluster` gains `exemplar: tuple[float, float, float, float] | None` — the page rect of one instance, for the crop Classification receives — and `linked_tag: str = ""` on a shape cluster absorbed by a tag cluster (kept for tests; never serialised).

**Symbol matches.**

```
symbol_matches
  id           uuid pk
  org_id       uuid fk orgs      not null
  project_id   uuid fk projects  not null
  sheet_id     uuid fk sheets    not null, cascade
  box          jsonb             [x, y, w, h] sheet units, as drawn
  status       str(20)           pending | found | failed   ck_symbol_matches_status
  matches      jsonb             [[x, y, w, h], …] sheet units; [] until found
  error        text default ''   estimator copy when failed
  created_by   uuid fk users
  created_at   timestamptz
  resolved_at  timestamptz null  set when accepted or discarded
```

`jobs.kind` gains `match` (`JOB_KINDS`, `ck_jobs_kind`, the migration's literal list); `jobs` gains `symbol_match_id uuid null`. `timeout_for("match")` = 60 s. `status` is a match's own axis — never a review label.

**Items from a match** carry `source_tag = "match:<match id>"`. `merge_sheet` never writes a `match:` tag, so a re-run can neither duplicate nor delete them; `drop_sheets` treats them like approved items (a sheet with match items is kept, marked `PAGE_GONE`).

## 3. Glyphs and signatures — `engine/glyphs.py`

Pure PyMuPDF and the standard library. No database, no model, no OpenCV. Every constant below was set by measuring the corpus (Unalaska E1.1/E2.1, Kittles EP101, United Utility E-101), not tuned against a score; the tests in §10 pin them.

**Paths.** `page.get_drawings()`, every point moved to the visual frame (`page_frame`), bbox computed from the points (PyMuPDF's `rect` for a vertical line is empty and unions to nothing). Three facts about electrical drafting decide what is kept:

- **Ink.** The architectural underlay is screened — drawn in grey — and the electrical work is full-tone. A path whose stroke (or fill, when it has no stroke) has luminance > `MAX_INK_LUMINANCE = 0.4` (`0.299 R + 0.587 G + 0.114 B`) is background and never a glyph. On Unalaska E2.1 this alone removes 20 of 33 clusters, all of them truss braces and door swings.
- **Size.** A path ≤ `MAX_GLYPH_PT = 40` on both sides may belong to a glyph; a candidate (below) needs ≥ `MIN_GLYPH_PT = 3` on both sides, so a pair of collinear dashes (0 × 4.6 pt) is never a symbol.
- **Shape.** A candidate must contain a curve, a closed path, or a fill, or else ≥ `MIN_STRAIGHT_PATHS = 3` straight segments. Two dashes meeting at a corner of a dashed wall are not a device; a filled arrowhead or an open circle is.

**Candidates.** Paths bucketed on an 8 pt grid; union-find over pairs whose bboxes overlap or come within `TOUCH_PT = 0.5`. A candidate with more than `MAX_PATHS = 24` paths (hatch, a north arrow) is dropped, and so is one whose bbox contains the centre of any text word — the tag beside a glyph does not overlap it; a room-number box does.

**Same shape.** Two candidates are the same glyph when, under one of the eight dihedral transforms (four rotations, each mirrored), they have the same number of paths, each path pair has the same fill/stroke/closed flags and point count, and every point matches a point of its pair within `TOL_PT = 0.35` after translating both to their bbox origin. Exact hashing was tried first and split identical receptacles into two clusters over 0.02 pt of floating-point jitter; nearest-point matching under a tolerance is what the corpus needs. Comparison is cheap because candidates are bucketed first on a coarse key `(path count, sorted per-path point counts, round(long side), round(short side))`. Fill and stroke are part of sameness (a filled circle and an open one are different devices); size is not normalised (a duplex and a quad receptacle differ by size on many keys).

**Clusters and signatures.** Candidates are compared in page order against each bucket's exemplars; a match joins that exemplar's cluster, a miss starts a new one. A cluster's `signature` is `sha256` of its exemplar's canonical form (translated to the origin, quantised to 0.25 pt, sorted, the lexicographically smallest of the eight transforms), first 8 hex — stable for the same file across runs, which is what `source_tag = "shape:<signature>"` needs for the merge key.

```python
@dataclass
class Glyph:
    rect: tuple[float, float, float, float]   # page points, visual frame
    forms: list[Form]                         # the eight dihedral forms, for same_shape
    key: tuple                                # the coarse bucket

@dataclass
class ShapeCluster:
    signature: str
    members: list[Glyph]

def glyphs_on(page, region, words) -> list[Glyph]
def same_shape(a: Glyph, b: Glyph) -> bool
def cluster(glyphs, min_instances=3) -> list[ShapeCluster]
def glyph_in(page, rect, words) -> Glyph | None       # the one candidate inside a drawn box, if any
def matches_of(glyph, glyphs) -> list[Glyph]           # every glyph the same shape as `glyph`, itself included
```

**Fixtures.** A cluster whose members sit at nearly the same page coordinates (within `FIXTURE_PT = 2`) on ≥ 60 % of the set's plan sheets is a border or legend fixture, not a device — `count()` drops it before returning (a one-sheet set has no fixtures to drop). Candidates outside the sheet's `region` (title block, border) and inside the stamp (`_stamp_points`) are excluded, as tag placements are today.

**Measured.** Unalaska E1.1: 7 clusters, 176 placements; E2.1: 13 clusters, 180 placements (a 37-instance junction box, 31 switches drawn as `$`); Kittles EP101: 5 clusters, 212 placements (80 + 72 duplex receptacles in two orientations, 43 boxed, 14 quad); United Utility E-101: 4 clusters, 138 placements (a 120-instance receptacle). Under 2 s per sheet.

## 4. Counting — `engine/counting.py`

`count_sheet` runs today's tag counter, then:

1. `glyphs_on(page, sheet.region, words)` → `cluster(...)` → one `DeviceCluster(tag="shape:<signature>", exemplar=members[0].rect, placements=[Placement(cx, cy, w, h)…])` per cluster with ≥ `MIN_PLACEMENTS` (3) members.
2. **Linking.** For every tag placement, the nearest glyph (any signature) whose centre lies within `LINK_FACTOR = 1.5` × the glyph's larger side of the tag's point. A shape cluster with ≥ `LINK_SHARE = 0.8` of its instances claimed by placements of one tag is that tag's glyph: the tag cluster's placements take those boxes (`w, h` from the glyph, centre moved to the glyph's centre), the shape cluster gets `linked_tag` and is removed from the output. A tag placement that matched nothing keeps `w = h = 0`. A shape cluster claimed by two tags below the share is left untagged — Classification sees it as its own device.
3. Output: tag clusters (now boxed) followed by the surviving shape clusters. Same `list[DeviceCluster]`; nothing downstream changes shape.

`count()` over a set applies the fixture drop across sheets before returning.

## 5. Classification of a shape cluster — `engine/classification.py`

A shape cluster has no tag to look up. `classify_run` renders each cluster's exemplar as a PNG crop (`documents.render_evidence_crop` at 300 dpi, padded 4 pt) and includes it in the one classification call, up to `MAX_CROPS_PER_SHEET = 20` per sheet (beyond that the largest clusters go first; the rest land unclassified). The prompt asks for a catalog item or `none` per crop, grounded in the sheet's legend entries and schedule text with the same verbatim-quote discipline as the tag call; the model's answer maps to status the same way (confidence stays server-side).

Without a key, or for `none`: the cluster becomes an item named **Unclassified symbol**, quantity = instance count, placements = the boxes, status *Needs attention*, with today's `_unknown_warning` reworded for a glyph (`found`: "A symbol appears {count} times on {sheet_no} but isn't in the legend."). The count is visible and reviewable; nobody's number silently omits it. Classification still never touches geometry; Counting still never names anything.

The merge key stays `(sheet number, source_tag)` with `source_tag = "shape:<hash>"` — stable across re-runs of the same file, so an estimator's edit to a shape cluster survives Start takeoff like any tag's does.

## 6. The `match` job — `worker/match_job.py`

Fifth job kind, same shape as the others: sandboxed child, `timeout_for("match")`, transient/terminal classification through `blobs.storage_errors`, never in the API process.

1. Load the `symbol_matches` row and its sheet; download the document to a tempfile (`blob_to_tempfile`).
2. Box → page points (`ingest.denormalize`, the inverse of `normalize_point`; new, next to it).
3. **Vector path.** `glyphs.glyph_in(page, rect, words)`. If a glyph is inside the box: `matches_of(glyph, glyphs_on(page, region, words))` — every glyph on the sheet the same shape, the boxed one included.
4. **Raster path** when `glyph_in` returns `None` (scanned page, a placed image, or a box drawn on plain lines). `engine/raster_match.py`: render the page greyscale at `MATCH_DPI = 200` (capped at 40 MP — lower the dpi to fit), crop the template, `cv2.matchTemplate(TM_CCOEFF_NORMED)` at 0°, 90°, 180°, 270°, keep peaks ≥ `MATCH_THRESHOLD = 0.80`, non-maximum suppression at half the template's size. The template itself always matches at its own location. Dependency `opencv-python-headless` in `api/requirements.txt` — imported only under `app.engine`, so the import-boundary tests (`app.main` imports no engine) cover it.
5. Write `matches` (sheet units, via `normalize_point`), `status = found`. A terminal failure writes `failed` with `copy.MATCH_FAILED`.

Both paths return `list[tuple[x, y, w, h]]` in page points; one function, `find_matches(path, page_index, sheet, rect)`, chooses.

## 7. The API — `app/matches/`

| Route | Does |
|---|---|
| `POST /api/sheets/{id}/matches` `{x, y, w, h}` | Org-scoped through the sheet's project. 409 `sheet_still_reading` if the document is not read; 409 `match_in_progress` if a pending match exists on the sheet; 422 if the box is outside 1000 × 750 or under 4 × 4 units. Creates the row and queues the job. Returns `SymbolMatchOut`. |
| `GET /api/symbol-matches/{id}` | The row: `id, sheet_id, box, status, count, matches, error`. Never a score, threshold, dpi, or method. |
| `POST /api/symbol-matches/{id}/items` `{name, catalog_item?}` or `{not_sure: true}` | Creates **one item** through `commit()` as one undoable action — the cluster model, exactly as Counting's output lands: `source_tag = "match:<id>"`, quantity = the match count, placements = the matches, `x, y` = the boxed one's centre. Named: *Ready to review*. Not sure: name "Unclassified symbol", *Needs attention*, the `_unknown_warning` glyph wording, `where` = the sheet number. 409 if already resolved or not yet `found`. Sets `resolved_at`. Returns the created item. |
| `DELETE /api/symbol-matches/{id}` | Discards: deletes the row (cascade none — items were never created). Audited, not undoable. 409 if resolved. |

Both GET and POST live in the tenancy tables (401 and cross-org 404 tests are table-driven). Item creation is a new write path but not a new rule: the items are ordinary rows, and every status rule (`rules.py`, server-authoritative) applies to them unchanged.

## 8. The client

**Placements.** `BlueprintCanvas.jsx` reads `[x, y, w, h]`: a marker's ring radius is `max(MIN_RING, hypot(w, h) / 2)` in paper units through `sheetGeometry`; a two-element placement uses the fixed ring. The selected item's instance rings (`selItem.placements`) outline each box. The minimap is unchanged (centres only).

**Tool.** A **Find like this** control next to Calibrate. Banner: "Drag a box around one symbol"; Esc cancels. The drag box is dashed blueprint blue; on release it is solid and the store calls `createMatch(sheetId, box)` (paper → sheet units via `fromPaper`). While pending, the banner reads "Searching this sheet…" and the store polls `getMatch(id)` at the existing cadence.

**Result.** Matches draw as hollow blueprint-blue boxes on the canvas — not markers; they have no status. The item panel shows the result card in place of the empty state:

- "**{N} matches found**" (tabular), the boxed crop rendered from the tiles at the box's location.
- A catalog picker (the same list the edit form uses) with a name field, and **Not sure yet**.
- **Add {N} to the takeoff** → `acceptMatch(id, {…})`; toast "Added 14 duplex receptacles from a drawn symbol" with Undo (one entry). **Discard** → `discardMatch(id)`.
- Zero other matches: "No other symbols like this were found" — the boxed one is still offered as an item of quantity 1.
- Failed: the `error` copy and **Try again**.

Store: `createMatch / getMatch / acceptMatch / discardMatch` in `api.js`; `useReviewStore` exposes `match` state `{ id, status, box, matches, count, error }` for the active sheet. Layer toggles never hide the result boxes and never touch totals; the result card disappears on sheet change (the match row stays and is offered again when the sheet is reopened).

## 9. Copy

`api/app/jobs/copy.py`: `MATCH_FAILED = "The symbol couldn't be searched for on this sheet. Draw the box again, or add the item by hand."`; `MATCH_UNAVAILABLE` for exhaustion (routed through `terminal_copy`, which also closes the parked render/sheet/classify exhaustion residual). Client strings in `src/lib/matchCopy.js`: `DRAW_PROMPT`, `SEARCHING`, `FOUND(n)`, `NONE_FOUND`, `ADDED(n, name)`. Sentence case; no "AI", no percentages, no "successfully".

## 10. Testing

- **Glyphs** (`tests/test_engine_glyphs.py`): a synthetic PDF built in the test with five identical circle-and-bar receptacles (three rotated, one mirrored, one jittered by 0.1 pt), a grey copy of the same glyph, a hatch (> 24 paths), a dashed-wall corner (two dashes), a lone line, and a text label overlapping one outline → one cluster of five, nothing else. Dihedral invariance, the tolerance, the 40 pt gate and 3 pt floor, the ink rule, the shape rule, the touch radius, fill-vs-stroke, and the fixture drop each get a unit.
- **Counting** (corpus tests skipped without `bid_examples/`): Unalaska E1.1 ≥ 5 shape clusters and ≥ 120 placements, E2.1 ≥ 8 and ≥ 120; Kittles EP101 ≥ 3 and ≥ 150; United Utility E-101 one cluster ≥ 100 — each at least two-thirds of what was measured, so a regression shows and jitter does not. Every existing tag count is unchanged; every box lies inside its visual page. Linking: a synthetic sheet with tag "A" beside each of five squares → one tag cluster of five, boxed, no shape cluster.
- **Ingest**: `[x, y, w, h]` normalises per axis; `[x, y]` still accepted; `w, h < 1` clamps to 1.
- **Match**: a synthetic vector sheet and a raster rendered from it return the same count; the raster path rejects a 0.6 correlation; NMS collapses adjacent peaks; org-scoped 404, both 409s, 422 on a bad box; the wire shape has no `score`; one `POST …/items` = one action row, one item of quantity N, one undo removes it; `merge_sheet` on a sheet with `match:` items leaves them; subprocess tests: `app.main` imports neither `app.engine` nor `cv2`.
- **Client**: drag → sheet units at two zoom levels; result boxes survive every layer toggle and totals do not change; two-element placements render with the fixed ring; the result card offers the boxed one as a quantity of 1 on zero matches.

## 11. Not built in B3b

- A firm symbol library — matches and shape clusters are project-scoped; cross-project defaults wait on the propagation decision (ROADMAP open decisions).
- A trained detector for scanned sets (stage 3), and OCR on raster sheets.
- Matching across sheets or the whole set — one sheet per request. Set-wide is the obvious next step once one sheet is trusted.
- Editing one placement's box by hand, or splitting a shape cluster Counting merged.
- Scale-normalised signatures (a glyph drawn at two sizes is two clusters, deliberately).
- Match-item evidence crops beyond the canvas box (the tile render is the witness).
