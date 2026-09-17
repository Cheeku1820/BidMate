# Accurate Symbol Marking (B3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-09-16
**Spec:** `docs/specs/accurate-symbol-marking.md`
**Branch:** `feat/accurate-symbol-marking` off `main`, worktree `.worktrees/accurate-symbol-marking`

**Goal:** Every placement carries its glyph's box; Counting finds untagged device glyphs on exploded vector sheets by shape and links them to their tags; the estimator can box one symbol and have every instance on the sheet found, then name it before it is counted.

**Architecture:** `engine/glyphs.py` (pure PyMuPDF) turns a page's small full-tone paths into glyph candidates and clusters them by tolerant dihedral shape comparison; `counting.py` emits those as `shape:<signature>` clusters beside tag clusters and links the two; Classification takes a crop per shape cluster. A fifth job kind, `match`, runs the same glyph code (or OpenCV template matching on a render, for raster) for one drawn box, and a new `app/matches/` router creates the resulting item through `commit()` as a new reversible `add` action.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PyMuPDF 1.28, `opencv-python-headless` (worker only), pytest; React 18, vitest + testing-library.

## Global Constraints

Copied from the spec; every task's requirements include these.

- **The API process never opens a PDF and never imports `app.engine` or `cv2`.** `app.main` imports neither; `app.worker` imports no router. Both subprocess tests (`tests/test_api_import_boundary.py`, `tests/test_worker_import_boundary.py`) must stay green, and Task 6 extends the API one to `cv2`.
- **Counting is tested, not trained.** Every threshold is a named module constant with the exact value from the spec: `MAX_INK_LUMINANCE = 0.4`, `MAX_GLYPH_PT = 40`, `MIN_GLYPH_PT = 3`, `MIN_STRAIGHT_PATHS = 3`, `TOUCH_PT = 0.5`, `MAX_PATHS = 24`, `TOL_PT = 0.35`, `FIXTURE_PT = 2`, `LINK_FACTOR = 1.5`, `LINK_SHARE = 0.8`, `MIN_PLACEMENTS = 3` (existing), `MAX_CROPS_PER_SHEET = 20`, `MATCH_DPI = 200`, `MATCH_THRESHOLD = 0.80`, `timeout_for("match") = 60`.
- **Counting does not know what anything is; Classification never touches geometry.** Shape clusters are unlabelled `DeviceCluster`s with `tag = "shape:<8 hex>"`.
- **Nothing on the wire names a score, threshold, dpi, method, model, confidence, job id, attempt, or exception class.** `SymbolMatchOut` carries exactly `id, sheet_id, box, status, count, matches, error`.
- **Four review labels, never a fifth.** A match's `status` (`pending | found | failed`) and result boxes are their own axis: result boxes are hollow blueprint blue, never a status colour; a match item lands *Ready to review* when named, *Needs attention* with the `legend` warning when not sure.
- **Nothing counted without a person.** A match creates no item until `POST /api/symbol-matches/{id}/items`; that creates **one item** of quantity N through `commit()` as one undoable `add` action.
- **Layer toggles never change totals.** Result boxes ignore layer toggles and are not items.
- **Placements:** wire and JSONB shape `[x, y, w, h]` in 1000 × 750 sheet units (`w, h ≥ 1`); a two-element `[x, y]` remains valid everywhere and means "no box". `Placement.w/h` in page points, `0` = point only.
- **Copy:** sentence case, no "AI", no exclamation marks, no "please", no "successfully", no percentages. Server strings live in `api/app/jobs/copy.py`; client strings in `src/lib/matchCopy.js`.
- **Merge:** `source_tag = "match:<match id>"` items are never written, matched, or deleted by `merge_sheet`; `drop_sheets` keeps a sheet that holds one, marked `PAGE_GONE`.
- **Tenancy:** every new route goes through `load_sheet` / `load_project` and appears in `tests/test_tenancy.py`'s `TENANCY_TABLE`.
- Backend tests run from `api/` with `../.enginevenv/bin/python -m pytest` (the main checkout's venv at `/Users/nikhit/Documents/takeoff-review/.enginevenv` if the worktree has none); Postgres from `docker compose up -d postgres`. Corpus tests skip without `bid_examples/` (symlinked into the worktree). Frontend: `npm test -- --run`, `npm run build`.
- Commit messages: imperative, one line of what changed, ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File structure

| File | Responsibility |
|---|---|
| `api/app/engine/contracts.py` | `Placement(x, y, w=0, h=0)`, `DeviceCluster.exemplar/linked_tag` |
| `api/app/engine/glyphs.py` (new) | paths → candidates → clusters; `same_shape`, `glyph_in`, `matches_of` |
| `api/app/engine/counting.py` | shape clusters beside tag clusters; linking; fixture drop |
| `api/app/engine/classification.py`, `llm.py` | shape-cluster classification with crops; glyph wording |
| `api/app/engine/raster_match.py` (new) | OpenCV template matching on a page render |
| `api/app/engine/rows.py`, `sheet.py`, `documents.py` | 4-element placements through rows and the evidence crop |
| `api/app/takeoff/ingest.py` | normalise `[x, y, w, h]`; `denormalize_box` |
| `api/app/takeoff/models.py`, `migrations/versions/0023_symbol_matches.py` | `SymbolMatch`, `Job.symbol_match_id`, `match` kind |
| `api/app/jobs/{schemas,copy,queue}.py` | timeout, copy, `enqueue_match`, `terminal_copy` |
| `api/app/worker/{classify_job,sheet_job,match_job,handlers}.py` | crops for shape clusters; boxes through the payload; the match handler |
| `api/app/takeoff/{merge,undo,undo_apply,review}.py` | `match:` protection; the `add` action and its undo |
| `api/app/matches/{router,schemas,service}.py` (new) | the four routes |
| `src/lib/store/api.js`, `api-mapping.js`, `src/lib/useReviewStore.js`, `src/lib/matchCopy.js` (new) | client store + copy |
| `src/components/BlueprintCanvas.jsx`, `CanvasPane.jsx`, `Workspace.jsx`, `ItemDetailPanel.jsx`, `MatchResultCard.jsx` (new) | the tool, the boxes, the result card |
| `docs/specs/accurate-symbol-marking.md` §12, `CLAUDE.md`, `README.md`, `docs/README.md` | as-built notes |

---

### Task 1: Placements carry a box end to end

**Files:**
- Modify: `api/app/engine/contracts.py:36-40` (`Placement`), `:43-53` (`DeviceCluster`)
- Modify: `api/app/engine/rows.py:200-202`, `:245-247`
- Modify: `api/app/engine/sheet.py:116-117`
- Modify: `api/app/engine/documents.py:416-470` (`render_evidence_crop`)
- Modify: `api/app/takeoff/ingest.py:180-186`, `:382-386`
- Modify: `api/app/worker/classify_job.py:125-126`, `api/app/worker/sheet_job.py:67-68`
- Test: `api/tests/test_engine_contracts.py`, `api/tests/test_ingest_mapping.py`, `api/tests/test_estimate_evidence.py`

**Interfaces:**
- Produces: `Placement(x: int, y: int, w: int = 0, h: int = 0)`; `DeviceCluster(tag, sheet_page_index, placements, exemplar: tuple[float, float, float, float] | None = None, linked_tag: str = "")`; row `"placements": [[x, y, w, h], …]` (page points, w/h 0 when unknown); ingest stores `[x, y]` when `w == h == 0`, else `[x, y, w, h]` with `w, h ≥ 1`; `ingest.denormalize_box(box, width_pt, height_pt) -> tuple[float, float, float, float]` (sheet units → page-point rect `(x0, y0, x1, y1)`); sheet-job payload clusters `{"tag", "placements": [[x, y, w, h]]}`.

- [ ] **Step 1: Failing contract and ingest tests**

Append to `api/tests/test_engine_contracts.py`:

```python
def test_placement_defaults_to_a_point():
    from app.engine.contracts import Placement
    p = Placement(10, 20)
    assert (p.w, p.h) == (0, 0)


def test_device_cluster_has_no_exemplar_by_default():
    from app.engine.contracts import DeviceCluster
    c = DeviceCluster(tag="R", sheet_page_index=0)
    assert c.exemplar is None and c.linked_tag == ""
```

Append to `api/tests/test_ingest_mapping.py` (use the module's existing payload helper if it has one; otherwise this minimal payload):

```python
def _payload_with(placements):
    return {
        "sheets": [{"key": "0", "number": "E2.1", "title": "", "discipline": "Electrical", "scale": "",
                    "width_pt": 2000, "height_pt": 1500, "kind": "plan"}],
        "items": [{"sheet_id": "0", "name": "Duplex receptacle", "system": "Power", "quantity": 2, "unit": "ea",
                   "status": "ready", "x": 1000, "y": 750, "placements": placements, "warning": None,
                   "source_tag": "R"}],
    }


def test_boxed_placements_normalise_per_axis_with_a_floor_of_one():
    from app.takeoff.ingest import map_payload
    mapped = map_payload(_payload_with([[1000, 750, 20, 30], [10, 10, 0.5, 0.5]]))
    assert mapped["items"][0]["placements"] == [[500, 375, 10, 15], [5, 5, 1, 1]]


def test_point_placements_stay_two_element():
    from app.takeoff.ingest import map_payload
    mapped = map_payload(_payload_with([[1000, 750, 0, 0], [200, 150]]))
    assert mapped["items"][0]["placements"] == [[500, 375], [100, 75]]


def test_denormalize_box_is_the_inverse_of_normalisation():
    from app.takeoff.ingest import denormalize_box
    assert denormalize_box([500, 375, 10, 15], 2000, 1500) == (990.0, 735.0, 1010.0, 765.0)
```

If `map_payload`'s payload shape differs from `_payload_with` (check the module's existing tests for the exact keys), match the existing shape — the assertions are what matter.

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_contracts.py tests/test_ingest_mapping.py -q`
Expected: the four new tests fail (`TypeError`/`AttributeError`/`ImportError`).

- [ ] **Step 3: Contracts**

In `api/app/engine/contracts.py`:

```python
@dataclass
class Placement:
    """Where one device sits, page points, visual frame. `w`/`h` are the
    glyph's extent when Counting found the drawn symbol; 0 when only the
    tag's text position is known (B3b spec §2)."""

    x: int
    y: int
    w: int = 0
    h: int = 0


@dataclass
class DeviceCluster:
    """Counting agent output: an *unlabelled* group of identical shapes or
    tags with exact coordinates. Counting does not know what these are."""

    tag: str
    sheet_page_index: int
    placements: list[Placement] = field(default_factory=list)
    # One instance's page rect (x0, y0, x1, y1), for the crop Classification
    # sees on a shape cluster. None on a tag cluster.
    exemplar: tuple[float, float, float, float] | None = None
    # Set on a shape cluster absorbed by a tag cluster (counting._link);
    # kept for tests, never serialised.
    linked_tag: str = ""
```

- [ ] **Step 4: Rows, evidence crop, payload, ingest**

`api/app/engine/rows.py` — both sites (`_row_from_spec` and `_row_from_catalog`):

```python
        "placements": [[p.x, p.y, p.w, p.h] for p in cluster.placements],
```

`api/app/engine/sheet.py:116`:

```python
        placements = row["placements"] or [(row["x"], row["y"])]
```
stays; change `documents.render_evidence_crop` to accept 2- or 4-element entries — replace the `xs`/`ys` block:

```python
        # A placement is (x, y) or (x, y, w, h); the box, when present,
        # is what the crop frames (B3b) -- the symbol, not the tag.
        x0s = [p[0] - (p[2] / 2 if len(p) >= 4 else 0) for p in placements]
        y0s = [p[1] - (p[3] / 2 if len(p) >= 4 else 0) for p in placements]
        x1s = [p[0] + (p[2] / 2 if len(p) >= 4 else 0) for p in placements]
        y1s = [p[1] + (p[3] / 2 if len(p) >= 4 else 0) for p in placements]
        if len(placements) == 1 and len(placements[0]) < 4:
            x, y = x0s[0], y0s[0]
            x0, y0, x1, y1 = x - EVIDENCE_POINT_RADIUS_PT, y - EVIDENCE_POINT_RADIUS_PT, x + EVIDENCE_POINT_RADIUS_PT, y + EVIDENCE_POINT_RADIUS_PT
        else:
            margin = EVIDENCE_CLUSTER_MARGIN_PT if len(placements) > 1 else EVIDENCE_POINT_RADIUS_PT
            x0, y0, x1, y1 = min(x0s) - margin, min(y0s) - margin, max(x1s) + margin, max(y1s) + margin
```

`api/app/worker/classify_job.py:125`:

```python
    queue.enqueue_sheets(db, job, [(s, {"clusters": [{"tag": c.tag, "placements": [[p.x, p.y, p.w, p.h] for p in c.placements]}
                                                     for c in clusters_by_sheet[s.id]]}) for s in plan_sheets])
```

`api/app/worker/sheet_job.py:67`:

```python
    clusters = [DeviceCluster(c["tag"], detected.page_index, [Placement(*(int(v) for v in p)) for p in c["placements"]])
                for c in (job.payload or {}).get("clusters", [])]
```

`api/app/takeoff/ingest.py` — replace the `placements = [...]` comprehension:

```python
        placements = [_normalize_placement(p, width, height) for p in (raw.get("placements") or [])
                      if isinstance(p, (list, tuple)) and len(p) >= 2]
```

and add, next to `normalize_point`:

```python
def _normalize_placement(p, width: int, height: int) -> list[int]:
    """[x, y] or [x, y, w, h] in page points -> sheet units. A box of
    zero extent is a point: stored two-element, drawn with the fixed
    ring (B3b spec §2). A real box never normalises below 1 unit."""
    x = normalize_point(p[0], width, SHEET_SPACE_W)
    y = normalize_point(p[1], height, SHEET_SPACE_H)
    if len(p) < 4 or not (p[2] and p[3]):
        return [x, y]
    w = max(1, normalize_point(p[2], width, SHEET_SPACE_W))
    h = max(1, normalize_point(p[3], height, SHEET_SPACE_H))
    return [x, y, w, h]


def denormalize_box(box, width_pt: float, height_pt: float) -> tuple[float, float, float, float]:
    """A sheet-unit [x, y, w, h] (centre + extent) -> page-point rect
    (x0, y0, x1, y1), the inverse of `_normalize_placement`."""
    x, y, w, h = (float(v) for v in box)
    sx, sy = width_pt / SHEET_SPACE_W, height_pt / SHEET_SPACE_H
    return ((x - w / 2) * sx, (y - h / 2) * sy, (x + w / 2) * sx, (y + h / 2) * sy)
```

- [ ] **Step 5: Run the touched suites**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_contracts.py tests/test_ingest_mapping.py tests/test_estimate_evidence.py tests/test_evidence_images.py tests/test_engine_pipeline.py tests/test_worker_run.py tests/test_merge.py -q`
Expected: all pass (existing two-element behaviour unchanged).

- [ ] **Step 6: Commit**

```bash
git add api/app/engine/contracts.py api/app/engine/rows.py api/app/engine/documents.py api/app/takeoff/ingest.py api/app/worker/classify_job.py api/app/worker/sheet_job.py api/tests/test_engine_contracts.py api/tests/test_ingest_mapping.py
git commit -m "Carry the glyph box on every placement, point-only rows unchanged"
```

---

### Task 2: `engine/glyphs.py` — candidates, shape comparison, clusters

**Files:**
- Create: `api/app/engine/glyphs.py`
- Test: `api/tests/test_engine_glyphs.py`

**Interfaces:**
- Produces:
  ```python
  MAX_INK_LUMINANCE = 0.4; MAX_GLYPH_PT = 40.0; MIN_GLYPH_PT = 3.0; MIN_STRAIGHT_PATHS = 3
  TOUCH_PT = 0.5; MAX_PATHS = 24; TOL_PT = 0.35; FIXTURE_PT = 2.0; GRID_PT = 8.0; QUANT_PT = 0.25
  @dataclass class Path: rect, pts: list[tuple[float, float]], fill: bool, stroke: bool, closed: bool, curved: bool
  @dataclass class Glyph: rect: tuple[float, float, float, float]; forms: list[Form]; key: tuple
  @dataclass class ShapeCluster: signature: str; members: list[Glyph]
  def paths_on(page) -> list[Path]                         # visual frame, full-tone ink only
  def glyphs_on(page, region, words) -> list[Glyph]        # words: list[page_frame.Word]
  def same_shape(a: Glyph, b: Glyph) -> bool
  def cluster(glyphs: list[Glyph], min_instances: int = 3) -> list[ShapeCluster]   # largest first
  def glyph_in(page, rect, words) -> Glyph | None
  def matches_of(glyph: Glyph, glyphs: list[Glyph]) -> list[Glyph]
  def signature_of(glyph: Glyph) -> str
  ```
  `Form = list[tuple[bool, bool, bool, list[tuple[float, float]]]]` — per path `(fill, stroke, closed, points)` relative to the bbox origin under one transform, paths sorted by `(fill, stroke, closed, len(points), min point)`.

- [ ] **Step 1: Failing tests**

`api/tests/test_engine_glyphs.py`:

```python
"""engine/glyphs.py: the shape rules the corpus set (B3b spec §3).
Every constant is a named value with a test; nothing here is tuned."""
import pymupdf
import pytest

from app.engine import glyphs
from app.engine.page_frame import visual_words


def _receptacle(page, cx, cy, rot=0, mirror=False, jitter=0.0, color=(0, 0, 0), r=4.0):
    """A circle with a bar through it, as electrical drafting draws a
    receptacle: one curve path plus two straight ones."""
    m = pymupdf.Matrix(1, 1).prerotate(rot)
    if mirror:
        m = pymupdf.Matrix(-1, 1) * m
    def at(x, y):
        p = pymupdf.Point(x, y) * m
        return pymupdf.Point(p.x + cx + jitter, p.y + cy)
    s = page.new_shape()
    s.draw_circle(at(0, 0), r)
    s.finish(color=color, width=0.5)
    s = page.new_shape()
    s.draw_line(at(-r - 2, 0), at(-r, 0))
    s.draw_line(at(r, 0), at(r + 2, 0))
    s.finish(color=color, width=0.5)
    s.commit()


@pytest.fixture
def page():
    doc = pymupdf.open()
    return doc.new_page(width=1000, height=800)


def _region():
    return (20, 16, 820, 784)


def test_five_receptacles_in_four_orientations_form_one_cluster(page):
    _receptacle(page, 100, 100)
    _receptacle(page, 200, 100, rot=90)
    _receptacle(page, 300, 100, rot=180)
    _receptacle(page, 400, 100, mirror=True)
    _receptacle(page, 500, 100, jitter=0.1)
    g = glyphs.glyphs_on(page, _region(), visual_words(page))
    assert len(g) == 5
    cl = glyphs.cluster(g)
    assert len(cl) == 1 and len(cl[0].members) == 5
    assert len(cl[0].signature) == 8


def test_screened_ink_is_never_a_glyph(page):
    _receptacle(page, 100, 100, color=(0.6, 0.6, 0.6))
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_a_dashed_wall_corner_is_not_a_glyph(page):
    s = page.new_shape()
    s.draw_line((100, 100), (100, 104)); s.draw_line((100, 104), (104, 104))
    s.finish(color=(0, 0, 0), width=0.5); s.commit()
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_three_straight_segments_are_a_glyph(page):
    s = page.new_shape()
    s.draw_line((100, 100), (106, 100)); s.finish(color=(0, 0, 0), width=0.5)
    s = page.new_shape(); s.draw_line((100, 100), (100, 106)); s.finish(color=(0, 0, 0), width=0.5)
    s = page.new_shape(); s.draw_line((100, 106), (106, 100)); s.finish(color=(0, 0, 0), width=0.5)
    s.commit()
    assert len(glyphs.glyphs_on(page, _region(), visual_words(page))) == 1


def test_a_hatch_and_a_large_box_are_not_glyphs(page):
    s = page.new_shape()
    for i in range(30):   # > MAX_PATHS touching lines
        s.draw_line((100 + i * 0.3, 100), (100 + i * 0.3, 110))
    s.finish(color=(0, 0, 0), width=0.2); s.commit()
    s = page.new_shape(); s.draw_rect(pymupdf.Rect(300, 300, 360, 360)); s.finish(color=(0, 0, 0)); s.commit()
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_a_glyph_under_text_is_dropped(page):
    s = page.new_shape(); s.draw_rect(pymupdf.Rect(100, 100, 130, 112)); s.finish(color=(0, 0, 0)); s.commit()
    page.insert_text((104, 110), "111", fontsize=8)
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_fill_and_stroke_are_part_of_the_shape(page):
    s = page.new_shape(); s.draw_circle((100, 100), 4); s.finish(color=(0, 0, 0), fill=(0, 0, 0)); s.commit()
    s = page.new_shape(); s.draw_circle((200, 100), 4); s.finish(color=(0, 0, 0)); s.commit()
    a, b = glyphs.glyphs_on(page, _region(), visual_words(page))
    assert not glyphs.same_shape(a, b)


def test_outside_the_region_is_ignored(page):
    _receptacle(page, 900, 100)   # title-block strip
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_glyph_in_and_matches_of(page):
    for x in (100, 200, 300):
        _receptacle(page, x, 100)
    s = page.new_shape(); s.draw_circle((500, 100), 4); s.finish(color=(0, 0, 0), fill=(0, 0, 0)); s.commit()
    words = visual_words(page)
    found = glyphs.glyph_in(page, (90, 90, 112, 110), words)
    assert found is not None
    assert len(glyphs.matches_of(found, glyphs.glyphs_on(page, _region(), words))) == 3
    assert glyphs.glyph_in(page, (600, 600, 640, 640), words) is None


def test_signature_is_stable_and_orientation_free(page):
    _receptacle(page, 100, 100)
    _receptacle(page, 200, 100, rot=90)
    a, b = glyphs.glyphs_on(page, _region(), visual_words(page))
    assert glyphs.signature_of(a) == glyphs.signature_of(b)


def test_the_visual_frame_is_used_on_a_rotated_page():
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=1000)
    _receptacle(page, 100, 100)
    page.set_rotation(90)
    (g,) = glyphs.glyphs_on(page, (0, 0, 1000, 800), visual_words(page))
    x0, y0, x1, y1 = g.rect
    assert 0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 800
    # (100, 100) on the unrotated page lands near (900, 100) after a 90° turn
    assert abs((x0 + x1) / 2 - 900) < 8 and abs((y0 + y1) / 2 - 100) < 8
```

- [ ] **Step 2: Run, expect ImportError**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_glyphs.py -q`
Expected: FAIL — `cannot import name 'glyphs'`.

- [ ] **Step 3: Implement `api/app/engine/glyphs.py`**

```python
"""Glyphs on an exploded vector sheet (B3b spec §3).

Every vector set in the corpus is Tier B: symbols are exploded into
loose paths with no block definitions to read, so identity has to be
recovered from geometry. This module turns a page's small full-tone
paths into glyph candidates and decides when two candidates are the
same drawn symbol. It knows nothing about what a symbol is -- that is
Classification's job -- and every threshold here is a measured
constant with a test, never a learned weight (CLAUDE.md: Counting is
tested, not trained).

Everything is in the visual frame (page_frame.py).
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass

import pymupdf

from app.engine.page_frame import Word

# Ink: the architectural underlay is screened (grey); electrical work is
# full-tone. Luminance above this is background.
MAX_INK_LUMINANCE = 0.4
# Size: a path bigger than this on either side is a wall, a wire run, a
# border -- never part of a symbol; a candidate smaller than MIN on
# either side is a dash or a tick.
MAX_GLYPH_PT = 40.0
MIN_GLYPH_PT = 3.0
# Shape: a candidate with no curve, no closed path and no fill needs at
# least this many straight segments -- two dashes at a corner are a wall.
MIN_STRAIGHT_PATHS = 3
# Grouping: paths whose bboxes overlap or come within TOUCH_PT belong to
# one candidate; more than MAX_PATHS is hatch or a north arrow.
TOUCH_PT = 0.5
MAX_PATHS = 24
GRID_PT = 8.0
# Sameness: every point matches a point of its pair within TOL_PT.
# Exact hashing split identical receptacles over 0.02 pt of jitter.
TOL_PT = 0.35
# Signature: the exemplar's canonical form on this grid, for a stable id.
QUANT_PT = 0.25
# A cluster at the same coordinates on most plan sheets is a border or
# legend fixture (counting.count applies this).
FIXTURE_PT = 2.0


@dataclass
class Path:
    rect: tuple[float, float, float, float]
    pts: list[tuple[float, float]]
    fill: bool
    stroke: bool
    closed: bool
    curved: bool


Form = list[tuple[bool, bool, bool, list[tuple[float, float]]]]


@dataclass
class Glyph:
    rect: tuple[float, float, float, float]
    forms: list[Form]     # the eight dihedral forms; forms[0] is the identity
    key: tuple            # coarse bucket: (paths, point counts, long side, short side)


@dataclass
class ShapeCluster:
    signature: str
    members: list[Glyph]


def _luminance(rgb) -> float:
    r, g, b = (list(rgb) + [0, 0, 0])[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def paths_on(page) -> list[Path]:
    """Every full-tone drawing path, points in the visual frame, bbox from
    the points (PyMuPDF's `rect` for a vertical line is empty and unions
    to nothing)."""
    m = page.rotation_matrix
    out: list[Path] = []
    for d in page.get_drawings():
        ink = d.get("color") or d.get("fill")
        if ink is None or _luminance(ink) > MAX_INK_LUMINANCE:
            continue
        pts: list[pymupdf.Point] = []
        curved = closed = False
        for it in d["items"]:
            if it[0] == "l":
                pts += [it[1], it[2]]
            elif it[0] == "c":
                pts += [it[1], it[2], it[3], it[4]]
                curved = True
            elif it[0] == "re":
                r = it[1]
                pts += [r.tl, r.tr, r.br, r.bl]
                closed = True
            elif it[0] == "qu":
                q = it[1]
                pts += [q.ul, q.ur, q.lr, q.ll]
                closed = True
        if not pts:
            continue
        vis = [pymupdf.Point(p) * m for p in pts]
        xs = [p.x for p in vis]
        ys = [p.y for p in vis]
        out.append(Path(rect=(min(xs), min(ys), max(xs), max(ys)), pts=[(p.x, p.y) for p in vis],
                        fill=bool(d.get("fill")), stroke=bool(d.get("color")),
                        closed=closed or bool(d.get("closePath")), curved=curved))
    return out


def _small(p: Path) -> bool:
    x0, y0, x1, y1 = p.rect
    return (x1 - x0) <= MAX_GLYPH_PT and (y1 - y0) <= MAX_GLYPH_PT


def _bbox(paths: list[Path]) -> tuple[float, float, float, float]:
    return (min(p.rect[0] for p in paths), min(p.rect[1] for p in paths),
            max(p.rect[2] for p in paths), max(p.rect[3] for p in paths))


def _touching(a, b) -> bool:
    return (b[0] <= a[2] + TOUCH_PT and b[2] >= a[0] - TOUCH_PT
            and b[1] <= a[3] + TOUCH_PT and b[3] >= a[1] - TOUCH_PT)


def _candidates(paths: list[Path]) -> list[list[Path]]:
    """Union-find over small paths, bucketed on a GRID_PT grid so a sheet
    of thirty thousand fragments stays linear."""
    n = len(paths)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, p in enumerate(paths):
        x0, y0, x1, y1 = p.rect
        for gx in range(int(x0 // GRID_PT), int(x1 // GRID_PT) + 1):
            for gy in range(int(y0 // GRID_PT), int(y1 // GRID_PT) + 1):
                grid[(gx, gy)].append(i)
    for cell in grid.values():
        for a in range(len(cell)):
            for b in range(a + 1, len(cell)):
                i, j = cell[a], cell[b]
                if _touching(paths[i].rect, paths[j].rect):
                    parent[find(i)] = find(j)
    groups: dict[int, list[Path]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(paths[i])
    return list(groups.values())


def _is_glyph(group: list[Path]) -> bool:
    if len(group) > MAX_PATHS:
        return False
    x0, y0, x1, y1 = _bbox(group)
    if (x1 - x0) > MAX_GLYPH_PT or (y1 - y0) > MAX_GLYPH_PT:
        return False
    if (x1 - x0) < MIN_GLYPH_PT or (y1 - y0) < MIN_GLYPH_PT:
        return False
    shaped = any(p.curved or p.closed or p.fill for p in group)
    return shaped or len(group) >= MIN_STRAIGHT_PATHS


def _forms(group: list[Path]) -> list[Form]:
    """The eight dihedral forms of a candidate, each relative to its own
    bbox origin so translation never matters."""
    x0, y0, x1, y1 = _bbox(group)
    w, h = x1 - x0, y1 - y0
    forms: list[Form] = []
    for t in range(8):
        rot, mirror = t % 4, t >= 4
        recs: Form = []
        for p in group:
            pts = []
            for (px, py) in p.pts:
                x, y = px - x0, py - y0
                ww, hh = w, h
                if mirror:
                    x = ww - x
                for _ in range(rot):      # 90° turns inside the box
                    x, y = hh - y, x
                    ww, hh = hh, ww
                pts.append((x, y))
            recs.append((p.fill, p.stroke, p.closed, pts))
        recs.sort(key=lambda r: (r[0], r[1], r[2], len(r[3]), min(r[3])))
        forms.append(recs)
    return forms


def _key(group: list[Path]) -> tuple:
    x0, y0, x1, y1 = _bbox(group)
    long_, short = max(x1 - x0, y1 - y0), min(x1 - x0, y1 - y0)
    return (len(group), tuple(sorted(len(p.pts) for p in group)), round(long_), round(short))


def _glyph(group: list[Path]) -> Glyph:
    return Glyph(rect=_bbox(group), forms=_forms(group), key=_key(group))


def _centre_in(rect, x, y) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def glyphs_on(page, region, words: list[Word]) -> list[Glyph]:
    """Every glyph candidate inside `region` (page points, visual frame),
    in page order. A candidate whose box contains a word's centre is
    text, not a symbol."""
    paths = [p for p in paths_on(page) if _small(p)]
    out: list[Glyph] = []
    centres = [(w.cx, w.cy) for w in words]
    for group in _candidates(paths):
        if not _is_glyph(group):
            continue
        rect = _bbox(group)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        if not _centre_in(region, cx, cy):
            continue
        if any(_centre_in(rect, x, y) for x, y in centres):
            continue
        out.append(_glyph(group))
    return out


def _points_match(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> bool:
    if len(a) != len(b):
        return False
    free = list(b)
    for (ax, ay) in a:
        hit = next((i for i, (bx, by) in enumerate(free) if abs(ax - bx) <= TOL_PT and abs(ay - by) <= TOL_PT), None)
        if hit is None:
            return False
        free.pop(hit)
    return True


def _forms_match(fa: Form, fb: Form) -> bool:
    if len(fa) != len(fb):
        return False
    free = list(fb)
    for ra in fa:
        hit = next((i for i, rb in enumerate(free) if ra[:3] == rb[:3] and _points_match(ra[3], rb[3])), None)
        if hit is None:
            return False
        free.pop(hit)
    return True


def same_shape(a: Glyph, b: Glyph) -> bool:
    """The same drawn symbol under some rotation or mirror, within TOL_PT."""
    if a.key != b.key:
        return False
    return any(_forms_match(a.forms[0], f) for f in b.forms)


def signature_of(glyph: Glyph) -> str:
    """A stable id for a shape: sha256 of the lexicographically smallest of
    the eight forms after quantising to QUANT_PT, first 8 hex. The same
    file yields the same signature run after run."""
    canon = []
    for f in glyph.forms:
        canon.append(sorted((r[0], r[1], r[2], sorted((round(x / QUANT_PT), round(y / QUANT_PT)) for x, y in r[3])) for r in f))
    return hashlib.sha256(repr(min(canon)).encode()).hexdigest()[:8]


def cluster(glyphs: list[Glyph], min_instances: int = 3) -> list[ShapeCluster]:
    """Group by shape: each glyph joins the first exemplar in its bucket it
    matches, else starts a cluster. Largest first, then by first member's
    position for a stable order."""
    buckets: dict[tuple, list[list[Glyph]]] = defaultdict(list)
    for g in glyphs:
        for members in buckets[g.key]:
            if same_shape(members[0], g):
                members.append(g)
                break
        else:
            buckets[g.key].append([g])
    out = [ShapeCluster(signature=signature_of(m[0]), members=m)
           for ms in buckets.values() for m in ms if len(m) >= min_instances]
    out.sort(key=lambda c: (-len(c.members), c.members[0].rect))
    return out


def matches_of(glyph: Glyph, glyphs: list[Glyph]) -> list[Glyph]:
    """Every glyph the same shape as `glyph` -- itself included when it is
    among `glyphs`."""
    return [g for g in glyphs if same_shape(glyph, g)]


def glyph_in(page, rect, words: list[Word]) -> Glyph | None:
    """The one candidate whose paths all lie inside `rect` (page points,
    visual frame). None when the box holds no full-tone glyph -- the
    caller falls back to raster matching."""
    x0, y0, x1, y1 = rect
    paths = [p for p in paths_on(page) if _small(p)
             and p.rect[0] >= x0 and p.rect[1] >= y0 and p.rect[2] <= x1 and p.rect[3] <= y1]
    groups = [g for g in _candidates(paths) if _is_glyph(g)]
    if not groups:
        return None
    group = max(groups, key=len)
    centres = [(w.cx, w.cy) for w in words]
    if any(_centre_in(_bbox(group), x, y) for x, y in centres):
        return None
    return _glyph(group)
```

- [ ] **Step 4: Run, all pass**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_glyphs.py -q`
Expected: 11 passed. If the rotated-page test's centre expectation is off by the page's rotation direction, check `page.rotation_matrix` on a `set_rotation(90)` page and fix the *test's* expected coordinates — the module must use `rotation_matrix` exactly as `page_frame.visual_words` does.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/glyphs.py api/tests/test_engine_glyphs.py
git commit -m "Add engine/glyphs: candidates and tolerant shape clusters on exploded geometry"
```

---

### Task 3: Counting emits shape clusters, links them to tags, drops fixtures

**Files:**
- Modify: `api/app/engine/counting.py:164-202`
- Test: `api/tests/test_engine_counting.py`, `api/tests/test_corpus_sheets.py`

**Interfaces:**
- Consumes: Task 2's `glyphs_on`, `cluster`, `ShapeCluster`; Task 1's `Placement(x, y, w, h)`, `DeviceCluster.exemplar/linked_tag`.
- Produces: `count_sheet` returns tag clusters (boxed where linked) then shape clusters `tag="shape:<sig>"`; `count()` applies the cross-sheet fixture drop; constants `LINK_FACTOR = 1.5`, `LINK_SHARE = 0.8`, `FIXTURE_SHARE = 0.6`.

- [ ] **Step 1: Failing tests**

Append to `api/tests/test_engine_counting.py`:

```python
from tests.test_engine_glyphs import _receptacle  # the same drawn receptacle


def _plan(tmp_path, draw, name="shapes.pdf", pages=1):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=1000, height=800)
        draw(page, i)
    path = tmp_path / name
    doc.save(path)
    region = (20, 16, 820, 784)
    return str(path), [DetectedSheet(page_index=i, number=f"E1.{i + 1}", title="t", discipline="Electrical",
                                     scale="", width_pt=1000, height_pt=800, region=region) for i in range(pages)]


def test_untagged_glyphs_become_a_shape_cluster_with_boxes(tmp_path):
    def draw(page, _):
        for x in (100, 200, 300, 400):
            _receptacle(page, x, 300)
    path, (sheet,) = _plan(tmp_path, draw)
    (c,) = counting.count_sheet(path, sheet)
    assert c.tag.startswith("shape:") and len(c.tag) == len("shape:") + 8
    assert c.count == 4 and c.exemplar is not None
    p = c.placements[0]
    assert p.w > 0 and p.h > 0 and abs(p.x - 100) <= 1 and abs(p.y - 300) <= 1


def test_a_tag_beside_each_glyph_absorbs_the_shape_cluster(tmp_path):
    def draw(page, _):
        for x in (100, 200, 300, 400, 500):
            _receptacle(page, x, 300)
            page.insert_text((x + 8, 296), "R", fontsize=6)
    path, (sheet,) = _plan(tmp_path, draw)
    clusters = counting.count_sheet(path, sheet)
    assert [c.tag for c in clusters] == ["R"]
    r = clusters[0]
    assert r.count == 5 and all(p.w > 0 and p.h > 0 for p in r.placements)
    assert all(abs(p.x - x) <= 1 for p, x in zip(sorted(r.placements, key=lambda p: p.x), (100, 200, 300, 400, 500)))


def test_a_tag_far_from_any_glyph_keeps_a_point_placement(tmp_path):
    def draw(page, _):
        for x in (100, 200, 300):
            page.insert_text((x, 300), "R", fontsize=6)
        for x in (100, 200, 300):
            _receptacle(page, x, 600)   # 300 pt away: not this tag's glyph
    path, (sheet,) = _plan(tmp_path, draw)
    tags = {c.tag: c for c in counting.count_sheet(path, sheet)}
    assert tags["R"].count == 3 and all(p.w == 0 and p.h == 0 for p in tags["R"].placements)
    assert len([t for t in tags if t.startswith("shape:")]) == 1


def test_fewer_than_three_instances_is_not_a_cluster(tmp_path):
    def draw(page, _):
        _receptacle(page, 100, 300); _receptacle(page, 200, 300)
    path, (sheet,) = _plan(tmp_path, draw)
    assert counting.count_sheet(path, sheet) == []


def test_a_shape_at_the_same_place_on_most_sheets_is_a_fixture(tmp_path):
    def draw(page, i):
        for x in (100, 200, 300):          # a legend-style row, same spot every page
            _receptacle(page, x, 100)
        if i == 0:
            for x in (100, 250, 400, 550):  # real devices on one page only
                _receptacle(page, x, 500, rot=90)
    path, sheets = _plan(tmp_path, draw, pages=3)
    clusters = counting.count(path, sheets)
    # the fixture row (same shape, same coordinates on 3 of 3 sheets) is gone;
    # page 0 keeps its four real devices, which share the shape but not the spot
    by_page = {}
    for c in clusters:
        by_page.setdefault(c.sheet_page_index, []).append(c)
    assert 1 not in by_page and 2 not in by_page
    assert len(by_page[0]) == 1 and by_page[0][0].count == 4
```

Append to `api/tests/test_corpus_sheets.py` (skips without the corpus, like its neighbours):

```python
# Measured 2026-09-16 on the corpus (spec §3 "Measured"); thresholds are
# two-thirds of what was seen so a regression shows and jitter does not.
SHAPE_FLOORS = {
    ("unalaska", 84): (5, 120),          # E1.1
    ("unalaska", 87): (8, 120),          # E2.1
    ("kittles_saxony", 4): (3, 150),     # EP101
}


@pytest.mark.parametrize("name,page_index", sorted(SHAPE_FLOORS))
def test_shape_clusters_count_untagged_devices(name, page_index):
    from app.engine import counting

    fx, path, sheets = _detected(name)
    sheet = next(s for s in sheets if s.page_index == page_index)
    shapes = [c for c in counting.count_sheet(path, sheet) if c.tag.startswith("shape:")]
    min_clusters, min_placements = SHAPE_FLOORS[(name, page_index)]
    assert len(shapes) >= min_clusters, (name, page_index, len(shapes))
    assert sum(c.count for c in shapes) >= min_placements
    for c in shapes:
        for p in c.placements:
            assert p.w > 0 and p.h > 0
            assert 0 <= p.x <= sheet.width_pt and 0 <= p.y <= sheet.height_pt


def test_united_utility_has_a_hundred_of_one_receptacle():
    from app.engine import counting

    fx, path, sheets = _detected("united_utility")
    sheet = next(s for s in sheets if s.page_index == 59)   # E-101
    shapes = [c for c in counting.count_sheet(path, sheet) if c.tag.startswith("shape:")]
    assert max((c.count for c in shapes), default=0) >= 100


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_tag_counts_are_unchanged_by_shape_clusters(name):
    """Linking moves a tag's placements onto glyph boxes; it never adds
    or removes a placement."""
    from app.engine import counting

    fx, path, sheets = _detected(name)
    for s in sheets:
        clusters = counting.count_sheet(path, s)
        for c in clusters:
            if c.tag.startswith("shape:"):
                continue
            assert c.count >= counting.MIN_PLACEMENTS
```

If `_detected` in `test_corpus_sheets.py` returns something other than `(fixture, path, sheets)`, adapt the unpacking; do not change `_detected`.

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_counting.py -q`
Expected: the five new tests fail (`count_sheet` returns no shape clusters / no boxes).

- [ ] **Step 3: Implement in `api/app/engine/counting.py`**

Add imports and constants near the top:

```python
import math

from app.engine import glyphs
from app.engine.glyphs import FIXTURE_PT

# Linking a tag to the glyph it labels (spec §4): a tag's nearest glyph
# within LINK_FACTOR × the glyph's larger side is its symbol, and a
# shape cluster whose instances are mostly claimed by one tag belongs
# to that tag.
LINK_FACTOR = 1.5
LINK_SHARE = 0.8
# A shape at the same coordinates on this share of a set's plan sheets
# is a border or legend fixture, not a device.
FIXTURE_SHARE = 0.6
```

Replace the tail of `count_sheet` (from `clusters = [` to `return clusters`) and `count`:

```python
    tag_clusters = [
        DeviceCluster(tag=tag, sheet_page_index=sheet.page_index, placements=places)
        for tag, places in by_tag.items()
        if len(places) >= MIN_PLACEMENTS
    ]
    shape_clusters = _shape_clusters(page, sheet, words)
    _link(tag_clusters, shape_clusters)
    clusters = tag_clusters + [c for c in shape_clusters if not c.linked_tag]
    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters


def _shape_clusters(page, sheet: DetectedSheet, words) -> list[DeviceCluster]:
    """Untagged device glyphs, by shape (glyphs.py). Counting names
    nothing: the tag is the shape's signature, and Classification
    decides what it is."""
    stamp = _stamp_points(page)
    found = glyphs.glyphs_on(page, sheet.region, words)
    found = [g for g in found
             if (round((g.rect[0] + g.rect[2]) / 2), round((g.rect[1] + g.rect[3]) / 2)) not in stamp]
    out = []
    for c in glyphs.cluster(found, MIN_PLACEMENTS):
        out.append(DeviceCluster(
            tag=f"shape:{c.signature}", sheet_page_index=sheet.page_index,
            placements=[_placement(g) for g in c.members], exemplar=c.members[0].rect,
        ))
    return out


def _placement(g: glyphs.Glyph) -> Placement:
    x0, y0, x1, y1 = g.rect
    return Placement(int(round((x0 + x1) / 2)), int(round((y0 + y1) / 2)),
                     max(1, int(round(x1 - x0))), max(1, int(round(y1 - y0))))


def _link(tag_clusters: list[DeviceCluster], shape_clusters: list[DeviceCluster]) -> None:
    """A tag placement claims the nearest glyph within LINK_FACTOR × the
    glyph's larger side. A shape cluster with ≥ LINK_SHARE of its
    instances claimed by one tag is that tag's symbol: the tag's
    placements take the boxes and the shape cluster is marked linked.
    Nothing here changes a tag cluster's count."""
    instances = [(sc, i, p) for sc in shape_clusters for i, p in enumerate(sc.placements)]
    claims: dict[tuple[int, int], tuple[DeviceCluster, int]] = {}   # (shape idx, instance) -> (tag cluster, placement idx)
    for tc in tag_clusters:
        for pi, tp in enumerate(tc.placements):
            best = None
            for si, (sc, i, p) in enumerate(instances):
                reach = LINK_FACTOR * max(p.w, p.h)
                d = math.hypot(tp.x - p.x, tp.y - p.y)
                if d <= reach and (best is None or d < best[0]):
                    best = (d, si)
            if best is not None:
                sc, i, _ = instances[best[1]]
                claims.setdefault((id(sc), i), (tc, pi))
    for sc in shape_clusters:
        by_tag: dict[str, list[tuple[int, int]]] = {}
        for i in range(len(sc.placements)):
            claim = claims.get((id(sc), i))
            if claim:
                by_tag.setdefault(claim[0].tag, []).append((i, claim[1]))
        for tag, pairs in by_tag.items():
            if len(pairs) < LINK_SHARE * len(sc.placements):
                continue
            tc = next(t for t in tag_clusters if t.tag == tag)
            for i, pi in pairs:
                tc.placements[pi] = sc.placements[i]
            sc.linked_tag = tag
            break


def count(path: str, sheets: list[DetectedSheet]) -> list[DeviceCluster]:
    out: list[DeviceCluster] = []
    for sheet in sheets:
        out.extend(count_sheet(path, sheet))
    return _drop_fixtures(out, sum(1 for s in sheets if s.kind == "plan" and not s.unreadable_reason))


def _drop_fixtures(clusters: list[DeviceCluster], plan_sheets: int) -> list[DeviceCluster]:
    """A shape whose instances sit at the same coordinates (within
    FIXTURE_PT) on ≥ FIXTURE_SHARE of the plan sheets is a border or a
    legend, not a device. Only those repeated instances go; a device of
    the same shape elsewhere on a sheet stays."""
    if plan_sheets < 2:
        return clusters
    spots: dict[tuple[str, tuple[int, int]], set[int]] = {}
    for c in clusters:
        if not c.tag.startswith("shape:"):
            continue
        for p in c.placements:
            key = (c.tag, (round(p.x / FIXTURE_PT), round(p.y / FIXTURE_PT)))
            spots.setdefault(key, set()).add(c.sheet_page_index)
    fixture = {k for k, pages in spots.items() if len(pages) >= FIXTURE_SHARE * plan_sheets}
    if not fixture:
        return clusters
    out = []
    for c in clusters:
        if not c.tag.startswith("shape:"):
            out.append(c)
            continue
        kept = [p for p in c.placements if (c.tag, (round(p.x / FIXTURE_PT), round(p.y / FIXTURE_PT))) not in fixture]
        if len(kept) >= MIN_PLACEMENTS:
            c.placements = kept
            out.append(c)
    return out
```

`count_sheet` already has `words` and `page` in scope; pass them. Keep `Placement` import from contracts.

- [ ] **Step 4: Run counting, corpus, pipeline**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_counting.py tests/test_corpus_sheets.py tests/test_engine_pipeline.py tests/test_worker_run.py -q`
Expected: all pass; corpus tests pass when `bid_examples/` is present (they are the ones that matter — run them). Timing: no corpus sheet over 5 s.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/counting.py api/tests/test_engine_counting.py api/tests/test_corpus_sheets.py
git commit -m "Count untagged device glyphs by shape and link them to their tags"
```

---

### Task 4: Classification of shape clusters — crops for the model, glyph wording without one

**Files:**
- Modify: `api/app/engine/classification.py:64-72` (`_unknown_warning`), `:226-241` (unclassified branches), `:257-306` (`classify_run`)
- Modify: `api/app/engine/llm.py:93-135` (`_prompt`), `:191-215` (`estimate`)
- Modify: `api/app/worker/classify_job.py:95-116`
- Test: `api/tests/test_engine_classify.py`, `api/tests/test_engine_llm_prompt.py`

**Interfaces:**
- Consumes: `DeviceCluster.exemplar`; `documents.render_evidence_crop`.
- Produces: `classify_run(clusters, sheets, schedule_text, context, estimator_notes, location, crops: dict[str, bytes] | None = None)`; `llm.estimate(tags, schedule_text, location, crops: dict[str, bytes] | None = None)` sends one image block per crop, labelled by tag; `MAX_CROPS_PER_SHEET = 20` in `classify_job`; deterministic path names a shape cluster `Unclassified symbol` with the glyph warning.

- [ ] **Step 1: Failing tests**

Append to `api/tests/test_engine_classify.py`:

```python
def test_a_shape_cluster_lands_unclassified_with_glyph_wording():
    from app.engine.classification import classify
    from app.engine.contracts import DetectedSheet, DeviceCluster, Placement
    sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                          width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    c = DeviceCluster(tag="shape:0a1b2c3d", sheet_page_index=0,
                      placements=[Placement(10, 10, 6, 6)] * 4, exemplar=(7, 7, 13, 13))
    (item,) = classify([c], [sheet])
    assert item.name == "Unclassified symbol" and item.status == "attention"
    assert item.source_tag == "shape:0a1b2c3d" and item.quantity == 4
    assert item.warning["title"] == "Symbol not in legend"
    assert item.warning["found"] == "A symbol appears 4 times on E2.1 but isn't in the legend."
    assert "shape:" not in item.warning["found"]
    assert item.placements[0].w == 6
```

Append to `api/tests/test_engine_llm_prompt.py`:

```python
def test_crops_travel_as_image_blocks_labelled_by_tag(monkeypatch):
    from app.engine import llm
    sent = {}

    class _Msg:
        content = [type("B", (), {"type": "text", "text": '{"location_labor_rate": 1, "material_factor": 1, "location_note": "", "items": []}'})()]

    class _Messages:
        def create(self, **kw):
            sent.update(kw)
            return _Msg()

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(llm, "Anthropic", lambda: _Client(), raising=False)
    monkeypatch.setattr(llm, "_client", lambda: _Client(), raising=False)
    llm.estimate([{"tag": "shape:abcd1234", "count": 4}], "", "", crops={"shape:abcd1234": b"\x89PNG"})
    content = sent["messages"][0]["content"]
    assert isinstance(content, list)
    assert any(b.get("type") == "image" and b["source"]["media_type"] == "image/png" for b in content)
    labels = [b["text"] for b in content if b.get("type") == "text"]
    assert any("shape:abcd1234" in t for t in labels)
```

Look at how `estimate` constructs its client today (`from anthropic import Anthropic` inside the function). Factor the client construction into a module-level `_client()` so the test can patch it; the test above patches `_client`.

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_classify.py tests/test_engine_llm_prompt.py -q`
Expected: the two new tests fail.

- [ ] **Step 3: Implement**

`classification.py` — a glyph wording beside `_unknown_warning`:

```python
def _unknown_glyph_warning(count: int, sheet_no: str) -> dict:
    """A symbol Counting found by shape with no tag to look up. Never
    quotes the signature -- `shape:…` is a processing internal."""
    return {
        "reason": "legend",
        "title": "Symbol not in legend",
        "found": f"A symbol appears {count} times on {sheet_no} but isn't in the legend.",
        "why": "An unclassified symbol has no catalog item, so it isn't counted or priced yet.",
        "fix": "Assign a classification, or reject it if it isn't a device.",
        "where": f"{sheet_no}.",
    }
```

At the top of the per-cluster loop in `classify` (before the `TAG_TO_CATALOG` branch):

```python
        if c.tag.startswith("shape:"):
            items.append(ClassifiedItem(
                catalog_id="unclassified", name="Unclassified symbol",
                system="Unknown", category="Unclassified", unit="ea", symbol="generic",
                quantity=c.count, sheet_page_index=c.sheet_page_index, placements=c.placements,
                status="attention", warning=_unknown_glyph_warning(c.count, no), source_tag=c.tag,
            ))
            continue
```

`classify_run` gains `crops: dict[str, bytes] | None = None` and passes it: `result = llm.estimate(tags, full_context, location, crops=crops)`.

`llm.py`:

```python
def _client():
    from anthropic import Anthropic  # imported lazily so the module loads without the SDK
    return Anthropic()


def _content(tags, schedule_text, location, crops):
    """The user turn: the prompt, then one labelled image per shape
    cluster so the model can see what it is naming. Tag text is data
    on the page, never an instruction (invariant 11): the label names
    the tag, the prompt already says how to read it."""
    blocks = [{"type": "text", "text": _prompt(tags, schedule_text, location)}]
    for tag, png in (crops or {}).items():
        blocks.append({"type": "text", "text": f"Symbol counted as tag {tag}:"})
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                   "data": base64.b64encode(png).decode("ascii")}})
    return blocks


def estimate(tags, schedule_text, location, crops=None) -> dict:
    ...
    msg = _client().messages.create(
        model=MODEL, max_tokens=8000, output_config={"effort": "low"},
        messages=[{"role": "user", "content": _content(tags, schedule_text, location, crops)}],
    )
```

In `_prompt`, add one line after "Tags counted:" block: `A tag of the form shape:xxxxxxxx is a symbol counted by its drawn shape, with no text tag; an image of it follows this text. Classify it from the image and the legend, or answer catalog_id "none".`

`classify_job.py` — inside the `with blob_to_tempfile(...)` loop, after counting each plan sheet, render crops for its shape clusters:

```python
MAX_CROPS_PER_SHEET = 20   # the largest clusters go to the model; the rest land unclassified

...
                    clusters_by_sheet[s.id] = counting.count_sheet(path, detected[s.id])
                    shapes = [c for c in clusters_by_sheet[s.id] if c.tag.startswith("shape:") and c.exemplar]
                    for c in shapes[:MAX_CROPS_PER_SHEET]:
                        x0, y0, x1, y1 = c.exemplar
                        png = documents.render_evidence_crop(path, detected[s.id].page_index, detected[s.id].width_pt,
                                                             detected[s.id].height_pt,
                                                             [((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0)])
                        if png:
                            crops[c.tag] = png
```

with `crops: dict[str, bytes] = {}` declared beside `clusters_by_sheet`, and `classification.classify_run(..., crops=crops)`. `count_sheet` is already per-sheet so `shapes` is in the sheet's order (largest first).

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_classify.py tests/test_engine_llm_prompt.py tests/test_engine_pipeline.py tests/test_worker_run.py tests/test_estimator_notes_channel.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/classification.py api/app/engine/llm.py api/app/worker/classify_job.py api/tests/test_engine_classify.py api/tests/test_engine_llm_prompt.py
git commit -m "Classify shape clusters from a crop, or land them as Unclassified symbol"
```

---

### Task 5: Schema — `symbol_matches`, the `match` job kind, copy, queue

**Files:**
- Create: `api/migrations/versions/0023_symbol_matches.py`
- Modify: `api/app/takeoff/models.py` (new `SymbolMatch`, `Job.symbol_match_id`), `api/app/jobs/schemas.py:5-12`, `api/app/jobs/copy.py`, `api/app/jobs/queue.py` (`enqueue_match`, `mark_failed`, `terminal_copy`)
- Test: `api/tests/test_migration_0023.py`, `api/tests/test_jobs_queue.py`, `api/tests/test_jobs_model.py`

**Interfaces:**
- Produces: `SymbolMatch(id, org_id, project_id, sheet_id, box: list, status, matches: list, error, created_by, created_at, resolved_at)`, `MATCH_STATUSES = ("pending", "found", "failed")`; `Job.symbol_match_id`; `JOB_KINDS` gains `"match"`, `timeout_for("match") == 60`; `copy.MATCH_FAILED`, `copy.MATCH_UNAVAILABLE`; `queue.enqueue_match(db, match: SymbolMatch) -> Job`; a failed match job writes `status="failed", error` on its row; `terminal_copy` returns `MATCH_FAILED` for a bare/`UNREADABLE` message on a match job and `requeue` exhaustion routes through `terminal_copy` (closing the parked B3 residual).

- [ ] **Step 1: Failing tests**

`api/tests/test_migration_0023.py` — mirror `test_migration_0022.py` exactly: a source-order test that `DELETE FROM jobs WHERE kind = 'match'` precedes the constraint recreation in `downgrade`, and a real-SQL test that `downgrade()` succeeds with a `kind='match'` job row and a `symbol_matches` row present, then `upgrade()` again. Copy that file's structure (imports, `MigrationContext`, `Operations`) and change the kind and table names.

Append to `api/tests/test_jobs_queue.py`:

```python
def test_enqueue_match_queues_one_job_with_the_match_id(db, project, sheet, dana):
    from app.takeoff.models import SymbolMatch
    m = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id, box=[500, 375, 10, 10], created_by=dana.id)
    db.add(m); db.flush()
    job = queue.enqueue_match(db, m)
    assert job.kind == "match" and job.symbol_match_id == m.id and job.status == "queued" and job.max_attempts == 3


