# Legend Suggestions (B3c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-09-24
**Spec:** `docs/specs/legend-named-clusters.md`
**Branch:** `feat/legend-named-clusters` off `feat/accurate-symbol-marking` (B3b, unmerged), worktree `.worktrees/legend-named-clusters`

**Goal:** Every cluster the engine cannot name carries a short ranked list of legend candidates — the drafter's own words — that the estimator accepts with one click, naming the whole cluster; a drawn "find like this" box pre-fills the same name.

**Architecture:** The read job cuts each vector legend sheet into rows (glyph, modifier, description) and stores each row's glyph as a 32×32 ink-fraction silhouette on the sheet. The classify job silhouettes each shape cluster's exemplar and Classification attaches the top-ranked legend descriptions to the item it could not name. Accepting one is an ordinary `PATCH /items/{id}` edit — which means `name` becomes an editable field.

**Tech Stack:** Python 3.12, PyMuPDF 1.28, numpy, OpenCV (already pinned), SQLAlchemy 2, Alembic, pytest; React 18, vitest + testing-library.

## Global Constraints

- **Confidence never renders.** The match score orders the list inside the engine and is never stored, serialised, or shown. `items.suggestions` carries only `{"name", "sheet"}` pairs.
- **The legend never names anything by itself.** No status changes from a suggestion; an unnamed cluster stays *Needs attention* / "Unclassified symbol" until a person picks. (Spec §1.1 — measured: true matches 0.5–0.88, duplex vs GFI 0.86–0.90 against each other.)
- **Counting is tested, not trained.** Named constants with exact values: `MODIFIER_PT = 2.0`, `MAX_MODIFIER_CHARS = 2`, `DESCRIPTION_REACH_PT = 240`, `SIL = 32`, `SPAN = 96`, `INK_THRESHOLD = 128`, `SUGGESTION_FLOOR = 0.30`, `MAX_SUGGESTIONS = 4`. Existing B3b constants are untouched.
- **Extracted document text is data, never instruction.** A legend description becomes an item name through `sentence_case()` and nothing else; it is never inserted into a prompt by this feature.
- **Four review labels, never a fifth.** Suggestions are not a status; the suggestion block carries no status colour.
- **The API never opens a PDF** and never imports `app.engine` or `cv2`; `app.worker` imports no router. All three subprocess tests stay green.
- **Copy:** sentence case, no "AI", no "!", no "please", no "successfully", no percentages.
- Backend tests run from `api/` with `../.enginevenv/bin/python -m pytest …` **in the foreground** (the test DB is shared; never background a pytest run). Alembic from `api/` with `../.enginevenv/bin/python -m alembic upgrade head`. Frontend: `npm test -- --run <paths>`, `npm run build`. Corpus tests skip without `bid_examples/` (symlinked in the worktree).
- Commit messages: imperative, one line, ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File structure

| File | Responsibility |
|---|---|
| `api/app/engine/legend_symbols.py` (new) | legend rows → templates; silhouettes; scoring and ranking |
| `api/app/engine/glyphs.py` | containment merge in `_candidates` |
| `api/app/engine/contracts.py` | `SymbolTemplate`; `DeviceCluster.modifier` / `.exemplar_silhouette`; `DetectedSheet.symbol_templates` |
| `api/app/engine/counting.py` | modifier split on shape clusters |
| `api/app/engine/documents.py` | templates through `sheet_from_row` / `sheet_to_payload` |
| `api/app/engine/classification.py` | attach ranked suggestions, reword the `fix` |
| `api/app/worker/read_job.py` | store templates on the legend sheet |
| `api/app/worker/classify_job.py` | silhouette each exemplar, pass templates |
| `api/app/worker/match_job.py` | `suggested_name` for a drawn box |
| `api/app/takeoff/{models,ingest,schemas,snapshot,mutations,edit_validation}.py` | the two columns, the wire, `name` editable |
| `api/migrations/versions/0024_symbol_templates.py` (new) | the migration |
| `api/app/matches/{schemas,router}.py` | `suggested_name` on the wire |
| `src/lib/store/api.js`, `api-mapping.js` | `suggestions`, `suggestedName`, `name` editable |
| `src/components/ItemDetailPanel.jsx`, `MatchResultCard.jsx` | the suggestion block, the pre-filled name |

---

### Task 1: Schema — templates, suggestions, suggested name

**Files:**
- Create: `api/migrations/versions/0024_symbol_templates.py`
- Modify: `api/app/takeoff/models.py` (`Sheet`, `Item`, `SymbolMatch`)
- Test: `api/tests/test_migration_0024.py`, `api/tests/test_takeoff_models.py`

**Interfaces:**
- Produces: `Sheet.symbol_templates: Mapped[list | None]` (JSONB), `Item.suggestions: Mapped[list | None]` (JSONB), `SymbolMatch.suggested_name: Mapped[str]` (String(300), default `""`).

- [ ] **Step 1: Write the failing tests**

`api/tests/test_migration_0024.py` — mirror `api/tests/test_migration_0023.py` exactly (read it first for the `MigrationContext`/`Operations` pattern): a source-order test is not needed here (no constraint to recreate), so write one real-SQL test that inserts a sheet with `symbol_templates`, an item with `suggestions` and a symbol match with `suggested_name`, runs `downgrade()`, asserts the three columns are gone (`information_schema.columns` returns no rows for them), then `upgrade()` again and asserts they are back.

Append to `api/tests/test_takeoff_models.py`:

```python
def test_sheet_item_and_match_carry_the_legend_columns(db, project, sheet, dana):
    from app.takeoff.models import Item, SymbolMatch
    sheet.symbol_templates = [{"description": "DUPLEX RECEPTACLE", "modifier": "", "rect": [0, 0, 10, 10],
                               "silhouette": "AAAA", "sheet_number": "E0.1"}]
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="generic", name="Unclassified symbol",
                system="Unknown", category="Unclassified", quantity=3, unit="ea",
                suggestions=[{"name": "Duplex receptacle", "sheet": "E0.1"}])
    match = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id,
                        box=[500, 375, 12, 12], created_by=dana.id)
    db.add_all([item, match]); db.flush(); db.refresh(sheet); db.refresh(item); db.refresh(match)
    assert sheet.symbol_templates[0]["description"] == "DUPLEX RECEPTACLE"
    assert item.suggestions == [{"name": "Duplex receptacle", "sheet": "E0.1"}]
    assert match.suggested_name == ""
```

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_migration_0024.py tests/test_takeoff_models.py -q`
Expected: FAIL — no such attribute / no such column.

- [ ] **Step 3: Implement**

`api/app/takeoff/models.py` — on `Sheet`, beside the render columns:

```python
    # B3c: the legend rows this sheet carries, when it is a legend sheet --
    # each a glyph's silhouette plus the drafter's own words for it. Read
    # once at upload; Classification ranks against them.
    symbol_templates: Mapped[list | None] = mapped_column(JSONB, nullable=True)
