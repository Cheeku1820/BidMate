# Engine Sheet Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Documents and Counting agents read every vector bid set in `bid_examples/` correctly — sheet numbers deterministic and right, schedules no longer counted as plans, titles real, and every placement in the frame the estimator sees so markers land on the drawing.

**Architecture:** One coordinate-frame transform at the PyMuPDF boundary (`page_frame.py`) puts words, spans and drawings into the visual frame; everything downstream reasons in that frame only. Title-block location, sheet-number and title extraction move into `title_block.py`; sheet-kind classification into `sheet_kind.py`; `documents.py` orchestrates. `DetectedSheet` gains `kind`; Counting returns nothing for a non-plan. A `Sheet.kind` column and a rail badge carry it to the estimator. Hand-written per-set fixtures are the answer key.

**Tech Stack:** Python 3.12, PyMuPDF (`pymupdf`), pytest, SQLAlchemy 2.0 + Alembic, React 18 + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-14-engine-sheet-fidelity-design.md`. Read §1.1 before Task 1 — it is the bug this whole plan exists for.

## Global Constraints

- **Visual frame everywhere.** `page.get_text*()` and `page.get_drawings()` return unrotated-mediabox coordinates; `page.rect` and `page.get_pixmap(clip=…)` are visual. Convert with `rect * page.rotation_matrix` (→ visual) and `rect * page.derotation_matrix` (→ unrotated). Verified 2026-09-14 on Unalaska page 87 and on a synthetic page: `get_textbox` needs an unrotated clip; `get_pixmap` needs a visual clip. No code outside `page_frame.py` may call `page.get_text("words")` or `page.get_text("dict")` directly.
- **Sheet kind is a closed set:** `plan`, `schedule`, `legend`, `diagram`, `other`. Nothing else, anywhere.
- **Unsure → `plan`.** Over-counting is visible in review; omission is silent.
- **A page is an electrical sheet when, and only when, the token in its title-block number cell matches `SHEET_ID`.** No whole-page fallback. No title block → not detected.
- **`SHEET_ID = re.compile(r"\bE[A-Z]{0,2}-?\d{1,3}(?:\.\d{1,2})?\b")`** — never applied to whole-page text to decide discipline.
- **No `set()` iteration decides a sheet number.** Ties resolve by frequency, then first appearance in reading order.
- **Counting is tested, not trained.** Every asserted count is one a person verified by opening the PDF. Fixtures are written by reading title blocks, never by running the engine and copying its output.
- **The four review labels are untouched.** `kind` is a sheet property on its own axis; it is never rendered with a status component or status colour.
- **Interface copy is sentence case**, no exclamation marks, no "successfully", no "please". Titles on the wire: `Panel schedule`, not `PANEL SCHEDULE`.
- **Raster sets stay `unreadable_reason`.** FedEx, Gerber and TSC Harrison must still be detected-and-unreadable, never silently absent.
- Backend tests run from `api/` with `TEST_DATABASE_URL` set; the engine venv is `/Users/nikhit/Documents/takeoff-review/.enginevenv/bin/python`. The corpus is at `bid_examples/` (a symlink in this worktree); tests that need it skip with a printed reason when it is absent.
- Commit messages: end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File structure

| File | Responsibility |
|---|---|
| `api/app/engine/page_frame.py` (new) | The one place PyMuPDF's two frames meet. `Word`, `visual_words()`, `visual_spans()`, `to_visual()`, `to_unrotated()`. |
| `api/app/engine/title_block.py` (new) | Locate the title-block strip; read the sheet number and title from it. `SHEET_ID` lives here. |
| `api/app/engine/sheet_kind.py` (new) | `classify_kind(title, page_text, has_scale) -> str`. |
| `api/app/engine/contracts.py` | `DetectedSheet.kind`. |
| `api/app/engine/documents.py` | `detect_sheets` orchestrates the three modules; region from the located strip; `render_evidence_crop` documented as visual-in. `RIGHT_STRIP` removed. |
| `api/app/engine/counting.py` | Reads words and spans through `page_frame`; returns `[]` for a non-plan. |
| `api/app/engine/estimate.py` | `full_takeoff` emits `kind`, `title`, `scale` per sheet (today it emits none of them, which is why every stored title is the fallback). |
| `api/app/takeoff/{models,schemas,snapshot,ingest,ingest_service,reprocess}.py`, `api/migrations/versions/0018_sheet_kind.py` | `Sheet.kind` through the store. |
| `src/lib/store/api-mapping.js`, `src/components/SheetsRail.jsx` | `sheet.kind`; a badge for non-plans. |
| `api/tests/fixtures/sheets/*.json` (new) | Per-set answer keys. |
| `api/tests/test_page_frame.py`, `test_title_block.py`, `test_sheet_kind.py`, `test_corpus_sheets.py` (new); `test_engine_documents.py`, `test_engine_counting.py`, `test_engine_pipeline.py` (modified) | |

---

### Task 1: `page_frame.py` — one transform at the boundary

**Files:**
- Create: `api/app/engine/page_frame.py`
- Test: `api/tests/test_page_frame.py`

**Interfaces:**
- Produces: `Word` dataclass (`x0 y0 x1 y1 text block line`, properties `cx`, `cy`); `visual_words(page) -> list[Word]`; `visual_spans(page) -> list[tuple[float, float, str]]` (cx, cy, font); `to_visual(rect, page) -> pymupdf.Rect`; `to_unrotated(rect, page) -> pymupdf.Rect`. Every coordinate returned is in the visual frame.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_page_frame.py
"""The frame transform is the fix under three of the spec's defects. These
tests pin the facts measured on 2026-09-14: raw text coordinates are
unrotated, page.rect is visual, and the transform round-trips."""

import pymupdf
import pytest

from app.engine import page_frame


@pytest.fixture
def rotated_page(tmp_path):
    """A 1000x800 page turned 90 degrees, so its visual frame is 800x1000.
    'A' is inserted at unrotated (100, 100); 'Z' at unrotated (900, 700)."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((100, 100), "A")
    page.insert_text((900, 700), "Z")
    page.set_rotation(90)
    path = tmp_path / "rot.pdf"
    doc.save(path)
    return pymupdf.open(path)[0]


def test_visual_words_land_inside_the_visual_page(rotated_page):
    assert rotated_page.rect.width == 800 and rotated_page.rect.height == 1000
    words = page_frame.visual_words(rotated_page)
    assert {w.text for w in words} == {"A", "Z"}
    for w in words:
        assert rotated_page.rect.contains(pymupdf.Rect(w.x0, w.y0, w.x1, w.y1)), w


def test_raw_words_would_not_have(rotated_page):
    """The bug: raw get_text coordinates do not fit the visual page."""
    raw = rotated_page.get_text("words")
    z = next(w for w in raw if w[4] == "Z")
    assert z[0] > rotated_page.rect.width, "raw x of Z exceeds the visual width"


def test_transform_round_trips(rotated_page):
    raw = rotated_page.get_text("words")
    r = pymupdf.Rect(raw[0][:4])
    back = page_frame.to_unrotated(page_frame.to_visual(r, rotated_page), rotated_page)
    assert abs(back.x0 - r.x0) < 1e-6 and abs(back.y1 - r.y1) < 1e-6


def test_visual_clip_reads_the_right_glyph(rotated_page):
    """A visual rect, derotated, is the clip get_textbox needs."""
    z = next(w for w in page_frame.visual_words(rotated_page) if w.text == "Z")
    clip = page_frame.to_unrotated(pymupdf.Rect(z.x0, z.y0, z.x1, z.y1), rotated_page)
    assert rotated_page.get_textbox(clip).strip() == "Z"


def test_visual_spans_match_visual_words(rotated_page):
    words = {w.text: (w.cx, w.cy) for w in page_frame.visual_words(rotated_page)}
    spans = page_frame.visual_spans(rotated_page)
    assert len(spans) == 2
    for cx, cy, font in spans:
        assert isinstance(font, str)
        assert any(abs(cx - wx) < 2 and abs(cy - wy) < 2 for wx, wy in words.values())


def test_unrotated_page_is_the_identity(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((100, 100), "A")
    raw = page.get_text("words")[0]
    w = page_frame.visual_words(page)[0]
    assert (round(w.x0), round(w.y0)) == (round(raw[0]), round(raw[1]))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && TEST_DATABASE_URL=postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff_test /Users/nikhit/Documents/takeoff-review/.enginevenv/bin/pytest tests/test_page_frame.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.engine.page_frame'`

- [ ] **Step 3: Write the module**

```python
# api/app/engine/page_frame.py
"""Coordinate frames for a PDF page.

PyMuPDF mixes two frames on a rotated page. `page.rect` and
`page.get_pixmap()` (including its `clip`) are in the VISUAL frame --
what a viewer shows. `page.get_text()`, `page.get_textbox()` and
`page.get_drawings()` are in the UNROTATED mediabox frame. On a page
with rotation 90 the two differ by a transpose and a flip, so a clip
built in one and applied in the other silently selects the wrong
region. That is how the counting region came to exclude the visual
right third of every Unalaska sheet, and how markers came to sit off
the drawing. Measured 2026-09-14, spec section 1.1.

Everything the engine reasons about is in the visual frame, and this
module is the only place the transform happens. No other module calls
`page.get_text("words")` or `page.get_text("dict")`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf


@dataclass(frozen=True)
class Word:
    """One whitespace-delimited token, visual frame."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int
    line: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def to_visual(rect, page: pymupdf.Page) -> pymupdf.Rect:
    """Unrotated-frame rect -> visual-frame rect."""
    return pymupdf.Rect(rect) * page.rotation_matrix


def to_unrotated(rect, page: pymupdf.Page) -> pymupdf.Rect:
    """Visual-frame rect -> unrotated-frame rect (what get_textbox wants)."""
    return pymupdf.Rect(rect) * page.derotation_matrix


def visual_words(page: pymupdf.Page) -> list[Word]:
    m = page.rotation_matrix
    out: list[Word] = []
    for x0, y0, x1, y1, text, block, line, _word in page.get_text("words"):
        r = pymupdf.Rect(x0, y0, x1, y1) * m
        out.append(Word(r.x0, r.y0, r.x1, r.y1, text, block, line))
    return out


def visual_spans(page: pymupdf.Page) -> list[tuple[float, float, str]]:
    """(centre x, centre y, font name) for every text span, visual frame.
    The seal filter in counting.py keys on the font."""
    m = page.rotation_matrix
    out: list[tuple[float, float, str]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                r = pymupdf.Rect(span["bbox"]) * m
                out.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, span["font"]))
    return out
```

- [ ] **Step 4: Run to verify they pass**

Run: same command as Step 2.
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/page_frame.py api/tests/test_page_frame.py
git commit -m "Put the PyMuPDF frame transform in one place

get_text and get_drawings return unrotated-mediabox coordinates while
page.rect and get_pixmap are visual. Every clip and region in
documents.py was built in one frame and applied in the other, which
on a rotated page selects the wrong region silently. This module is
now the only place the two frames meet.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Counting reads the visual frame

**Files:**
- Modify: `api/app/engine/counting.py:166-199` (`count_sheet`), `:101-163` (`_stamp_points`)
- Modify: `api/tests/test_engine_counting.py` (the `known_sheet` fixture and the two seal tests)

**Interfaces:**
- Consumes: `page_frame.visual_words`, `page_frame.visual_spans`.
- Produces: `Placement.x/y` are now **visual-frame** integers. `count_sheet(path, sheet)` signature unchanged.

The seal tests assert that no placement falls inside the seal's coordinate window. That window (`850 < x < 1010 and 40 < y < 160`) was written in the unrotated frame. On a 90° page with mediabox 1584×2448, `rect * rotation_matrix` maps unrotated `(x, y)` to visual `(2448 − y, x)` — so the window becomes `2288 < x < 2408 and 850 < y < 1010`. Verify that on page 84 before moving the assertion: print the visual centre of the `ArialNarrow` spans and confirm they fall inside the new window.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_engine_counting.py` (keep everything already there for now):

```python
def test_placements_are_in_the_visual_frame(tmp_path):
    """A rotated page: the tag's placement must land where a viewer
    sees it, inside page.rect, not at its raw unrotated coordinate."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    for i in range(3):
        page.insert_text((900, 100 + i * 60), "R")   # unrotated x=900
    page.set_rotation(90)                            # visual page is 800x1000
    path = tmp_path / "rot.pdf"
    doc.save(path)
    sheet = DetectedSheet(
        page_index=0, number="E1.1", title="test", discipline="Electrical",
        scale="", width_pt=800, height_pt=1000, region=(0, 0, 800, 1000),
    )
    clusters = counting.count_sheet(str(path), sheet)
    assert [c.tag for c in clusters] == ["R"]
    for p in clusters[0].placements:
        assert 0 <= p.x <= 800 and 0 <= p.y <= 1000, (p.x, p.y)
        # Measured: on a 90-degree page unrotated (x, y) -> visual (H - y, x),
        # so unrotated x=900 becomes visual y~900 and unrotated y 100-220
        # becomes visual x ~580-700. The raw value 900 fits neither axis's
        # old reading -- that is the bug.
        assert p.y > 850, "unrotated x=900 must become a large visual y on a 90-degree page"
```

Then move the two seal windows. In `test_the_seal_is_not_counted_as_devices` and `test_real_devices_survive_the_stamp_filter`, replace

```python
    seal = [p for c in clusters for p in c.placements
            if 850 < p.x < 1010 and 40 < p.y < 160]
```

with

```python
    # Visual frame. The seal's unrotated window was x 850-1010, y 40-160;
    # on this 90-degree page visual (x, y) = (2448 - y_unrot, x_unrot).
    seal = [p for c in clusters for p in c.placements
            if 2288 < p.x < 2408 and 850 < p.y < 1010]
```

and update `known_sheet`'s docstring line "A device tag inside the title-block strip (x > 820)" — the fixture itself is unrotated so its numbers stay as they are.

- [ ] **Step 2: Run to verify the new test fails**

Run: `cd api && …pytest tests/test_engine_counting.py::test_placements_are_in_the_visual_frame -v`
Expected: FAIL — `assert 900 < 200` (placement x is the raw unrotated value).

- [ ] **Step 3: Rewrite `count_sheet` and `_stamp_points` on the visual frame**

Replace the body of `_stamp_points(page)` from `condensed: list[...] = []` through the `for block in page.get_text("dict")…` loop with:

```python
    condensed: list[tuple[float, float]] = []
    spans: list[tuple[float, float]] = []
    for cx, cy, font in visual_spans(page):
        spans.append((cx, cy))
        if _CONDENSED_FONT in font.lower():
            condensed.append((cx, cy))
```

and add `from .page_frame import visual_spans, visual_words` to the imports. Then replace `count_sheet`'s word loop:

```python
def count_sheet(path: str, sheet: DetectedSheet) -> list[DeviceCluster]:
    if sheet.unreadable_reason:
        return []
    doc = pymupdf.open(path)
    page = doc[sheet.page_index]
    # Visual frame throughout (page_frame.py): a placement is where a
    # viewer sees the tag, so ingest's normalisation against the visual
    # width_pt/height_pt lands the marker on the drawing.
    words = visual_words(page)
    stamp = _stamp_points(page)

    line_len: Counter = Counter((w.block, w.line) for w in words)

    by_tag: dict[str, list[Placement]] = defaultdict(list)
    for w in words:
        t = w.text.strip()
        if not TAG.match(t) or t in NOISE:
            continue
        if line_len[(w.block, w.line)] > MAX_LINE_WORDS:
            continue  # prose, not a device tag
        if (round(w.cx), round(w.cy)) in stamp:
            continue  # title-block seal/stamp text is never a device tag
        if not _in_region(w.cx, w.cy, sheet.region):
            continue
        by_tag[t].append(Placement(int(w.cx), int(w.cy)))
    clusters = [
        DeviceCluster(tag=tag, sheet_page_index=sheet.page_index, placements=places)
        for tag, places in by_tag.items()
        if len(places) >= MIN_PLACEMENTS
    ]
    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters
```

Update the `_stamp_points` docstring's last paragraph — "Positions are rounded to whole points so they can be matched against the word list, which reports the same coordinates" — to add "both in the visual frame (page_frame.py)".

- [ ] **Step 4: Run the whole counting file**

Run: `cd api && …pytest tests/test_engine_counting.py -v -rs`
Expected: all pass, including the two seal tests on the moved windows. If a seal test fails, do not widen the window — print the visual centres of the `ArialNarrow` spans on page 84 (`[(round(cx), round(cy)) for cx, cy, f in visual_spans(page) if "narrow" in f.lower()]`) and set the window to enclose them with the same ±margins the old one had.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/counting.py api/tests/test_engine_counting.py
git commit -m "Count in the visual frame so placements land where the viewer looks

Placements were raw get_text coordinates and ingest normalised them
against the visual page size, which on every rotated Unalaska sheet
put markers squashed left, off the bottom edge, and unrotated. The
seal filter's span centres move with them; the seal test windows are
transformed by hand to the visual frame, not loosened.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `title_block.py` — locate the strip, read the number deterministically

**Files:**
- Create: `api/app/engine/title_block.py`
- Test: `api/tests/test_title_block.py`

**Interfaces:**
- Consumes: `page_frame.Word`.
- Produces: `SHEET_ID` (compiled regex); `TitleBlock(edge: str, strip: tuple[float,float,float,float], words: list[Word])` with `edge in {"bottom","right","top","left"}`; `locate(words, width, height) -> TitleBlock | None`; `sheet_number(tb) -> str` (`""` when the strip holds no family token); `title(tb, number) -> str` (Task 4 fills this in; here it returns `""`).

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_title_block.py
"""Title-block location and the deterministic sheet number. Synthetic
pages only; the corpus is Task 6's job."""

import pymupdf
import pytest

from app.engine import page_frame, title_block


def _page(tmp_path, width=1000, height=800, rotation=0):
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    return doc, page


def _words(doc, page, tmp_path, rotation=0):
    if rotation:
        page.set_rotation(rotation)
    path = tmp_path / "p.pdf"
    doc.save(path)
    p = pymupdf.open(path)[0]
    return page_frame.visual_words(p), p.rect.width, p.rect.height


def test_locates_a_right_strip(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "DRAWN")
    page.insert_text((900, 760), "E2.1")       # number cell, bottom of the strip
    page.insert_text((300, 400), "SEE E5.1")   # a reference in the drawing
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert tb is not None and tb.edge == "right"
    assert title_block.sheet_number(tb) == "E2.1"


def test_locates_a_bottom_strip_on_a_rotated_page(tmp_path):
    """Unrotated right strip + 90-degree rotation = visual bottom strip."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "CHECKED")
    page.insert_text((900, 760), "E-101")
    words, w, h = _words(doc, page, tmp_path, rotation=90)
    tb = title_block.locate(words, w, h)
    assert tb is not None and tb.edge == "bottom"
    assert title_block.sheet_number(tb) == "E-101"


def test_no_strip_means_none(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((300, 400), "SEE E5.1 FOR DETAILS")
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.locate(words, w, h) is None


def test_number_prefers_the_corner_over_frequency(tmp_path):
    """A revision table in the strip repeats another sheet's number three
    times; the number cell at the corner still wins."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    for y in (200, 230, 260):
        page.insert_text((900, y), "E1.0")     # references, mid-strip
    page.insert_text((900, 770), "E2.1")       # the number cell, at the corner
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.sheet_number(title_block.locate(words, w, h)) == "E2.1"


def test_ties_break_by_frequency_then_first_seen(tmp_path):
    """Two tokens equidistant from the corner: the more frequent wins;
    still tied, the first in reading order wins. Never hash order."""
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    # Corner of the right strip is (1000, 800). Both tokens sit ~72pt from
    # it -- (40, 60) and (60, 40) away -- so distance cannot separate them.
    page.insert_text((960, 740), "E3.1")
    page.insert_text((940, 760), "E3.2")
    page.insert_text((900, 300), "E3.2")       # E3.2 appears twice overall
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.sheet_number(title_block.locate(words, w, h)) == "E3.2"


def test_ties_at_equal_frequency_take_the_first_in_reading_order(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((940, 760), "E3.1")       # inserted first
    page.insert_text((960, 740), "E3.2")
    words, w, h = _words(doc, page, tmp_path)
    assert title_block.sheet_number(title_block.locate(words, w, h)) == "E3.1"


def test_strip_with_no_family_token_yields_empty(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((900, 130), "DRAWN")
    page.insert_text((900, 760), "A-101")      # an architectural number
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert tb is not None
    assert title_block.sheet_number(tb) == ""


@pytest.mark.parametrize("token,ok", [
    ("E2.1", True), ("E-101", True), ("E101", True), ("EP-1", True), ("EL101", True),
    ("EF-1", True), ("EX10", True), ("ED-101", True), ("EQ101", True),
    ("A-101", False), ("M2.1", False), ("E", False), ("SEE", False), ("EE-12624", False),
])
def test_sheet_id_family(token, ok):
    assert bool(title_block.SHEET_ID.fullmatch(token)) is ok
```

Note `EE-12624` (the engineer's licence number on the Unalaska seal) must not match: `E[A-Z]{0,2}` allows `EE`, but `\d{1,3}` caps the digits at three, so `12624` fails. Keep that cap.

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && …pytest tests/test_title_block.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

```python
# api/app/engine/title_block.py
"""Locate a sheet's title block and read its number and title.

A title block is a strip along one edge of the visual page; which edge
varies by firm (Unalaska's is along the visual bottom once the page's
90-degree rotation is applied). It is found by scoring each of the four
edge strips on how many sheet-number-family tokens and title-block
labels it holds. The sheet's own number is the family token nearest the
corner the strip ends at -- drafting convention puts the number cell
there -- which is what lets a revision table that repeats another
sheet's number three times lose to the one number cell.

Deterministic by construction: ties break by frequency in the strip,
then by first appearance in reading order. Nothing here iterates a set.
The previous implementation did (`max(set(ids), key=ids.count)`), and
the same page resolved to three different numbers across three
processes. Spec section 2.3.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .page_frame import Word

# The sheet-number family across the corpus: E2.1, E-101, E101, EP-1,
# EL101, EF-1, EX10, ED-101, EQ101. Two optional discipline letters, an
# optional hyphen, one to three digits, an optional decimal. The
# three-digit cap keeps a licence number like EE-12624 out. Broad enough
# to match a device tag ("E1"), so it is NEVER applied to whole-page
# text to decide whether a page is electrical -- only to the strip.
SHEET_ID = re.compile(r"\bE[A-Z]{0,2}-?\d{1,3}(?:\.\d{1,2})?\b")

# Labels a title block carries. Uppercase, compared against the word.
LABELS = {"SHEET", "DRAWN", "CHECKED", "DATE", "PROJECT", "REVISION", "REV", "SCALE", "TITLE"}

# The outer fraction of the page an edge strip covers.
STRIP = 0.18


@dataclass(frozen=True)
class TitleBlock:
    edge: str  # "bottom" | "right" | "top" | "left"
    strip: tuple[float, float, float, float]  # visual frame
    words: list[Word]  # every word inside the strip, reading order


def _strips(width: float, height: float) -> dict[str, tuple[float, float, float, float]]:
    return {
        "bottom": (0, height * (1 - STRIP), width, height),
        "right": (width * (1 - STRIP), 0, width, height),
        "top": (0, 0, width, height * STRIP),
        "left": (0, 0, width * STRIP, height),
    }


def _inside(w: Word, r: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = r
    return x0 <= w.cx <= x1 and y0 <= w.cy <= y1


def _score(words: list[Word]) -> int:
    return sum(1 for w in words if SHEET_ID.fullmatch(w.text) or w.text.upper().strip(":") in LABELS)


def locate(words: list[Word], width: float, height: float) -> TitleBlock | None:
    """The edge strip that reads most like a title block, or None when no
    strip holds a single family token or label -- in which case the page
    is not detected as an electrical sheet (spec 2.2)."""
    best: TitleBlock | None = None
    best_score = 0
    # Fixed iteration order (bottom, right, top, left): a tie between two
    # edges resolves the same way every run.
    for edge, strip in _strips(width, height).items():
        inside = [w for w in words if _inside(w, strip)]
        s = _score(inside)
        if s > best_score:
            best, best_score = TitleBlock(edge=edge, strip=strip, words=inside), s
    return best


def _corner(tb: TitleBlock) -> tuple[float, float]:
    x0, y0, x1, y1 = tb.strip
    return {
        "bottom": (x1, y1),
        "right": (x1, y1),
        "top": (x1, y0),
        "left": (x0, y1),
    }[tb.edge]


def sheet_number(tb: TitleBlock) -> str:
    """The family token nearest the strip's end corner; ties by frequency
    in the strip, then first appearance. "" when the strip holds none."""
    tokens = [w for w in tb.words if SHEET_ID.fullmatch(w.text)]
    if not tokens:
        return ""
    cx, cy = _corner(tb)
    freq = Counter(w.text for w in tokens)
    first = {}
    for i, w in enumerate(tokens):
        first.setdefault(w.text, i)
    # Distance bands of 40pt: two tokens in the same cell are "equally
    # near"; the tiebreakers then decide, never float noise.
    return min(
        tokens,
        key=lambda w: (round(((w.cx - cx) ** 2 + (w.cy - cy) ** 2) ** 0.5 / 40), -freq[w.text], first[w.text]),
    ).text


def title(tb: TitleBlock, number: str) -> str:
    """Filled in by Task 4."""
    return ""
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd api && …pytest tests/test_title_block.py -v`
Expected: all pass. If either tie test fails on the band, print both tokens' distances to the corner and adjust positions so they round to the same 40pt band — never change the tie-break rule to fit the fixture.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/title_block.py api/tests/test_title_block.py
git commit -m "Locate the title block and read the sheet number deterministically

Scores the four edge strips for family tokens and title-block labels,
takes the token nearest the strip's end corner, and breaks ties by
frequency then reading order. Replaces max(set(ids), key=ids.count),
which resolved the same page to three different numbers across three
processes. SHEET_ID now covers the five conventions in the corpus and
is applied to the strip only.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Sheet kind and title

**Files:**
- Create: `api/app/engine/sheet_kind.py`
- Modify: `api/app/engine/title_block.py` (`title()`)
- Modify: `api/app/engine/contracts.py:16-31` (`DetectedSheet.kind`)
- Test: `api/tests/test_sheet_kind.py`, add to `api/tests/test_title_block.py`

**Interfaces:**
- Produces: `sheet_kind.KINDS = ("plan", "schedule", "legend", "diagram", "other")`; `sheet_kind.classify(title: str, page_text: str, has_scale: bool) -> str`; `sheet_kind.label(kind) -> str` (`"Electrical plan"`, `"Schedule"`, `"Legend"`, `"Diagram"`, `"Sheet"`); `title_block.title(tb, number) -> str` (sentence case, or `""`); `DetectedSheet.kind: str = "plan"`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_sheet_kind.py
from app.engine import sheet_kind


def test_kinds_are_the_closed_set():
    assert sheet_kind.KINDS == ("plan", "schedule", "legend", "diagram", "other")


def test_title_decides_first():
    assert sheet_kind.classify("Panel schedules", "", True) == "schedule"
    assert sheet_kind.classify("Electrical legend and abbreviations", "", False) == "legend"
    assert sheet_kind.classify("One-line diagram", "", False) == "diagram"
    assert sheet_kind.classify("Lighting controls", "", False) == "diagram"
    assert sheet_kind.classify("First floor power plan", "", True) == "plan"
    assert sheet_kind.classify("Cover sheet", "", False) == "other"


def test_content_markers_when_the_title_is_silent():
    sched = "PANEL SCHEDULE ... LUMINAIRE SCHEDULE ... VA CKT AMP"
    assert sheet_kind.classify("", sched, False) == "schedule"
    assert sheet_kind.classify("", "ON / OFF " * 5, False) == "diagram"
    assert sheet_kind.classify("", "READING AREA  STACKS/ADULT", True) == "plan"


def test_one_schedule_header_is_not_enough():
    """A plan sheet with one embedded lighting schedule block is still a plan."""
    assert sheet_kind.classify("", "LUMINAIRE SCHEDULE  A  B  C", True) == "plan"


def test_a_scale_outranks_content_markers():
    assert sheet_kind.classify("", "PANEL SCHEDULE  LUMINAIRE SCHEDULE", True) == "plan"


def test_unsure_is_plan():
    assert sheet_kind.classify("", "", False) == "plan"


def test_labels_are_sentence_case():
    assert [sheet_kind.label(k) for k in sheet_kind.KINDS] == [
        "Electrical plan", "Schedule", "Legend", "Diagram", "Sheet",
    ]
```

Add to `api/tests/test_title_block.py`:

```python
def test_title_reads_the_cell_next_to_the_number(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((880, 700), "FIRST FLOOR")
    page.insert_text((880, 725), "POWER PLAN")
    page.insert_text((900, 770), "E2.1")
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E2.1") == "First floor power plan"


def test_title_rejects_address_and_seal_lines(tmp_path):
    doc, page = _page(tmp_path)
    page.insert_text((900, 100), "SHEET")
    page.insert_text((860, 700), "3909 ARCTIC BOULEVARD, SUITE 103")
    page.insert_text((860, 725), "REGISTERED PROFESSIONAL ENGINEER")
    page.insert_text((900, 770), "E2.1")
    words, w, h = _words(doc, page, tmp_path)
    tb = title_block.locate(words, w, h)
    assert title_block.title(tb, "E2.1") == ""
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && …pytest tests/test_sheet_kind.py tests/test_title_block.py -v`
Expected: `test_sheet_kind.py` fails on import; the two new title tests fail on `"" == "First floor power plan"`.

- [ ] **Step 3: Write `sheet_kind.py`, fill in `title()`, add `kind` to the contract**

```python
# api/app/engine/sheet_kind.py
"""What kind of sheet a page is: the one field that stops a panel
schedule being counted as a floor plan.

A closed set. Decided from the title-block title first, content markers
second, and when nothing decides, `plan` -- over-counting is visible in
review, omission is silent (spec 2.4). This is a property of a sheet on
its own axis; it is never one of the four review labels and is never
rendered with a status component.
"""

from __future__ import annotations

import re

KINDS = ("plan", "schedule", "legend", "diagram", "other")

_TITLE_RULES = (
    ("schedule", ("SCHEDULE",)),
    ("legend", ("LEGEND", "SYMBOLS", "ABBREVIATIONS")),
    ("diagram", ("ONE-LINE", "ONE LINE", "RISER", "DIAGRAM", "DETAILS", "CONTROLS")),
    ("plan", ("PLAN",)),
    ("other", ("COVER", "INDEX", "NOTES")),
)

_SCHEDULE_HEADERS = (
    "PANEL SCHEDULE", "LUMINAIRE SCHEDULE", "FIXTURE SCHEDULE",
    "EQUIPMENT SCHEDULE", "MECHANICAL SCHEDULE",
)
_ON_OFF = re.compile(r"\bON\s*/\s*OFF\b")