def test_a_failed_match_job_marks_its_row(db, project, sheet, dana):
    from app.takeoff.models import SymbolMatch
    m = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id, box=[500, 375, 10, 10], created_by=dana.id)
    db.add(m); db.flush()
    job = queue.enqueue_match(db, m)
    queue.mark_failed(db, job, queue.terminal_copy(job, ""))
    assert m.status == "failed" and m.error == copy.MATCH_FAILED


def test_exhausted_retries_land_on_kind_specific_copy(db, project, sheet, dana):
    from app.takeoff.models import SymbolMatch
    m = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id, box=[500, 375, 10, 10], created_by=dana.id)
    db.add(m); db.flush()
    job = queue.enqueue_match(db, m)
    job.attempts = job.max_attempts
    queue.requeue(db, job, copy.UNAVAILABLE)
    assert job.status == "failed" and m.error == copy.MATCH_UNAVAILABLE
```

Append to `api/tests/test_jobs_model.py` a check that `timeout_for("match") == 60` and `"match" in JOB_KINDS`.

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_migration_0023.py tests/test_jobs_queue.py tests/test_jobs_model.py -q`

- [ ] **Step 3: Implement**

`api/app/jobs/schemas.py`:

```python
JOB_KINDS = ("read", "classify", "sheet", "render", "match")
...
_DEFAULT_TIMEOUTS = {"read": 120, "classify": 300, "sheet": 180, "render": 300, "match": 60}
# B3b: the closed set for SymbolMatch.status -- a match's own axis, never a review label.
MATCH_STATUSES = ("pending", "found", "failed")
```