```

on `Item`, beside `source_tag`:

```python
    # B3c: legend rows this item's symbol looks like, best first, for an
    # estimator to pick from. Names only -- the score that ordered them
    # stops in the engine (CLAUDE.md: confidence never renders).
    suggestions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
```

on `SymbolMatch`, beside `error`:

```python
    suggested_name: Mapped[str] = mapped_column(String(300), default="", server_default="")
```

Migration `0024_symbol_templates.py` (revision `'0024'`, down `'0023'`): `op.add_column` for the three, `op.drop_column` in reverse order on downgrade. Docstring in the style of 0023.

- [ ] **Step 4: Migrate and run**

Run: `cd api && ../.enginevenv/bin/python -m alembic upgrade head && ../.enginevenv/bin/python -m pytest tests/test_migration_0024.py tests/test_migration_0023.py tests/test_takeoff_models.py tests/test_worker_import_boundary.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/migrations/versions/0024_symbol_templates.py api/app/takeoff/models.py api/tests/test_migration_0024.py api/tests/test_takeoff_models.py
git commit -m "Add the legend template, suggestion and suggested-name columns"
```

---

### Task 2: The containment merge in `glyphs.py`

**Files:**
- Modify: `api/app/engine/glyphs.py` (`_candidates`)
- Test: `api/tests/test_engine_glyphs.py`, `api/tests/test_corpus_sheets.py`

**Interfaces:**
- Produces: `_candidates` also joins a candidate whose bbox centre lies inside another candidate's bbox (both sides ≤ `MAX_GLYPH_PT`), so a square-plus-inner-circle is one glyph. No new constant.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_engine_glyphs.py`:

```python
def test_a_symbol_drawn_as_a_box_around_a_circle_is_one_glyph(page):
    s = page.new_shape(); s.draw_rect(pymupdf.Rect(100, 100, 118, 118)); s.finish(color=(0, 0, 0), width=0.7); s.commit()
    s = page.new_shape(); s.draw_circle((109, 109), 5); s.finish(color=(0, 0, 0), width=0.7); s.commit()
    g = glyphs.glyphs_on(page, _region(), visual_words(page))
    assert len(g) == 1
    x0, y0, x1, y1 = g[0].rect
    assert x1 - x0 >= 17 and y1 - y0 >= 17


def test_containment_never_swallows_a_neighbour(page):
    s = page.new_shape(); s.draw_rect(pymupdf.Rect(100, 100, 118, 118)); s.finish(color=(0, 0, 0), width=0.7); s.commit()
    s = page.new_shape(); s.draw_circle((140, 109), 5); s.finish(color=(0, 0, 0), width=0.7); s.commit()
    assert len(glyphs.glyphs_on(page, _region(), visual_words(page))) == 2
```

- [ ] **Step 2: Run, expect the first to fail**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_glyphs.py -q`
Expected: `test_a_symbol_drawn_as_a_box_around_a_circle_is_one_glyph` FAILS (2 glyphs), the second passes.

- [ ] **Step 3: Implement**

In `_candidates`, after the existing pairwise touch loop and before the `groups` assembly, add a second pass over the grouped candidates:

```python
    # A symbol drawn as an outline around an inner mark -- a recessed
    # fixture's square around its circle -- is two candidates that never
    # touch: the inner one floats inside the outer one's bbox with a gap
    # on every side. Join a candidate whose own centre lies inside
    # another's box, both still glyph-sized, so the same symbol is one
    # candidate on the legend sheet and on the plan alike. Containment is
    # one-directional (the inner is inside the outer), so this can only
    # ever join parts of one symbol, never two neighbours.
    roots = defaultdict(list)
    for i in range(n):
        if i not in dense:
            roots[find(i)].append(i)
    boxes = {r: _bbox([paths[i] for i in members]) for r, members in roots.items()}
    for a, ba in boxes.items():
        for b, bb in boxes.items():
            if a == b or find(a) == find(b):
                continue
            cx, cy = (ba[0] + ba[2]) / 2, (ba[1] + ba[3]) / 2
            if not (bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]):
                continue
            if max(bb[2] - bb[0], bb[3] - bb[1]) > MAX_GLYPH_PT:
                continue
            parent[find(a)] = find(b)
```

- [ ] **Step 4: Run, including the corpus**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_glyphs.py tests/test_engine_counting.py tests/test_corpus_sheets.py -q`
Expected: all pass. The corpus floors are cluster and placement **minimums**; the merge can only reduce cluster counts by joining parts, so if a floor now fails, report the numbers — do not lower a floor.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/glyphs.py api/tests/test_engine_glyphs.py
git commit -m "Group an outline and the mark inside it as one glyph"
```

---

### Task 3: Legend rows — `engine/legend_symbols.py`

**Files:**
- Create: `api/app/engine/legend_symbols.py`
- Modify: `api/app/engine/contracts.py` (`SymbolTemplate`)
- Test: `api/tests/test_engine_legend_symbols.py`

**Interfaces:**
- Produces:
  ```python
  MODIFIER_PT = 2.0; MAX_MODIFIER_CHARS = 2; DESCRIPTION_REACH_PT = 240
  SIL = 32; SPAN = 96; INK_THRESHOLD = 128
  def silhouette(page, rect) -> bytes                      # SIL*SIL ink fractions, one byte each
  def templates_on(page, words, sheet_number="") -> list[SymbolTemplate]
  def sentence_case(text: str) -> str
  ```
  `SymbolTemplate(description, modifier, rect, silhouette, sheet_number)` in `contracts.py`.

- [ ] **Step 1: Write the failing tests**

`api/tests/test_engine_legend_symbols.py`:

```python
"""Legend rows and silhouettes (B3c spec §3). The legend is the only
labelled data a drawing set ships with; this reads it."""
import pymupdf
import pytest

from app.engine import legend_symbols as ls
from app.engine.page_frame import visual_words
from tests.test_engine_glyphs import _receptacle


def _row(page, y, draw, text, modifier=""):
    draw(page, 120, y)
    if modifier:
        page.insert_text((132, y + 3), modifier, fontsize=5)
    page.insert_text((150, y + 3), text, fontsize=7)