_LABELS = {
    "plan": "Electrical plan",
    "schedule": "Schedule",
    "legend": "Legend",
    "diagram": "Diagram",
    "other": "Sheet",
}


def classify(title: str, page_text: str, has_scale: bool) -> str:
    t = title.upper()
    for kind, needles in _TITLE_RULES:
        if any(n in t for n in needles):
            return kind
    if has_scale:
        return "plan"
    text = page_text.upper()
    headers = sum(1 for h in _SCHEDULE_HEADERS if h in text)
    if headers >= 2:
        return "schedule"
    if len(_ON_OFF.findall(text)) >= 4:
        return "diagram"
    return "plan"


def label(kind: str) -> str:
    return _LABELS.get(kind, _LABELS["plan"])
```

Replace `title()` in `title_block.py`:

```python
# Words that mark an address, a signature line or a seal -- never a title.
_NOT_TITLE = {
    "SUITE", "BOULEVARD", "STREET", "AVENUE", "PHONE", "FAX", "CHECKED", "DRAWN",
    "DATE", "REGISTERED", "PROFESSIONAL", "ENGINEER", "SHEET", "PROJECT", "NO.",
}
# How far from the number cell the title cell may sit, in points.
_TITLE_REACH = 120.0


def title(tb: TitleBlock, number: str) -> str:
    """The title cell: uppercase lines within _TITLE_REACH of the number
    cell, joined, sentence-cased. "" when nothing passes the sanity check
    (2-10 words, no digits-only tokens, none of _NOT_TITLE)."""
    cell = next((w for w in tb.words if w.text == number), None)
    if cell is None:
        return ""
    near = [
        w for w in tb.words
        if w.text != number
        and abs(w.cx - cell.cx) <= _TITLE_REACH
        and abs(w.cy - cell.cy) <= _TITLE_REACH
        and w.text.isupper()
    ]
    # Group by text line, keep reading order.
    lines: dict[tuple[int, int], list[str]] = {}
    for w in near:
        lines.setdefault((w.block, w.line), []).append(w.text)
    words: list[str] = [t for _, ts in sorted(lines.items()) for t in ts]
    if not 2 <= len(words) <= 10:
        return ""
    if any(t.isdigit() for t in words):
        return ""
    if any(t.strip(",.:") in _NOT_TITLE for t in words):
        return ""
    text = " ".join(words).strip(" ,.")
    return text[:1].upper() + text[1:].lower()