`api/app/jobs/copy.py`:

```python
MATCH_FAILED = "The symbol couldn't be searched for on this sheet. Draw the box again, or add the item by hand."
MATCH_UNAVAILABLE = "The symbol couldn't be searched for right now. Try again in a few minutes."
```

`api/app/takeoff/models.py` — `Job` gains:

```python
    symbol_match_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("symbol_matches.id", ondelete="CASCADE"), nullable=True)
```

and a new model after `ScopeStatement`:

```python
class SymbolMatch(Base):
    """One 'find every one like this' request (B3b spec §2): the box an
    estimator drew, and what the worker found. `status` is the match's
    own axis -- pending, found, failed -- never one of the four review
    labels; nothing is counted until a person names the result."""

    __tablename__ = "symbol_matches"
    __table_args__ = (
        CheckConstraint("status in ('" + "', '".join(MATCH_STATUSES) + "')", name="ck_symbol_matches_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)
    box: Mapped[list] = mapped_column(JSONB)                      # [x, y, w, h] sheet units, as drawn
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    matches: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Migration `0023_symbol_matches.py` (revision `'0023'`, down `'0022'`): `create_table('symbol_matches', …)` with those columns and the check constraint, `add_column('jobs', symbol_match_id …)` with FK `ondelete='CASCADE'`, drop/recreate `ck_jobs_kind` with `'read', 'classify', 'sheet', 'render', 'match'`. Downgrade: `DELETE FROM jobs WHERE kind = 'match'`, then recreate the four-kind constraint, drop the column, drop the table. Keep 0022's docstring convention: kinds spelled as literals.

`api/app/jobs/queue.py`:

```python
def enqueue_match(db: Session, match: SymbolMatch) -> Job:
    """One job per drawn box, attributed to the person who drew it."""
    job = Job(org_id=match.org_id, project_id=match.project_id, kind="match", sheet_id=match.sheet_id,
              symbol_match_id=match.id, requested_by=match.created_by, max_attempts=MAX_ATTEMPTS)
    db.add(job)
    db.flush()
    return job