@pytest.fixture
def legend():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    _row(page, 60, lambda p, x, y: _receptacle(p, x, y), "DUPLEX RECEPTACLE")
    _row(page, 100, lambda p, x, y: (_receptacle(p, x, y), p.draw_line((x - 6, y + 6), (x + 6, y - 6))), "GROUND FAULT RECEPTACLE")
    def money(p, x, y):
        s = p.new_shape(); s.draw_line((x, y - 6), (x, y + 6)); s.draw_circle((x, y - 2), 3); s.draw_circle((x, y + 2), 3)
        s.finish(color=(0, 0, 0), width=0.7); s.commit()
    _row(page, 140, money, "SINGLE POLE SWITCH")
    _row(page, 180, money, "THREE-WAY SWITCH", modifier="3")
    def boxed(p, x, y):
        s = p.new_shape(); s.draw_rect(pymupdf.Rect(x - 9, y - 9, x + 9, y + 9)); s.finish(color=(0, 0, 0), width=0.7); s.commit()
        s = p.new_shape(); s.draw_circle((x, y), 5); s.finish(color=(0, 0, 0), width=0.7); s.commit()
    _row(page, 220, boxed, "RECESSED LIGHTING FIXTURE")
    s = page.new_shape(); s.draw_line((120, 300), (180, 300)); s.finish(color=(0, 0, 0), width=0.7); s.commit()  # no text
    return page


def test_every_legend_row_becomes_a_template(legend):
    t = ls.templates_on(legend, visual_words(legend), sheet_number="E0.1")
    assert len(t) == 5
    assert [x.description for x in t][0] == "DUPLEX RECEPTACLE"
    assert all(x.sheet_number == "E0.1" for x in t)


def test_a_touching_subscript_is_the_modifier(legend):
    t = {x.description: x for x in ls.templates_on(legend, visual_words(legend))}
    assert t["THREE-WAY SWITCH"].modifier == "3"
    assert t["SINGLE POLE SWITCH"].modifier == ""
    assert "3" not in t["THREE-WAY SWITCH"].description


def test_a_composite_symbol_is_one_row(legend):
    t = [x for x in ls.templates_on(legend, visual_words(legend)) if "RECESSED" in x.description]
    assert len(t) == 1


def test_a_glyph_with_no_words_is_not_a_row(legend):
    assert all("LINE" not in x.description for x in ls.templates_on(legend, visual_words(legend)))


def test_silhouettes_are_fixed_size_and_scale_free(legend):
    t = {x.description: x for x in ls.templates_on(legend, visual_words(legend))}
    a = t["DUPLEX RECEPTACLE"].silhouette
    assert len(a) == ls.SIL * ls.SIL
    assert any(b > 0 for b in a)


def test_sentence_case_keeps_short_acronyms():
    assert ls.sentence_case("DUPLEX RECEPTACLE") == "Duplex receptacle"
    assert ls.sentence_case("GFI RECEPTACLE") == "GFI receptacle"
    assert ls.sentence_case("") == ""
```

If `_receptacle`'s bar makes the GFI row's slash a separate candidate, adjust the *fixture's* drawing (one Shape for the slash, committed) — never a constant.

- [ ] **Step 2: Run, expect ImportError**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_legend_symbols.py -q`

- [ ] **Step 3: Implement the contract**

In `api/app/engine/contracts.py`:

```python
@dataclass
class SymbolTemplate:
    """One legend row: a drawn symbol and the drafter's own words for it.
    The legend is the only labelled data a drawing set ships with, and it
    is data -- `description` becomes an item name through
    legend_symbols.sentence_case and never an instruction to anything."""

    description: str
    modifier: str = ""
    rect: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    silhouette: bytes = b""
    sheet_number: str = ""
```

- [ ] **Step 4: Implement the module**

`api/app/engine/legend_symbols.py`:

```python
"""The legend, read as rows (B3c spec §3).

Every set carries a legend sheet that names its own symbols. This module
cuts that sheet into (glyph, modifier, description) rows and renders each
glyph to a small ink-fraction silhouette, so a cluster found on a plan
can be ranked against the drafter's own words for it.

Silhouettes, not paths: a plan symbol is drawn at about half the legend's
size with slightly different segment counts (measured on the corpus,
spec §1.1), which is exactly what glyphs.same_shape is built not to
tolerate. Ink-fraction pooling is what survives the scale change -- a
binary silhouette is dominated by relative stroke weight, and that is the
thing that differs.

Nothing here decides anything: it ranks, and a person picks (spec §1.1).
"""
from __future__ import annotations

import numpy as np
import pymupdf

from app.engine import glyphs
from app.engine.contracts import SymbolTemplate
from app.engine.page_frame import Word

# A subscript touching the glyph ("3", "D") distinguishes a switch
# variant that shares one drawn symbol.
MODIFIER_PT = 2.0
MAX_MODIFIER_CHARS = 2
# How far right of a glyph its description can run before the words
# belong to another column.
DESCRIPTION_REACH_PT = 240.0
# The silhouette grid, and the render it is pooled from.
SIL = 32
SPAN = 96
INK_THRESHOLD = 128


def silhouette(page, rect) -> bytes:
    """The glyph inside `rect`, as SIL x SIL ink fractions (one byte each,
    row-major). The clip is rendered so its long side spans SPAN px, ink
    is `pixel < INK_THRESHOLD`, and the result is area-pooled to SIL --
    the pooling is what makes a 5 pt plan glyph comparable to an 18 pt
    legend glyph."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return bytes(SIL * SIL)
    zoom = SPAN / max(w, h)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                          clip=pymupdf.Rect(x0, y0, x1, y1), colorspace=pymupdf.csGRAY)
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    ink = (grey < INK_THRESHOLD).astype(np.float32)[:SPAN, :SPAN]
    square = np.zeros((SPAN, SPAN), dtype=np.float32)
    oy, ox = (SPAN - ink.shape[0]) // 2, (SPAN - ink.shape[1]) // 2
    square[oy:oy + ink.shape[0], ox:ox + ink.shape[1]] = ink
    cell = SPAN // SIL
    pooled = square.reshape(SIL, cell, SIL, cell).mean(axis=(1, 3))
    return bytes(np.clip(pooled * 255.0, 0, 255).astype(np.uint8).ravel())


def _near(rect, word: Word, gap: float) -> bool:
    x0, y0, x1, y1 = rect
    return word.x0 <= x1 + gap and word.x1 >= x0 - gap and word.y0 <= y1 + gap and word.y1 >= y0 - gap


def sentence_case(text: str) -> str:
    """Legend words as an item name. An acronym of four letters or fewer
    keeps its case ("GFI", "NEMA"); everything else reads as a sentence."""
    words = (text or "").split()
    out = []
    for i, w in enumerate(words):
        if w.isupper() and len(w) <= 4 and any(c.isalpha() for c in w):
            out.append(w)
        elif i == 0:
            out.append(w.capitalize())
        else:
            out.append(w.lower())
    return " ".join(out)


def templates_on(page, words: list[Word], sheet_number: str = "") -> list[SymbolTemplate]:
    """Every legend row on this page, in reading order. A glyph with no
    description beside it is a stray drawing, not a row."""
    found = glyphs.glyphs_on(page, (0, 0, page.rect.width, page.rect.height), words)
    found.sort(key=lambda g: (round(g.rect[1]), g.rect[0]))
    out: list[SymbolTemplate] = []
    for g in found:
        x0, y0, x1, y1 = g.rect
        cy, height = (y0 + y1) / 2, y1 - y0
        band = [w for w in words if abs(w.cy - cy) <= max(height, 6.0)]
        modifier = ""
        for w in band:
            text = w.text.strip()
            if len(text) <= MAX_MODIFIER_CHARS and text and _near(g.rect, w, MODIFIER_PT):
                modifier = text
                break
        right = [w for w in band if w.x0 >= x1 - 1 and w.x0 <= x1 + DESCRIPTION_REACH_PT
                 and w.text.strip() != modifier]
        right.sort(key=lambda w: (round(w.cy), w.x0))
        description = " ".join(w.text.strip() for w in right if w.text.strip())
        if not description:
            continue
        out.append(SymbolTemplate(description=description, modifier=modifier, rect=g.rect,
                                  silhouette=silhouette(page, g.rect), sheet_number=sheet_number))
    return out
```

