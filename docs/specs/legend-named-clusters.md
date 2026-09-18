# B3c — Legend-named clusters

**Date:** 2026-09-18
**Branch:** `feat/legend-named-clusters`, off `feat/accurate-symbol-marking` (B3b, unmerged — the stack stays linear: main ← B3b ← B3c)
**Implements:** step 1 of `docs/roadmap/blueprint-analysis-research.md` §2 — the legend is the classifier the drawing ships with.

## 1. What this changes

After B3b, Counting finds every untagged device glyph on an exploded vector sheet and Classification either sends a crop to the model or lands the cluster as *Unclassified symbol*. The legend sheet — which every set carries and which the read job already detects as `kind == "legend"` — names those same glyphs in the drafter's own words, and nothing reads it that way.

After B3c the read job cuts each vector legend sheet into rows (glyph, modifier, description), stores each row's glyph as a small normalised silhouette, and Classification names a plan cluster from the legend row its exemplar matches — deterministically, before any model call, with no key. On the corpus this names the Kittles receptacles, the United Utility receptacle and Unalaska's recessed fixtures and switches from their own legends. The result card of *find every one like this* pre-fills the same name.

Two facts from the corpus shape the design (measured 2026-09-17 on Unalaska E0.1/E2.1):

1. **Plan symbols are drawn at about half the legend's size** (the recessed fixture is 18 pt in the legend, 9 pt on the plan) and with small path differences (the plan `$` has 19 segments to the legend's 17). B3b's exact, size-sensitive `same_shape` is right for "the same symbol on the same sheet" and wrong for "the same symbol as the legend". Legend matching therefore compares **normalised silhouettes** — the same normalised cross-correlation `raster_match` already uses — not paths.
2. **Switch variants share one glyph and differ by a subscript** (`$` / `$3` / `$4` / `$D` / `$K`). A template is glyph **plus** modifier, and a plan cluster splits by the modifier beside each instance.

Nothing counted changes. Counting still does not know what anything is; it gains one geometric fact (the modifier beside a glyph). Classification still names; it gains a deterministic source ahead of the model. Every constant below is a named module value with a test.

## 2. Data model

Migration `0024_symbol_templates`, reversible: `sheets.symbol_templates JSONB NULL` — on a legend sheet, the list of rows the read job cut:

```
[{"description": "DUPLEX RECEPTACLE", "modifier": "", "rect": [x0, y0, x1, y1], "silhouette": "<base64 of 48×48 bits, 288 bytes>"}, …]
```