```

In `contracts.py`, add after `region`:

```python
    # What the sheet is: "plan" | "schedule" | "legend" | "diagram" | "other"
    # (sheet_kind.KINDS). Counting runs only on a plan. A sheet property
    # on its own axis -- never one of the four review labels.
    kind: str = "plan"
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd api && …pytest tests/test_sheet_kind.py tests/test_title_block.py -v`
Expected: all pass. If `test_title_reads_the_cell_next_to_the_number` fails on reach, the synthetic title lines sit more than 120pt from the number — move them to y=720/745 rather than widening `_TITLE_REACH`, which was chosen to exclude the address block on Unalaska (`3909 ARCTIC BOULEVARD` sits ~300pt from the number cell).

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/sheet_kind.py api/app/engine/title_block.py api/app/engine/contracts.py api/tests/test_sheet_kind.py api/tests/test_title_block.py
git commit -m "Give a sheet a kind, and read its title from the title block

Closed set: plan, schedule, legend, diagram, other. Title first,
content markers second, plan when unsure. The title is the uppercase
cell beside the number, sanity-checked against address and seal lines.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `detect_sheets` on the new modules; Counting gated on kind

**Files:**
- Modify: `api/app/engine/documents.py:23-34` (constants), `:61-84` (`_sheet_number` → delete), `:91-131` (`detect_sheets`), `:197-` (`render_evidence_crop` docstring)
- Modify: `api/app/engine/counting.py` (`count_sheet` — the kind gate)
- Modify: `api/tests/test_engine_documents.py` (fixture and the two sheet-number tests)
- Modify: `api/tests/test_engine_pipeline.py` (add the Unalaska assertions)

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `detect_sheets(path) -> list[DetectedSheet]` with `kind`, a real `title` (or the kind label), `scale`, and `region` computed from the located strip. `count_sheet` returns `[]` when `sheet.kind != "plan"`.

- [ ] **Step 1: Rewrite the synthetic documents tests**

Replace `api/tests/test_engine_documents.py` lines 1–61 (the fixture and the two sheet-number tests; keep the evidence-crop tests from line 63 on) with:

```python
"""The Documents agent on synthetic pages. The corpus is test_corpus_sheets.py."""