- [ ] **Step 5: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_legend_symbols.py tests/test_engine_contracts.py -q`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add api/app/engine/legend_symbols.py api/app/engine/contracts.py api/tests/test_engine_legend_symbols.py
git commit -m "Read a legend sheet as rows of glyph, modifier and description"
```

---

### Task 4: Ranking

**Files:**
- Modify: `api/app/engine/legend_symbols.py`
- Test: `api/tests/test_engine_legend_symbols.py`

**Interfaces:**
- Produces: `SUGGESTION_FLOOR = 0.30`, `MAX_SUGGESTIONS = 4`; `match_score(a: bytes, b: bytes) -> float`; `rank_templates(sil: bytes, modifier: str, templates: list[SymbolTemplate], limit: int = MAX_SUGGESTIONS) -> list[SymbolTemplate]`.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_engine_legend_symbols.py`:

```python
def _sil_of(page, description, words=None):
    t = {x.description: x for x in ls.templates_on(page, words or visual_words(page))}
    return t[description].silhouette


def test_a_glyph_scores_one_against_itself(legend):
    a = _sil_of(legend, "DUPLEX RECEPTACLE")
    assert ls.match_score(a, a) == pytest.approx(1.0, abs=1e-6)


def test_the_same_symbol_at_half_scale_ranks_first():
    doc = pymupdf.open(); page = doc.new_page(width=400, height=200)
    _receptacle(page, 80, 80, r=8)            # the legend's size
    _receptacle(page, 240, 80, r=4)           # the plan's size
    words = visual_words(page)
    big, small = sorted(glyphs.glyphs_on(page, (0, 0, 400, 200), words), key=lambda g: g.rect[0])
    a, b = ls.silhouette(page, big.rect), ls.silhouette(page, small.rect)
    assert ls.match_score(a, b) >= 0.8


def test_a_rotated_copy_still_matches():
    doc = pymupdf.open(); page = doc.new_page(width=400, height=200)
    _receptacle(page, 80, 80, r=8)
    _receptacle(page, 240, 80, r=8, rot=90)
    words = visual_words(page)
    a, b = [ls.silhouette(page, g.rect) for g in sorted(glyphs.glyphs_on(page, (0, 0, 400, 200), words), key=lambda g: g.rect[0])]
    assert ls.match_score(a, b) >= 0.8


def test_ranking_is_ordered_capped_and_floored(legend):
    words = visual_words(legend)
    templates = ls.templates_on(legend, words)
    sil = _sil_of(legend, "DUPLEX RECEPTACLE", words)
    ranked = ls.rank_templates(sil, "", templates)
    assert ranked and ranked[0].description == "DUPLEX RECEPTACLE"
    assert len(ranked) <= ls.MAX_SUGGESTIONS
    assert all(t.modifier == "" for t in ranked)
    assert ls.rank_templates(bytes(ls.SIL * ls.SIL), "", templates) == []


def test_a_modifier_selects_its_own_rows(legend):
    words = visual_words(legend)
    templates = ls.templates_on(legend, words)
    sil = _sil_of(legend, "THREE-WAY SWITCH", words)
    ranked = ls.rank_templates(sil, "3", templates)
    assert [t.description for t in ranked] == ["THREE-WAY SWITCH"]


def test_near_identical_rows_both_survive(legend):
    words = visual_words(legend)
    templates = ls.templates_on(legend, words)
    ranked = ls.rank_templates(_sil_of(legend, "DUPLEX RECEPTACLE", words), "", templates)
    assert "GROUND FAULT RECEPTACLE" in [t.description for t in ranked]


def test_the_constants_are_what_the_corpus_set():
    assert (ls.SUGGESTION_FLOOR, ls.MAX_SUGGESTIONS, ls.SIL, ls.SPAN) == (0.30, 4, 32, 96)
```

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_legend_symbols.py -q`

- [ ] **Step 3: Implement**

Append to `api/app/engine/legend_symbols.py`:

```python
# Below this correlation a template is unrelated, not a worse guess. A
# floor, never a decision: the measurement that killed thresholded
# naming is in spec section 1.1 -- true matches run 0.5 to 0.88 and two
# near-identical legend rows score 0.86 against each other, so the
# ranking is offered and a person picks.
SUGGESTION_FLOOR = 0.30
MAX_SUGGESTIONS = 4


def _grid(sil: bytes) -> np.ndarray:
    return np.frombuffer(sil, dtype=np.uint8).reshape(SIL, SIL).astype(np.float32)


def _unit(a: np.ndarray) -> np.ndarray:
    x = a - a.mean()
    n = float(np.sqrt((x * x).sum()))
    return x / n if n else x


def match_score(a: bytes, b: bytes) -> float:
    """The best zero-mean normalised correlation of two ink-fraction
    grids over the eight dihedral transforms -- a symbol drawn rotated or
    mirrored is the same symbol (glyphs._forms enumerates the same
    eight)."""
    if len(a) != SIL * SIL or len(b) != SIL * SIL:
        return 0.0
    ga, gb = _unit(_grid(a)), _grid(b)
    best = 0.0
    for k in range(4):
        rot = np.rot90(gb, k)
        for candidate in (rot, np.fliplr(rot)):
            best = max(best, float((ga * _unit(candidate)).sum()))
    return best


def rank_templates(sil: bytes, modifier: str, templates, limit: int = MAX_SUGGESTIONS):
    """The legend rows this silhouette looks most like, best first. Only
    rows with the same modifier are eligible; the score orders the list
    and never leaves this module."""
    scored = [(match_score(sil, t.silhouette), i, t)
              for i, t in enumerate(templates) if (t.modifier or "") == (modifier or "")]
    scored = [s for s in scored if s[0] >= SUGGESTION_FLOOR]
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [t for _score, _i, t in scored[:limit]]
```

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_legend_symbols.py -q`
Expected: pass. If `test_the_same_symbol_at_half_scale_ranks_first` falls below 0.8, report the number — do not lower the assertion or a constant without saying so.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/legend_symbols.py api/tests/test_engine_legend_symbols.py
git commit -m "Rank legend rows by silhouette, and let a person pick"
```

