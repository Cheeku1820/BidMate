# B3c — Legend suggestions

**Date:** 2026-09-18 (revised 2026-09-24 after measurement — see §1.1)
**Branch:** `feat/legend-named-clusters`, off `feat/accurate-symbol-marking` (B3b, unmerged — the stack stays linear: main ← B3b ← B3c)
**Implements:** step 1 of `docs/roadmap/blueprint-analysis-research.md` §2 — the legend is the classifier the drawing ships with.

## 1. What this changes

After B3b, Counting finds every untagged device glyph on an exploded vector sheet and Classification either sends a crop to the model or lands the cluster as *Unclassified symbol*. The legend sheet — which every set carries and which the read job already detects as `kind == "legend"` — names those same glyphs in the drafter's own words, and nothing reads it that way.

After B3c the read job cuts each vector legend sheet into rows (glyph, modifier, description) and stores each row's glyph as a small normalised silhouette. Every cluster the engine cannot name on its own then carries a short, ranked list of **legend candidates** — the drafter's own words for the symbols it looks most like — and the estimator picks one with a click, which names every instance in that cluster at once. *Find every one like this* pre-fills its name field from the top candidate. The legend never names anything by itself.

## 1.1 Why suggestions, not automatic naming

The first draft of this spec named a cluster automatically when its silhouette matched a legend row above a threshold. Measured on the corpus (Unalaska E0.1 legend against E2.1 plan, 2026-09-24, four silhouette variants including ink-fraction pooling, Gaussian blur and a distance transform), that rule does not survive:

- True matches score between **0.5 and 0.88** depending on how much the plan's stroke weight differs from the legend's (the switch 0.81–0.88, the recessed fixture 0.78–0.81, the receptacles 0.61–0.76, one junction-box cluster 0.12 — no match at all). No single threshold catches the receptacles without also catching wrong rows.
- Legend rows are often **near-identical by construction**: a duplex receptacle and a ground-fault duplex receptacle score **0.86–0.90 against each other**, because the GFI symbol *is* the duplex symbol with a slash. No margin rule separates them, so the most common device on a set would land *Needs attention* — hundreds of acknowledgements, the opposite of the intent.

Ranking is reliable where an absolute score is not: on every cluster measured, the correct row was first or second. So the engine ranks and the estimator decides — which is also what "nothing gets counted without a person" already requires of every other quantity in the product.

Two further facts from the corpus shape the rest (measured 2026-09-17):

1. **Plan symbols are drawn at about half the legend's size** (the recessed fixture is 18 pt in the legend, 9 pt on the plan) and with small path differences (the plan `$` has 19 segments to the legend's 17). B3b's exact, size-sensitive `same_shape` is right for "the same symbol on the same sheet" and wrong for "the same symbol as the legend", so legend comparison uses normalised silhouettes, not paths.
2. **Switch variants share one glyph and differ by a subscript** (`$` / `$3` / `$4` / `$D` / `$K`). A template is glyph **plus** modifier, and a plan cluster splits by the modifier beside each instance.

Nothing counted changes. Counting still does not know what anything is; it gains one geometric fact (the modifier beside a glyph). Classification still names; it gains a ranked list to offer. Every constant below is a named module value with a test.

## 2. Data model

Migration `0024_symbol_templates`, reversible:

- `sheets.symbol_templates JSONB NULL` — on a legend sheet, the rows the read job cut:

```
[{"description": "DUPLEX RECEPTACLE", "modifier": "", "rect": [x0, y0, x1, y1], "silhouette": "<base64 of 32×32 ink-fraction bytes>"}, …]
```

- `items.suggestions JSONB NULL` — on an unnamed item, the ranked candidates the estimator can accept:

```
[{"name": "Duplex receptacle", "sheet": "E0.1"}, {"name": "Ground fault interrupter duplex receptacle", "sheet": "E0.1"}, …]
```

At most `MAX_SUGGESTIONS = 4` entries, best first. No score, no threshold, no signature ever reaches this column — it is read straight onto the wire.

- `symbol_matches.suggested_name VARCHAR(300) DEFAULT ''` — the top candidate for a drawn box (§7).

