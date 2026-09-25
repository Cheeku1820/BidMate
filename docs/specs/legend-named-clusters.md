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

## 11. As built

Tasks 1–10 are merged (`feat/legend-named-clusters`, HEAD `7aa6914`). This section records where the shipped code diverges from the design above, and what the corpus actually measured along the way.

### 11.1 The pivot, in the shipped code

§1.1 already records the measurement that killed automatic naming: true matches score 0.5–0.88 depending on stroke weight, while a duplex receptacle and a ground-fault duplex receptacle score 0.86–0.90 *against each other*, because the GFI symbol is the duplex symbol with a slash added. No threshold separates "correct" from "wrong but similar," so the shipped design never tries to. `rank_templates` has no accept path — it returns a list, best first, and nothing downstream treats the first entry as a decision. `classify()` only ever attaches `suggestions`; it never writes a `name` from a ranked score. `MatchResultCard` and the item panel's suggestion block only ever offer buttons for the estimator to click. Accepting one is the same `PATCH /api/items/{id}` an estimator would send by typing the name themselves — there is no second, shorter code path from a silhouette match to a stored name. The legend narrows what the estimator has to type; it never types for them.

### 11.2 `MAX_MODIFIER_CHARS` moved from 2 to 1

The brief's constant carried over from `legend_symbols.py` at 2 characters, on the reasoning that a switch subscript like "3", "4", "D", or "K" is short. The corpus proved that band too wide: on Kittles Saxony's EP101, two-character tokens beside a receptacle glyph turned out to be circuit numbers ("43", "31", "37", …) rather than device variants — conventionally drafted right next to the device they feed, so they satisfy the same touching-proximity rule a real subscript would. At `MAX_MODIFIER_CHARS = 2` this split EP101's four real receptacle clusters into nineteen, one per circuit number, with every placement still conserved (212 in, 212 out) but the review queue fragmented by wiring detail instead of device type. Capping the constant at one character removes every circuit-number token (none of the corpus's genuine subscripts are two characters; Unalaska E0.1's own switch variants are single characters) while leaving the real splits intact: EP101 is back to 4 clusters / 212 placements, matching its pre-split baseline exactly, and Pulte Sagebriar's single-letter fixture-group subscripts (`b`, `e`, `u`, `r`, `f`, `x`) still split correctly at one character. The constant is shared between the legend reader and Counting's modifier split on purpose — a legend row's own subscript is single-character too, so the two sides read the same rule.

### 11.3 The containment merge's real semantics