---

### Task 5: The read job stores templates

**Files:**
- Modify: `api/app/engine/documents.py` (`read`, `sheet_from_row`), `api/app/engine/contracts.py` (`DetectedSheet.symbol_templates`), `api/app/worker/read_job.py`
- Test: `api/tests/test_worker_read.py`, `api/tests/test_engine_documents.py`

**Interfaces:**
- Consumes: `legend_symbols.templates_on`.
- Produces: `DetectedSheet.symbol_templates: list[SymbolTemplate]` (default empty), carried by `sheet_from_row` as a list of dicts with `silhouette` base64-encoded; `Sheet.symbol_templates` written by the read job for `kind == "legend"`. (`sheet_to_payload` carries no templates — the wire payload `estimate.full_takeoff` returns per sheet doesn't need them, and the read job writes `Sheet.symbol_templates` directly — so it was correctly left unmodified.)

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_worker_read.py`:

```python
def test_a_legend_sheet_stores_its_rows(db, project, dana, inline, monkeypatch):
    import pymupdf
    from sqlalchemy import select
    from app.takeoff.models import Sheet
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    page.insert_text((72, 40), "E0.1 LEGEND AND ABBREVIATIONS")
    page.draw_rect(pymupdf.Rect(30, 30, 570, 380))
    s = page.new_shape(); s.draw_circle((120, 120), 8); s.draw_line((108, 120), (114, 120)); s.draw_line((126, 120), (132, 120))
    s.finish(color=(0, 0, 0), width=0.7); s.commit()
    page.insert_text((150, 123), "DUPLEX RECEPTACLE", fontsize=7)
    d = _stored(db, project, dana, inline, doc.tobytes())
    queue.enqueue_read(db, d); _run_all(db)
    sheet = db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))).first()
    assert sheet.kind == "legend"
    assert sheet.symbol_templates and sheet.symbol_templates[0]["description"] == "DUPLEX RECEPTACLE"
    assert sheet.symbol_templates[0]["sheet_number"] == sheet.number
    assert isinstance(sheet.symbol_templates[0]["silhouette"], str)   # base64 on the row


def test_a_plan_sheet_stores_no_templates(db, project, dana, inline, monkeypatch):
    from sqlalchemy import select
    from app.takeoff.models import Sheet
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf("E2.1 POWER PLAN", pages=1))
    queue.enqueue_read(db, d); _run_all(db)
    sheet = db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))).first()
    assert not sheet.symbol_templates
```

If the synthetic page is not classified `legend` by `sheet_kind`, read that module and adjust the page's text so it is (the kind gate is not this task's to change).

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_worker_read.py -q -k legend`

- [ ] **Step 3: Implement**

`contracts.py` — on `DetectedSheet`, beside `legend`:

```python
    # B3c: the legend rows read off this sheet, when it is a legend sheet.
    symbol_templates: list["SymbolTemplate"] = field(default_factory=list)
```

`documents.py` — in `read`/`detect_sheets`, after a sheet's kind is decided, for a legend sheet:

```python
        if sheet.kind == "legend":
            sheet.symbol_templates = legend_symbols.templates_on(page, words, sheet_number=sheet.number)
```

(use the page and `visual_words` already in scope there; import `legend_symbols` at the top).

Add the two conversions, next to `sheet_to_payload`:

```python
def template_to_payload(t: SymbolTemplate) -> dict:
    """A template as it is stored on the sheet row: the silhouette is
    base64 so the column stays JSON."""
    return {"description": t.description, "modifier": t.modifier, "rect": list(t.rect),
            "silhouette": base64.b64encode(t.silhouette).decode("ascii"), "sheet_number": t.sheet_number}


def template_from_row(raw: dict) -> SymbolTemplate:
    return SymbolTemplate(description=raw.get("description", ""), modifier=raw.get("modifier", ""),
                          rect=tuple(raw.get("rect") or (0, 0, 0, 0)),
                          silhouette=base64.b64decode(raw.get("silhouette") or ""),
                          sheet_number=raw.get("sheet_number", ""))
```

`sheet_from_row` gains a `symbol_templates=None` keyword (last, defaulted, so existing callers keep working) mapping through `template_from_row`. `import base64` at the top.

`read_job.py` — in the `Drawings` branch, beside `sheet.legend = …`:

```python
            sheet.symbol_templates = [documents.template_to_payload(t) for t in detected.symbol_templates] or None
```

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_worker_read.py tests/test_engine_documents.py tests/test_corpus_sheets.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/contracts.py api/app/engine/documents.py api/app/worker/read_job.py api/tests/test_worker_read.py
git commit -m "Store a legend sheet's rows at upload"
```

---

### Task 6: Counting splits a cluster by its modifier

**Files:**
- Modify: `api/app/engine/counting.py`, `api/app/engine/contracts.py` (`DeviceCluster.modifier`, `.exemplar_silhouette`)
- Test: `api/tests/test_engine_counting.py`, `api/tests/test_corpus_sheets.py`

**Interfaces:**
- Produces: `DeviceCluster.modifier: str = ""`, `DeviceCluster.exemplar_silhouette: bytes | None = None`; shape clusters tagged `shape:<sig>` or `shape:<sig>:<modifier>`; constants `MODIFIER_PT`/`MAX_MODIFIER_CHARS` imported from `legend_symbols`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_engine_counting.py`:

```python
def test_a_subscript_splits_a_shape_cluster(tmp_path):
    def draw(page, _):
        for i, x in enumerate((100, 200, 300, 400, 500, 600, 700)):
            s = page.new_shape()
            s.draw_line((x, 294), (x, 306)); s.draw_circle((x, 298), 3); s.draw_circle((x, 302), 3)
            s.finish(color=(0, 0, 0), width=0.7); s.commit()
            if i < 4:
                page.insert_text((x + 4, 296), "3", fontsize=5)
    path, (sheet,) = _plan(tmp_path, draw)
    by_tag = {c.tag: c for c in counting.count_sheet(path, sheet)}
    threes = [c for t, c in by_tag.items() if t.endswith(":3")]
    plains = [c for t, c in by_tag.items() if t.startswith("shape:") and not t.endswith(":3")]
    assert len(threes) == 1 and threes[0].count == 4 and threes[0].modifier == "3"
    assert len(plains) == 1 and plains[0].count == 3 and plains[0].modifier == ""
```

