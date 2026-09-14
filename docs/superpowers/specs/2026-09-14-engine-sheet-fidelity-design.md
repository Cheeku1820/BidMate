# Engine sheet fidelity — design

**Date:** 2026-09-14
**Status:** Approved for planning.
**Supersedes:** the diagnosis in `2026-09-08-engine-sheet-fidelity-findings.md`, which measured five defects on one set. This design reaches the root cause under three of them, adds one the findings missed, and widens the target from one set to every vector set in `bid_examples/`.

## 1. What is wrong, measured

### 1.1 The root cause: geometry in the wrong frame

Every page in the Unalaska set is rotated 90°; TSC Nutrition and United Utility mix 0°, 90° and 270° within one file. PyMuPDF's `page.rect` reports the **visual** frame (2448 × 1584 for a rotated Unalaska page) while `page.get_text()` returns coordinates in the **unrotated mediabox** frame (1584 × 2448). `documents.py` builds every clip and region from `page.rect` and applies them to text in the other frame. Three consequences:

| Consequence | Measured |
|---|---|
| The title-block clip (`RIGHT_STRIP`) selects nothing, so `_sheet_number` always falls back to whole-page frequency, ties are common, and `max(set(...))` breaks them in hash order | Page 89 resolved to `E7.1`, `E6.2`, `E4.1` on three consecutive processes. 14 pages collapse to 11 numbers. Page 87 is really `E2.1`. |
| The counting region excludes the visual right ~37 % of every sheet instead of the 18 % title strip it meant to | 98 of 626 tag-shaped words on the five plan pages (16 %) are dropped before counting runs. A silent under-count. |
| Placements are unrotated-frame coordinates; `ingest.py` normalises them against the rotated `width_pt` / `height_pt` | Markers land squashed into the left two-thirds of sheet space, run off the bottom edge, and are not rotated. Evidence crops are right because `render_evidence_crop` clips in the frame the coordinates came from. **This is the original complaint** — issues not landing on the blueprint. |

### 1.2 Non-plan sheets counted as plans

No field says what kind of sheet a page is. Schedules, the legend sheet, the one-line and the lighting-controls sheet are counted as device plans: 106 of 303 Unalaska placements (35 %) are `VA`, `CKT`, `AMP`, `ON / OFF` and legend entries.

### 1.3 Titles are a constant

Every sheet is titled "Electrical plan". Nothing reads the title cell.

### 1.4 Sheet-number conventions — the reason nothing else in the corpus is read

`SHEET_ID` is `\bE\d{1,2}\.\d{1,2}\b`. Surveyed 2026-09-14 across `bid_examples/`:

| Set | Electrical PDF | Pages | Rotation | Convention | Detected today |
|---|---|---|---|---|---|
| Unalaska | `21_1001_unalaska_library_cd_biddrawings.pdf` | 94 (14 electrical) | 0 / 90 / 270 | `E1.1` | 14 |
| Kittles Saxony | `PLANS/Electrical Plans.pdf` | 11 | 0 | `E-101`, `EL101`, `EP101`, `EF-1` | **0** |
| Pulte Sagebriar | `PLANS/…Electrical.pdf` | 10 | 0 | `E-101`, `EX1`, `EX10`, `EF-1` | **0** |
| TSC Nutrition & Technology | `PLANS/…100__CD_Set.pdf` | 78, mixed disciplines | 0 / 90 / 270 | `E101`, `EQ101`, `ES101`, `EL101` | **0** |
| United Utility Supply | `PLANS/0_DRAWING SET…pdf` | 66, mixed disciplines | 0 / 90 | `E-101`, `EF-1`, `EP-1`, `ED-101` | **0** |
| FedEx, Gerber, TSC Harrison | — | — | — | raster; no text layer | 0 (correctly unreadable) |

Architectural and civil PDFs in the same folders *reference* E-sheets ("SEE E-101"), so a widened regex applied to whole-page text would pull non-electrical pages in. The sheet's own number — the one in its title block — is the only reliable discriminator.

## 2. Design

### 2.1 One frame: the visual one

All geometry in the Documents and Counting agents is in the **visual frame** — `page.rect`, what the estimator sees and what a rendered page image shows. The transform happens once, at the extraction boundary: word and drawing coordinates from PyMuPDF are mapped through `page.rotation_matrix` before anything reads them. Clips are expressed visually and mapped back through `page.derotation_matrix` where PyMuPDF needs mediabox-frame input. `DetectedSheet.width_pt` / `height_pt` remain visual (they already are). Placements become visual. `ingest.py`'s normalisation is then correct with no change.

`render_evidence_crop` receives visual coordinates and passes them straight to `get_pixmap(clip=…)`, which takes a **visual** clip (measured 2026-09-14: a visual clip renders the glyph, an unrotated one renders blank). No transform there. `get_textbox`, by contrast, wants an unrotated clip — the API is mixed, which is why `page_frame.py` is the only place the two frames meet.

