# Blueprint Backdrop Removal and Real Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the whole-sheet raster backdrop from the review canvas, replace it with real per-item evidence crops generated during processing, and fix the title-block sheet-number bug — per `docs/superpowers/specs/2026-08-30-blueprint-evidence-design.md`.

**Architecture:** The engine crops a small PNG around each item's counted location(s) while the source PDF is still open (the only window it's ever available), base64-encodes it into the wire payload, and the API decodes it into a new `item_evidence_images` table — kept separate from `Item` so the undo/snapshot machinery (which walks every `Item` column automatically) never has to know binary data exists. A new endpoint serves it; the canvas drops the raster background entirely and falls back to the honest blank surface that already exists in `PlanDrawing.jsx`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, pymupdf, React 18, Vitest.

## Global Constraints

- Every quantity needs traceable evidence (CLAUDE.md) — this plan is what makes `Item.evidence` non-null for the first time; do not ship a task that leaves it unpopulated.
- No AI framing, model names, or confidence numbers anywhere in product-facing copy or code comments the estimator's screen reflects.
- `npm run build` must pass before any frontend commit; run the backend suite from `api/` with `TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest -q` before any backend commit.
- A missing or failed evidence crop must never fail the takeoff — same principle the vision pass already follows in `estimate_service.py`.
- Migration revision ids match the `versions/` filename sequence number (see `0012_notes.py`'s own docstring) — this plan's migration is `0013`.
- `Item.evidence` and the new `item_evidence_images` table are populated by the engine/ingest path only; nothing here changes the four-label review vocabulary, the warning schema, or approval rules.

---

### Task 1: Fix the sheet-number bug — read the title block, not the whole page

**Files:**
- Modify: `api/app/engine/documents.py:48-52` (`_sheet_number`), and its two call sites at lines 77 and 89 inside `detect_sheets`.
- Test: `api/tests/test_engine_documents.py` (new file)

**Interfaces:**
- Produces: `_sheet_number(page: pymupdf.Page, text: str) -> str` (signature change — was `_sheet_number(text: str) -> str`). No other module calls this function today (confirmed by search), so this is a same-file-only signature change.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_engine_documents.py`:

```python
"""Documents agent -- sheet-number detection must read the title block,
not whichever E-number happens to repeat most in the page's body text. A
callout bubble referencing another sheet can otherwise outvote the title
block's own number (found against a real drawing set: a page whose title
block read E1.2 was labelled E5.1 because a referenced-sheet callout on
the page said E5.1 four times).
"""
import pymupdf

from app.engine import documents


def _page_with_callouts(tmp_path, own_number: str, referenced_number: str, referenced_repeats: int):
    """A 1000x800 landscape sheet whose title block (right-hand strip,
    matching documents.RIGHT_STRIP) carries `own_number`, and whose body
    carries `referenced_number` repeated `referenced_repeats` times --
    enough to outvote a title block that only appears once if the bug is
    present."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    tb_x = 1000 * documents.RIGHT_STRIP + 20
    page.insert_text((tb_x, 700), own_number)
    for i in range(referenced_repeats):
        page.insert_text((100 + i * 40, 100 + i * 20), referenced_number)
    path = tmp_path / "sheet.pdf"
    doc.save(path)
    doc.close()
    return str(path)


def test_sheet_number_prefers_the_title_block(tmp_path):
    path = _page_with_callouts(tmp_path, own_number="E1.2", referenced_number="E5.1", referenced_repeats=4)
    doc = pymupdf.open(path)
    page = doc[0]
    text = page.get_text("text")
    assert documents._sheet_number(page, text) == "E1.2"


def test_sheet_number_falls_back_to_whole_page_when_title_block_is_silent(tmp_path):
    """A page whose title-block strip has no machine-readable E-number
    (some scanned or oddly-drafted sets) still gets *a* number rather
    than an empty one, from whatever the page carries."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((100, 100), "E3.1")
    path = tmp_path / "sheet.pdf"
    doc.save(path)
    doc.close()
    doc = pymupdf.open(path)
    page = doc[0]
    assert documents._sheet_number(page, page.get_text("text")) == "E3.1"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_engine_documents.py -v
```

Expected: `test_sheet_number_prefers_the_title_block` FAILS (`_sheet_number()` today takes one argument, `text`, so calling it with two raises a `TypeError`).

- [ ] **Step 3: Implement the fix**

In `api/app/engine/documents.py`, replace lines 48-52:

```python
def _sheet_number(text: str) -> str:
    ids = SHEET_ID.findall(text)
    if not ids:
        return ""
    # The sheet's own number is the one that repeats most in its own text
    # (title block + references back to itself); good enough for v1, and
    # the estimator can correct it.
    return max(set(ids), key=ids.count)
```

with:

```python
def _sheet_number(page: pymupdf.Page, text: str) -> str:
    """The sheet's own number, read from its title block first.

    The title block is the one place on the page an E-number is
    guaranteed to name *this* sheet rather than a sheet it references —
    a detail callout bubble ("see 2/E5.1") can otherwise repeat a
    different sheet's number more often than the title block states this
    one's, and the most-frequent heuristic below would pick the wrong
    sheet. RIGHT_STRIP is the same boundary `detect_sheets` already uses
    to exclude the title block from device counting, reused here rather
    than duplicated so the two never drift apart.
    """
    w, h = page.rect.width, page.rect.height
    tb_text = page.get_text("text", clip=pymupdf.Rect(w * RIGHT_STRIP, 0, w, h))
    ids = SHEET_ID.findall(tb_text)
    if not ids:
        # Some sets have no machine-readable text in a consistent
        # title-block box -- fall back to the whole page rather than
        # returning nothing.
        ids = SHEET_ID.findall(text)
    if not ids:
        return ""
    return max(set(ids), key=ids.count)
```

Then update both call sites inside `detect_sheets` (currently `_sheet_number(text)` at lines 77 and 89) to `_sheet_number(page, text)`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_engine_documents.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/documents.py api/tests/test_engine_documents.py
git commit -m "Fix: read a sheet's number from its title block, not the whole page"
```

---

### Task 2: Add `render_evidence_crop` to the Documents module

**Files:**
- Modify: `api/app/engine/documents.py` (add constants + function; delete two now-fully-superseded functions in a later task, not this one)
- Test: `api/tests/test_engine_documents.py` (append to Task 1's file)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `render_evidence_crop(path: str, page_index: int, page_width_pt: float, page_height_pt: float, placements: list[tuple[float, float]]) -> bytes | None`. Task 3 calls this per row.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_engine_documents.py`:

```python
def _one_page_pdf(tmp_path, width=1000, height=800):
    doc = pymupdf.open()
    doc.new_page(width=width, height=height)
    path = tmp_path / "page.pdf"
    doc.save(path)
    doc.close()
    return str(path)


def test_evidence_crop_returns_a_valid_png_for_a_point_item(tmp_path):
    path = _one_page_pdf(tmp_path)
    png = documents.render_evidence_crop(path, 0, 1000, 800, [(500, 400)])
    assert png is not None
    doc = pymupdf.open(stream=png, filetype="png")
    assert doc[0].rect.width > 0 and doc[0].rect.height > 0


def test_evidence_crop_covers_every_placement_in_a_cluster(tmp_path):
    """A crop for a scattered cluster must not silently drop the ones
    farthest from the centroid -- render at a bounding box that contains
    every placement, even if that means a lower zoom."""
    path = _one_page_pdf(tmp_path)
    placements = [(50, 50), (900, 700)]
    png = documents.render_evidence_crop(path, 0, 1000, 800, placements)
    assert png is not None


def test_evidence_crop_clamps_to_the_page_at_a_corner(tmp_path):
    """A point right at the page edge must not ask pymupdf for a clip
    rect that extends past the page (a Rect with a negative or
    out-of-bounds coordinate is legal in pymupdf but must not be handed
    a nonsensical crop for a corner device)."""
    path = _one_page_pdf(tmp_path)
    png = documents.render_evidence_crop(path, 0, 1000, 800, [(2, 2)])
    assert png is not None


def test_evidence_crop_returns_none_for_a_bad_page_index(tmp_path):
    path = _one_page_pdf(tmp_path)
    assert documents.render_evidence_crop(path, 7, 1000, 800, [(500, 400)]) is None


def test_evidence_crop_returns_none_with_no_placements(tmp_path):
    path = _one_page_pdf(tmp_path)
    assert documents.render_evidence_crop(path, 0, 1000, 800, []) is None


def test_evidence_crop_returns_none_with_unmeasured_page_dims(tmp_path):
    """A sheet the Documents agent couldn't measure (width/height 0) must
    not crash the takeoff by dividing by zero when computing zoom."""
    path = _one_page_pdf(tmp_path)
    assert documents.render_evidence_crop(path, 0, 0, 0, [(500, 400)]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_engine_documents.py -k evidence_crop -v
```

Expected: FAIL with `AttributeError: module 'app.engine.documents' has no attribute 'render_evidence_crop'`.

- [ ] **Step 3: Implement**

Add near the top of `api/app/engine/documents.py`, alongside `RIGHT_STRIP`/`BORDER`:

```python
# A crop around one item's counted location(s), for the item panel's
# evidence view. A point item gets a fixed radius around its single
# coordinate; a multi-placement cluster gets the bounding box of every
# placement plus a margin, so the crop shows the group Counting actually
# found rather than one instance of it -- see render_evidence_crop.
EVIDENCE_POINT_RADIUS_PT = 90
EVIDENCE_CLUSTER_MARGIN_PT = 40
EVIDENCE_MAX_PX = 640      # longest output edge, in pixels
EVIDENCE_MIN_ZOOM = 0.5
EVIDENCE_MAX_ZOOM = 4.0
```

Add the function after `render_vision_png_bytes` (near the other render helpers):

```python
def render_evidence_crop(
    path: str,
    page_index: int,
    page_width_pt: float,
    page_height_pt: float,
    placements: list[tuple[float, float]],
) -> bytes | None:
    """A tight PNG crop of the source page around one item's counted
    location(s), for the item panel's evidence view.

    Zoom is chosen so the crop's longest edge lands near
    EVIDENCE_MAX_PX regardless of how large the bounding box is -- a
    cluster spread across most of a sheet renders at a lower zoom
    rather than having placements cropped out of frame; nothing here
    ever discards a placement to keep zoom high.

    Returns None on any failure -- a missing crop must never fail the
    takeoff, the same principle the vision pass in estimate_service.py
    already follows.
    """
    if not placements or page_width_pt <= 0 or page_height_pt <= 0:
        return None
    try:
        xs = [p[0] for p in placements]
        ys = [p[1] for p in placements]
        if len(placements) == 1:
            x, y = xs[0], ys[0]
            x0 = x - EVIDENCE_POINT_RADIUS_PT
            y0 = y - EVIDENCE_POINT_RADIUS_PT
            x1 = x + EVIDENCE_POINT_RADIUS_PT
            y1 = y + EVIDENCE_POINT_RADIUS_PT
        else:
            x0 = min(xs) - EVIDENCE_CLUSTER_MARGIN_PT
            y0 = min(ys) - EVIDENCE_CLUSTER_MARGIN_PT
            x1 = max(xs) + EVIDENCE_CLUSTER_MARGIN_PT
            y1 = max(ys) + EVIDENCE_CLUSTER_MARGIN_PT

        x0 = max(0.0, x0)
        y0 = max(0.0, y0)
        x1 = min(float(page_width_pt), x1)
        y1 = min(float(page_height_pt), y1)
        if x1 <= x0 or y1 <= y0:
            return None

        bbox_w, bbox_h = x1 - x0, y1 - y0
        zoom = EVIDENCE_MAX_PX / max(bbox_w, bbox_h)
        zoom = max(EVIDENCE_MIN_ZOOM, min(EVIDENCE_MAX_ZOOM, zoom))

        doc = pymupdf.open(path)
        page = doc[page_index]
        clip = pymupdf.Rect(x0, y0, x1, y1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        return pix.tobytes("png")
    except Exception:  # noqa: BLE001 -- a missing crop must never fail the takeoff
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_engine_documents.py -v
```

Expected: all PASS (Task 1's tests plus these).

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/documents.py api/tests/test_engine_documents.py
git commit -m "Add render_evidence_crop: a real per-item image cut from the source PDF"
```

---

### Task 3: Wire crop generation into the engine's row-building pipeline

**Files:**
- Modify: `api/app/engine/estimate.py` (imports, `_compute`)
- Test: `api/tests/test_estimate_evidence.py` (new file)

**Interfaces:**
- Consumes: `documents.render_evidence_crop` (Task 2).
- Produces: every row dict returned by `full_takeoff()` (and therefore every item in `POST /estimate/project`'s response) carries a new key `"evidence_png_b64": str | None`. Task 6 (`ingest.py`) reads this key.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_estimate_evidence.py`:

```python
"""Every row full_takeoff() produces carries a real evidence crop of the
source page, generated while the PDF is still open -- the only point in
the request lifecycle it's available."""
import base64

import pymupdf

from app.engine import estimate as estimate_mod


def _known_sheet_pdf(tmp_path):
    """Same shape as test_engine_counting.py's known_sheet fixture: a
    1000x800 sheet with 5 isolated 'A' tags and 3 isolated 'R' tags in
    the drawing area."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    for i in range(5):
        page.insert_text((100 + i * 60, 100 + i * 40), "A")
    for i in range(3):
        page.insert_text((200 + i * 50, 400), "R")
    path = tmp_path / "known.pdf"
    doc.save(path)
    doc.close()
    return str(path)


def test_full_takeoff_rows_carry_a_decodable_evidence_crop(tmp_path):
    path = _known_sheet_pdf(tmp_path)
    result = estimate_mod.full_takeoff(path, location="")
    assert result["items"], "expected at least one counted row"
    with_crops = [r for r in result["items"] if r.get("evidence_png_b64")]
    assert with_crops, "expected at least one row to carry a crop"
    png_bytes = base64.b64decode(with_crops[0]["evidence_png_b64"])
    doc = pymupdf.open(stream=png_bytes, filetype="png")
    assert doc[0].rect.width > 0


def test_estimate_summary_rows_do_not_carry_crops(tmp_path):
    """The consolidated Instant-estimate summary (estimate(), not
    full_takeoff()) has no canvas and no per-item panel -- it must not
    pay the cost of generating crops it never shows."""
    path = _known_sheet_pdf(tmp_path)
    result = estimate_mod.estimate(path, location="")
    assert result["items"]
    assert all("evidence_png_b64" not in r for r in result["items"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_estimate_evidence.py -v
```

Expected: `test_full_takeoff_rows_carry_a_decodable_evidence_crop` FAILS (no row has `"evidence_png_b64"`, so `with_crops` is empty and the assert fails). The second test passes already (there's nothing to remove yet) — that's fine, it stays green through this task and only matters once Step 3 is in place to confirm it doesn't regress.

- [ ] **Step 3: Implement**

In `api/app/engine/estimate.py`, add to the imports at the top:

```python
import base64
```

`_compute()` is shared by both `estimate()` and `full_takeoff()` (confirmed: both call `_compute` and neither post-processes rows further before consuming them). Crops must only be attached for the `full_takeoff()` path. Add a `with_evidence: bool` parameter to `_compute`, defaulting to preserve `estimate()`'s existing behavior:

Change the signature at its definition:

```python
def _compute(path: str, location: str, context: str = "", estimator_notes: list[dict] | None = None, with_evidence: bool = False):
```

Immediately before the existing `meta = {` block (right after the `if not used_llm:` block that appends `_row_from_catalog` rows), insert:

```python
    if with_evidence:
        dims_by_page = {s.page_index: (s.width_pt, s.height_pt) for s in sheets}
        for row in rows:
            page_index = row["page"] - 1
            width_pt, height_pt = dims_by_page.get(page_index, (0, 0))
            placements = row["placements"] or [(row["x"], row["y"])]
            png = documents.render_evidence_crop(path, page_index, width_pt, height_pt, placements)
            row["evidence_png_b64"] = base64.b64encode(png).decode("ascii") if png else None
```

Then update `full_takeoff()`'s call to `_compute` (it currently reads `rows, sheets, meta = _compute(path, location, context, estimator_notes)`) to pass `with_evidence=True`:

```python
    rows, sheets, meta = _compute(path, location, context, estimator_notes, with_evidence=True)
```

`estimate()`'s call to `_compute(path, location)` is left unchanged — `with_evidence` defaults to `False`, so its rows never get the key, matching `test_estimate_summary_rows_do_not_carry_crops`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_estimate_evidence.py -v
```

Expected: both PASS. Then run the full existing engine suite to confirm nothing else regressed:

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_engine_classify.py tests/test_engine_counting.py tests/test_estimator_notes_channel.py -v
```

Expected: all PASS (unrelated to this change, confirms no signature-change fallout).

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/estimate.py api/tests/test_estimate_evidence.py
git commit -m "Wire evidence-crop generation into full_takeoff's row pipeline"
```

---

### Task 4: `ItemEvidenceImage` model and migration

**Files:**
- Modify: `api/app/takeoff/models.py` (add `LargeBinary` import, new class)
- Create: `api/migrations/versions/0013_item_evidence_images.py`
- Test: `api/tests/test_takeoff_models.py` (append)

**Interfaces:**
- Produces: `ItemEvidenceImage` (SQLAlchemy model, table `item_evidence_images`, columns `item_id` (PK, FK to `items.id`, `ON DELETE CASCADE`), `png` (bytes), `created_at`). Tasks 5, 7, 8, 9 use this class directly.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_takeoff_models.py` (check its existing imports at the top first and add to them rather than duplicating):

```python
def test_item_evidence_image_cascades_on_item_delete(db, item):
    """The image is a cache of what the drawing showed at that item's
    location, not reviewable state -- deleting the item deletes the
    image with it, same as Warning already does. `item` is the shared
    conftest.py fixture (a real, already-flushed Item row)."""
    from app.takeoff.models import ItemEvidenceImage

    db.add(ItemEvidenceImage(item_id=item.id, png=b"fake-png-bytes"))
    db.commit()

    db.delete(item)
    db.commit()

    assert db.get(ItemEvidenceImage, item.id) is None


def test_item_evidence_image_is_not_in_the_undo_snapshot_types():
    """The undo/snapshot machinery (snapshots._column_snapshot) walks
    every mapped column of Item automatically -- this table must stay
    outside that entirely, or a delete's full-row snapshot would need to
    JSON-encode raw PNG bytes. Nothing about an evidence image is ever
    undone, so it has no business in ITEM_SNAPSHOT_TYPES."""
    from app.takeoff.snapshots import ITEM_SNAPSHOT_TYPES

    assert "evidence_image" not in ITEM_SNAPSHOT_TYPES
    assert "png" not in ITEM_SNAPSHOT_TYPES
```

`item` (and the `sheet`/`project`/`db` it depends on) are the existing fixtures already defined in `api/tests/conftest.py:121-136` — no new fixtures needed for this task.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_takeoff_models.py -k evidence_image -v
```

Expected: FAIL with `ImportError: cannot import name 'ItemEvidenceImage'`.

- [ ] **Step 3: Implement the model**

In `api/app/takeoff/models.py`, add `LargeBinary` to the existing `sqlalchemy` import:

```python
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Identity, Index,
    Integer, LargeBinary, Numeric, String, Text, func, text,
)
```

Insert the new class between the end of `Item` (`updated_at: Mapped[datetime] = mapped_column(...)`) and `class Warning(Base):`:

```python
class ItemEvidenceImage(Base):
    """A crop of the source drawing around one item's counted
    location(s) -- what "View evidence" actually shows. Deliberately its
    own table, not a column on Item: `snapshots._column_snapshot()`
    walks every mapped column of Item automatically for the delete-undo
    snapshot, and this codebase has already hit "a new Item column
    breaks decode_snapshot()" twice. Nothing about this row is ever
    reviewed or undone -- it is a cache of what the drawing showed, not
    estimator state -- so it stays outside the action-log/undo system
    entirely rather than being taught to it.

    One row per item at most: `item_id` is both the primary key and the
    foreign key, so a re-run's upsert (see evidence_images.py) never has
    to reason about more than one existing row per item. `ON DELETE
    CASCADE` means deleting an item (or undoing back through a delete,
    which recreates the Item row) does not restore a lost image -- it
    starts with none, the same honest state as an item that never had
    one.
    """

    __tablename__ = "item_evidence_images"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    png: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Write the migration**

Create `api/migrations/versions/0013_item_evidence_images.py`:

```python
"""item_evidence_images

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-30 00:00:00.000000

Convention: revision ids match the versions/ filename sequence number
rather than the autogenerated hash, so the chain and the directory
listing always agree.

A crop of the source drawing per item, kept in its own table rather than
a new items column so the undo/snapshot machinery (which walks every
mapped Item column automatically) never has to reason about binary data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0013'
down_revision: Union[str, None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'item_evidence_images',
        sa.Column('item_id', UUID(as_uuid=True), sa.ForeignKey('items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('png', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('item_evidence_images')
```

- [ ] **Step 5: Run the migration and verify up/down/up**

```bash
cd api
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" alembic upgrade head
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" alembic downgrade -1
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" alembic upgrade head
DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" alembic upgrade head
```

Expected: no errors; `\d item_evidence_images` in `psql` shows the three columns and the FK.

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_takeoff_models.py -v
```

Expected: all PASS, including the two new tests.

- [ ] **Step 7: Commit**

```bash
git add api/app/takeoff/models.py api/migrations/versions/0013_item_evidence_images.py api/tests/test_takeoff_models.py
git commit -m "Add item_evidence_images table, kept outside the undo/snapshot system"
```

---

### Task 5: Shared upsert helper

**Files:**
- Create: `api/app/takeoff/evidence_images.py`
- Test: `api/tests/test_evidence_images.py` (new file)

**Interfaces:**
- Consumes: `ItemEvidenceImage` (Task 4).
- Produces: `upsert_evidence_image(db: Session, item_id: uuid.UUID, png: bytes | None) -> None`. Tasks 7 and 8 call this once per item after that item's row is flushed.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_evidence_images.py`:

```python
"""upsert_evidence_image is the one function both first-time ingest and a
reprocess re-run call to keep an item's evidence image in sync with what
the engine most recently produced for it."""
import uuid

from app.takeoff.evidence_images import upsert_evidence_image
from app.takeoff.models import Item, ItemEvidenceImage, ReviewStatus, Sheet


def _make_item(db, project):
    sheet = Sheet(id=uuid.uuid4(), project_id=project.id, number="E1.1", title="t",
                  discipline="Electrical", revision="", scale="", scale_options=[], plan="",
                  sort_order=0)
    db.add(sheet)
    db.flush()
    item = Item(id=uuid.uuid4(), project_id=project.id, sheet_id=sheet.id, symbol="receptacle",
                name="Receptacle", description="", system="Power", category="Devices",
                quantity=1, unit="ea", status=ReviewStatus.READY)
    db.add(item)
    db.flush()
    return item


def test_upsert_inserts_a_new_image(db, project):
    item = _make_item(db, project)
    upsert_evidence_image(db, item.id, b"first-png")
    db.commit()
    row = db.get(ItemEvidenceImage, item.id)
    assert row is not None and row.png == b"first-png"


def test_upsert_replaces_an_existing_image(db, project):
    item = _make_item(db, project)
    upsert_evidence_image(db, item.id, b"first-png")
    db.commit()
    upsert_evidence_image(db, item.id, b"second-png")
    db.commit()
    row = db.get(ItemEvidenceImage, item.id)
    assert row.png == b"second-png"


def test_upsert_clears_a_stale_image_when_png_is_none(db, project):
    """A re-run whose crop generation failed this time must not leave a
    previous run's image silently misrepresenting the current takeoff."""
    item = _make_item(db, project)
    upsert_evidence_image(db, item.id, b"first-png")
    db.commit()
    upsert_evidence_image(db, item.id, None)
    db.commit()
    assert db.get(ItemEvidenceImage, item.id) is None


def test_upsert_with_none_and_no_existing_row_is_a_no_op(db, project):
    item = _make_item(db, project)
    upsert_evidence_image(db, item.id, None)
    db.commit()
    assert db.get(ItemEvidenceImage, item.id) is None
```

If `db` / `project` fixtures in `api/tests/conftest.py` differ from this shape (e.g. `project` needs an explicit org/user setup other tests perform), match whatever `api/tests/test_ingest_endpoint.py` or `api/tests/test_reprocess.py` already use for those two fixture names rather than inventing new setup.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_evidence_images.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.takeoff.evidence_images'`.

- [ ] **Step 3: Implement**

Create `api/app/takeoff/evidence_images.py`:

```python
"""upsert_evidence_image -- the one function both first-time ingest
(ingest_service.py) and a reprocess re-run (reprocess.py) call to keep an
item's evidence image in sync with what the engine most recently produced
for it. Split out rather than living in either caller: both need the
exact same replace-or-clear behavior, and ingest.py's mapping stays a
pure function (its own docstring's stated contract) by not touching the
database itself.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import ItemEvidenceImage


def upsert_evidence_image(db: DbSession, item_id: uuid.UUID, png: bytes | None) -> None:
    """Replace item_id's evidence image, or clear it if `png` is None.

    Always deletes whatever existed first: a re-run whose crop failed
    this time must not leave a previous run's image standing in for a
    takeoff it no longer matches.
    """
    db.query(ItemEvidenceImage).filter_by(item_id=item_id).delete()
    if png is not None:
        db.add(ItemEvidenceImage(item_id=item_id, png=png))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_evidence_images.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/evidence_images.py api/tests/test_evidence_images.py
git commit -m "Add upsert_evidence_image, shared by ingest and reprocess"
```

---

### Task 6: `ingest.py` — populate `evidence` and decode the crop

**Files:**
- Modify: `api/app/takeoff/ingest.py` (`map_payload`)
- Test: `api/tests/test_ingest_mapping.py` (append)

**Interfaces:**
- Consumes: the `"evidence_png_b64"` key on each item dict (Task 3's wire shape).
- Produces: each dict in `MappedTakeoff.items` gains two keys: `"evidence": {"detail": str, "sheet": str, "has_image": bool}` and `"evidence_png": bytes | None`. Tasks 7 and 8 read both; `"evidence_png"` is popped off before constructing the `Item` row (it is not an `Item` column).

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_ingest_mapping.py` (reuse the existing `_payload()` helper already in that file):

```python
import base64


def test_map_payload_populates_evidence_metadata():
    payload = _payload()
    payload["items"][0]["evidence_png_b64"] = base64.b64encode(b"fake-png").decode("ascii")
    mapped = map_payload(payload)
    item = mapped.items[0]
    assert item["evidence"]["sheet"] == "E2.1"
    assert item["evidence"]["has_image"] is True
    assert "2 locations" in item["evidence"]["detail"]
    assert item["evidence_png"] == b"fake-png"


def test_map_payload_evidence_has_image_false_without_a_crop():
    payload = _payload()
    mapped = map_payload(payload)
    item = mapped.items[0]
    assert item["evidence"]["has_image"] is False
    assert item["evidence_png"] is None


def test_map_payload_evidence_detail_is_singular_for_one_location():
    payload = _payload()
    payload["items"][0]["placements"] = [[1000, 750]]
    mapped = map_payload(payload)
    assert "1 location" in mapped.items[0]["evidence"]["detail"]
    assert "1 locations" not in mapped.items[0]["evidence"]["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_ingest_mapping.py -k evidence -v
```

Expected: FAIL — `item["evidence"]` raises `KeyError` today (the key is never set).

- [ ] **Step 3: Implement**

In `api/app/takeoff/ingest.py`, add `import base64` near the top with the other imports. Inside `map_payload`'s `for raw in payload.get("items") or []:` loop, the dict currently ends with:

```python
            "source_tag": str(raw.get("tag") or ""),
            "warning": validate_warning(warning) if warning else None,
        })
```

Change this to build the placements list first (it's already computed inline for the `"placements"` key — assign it to a local so both that key and the evidence detail can use it), then add the two new keys. The full item-append block becomes:

```python
        placements = [
            [normalize_point(p[0], width, SHEET_SPACE_W), normalize_point(p[1], height, SHEET_SPACE_H)]
            for p in (raw.get("placements") or [])
            if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
        n_places = len(placements) or 1
        png_b64 = raw.get("evidence_png_b64")
        sheet_number = next((s["number"] for s in sheets if s["key"] == key), "")
        items.append({
            "sheet_key": key,
            "symbol": str(raw.get("symbol") or "") or infer_symbol(name, system),
            "name": name,
            "description": str(raw.get("description") or ""),
            "system": system,
            "category": str(raw.get("category") or ""),
            "quantity": raw.get("quantity") or 0,
            "unit": str(raw.get("unit") or "ea"),
            "status": str(raw.get("status") or "ready"),
            "x": normalize_point(raw.get("x"), width, SHEET_SPACE_W),
            "y": normalize_point(raw.get("y"), height, SHEET_SPACE_H),
            "placements": placements,
            "material_cost": raw.get("material_cost") or 0,
            "labor_hours": raw.get("labor_hours") or 0,
            "labor_cost": raw.get("labor_cost") or 0,
            "total_cost": raw.get("total_cost") or 0,
            "ai_confirmed": bool(raw.get("ai_confirmed")),
            "source_tag": str(raw.get("tag") or ""),
            "warning": validate_warning(warning) if warning else None,
            "evidence": {
                "detail": f"Counted from the drawing at {n_places} location{'s' if n_places != 1 else ''}",
                "sheet": sheet_number,
                "has_image": bool(png_b64),
            },
            "evidence_png": base64.b64decode(png_b64) if png_b64 else None,
        })
```

This replaces the existing `"placements": [...]` inline computation (now the `placements` local, computed once above) and the final two lines of the append block. Everything else in the dict literal is unchanged from what's already there.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_ingest_mapping.py -v
```

Expected: all PASS, including every pre-existing test in the file (confirms the refactor of the `placements` key didn't change its value).

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/ingest.py api/tests/test_ingest_mapping.py
git commit -m "ingest.py: populate Item.evidence for the first time, decode the crop"
```

---

### Task 7: Wire evidence into first-time ingest

**Files:**
- Modify: `api/app/takeoff/ingest_service.py`
- Test: `api/tests/test_ingest_endpoint.py` (append)

**Interfaces:**
- Consumes: `upsert_evidence_image` (Task 5), `row["evidence"]` / `row["evidence_png"]` (Task 6).

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_ingest_endpoint.py`:

```python
import base64

from app.takeoff.models import ItemEvidenceImage


def test_ingest_stores_evidence_metadata_and_image(client, db, project, signed_in_user):
    payload = {
        "sheets": PAYLOAD["sheets"],
        "items": [{**PAYLOAD["items"][0], "evidence_png_b64": base64.b64encode(b"fake-png").decode("ascii")}],
    }
    response = _ingest(client, project.id, payload=payload)
    assert response.status_code == 200, response.text

    item = db.scalars(select(Item).where(Item.project_id == project.id)).one()
    assert item.evidence["sheet"] == "E2.1"
    assert item.evidence["has_image"] is True

    image = db.get(ItemEvidenceImage, item.id)
    assert image is not None and image.png == b"fake-png"


def test_ingest_without_a_crop_leaves_no_image_row(client, db, project, signed_in_user):
    response = _ingest(client, project.id)  # PAYLOAD has no evidence_png_b64
    assert response.status_code == 200, response.text
    item = db.scalars(select(Item).where(Item.project_id == project.id)).one()
    assert item.evidence["has_image"] is False
    assert db.get(ItemEvidenceImage, item.id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_ingest_endpoint.py -k evidence -v
```

Expected: FAIL — `item.evidence` is `None` today (`item.evidence["sheet"]` raises `TypeError`).

- [ ] **Step 3: Implement**

In `api/app/takeoff/ingest_service.py`, add the import:

```python
from app.takeoff.evidence_images import upsert_evidence_image
```

In the `for row in mapped.items:` loop, the `Item(...)` constructor currently does not set `evidence`. Change it to:

```python
    for row in mapped.items:
        item = Item(
            id=uuid.uuid4(), project_id=project.id, sheet_id=sheet_ids_by_key[row["sheet_key"]],
            symbol=row["symbol"], name=row["name"], description=row["description"],
            system=row["system"], category=row["category"], quantity=row["quantity"],
            unit=row["unit"], status=ReviewStatus(row["status"]),
            x=row["x"], y=row["y"], placements=row["placements"],
            material_cost=row["material_cost"], labor_hours=row["labor_hours"],
            labor_cost=row["labor_cost"], total_cost=row["total_cost"],
            ai_confirmed=row["ai_confirmed"], source_tag=row["source_tag"],
            evidence=row["evidence"],
        )
        db.add(item)
        db.flush()
        upsert_evidence_image(db, item.id, row["evidence_png"])
        if row["warning"]:
            w = row["warning"]
            db.add(Warning(
                id=uuid.uuid4(), item_id=item.id, sheet_id=None,
                reason=WarningReason(w["reason"]), title=w["title"], found=w["found"],
                why=w["why"], fix=w["fix"], where_=w["where"],
            ))
```

The added `db.flush()` immediately after `db.add(item)` is required: `upsert_evidence_image` needs `item.id` to already exist as a row `item_evidence_images.item_id` can foreign-key against in the same transaction (the id itself is already assigned client-side by `uuid.uuid4()`, but the FK target row must exist before the child insert is flushed — flushing the item first guarantees ordering the same way the existing sheet-then-item flush above it already does).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_ingest_endpoint.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/ingest_service.py api/tests/test_ingest_endpoint.py
git commit -m "ingest_service.py: store evidence metadata and image on first ingest"
```

---

### Task 8: Wire evidence into reprocess (both branches)

**Files:**
- Modify: `api/app/takeoff/reprocess.py` (`_overwrite`, and the insert-new branch inside `reprocess_takeoff`)
- Test: `api/tests/test_reprocess.py` (append)

**Interfaces:**
- Consumes: `upsert_evidence_image` (Task 5), `row["evidence"]` / `row["evidence_png"]` (Task 6).

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_reprocess.py`. First extend the file's existing `_item()` helper to optionally carry a crop — change its signature from `def _item(tag, name, status="ready", qty=10, warning=None):` to:

```python
def _item(tag, name, status="ready", qty=10, warning=None, evidence_png_b64=None):
    return {"name": name, "system": "Power", "category": "Devices", "unit": "ea",
            "quantity": qty, "status": status, "sheet_id": "tk1:0", "symbol": "receptacle",
            "warning": warning, "x": 1000, "y": 750, "placements": [[1000, 750]], "tag": tag,
            "material_cost": 10.0, "labor_hours": 1.0, "labor_cost": 78.0, "total_cost": 88.0,
            "evidence_png_b64": evidence_png_b64}
```

Then add:

```python
import base64

from app.takeoff.models import ItemEvidenceImage


def test_reprocess_sets_evidence_image_on_a_newly_inserted_item(client, db, project, signed_in_user):
    png_b64 = base64.b64encode(b"new-item-png").decode("ascii")
    _seed(client, project, [])
    client.post(f"/api/projects/{project.id}/reprocess",
                json={"payload": _payload([_item("R", "20A duplex receptacle", evidence_png_b64=png_b64)])})
    item = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    image = db.get(ItemEvidenceImage, item.id)
    assert image is not None and image.png == b"new-item-png"


def test_reprocess_replaces_evidence_image_on_a_matched_unapproved_item(client, db, project, signed_in_user):
    first_png = base64.b64encode(b"first-run-png").decode("ascii")
    second_png = base64.b64encode(b"second-run-png").decode("ascii")
    _seed(client, project, [_item("R", "20A duplex receptacle", evidence_png_b64=first_png)])
    item_before = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    item_id = item_before.id

    client.post(f"/api/projects/{project.id}/reprocess",
                json={"payload": _payload([_item("R", "20A duplex receptacle", evidence_png_b64=second_png)])})

    image = db.get(ItemEvidenceImage, item_id)
    assert image is not None and image.png == b"second-run-png"


def test_reprocess_clears_evidence_image_when_a_rerun_crop_fails(client, db, project, signed_in_user):
    """A re-run whose crop generation failed this time must not leave the
    previous run's image standing in for a takeoff it no longer matches."""
    first_png = base64.b64encode(b"first-run-png").decode("ascii")
    _seed(client, project, [_item("R", "20A duplex receptacle", evidence_png_b64=first_png)])
    item_before = db.scalars(select(Item).where(Item.source_tag == "R")).one()
    item_id = item_before.id

    client.post(f"/api/projects/{project.id}/reprocess",
                json={"payload": _payload([_item("R", "20A duplex receptacle")])})  # no evidence_png_b64

    assert db.get(ItemEvidenceImage, item_id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_reprocess.py -k evidence_image -v
```

Expected: FAIL — no `ItemEvidenceImage` row is ever created by `reprocess_takeoff` today.

- [ ] **Step 3: Implement**

In `api/app/takeoff/reprocess.py`, add the import:

```python
from app.takeoff.evidence_images import upsert_evidence_image
```

Add one line inside `_overwrite()` (which already sets every other engine-owned field), right after `item.source_tag = row["source_tag"]` and before the `item.version += 1` comment/line:

```python
    item.source_tag = row["source_tag"]
    item.evidence = row["evidence"]
    # Bumped exactly like every other mutation that changes a row's
```

(The comment shown is the existing one already in the file immediately after `source_tag` — this only inserts the new `item.evidence = row["evidence"]` line above it.)

Then, in `reprocess_takeoff`, the matched-and-updated branch currently reads:

```python
        if current is not None:
            changed = _changes_visibly(current, sheet, row, _warning_title(db, current.id))
            _overwrite(current, sheet, row)
            _replace_warning(db, current.id, row["warning"])
            if changed:
                reclassified += 1
```

Add the upsert call right after `_overwrite`:

```python
        if current is not None:
            changed = _changes_visibly(current, sheet, row, _warning_title(db, current.id))
            _overwrite(current, sheet, row)
            _replace_warning(db, current.id, row["warning"])
            upsert_evidence_image(db, current.id, row["evidence_png"])
            if changed:
                reclassified += 1
```

And the insert-new branch currently reads:

```python
        else:
            item = Item(
                id=uuid.uuid4(), project_id=project.id, sheet_id=sheet.id,
                symbol=row["symbol"], name=row["name"], description=row["description"],
                system=row["system"], category=row["category"], quantity=row["quantity"],
                unit=row["unit"], status=ReviewStatus(row["status"]), x=row["x"], y=row["y"],
                placements=row["placements"], material_cost=row["material_cost"],
                labor_hours=row["labor_hours"], labor_cost=row["labor_cost"],
                total_cost=row["total_cost"], ai_confirmed=row["ai_confirmed"],
                source_tag=row["source_tag"],
            )
            db.add(item)
            if row["warning"]:
                w = row["warning"]
                db.add(Warning(id=uuid.uuid4(), item_id=item.id, sheet_id=None,
                               reason=WarningReason(w["reason"]), title=w["title"], found=w["found"],
                               why=w["why"], fix=w["fix"], where_=w["where"]))
            added += 1
```

Change to:

```python
        else:
            item = Item(
                id=uuid.uuid4(), project_id=project.id, sheet_id=sheet.id,
                symbol=row["symbol"], name=row["name"], description=row["description"],
                system=row["system"], category=row["category"], quantity=row["quantity"],
                unit=row["unit"], status=ReviewStatus(row["status"]), x=row["x"], y=row["y"],
                placements=row["placements"], material_cost=row["material_cost"],
                labor_hours=row["labor_hours"], labor_cost=row["labor_cost"],
                total_cost=row["total_cost"], ai_confirmed=row["ai_confirmed"],
                source_tag=row["source_tag"], evidence=row["evidence"],
            )
            db.add(item)
            db.flush()
            upsert_evidence_image(db, item.id, row["evidence_png"])
            if row["warning"]:
                w = row["warning"]
                db.add(Warning(id=uuid.uuid4(), item_id=item.id, sheet_id=None,
                               reason=WarningReason(w["reason"]), title=w["title"], found=w["found"],
                               why=w["why"], fix=w["fix"], where_=w["where"]))
            added += 1
```

The `db.flush()` before the upsert call is required here for the same FK-ordering reason as Task 7 — `item.id` must exist as a persisted row before `item_evidence_images` can reference it within the same transaction.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_reprocess.py -v
```

Expected: all PASS, including every pre-existing test in the file — pay particular attention to `test_reprocess_leaves_an_approved_item_untouched`, which must still pass unchanged (approved items are never passed to `_overwrite` or the insert branch, so they never reach `upsert_evidence_image` either — confirm this by reading its assertions, not just running it green).

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/reprocess.py api/tests/test_reprocess.py
git commit -m "reprocess.py: keep evidence image in sync across a re-run's two branches"
```

---

### Task 9: Serve the evidence image

**Files:**
- Modify: `api/app/takeoff/mutations.py`
- Test: `api/tests/test_mutation_endpoints.py` (append) — check this file's existing imports/fixtures before appending, matching its established style for a `/items/{item_id}/...` route test.

**Interfaces:**
- Consumes: `ItemEvidenceImage` (Task 4), `load_item`/`not_found` (already imported in `mutations.py`).
- Produces: `GET /api/items/{item_id}/evidence-image` — 200 with `image/png` bytes, or 404.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_mutation_endpoints.py`:

```python
from app.takeoff.models import Item, ItemEvidenceImage, ReviewStatus, Sheet


def test_evidence_image_endpoint_returns_the_stored_png(client, db, item, signed_in_user):
    db.add(ItemEvidenceImage(item_id=item.id, png=b"stored-png-bytes"))
    db.commit()

    response = client.get(f"/api/items/{item.id}/evidence-image")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"stored-png-bytes"


def test_evidence_image_endpoint_404s_without_an_image(client, item, signed_in_user):
    response = client.get(f"/api/items/{item.id}/evidence-image")
    assert response.status_code == 404


def test_evidence_image_endpoint_404s_for_another_orgs_item(client, db, signed_in_user, other_org_project):
    other_sheet = Sheet(project_id=other_org_project.id, number="E1.1", title="t",
                         discipline="Electrical", revision="", scale="", scale_options=[], plan="")
    db.add(other_sheet)
    db.flush()
    other_item = Item(project_id=other_org_project.id, sheet_id=other_sheet.id, symbol="receptacle",
                       name="Receptacle", system="Power", category="Devices", quantity=1,
                       unit="EA", status=ReviewStatus.READY)
    db.add(other_item)
    db.flush()
    db.add(ItemEvidenceImage(item_id=other_item.id, png=b"not-yours"))
    db.commit()

    response = client.get(f"/api/items/{other_item.id}/evidence-image")
    assert response.status_code == 404
```

`item` (and `sheet`/`project`) are the existing fixtures from `api/tests/conftest.py:121-136`; `other_org_project` is the existing fixture at `conftest.py:203` (a project in a different org from `signed_in_user`, with no sheet or item of its own — the third test builds those manually for that project, the same way `test_ingest_endpoint.py` and `test_evidence_images.py` (Task 5) already construct rows directly rather than through a fixture).

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_mutation_endpoints.py -k evidence_image -v
```

Expected: FAIL with 404 Not Found on all three (route doesn't exist yet) — the third test happens to pass by coincidence (a 404 is what it expects too), so check its failure is a routing 404 from FastAPI's default handler, not this task's `not_found()`, by temporarily running only the first test to confirm it currently fails.

- [ ] **Step 3: Implement**

In `api/app/takeoff/mutations.py`, add `Response` to the existing `from fastapi import APIRouter, Depends, Header` line:

```python
from fastapi import APIRouter, Depends, Header, Response
```

Add `ItemEvidenceImage` to the existing `from app.takeoff.models import Note, Project` line:

```python
from app.takeoff.models import ItemEvidenceImage, Note, Project
```

Add the route near the other `/items/{item_id}/...` routes (next to `approve`/`reject`/`unreject`):

```python
@router.get("/items/{item_id}/evidence-image")
def get_item_evidence_image(
    item_id: uuid.UUID,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> Response:
    item = load_item(item_id, db, user)
    row = db.get(ItemEvidenceImage, item.id)
    if row is None:
        raise not_found()
    return Response(
        content=row.png, media_type="image/png",
        headers={"Cache-Control": "max-age=86400, immutable"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest tests/test_mutation_endpoints.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the full backend suite**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest -q
```

Expected: all PASS. This is the last backend-only task — a good checkpoint before moving to the frontend.

- [ ] **Step 6: Commit**

```bash
git add api/app/takeoff/mutations.py api/tests/test_mutation_endpoints.py
git commit -m "Serve an item's evidence image at GET /items/{id}/evidence-image"
```

---

### Task 10: Remove the raster backdrop from the canvas

**Files:**
- Modify: `src/components/Workspace.jsx:256-270` (remove `sheetImageUrl` prop construction)
- Modify: `src/components/CanvasPane.jsx` (remove `sheetImageUrl` prop threading)
- Modify: `src/components/BlueprintCanvas.jsx` (remove `sheetImageUrl` prop and the `<image>` element)
- Modify: `src/components/PlanDrawing.jsx` (delete `WarehousePlan`, `OfficePlan`, and their now-unused private helpers)
- Test: `src/components/Workspace.test.jsx` (append)

**Interfaces:**
- No other task depends on `sheetImageUrl` or the deleted `PlanDrawing` functions — this task only removes.

- [ ] **Step 1: Write the failing test**

Check `src/components/Workspace.test.jsx`'s existing setup (how it renders `Workspace` and what store/props it provides) before writing this, then append a test in the same style:

```jsx
test("the canvas never requests a sheet image from the engine", () => {
  // Render the workspace with at least one sheet selected, the same way
  // this file's other tests already do.
  render(<Workspace {...existingTestSetupProps} />);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  // No <image> SVG element (BlueprintCanvas renders markers as SVG, not
  // <img>, so this also guards against a stray raster element inside
  // the SVG tree specifically).
  expect(document.querySelector("image")).toBeNull();
});
```

Adapt `existingTestSetupProps` to however this file already renders `Workspace` in its other tests (store mock, project id, etc.) — do not invent new setup scaffolding when the file already has one.

- [ ] **Step 2: Run test to verify it fails**

```bash
npm test -- Workspace.test.jsx
```

Expected: this specific test currently passes or fails depending on whether the test environment's fetch to `localhost:8100` resolves to anything — either way, note the *current* behavior before the fix so Step 4 can show a real before/after. If the test environment has no network access at all, the `<image>` element still renders in the DOM immediately (React doesn't wait for the image to load before mounting the element) with a broken `src` — so `document.querySelector("image")` finding a node is the actual pre-fix signal to check for, regardless of network mocking.

- [ ] **Step 3: Implement**

In `src/components/Workspace.jsx`, replace the `<CanvasPane>` block (currently lines 256-270ish):

```jsx
        <CanvasPane
          sheet={sheet}
          items={items}
          sheetImageUrl={
            // takeoffId alone decides this: pageIndex is a zero-based page
            // number, so testing it for truthiness hid the first page of
            // every processed set behind the blank fallback.
            sheet?.takeoffId
              ? `http://localhost:8100/sheet-image?takeoff_id=${encodeURIComponent(sheet.takeoffId)}&page=${sheet.pageIndex ?? 0}`
              : null
          }
          selId={selectedItemId}
```

with:

```jsx
        <CanvasPane
          sheet={sheet}
          items={items}
          selId={selectedItemId}
```

In `src/components/CanvasPane.jsx`, remove `sheetImageUrl` from the destructured props (line 23) and from the `<BlueprintCanvas>` call (line 72):

```jsx
export default function CanvasPane({
  sheet, items, selId, onSelect, layers, onLayersChange, tool, onToolChange,
  canvasQuery, onCanvasQuery, showFind, onToggleFind, menu, onToggleMenu,
  remoteSelections, onCalibrate,
}) {
```

and remove the `sheetImageUrl={sheetImageUrl}` line from the `<BlueprintCanvas>` element.

In `src/components/BlueprintCanvas.jsx`, remove `sheetImageUrl,` from the destructured props (line 29), and remove the whole conditional block:

```jsx
            {sheetImageUrl ? (
              <image href={sheetImageUrl} x={0} y={0} width={SHEET_W} height={SHEET_H} preserveAspectRatio="none" />
            ) : null}
```

Update the comment immediately above `<PlanDrawing sheet={sheet} />` in the same file (it currently explains why the image sits over `PlanDrawing`, which is no longer true):

```jsx
            {/* The base layer under every marker. Markers were normalized
                to this same 1000x750 sheet space at ingest, so they land
                correctly on it regardless of what PlanDrawing renders. For
                every sheet from an uploaded document, PlanDrawing renders
                nothing but the sheet number on blank paper -- there is no
                drawn geometry that could honestly stand in for a page
                nobody in this codebase has seen. */}
            <PlanDrawing sheet={sheet} />
```

In `src/components/PlanDrawing.jsx`, delete the functions `WarehousePlan`, `OfficePlan`, and their private helpers `GridBubble`, `DimString`, `RoomTag`, `DoorSwing`, `NorthArrow`, `GraphicScale`, `TitleBlock` (everything between the `DIM`/`TEXT` constants and `IngestedSheetSurface` — confirm each helper has no caller left outside `WarehousePlan`/`OfficePlan` before deleting it, since `IngestedSheetSurface` only uses the `DIM` constant). Delete the now-unused `WALL` and `THIN` constants at the top (`DIM` stays — `IngestedSheetSurface` uses it; `TEXT` becomes unused too once the helpers are gone, delete it as well). Simplify the default export:

```jsx
export default function PlanDrawing({ sheet }) {
  // Every sheet that came from an uploaded document gets the neutral
  // surface below -- there is no drawn geometry that could honestly
  // stand in for a page nobody in this codebase has seen. `plan` is
  // always "" for a real, ingested sheet (see ingest.py); the two
  // fixture floor plans this function used to branch to for
  // sheet.plan === "warehouse"/"office" were seed-store-only and are
  // gone along with the seed store.
  return <IngestedSheetSurface sheet={sheet} />;
}
```

The final file should contain only: the file header comment (update it — it currently claims "each sheet is drafted with double-line walls..." which is no longer true; replace with a short accurate description that this renders the honest blank surface for a real sheet), the `DIM` constant, `IngestedSheetSurface`, and the default export above.

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- Workspace.test.jsx PlanDrawing
```

Expected: all PASS. If `PlanDrawing` has no dedicated test file (only exercised through `Workspace.test.jsx`), running just `Workspace.test.jsx` is sufficient.

Then run the full frontend suite and the build:

```bash
npm test
npm run build
```

Expected: all PASS, build clean. Investigate and fix any test that referenced `WarehousePlan`/`OfficePlan`/`sheetImageUrl` directly rather than skipping it.

- [ ] **Step 5: Commit**

```bash
git add src/components/Workspace.jsx src/components/CanvasPane.jsx src/components/BlueprintCanvas.jsx src/components/PlanDrawing.jsx src/components/Workspace.test.jsx
git commit -m "Remove the whole-sheet raster backdrop and its dead fixture geometry"
```

---

### Task 11: Real evidence in the item panel and evidence dialog

**Files:**
- Modify: `src/lib/store/api-mapping.js` (add `evidenceImageUrl` helper)
- Modify: `src/components/MiscModals.jsx` (`EvidenceModal`)
- Test: `src/lib/store/api-mapping.test.js` (check whether this file exists; if not, check where `mapItem` is already tested and add there) and `src/components/MiscModals.test.jsx` (create if no test file for this component exists — check first)

**Interfaces:**
- Consumes: `item.evidence.has_image` (wire shape from Task 6, passed through unmodified by `mapItem` today, same as `detail`/`sheet` already are), `item.id`, `item.version` (already mapped in `mapItem`).
- Produces: `evidenceImageUrl(item): string | null`, exported from `api-mapping.js`.

- [ ] **Step 1: Find or create the test files**

```bash
grep -rl "mapItem" src/lib/store/*.test.js src/**/*.test.jsx 2>/dev/null
grep -rl "EvidenceModal" src/components/*.test.jsx 2>/dev/null
```

If a test file covering `mapItem` already exists, append to it. If none exists, create `src/lib/store/api-mapping.test.js` following the plain-Vitest style used elsewhere in this repo (no component rendering needed — these are pure functions). If no test file covers `MiscModals.jsx`, create `src/components/MiscModals.test.jsx`.

- [ ] **Step 2: Write the failing tests**

In the `api-mapping` test file:

```js
import { describe, expect, test } from "vitest";
import { evidenceImageUrl } from "./api-mapping.js";

describe("evidenceImageUrl", () => {
  test("returns a URL when the item has an image", () => {
    const item = { id: "abc-123", version: 4, evidence: { has_image: true } };
    expect(evidenceImageUrl(item)).toBe("/api/items/abc-123/evidence-image?v=4");
  });

  test("returns null when the item has no image", () => {
    const item = { id: "abc-123", version: 4, evidence: { has_image: false } };
    expect(evidenceImageUrl(item)).toBeNull();
  });

  test("returns null when the item has no evidence at all", () => {
    const item = { id: "abc-123", version: 4, evidence: null };
    expect(evidenceImageUrl(item)).toBeNull();
  });
});
```

In `src/components/MiscModals.test.jsx` (adapt imports/rendering helpers to match this repo's existing component-test conventions, e.g. how `ScaleModal` or another `MiscModals` export is already tested if one is — check before writing):

```jsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { EvidenceModal } from "./MiscModals.jsx";

const baseItem = {
  id: "item-1", version: 1, symbol: "receptacle", status: "ready",
  evidence: { sheet: "E2.1", detail: "Counted from the drawing at 3 locations", has_image: true },
};

describe("EvidenceModal", () => {
  test("shows a real image when the item has one", () => {
    render(<EvidenceModal item={baseItem} onClose={() => {}} />);
    const img = screen.getByRole("img");
    expect(img.src).toContain("/api/items/item-1/evidence-image");
  });

  test("falls back to text when the image fails to load", () => {
    render(<EvidenceModal item={baseItem} onClose={() => {}} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByText(/no evidence recorded/i)).toBeInTheDocument();
  });

  test("shows the fallback directly for an item with no image", () => {
    const noImage = { ...baseItem, evidence: { ...baseItem.evidence, has_image: false } };
    render(<EvidenceModal item={noImage} onClose={() => {}} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(/no evidence recorded/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
npm test -- api-mapping MiscModals
```

Expected: FAIL — `evidenceImageUrl` doesn't exist yet, and `EvidenceModal` still renders the `<svg>` sketch with no `role="img"` element.

- [ ] **Step 4: Implement**

In `src/lib/store/api-mapping.js`, add near `mapItem`:

```js
// Built from fields mapItem already carries unchanged from the wire
// (evidence.has_image, id, version) -- version already increments on
// every server-side rewrite of the item (approve/edit/reject/reprocess
// all bump it), which makes it a correct cache-buster for free: a
// re-run that replaces an item's image is guaranteed to change this URL.
export function evidenceImageUrl(item) {
  if (!item?.evidence?.has_image) return null;
  return `/api/items/${item.id}/evidence-image?v=${item.version}`;
}
```

In `src/components/MiscModals.jsx`, add `useState` to the React import at the top of the file (check the current import line — this file currently has no React hook imports since none of its components use state; add `import { useState } from "react";` at the top), and add the import:

```jsx
import { evidenceImageUrl } from "../lib/store/api-mapping.js";
```

Replace `EvidenceModal` entirely:

```jsx
export function EvidenceModal({ item, onClose }) {
  const [failed, setFailed] = useState(false);
  const url = evidenceImageUrl(item);
  const showImage = url && !failed;
  return (
    <Modal title="Source evidence" onClose={onClose}>
      {showImage ? (
        <div style={{ border: "1px solid var(--line-2)", borderRadius: 6, background: "var(--sheet)", padding: 8, marginBottom: 12 }}>
          <img
            src={url}
            alt={`Source drawing crop for ${item.name}, ${item.evidence.sheet}`}
            style={{ display: "block", width: "100%", borderRadius: 4 }}
            onError={() => setFailed(true)}
          />
        </div>
      ) : (
        <p className="value value--muted" style={{ marginBottom: 12 }}>
          No evidence recorded for this item.
        </p>
      )}
      {showImage ? (
        <p style={{ margin: 0, fontSize: 13.5 }}>
          This is the region of {item.evidence.sheet} the quantity was read from. Opening evidence never leaves your place in the review.
        </p>
      ) : null}
    </Modal>
  );
}
```

Remove the now-unused `SymbolGlyph` and `STATUS`/`displayStatus` imports from the top of `MiscModals.jsx` *only if* nothing else in the file still uses them — check `ScaleModal`, `DeleteModal`, and `HelpModal` in the same file before removing any import; `displayStatus`/`STATUS`/`SymbolGlyph` were used only by the old `EvidenceModal` body if that's confirmed true by grep, in which case remove those three imports.

```bash
grep -n "SymbolGlyph\|STATUS\[\|displayStatus" src/components/MiscModals.jsx
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
npm test -- api-mapping MiscModals
```

Expected: all PASS.

Then the full frontend suite and build:

```bash
npm test
npm run build
```

Expected: all PASS, build clean.

- [ ] **Step 6: Commit**

```bash
git add src/lib/store/api-mapping.js src/components/MiscModals.jsx src/lib/store/api-mapping.test.js src/components/MiscModals.test.jsx
git commit -m "Show a real evidence crop in the source-evidence dialog"
```

(Adjust the `git add` paths above to whichever test files Step 1 actually found or created.)

---

### Task 12: Clean up `estimate_service.py`

**Files:**
- Modify: `api/estimate_service.py` (remove `/sheet-image`, `_PDF_STORE`, `_remember_pdf`; localize the vision-pass PDF lookup)
- Modify: `api/app/engine/documents.py` (delete `render_page_png` and `render_page_png_bytes`)
- Test: none new — this task only removes now-dead code and re-runs existing coverage to confirm nothing depended on it.

**Interfaces:**
- Produces: `_read_sheets_with_vision(sheets: list[dict], pdf_bytes_by_id: dict[str, bytes]) -> None` (signature change — was `_read_sheets_with_vision(sheets)`, reading from the module-level `_PDF_STORE`). Only `estimate_project_endpoint` calls this function, so this is a same-file-only signature change.

- [ ] **Step 1: Confirm nothing outside this file depends on what's being removed**

```bash
grep -rn "sheet-image\|_PDF_STORE\|_remember_pdf\|render_page_png" --include="*.py" --include="*.js" --include="*.jsx" api src
```

Expected: after Task 10, the only remaining matches are inside `api/estimate_service.py` and `api/app/engine/documents.py` themselves. If anything else still matches, stop and re-check Task 10 was fully applied before continuing.

- [ ] **Step 2: Implement — estimate_service.py**

Remove the `_PDF_STORE`/`_PDF_STORE_CAP`/`_remember_pdf` block near the top of the file:

```python
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
```

Every call site that used `_remember_pdf(data)` to produce a `takeoff_id` (there is one in `estimate_full_endpoint` and one in `estimate_project_endpoint`'s upload loop) still needs a `takeoff_id` string — it's stored on sheets and used to keep multiple documents' sheets distinct when merging (per the existing `merged_sheets` comment: "so the canvas fetches the right page image per drawing" — that comment is now stale too and should be updated, see below). Replace `_remember_pdf(data)` with a plain `uuid.uuid4().hex` at both call sites:

In `estimate_full_endpoint`:
```python
    data = await file.read()
    takeoff_id = uuid.uuid4().hex
```//
(replacing `takeoff_id = _remember_pdf(data)`)

In `estimate_project_endpoint`'s loop, replace:
```python
            if t == "Drawings":
                takeoff_id = _remember_pdf(data)
                fd, path = tempfile.mkstemp(suffix=".pdf")
```
with:
```python
            if t == "Drawings":
                takeoff_id = uuid.uuid4().hex
                fd, path = tempfile.mkstemp(suffix=".pdf")
```

`estimate_project_endpoint` still needs the raw bytes for the vision pass, but only within this one request now. Build a local dict alongside the existing `drawings` list — change:

```python
    drawings: list[tuple[str, str, str]] = []  # (takeoff_id, temp_path, filename)
    context_parts: list[str] = []
```

to:

```python
    drawings: list[tuple[str, str, str]] = []  # (takeoff_id, temp_path, filename)
    pdf_bytes_by_id: dict[str, bytes] = {}
    context_parts: list[str] = []
```

and inside the loop, right after `takeoff_id = uuid.uuid4().hex`, add:

```python
                pdf_bytes_by_id[takeoff_id] = data
```

Then change the call `await _read_sheets_with_vision(merged_sheets)` to:

```python
        await _read_sheets_with_vision(merged_sheets, pdf_bytes_by_id)
```

Update `_read_sheets_with_vision`'s signature and body from:

```python
async def _read_sheets_with_vision(sheets: list[dict]) -> None:
    if not llm.available():
        return
    targets = [s for s in sheets if not s.get("unreadable") and _PDF_STORE.get(s.get("takeoff_id"))]
    if not targets:
        return
    results = await asyncio.gather(
        *[asyncio.to_thread(_render_and_read, _PDF_STORE[s["takeoff_id"]], s["page"], s.get("number") or f"page {s['page']}") for s in targets],
        return_exceptions=True,
    )
    for sheet, res in zip(targets, results):
        if isinstance(res, dict) and res.get("devices"):
            sheet["ai_reading"] = res
```

to:

```python
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
```

Update the stale docstring on `estimate_project_endpoint` (currently ends with "so the canvas fetches the right page image per drawing" — no longer true):

```python
    """Process the whole document set: every Drawings PDF goes through the
    engine (merged), and every other document (specs, addenda, scope) has
    its electrical-relevant text extracted as context so the classifier can
    read schedules that live outside the drawings. Each sheet keeps its own
    takeoff_id so several drawing files merge without their sheet
    references colliding, and so the vision pass below can find the right
    document's bytes for each sheet within this same request."""
```

Also update `estimate_full_endpoint`'s docstring, which currently says "Also keeps the PDF bytes so the canvas can fetch sheet images":

```python
@app.post("/estimate/full")
async def estimate_full_endpoint(file: UploadFile = File(...), location: str = Form("")):
    """Per-sheet takeoff with coordinates and page dimensions, for the full
    review workflow."""
```

Delete the `/sheet-image` route entirely:

```python
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
```

If `OrderedDict` (from `collections`) and `Response` (from `fastapi.responses`) are no longer used anywhere else in this file after these deletions, remove those two imports too — check with:

```bash
grep -n "OrderedDict\|Response(" api/estimate_service.py
```

- [ ] **Step 3: Implement — documents.py**

Delete `render_page_png` (already had zero callers before this plan) and `render_page_png_bytes` (its only caller, `/sheet-image`, was just removed):

```python
def render_page_png(path: str, page_index: int, zoom: float = 2.0) -> bytes:
    """Render a sheet to PNG for the canvas to show behind the markers.
    A real blueprint needs its own page image; the drawn SVG is only for
    the seed fixture."""
    doc = pymupdf.open(path)
    page = doc[page_index]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    return pix.tobytes("png")
```

and

```python
def render_page_png_bytes(pdf_bytes: bytes, page_index: int, zoom: float = 1.6) -> bytes:
    """Same, from the PDF bytes the service keeps in memory keyed by
    takeoff id (so the canvas can fetch one sheet image on demand without
    the whole set living in the browser)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    return pix.tobytes("png")
```

Confirm no test imports either function before deleting:

```bash
grep -rn "render_page_png" api/tests
```

If any test references them, remove that test (it was testing dead-code-to-be, per this plan's Task 12 Step 1 confirmation) rather than keeping it.

- [ ] **Step 4: Run tests to verify everything still passes**

```bash
cd api && TEST_DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test" DATABASE_URL="postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff" python3 -m pytest -q
```

Expected: all PASS, same count as Task 9's checkpoint (this task removes code, it should not change test counts other than any dead test found and removed in Step 3).

Then a manual smoke check that the service still starts and processes a document (this file has no direct test suite of its own — it's exercised through the frontend manually per this repo's established workflow):

```bash
cd api && ../.enginevenv/bin/uvicorn estimate_service:app --port 8100 &
sleep 2
curl -s localhost:8100/health
kill %1
```

Expected: `{"ok":true,...}`.

- [ ] **Step 5: Commit**

```bash
git add api/estimate_service.py api/app/engine/documents.py
git commit -m "estimate_service.py: remove the sheet-image cache and route it fed"
```

---

## Self-review notes (from writing this plan)

**Spec coverage:** every "In" item from the spec has a task — backdrop removal (Task 10), evidence generation/storage/serving (Tasks 2–3, 4–9), sheet-number fix (Task 1), and estimate_service.py cleanup (Task 12) including the `render_page_png`/`_PDF_STORE` items the spec called out as found during investigation. `WarehousePlan`/`OfficePlan` deletion is folded into Task 10 per the spec's own listing of it as backdrop-adjacent cleanup.

**Deviation from the spec's pseudocode, both intentional:** (1) the spec's sheet-number fix sketch introduced a new `TITLE_BLOCK_STRIP = 0.18` constant; Task 1 instead reuses the existing `RIGHT_STRIP = 0.82` (`1 - 0.18`), since that's already the exact boundary `detect_sheets` uses to exclude the title block from device counting — one constant instead of two that could drift apart. (2) the spec's crop-sizing sketch mentioned an `EVIDENCE_MAX_BBOX_PT` cap "beyond which... let zoom shrink instead of cropping"; Task 2's `zoom = EVIDENCE_MAX_PX / max(bbox_w, bbox_h)` formula already produces that behavior for any bbox size without a separate cap constant, so it was dropped as redundant rather than implemented unused.

**Type/name consistency checked:** `evidence_png_b64` (wire) → `evidence_png` (mapped dict, Task 6) → popped off before `Item(...)` construction (Tasks 7–8) → never a column name. `has_image` (not `hasImage`) is used consistently wherever the evidence dict is read on the frontend (Task 11), matching that `mapItem` passes the dict through unmodified. `render_evidence_crop`'s signature is identical everywhere it's declared (Task 2) and called (Task 3).