- [ ] **Step 2: Run, expect failure**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_counting.py -q -k subscript`

- [ ] **Step 3: Implement**

`contracts.py` — on `DeviceCluster`:

```python
    # B3c: the subscript beside this cluster's instances ("3", "D"), when
    # every instance carries the same one. A switch variant shares its
    # drawn symbol and differs only here, so it is part of the cluster's
    # identity -- Counting records it and never interprets it.
    modifier: str = ""
    # The exemplar as an ink-fraction silhouette, rendered by the classify
    # job while the file is open, for ranking against the legend.
    exemplar_silhouette: bytes | None = None
```

`counting.py` — import `MAX_MODIFIER_CHARS, MODIFIER_PT` from `app.engine.legend_symbols`, and in `_shape_clusters`, replace the single-cluster append with a per-modifier split:

```python
    for c in glyphs.cluster(found, MIN_PLACEMENTS):
        by_modifier: dict[str, list] = {}
        for g in c.members:
            by_modifier.setdefault(_modifier_of(g.rect, words), []).append(g)
        for modifier, members in sorted(by_modifier.items()):
            if len(members) < MIN_PLACEMENTS:
                continue
            tag = f"shape:{c.signature}" + (f":{modifier}" if modifier else "")
            out.append(DeviceCluster(
                tag=tag, sheet_page_index=sheet.page_index, modifier=modifier,
                placements=[_placement(g) for g in members], exemplar=members[0].rect,
            ))
    return out


def _modifier_of(rect, words) -> str:
    """The subscript touching this instance, if any -- a switch variant's
    only difference from its plain sibling."""
    x0, y0, x1, y1 = rect
    for w in words:
        text = w.text.strip()
        if not text or len(text) > MAX_MODIFIER_CHARS:
            continue
        if w.x0 <= x1 + MODIFIER_PT and w.x1 >= x0 - MODIFIER_PT and w.y0 <= y1 + MODIFIER_PT and w.y1 >= y0 - MODIFIER_PT:
            return text
    return ""
```

- [ ] **Step 4: Run, including the corpus**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_counting.py tests/test_corpus_sheets.py tests/test_engine_pipeline.py tests/test_worker_run.py -q`
Expected: pass. Splitting can drop a sub-cluster below `MIN_PLACEMENTS`; if a corpus floor fails, report the before/after numbers rather than changing a floor.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/counting.py api/app/engine/contracts.py api/tests/test_engine_counting.py
git commit -m "Split a shape cluster by the subscript beside its instances"
```

---

### Task 7: Classification attaches ranked suggestions

**Files:**
- Modify: `api/app/engine/classification.py`, `api/app/engine/rows.py`, `api/app/worker/classify_job.py`, `api/app/takeoff/ingest.py`, `api/app/takeoff/merge.py`
- Test: `api/tests/test_engine_classify.py`, `api/tests/test_ingest_mapping.py`, `api/tests/test_merge.py`

**Interfaces:**
- Consumes: `legend_symbols.rank_templates`, `sentence_case`; `DeviceCluster.exemplar_silhouette`, `.modifier`.
- Produces: `classify(clusters, sheets, templates=None)` and `classify_cluster(cluster, sheets, templates=None)`; `ClassifiedItem.suggestions: list[dict]`; row key `"suggestions"`; `Item.suggestions` written by `merge_sheet`.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_engine_classify.py`:

```python
def _template(description, silhouette, modifier=""):
    from app.engine.contracts import SymbolTemplate
    return SymbolTemplate(description=description, modifier=modifier, rect=(0, 0, 10, 10),
                          silhouette=silhouette, sheet_number="E0.1")


def _sil(seed):
    import numpy as np
    from app.engine import legend_symbols as ls
    rng = np.random.default_rng(seed)
    return bytes((rng.random((ls.SIL, ls.SIL)) * 255).astype("uint8").ravel())


def test_an_unnamed_cluster_carries_ranked_suggestions():
    from app.engine.classification import classify
    from app.engine.contracts import DetectedSheet, DeviceCluster, Placement
    sil = _sil(1)
    sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                          width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    c = DeviceCluster(tag="shape:0a1b2c3d", sheet_page_index=0, placements=[Placement(10, 10, 6, 6)] * 4,
                      exemplar=(7, 7, 13, 13), exemplar_silhouette=sil)
    (item,) = classify([c], [sheet], templates=[_template("DUPLEX RECEPTACLE", sil), _template("PANEL", _sil(2))])
    assert item.name == "Unclassified symbol" and item.status == "attention"
    assert item.suggestions[0] == {"name": "Duplex receptacle", "sheet": "E0.1"}
    assert item.warning["fix"] == "Pick what this symbol is from the legend entries listed, or classify it by hand."
    assert "0a1b2c3d" not in str(item.suggestions)


def test_a_named_cluster_carries_no_suggestions():
    from app.engine.classification import classify
    from app.engine.contracts import DetectedSheet, DeviceCluster, Placement
    sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                          width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    c = DeviceCluster(tag="R", sheet_page_index=0, placements=[Placement(10, 10)] * 4)
    (item,) = classify([c], [sheet], templates=[_template("DUPLEX RECEPTACLE", _sil(1))])
    assert not item.suggestions


def test_no_templates_means_the_old_wording():
    from app.engine.classification import classify
    from app.engine.contracts import DetectedSheet, DeviceCluster, Placement
    sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                          width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    c = DeviceCluster(tag="shape:0a1b2c3d", sheet_page_index=0, placements=[Placement(10, 10, 6, 6)] * 4,
                      exemplar=(7, 7, 13, 13), exemplar_silhouette=_sil(3))
    (item,) = classify([c], [sheet], templates=[])
    assert item.suggestions == []
    assert item.warning["fix"] == "Assign a classification, or reject it if it isn't a device."
```

Append to `api/tests/test_ingest_mapping.py` a test that `map_payload` carries a row's `"suggestions"` through unchanged and defaults it to `[]` when absent; and to `api/tests/test_merge.py` a test that `merge_sheet` writes `Item.suggestions` from the row and clears it when a later run reports none.

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_classify.py tests/test_ingest_mapping.py tests/test_merge.py -q`

- [ ] **Step 3: Implement**

`classification.py`:
- `ClassifiedItem` gains `suggestions: list[dict] = field(default_factory=list)`.
- `classify(clusters, sheets, templates=None)`; in the `shape:` branch build

```python
            ranked = []
            if templates and c.exemplar_silhouette:
                ranked = [{"name": legend_symbols.sentence_case(t.description), "sheet": t.sheet_number}
                          for t in legend_symbols.rank_templates(c.exemplar_silhouette, c.modifier, templates)]
            warning = _unknown_glyph_warning(c.count, no)
            if ranked:
                warning = {**warning, "fix": "Pick what this symbol is from the legend entries listed, or classify it by hand."}