```

In `terminal_copy`: `if job.kind == "match" and message in ("", copy.UNREADABLE): return copy.MATCH_FAILED`. In `mark_failed`: after the render branch,

```python
    if job.kind == "match" and job.symbol_match_id:
        match = db.get(SymbolMatch, job.symbol_match_id)
        if match is not None:
            match.status, match.error = "failed", error
```

In `requeue`, when attempts are exhausted: `return mark_failed(db, job, _exhausted_copy(job, error))` with

```python
def _exhausted_copy(job: Job, error: str) -> str:
    """Retries ran out on a transient reason. The generic 'couldn't open
    this file' is right for a read and wrong for every other kind."""
    if error != copy.UNAVAILABLE:
        return error
    return {"sheet": copy.SHEET_FAILED, "classify": copy.RUN_FAILED, "render": copy.RENDER_FAILED,
            "match": copy.MATCH_UNAVAILABLE}.get(job.kind, error)
```

Check the existing exhaustion tests in `test_jobs_queue.py`/`test_worker_loop.py` for read jobs still pass (a read keeps `UNAVAILABLE`).

- [ ] **Step 4: Migrate the dev database and run**

Run: `cd api && ../.enginevenv/bin/python -m alembic upgrade head && ../.enginevenv/bin/python -m pytest tests/test_migration_0023.py tests/test_migration_0022.py tests/test_jobs_queue.py tests/test_jobs_model.py tests/test_worker_loop.py tests/test_takeoff_models.py -q`
Expected: all pass. (The test database is created by `conftest.py` from the models; the migration tests exercise the SQL.)

- [ ] **Step 5: Commit**

```bash
git add api/migrations/versions/0023_symbol_matches.py api/app/takeoff/models.py api/app/jobs api/tests/test_migration_0023.py api/tests/test_jobs_queue.py api/tests/test_jobs_model.py
git commit -m "Add symbol_matches and the match job kind"
```

---

### Task 6: `engine/raster_match.py` — template matching on a render

**Files:**
- Create: `api/app/engine/raster_match.py`
- Modify: `api/requirements.txt` (add `opencv-python-headless==4.10.0.84`), `api/tests/test_api_import_boundary.py`
- Test: `api/tests/test_engine_raster_match.py`

**Interfaces:**
- Produces: `MATCH_DPI = 200`, `MATCH_THRESHOLD = 0.80`, `MAX_PIXELS = 40_000_000`; `find_on_render(path, page_index, rect) -> list[tuple[float, float, float, float]]` — page-point rects (visual frame) of every match, the template's own location included, NMS at half the template size, four rotations.

- [ ] **Step 1: Install and write failing tests**

Run: `cd api && ../.enginevenv/bin/pip install opencv-python-headless==4.10.0.84` and add the pin to `requirements.txt` under `pymupdf`.

`api/tests/test_engine_raster_match.py`:

```python
"""Template matching on a page render (B3b spec §6, raster path)."""
import pymupdf
import pytest

from app.engine import raster_match
from tests.test_engine_glyphs import _receptacle