`DetectedSheet` gains `symbol_templates: list[SymbolTemplate]` (empty on non-legend sheets); `sheet_from_row`/`sheet_to_payload` carry it. `DeviceCluster` gains `modifier: str = ""` and `exemplar_silhouette: bytes | None` (rendered by the classify job while the file is open — geometry, no name). `Item` is otherwise unchanged: a suggestion-named item is an ordinary row whose `source_tag` is the cluster's.

Contracts in `engine/contracts.py`:

```python
@dataclass
class SymbolTemplate:
    description: str          # the legend's own words, uppercase as printed
    modifier: str             # "", "3", "D", … — text touching the glyph
    rect: tuple[float, float, float, float]   # page points on the legend sheet
    silhouette: bytes         # SIL × SIL ink fractions, one byte each, row-major
    sheet_number: str         # the legend sheet it was read from, e.g. "E0.1"
```

Legend text is data: it becomes a name after `sentence_case()` (uppercase → first letter capitalised, acronyms of ≤ 4 letters kept), never a prompt and never an instruction (invariant 11 in ROADMAP).

## 3. Legend rows — `engine/legend_symbols.py`

Pure PyMuPDF + `glyphs.py` + numpy; runs in the read job on every sheet with `kind == "legend"` and a vector layer (a raster legend yields `[]` and the set behaves as today).

- **Glyph column.** `glyphs.glyphs_on(page, page.rect, words)` with one new grouping rule in `glyphs.py`: `_candidates` also merges a candidate whose bbox centre lies inside another candidate's bbox (both ≤ `MAX_GLYPH_PT`) — a **containment merge** — so the recessed fixture's square-plus-circle is one glyph on the legend and on the plan alike. (This rule applies to plan counting too; it only ever joins parts of one symbol, and the corpus counts are re-asserted.)
- **Row band.** A row is a glyph plus every word whose vertical centre lies within the glyph's own height of the glyph's centre.
- **Modifier.** A word in the band whose bbox comes within `MODIFIER_PT = 2.0` of the glyph's bbox and has ≤ `MAX_MODIFIER_CHARS = 2` characters. Empty otherwise.
- **Description.** The words in the band to the right of the glyph (and the modifier), within `DESCRIPTION_REACH_PT = 240` of the glyph's right edge, in reading order; joined with single spaces. A row with no description words is dropped (a stray drawing, not a legend entry).
- **Silhouette.** `silhouette(page, rect) -> bytes`: the page clipped to the glyph's rect, rendered greyscale at a zoom that makes the long side `SPAN = 96` px, ink measured as `pixel < 128`, then area-pooled to `SIL = 32` squares of **ink fraction** (one byte per cell, 0–255) and centred in the square. Pooling is what makes a 5 pt plan glyph and an 18 pt legend glyph comparable — a binary silhouette is dominated by relative stroke weight, which is exactly what differs between them.
- Output: `templates_on(page, words) -> list[SymbolTemplate]`, rows in reading order.

## 4. Ranking — `engine/legend_symbols.py`

- `match_score(a: bytes, b: bytes) -> float`: the best zero-mean normalised correlation of ink-fraction grids over the eight dihedral transforms (rotations by 90° and mirrors, as `glyphs._forms` enumerates). Identical grids score 1.0.
- `rank_templates(silhouette, modifier, templates, limit=MAX_SUGGESTIONS) -> list[SymbolTemplate]`: templates whose modifier equals the cluster's, scored and sorted best first, keeping those at or above `SUGGESTION_FLOOR = 0.30` (a floor that removes the unrelated, not a decision — on the corpus the correct row placed first or second every time) and at most `limit`. Ties break on the legend's reading order, so the list is stable across runs.
- The score orders the list and never leaves the engine: it is not stored, not serialised, and not shown (CLAUDE.md, "confidence never renders").

## 5. Counting — the modifier splits a cluster

In `counting._shape_clusters`, after clustering: for each instance, the modifier is the word (≤ `MAX_MODIFIER_CHARS`) whose bbox comes within `MODIFIER_PT` of the instance's rect. A cluster whose instances carry different modifiers splits into one `DeviceCluster` per modifier, tagged `shape:<sig>` (no modifier) and `shape:<sig>:<modifier>`, each keeping its own placements and exemplar; `MIN_PLACEMENTS` applies per sub-cluster. Tag linking runs after the split. Counting records the modifier; it does not interpret it.

## 6. Classification — suggestions on what it could not name