§3 describes the containment merge as joining "a candidate whose bbox centre lies inside another candidate's bbox (both ≤ `MAX_GLYPH_PT`)." The shipped rule in `glyphs.py` is narrower than that sentence suggests, and the narrowing is load-bearing, not a bug: a contained candidate must also be no more than `CONTAINED_SHARE = 0.6` of the container's longest side, and the merge only fires when **exactly one** candidate meets both tests inside a given container. The bbox-size guard on the contained candidate (`≤ MAX_GLYPH_PT`) is dead code in practice — the 0.6 share rule is strictly tighter for any container at or under `MAX_GLYPH_PT` itself, so nothing ever fails the size check without also failing the share check. And "exactly one" counts only *size-eligible* candidates, not every candidate geometrically inside the container: a 38 pt enclosure holding an 8 pt device and a 30 pt candidate merges the 8 pt one, because the 30 pt candidate is 30/38 ≈ 0.79 of the container's side — over the 0.6 share and excluded from the count — leaving exactly one eligible candidate, which merges. A container that happens to hold two small, genuinely separate marks still merges neither, since "exactly one" fails once both qualify. This is the semantics as shipped, verified against the corpus (Task 2's fix rounds re-measured Unalaska E2.1 and Kittles EP101 after each change), not the semantics the earlier sentence in §3 describes.

### 11.4 `name` becomes a real field

§6 and §8 assume an estimator can already rename an item by editing it. Before this work, `EditIn` had no `name` field at all — `Item.name` was engine-written only. Task 8 added it as `EditIn`'s sixth editable field, validated in `edit_validation.py` alongside the other free-text fields but with its own rule: a blank name (after stripping) is refused as `invalid_name`, 422, "An item needs a name. Type what this symbol is."; a name over 300 characters is refused the same way, "That name is too long. Keep it under 300 characters."; a name that passes is stored trimmed. Accepting a legend suggestion and typing a name by hand are the same code path from this point on.

### 11.5 Two pre-existing defects fixed in passing

Both were latent before this plan touched anything, and both surfaced only because this work added the tests that could catch them.

`ITEM_SNAPSHOT_TYPES` had never been updated when `Item.suggestions` was added as a mapped column in an earlier B3c task — `decode_snapshot` raised `KeyError: 'decode_snapshot: no type given for: suggestions'` on any item delete followed by undo, regardless of whether that item carried a real suggestion. Task 7 found it running the merge suite before making any production change, confirmed it pre-existing, and fixed it with the same one-line addition its sibling `list`-typed fields (`path`, `placements`) already had.

`actions.commit()` wrote `Action.label` past its `String(300)` database column. `Item.name` has always been `String(300)`, but nothing capped an undo-toast label built from it (`f"Edited {item.name}"` is already 307 characters at a 300-character name) below the column's own limit — a latent defect that Task 8's `name` field made reliably reachable by direct estimator input for the first time, where before only the engine could write a name that long. The 300-character boundary test in Task 8's follow-up round surfaced it as a 500 (`StringDataRightTruncation`), not an assertion failure. Fixed once, in the one funnel every mutation kind writes an `Action` row through: `commit()` now truncates a label to 299 characters plus an ellipsis rather than trusting every caller to stay under the limit, covering `undo`/`redo`'s own label prefixes the same way.

### 11.6 What the corpus actually showed

`legend_symbols.templates_on` read 98 symbol templates off Unalaska's E0.1 legend sheet — well past the ≥ 25 floor above — and the entire 14-sheet Unalaska drawings PDF, legend sheet included, reads in 6.7 seconds against the worker's 120-second per-document sandbox timeout. Kittles Saxony's own legend-sheet template count was not separately measured in these tasks; what the corpus does show for Kittles is the EP101 cluster-count swing recorded in §11.2 (4 → 19 → 4 clusters as `MAX_MODIFIER_CHARS` moved 2 → 1, placements conserved at 212 throughout). The ranking results on Unalaska's E2.1 plan against the E0.1 legend are the ones §1.1 already carries: the switch cluster scored 0.81–0.88 against its legend row, the recessed-fixture cluster 0.78–0.81, the receptacles 0.61–0.76 (one junction-box cluster found no match at all, 0.12), and a duplex receptacle scored 0.86–0.90 against the unrelated ground-fault row — the measurement that motivated §11.1's pivot in the first place.

### 11.7 Known limits

The legend row band is vertical-only — a word qualifies by vertical proximity to the glyph's centre with no horizontal bound — so a tall glyph in a dense, tightly-spaced legend could in principle pull a neighbouring row's words into its own description. `counting.py`'s `tag_points` (the set of word positions already consumed as device tags, excluded from modifier detection) is keyed on rounded centre coordinates, so a modifier word whose rounded centre coincides with an unrelated consumed tag's could be wrongly excluded, suppressing a legitimate modifier. And `_project_templates` (the match job's per-project template gather) has no `order_by`, so the ordering of templates gathered across several legend sheets on one project is not guaranteed stable between reads — the single top suggestion a cluster or a drawn box ends up with is unaffected, since ranking, not gather order, decides that; only the *order of ties* below it could shuffle.

### 11.8 Open question: a renamed item's status

Accepting a legend suggestion writes `{"name": ...}` only, exactly as §8 specifies. But the server's *Needs attention* → *Ready to review* flip (`api/app/takeoff/review.py`, `_apply_edit`) keys on `category`, not `name`: it moves an item off *Needs attention* only when `category` leaves `"Unclassified"`. An item named from a legend suggestion keeps `category == "Unclassified"`, so it stays *Needs attention*, keeps its "Pick what this symbol is from the legend entries listed, or classify it by hand." warning, and — because the suggestion block itself only renders while `sel.name === "Unclassified symbol"` — loses the very block that offered the name that was just accepted. This was raised to the user mid-build and not resolved; nothing was changed, and the spec as written governs. The options, as put to the user and still open: send `category` along with the accepted name, so the item clears the same way a full classification does; gate the block's visibility on `category` rather than `name`, so a renamed-but-not-yet-categorized item still shows remaining suggestions if any; or leave the behaviour as specified and let the estimator clear the status through the normal Edit path, which already lets them set both fields at once. This document does not pick one.