def _raster_pdf(tmp_path, spots, rot=0):
    """A vector page drawn, rendered to an image, and placed on a fresh
    page -- so the page has no vector paths, as a scanned sheet has none."""
    src = pymupdf.open()
    p = src.new_page(width=1000, height=800)
    for (x, y) in spots:
        _receptacle(p, x, y, rot=rot)
    pix = p.get_pixmap(matrix=pymupdf.Matrix(3, 3))
    out = pymupdf.open()
    page = out.new_page(width=1000, height=800)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    path = tmp_path / "raster.pdf"
    out.save(path)
    return str(path)


def test_finds_every_copy_of_the_boxed_symbol(tmp_path):
    path = _raster_pdf(tmp_path, [(100, 100), (300, 100), (500, 400), (700, 600)])
    found = raster_match.find_on_render(path, 0, (92, 92, 108, 108))
    assert len(found) == 4
    centres = sorted(((r[0] + r[2]) / 2, (r[1] + r[3]) / 2) for r in found)
    for (cx, cy), (x, y) in zip(centres, sorted([(100, 100), (300, 100), (500, 400), (700, 600)])):
        assert abs(cx - x) < 2 and abs(cy - y) < 2


def test_rotated_copies_are_found(tmp_path):
    src = pymupdf.open()
    p = src.new_page(width=1000, height=800)
    _receptacle(p, 100, 100)
    _receptacle(p, 300, 100, rot=90)
    _receptacle(p, 500, 100, rot=180)
    pix = p.get_pixmap(matrix=pymupdf.Matrix(3, 3))
    out = pymupdf.open(); page = out.new_page(width=1000, height=800)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    path = tmp_path / "rot.pdf"; out.save(path)
    assert len(raster_match.find_on_render(str(path), 0, (92, 92, 108, 108))) == 3


def test_a_different_symbol_is_not_a_match(tmp_path):
    src = pymupdf.open()
    p = src.new_page(width=1000, height=800)
    _receptacle(p, 100, 100)
    s = p.new_shape(); s.draw_rect(pymupdf.Rect(296, 96, 304, 104)); s.finish(color=(0, 0, 0)); s.commit()
    pix = p.get_pixmap(matrix=pymupdf.Matrix(3, 3))
    out = pymupdf.open(); page = out.new_page(width=1000, height=800)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    path = tmp_path / "diff.pdf"; out.save(path)
    found = raster_match.find_on_render(str(path), 0, (92, 92, 108, 108))
    assert len(found) == 1


def test_the_api_never_imports_opencv():
    import subprocess, sys, os
    code = "import sys; import app.main; assert 'cv2' not in sys.modules, 'app.main imported cv2'"
    r = subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(os.path.dirname(__file__)), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
```

Also add the `cv2` assertion to `tests/test_api_import_boundary.py`'s existing subprocess code string (`'cv2' not in sys.modules`).

- [ ] **Step 2: Run, expect ImportError**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_raster_match.py -q`

- [ ] **Step 3: Implement `api/app/engine/raster_match.py`**

```python
"""Find every copy of a boxed symbol on a page render (B3b spec §6).

The raster path of 'find every one like this': when the box holds no
vector glyph -- a scanned sheet, a placed image -- the page is rendered
once and the box's pixels are slid over it with normalised
cross-correlation. Deterministic and constant-driven, like glyphs.py;
the threshold is a measured value with a test, not a tuned one.

OpenCV is imported here and nowhere else; app.main must never reach
this module (test_api_import_boundary.py).
"""
from __future__ import annotations

import cv2
import numpy as np
import pymupdf

MATCH_DPI = 200
MATCH_THRESHOLD = 0.80
MAX_PIXELS = 40_000_000
_ROTATIONS = (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE)


def _render(page) -> tuple[np.ndarray, float]:
    """Greyscale pixels of the visual page and the scale (px per point)."""
    scale = MATCH_DPI / 72
    if page.rect.width * page.rect.height * scale * scale > MAX_PIXELS:
        scale = (MAX_PIXELS / (page.rect.width * page.rect.height)) ** 0.5
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return img, scale


def _peaks(score: np.ndarray, tw: int, th: int) -> list[tuple[int, int, float]]:
    """Every location at or above the threshold, strongest first, with
    non-maximum suppression at half the template's size."""
    ys, xs = np.where(score >= MATCH_THRESHOLD)
    cands = sorted(((float(score[y, x]), int(x), int(y)) for y, x in zip(ys, xs)), reverse=True)
    kept: list[tuple[int, int, float]] = []
    for s, x, y in cands:
        if all(abs(x - kx) >= tw / 2 or abs(y - ky) >= th / 2 for kx, ky, _ in kept):
            kept.append((x, y, s))
    return kept


def find_on_render(path: str, page_index: int, rect) -> list[tuple[float, float, float, float]]:
    """Page-point rects (visual frame) of every place the pixels inside
    `rect` recur on the page, at 0/90/180/270°, the box itself included.
    Overlapping hits across rotations collapse to the strongest."""
    doc = pymupdf.open(path)
    page = doc[page_index]
    img, scale = _render(page)
    x0, y0, x1, y1 = (int(round(v * scale)) for v in rect)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    template = img[y0:y1, x0:x1]
    if template.size == 0 or min(template.shape) < 4:
        return []
    hits: list[tuple[int, int, int, int, float]] = []   # x, y, w, h, score
    for rot in _ROTATIONS:
        t = template if rot is None else cv2.rotate(template, rot)
        th, tw = t.shape
        if th > img.shape[0] or tw > img.shape[1]:
            continue
        score = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
        hits += [(x, y, tw, th, s) for x, y, s in _peaks(score, tw, th)]
    hits.sort(key=lambda h: -h[4])
    kept: list[tuple[int, int, int, int, float]] = []
    for h in hits:
        cx, cy = h[0] + h[2] / 2, h[1] + h[3] / 2
        if all(abs(cx - (k[0] + k[2] / 2)) >= h[2] / 2 or abs(cy - (k[1] + k[3] / 2)) >= h[3] / 2 for k in kept):
            kept.append(h)
    return [(x / scale, y / scale, (x + w) / scale, (y + h) / scale) for x, y, w, h, _ in kept]
```

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_raster_match.py tests/test_api_import_boundary.py tests/test_worker_import_boundary.py -q`
Expected: pass. If the rotated test finds the 90° copy twice (the receptacle is nearly symmetric under 180°), the cross-rotation NMS above handles it; if the threshold rejects a real copy, check the render scale is applied to `rect` before cropping — never lower `MATCH_THRESHOLD`.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/raster_match.py api/requirements.txt api/tests/test_engine_raster_match.py api/tests/test_api_import_boundary.py
git commit -m "Add raster template matching for find-every-one-like-this"
```

---

### Task 7: The `match` job

**Files:**
- Create: `api/app/worker/match_job.py`
- Modify: `api/app/worker/handlers.py:30-33`
- Test: `api/tests/test_worker_match.py`

**Interfaces:**
- Consumes: Task 2 `glyph_in`/`glyphs_on`/`matches_of`; Task 6 `find_on_render`; Task 1 `denormalize_box`; Task 5 `SymbolMatch`, `enqueue_match`.
- Produces: `match_job.find_matches(path, page_index, sheet: DetectedSheet, rect) -> list[tuple[float, float, float, float]]` (page points); the handler writes `matches` (sheet units `[x, y, w, h]`), `status="found"`; a vector sheet uses glyphs, a raster one uses the render.

- [ ] **Step 1: Failing tests**

`api/tests/test_worker_match.py`:

```python
"""The match job: one drawn box in, every copy on the sheet out, in
sheet units; vector by shape, raster by render (B3b spec §6)."""
import io

import pymupdf
from sqlalchemy import select

from app.jobs import copy, queue
from app.takeoff.models import Job, Sheet, SymbolMatch
from tests.test_engine_glyphs import _receptacle
from tests.test_worker_read import _run_all, _stored, inline  # noqa: F401


def _vector_pdf():
    doc = pymupdf.open()
    p = doc.new_page(width=1000, height=800)
    p.insert_text((72, 72), "E2.1 POWER PLAN")
    p.draw_rect(pymupdf.Rect(30, 30, 800, 760), color=(0, 0, 0))
    for x in (100, 300, 500):
        _receptacle(p, x, 400)
    s = p.new_shape(); s.draw_circle((700, 400), 4); s.finish(color=(0, 0, 0), fill=(0, 0, 0)); s.commit()
    return doc.tobytes()


def _raster_pdf():
    src = pymupdf.open(stream=_vector_pdf(), filetype="pdf")
    pix = src[0].get_pixmap(matrix=pymupdf.Matrix(3, 3))
    doc = pymupdf.open()
    p = doc.new_page(width=1000, height=800)
    p.insert_image(p.rect, stream=pix.tobytes("png"))
    p.insert_text((72, 72), "E2.1 POWER PLAN")
    return doc.tobytes()


def _read(db, project, dana, store, monkeypatch, data):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, store, data)
    queue.enqueue_read(db, d); _run_all(db)
    return db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))).first()


def _match(db, project, dana, sheet, box):
    m = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id, box=box, created_by=dana.id)
    db.add(m); db.flush()
    queue.enqueue_match(db, m); _run_all(db)
    db.refresh(m)
    return m


def test_a_vector_sheet_matches_by_shape(db, project, dana, inline, monkeypatch):
    sheet = _read(db, project, dana, inline, monkeypatch, _vector_pdf())
    # the box around the first receptacle, in sheet units (1000x800 page -> x same, y * 750/800)
    m = _match(db, project, dana, sheet, [100, 375, 16, 15])
    assert m.status == "found" and len(m.matches) == 3
    xs = sorted(x for x, _y, _w, _h in m.matches)
    assert [abs(x - e) <= 2 for x, e in zip(xs, (100, 300, 500))] == [True] * 3
    assert all(w >= 1 and h >= 1 for _x, _y, w, h in m.matches)


def test_a_raster_sheet_matches_by_render(db, project, dana, inline, monkeypatch):
    sheet = _read(db, project, dana, inline, monkeypatch, _raster_pdf())
    m = _match(db, project, dana, sheet, [100, 375, 16, 15])
    assert m.status == "found" and len(m.matches) == 3


def test_a_failing_match_marks_its_row(db, project, dana, inline, monkeypatch):
    from app.worker import match_job
    sheet = _read(db, project, dana, inline, monkeypatch, _vector_pdf())
    monkeypatch.setattr(match_job, "find_matches", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    m = _match(db, project, dana, sheet, [100, 375, 16, 15])
    assert m.status == "failed" and m.error == copy.MATCH_FAILED
    job = db.scalars(select(Job).where(Job.symbol_match_id == m.id)).one()
    assert job.status == "failed" and "RuntimeError" not in job.error
```

If the read job marks the raster page unreadable (no vector paths) and the sheet row carries `unreadable_reason`, the match must still run — the handler loads the sheet regardless; if `_read` yields no sheet for the raster PDF because detection needs a drawn rect, add `p.draw_rect(...)` to `_raster_pdf` as `_vector_pdf` does.

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_worker_match.py -q`
Expected: `Terminal: No handler for match` / import errors.

- [ ] **Step 3: Implement `api/app/worker/match_job.py`**

```python
"""match: every copy of one drawn box on one sheet (B3b spec §6). By
shape when the box holds a vector glyph, by render otherwise. Writes the
result onto the symbol_matches row; creates no item -- a person names
the result first (app/matches)."""
from __future__ import annotations

import uuid

import pymupdf
from sqlalchemy.orm import Session

from app.engine import glyphs, raster_match
from app.engine.contracts import DetectedSheet
from app.engine.page_frame import visual_words
from app.takeoff.ingest import denormalize_box, normalize_point, SHEET_SPACE_H, SHEET_SPACE_W
from app.takeoff.models import Document, Job, Sheet, SymbolMatch
from app.worker.blobs import blob_to_tempfile
from app.worker.classify_job import _detected
from app.worker.handlers import register


def find_matches(path: str, page_index: int, sheet: DetectedSheet, rect) -> list[tuple[float, float, float, float]]:
    """Page-point rects of every copy of what is inside `rect`, the boxed
    one included. One function, two methods: the glyph in the box decides."""
    doc = pymupdf.open(path)
    page = doc[page_index]
    words = visual_words(page)
    glyph = glyphs.glyph_in(page, rect, words)
    if glyph is not None:
        return [g.rect for g in glyphs.matches_of(glyph, glyphs.glyphs_on(page, sheet.region, words))]
    return raster_match.find_on_render(path, page_index, rect)


def _to_sheet_units(rects, width_pt: float, height_pt: float) -> list[list[int]]:
    out = []
    for x0, y0, x1, y1 in rects:
        out.append([normalize_point((x0 + x1) / 2, width_pt, SHEET_SPACE_W), normalize_point((y0 + y1) / 2, height_pt, SHEET_SPACE_H),
                    max(1, normalize_point(x1 - x0, width_pt, SHEET_SPACE_W)), max(1, normalize_point(y1 - y0, height_pt, SHEET_SPACE_H))])
    return out


@register("match")
def run(db: Session, job: Job) -> None:
    match = db.get(SymbolMatch, job.symbol_match_id) if job.symbol_match_id else None
    sheet = db.get(Sheet, match.sheet_id) if match is not None else None
    doc = db.get(Document, uuid.UUID(sheet.takeoff_id)) if sheet is not None and sheet.takeoff_id else None
    if match is None or sheet is None or doc is None:
        return   # deleted between queue and run
    detected = _detected(sheet)
    rect = denormalize_box(match.box, sheet.width_pt, sheet.height_pt)
    with blob_to_tempfile(doc.storage_key, doc.filename) as path:
        rects = find_matches(path, detected.page_index, detected, rect)
    match.matches = _to_sheet_units(rects, sheet.width_pt, sheet.height_pt)
    match.status, match.error = "found", ""
    db.flush()
```

`handlers._load_handlers`: add `"match_job"` to the tuple (and update its comment to "five").

Check `denormalize_box` lives where `ingest` says (Task 1) and that `SHEET_SPACE_W/H` are exported names in `ingest.py`.

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_worker_match.py tests/test_worker_import_boundary.py tests/test_worker_render.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/match_job.py api/app/worker/handlers.py api/tests/test_worker_match.py
git commit -m "Add the match job: one drawn box in, every copy on the sheet out"
```

---

### Task 8: The `add` action — one item from a match, undoable

**Files:**
- Modify: `api/app/takeoff/undo.py:76` (`REVERSIBLE`), `api/app/takeoff/undo_apply.py:76-96` (`apply`), `api/app/takeoff/review.py` (new `add_item`)
- Modify: `api/app/takeoff/merge.py` (`merge_sheet` bucket build, `drop_sheets`)
- Test: `api/tests/test_review_state_machine.py` (or a new `api/tests/test_add_item.py`), `api/tests/test_merge.py`

**Interfaces:**
- Produces: `review.add_item(db, actor, *, project, sheet, name, symbol, system, quantity, placements, x, y, source_tag, status, warning: dict | None, label) -> tuple[Item, Action]` — commits kind `"add"`, `before={}`, `after=` the delete-style snapshot (item columns minus `version`, plus `warnings`); undo deletes the row, redo restores it. `merge_sheet` skips `match:` items on both the bucket and the leftover sweep; `drop_sheets` treats a `match:` item like an approved one.

- [ ] **Step 1: Failing tests**

`api/tests/test_add_item.py`:

```python
"""An item a person adds (from a symbol match) is one undoable `add`
action: undo removes it and its warning, redo brings both back."""
from sqlalchemy import select

from app.takeoff import review, undo
from app.takeoff.models import Item, Warning


def _warning():
    return {"reason": "legend", "title": "Symbol not in legend", "found": "A symbol appears 3 times on E2.1 but isn't in the legend.",
            "why": "An unclassified symbol has no catalog item, so it isn't counted or priced yet.",
            "fix": "Assign a classification, or reject it if it isn't a device.", "where": "E2.1."}


def test_add_item_is_one_reversible_action(db, project, sheet, dana):
    item, action = review.add_item(
        db, dana, project=project, sheet=sheet, name="Unclassified symbol", symbol="generic", system="Unknown",
        quantity=3, placements=[[100, 100, 8, 8], [200, 100, 8, 8], [300, 100, 8, 8]], x=100, y=100,
        source_tag="match:abc", status="attention", warning=_warning(), label="Added 3 symbols from a drawn symbol")
    db.commit()
    assert action.kind == "add" and action.item_id == item.id and action.before == {}
    assert db.scalar(select(Warning).where(Warning.item_id == item.id)) is not None
    assert undo.undo_head(db, dana, project.id).id == action.id

    undo.undo(db, dana, project.id); db.commit()
    assert db.get(Item, item.id) is None
    assert db.scalar(select(Warning).where(Warning.item_id == item.id)) is None

    undo.redo(db, dana, project.id); db.commit()
    restored = db.get(Item, item.id)
    assert restored is not None and restored.quantity == 3 and restored.source_tag == "match:abc"
    assert db.scalar(select(Warning).where(Warning.item_id == item.id)) is not None


def test_a_named_item_lands_ready_without_a_warning(db, project, sheet, dana):
    item, _ = review.add_item(
        db, dana, project=project, sheet=sheet, name="Duplex receptacle", symbol="receptacle", system="Power",
        quantity=2, placements=[[100, 100, 8, 8], [200, 100, 8, 8]], x=100, y=100,
        source_tag="match:def", status="ready", warning=None, label="Added 2 duplex receptacles from a drawn symbol")
    db.commit()
    assert item.status.value == "ready" and db.scalar(select(Warning).where(Warning.item_id == item.id)) is None
```

Append to `api/tests/test_merge.py` (use that file's existing helpers for a project/sheet and a `rows` payload — read them first; the assertions are what matter):

```python
def test_merge_never_touches_a_match_item(db, project, sheet, dana):
    from app.takeoff import merge, review
    item, _ = review.add_item(db, dana, project=project, sheet=sheet, name="Duplex receptacle", symbol="receptacle",
                              system="Power", quantity=2, placements=[[100, 100, 8, 8], [200, 100, 8, 8]], x=100, y=100,
                              source_tag=f"match:{uuid.uuid4()}", status="ready", warning=None, label="Added")
    db.flush()
    merge.merge_sheet(db, project=project, sheet=sheet, rows=[], ai_reading=None)   # a re-run reporting nothing
    db.flush()
    assert db.get(Item, item.id) is not None


def test_drop_sheets_keeps_a_sheet_holding_a_match_item(db, project, sheet, dana):
    from app.jobs import copy
    from app.takeoff import merge, review
    review.add_item(db, dana, project=project, sheet=sheet, name="Duplex receptacle", symbol="receptacle",
                    system="Power", quantity=1, placements=[[100, 100, 8, 8]], x=100, y=100,
                    source_tag=f"match:{uuid.uuid4()}", status="ready", warning=None, label="Added")
    db.flush()
    merge.drop_sheets(db, [sheet.id]); db.flush()
    assert db.get(Sheet, sheet.id) is not None and sheet.unreadable_reason == copy.PAGE_GONE
```

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_add_item.py tests/test_merge.py -q`

- [ ] **Step 3: Implement**

`api/app/takeoff/review.py` — add (imports: `Item`, `Warning`, `WarningReason`, `ReviewStatus`, `commit`, `encode_snapshot`, `_column_snapshot`, `WARNINGS_KEY` already used in this module):

```python
def add_item(db: DbSession, actor: User, *, project, sheet, name: str, symbol: str, system: str, quantity,
             placements: list, x: int, y: int, source_tag: str, status: str, warning: dict | None, label: str) -> tuple[Item, Action]:
    """A person adds an item (B3b: the result of a symbol match, named or
    'not sure'). The mirror of `delete_item`: `before` is empty and
    `after` is the same full snapshot a delete records, so undo removes
    the row and redo restores it, warning included. Never approved here
    -- approval is its own act."""
    item = Item(
        id=uuid.uuid4(), project_id=project.id, sheet_id=sheet.id, symbol=symbol, name=name, description="",
        system=system, category="Devices" if status == "ready" else "Unclassified", quantity=quantity, unit="ea",
        status=ReviewStatus(status), x=x, y=y, placements=placements, source_tag=source_tag,
    )
    db.add(item)
    db.flush()
    warnings = []
    if warning:
        w = Warning(id=uuid.uuid4(), item_id=item.id, sheet_id=None, reason=WarningReason(warning["reason"]),
                    title=warning["title"], found=warning["found"], why=warning["why"], fix=warning["fix"], where_=warning["where"])
        db.add(w)
        db.flush()
        warnings.append(w)
    snapshot = _column_snapshot(item)
    snapshot.pop("version", None)
    after = {**snapshot, WARNINGS_KEY: [encode_snapshot(_column_snapshot(w)) for w in warnings],
             LABOR_LINE_KEY: None, MATERIAL_PRICE_KEY: None}
    action = commit(db, actor=actor, project_id=project.id, kind="add", label=label, before={}, after=after,
                    item_id=item.id, sheet_id=sheet.id)
    return item, action
```

`undo.py`: `REVERSIBLE` gains `"add"`. `undo_apply.apply`:

```python
    elif action.kind == "add":
        _apply_add(db, action, direction)
```

and

```python
def _apply_add(db: DbSession, action: Action, direction: str) -> None:
    """The mirror of _apply_delete: an undo (`before`) removes the added
    row -- ON DELETE CASCADE takes its warning -- and a redo (`after`)
    restores the row and its warnings from the snapshot `add_item`
    recorded."""
    if direction == "before":
        _delete_row_if_present(db, Item, action.item_id)
        return
    state = action.after
    item_fields = {k: v for k, v in state.items() if k not in NESTED_SNAPSHOT_KEYS}
    _restore_row_if_missing(db, Item, decode_snapshot(item_fields, ITEM_SNAPSHOT_TYPES))
    for encoded in state.get(WARNINGS_KEY, []):
        _restore_row_if_missing(db, Warning, decode_snapshot(encoded, WARNING_SNAPSHOT_TYPES))
```

Check `_delete_row_if_present`'s signature in `undo_apply.py` (`(db, model, pk)`) and that `NESTED_SNAPSHOT_KEYS` covers `warnings`, `labor_line`, `material_price`.

`merge.py` — in `merge_sheet`, when building `by_key`, skip match items; and in `drop_sheets`, treat them as approved:

```python
    for i in existing:
        if i.source_tag.startswith("match:"):
            continue   # a person's own addition: no engine row ever matches or removes it
        by_key.setdefault(_key(sheet.number, i.source_tag), []).append(i)
```

```python
            if item.status is ReviewStatus.APPROVED or item.source_tag.startswith("match:"):
                any_approved = True
                continue
```

Check `merge.py`'s exact variable names around line 326 and 445 before editing.

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_add_item.py tests/test_merge.py tests/test_undo_redo.py tests/test_review_state_machine.py tests/test_action_log.py -q`
Expected: pass. If a test enumerates `REVERSIBLE` kinds by name, add `"add"` to its expectation.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/review.py api/app/takeoff/undo.py api/app/takeoff/undo_apply.py api/app/takeoff/merge.py api/tests/test_add_item.py api/tests/test_merge.py
git commit -m "Add the reversible add action and keep match items out of the merge"
```

---

### Task 9: The matches API

**Files:**
- Create: `api/app/matches/__init__.py`, `api/app/matches/schemas.py`, `api/app/matches/service.py`, `api/app/matches/router.py`
- Modify: `api/app/main.py` (include router), `api/tests/test_tenancy.py` (`TENANCY_TABLE`), `api/tests/test_auth.py` if it lists GET routes
- Test: `api/tests/test_matches_api.py`

**Interfaces:**
- Consumes: Task 5 `SymbolMatch`, `enqueue_match`; Task 8 `review.add_item`; `snapshot.item_out`; `load_sheet`, `load_project`, `not_found`.
- Produces routes (spec §7): `POST /api/sheets/{sheet_id}/matches`, `GET /api/symbol-matches/{id}`, `POST /api/symbol-matches/{id}/items`, `DELETE /api/symbol-matches/{id}`; `SymbolMatchOut{id, sheet_id, box, status, count, matches, error}`; `MatchBoxIn{x, y, w, h}`; `MatchItemsIn{name: str | None, symbol: str | None, system: str | None, not_sure: bool = False}`; error codes `sheet_still_reading`, `match_in_progress`, `invalid_box`, `match_not_ready`, `match_resolved`.

- [ ] **Step 1: Failing tests**

`api/tests/test_matches_api.py` — use the fixtures `client`, `signed_in_user`, `project`, `sheet`, `db`, `other_org_project` from `conftest.py` (read it for exact names and how a signed-in client is obtained). Tests:

```python
import uuid

from sqlalchemy import select

from app.jobs import copy
from app.takeoff.models import Action, Item, Job, SymbolMatch, Warning


def _sheet_read(db, sheet):
    sheet.unreadable_reason = ""
    db.flush()


def _box():
    return {"x": 500, "y": 375, "w": 12, "h": 12}


def test_post_creates_a_pending_match_and_queues_a_job(client, signed_in_user, db, project, sheet):
    r = client.post(f"/api/sheets/{sheet.id}/matches", json=_box())
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"id", "sheet_id", "box", "status", "count", "matches", "error"}
    assert body["status"] == "pending" and body["count"] == 0 and body["matches"] == []
    assert db.scalar(select(Job).where(Job.kind == "match", Job.symbol_match_id == uuid.UUID(body["id"]))) is not None


def test_a_second_box_while_one_is_pending_is_refused(client, signed_in_user, db, project, sheet):
    assert client.post(f"/api/sheets/{sheet.id}/matches", json=_box()).status_code == 201
    r = client.post(f"/api/sheets/{sheet.id}/matches", json=_box())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "match_in_progress"


def test_a_box_outside_the_sheet_or_too_small_is_refused(client, signed_in_user, sheet):
    assert client.post(f"/api/sheets/{sheet.id}/matches", json={"x": 1200, "y": 10, "w": 10, "h": 10}).status_code == 422
    assert client.post(f"/api/sheets/{sheet.id}/matches", json={"x": 100, "y": 10, "w": 2, "h": 10}).status_code == 422


def _found(db, project, sheet, user_id, n=3):
    m = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id, box=[500, 375, 12, 12],
                    status="found", matches=[[100 * i + 100, 375, 12, 12] for i in range(n)], created_by=user_id)
    db.add(m); db.commit()
    return m