```
  and pass `suggestions=ranked`, `warning=warning` into the `ClassifiedItem`.
- `classify_cluster(cluster, sheets, templates=None)` forwards `templates`.
- `classify_run(..., templates=None)` keeps the model path unchanged; templates are used only by the deterministic naming path.

`rows.py` — `_row_from_catalog` adds `"suggestions": item.suggestions` (and `_row_from_spec` adds `"suggestions": []`).

`ingest.py` — `map_payload` carries `"suggestions": raw.get("suggestions") or []` on each item.

`merge.py` — `_overwrite` and the insert both set `item.suggestions = row["suggestions"] or None`.

`classify_job.py` — while the file is open, after counting each plan sheet, render each shape cluster's exemplar silhouette and collect the project's templates:

```python
                    for c in clusters_by_sheet[s.id]:
                        if c.tag.startswith("shape:") and c.exemplar:
                            c.exemplar_silhouette = legend_symbols.silhouette(page_of(path, detected[s.id].page_index), c.exemplar)
```
  — open the page once per sheet (`doc = pymupdf.open(path)` is already available through `documents`; if not, add a small local helper that opens the document once per file and indexes pages, so the file is opened once, not once per cluster).

  and, before `classify_run`, gather templates from every sheet row:

```python
    templates = [documents.template_from_row(t) for s in all_sheets for t in (s.symbol_templates or [])]
```
  passing `templates=templates` into `classify_run` and into `sheet.rows_for`'s deterministic path (`sheet_job` passes it through the job payload as the templates are on the sheet rows — read them there instead of the payload, to keep the payload small).

`sheet.py` — `rows_for(..., templates=None)` forwards to `classification_mod.classify_cluster(c, sheets, templates)`.

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_engine_classify.py tests/test_ingest_mapping.py tests/test_merge.py tests/test_worker_run.py tests/test_engine_pipeline.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/classification.py api/app/engine/rows.py api/app/engine/sheet.py api/app/worker/classify_job.py api/app/takeoff/ingest.py api/app/takeoff/merge.py api/tests
git commit -m "Offer legend candidates on a symbol the engine could not name"
```

---

### Task 8: `name` becomes editable, and suggestions reach the wire

**Files:**
- Modify: `api/app/takeoff/mutations.py` (`EditIn`), `api/app/takeoff/edit_validation.py`, `api/app/takeoff/schemas.py` (`ItemOut`), `api/app/takeoff/snapshot.py`
- Modify: `src/lib/store/api.js` (`EDITABLE_FIELDS`), `src/lib/store/api-mapping.js` (`mapItem`)
- Test: `api/tests/test_mutation_endpoints.py`, `api/tests/test_edit_validation.py` (whichever file holds the edit-validation tests — find it with `grep -rn "validate_edit" api/tests | head`), `src/lib/store/api-mapping.test.js`

**Interfaces:**
- Produces: `EditIn.name: str | None`; `validate_edit` refuses an empty or >300-character name; `ItemOut.suggestions: list[dict] = []`; client `EDITABLE_FIELDS` gains `"name"`; `mapItem` carries `suggestions`.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_mutation_endpoints.py`:

```python
def test_an_item_can_be_renamed(client, signed_in_user, db, project, item):
    r = client.patch(f"/api/items/{item.id}", json={"name": "Duplex receptacle"},
                     headers={"If-Match": str(item.version)})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["name"] == "Duplex receptacle"
    assert r.json()["label"].startswith("Edited")


def test_a_blank_or_oversized_name_is_refused(client, signed_in_user, item):
    for bad in ("   ", "x" * 301):
        r = client.patch(f"/api/items/{item.id}", json={"name": bad}, headers={"If-Match": str(item.version)})
        assert r.status_code == 422, bad


def test_item_out_carries_suggestions(client, signed_in_user, db, project, item):
    item.suggestions = [{"name": "Duplex receptacle", "sheet": "E0.1"}]
    db.commit()
    body = client.get(f"/api/projects/{project.id}/snapshot").json()
    row = next(i for i in body["items"] if i["id"] == str(item.id))
    assert row["suggestions"] == [{"name": "Duplex receptacle", "sheet": "E0.1"}]
```

Append to the client mapping test file:

```js
it("carries suggestions and allows a name edit", () => {
  expect(mapItem({ ...ITEM_WIRE, suggestions: [{ name: "Duplex receptacle", sheet: "E0.1" }] }).suggestions)
    .toEqual([{ name: "Duplex receptacle", sheet: "E0.1" }]);
});
```

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_mutation_endpoints.py -q -k "rename or blank or suggestions"` and `npm test -- --run src/lib/store/api-mapping.test.js`

- [ ] **Step 3: Implement**