`DetectedSheet` gains `symbol_templates: list[SymbolTemplate]` (empty on non-legend sheets); `sheet_from_row`/`sheet_to_payload` carry it. `DeviceCluster` gains `modifier: str = ""` and `exemplar_silhouette: bytes | None` (the plan cluster's exemplar rendered by the classify job while the file is open — geometry, no name). `Item` is unchanged: a legend-named item is an ordinary *Ready to review* row whose `source_tag` is the cluster's (`shape:<sig>` or `shape:<sig>:<modifier>`).

Contracts in `engine/contracts.py`:

```python
@dataclass
class SymbolTemplate:
    description: str          # the legend's own words, uppercase as printed
    modifier: str             # "", "3", "D", … — text touching the glyph
    rect: tuple[float, float, float, float]   # page points on the legend sheet
    silhouette: bytes         # SIL × SIL bits, row-major, MSB first
```

Legend text is data: it becomes a name after `sentence_case()` (uppercase → first letter capitalised, acronyms of ≤ 4 letters kept), never a prompt and never an instruction (invariant 11 in ROADMAP).

## 3. Legend rows — `engine/legend_symbols.py`

Pure PyMuPDF + `glyphs.py`; runs in the read job on every sheet with `kind == "legend"` and a vector layer (a raster legend yields `[]` and the set behaves as today).

- **Glyph column.** `glyphs.glyphs_on(page, page.rect, words)` with one new grouping rule in `glyphs.py`: `_candidates` also merges a candidate whose bbox centre lies inside another candidate's bbox (both ≤ `MAX_GLYPH_PT`) — a **containment merge** — so the recessed fixture's square-plus-circle is one glyph on the legend and on the plan alike. (This rule applies to plan counting too; it only ever joins parts of one symbol, and the corpus counts are re-asserted.)
- **Row band.** A row is a glyph plus every word whose vertical centre lies within the glyph's own height of the glyph's centre.
- **Modifier.** A word in the band whose bbox comes within `MODIFIER_PT = 2.0` of the glyph's bbox and has ≤ `MAX_MODIFIER_CHARS = 2` characters. Empty otherwise.
- **Description.** The words in the band to the right of the glyph (and the modifier), within `DESCRIPTION_REACH_PT = 240` of the glyph's right edge, in reading order (sorted by line then x — use `get_text("blocks")` for the block that contains them so multi-line descriptions keep their order); joined with single spaces. A row with no description words is dropped (a stray drawing, not a legend entry).
- **Silhouette.** `silhouette(paths, rect) -> bytes`: the glyph's paths drawn onto a `SIL = 48` square bitmap, scaled so the box's long side spans 44 px, centred, strokes 2 px, fills filled — rendered with PyMuPDF's own drawing (a temporary page: `page.new_shape()` replays the paths, `get_pixmap` at the computed zoom, threshold at 50 % grey) so the legend and the plan go through the same rasteriser.
- Output: `templates_on(page, words) -> list[SymbolTemplate]`, rows in reading order.

## 4. Matching — `engine/legend_symbols.py`

- `match_score(a: bytes, b: bytes) -> float`: the best normalised cross-correlation of silhouette `a` against the eight dihedral transforms of `b` (rotations by 90° and mirrors, as `glyphs._forms` enumerates). Two identical silhouettes score 1.0; blank vs anything is 0.
- `best_template(silhouette, modifier, templates) -> tuple[SymbolTemplate | None, str]` compares only templates with the same modifier and returns `(template, "match")` when the best score ≥ `LEGEND_MATCH = 0.80` and the runner-up trails by ≥ `LEGEND_MARGIN = 0.05`; `(best, "ambiguous")` when two rows clear the threshold within the margin; `(None, "none")` otherwise.
- Both constants were set from the corpus and are pinned by tests; there is no tuning path.

## 5. Counting — the modifier splits a cluster

In `counting._shape_clusters`, after clustering: for each instance, the modifier is the word (≤ 2 chars) whose bbox comes within `MODIFIER_PT` of the instance's rect. A cluster whose instances carry different modifiers splits into one `DeviceCluster` per modifier, tagged `shape:<sig>` (no modifier) and `shape:<sig>:<modifier>`, each keeping its own placements and exemplar; `MIN_PLACEMENTS` applies per sub-cluster. Tag linking runs after the split. Counting records the modifier; it does not interpret it.

## 6. Classification — the legend before the model

The classify job, with the file open, renders `exemplar_silhouette` for every shape cluster (`legend_symbols.silhouette` on the exemplar's paths) and passes the project's templates — every legend sheet's `symbol_templates` — into `classify_run`.

In `classify()`'s deterministic path, before the existing `shape:` branch, for a shape cluster with a silhouette:

| `best_template` outcome | Item |
|---|---|
| `match` | name = `sentence_case(description)`; catalog item when `catalog.match_description(description)` finds one by keyword (a small table: "RECEPTACLE" → duplex receptacle, "GFI"/"GROUND FAULT" → GFCI, "SWITCH" → switch, "FIXTURE"/"LUMINAIRE" → luminaire generic, "JUNCTION" → junction box, "DATA"/"TELECOM" → data outlet; else `unclassified` catalog with the legend name); `symbol` from the catalog item or `infer_symbol(name, system)`; status **Ready to review**; no warning; `source_tag` = the cluster tag; `legend_row` recorded on the item's `evidence` JSON (`{"legend_sheet": "E0.1", "legend_description": …}`) so the panel's evidence answers "where". |
| `ambiguous` | name from the best row; status **Needs attention**; warning `reason "legend"`, title "Symbol matches two legend entries", `found` "This symbol matches both '{a}' and '{b}' on {legend_sheet}.", `why` "The wrong entry changes the device and its price.", `fix` "Pick the legend entry this symbol is, then approve.", `where` "{legend_sheet} and {plan_sheet}." |
| `none` | today's behaviour — the crop to the model with a key, *Unclassified symbol* without. |

Legend-named clusters (both `match` and `ambiguous`) are removed from the model's tag list and crop set: the model only sees what the legend could not name. The model path's guard from B3b (a `none` answer lands as *Unclassified symbol*) is unchanged.

## 7. Find every one like this — a suggestion

`worker/match_job.find_matches` returns, alongside the rects, the silhouette of the boxed glyph (vector path only); the job scores it with `best_template` against the project's templates and stores `suggested_name` (`sentence_case(description)` on `match`, "" otherwise) on `symbol_matches` (`suggested_name VARCHAR(300) DEFAULT ''`, same migration). `SymbolMatchOut` gains `suggested_name`; the result card's name field starts with it (the estimator still names, or says "Not sure yet"). Never a score on the wire.

## 8. Copy

Item names come from the legend in sentence case ("Duplex receptacle", "Ground fault interrupter duplex receptacle"); acronyms ≤ 4 letters stay uppercase ("GFI", "AFF", "NEMA"). The ambiguity warning above is the only new copy. No "AI", no percentages.

## 9. Testing

- **Legend rows** (`tests/test_engine_legend_symbols.py`): a synthetic legend page with five rows — a receptacle, a GFI receptacle (one extra bar), a `$` with no modifier, a `$` with a touching "3", and a square-with-inner-circle — plus a stray line with no text → five templates, the modifier row carries `"3"`, the composite row is one template, descriptions in reading order across a two-line description.
- **Silhouettes and matching**: the same glyph at 1× and 0.5× scores ≥ 0.95; rotated 90° scores the same; a receptacle vs a square scores < 0.5; the GFI vs plain receptacle margin is exercised (either clearly separated or asserted ambiguous, from the measurement); `LEGEND_MATCH`/`LEGEND_MARGIN` exact values asserted.
- **Counting**: a plan with `$` instances carrying "3" beside four of them and nothing beside three → two clusters `shape:<sig>:3` (4) and `shape:<sig>` (3); the containment merge keeps the composite fixture one cluster.
- **Classification**: with templates present, a matching cluster lands *Ready to review* with the legend name and the catalog item; an ambiguous pair lands *Needs attention* with the four-field warning; a non-matching cluster still goes to the model / *Unclassified symbol*; a legend-named cluster is absent from the model's tag list and crops.
- **Corpus** (skipped without `bid_examples/`): Unalaska E0.1 yields ≥ 25 templates and Kittles E-000 ≥ 15; on Unalaska E2.1 the switch cluster and the recessed-fixture cluster are legend-named; on Kittles EP101 the two duplex-receptacle clusters are named from a row containing "RECEPTACLE". Floors are set from the measurement when the plan is written, at two-thirds of what is seen.
- **Match job**: a boxed legend-matching glyph yields `suggested_name`; `SymbolMatchOut` carries it and no score.
- **Client**: the result card's name field is pre-filled from `suggestedName` and still editable; the import-boundary tests unchanged.

## 10. Not built in B3c

- Raster legend sheets (a scanned legend yields no templates; the set behaves as today).
- Legend rows with no drawn glyph (abbreviation rows are already `LegendEntry` kind "abbreviation").
- A firm-wide template library, or reusing one project's templates on another.
- Showing or editing templates on screen D.
- Legend matching for tag-linked clusters (a tag already names them).