Rejected: derotating only the clips (leaves the marker bug); keeping everything in the mediabox frame and rotating in the client (pushes page-rotation knowledge into the canvas, which will render page images that are already rotated).

### 2.2 Locating the title block

A title block is a strip along one edge of the visual page. Which edge varies by firm. Detection, per page:

1. For each of the four edge strips (outer 18 % of width or height), find the type size of the largest *sheet-number-shaped* token it holds — any discipline's, `[A-Z]{1,3}-?\d{1,3}(\.\d{1,2})?` — and count *distinct* sheet-number-family tokens (§2.5) (a revision table repeating one other sheet's number three times must not outscore the strip holding the actual number cell) plus the labels `SHEET`, `DRAWN`, `CHECKED`, `DATE`, `PROJECT`, `REVISION`.
2. The strip holding the largest token is the title block; the count breaks the tie, which arises whenever the number cell sits in the corner two strips share. Size first, because the number cell is display type and everything else shaped like a sheet number is body type: a general-notes block along one edge saying `SEE SHEET E-000 / E-501 / E-502 / E-601 AND E-602` (Kittles Saxony EP102, five distinct tokens and four `SHEET` labels), a fan schedule's `EF-1 … EF-6`, a cover's drawing index, an equipment tag spilling in from the drawing (TSC Nutrition, 2026-09-14) all out-counted the real title block. The tiebreak counts *family* tokens only — the any-discipline shape also matches circuit tags (`BPW-3`, `UH-4`), and a plan's bottom strip holds dozens. If no strip scores, the page has no readable title block and **is not detected as an electrical sheet**. And **a sheet is a drawing**: a page with zero drawing paths and zero images — a project-manual page whose left column says `SHEET / E7.1 / DATE` — is not a sheet whatever its strips say. Zero, not a count: Pulte Sagebriar's 323-path riser diagram is a sheet. This is deliberately conservative: an electrical page with an unreadable title block is a page the per-set fixture test (§3.1) will name, and a fix can be aimed at it; an architectural page pulled in because it says "SEE E-101" is a phantom sheet nobody looks for.

The counting region is the visual page minus a 3 % border minus the detected strip. `RIGHT_STRIP` stops being a constant.

### 2.3 Sheet number — deterministic

Within the title-block strip: the sheet-number-shaped token (any discipline) **set largest**, then among those the one **nearest the page corner the strip ends at** — bottom-right for a bottom or right strip, top-right for a top strip, bottom-left for a left strip; drafting convention puts the number cell there. **Two or more distinct tokens sharing the largest size are an index, not a number cell** — a cover's drawing index runs down a strip with every row in one face, and picking from it by corner is picking by row order (Unalaska's and TSC Nutrition's covers) — so the strip holds no number cell and the page is not a sheet. Frequency within the strip, then first appearance in reading order, order the instances of the one number (a callout bubble set as large as the cell). The page is an electrical sheet only when that token is in the family (§2.5): a mechanical sheet whose corner cell reads `M1.01` is read as `M1.01` and rejected, rather than having an `EF-7` tag from elsewhere in its strip taken as its number. No `set()` iteration anywhere in the path — a regression test runs `detect_sheets` in three subprocesses with different `PYTHONHASHSEED` and asserts identical output.

A strip that holds no family token means the page is not an electrical sheet (§2.5).

### 2.4 Sheet kind

`DetectedSheet.kind`, closed set: `plan`, `schedule`, `legend`, `diagram`, `other`. Decided in order:

1. **Title-block title** (§2.6) — contains `SCHEDULE` → `schedule`; `LEGEND`, `SYMBOLS`, `ABBREVIATIONS` → `legend`; `ONE-LINE`, `ONE LINE`, `RISER`, `DIAGRAM`, `DETAILS`, `CONTROLS` → `diagram`; `PLAN` → `plan`; `COVER`, `INDEX`, `NOTES` → `other`.
2. **Content markers**, when the title decides nothing — ≥ 2 distinct schedule headers (`PANEL SCHEDULE`, `LUMINAIRE SCHEDULE`, `FIXTURE SCHEDULE`, `EQUIPMENT SCHEDULE`, `MECHANICAL SCHEDULE`) and no scale label → `schedule`; `ON / OFF` repeated ≥ 4 times and no scale → `diagram`; a scale label present → `plan`.
3. **Unsure → `plan`.** Over-counting is visible in review; omission is silent.

`count_sheet` returns `[]` for any sheet whose kind is not `plan`. The legend sheet still feeds `parse_legend` — it stops contributing devices, nothing else.

### 2.5 Sheet-number family

`SHEET_ID` becomes `\bE[A-Z]{0,2}-?\d{1,3}(?:\.\d{1,2})?\b`, covering every convention in §1.4. Because the family is broad enough to match device tags (`E1`) and equipment tags (`EQ101`), it is **never** applied to whole-page text to decide whether a page is electrical. A page is an electrical sheet when, and only when, the token in its title-block number cell (§2.3) is in the family. There is no whole-page fallback.