The classify job, with the file open, renders `exemplar_silhouette` for every shape cluster and passes the project's templates — every legend sheet's `symbol_templates` — into `classify_run`.

`classify()` is unchanged for everything it already names: a tag-linked cluster keeps its tag's name, and a `shape:` cluster still lands as **Unclassified symbol**, *Needs attention*, with today's "Symbol not in legend" warning on the deterministic path, or goes to the model with a key. What changes is that an unnamed cluster now carries `suggestions` — `rank_templates(...)` mapped to `{"name": sentence_case(description), "sheet": sheet_number}` — and the warning's `fix` reads "Pick what this symbol is from the legend entries listed, or classify it by hand." when there is at least one. Items the model names keep their own result; suggestions are attached only where the name is still *Unclassified symbol*.

Accepting a suggestion is an ordinary edit: `PATCH /api/items/{id}` with the chosen name (the existing route, the existing `edit` action, the existing undo). One acceptance names the whole cluster because a cluster is one item — that is the Counting/Classification boundary doing its job.

## 7. Find every one like this — a pre-filled name

`worker/match_job.find_matches` also returns the silhouette of the boxed glyph (vector path only); the job stores `rank_templates(...)[0]`'s name on `symbol_matches.suggested_name` (empty when nothing clears the floor). `SymbolMatchOut` gains `suggested_name`; the result card's name field starts with it, editable, with "Not sure yet" unchanged. Never a score on the wire.

## 8. The client

`ItemDetailPanel` renders a **Suggested from the legend** block on an item whose name is "Unclassified symbol" and whose `suggestions` are non-empty: up to four buttons, each `{name} · from {sheet}`, sentence case. Clicking one edits the item through the existing `editItem` path (one undoable action, the toast reads "Renamed to duplex receptacle"). The block never renders a score, never renders for a named item, and is absent when `suggestions` is empty. `mapItem` carries `suggestions`; the store needs no new call.

## 9. Testing

- **Legend rows** (`tests/test_engine_legend_symbols.py`): a synthetic legend page with five rows — a receptacle, a GFI receptacle (one extra bar), a `$` with no modifier, a `$` with a touching "3", and a square-with-inner-circle — plus a stray line with no text → five templates, the modifier row carries `"3"`, the composite row is one template, descriptions in reading order across a two-line description.
- **Silhouettes and ranking**: the same glyph at 1× and 0.5× ranks first against itself; a rotated copy ranks first; `rank_templates` returns at most `MAX_SUGGESTIONS`, is ordered, drops everything below `SUGGESTION_FLOOR`, and returns `[]` when no template clears it; the exact constant values are asserted; two near-identical rows (receptacle and GFI) both appear in the list rather than one being discarded — the estimator chooses.
- **Counting**: a plan with `$` instances carrying "3" beside four of them and nothing beside three → two clusters `shape:<sig>:3` (4) and `shape:<sig>` (3); the containment merge keeps the composite fixture one cluster; corpus counts re-asserted.
- **Classification**: an unnamed cluster carries ranked suggestions and the reworded `fix`; a named cluster carries none; suggestions are absent when the project has no legend templates; nothing in the item payload carries a score.
- **Corpus** (skipped without `bid_examples/`): Unalaska E0.1 yields ≥ 25 templates and Kittles E-000 ≥ 15; on Unalaska E2.1 the switch cluster's suggestions contain the legend's switch row and the recessed-fixture cluster's contain its fixture row (each within the first two); floors set from the measurement when the plan is written.
- **Match job**: a boxed legend-matching glyph yields `suggested_name`; `SymbolMatchOut` carries it and no score.
- **Client**: the suggestion block renders for an unclassified item with suggestions and not otherwise; clicking one calls `editItem` with that name; the result card's name field is pre-filled from `suggestedName`; no percentage or score text anywhere.

## 10. Not built in B3c

- Automatic naming from the legend at any confidence — see §1.1; the estimator picks.
- Raster legend sheets (a scanned legend yields no templates; the set behaves as today).
- Legend rows with no drawn glyph (abbreviation rows are already `LegendEntry` kind "abbreviation").
- A firm-wide template library, or reusing one project's templates on another.
- Showing or editing templates on screen D.
- Suggestions for tag-linked clusters (a tag already names them).
- Remembering an accepted suggestion so the same symbol is pre-named on the next sheet or the next revision — that is the project symbol library, step 2 of the research note.