`EditIn` gains `name: str | None = None` (the docstring's "five fields" becomes six). `edit_validation.validate_edit` gains, in the same shape as its existing field rules:

```python
    if "name" in changes:
        name = (changes["name"] or "").strip()
        if not name:
            raise DomainError("invalid_name", "An item needs a name. Type what this symbol is.", status=422)
        if len(name) > 300:
            raise DomainError("invalid_name", "That name is too long. Keep it under 300 characters.", status=422)
        changes["name"] = name
```

(read the module first and follow its existing refusal style exactly — code, message, status.)

`ItemOut` gains `suggestions: list[dict] = Field(default_factory=list)`; `_item_out` passes `suggestions=item.suggestions or []`.

Client: `EDITABLE_FIELDS = ["name", "system", "category", "quantity", "notes", "symbol"];` and `mapItem` adds `suggestions: i.suggestions ?? []`.

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_mutation_endpoints.py tests/test_review_state_machine.py tests/test_undo_redo.py tests/test_snapshot.py -q` then `npm test -- --run src/lib`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff src/lib api/tests src/lib/store/api-mapping.test.js
git commit -m "Let an estimator rename an item, and carry its legend candidates"
```

---

### Task 9: A drawn box suggests a name

**Files:**
- Modify: `api/app/worker/match_job.py`, `api/app/matches/schemas.py`, `api/app/matches/router.py`
- Test: `api/tests/test_worker_match.py`, `api/tests/test_matches_api.py`

**Interfaces:**
- Produces: `match_job` writes `SymbolMatch.suggested_name`; `SymbolMatchOut.suggested_name: str`.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_worker_match.py` a test that a sheet whose project has a legend sheet with a receptacle row, and a plan receptacle boxed, yields `match.suggested_name == "Duplex receptacle"`; and one where the project has no templates and `suggested_name == ""`. Append to `api/tests/test_matches_api.py`:

```python
def test_the_wire_carries_a_suggested_name(client, signed_in_user, db, project, sheet):
    m = _found(db, project, sheet, signed_in_user.id)
    m.suggested_name = "Duplex receptacle"; db.commit()
    body = client.get(f"/api/symbol-matches/{m.id}").json()
    assert body["suggested_name"] == "Duplex receptacle"
    assert not any(k in body for k in ("score", "threshold"))
```

- [ ] **Step 2: Run, expect failures**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_worker_match.py tests/test_matches_api.py -q`

- [ ] **Step 3: Implement**

In `match_job.run`, after the matches are computed and while the page is open, compute the boxed glyph's silhouette (`legend_symbols.silhouette(page, rect)`) and rank it against the project's templates (read from every sheet row of the project, `documents.template_from_row`), writing `match.suggested_name = legend_symbols.sentence_case(best.description)` when `rank_templates` returns anything, else `""`. The modifier for a drawn box is `""`.

`SymbolMatchOut` gains `suggested_name: str = ""`; the router's `_out` passes `m.suggested_name`.

- [ ] **Step 4: Run**

Run: `cd api && ../.enginevenv/bin/python -m pytest tests/test_worker_match.py tests/test_matches_api.py tests/test_tenancy.py -q`

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/match_job.py api/app/matches api/tests
git commit -m "Suggest a name for a drawn symbol from the legend"
```

---

### Task 10: The suggestion block, and the pre-filled name

**Files:**
- Modify: `src/components/ItemDetailPanel.jsx`, `src/components/MatchResultCard.jsx`, `src/lib/store/api-mapping.js` (`mapMatch`), `src/styles.css`
- Test: `src/components/ItemDetailPanel.suggestions.test.jsx` (new), `src/components/MatchResultCard.test.jsx`

**Interfaces:**
- Consumes: `item.suggestions`, `match.suggestedName`, `editItem`.
- Produces: a **Suggested from the legend** block on an unclassified item; `MatchResultCard`'s name field defaults to `match.suggestedName`.

- [ ] **Step 1: Write the failing tests**

`src/components/ItemDetailPanel.suggestions.test.jsx`: render the panel with a selected item named "Unclassified symbol" carrying two suggestions → two buttons labelled `Duplex receptacle · from E0.1`; clicking the first calls `onSaveEdit`/`onStartEdit`'s path — assert the panel calls its `onAcceptSuggestion` prop with `"Duplex receptacle"` (add that prop; `Workspace` wires it to `editItem(item.id, { name }, item.version)`). A named item and an item with no suggestions render no block. Assert no "%" or score text.

`MatchResultCard.test.jsx`: a found match with `suggestedName: "Duplex receptacle"` renders the name input with that value, and **Add N to the takeoff** enabled.

- [ ] **Step 2: Run, expect failures**

Run: `npm test -- --run src/components/ItemDetailPanel.suggestions.test.jsx src/components/MatchResultCard.test.jsx`

- [ ] **Step 3: Implement**

`mapMatch` gains `suggestedName: m.suggested_name ?? ""`. `MatchResultCard` initialises `useState(match.suggestedName || "")`.

`ItemDetailPanel` renders, under the warning on a selected item whose `name === "Unclassified symbol"` and `suggestions?.length`:

```jsx
        <div className="suggestions">
          <p className="label">Suggested from the legend</p>
          {sel.suggestions.map((s) => (
            <button key={`${s.name}-${s.sheet}`} className="btn btn--block" onClick={() => onAcceptSuggestion(sel, s.name)}>
              {s.name} · from {s.sheet}
            </button>
          ))}
        </div>
```

`Workspace` passes `onAcceptSuggestion={(item, name) => editItem(item.id, { name }, item.version)}`. `.suggestions` styling reuses existing tokens (no new colours).

- [ ] **Step 4: Run everything**

Run: `npm test -- --run && npm run build`, then `cd api && ../.enginevenv/bin/python -m pytest -q`
Expected: both suites green; report the counts.

- [ ] **Step 5: Commit**

```bash
git add src/components src/lib/store/api-mapping.js src/styles.css
git commit -m "Offer the legend's own words on an unclassified symbol"
```

---

### Task 11: Docs as built

**Files:**
- Modify: `docs/specs/legend-named-clusters.md` (add `## 11. As built`), `docs/README.md` (B3c row → `built`, plan link), `CLAUDE.md` (architecture tree: `legend_symbols.py`; the engine paragraph: the legend suggests, a person picks; `name` is editable), `README.md` ("What's in the drawing": the legend block), `docs/roadmap/blueprint-analysis-research.md` (§2 step 1 → built, with what the measurement changed)
- Test: none; run `npm run build`.

- [ ] **Step 1: Write the as-built section**

Record every deviation found during Tasks 1–10 — including: `EditIn` had no `name` field before this work (spec §6 assumed it); whatever the corpus measured for `rank_templates` on Unalaska and Kittles; any constant that moved and why; anything parked in the ledger.

- [ ] **Step 2: Update the four other docs**

One sentence each, no restructuring.

- [ ] **Step 3: Commit**

```bash
git add docs CLAUDE.md README.md
git commit -m "Docs: legend suggestions as built"
```

---

## Self-review

**Spec coverage.** §2 data model → Task 1 (columns) and Tasks 3/6 (contracts); §3 legend rows → Tasks 2 (containment merge) and 3; §4 ranking → Task 4; §5 modifier split → Task 6; §6 classification and the reworded `fix` → Task 7; §7 find-like-this → Task 9; §8 client → Task 10 (plus Task 8 for the wire); §9 testing → each task's Step 1 plus the corpus checks in Tasks 2, 6 and 11; §10 not built — nothing here auto-names, reads a raster legend, or stores a firm-wide library.

**Placeholder scan.** Every code step carries its code. Three places name a file to read first rather than reproducing it (`edit_validation`'s refusal style, `sheet_kind`'s gate, the mapping test's fixture names) because those idioms live in files this plan does not quote; the assertions and the required behaviour are given in full.

**Type consistency.** `SymbolTemplate(description, modifier, rect, silhouette, sheet_number)` (Task 3) is what `template_to_payload`/`template_from_row` (Task 5) round-trip and what `rank_templates` (Task 4) consumes; `DeviceCluster.modifier`/`.exemplar_silhouette` (Task 6) are what Task 7 reads; `ClassifiedItem.suggestions` → row `"suggestions"` → `Item.suggestions` → `ItemOut.suggestions` → `mapItem().suggestions` → the panel (Tasks 7, 8, 10); `SymbolMatch.suggested_name` → `SymbolMatchOut.suggested_name` → `mapMatch().suggestedName` → the card (Tasks 1, 9, 10).