### 2.6 Title

From the title cell: the largest-type text line(s) within reach of the number cell — leaving out *value lines* (every token more digits than letters: a project number `24108` or `25-0107LE`, a date) and *issue stamps* (`RELEASED FOR CONSTRUCTION`, `NOT FOR …`, `ISSUED FOR …`, `PRELIMINARY`, `BID SET`), which are cells of the block or marks across it, never the title — joined with spaces and sanity-checked as a whole cell — 2 to 10 words, no digits-only tokens, none of `SUITE`, `BOULEVARD`, `STREET`, `PHONE`, `CHECKED`, `DRAWN`, `DATE`, `REGISTERED`, `PROFESSIONAL`, `ENGINEER`. When the check fails, the title is the kind label: `Electrical plan`, `Schedule`, `Legend`, `Diagram`, `Sheet`. Titles are sentence case on the wire (`Panel schedule`, not `PANEL SCHEDULE`) per the copy rule.

### 2.7 Store and interface

- `Sheet.kind` column, `String(20)`, default `plan`, server default `plan`; migration `0018`, reversible.
- Wire: `estimate.full_takeoff` emits `kind` per sheet → `ingest.py` validates it against the closed set (unknown → `plan`, and a log line) → `SheetOut.kind` → `api-mapping.mapSheet` → `sheet.kind`.
- `SheetsRail`: for `kind !== "plan"`, render the kind label after the number in the existing secondary text style — `E0.3 · Panel schedule`. No new filter, no new colour, no status component. Kind is a sheet property on its own axis; the four review labels are untouched.

### 2.8 Out of scope, named

- Schedule *blocks* embedded on plan sheets (the remaining residue of the old finding #5).
- Two pages genuinely carrying the same sheet number — that is revision handling.
- Raster sets (FedEx, Gerber, TSC Harrison) — they remain `unreadable_reason`, correctly. This design must not change that. **Pages of outlined text are ruled the same way** (2026-09-14): TSC Nutrition's fourteen electrical pages carry no text layer — the text was outlined to drawing paths — so a page with no words and substantial drawing content (`OUTLINED_MIN_DRAWINGS` paths) is detected with `number ""`, title `Sheet with outlined text`, kind `other` and its own reason, through the same emission the scan path uses. Reading outlined text is out of scope; hiding the page is not.
- Discipline detection beyond "the number is in the E family."

## 3. Testing

**Counting is tested, not trained.** Every assertion below is against a value a person can verify by opening the PDF.

### 3.1 Per-set fixtures

For each of the five vector sets, a checked-in fixture `api/tests/fixtures/sheets/<set>.json` records, per electrical page: `page_index`, `number`, `kind`, `rotation`. The implementer writes each fixture **by reading the title blocks**, not by running the engine and copying its output. The fixture is the answer key.

A parametrised test loads each set (via `BIDMATE_BID_SET`'s directory, `bid_examples/`, skipping with a printed reason when absent) and asserts:

- the detected page set equals the fixture's page set — no architectural or civil page leaks in, no electrical page is missed;
- every detected `number` and `kind` equals the fixture's;
- numbers within a set are distinct (with the fixture allowed to declare a known duplicate explicitly, so a revision reissue is a recorded fact rather than a test failure).

### 3.2 Determinism

`detect_sheets` on Unalaska in three subprocesses with `PYTHONHASHSEED` = 0, 1, 2: byte-identical output.

### 3.3 Frame correctness

- Every placement on every vector set lies inside `[0, width_pt] × [0, height_pt]`.
- On one rotated Unalaska plan page and one 270° TSC Nutrition page, a hand-chosen device tag's visual coordinate, when a small square around it is rendered from the page's rotated pixmap, contains that tag's glyph (assert via `page.get_textbox` on the derotated clip returning the tag). This is the test that proves markers will sit on the drawing.
- Unalaska plan placements after the fix: **≥ 197 and ≤ 330** on the eight plan pages — the lower bound is what the mis-framed region left, the upper bound guards against the seal and schedules coming back.

### 3.4 Kind gating

- Unalaska: pages 80, 81, 82, 91, 92, 93 produce zero placements; page 80 still yields a non-empty `legend`. (Pages 83 and 90 are E1.0 Site plan and E5.1 Enlarged floor plans per the E0.1 drawing index — plans, not the one-line and equipment schedule the earlier findings called them.)
- Raster sets: every page detected carries `unreadable_reason`; none carries placements.

### 3.5 Existing regression tests

`test_engine_counting.py`, `test_engine_legend.py`, `test_engine_pipeline.py` keep passing. Where an asserted count changes because the region is now correct, the new value is verified by hand before the assertion moves.