def test_get_returns_the_result_without_internals(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    body = client.get(f"/api/symbol-matches/{m.id}").json()
    assert body["status"] == "found" and body["count"] == 3 and len(body["matches"]) == 3
    assert not any(k in body for k in ("score", "threshold", "dpi", "method", "job_id"))


def test_naming_the_result_adds_one_ready_item_as_one_action(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    r = client.post(f"/api/symbol-matches/{m.id}/items", json={"name": "Duplex receptacle", "symbol": "receptacle", "system": "Power"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["label"] == "Added 3 duplex receptacles from a drawn symbol"
    item = db.get(Item, uuid.UUID(body["item"]["id"]))
    assert item.quantity == 3 and item.status.value == "ready" and item.source_tag == f"match:{m.id}"
    assert item.placements == m.matches and (item.x, item.y) == (500, 375)
    actions = list(db.scalars(select(Action).where(Action.project_id == project.id, Action.kind == "add")))
    assert len(actions) == 1
    db.refresh(m)
    assert m.resolved_at is not None


def test_not_sure_adds_an_unclassified_item_needing_attention(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    r = client.post(f"/api/symbol-matches/{m.id}/items", json={"not_sure": True})
    assert r.status_code == 201, r.text
    item = db.get(Item, uuid.UUID(r.json()["item"]["id"]))
    assert item.name == "Unclassified symbol" and item.status.value == "attention"
    w = db.scalar(select(Warning).where(Warning.item_id == item.id))
    assert w.title == "Symbol not in legend" and w.found == f"A symbol appears 3 times on {sheet.number} but isn't in the legend."


def test_a_resolved_or_pending_match_cannot_be_accepted(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    assert client.post(f"/api/symbol-matches/{m.id}/items", json={"not_sure": True}).status_code == 201
    r = client.post(f"/api/symbol-matches/{m.id}/items", json={"not_sure": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "match_resolved"
    p = client.post(f"/api/sheets/{sheet.id}/matches", json=_box()).json()
    r = client.post(f"/api/symbol-matches/{p['id']}/items", json={"not_sure": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "match_not_ready"


def test_discard_removes_the_match_and_no_item(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    assert client.delete(f"/api/symbol-matches/{m.id}").status_code == 204
    assert db.get(SymbolMatch, m.id) is None
    assert db.scalar(select(Item).where(Item.source_tag == f"match:{m.id}")) is None


def test_another_orgs_match_is_a_404(client, signed_in_user, db, other_org_project):
    other_sheet = db.scalars(select(Sheet).where(Sheet.project_id == other_org_project.id)).first()
    r = client.post(f"/api/sheets/{other_sheet.id}/matches", json=_box())
    assert r.status_code == 404
```

Add to `TENANCY_TABLE` in `tests/test_tenancy.py` four rows following the file's existing tuple shape (method, template, path builder, body, expected):

```python
    ("POST", "/api/sheets/{sheet_id}/matches",
     lambda p, s, i: f"/api/sheets/{s.id}/matches", {"x": 500, "y": 375, "w": 12, "h": 12}, None),
    ("GET", "/api/symbol-matches/{match_id}", ..., None, None),
    ("POST", "/api/symbol-matches/{match_id}/items", ..., {"not_sure": True}, None),
    ("DELETE", "/api/symbol-matches/{match_id}", ..., None, None),
```

Read how the table builds paths for ids it does not own (`p, s, i` are project, sheet, item); if it has no match fixture, extend its seeding fixture to create one `SymbolMatch` per org (status `found`, one match) and thread its id into the lambda the same way `i.id` is. Do the same in `test_auth.py` if it iterates GET routes for 401.

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_matches_api.py tests/test_tenancy.py -q`

- [ ] **Step 3: Implement**

`api/app/matches/schemas.py`:

```python
"""The wire shape of a symbol match. Nothing here names a score, a
threshold, a dpi, a method, or a job (CLAUDE.md: processing internals
stop at the API boundary)."""
import uuid

from pydantic import BaseModel, Field

from app.takeoff.schemas import ItemOut


class MatchBoxIn(BaseModel):
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=750)
    w: int = Field(ge=4, le=1000)
    h: int = Field(ge=4, le=750)


class MatchItemsIn(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    symbol: str | None = None
    system: str | None = None
    not_sure: bool = False


class SymbolMatchOut(BaseModel):
    id: uuid.UUID
    sheet_id: uuid.UUID
    box: list[int]
    status: str
    count: int
    matches: list[list[int]]
    error: str


class MatchItemOut(BaseModel):
    label: str
    version: int
    item: ItemOut
```

`api/app/matches/service.py`:

```python
"""Symbol matches: create, read, accept, discard. Accepting is the one
path here that creates an item, and it goes through review.add_item so
the action log, undo, and every status rule see an ordinary item."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.jobs import copy, queue
from app.jobs.queue import _IN_FLIGHT
from app.takeoff import actions, review
from app.takeoff.models import Job, Project, Sheet, SymbolMatch
from app.takeoff.router import load_project, not_found

NOT_SURE_NAME = "Unclassified symbol"


def load_match(match_id: uuid.UUID, db: DbSession, user: User) -> SymbolMatch:
    match = db.get(SymbolMatch, match_id)
    if match is None:
        raise not_found()
    load_project(match.project_id, db, user)   # the one tenancy gate
    return match


def _plural(name: str, n: int) -> str:
    return name.lower() if n == 1 else name.lower() + ("s" if not name.lower().endswith("s") else "")


def create(db: DbSession, actor: User, sheet: Sheet, box: list[int]) -> SymbolMatch:
    if sheet.unreadable_reason == copy.PAGE_GONE:
        raise DomainError("sheet_gone", copy.PAGE_GONE, status=409)
    if not sheet.width_pt or not sheet.height_pt:
        raise DomainError("sheet_still_reading", copy.DRAWINGS_READING, status=409)
    if box[0] - box[2] / 2 < 0 or box[0] + box[2] / 2 > 1000 or box[1] - box[3] / 2 < 0 or box[1] + box[3] / 2 > 750:
        raise DomainError("invalid_box", "Draw the box inside the sheet.", status=422)
    pending = db.scalars(select(SymbolMatch).where(SymbolMatch.sheet_id == sheet.id, SymbolMatch.status == "pending")).first()
    if pending is not None:
        raise DomainError("match_in_progress", "A search is already running on this sheet. Wait for it to finish.", status=409)
    project = db.get(Project, sheet.project_id)
    match = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id, box=list(box), created_by=actor.id)
    db.add(match)
    db.flush()
    queue.enqueue_match(db, match)
    return match


def accept(db: DbSession, actor: User, match: SymbolMatch, *, name: str | None, symbol: str | None, system: str | None,
           not_sure: bool):
    if match.resolved_at is not None:
        raise DomainError("match_resolved", "This search has already been added or discarded.", status=409)
    if match.status != "found":
        raise DomainError("match_not_ready", "The search hasn't finished yet.", status=409)
    if not not_sure and not (name or "").strip():
        raise DomainError("name_required", "Name the symbol, or choose Not sure yet.", status=422)
    sheet = db.get(Sheet, match.sheet_id)
    project = db.get(Project, match.project_id)
    n = len(match.matches)
    if not_sure:
        warning = {"reason": "legend", "title": "Symbol not in legend",
                   "found": f"A symbol appears {n} times on {sheet.number} but isn't in the legend.",
                   "why": "An unclassified symbol has no catalog item, so it isn't counted or priced yet.",
                   "fix": "Assign a classification, or reject it if it isn't a device.", "where": f"{sheet.number}."}
        item_name, item_symbol, item_system, status = NOT_SURE_NAME, "generic", "Unknown", "attention"
        label = f"Added {n} unclassified symbol{'s' if n != 1 else ''} from a drawn symbol"
    else:
        warning = None
        item_name, item_symbol, item_system, status = name.strip(), symbol or "generic", system or "Unknown", "ready"
        label = f"Added {n} {_plural(item_name, n)} from a drawn symbol"
    item, action = review.add_item(
        db, actor, project=project, sheet=sheet, name=item_name, symbol=item_symbol, system=item_system, quantity=n,
        placements=[list(m) for m in match.matches], x=match.box[0], y=match.box[1],
        source_tag=f"match:{match.id}", status=status, warning=warning, label=label)
    match.resolved_at = datetime.now(timezone.utc)
    db.flush()
    return item, action


def discard(db: DbSession, actor: User, match: SymbolMatch) -> None:
    if match.resolved_at is not None:
        raise DomainError("match_resolved", "This search has already been added or discarded.", status=409)
    actions.commit(db, actor=actor, project_id=match.project_id, kind="match_discard",
                   label="Discarded a symbol search", before={"box": match.box}, after={}, sheet_id=match.sheet_id)
    db.delete(match)
    db.flush()
```

The `"match_discard"` kind is audited, not reversible (not in `REVERSIBLE`), like notes. Check `Action.kind` has no check constraint limiting kinds (grep the migrations); if it does, add the kind there.

`api/app/matches/router.py`:

```python
"""Thin HTTP layer for symbol matches. router -> service -> models."""
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session as DbSession

from app.auth.dependencies import current_user
from app.db import get_db
from app.identity.models import User
from app.matches import service
from app.matches.schemas import MatchBoxIn, MatchItemOut, MatchItemsIn, SymbolMatchOut
from app.takeoff.models import SymbolMatch
from app.takeoff.router import load_sheet
from app.takeoff.snapshot import item_out

router = APIRouter(prefix="/api", tags=["matches"])


def _out(m: SymbolMatch) -> SymbolMatchOut:
    return SymbolMatchOut(id=m.id, sheet_id=m.sheet_id, box=list(m.box), status=m.status,
                          count=len(m.matches or []), matches=[list(x) for x in (m.matches or [])], error=m.error)


@router.post("/sheets/{sheet_id}/matches", response_model=SymbolMatchOut, status_code=201)
def create_match(sheet_id: uuid.UUID, payload: MatchBoxIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    sheet = load_sheet(sheet_id, db, user)
    match = service.create(db, user, sheet, [payload.x, payload.y, payload.w, payload.h])
    db.commit()
    return _out(match)


@router.get("/symbol-matches/{match_id}", response_model=SymbolMatchOut)
def get_match(match_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return _out(service.load_match(match_id, db, user))


@router.post("/symbol-matches/{match_id}/items", response_model=MatchItemOut, status_code=201)
def accept_match(match_id: uuid.UUID, payload: MatchItemsIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    match = service.load_match(match_id, db, user)
    item, action = service.accept(db, user, match, name=payload.name, symbol=payload.symbol, system=payload.system,
                                  not_sure=payload.not_sure)
    db.commit()
    return MatchItemOut(label=action.label, version=item.version, item=item_out(db, item))


@router.delete("/symbol-matches/{match_id}", status_code=204)
def discard_match(match_id: uuid.UUID, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    match = service.load_match(match_id, db, user)
    service.discard(db, user, match)
    db.commit()
    return Response(status_code=204)
```

`main.py`: `from app.matches.router import router as matches_router` and `app.include_router(matches_router)` beside the scope router. Check how single-item mutation endpoints return `version` (a project snapshot version vs item version) and match `MatchItemOut.version` to what `mutateItem` in `api.js` expects (`raw.version`) — use the same source the approve endpoint uses.

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_matches_api.py tests/test_tenancy.py tests/test_auth.py tests/test_observability.py tests/test_api_import_boundary.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/matches api/app/main.py api/tests/test_matches_api.py api/tests/test_tenancy.py api/tests/test_auth.py
git commit -m "Add the symbol match routes: draw, poll, name or not sure, discard"
```

---

### Task 10: Client store — match calls, state, copy

**Files:**
- Create: `src/lib/matchCopy.js`
- Modify: `src/lib/store/api.js` (four calls + export), `src/lib/store/api-mapping.js` (`mapMatch`), `src/lib/useReviewStore.js` (match state)
- Test: `src/lib/store/api.test.js` (or the existing api store test file — find it with `ls src/lib/store/*.test.js`), `src/lib/matchCopy.test.js`

**Interfaces:**
- Produces: store `createMatch(sheetId, {x, y, w, h}) -> match`, `getMatch(id) -> match`, `acceptMatch(id, {name, symbol, system} | {notSure: true}) -> {label, version, item}`, `discardMatch(id)`; `mapMatch(raw) -> {id, sheetId, box, status, count, matches, error}`; `useReviewStore` returns `match`, `startMatch(sheetId, box)`, `acceptMatch(fields)`, `discardMatch()`, `clearMatch()` — `match` is `null` or `{id, sheetId, box, status, count, matches, error}` and is polled every 2 s while `pending`; `matchCopy` exports `DRAW_PROMPT`, `SEARCHING`, `found(n)`, `NONE_FOUND`, `NOT_SURE`, `addLabel(n)`.

- [ ] **Step 1: Failing tests**

`src/lib/matchCopy.test.js`:

```js
import { describe, expect, it } from "vitest";
import * as copy from "./matchCopy.js";

describe("match copy", () => {
  it("reads as an instrument", () => {
    for (const s of [copy.DRAW_PROMPT, copy.SEARCHING, copy.found(3), copy.NONE_FOUND, copy.NOT_SURE, copy.addLabel(3)]) {
      expect(s).not.toMatch(/!|please|successfully|\bAI\b|%/);
      expect(s[0]).toBe(s[0].toUpperCase());
    }
  });
  it("counts", () => {
    expect(copy.found(3)).toBe("3 matches found");
    expect(copy.found(1)).toBe("1 match found");
    expect(copy.addLabel(14)).toBe("Add 14 to the takeoff");
  });
});
```

In the api store test file, add (following its existing `fetch` stubbing pattern):

```js
it("createMatch posts the box and maps the result", async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({ id: "m1", sheet_id: "s1", box: [500, 375, 12, 12], status: "pending", count: 0, matches: [], error: "" }, 201));
  const m = await store.createMatch("s1", { x: 500, y: 375, w: 12, h: 12 });
  expect(fetchMock.mock.calls[0][0]).toBe("/api/sheets/s1/matches");
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ x: 500, y: 375, w: 12, h: 12 });
  expect(m).toEqual({ id: "m1", sheetId: "s1", box: [500, 375, 12, 12], status: "pending", count: 0, matches: [], error: "" });
});

it("acceptMatch sends not_sure or the name and invalidates the cache", async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({ label: "Added 3 unclassified symbols from a drawn symbol", version: 2, item: ITEM_WIRE }, 201));
  const r = await store.acceptMatch("m1", { notSure: true });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ not_sure: true });
  expect(r.label).toMatch(/^Added 3/);
});
```

Use the file's existing item wire fixture for `ITEM_WIRE` and its response helper names.

- [ ] **Step 2: Run, expect failures**

Run: `npm test -- --run src/lib`

- [ ] **Step 3: Implement**

`src/lib/matchCopy.js`:

```js
/** Copy for "find every one like this" (B3b spec §9). Sentence case,
 *  plain construction terms, no processing internals. */
export const DRAW_PROMPT = "Drag a box around one symbol";
export const SEARCHING = "Searching this sheet…";
export const NONE_FOUND = "No other symbols like this were found";
export const NOT_SURE = "Not sure yet";
export const found = (n) => `${n} ${n === 1 ? "match" : "matches"} found`;
export const addLabel = (n) => `Add ${n} to the takeoff`;
```

`api-mapping.js`:

```js
export function mapMatch(m) {
  return { id: m.id, sheetId: m.sheet_id, box: m.box, status: m.status, count: m.count, matches: m.matches ?? [], error: m.error ?? "" };
}
```

`api.js` inside `createApiStore` (next to `setScale`):

```js
  async function createMatch(sheetId, { x, y, w, h }) {
    return mapMatch(await request(`/api/sheets/${sheetId}/matches`, { method: "POST", body: { x, y, w, h } }));
  }

  async function getMatch(id) {
    return mapMatch(await request(`/api/symbol-matches/${id}`));
  }

  /** Names the result (one item, Ready to review) or files it as "not
   *  sure" (Needs attention). Either way one undoable action -- the
   *  server's `add` -- so the cache is invalidated exactly as a
   *  single-item mutation's is. */
  async function acceptMatch(id, fields) {
    const body = fields.notSure ? { not_sure: true } : { name: fields.name, symbol: fields.symbol, system: fields.system };
    const raw = await request(`/api/symbol-matches/${id}/items`, { method: "POST", body });
    invalidateCache();
    return { label: raw.label, version: raw.version, item: mapItem(raw.item) };
  }

  async function discardMatch(id) {
    await request(`/api/symbol-matches/${id}`, { method: "DELETE" });
  }
```

and export all four in the returned object.

`useReviewStore.js` — add state and actions (place after `setScale`):

```js
  // "Find every one like this" (B3b): the one search in flight on the
  // sheet in view. Polled while pending; the result boxes it carries are
  // not items and no layer toggle or total ever sees them.
  const [match, setMatch] = useState(null);
  const startMatch = useCallback(async (sheetId, box) => {
    try {
      const m = await store.createMatch(sheetId, box);
      setMatch(m);
      return m;
    } catch (err) {
      if (handleSignedOut(err)) return null;
      setMatch({ id: null, sheetId, box: [box.x, box.y, box.w, box.h], status: "failed", count: 0, matches: [], error: err?.message || "" });
      return null;
    }
  }, [store, handleSignedOut]);
  useEffect(() => {
    if (!match?.id || match.status !== "pending") return undefined;
    const t = setInterval(async () => {
      try { setMatch(await store.getMatch(match.id)); } catch (err) { handleSignedOut(err); }
    }, 2000);
    return () => clearInterval(t);
  }, [store, match?.id, match?.status, handleSignedOut]);
  const acceptMatch = useCallback(async (fields) => {
    if (!match?.id) return null;
    const res = await runItemMutation(null, () => store.acceptMatch(match.id, fields), { adds: true });
    if (res) setMatch(null);
    return res;
  }, [store, match, runItemMutation]);
  const discardMatch = useCallback(async () => {
    if (match?.id) { try { await store.discardMatch(match.id); } catch (err) { handleSignedOut(err); } }
    setMatch(null);
  }, [store, match, handleSignedOut]);
  const clearMatch = useCallback(() => setMatch(null), []);
```

`runItemMutation` gains an `adds` option: when set, `patchItem` is replaced by appending `res.item` to `snapshot.items` (write `addItemLocal(item, version)` beside `removeItemLocal`). Return `match, startMatch, acceptMatch, discardMatch, clearMatch` from the hook.

- [ ] **Step 4: Run**

Run: `npm test -- --run src/lib && npm run build`
Expected: pass, build clean.

- [ ] **Step 5: Commit**

```bash
git add src/lib/matchCopy.js src/lib/matchCopy.test.js src/lib/store/api.js src/lib/store/api-mapping.js src/lib/useReviewStore.js src/lib/store/*.test.js
git commit -m "Client store: create, poll, accept and discard a symbol match"
```

---

### Task 11: The canvas — boxed placements, the Find-like-this tool, result boxes

**Files:**
- Modify: `src/components/BlueprintCanvas.jsx` (placement rings → boxes; `tool === "match"` drag; result boxes; banner), `src/components/CanvasPane.jsx` (tool button), `src/components/Workspace.jsx` (wiring), `src/styles.css` (`.viewport--boxing`, `.matchbox` tokens only if new colours are needed — use `--blue`)
- Test: `src/components/BlueprintCanvas.test.jsx`

**Interfaces:**
- Consumes: `sheetGeometry.fromPaper/toPaper/pointToPaper`; store `match`, `startMatch`.
- Produces: `BlueprintCanvas` props `match` (`null | {box, matches, status}`), `onDrawBox({x, y, w, h})` (sheet units); tool name `"match"`; a placement `[x, y, w, h]` renders as `<rect class="placement-box">` and `[x, y]` as the existing `<circle r=5>`; result boxes render as `<rect class="matchbox">` with `stroke="var(--blue)"`, `fill="none"`, never a status colour, unaffected by `layers`.

- [ ] **Step 1: Failing tests**

Append to `src/components/BlueprintCanvas.test.jsx`:

```js
describe("boxed placements and symbol matches", () => {
  const SHEET = { ...THREE_TWO };

  it("outlines a selected item's boxed placements and rings its point placements", () => {
    const items = [{ id: "i1", sheetId: "s1", x: 100, y: 100, status: "ready", symbol: "receptacle", name: "r", quantity: 2, unit: "ea",
                     placements: [[100, 100, 20, 10], [300, 100]] }];
    const { container } = canvas(SHEET, items, { selectedId: "i1" });
    const box = container.querySelector("rect.placement-box");
    expect(box).not.toBeNull();
    expect(box.getAttribute("width")).toBe("20");
    expect(Number(box.getAttribute("height"))).toBeCloseTo(10 * (667 / 750), 1);
    expect(container.querySelectorAll("circle.placement-ring").length).toBe(1);
  });

  it("draws result boxes in blueprint blue regardless of layers", () => {
    const match = { status: "found", box: [100, 100, 20, 10], matches: [[100, 100, 20, 10], [300, 100, 20, 10]] };
    const { container } = canvas(SHEET, [], { match, layers: { ...LAYERS, detected: false, approved: false } });
    const boxes = container.querySelectorAll("rect.matchbox");
    expect(boxes.length).toBe(2);
    expect(boxes[0].getAttribute("stroke")).toBe("var(--blue)");
    expect(boxes[0].getAttribute("fill")).toBe("none");
  });

  it("hands a dragged box up in sheet units", () => {
    const onDrawBox = vi.fn();
    const { container } = canvas(SHEET, [], { tool: "match", onDrawBox });
    const vp = container.querySelector(".viewport");
    vp.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 667 });
    act(() => { fireEvent.pointerDown(vp, { clientX: 100, clientY: 100, pointerId: 1 }); });
    act(() => { fireEvent.pointerMove(vp, { clientX: 140, clientY: 120, pointerId: 1 }); });
    act(() => { fireEvent.pointerUp(vp, { clientX: 140, clientY: 120, pointerId: 1 }); });
    expect(onDrawBox).toHaveBeenCalledTimes(1);
    const box = onDrawBox.mock.calls[0][0];
    // at scale 1 with no translation: paper (100..140, 100..120) -> centre (120, 110 / ky), extent (40, 20 / ky)
    expect(box.x).toBe(120); expect(box.w).toBe(40);
    expect(box.y).toBeCloseTo(110 * 750 / 667, 0); expect(box.h).toBeCloseTo(20 * 750 / 667, 0);
  });
});
```

Import `fireEvent` from testing-library. The canvas's initial `view` may not be `{scale: 1, tx: 0, ty: 0}` — read `BlueprintCanvas.jsx`'s initial state and `fit()`; if `fit` runs on mount against the stubbed `ResizeObserver` size, set the test's expectations from the actual initial view (the mapping through `toPaperPoint` is what is being tested, not a specific scale).

- [ ] **Step 2: Run, expect failures**

Run: `npm test -- --run src/components/BlueprintCanvas.test.jsx`

- [ ] **Step 3: Implement**

`BlueprintCanvas.jsx`:

- Props: add `match = null`, `onDrawBox = () => {}`.
- Drag state: `const [boxDrag, setBoxDrag] = useState(null)` — `{x0, y0, x1, y1}` in paper units.
- `onPointerDown`: `if (tool === "match") { const p = toPaperPoint(e.clientX, e.clientY); setBoxDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y }); e.currentTarget.setPointerCapture(e.pointerId); return; }` before the calibrate early-return.
- `onPointerMove`: `if (boxDrag) { const p = toPaperPoint(...); setBoxDrag((b) => ({ ...b, x1: p.x, y1: p.y })); return; }`.
- `onPointerUp`: if `boxDrag`, compute the box:

```js
      const x0 = Math.min(boxDrag.x0, boxDrag.x1), x1 = Math.max(boxDrag.x0, boxDrag.x1);
      const y0 = Math.min(boxDrag.y0, boxDrag.y1), y1 = Math.max(boxDrag.y0, boxDrag.y1);
      setBoxDrag(null);
      if (x1 - x0 >= 4 && y1 - y0 >= 4) {
        const c = fromPaper({ x: (x0 + x1) / 2, y: (y0 + y1) / 2 }, sheet);
        const e2 = fromPaper({ x: x1 - x0, y: y1 - y0 }, sheet);
        onDrawBox({ x: Math.round(c.x), y: Math.round(c.y), w: Math.round(e2.x), h: Math.round(e2.y) });
      }
```

- Escape: in the existing key handling (or a `useEffect` on `keydown`), `Escape` clears `boxDrag`.
- Rendering, inside the sheet `<g>` after the placement rings block: replace the rings block so each placement with 4 entries draws `<rect className="placement-box" x={cx - w/2} y={cy - h/2} width={w} height={h} fill="none" stroke={meta.color} strokeWidth="1.6" opacity="0.75" />` where `[cx, cy] = pointToPaper(p, sheet)`, `w = p[2]`, `h = p[3] * ky` (compute `ky` as `paperSize(sheet).h / 750`, matching `sheetGeometry`), and 2-entry ones keep `<circle className="placement-ring" …>`. Show them for the selected item even when it has a single placement with a box.
- Result boxes, in a `<g pointerEvents="none" aria-hidden="true">` drawn after markers, ignoring `layers`: for each `match?.matches` entry `<rect className="matchbox" … stroke="var(--blue)" fill="none" strokeWidth="1.6" />`; the drawn `match.box` itself as the same rect with `strokeDasharray="4 3"` while `match.status === "pending"`, solid when found. The in-progress `boxDrag` renders as a dashed blue rect.
- Banner: when `tool === "match"`, the same overlay shape as calibration with `<strong>Find like this</strong>` and `DRAW_PROMPT`, or `SEARCHING` while `match?.status === "pending"`. Import from `../lib/matchCopy.js`.
- Cursor: `viewport--boxing` class when `tool === "match"` (add `.viewport--boxing { cursor: crosshair; }` to `styles.css` next to `.viewport--measuring`).

`CanvasPane.jsx`: a third tool button `<button className="iconbtn" aria-pressed={tool === "match"} onClick={() => onToolChange(tool === "match" ? "pan" : "match")} title="Find like this"><ScanSearch size={15} /></button>` (`ScanSearch` from lucide-react; if unavailable in the installed version use `Scan`). Pass `match` and `onDrawBox` through to `BlueprintCanvas`.

`Workspace.jsx`: take `match, startMatch` from the store hook; `onDrawBox={(box) => { startMatch(sheet.id, box); setTool("pan"); }}`; pass `match={match?.sheetId === sheet.id ? match : null}`.

- [ ] **Step 4: Run**

Run: `npm test -- --run src/components/BlueprintCanvas.test.jsx src/components/Workspace.test.jsx && npm run build`

- [ ] **Step 5: Commit**

```bash
git add src/components/BlueprintCanvas.jsx src/components/CanvasPane.jsx src/components/Workspace.jsx src/styles.css src/components/BlueprintCanvas.test.jsx
git commit -m "Canvas: boxed placements, the Find-like-this tool, result boxes"
```

---

### Task 12: The result card in the item panel

**Files:**
- Create: `src/components/MatchResultCard.jsx`
- Modify: `src/components/ItemDetailPanel.jsx:20-24` (render the card when `match` is set and nothing is selected), `src/components/Workspace.jsx` (props)
- Test: `src/components/MatchResultCard.test.jsx`

**Interfaces:**
- Consumes: store `match`, `acceptMatch`, `discardMatch`, `startMatch`; `SYMBOL_LABELS`, `SYSTEMS`; `matchCopy`.
- Produces: `<MatchResultCard match onAccept(fields) onDiscard onRetry sheetNumber />`.

- [ ] **Step 1: Failing tests**

`src/components/MatchResultCard.test.jsx`:

```js
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import MatchResultCard from "./MatchResultCard.jsx";

const found = (n) => ({ id: "m1", status: "found", box: [100, 100, 20, 10], count: n, matches: Array.from({ length: n }, (_, i) => [100 + i * 50, 100, 20, 10]), error: "" });

describe("MatchResultCard", () => {
  it("shows the count and adds with a name", () => {
    const onAccept = vi.fn();
    render(<MatchResultCard match={found(3)} onAccept={onAccept} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(screen.getByText("3 matches found")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Duplex receptacle" } });
    fireEvent.click(screen.getByRole("button", { name: "Add 3 to the takeoff" }));
    expect(onAccept).toHaveBeenCalledWith({ name: "Duplex receptacle", symbol: expect.any(String), system: expect.any(String) });
  });

  it("not sure yet files it without a name", () => {
    const onAccept = vi.fn();
    render(<MatchResultCard match={found(3)} onAccept={onAccept} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    fireEvent.click(screen.getByRole("button", { name: "Not sure yet" }));
    expect(onAccept).toHaveBeenCalledWith({ notSure: true });
  });

  it("the add button is disabled without a name", () => {
    render(<MatchResultCard match={found(3)} onAccept={() => {}} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(screen.getByRole("button", { name: "Add 3 to the takeoff" }).disabled).toBe(true);
  });

  it("offers the boxed one alone when nothing else matched", () => {
    render(<MatchResultCard match={found(1)} onAccept={() => {}} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(screen.getByText("No other symbols like this were found")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add 1 to the takeoff" })).toBeTruthy();
  });

  it("shows the failure copy and a retry", () => {
    const onRetry = vi.fn();
    render(<MatchResultCard match={{ ...found(0), status: "failed", error: "The symbol couldn't be searched for on this sheet." }} onAccept={() => {}} onDiscard={() => {}} onRetry={onRetry} sheetNumber="E2.1" />);
    expect(screen.getByText(/couldn't be searched/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("never shows a percentage or an AI word", () => {
    const { container } = render(<MatchResultCard match={found(3)} onAccept={() => {}} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(container.textContent).not.toMatch(/%|\bAI\b|confidence/i);
  });
});
```

- [ ] **Step 2: Run, expect failure**

Run: `npm test -- --run src/components/MatchResultCard.test.jsx`

- [ ] **Step 3: Implement `src/components/MatchResultCard.jsx`**

```jsx
import { useState } from "react";
import { SYMBOL_LABELS } from "./Symbols.jsx";
import { SYSTEMS } from "../lib/vocabulary.js";
import * as copy from "../lib/matchCopy.js";

/** What a drawn box found (B3b spec §8). Not an item yet -- nothing is
 *  counted until the estimator names it or says they are not sure --
 *  so this card carries no review label and no status colour. */
export default function MatchResultCard({ match, onAccept, onDiscard, onRetry, sheetNumber }) {
  const [name, setName] = useState("");
  const [symbol, setSymbol] = useState("receptacle");
  const [system, setSystem] = useState(SYSTEMS[0]);
  const n = match.count;

  if (match.status === "pending") {
    return (
      <section className="matchcard" aria-label="Symbol search">
        <p className="label">Find like this · {sheetNumber}</p>
        <p className="value value--muted">{copy.SEARCHING}</p>
        <button className="btn btn--block" onClick={onDiscard}>Cancel</button>
      </section>
    );
  }
  if (match.status === "failed") {
    return (
      <section className="matchcard" aria-label="Symbol search">
        <p className="label">Find like this · {sheetNumber}</p>
        <p className="value">{match.error}</p>
        <button className="btn btn--primary btn--block" onClick={onRetry}>Try again</button>
        <button className="btn btn--block" onClick={onDiscard}>Discard</button>
      </section>
    );
  }
  return (
    <section className="matchcard" aria-label="Symbol search">
      <p className="label">Find like this · {sheetNumber}</p>
      <h2 className="tabular">{copy.found(n)}</h2>
      {n <= 1 && <p className="value value--muted">{copy.NONE_FOUND}</p>}
      <label className="label" htmlFor="match-name">Name</label>
      <input id="match-name" className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="What is this symbol" />
      <label className="label" htmlFor="match-symbol">Symbol</label>
      <select id="match-symbol" className="field" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
        {Object.entries(SYMBOL_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
      <label className="label" htmlFor="match-system">System</label>
      <select id="match-system" className="field" value={system} onChange={(e) => setSystem(e.target.value)}>
        {SYSTEMS.map((s) => <option key={s}>{s}</option>)}
      </select>
      <button className="btn btn--primary btn--block" disabled={!name.trim()} onClick={() => onAccept({ name: name.trim(), symbol, system })}>
        {copy.addLabel(n)}
      </button>
      <button className="btn btn--block" onClick={() => onAccept({ notSure: true })}>{copy.NOT_SURE}</button>
      <button className="btn btn--block" onClick={onDiscard}>Discard</button>
    </section>
  );
}
```

`ItemDetailPanel.jsx`: new props `match, onAcceptMatch, onDiscardMatch, onRetryMatch`; at the top of the `!sel` branch, render `<aside className="detail"><div className="detail__scroll"><MatchResultCard … sheetNumber={currentSheet?.number} /></div></aside>` when `match` is set, else the existing progress summary. `Workspace.jsx`: pass `match`, `onAcceptMatch={acceptMatch}`, `onDiscardMatch={discardMatch}`, `onRetryMatch={() => { const b = match.box; discardMatch(); startMatch(sheet.id, { x: b[0], y: b[1], w: b[2], h: b[3] }); }}`; selecting an item while a match is showing keeps the match (it returns when the selection clears). Add `.matchcard` spacing to `styles.css` reusing existing tokens (no new colours).

- [ ] **Step 4: Run everything**

Run: `npm test -- --run && npm run build && cd api && ../.enginevenv/bin/python -m pytest -q -x`
Expected: both suites green.

- [ ] **Step 5: Commit**

```bash
git add src/components/MatchResultCard.jsx src/components/MatchResultCard.test.jsx src/components/ItemDetailPanel.jsx src/components/Workspace.jsx src/styles.css
git commit -m "Item panel: the symbol search result card"
```

---

### Task 13: Docs and the as-built note

**Files:**
- Modify: `docs/specs/accurate-symbol-marking.md` (add `## 12. As built`), `docs/README.md` (row → plan link, status `merged` happens at merge; set `plans/accurate-symbol-marking.md`), `CLAUDE.md` (Architecture tree: `glyphs.py`, `raster_match.py`, `match_job.py`, `app/matches/`, `MatchResultCard.jsx`; "The engine is five agents" paragraph: Counting now clusters exploded geometry), `README.md` ("What's in the drawing" paragraph: markers sit on the symbol; Find like this), `ROADMAP.md` §2.1 Symbol detection bullet: built for exploded vector; `BUILD-STAGES.md` "Counting method" stage 2 cell → built.
- Test: none (docs); `npm run build` still.

- [ ] **Step 1: Write the as-built section**

Record what differs from the spec as written, discovered during Tasks 1–12 (constants that moved, thresholds measured, anything parked in the ledger), as `## 12. As built` at the end of the spec, in the same voice as B3's §11.

- [ ] **Step 2: Update the five docs above**

Keep each edit to the sentence that changed; do not restructure.

- [ ] **Step 3: Commit**

```bash
git add docs CLAUDE.md README.md ROADMAP.md BUILD-STAGES.md
git commit -m "Docs: accurate symbol marking as built"
```

---

## Self-review

**Spec coverage.** §2 placements → Task 1; `symbol_matches`/`match` kind → Task 5; §3 glyphs → Task 2; §4 counting/linking/fixtures → Task 3; §5 classification with crops → Task 4; §6 match job, vector + raster → Tasks 6–7; §7 routes, 409/422, tenancy, one item/one action → Tasks 8–9; §8 client: boxed rings, tool, result boxes, result card, store polling → Tasks 10–12; §9 copy → Tasks 5 and 10; §10 tests are spread through each task's Step 1; §11 not built — nothing here builds a firm library, a detector, set-wide match, or box editing. Merge protection for `match:` → Task 8.

**Placeholder scan.** Every code step carries its code. Two places say "read the file's existing helpers first" (Task 9's tenancy table, Task 10's api store test) because those helper names live in files the plan does not reproduce; the assertions are given in full.

**Type consistency.** `Placement(x, y, w, h)` (Task 1) is what Task 3 builds and Task 7 reads via `DetectedSheet`; `denormalize_box` (Task 1) is what Task 7 calls; `glyph_in / glyphs_on / matches_of` (Task 2) are the names Task 7 uses; `SymbolMatch.box/matches/status/resolved_at` (Task 5) are what Tasks 7 and 9 read and write; `review.add_item` keyword signature (Task 8) matches Task 9's call; the store's `createMatch/getMatch/acceptMatch/discardMatch` and the hook's `match/startMatch/acceptMatch/discardMatch/clearMatch` (Task 10) are what Tasks 11 and 12 consume; `SymbolMatchOut` fields match `mapMatch`.