import pymupdf
import pytest

from app.engine import documents


def _sheet(tmp_path, own_number, refs=(), title_lines=(), rotation=0, drawings=600, scale=True):
    """A 1000x800 page with a right-edge title block (SHEET/DRAWN labels,
    optional title lines, the number cell at the bottom corner), a body
    that references other sheets, and enough vector paths to be a plan."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((900, 60), "SHEET")
    page.insert_text((900, 85), "DRAWN")
    for i, line in enumerate(title_lines):
        page.insert_text((870, 700 + i * 22), line)
    page.insert_text((900, 770), own_number)
    for i, ref in enumerate(refs):
        page.insert_text((200, 200 + i * 40), f"SEE {ref}")
    if scale:
        page.insert_text((200, 600), 'SCALE: 1/8" = 1\'-0"')
    for i in range(drawings):
        page.draw_line((50 + (i % 40) * 15, 100 + (i // 40) * 12), (55 + (i % 40) * 15, 105 + (i // 40) * 12))
    if rotation:
        page.set_rotation(rotation)
    path = tmp_path / "s.pdf"
    doc.save(path)
    return str(path)


def test_sheet_number_comes_from_the_title_block(tmp_path):
    path = _sheet(tmp_path, "E2.1", refs=("E5.1", "E5.1", "E5.1"))
    (s,) = documents.detect_sheets(path)
    assert s.number == "E2.1"


def test_a_page_with_no_title_block_is_not_a_sheet(tmp_path):
    """No whole-page fallback: an architectural page that says SEE E-101
    three times is not an electrical sheet."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    for i in range(3):
        page.insert_text((200, 200 + i * 40), "SEE E-101")
    for i in range(600):
        page.draw_line((50 + (i % 40) * 15, 100 + (i // 40) * 12), (55 + (i % 40) * 15, 105 + (i // 40) * 12))
    path = tmp_path / "arch.pdf"
    doc.save(path)
    assert documents.detect_sheets(str(path)) == []


def test_rotated_page_reads_the_same(tmp_path):
    path = _sheet(tmp_path, "E-101", title_lines=("FIRST FLOOR", "POWER PLAN"), rotation=90)
    (s,) = documents.detect_sheets(path)
    assert s.number == "E-101"
    assert s.title == "First floor power plan"
    assert s.kind == "plan"
    assert (s.width_pt, s.height_pt) == (800, 1000)
    x0, y0, x1, y1 = s.region
    assert 0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1000
    # The title block is along the visual bottom on a 90-degree page.
    assert y1 < 1000 * 0.85


def test_region_excludes_the_located_strip_not_a_fixed_right_strip(tmp_path):
    path = _sheet(tmp_path, "E1.1")
    (s,) = documents.detect_sheets(path)
    x0, y0, x1, y1 = s.region
    assert x1 <= 1000 * (1 - 0.18) + 0.5  # right strip located and excluded
    assert y1 > 800 * 0.9                 # nothing taken off the bottom


def test_kind_from_the_title(tmp_path):
    path = _sheet(tmp_path, "E0.3", title_lines=("PANEL", "SCHEDULES"), scale=False)
    (s,) = documents.detect_sheets(path)
    assert s.kind == "schedule"
    assert s.title == "Panel schedules"


def test_title_falls_back_to_the_kind_label(tmp_path):
    path = _sheet(tmp_path, "E0.1", title_lines=("3909 ARCTIC BOULEVARD, SUITE 103",), scale=False)
    (s,) = documents.detect_sheets(path)
    assert s.title == "Electrical plan"
```

- [ ] **Step 2: Add the Unalaska assertions to `test_engine_pipeline.py`**

Append:

```python
def test_unalaska_sheet_numbers_are_distinct_and_deterministic():
    """14 pages, 14 numbers, identical across three processes with
    different hash seeds. The old code resolved page 89 to E7.1, E6.2
    and E4.1 on three consecutive runs."""
    import json, os, subprocess, sys

    code = (
        "import json,sys; sys.path.insert(0,'.');"
        "from app.engine import documents; from tests.bid_set import BID;"
        "print(json.dumps([(s.page_index,s.number,s.kind,s.title) for s in documents.detect_sheets(BID)]))"
    )
    runs = []
    for seed in ("0", "1", "2"):
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env={**os.environ, "PYTHONHASHSEED": seed}, check=True)
        runs.append(json.loads(out.stdout.strip().splitlines()[-1]))
    assert runs[0] == runs[1] == runs[2]
    numbers = [r[1] for r in runs[0]]
    assert len(numbers) == 14
    assert len(set(numbers)) == 14, sorted(numbers)


def test_unalaska_non_plans_contribute_no_devices():
    from app.engine import counting, documents

    sheets = {s.page_index: s for s in documents.detect_sheets(BID)}
    for page in (80, 81, 82, 83, 90, 91):
        assert sheets[page].kind != "plan", (page, sheets[page].kind, sheets[page].title)
        assert counting.count_sheet(BID, sheets[page]) == []
    assert sheets[80].legend, "the legend sheet must still feed classification"


def test_unalaska_plan_placements_are_in_range_and_in_frame():
    """Lower bound: what the mis-framed region left. Upper bound: the seal
    and the schedules stay out."""
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    plans = [s for s in sheets if s.kind == "plan"]
    total = 0
    for s in plans:
        for c in counting.count_sheet(BID, s):
            for p in c.placements:
                assert 0 <= p.x <= s.width_pt and 0 <= p.y <= s.height_pt, (s.number, p)
                total += 1
    assert 197 <= total <= 320, total


def test_a_placement_sits_on_its_glyph_in_the_rotated_render():
    """The marker test. Page 87 (rotation 90): take the first 'J' placement;
    the rendered rotated pixmap, clipped to a square around it, must
    contain a 'J' when the same square is read back as text."""
    import pymupdf
    from app.engine import counting, documents, page_frame

    sheets = {s.page_index: s for s in documents.detect_sheets(BID)}
    j = next(c for c in counting.count_sheet(BID, sheets[87]) if c.tag == "J")
    p = j.placements[0]
    page = pymupdf.open(BID)[87]
    assert page.rotation == 90
    square = pymupdf.Rect(p.x - 12, p.y - 12, p.x + 12, p.y + 12)
    assert "J" in page.get_textbox(page_frame.to_unrotated(square, page))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(4, 4), clip=square)
    ink = sum(1 for i in range(0, len(pix.samples), pix.n) if pix.samples[i] < 128)
    assert ink > 0, "the visual clip rendered blank"
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd api && …pytest tests/test_engine_documents.py tests/test_engine_pipeline.py -v -rs`
Expected: the new synthetic tests fail (`documents.RIGHT_STRIP` still referenced by the old fixture is gone, `kind` absent, region wrong); the Unalaska tests fail on distinct numbers / kinds.

- [ ] **Step 4: Rewrite `detect_sheets`**

In `documents.py`: delete `SHEET_ID`, `RIGHT_STRIP`, and `_sheet_number` entirely; keep `SCALE`, `BORDER`, `SCHEDULE_KEYWORDS`, `_is_raster`, `_scale`. Add imports:

```python
from . import sheet_kind, title_block
from .page_frame import visual_words
```

Replace `detect_sheets`:

```python
def detect_sheets(path: str) -> list[DetectedSheet]:
    doc = pymupdf.open(path)
    sheets: list[DetectedSheet] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        w, h = page.rect.width, page.rect.height  # visual frame
        text = page.get_text("text")
        words = visual_words(page)

        # An electrical sheet is a page whose own title-block number cell
        # holds a family token. No whole-page fallback: architectural
        # pages say "SEE E-101" and would otherwise be pulled in.
        tb = title_block.locate(words, w, h)
        number = title_block.sheet_number(tb) if tb else ""
        if not number:
            continue

        region = _region(w, h, tb.strip)
        if _is_raster(page):
            sheets.append(
                DetectedSheet(
                    page_index=pno, number=number, title="Electrical",
                    discipline="Electrical", scale="", width_pt=w, height_pt=h, region=region,
                    unreadable_reason="Scanned sheet — vector reading isn't available yet, so it was not counted.",
                )
            )
            continue
        if len(page.get_drawings()) < 500:
            continue  # a text-only page, not a drawing

        scale = _scale(text)
        raw_title = title_block.title(tb, number)
        kind = sheet_kind.classify(raw_title, text, bool(scale))
        sched = text if any(k in text.upper() for k in SCHEDULE_KEYWORDS) else ""
        sheets.append(
            DetectedSheet(
                page_index=pno, number=number, title=raw_title or sheet_kind.label(kind),
                discipline="Electrical", scale=scale, width_pt=w, height_pt=h,
                region=region, kind=kind, schedule_text=sched,
                legend=[replace(e, page_index=pno) for e in parse_legend(sched)],
            )
        )
    return sheets


def _region(w: float, h: float, strip: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """The visual page minus a border minus the located title-block
    strip. Replaces the old fixed right strip, which was built in the
    rotated frame and applied to unrotated text (spec 1.1)."""
    x0, y0, x1, y1 = w * BORDER, h * BORDER, w * (1 - BORDER), h * (1 - BORDER)
    sx0, sy0, sx1, sy1 = strip
    if sx0 > 0 and sx1 >= w:      # right strip
        x1 = min(x1, sx0)
    elif sx1 < w:                 # left strip
        x0 = max(x0, sx1)
    elif sy0 > 0:                 # bottom strip
        y1 = min(y1, sy0)
    else:                         # top strip
        y0 = max(y0, sy1)
    return (x0, y0, x1, y1)
```

Update the module docstring's second sentence to "…each sheet's number, title and kind from the title block, the drawing region device tags are counted within (the visual page less the located title-block strip)…". In `render_evidence_crop`'s docstring add: "`placements` and the page dimensions are in the visual frame, which is the frame `get_pixmap(clip=…)` takes — no transform here (page_frame.py)."

In `counting.py`, at the top of `count_sheet`:

```python
    if sheet.unreadable_reason or sheet.kind != "plan":
        return []  # only a plan carries devices; a schedule is read, not counted
```

- [ ] **Step 5: Run the engine suite**

Run: `cd api && …pytest tests/test_engine_documents.py tests/test_engine_counting.py tests/test_engine_legend.py tests/test_engine_pipeline.py tests/test_estimate_evidence.py -v -rs`
Expected: all pass with zero skips (the corpus is present). Two places may need attention, and both must be resolved by reading the PDF rather than by loosening an assertion:

- If `test_unalaska_non_plans_contribute_no_devices` fails on a page's kind, print `(page, title, kind)` for all 14, open that page in the PDF, and adjust `_TITLE_RULES` / the content markers in `sheet_kind.py` to what the title block actually says — then add the phrase to `test_sheet_kind.py`.
- If `test_unalaska_sheet_numbers_are_distinct_and_deterministic` fails on distinctness, print `(page, number)` for all 14 and read those pages' title blocks. A genuine duplicate is recorded in the Task 6 fixture as `"known_duplicate": true`; a wrong corner pick is fixed in `title_block.sheet_number`.

- [ ] **Step 6: Commit**

```bash
git add api/app/engine/documents.py api/app/engine/counting.py api/tests/test_engine_documents.py api/tests/test_engine_pipeline.py
git commit -m "Detect sheets from the title block, in the visual frame, with a kind

A page is an electrical sheet only when its own title-block number
cell holds a family token; there is no whole-page fallback. The
counting region is the visual page less the located strip, which on
Unalaska returns the right third of every sheet that the old fixed
strip silently excluded. Schedules, the legend and the one-line are
detected, titled and read, and contribute no devices.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Per-set fixtures across the five vector sets

**Files:**
- Create: `api/tests/fixtures/sheets/unalaska.json`, `kittles_saxony.json`, `pulte_sagebriar.json`, `tsc_nutrition.json`, `united_utility.json`
- Create: `api/tests/test_corpus_sheets.py`
- Modify: `api/tests/bid_set.py` (add `CORPUS` and the per-set paths)

**Interfaces:**
- Consumes: `documents.detect_sheets`, `counting.count_sheet`.
- Produces: the answer keys. Later plans assert against these files.

This is the task the user asked for by name: "test on all the bid examples." **The fixtures are written by opening each PDF and reading each title block**, not by running the engine. That is the whole point — the engine is checked against a person's reading, so a wrong engine cannot write its own answer key. Expect this task to surface title-block layouts the synthetic tests did not anticipate; fix `title_block.py` / `sheet_kind.py` for each and add a synthetic test that reproduces the layout.

- [ ] **Step 1: Extend `bid_set.py`**

```python
# append to api/tests/bid_set.py
CORPUS = os.environ.get(
    "BIDMATE_CORPUS",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bid_examples"),
)

# The electrical PDF of each vector set, keyed by fixture name.
VECTOR_SETS = {
    "unalaska": "Unalaska Bid/21_1001_unalaska_library_cd_biddrawings.pdf",
    "kittles_saxony": "Kittles Saxony/PLANS/Electrical Plans.pdf",
    "pulte_sagebriar": "Pulte Sagebriar Clubhouse/PLANS/20250124 - Sagebriar - Permit_Bid - Electrical.pdf",
    "tsc_nutrition": "TSC Nutrition & Technology Renovations/PLANS/2025-0604_Nutrition___Technology_100__CD_Set.pdf",
    "united_utility": "United Utility Supply/PLANS/0_DRAWING SET_UUS_BID DOCUMENTS_20260608_2.pdf",
}

# Raster sets: every detected page must carry unreadable_reason.
RASTER_SETS = {
    "fedex": "FedEx Office Bid/FedEx Office.pdf",
    "gerber": "Gerber Collision & Glass Bid/Renovation for Gerber Collision & Glass (1).pdf",
}


def corpus_path(rel: str) -> str:
    return os.path.join(CORPUS, rel)
```

Confirm each path exists with `ls` before committing — the Pulte and TSC filenames above were read from a directory listing on 2026-09-14 and may carry characters a shell mangles.

- [ ] **Step 2: Write the fixtures by hand**

For each vector set, open the PDF (any viewer; `python -c "import pymupdf; d=pymupdf.open(p); d[i].get_pixmap(matrix=pymupdf.Matrix(0.3,0.3)).save('/tmp/p.png')"` renders a page to look at). For every page that is an electrical sheet, record what its title block says. Fixture shape:

```json
{
  "pdf": "Unalaska Bid/21_1001_unalaska_library_cd_biddrawings.pdf",
  "sheets": [
    {"page_index": 80, "number": "E0.1", "kind": "legend", "rotation": 90},
    {"page_index": 81, "number": "E0.2", "kind": "schedule", "rotation": 90},
    {"page_index": 82, "number": "E0.3", "kind": "schedule", "rotation": 90}
  ]
}
```

Rules for writing them:
- `number` is exactly what the number cell prints, including hyphens.
- `kind` is your reading of the sheet: a floor plan with a scale is `plan`; a page of tables is `schedule`; symbols/abbreviations is `legend`; a one-line, riser, control or detail sheet is `diagram`; a cover or index is `other`. When you would hesitate, write `plan` and note why in a `"note"` field.
- A page whose title block you cannot read gets `"number": "", "note": "title block unreadable: <why>"` — the test then asserts it is *not* detected, which is the spec's rule, and the note is the backlog.
- Two pages that genuinely carry the same number get `"known_duplicate": true` on the second.
- `rotation` is `page.rotation`, recorded so a future frame regression is caught on every rotation the corpus has.

For the mixed-discipline sets (TSC Nutrition, 78 pages; United Utility, 66 pages) list only the electrical pages; the test asserts nothing else is detected.

- [ ] **Step 3: Write the corpus test**

```python
# api/tests/test_corpus_sheets.py
"""Every vector set in the corpus, against a hand-written answer key.

The fixture under tests/fixtures/sheets/ was written by reading each
title block, not by running the engine -- a wrong engine cannot write
its own key. Counting is tested, not trained (CLAUDE.md)."""

import json
import os
from pathlib import Path

import pymupdf
import pytest

from tests.bid_set import RASTER_SETS, VECTOR_SETS, corpus_path

FIXTURES = Path(__file__).parent / "fixtures" / "sheets"


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _skip_unless(rel):
    if not os.path.exists(corpus_path(rel)):
        pytest.skip(f"corpus set not present: {rel}")


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_detected_pages_match_the_key(name):
    from app.engine import documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    found = {s.page_index: s for s in documents.detect_sheets(corpus_path(fx["pdf"]))}
    expected = {s["page_index"]: s for s in fx["sheets"] if s["number"]}
    missed = sorted(set(expected) - set(found))
    extra = sorted(set(found) - set(expected))
    assert not missed, f"{name}: electrical pages not detected: {[(p, expected[p]['number']) for p in missed]}"
    assert not extra, f"{name}: non-electrical pages detected: {[(p, found[p].number) for p in extra]}"
    unreadable = [s["page_index"] for s in fx["sheets"] if not s["number"]]
    assert not (set(unreadable) & set(found)), f"{name}: pages the key marks unreadable were detected"


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_numbers_and_kinds_match_the_key(name):
    from app.engine import documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    found = {s.page_index: s for s in documents.detect_sheets(corpus_path(fx["pdf"]))}
    for s in fx["sheets"]:
        if not s["number"]:
            continue
        got = found[s["page_index"]]
        assert got.number == s["number"], (name, s["page_index"], got.number, s["number"])
        assert got.kind == s["kind"], (name, s["page_index"], got.title, got.kind, s["kind"])


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_numbers_are_distinct_unless_the_key_says_otherwise(name):
    from app.engine import documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    dups = {s["page_index"] for s in fx["sheets"] if s.get("known_duplicate")}
    numbers = [s.number for s in documents.detect_sheets(corpus_path(fx["pdf"])) if s.page_index not in dups]
    assert len(numbers) == len(set(numbers)), sorted(n for n in numbers if numbers.count(n) > 1)


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_every_placement_is_inside_its_visual_page(name):
    from app.engine import counting, documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    path = corpus_path(fx["pdf"])
    doc = pymupdf.open(path)
    for s in documents.detect_sheets(path):
        assert doc[s.page_index].rotation == next(f["rotation"] for f in fx["sheets"] if f["page_index"] == s.page_index)
        for c in counting.count_sheet(path, s):
            for p in c.placements:
                assert 0 <= p.x <= s.width_pt and 0 <= p.y <= s.height_pt, (name, s.number, p)


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_non_plans_carry_no_devices(name):
    from app.engine import counting, documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    path = corpus_path(fx["pdf"])
    for s in documents.detect_sheets(path):
        if s.kind != "plan":
            assert counting.count_sheet(path, s) == [], (name, s.number, s.kind)


@pytest.mark.parametrize("name", sorted(RASTER_SETS))
def test_raster_sets_are_unreadable_not_silent(name):
    from app.engine import counting, documents

    rel = RASTER_SETS[name]
    _skip_unless(rel)
    path = corpus_path(rel)
    sheets = documents.detect_sheets(path)
    for s in sheets:
        assert s.unreadable_reason, (name, s.page_index)
        assert counting.count_sheet(path, s) == []
```

- [ ] **Step 4: Run, and iterate against the key**

Run: `cd api && …pytest tests/test_corpus_sheets.py -v -rs`
Expected on the first run: failures on sets other than Unalaska, each naming a page. For each failure, open that page. The fix goes in `title_block.py` or `sheet_kind.py` **with a synthetic test in `test_title_block.py` / `test_sheet_kind.py` that reproduces the layout** — never in the fixture, unless the fixture was misread, in which case say so in the commit message.

Known shapes to expect from the 2026-09-14 survey: Kittles and United Utility use `E-101`-style numbers with `EL`/`EP`/`EF` discipline prefixes; TSC Nutrition mixes 0°/90°/270° pages in one file and its title block edge may differ by rotation; Pulte uses `EX1`–`EX10` for existing-conditions sheets, which are still electrical sheets.

Raster sets: if `detect_sheets` returns zero pages for FedEx or Gerber, that is a regression against the spec (they must be detected *and* unreadable). Their pages have no text, so `title_block.locate` returns `None`. Handle it in `detect_sheets`: when `_is_raster(page)` and no title block is found, still emit the sheet with `number=""`, `title="Scanned sheet"`, `kind="other"` and the existing unreadable reason — silence must not read as completeness. Add that branch before the `if not number: continue`.

- [ ] **Step 5: Run the whole backend suite**

Run: `cd api && TEST_DATABASE_URL=… …pytest -q -rs`
Expected: green, zero skips.

- [ ] **Step 6: Commit**

```bash
git add api/tests/bid_set.py api/tests/fixtures/sheets api/tests/test_corpus_sheets.py api/app/engine api/tests
git commit -m "Test the Documents agent against every vector set in the corpus

Five hand-written answer keys -- one per vector set, read from the
title blocks, never from the engine -- and a parametrised test that
asserts detected pages, numbers, kinds, distinctness, frame bounds and
the no-devices-on-a-schedule rule on each. Raster sets are asserted
detected-and-unreadable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: `Sheet.kind` through the store

**Files:**
- Modify: `api/app/takeoff/models.py:117-146` (`Sheet`)
- Create: `api/migrations/versions/0018_sheet_kind.py`
- Modify: `api/app/takeoff/schemas.py:114-136` (`SheetOut`), `api/app/takeoff/snapshot.py:80-97` (`sheet_out`), `api/app/takeoff/ingest.py:284-303` (`map_payload`), `api/app/takeoff/ingest_service.py:75-83`, `api/app/takeoff/reprocess.py:262-270`, `api/app/engine/estimate.py:385-407` (`full_takeoff`)
- Test: `api/tests/test_ingest_mapping.py` (find the existing ingest test module with `grep -ln "map_payload" api/tests/*.py` and add there), `api/tests/test_engine_pipeline.py`

**Interfaces:**
- Produces: `Sheet.kind: str` (`String(20)`, default `"plan"`); `SheetOut.kind: str = "plan"`; `full_takeoff()["sheets"][i]` carries `kind`, `title`, `scale`; `map_payload` validates `kind` against `sheet_kind.KINDS`, unknown → `"plan"` with a `log.warning`.

- [ ] **Step 1: Write the failing tests**

In the ingest mapping test module:

```python
def test_sheet_kind_is_mapped_and_validated(caplog):
    from app.takeoff.ingest import map_payload

    mapped = map_payload({"sheets": [
        {"id": "80", "number": "E0.1", "kind": "legend", "title": "Electrical legend", "scale": "", "page": 81, "width_pt": 2448, "height_pt": 1584},
        {"id": "87", "number": "E2.1", "kind": "plan", "title": "First floor plan", "scale": '1/8" = 1', "page": 88, "width_pt": 2448, "height_pt": 1584},
        {"id": "99", "number": "E9.9", "kind": "banana", "page": 100, "width_pt": 1, "height_pt": 1},
    ], "items": []})
    kinds = [s["kind"] for s in mapped.sheets]
    assert kinds == ["legend", "plan", "plan"]
    assert mapped.sheets[0]["title"] == "Electrical legend"
    assert mapped.sheets[1]["scale"] == '1/8" = 1'
    assert "banana" in caplog.text


def test_sheet_kind_defaults_to_plan_when_absent():
    from app.takeoff.ingest import map_payload

    mapped = map_payload({"sheets": [{"id": "1", "number": "E1.1", "page": 2, "width_pt": 1, "height_pt": 1}], "items": []})
    assert mapped.sheets[0]["kind"] == "plan"
```

In `test_engine_pipeline.py`:

```python
def test_full_takeoff_emits_kind_title_and_scale_per_sheet():
    from app.engine import estimate

    out = estimate.full_takeoff(BID, "Unalaska, AK")
    by_number = {s["number"]: s for s in out["sheets"]}
    assert by_number["E0.3"]["kind"] == "schedule"
    assert by_number["E0.3"]["title"]            # not empty, whatever the cell says
    assert {s["kind"] for s in out["sheets"]} <= {"plan", "schedule", "legend", "diagram", "other"}
    assert any(s["scale"] for s in out["sheets"] if s["kind"] == "plan")
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && …pytest tests/<ingest module> tests/test_engine_pipeline.py::test_full_takeoff_emits_kind_title_and_scale_per_sheet -v`
Expected: FAIL — `KeyError: 'kind'` / `mapped.sheets[0]["kind"]` absent.

- [ ] **Step 3: Model, migration, schema, snapshot**

`models.py`, after `unreadable_reason`:

```python
    # What the sheet is (sheet_kind.KINDS): plan, schedule, legend,
    # diagram, other. A schedule is read and shown; only a plan carries
    # counted items. Its own axis -- never one of the four review labels.
    kind: Mapped[str] = mapped_column(String(20), default="plan", server_default="plan")
```

Migration:

```python
# api/migrations/versions/0018_sheet_kind.py
"""sheet kind

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-14 00:00:00.000000

Adds sheets.kind -- plan / schedule / legend / diagram / other -- so a
panel schedule stays visible in the sheet rail, labelled, without
contributing counted items. Defaulted to 'plan', which is what every
existing row was implicitly treated as, so no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0018'
down_revision: Union[str, None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sheets', sa.Column('kind', sa.String(length=20), nullable=False, server_default='plan'))


def downgrade() -> None:
    op.drop_column('sheets', 'kind')
```

`schemas.py` `SheetOut`, after `unreadable_reason`:

```python
    # plan | schedule | legend | diagram | other. A sheet property on its
    # own axis; the rail labels non-plans with it.
    kind: str = "plan"
```

`snapshot.py` `sheet_out`: add `kind=sheet.kind,`. `ingest_service.py` and `reprocess.py` `Sheet(...)` constructors: add `kind=row["kind"],`.

- [ ] **Step 4: Ingest and emit**

`ingest.py` `map_payload`, in the sheet dict after `"unreadable_reason"`:

```python
            "kind": _sheet_kind(raw.get("kind"), key),
```

and add near the top (with the other helpers, importing `from app.engine.sheet_kind import KINDS` and `log = logging.getLogger(__name__)` if the module has no logger yet):

```python
def _sheet_kind(raw, key: str) -> str:
    """The engine's kind, validated against the closed set. An unknown
    value becomes 'plan' -- the visible failure -- and is logged by sheet
    key, never by content."""
    kind = str(raw or "plan")
    if kind not in KINDS:
        log.warning("ingest: sheet %s carried unknown kind %r; treating as plan", key, kind)
        return "plan"
    return kind
```

`estimate.py` `full_takeoff` sheet dict, add:

```python
                "title": s.title,
                "scale": s.scale,
                "kind": s.kind,
```

- [ ] **Step 5: Migrate, run tests both ways**

Run:
```
cd api && DATABASE_URL=postgresql+psycopg://takeoff:takeoff@localhost:5432/takeoff …alembic upgrade head
… alembic downgrade -1 && … alembic upgrade head
TEST_DATABASE_URL=… …pytest -q -rs
```
Expected: `0018 (head)`, the reversal clean, suite green.

- [ ] **Step 6: Commit**

```bash
git add api/app api/migrations/versions/0018_sheet_kind.py api/tests
git commit -m "Carry sheet kind, title and scale from the engine into the store

full_takeoff never emitted title or scale, which is why every stored
sheet read 'Electrical plan' regardless of what the title block said.
kind is validated at ingest against the closed set; unknown values
become plan and are logged by sheet key.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The rail shows what a non-plan sheet is

**Files:**
- Modify: `src/lib/store/api-mapping.js:73-97` (`mapSheet`)
- Modify: `src/components/SheetsRail.jsx:66-74` (badges)
- Create: `src/components/SheetsRail.test.jsx`
- Test: `src/lib/store/api-mapping.test.js` if it exists (`ls src/lib/store/*.test.js`), else add the `mapSheet` assertion to the new rail test

**Interfaces:**
- Consumes: `SheetOut.kind`.
- Produces: `sheet.kind` in the store; a `badge` reading `Schedule` / `Legend` / `Diagram` / `Sheet` on non-plan rows.

- [ ] **Step 1: Write the failing test**

```jsx
// src/components/SheetsRail.test.jsx
import { describe, expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SheetsRail from "./SheetsRail.jsx";
import { mapSheet } from "../lib/store/api-mapping.js";

const base = { discipline: "Electrical", revision: "A", scale: "", plan: "", superseded: false };

function rail(sheets) {
  return render(
    <SheetsRail sheets={sheets} items={[]} sheetId={null} onSelectSheet={vi.fn()}
      filter="all" onFilter={vi.fn()} query="" onQuery={vi.fn()} open onToggleOpen={vi.fn()} />
  );
}

describe("SheetsRail sheet kind", () => {
  test("a schedule sheet is labelled, a plan is not", () => {
    rail([
      { ...base, id: "s1", number: "E0.3", title: "Panel schedules", kind: "schedule" },
      { ...base, id: "s2", number: "E2.1", title: "First floor plan", kind: "plan" },
    ]);
    expect(screen.getByText("Schedule")).toBeInTheDocument();
    expect(screen.queryByText("Electrical plan")).not.toBeInTheDocument();
  });

  test("the kind badge is not a status pill", () => {
    rail([{ ...base, id: "s1", number: "E0.1", title: "Legend", kind: "legend" }]);
    const badge = screen.getByText("Legend", { selector: ".badge" });
    expect(badge.className).not.toMatch(/pill|status|attention|approved|missing|ready/);
  });

  test("mapSheet carries kind and defaults it to plan", () => {
    expect(mapSheet({ id: "x", number: "E1", title: "t", kind: "diagram" }).kind).toBe("diagram");
    expect(mapSheet({ id: "x", number: "E1", title: "t" }).kind).toBe("plan");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- --run src/components/SheetsRail.test.jsx`
Expected: FAIL — `Unable to find an element with the text: Schedule`.

- [ ] **Step 3: Implement**

`api-mapping.js` `mapSheet`, after `unreadableReason`:

```js
    // plan | schedule | legend | diagram | other. The rail labels a
    // non-plan with it. A sheet property on its own axis -- never one of
    // the four review labels, never rendered with a status component.
    kind: s.kind ?? "plan",
```

`SheetsRail.jsx`: add above the component

```jsx
// Sentence-case labels for a sheet that is not a device plan. Plans get
// no badge: the rail is mostly plans and the label would be noise.
const KIND_LABEL = { schedule: "Schedule", legend: "Legend", diagram: "Diagram", other: "Sheet" };
```

and in the badges span, before the revision badge:

```jsx
                      {KIND_LABEL[s.kind] && <span className="badge">{KIND_LABEL[s.kind]}</span>}
```

- [ ] **Step 4: Run tests and build**

Run: `npm test -- --run && npm run build`
Expected: green (267 tests or thereabouts — 266 plus these), build clean.

- [ ] **Step 5: Commit**

```bash
git add src/lib/store/api-mapping.js src/components/SheetsRail.jsx src/components/SheetsRail.test.jsx
git commit -m "Label a non-plan sheet in the rail

E0.3 reads 'E0.3 · Panel schedules · Schedule' instead of 'Electrical
plan'. A plain badge, not a status pill: kind is its own axis and the
four review labels stay four.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** §1.1 frame → Tasks 1, 2, 5. §1.2 kind → Tasks 4, 5. §1.3 title → Tasks 4, 5, 7 (emit). §1.4 conventions → Task 3 (`SHEET_ID`), Task 6 (proved on each set). §2.1 → 1, 2, 5 (evidence crop docstring). §2.2 → 3, 5 (`_region`). §2.3 → 3, 5 (determinism test). §2.4 → 4, 5 (gate). §2.5 → 3, 5. §2.6 → 4. §2.7 → 7, 8. §2.8 raster → 6 (raster branch + test). §3.1 → 6. §3.2 → 5. §3.3 → 2, 5 (glyph test), 6 (bounds). §3.4 → 5, 6. §3.5 → 2 (seal windows), 5.

**Placeholders.** `title()` in Task 3 returns `""` with "Filled in by Task 4" — it is replaced in Task 4 Step 3, which carries the full body. No other stubs.

**Type consistency.** `page_frame.Word(x0,y0,x1,y1,text,block,line)` used in Tasks 2, 3, 4. `title_block.locate(words, width, height) -> TitleBlock | None`, `sheet_number(tb) -> str`, `title(tb, number) -> str` used in Task 5 as written. `sheet_kind.classify(title, page_text, has_scale)` and `label(kind)` used in Task 5 as written. `DetectedSheet.kind` (Task 4) read in Tasks 5–7. `Sheet.kind` / `SheetOut.kind` / `sheet.kind` (Tasks 7–8) match.

**One thing the plan leaves for the fix loop on purpose.** Task 6 will meet title-block layouts the synthetic tests did not anticipate — that is what the corpus is for. The rule is fixed: every such fix lands with a synthetic test reproducing the layout, and the fixture is never edited to match the engine.
