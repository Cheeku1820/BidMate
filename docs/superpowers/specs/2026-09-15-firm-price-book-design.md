# The firm's price book — design

**Date:** 2026-09-15
**Status:** Approved for planning.
**Implements:** `2026-09-13-full-webapp-plan.md` §1.2 tasks 1, 2, 6 and Phase C §4.4 ("firm price book as the default tier"), pulled forward.
**Builds on:** `2026-08-31-labor-material-pricing-design.md` — the company tables, the precedence chain, and its decision that entries key on `item.name`. This design changes none of that; it fills the tables with a real firm's numbers and makes every consumer read through the chain.

## 1. What this is for

The product has a precedence chain and empty company tables. Two of the eight bid folders carry the estimator's own estimate workbooks — the FedEx Office and Gerber Collision bids — on one 17-column template, with unit labor hours, unit material costs, a labor rate and a markup stack for every line they priced. That is the first real pricing source this project has had. This design turns it into the company's price book and makes the whole product price from it.

Two halves:

1. **The book exists.** Parse the workbooks into a dataset, bridge the estimator's item names to the engine's, derive one unit-hours and one unit-price per item, and load them into `CompanyLaborHoursOverride` and `CompanyMaterialPrice` through the audit log.
2. **One pricing truth.** Today the Labor and Material workspaces resolve through `pricing.py` (company book first), while the takeoff spreadsheet, the export preview and the item panel read the engine's stored `total_cost` straight off the item. Loading the book would make the Labor tab and the spreadsheet disagree. After this design, every consumer resolves through the same chain.

Nothing in it is invented. Every number the loader writes is one the firm typed into a bid.

## 2. Electrical only

The firm bids Division 26. Both workbooks carry a `01 00 00 GENERAL CONDITIONS` section (final and daily cleanup, project planning, lump sums) above `26 00 00 ELECTRICAL`. The rule:

**The CSI section heading a line sits under decides. Only lines under a Division 26 heading (`26 xx xx`) enter the price book or the loader.** Lines under any other section are recorded in the dataset with their section — Phase E's general-conditions design wants to see them — and are never priced. Lump-sum lines (`LS` unit) under Division 26 are recorded but never enter the book either; the book holds per-unit values only (`EA`, `LF`, and the like).

What the estimator files under 26 is electrical for this purpose. FedEx lists telephone equipment and cable outlets there; they enter the book under the names the estimator gave them. Discipline is decided by the section heading the firm chose, never by reading the description.

## 3. The dataset

### 3.1 Sources, measured 2026-09-15

| Folder | File | Sheets | What it is |
|---|---|---|---|
| FedEx Office Bid | `Fedex Office.xlsx` | `ESTIMATE` (294 × 20) | One estimate sheet, header on row 5 |
| Gerber Collision & Glass Bid | `Renovation for Gerber Collision & Glass.xlsx` | `PHASE I`, `PHASE II (2)` (detail), `SUMMARY BID` (roll-up) | Header on row 6; the summary carries each phase as one `LS` line |
| Pulte Sagebriar Clubhouse | `LIGHTING COUNTS/Sagebriar Fixture Counts.xlsx` | `Sheet1` (46 × 3) | Fixture type → count. No pricing. |
| TSC Nutrition & Technology | `Lighting Counts/…xlsx` | `Sheet1` (15 × 2) | Fixture type → count. No pricing. |

The four other folders carry no workbook.

### 3.2 The template

Seventeen columns, in this order, on a header row that may sit on row 5 or 6:

`SR #`, `DWG. NO.`, `DETAIL NO.`, `CSI NO.`, `DESCRIPTION`, `QTY.`, `WASTE`, `QTY. W/ WASTE`, `UNIT`, `UNIT LABOR HOURS`, `TOTAL LABOR HOURS`, `LABOR RATE`, `TOTAL LABOR COST`, `UNIT MATERIAL COST`, `TOTAL MATERIAL COST`, `TOTAL`, `TOTAL COST`.

The parser finds the header by matching the first five names, wherever the row is, and refuses a sheet whose header does not match — a new template is a new parser, not a guess.

Rows are one of: a **section heading** (`CSI NO.` filled with a `NN 00 00` code and `DESCRIPTION` in caps, no quantity); a **group heading** (`DESCRIPTION` only — "Power Fixtures", "Electrical Panels"); a **line** (`QTY.` filled); a **subtotal** (`DESCRIPTION` = `Sub Total`, skipped); or a **markup row** (`SR #` column reads `SUB - TOTAL`, `OVERHEAD AND PROFIT`, `TAX`, `BID BOND`, `CONTIGENCIES`, `TOTAL TRADES COST` — the misspelling is the firm's and is matched as written).

### 3.3 Records

**`LineRecord`** — one per line row:

```
bid, sheet, section_csi, section_name, group, sr, dwg_no, detail_no,
description, qty, waste, qty_w_waste, unit,
unit_hours, total_hours_stored, total_hours_computed,
rate, total_labor_stored, total_labor_computed,
unit_material, total_material_stored, total_material_computed,
literal_totals: list[str]   # which of the four total columns were typed values, not formulas
```

`*_computed` is `qty_w_waste × unit_*` (and `× rate` for labor cost). `*_stored` is the cell's evaluated value. The two disagree on a **stale row** — FedEx row 19 stores 20.16 hr and $540 against qty 2 × 0.56 hr × $15, left over from an earlier quantity of 36. `literal_totals` records *why* it could drift: FedEx types its totals; Gerber's phase sheets use formulas. This is the stale-row signal the full plan asks for, and the dataset keeps both numbers rather than picking one.

**`MarkupRecord`** — one per sheet that carries the markup block:

```
bid, sheet, rate_overhead_profit, rate_tax, rate_bond, rate_contingency,
applies_to: "labor_and_material",   # both bids: each rate × the same subtotal, summed
subtotal_labor, subtotal_material, total_trades_cost
```

Measured: FedEx 0.20 / 0.08875 / 0.015 / 0.03; Gerber 0.10 / 0.07 / 0.015 / 0.03. Both apply every rate to labor and material alike and sum them — an additive stack, tax included on labor. Recorded, not judged; the Estimate summary workspace (Phase E) is where the estimator owns this.

**`CountRecord`** — `bid, fixture_type, count` from the two count sheets. Count truth for the Counting and Classification evals on Pulte and TSC. This design records them; nothing here asserts against them.

**`RollupRecord`** — Gerber's `SUMMARY BID` lines (`Phase 1`, `Phase 2` as `LS`), kept so the dataset can show the summary reconciles to its phases. Never in the book.

### 3.4 Names

`api/eval/corpus/names.json` — a hand-written map from the estimator's description to the name the engine gives the same item:

```json
{
  "Duplex Receptacle": "20A duplex receptacle",
  "GFCI Duplex Receptacle": "20A GFCI receptacle",
  "Junction Box": "Junction box",
  "Panel Board": "Panelboard",
  "Boost Transformer 208-480V": "Boost transformer 208-480V"
}
```

Where the catalog (`api/app/engine/catalog.py`) has the item, the value is the catalog's display name — that is what `item.name` carries on an engine-classified item, and the pricing chain matches on it exactly. Where the catalog has no such item, the value is a cleaned form of the estimator's own words; it enters the book under that name and starts matching the day Phase C adds the item. A description absent from the map is **listed in the summary as unmapped and excluded from the book** — never guessed, never dropped silently.

The map is the one hand-curated artefact. It is committed (it holds names, not prices).

### 3.5 The price book

Per normalized name, from Division 26 per-unit lines only:

```
name, unit,
hours_by_bid: {bid: unit_hours}, price_by_bid: {bid: unit_material},
hours: <value from the latest bid by plan date>, price: <same>,
effective_date: <that bid's plan date>,
bids_seen: N, hours_spread: max/min - 1, price_spread: max/min - 1,
disagrees: hours_spread > 0.25 or price_spread > 0.25
```

Latest bid wins — a firm's current number is the one on its most recent bid. **The bid's plan date** is read from the workbook's `Date of plans` cell when that cell is a date (Gerber's is an Excel serial); when it is not (FedEx's holds an address — the template's header rows are misaligned), it comes from `api/eval/corpus/bids.json`, a hand-entered, committed file of `{bid: {plan_date, source}}` where `source` names the bid document the date was read from. A bid with a date in neither place is a build error, not a guess. A spread above 25 % is flagged so a person looks, never averaged away. `rate` is recorded once for the book (both bids: 85.00) with its date.

### 3.6 The build

`python -m eval.corpus build`, run from `api/`, writes into `bid_examples/_derived/` (gitignored — a firm's pricing stays out of git like its drawings):

| File | Contents |
|---|---|
| `lines.csv` | every `LineRecord` |
| `markups.json` | every `MarkupRecord` |
| `counts.csv` | every `CountRecord` |
| `rollups.csv` | Gerber's summary lines |
| `price_book.json` | §3.5 |
| `summary.md` | counts per bid and section, per-unit lines under Division 26, names mapped / unmapped (listed), stale rows (listed by bid and row), book size, disagreements (names only) — **never a price or an hour** |

Deterministic and idempotent: the same folders produce byte-identical output. The summary is safe to paste into docs.

## 4. The loader

`python -m app.load_price_book --org-email <admin> --book bid_examples/_derived/price_book.json`, in the `create_admin` management-command pattern.

For each book entry: insert a `CompanyLaborHoursOverride(item_name, hours_per_unit)` and a `CompanyMaterialPrice(item_name, unit_price, effective_date)` for the admin's org, **through `record_company_action`** with `label` reading as estimator-facing copy ("Loaded company hours for 20A duplex receptacle from the bid corpus") — the same path `pricing_router.py`'s PUT endpoints take, so every loaded value is in the audit log attributed to the admin who ran it. A name that already has a row is **skipped and reported**, never overwritten — an estimator's own entry outranks the corpus. `CompanyLaborRate.journeyman_rate` is set to the book's rate only when it is still zero. The command prints what it wrote, what it skipped, and what it left alone.

It is a loader, not a seed: it moves the firm's real numbers from their file into their library, once, audited. Running it twice is a no-op.

## 5. One pricing truth

### 5.1 The change

`snapshot.py` builds `ItemOut` today by copying `item.material_cost`, `item.labor_cost`, `item.total_cost` — the engine's stored numbers. After this design it resolves them through `pricing.resolve_material_price` and `pricing.resolve_labor`, exactly as `pricing_router.py`'s `material-rows` and `labor-rows` endpoints do, and serialises:

```
material_cost   = unit_price × quantity        (None when unresolved)
labor_hours     = adjusted hours               (None when unresolved)
labor_cost      = hours × rate                 (None when unresolved)
total_cost      = material_cost + labor_cost   (None when either is)
material_source = "Company price" | "Regional baseline" | "Project price" | "Allowance" | None
labor_source    = "Company standard" | "Estimated basis" | "Estimator entered" | None
```

`None` on the wire is *Missing information* on the screen — the cell reads the words, never `$0.00`. That is the same vocabulary the pricing rows already use for the same condition, and it is a cost-cell state, not the item's review label: an item can be *Ready to review* with a *Missing information* cost, because evidence and price are different questions.

Company rows are fetched **once per snapshot** — every `CompanyMaterialPrice` and `CompanyLaborHoursOverride` for the org whose `item_name` is in the snapshot's item names, plus the org's `CompanyLaborRate` — then resolved per item in memory. `pricing_router.py` already does this per endpoint; the two lookups move into one shared function both call, so the snapshot and the workspaces cannot drift.

The engine's stored `item.material_cost` / `labor_hours` / `labor_cost` stay on the row and stay populated at ingest and reprocess. They are tier 4 of the chain and nothing else reads them.

### 5.2 Consumers

- `api-mapping.mapItem` carries `materialSource`, `laborSource`, and passes `null` through as `null` (today it coerces to `Number(… ?? 0)`, which is the `$0.00` this design removes).
- **Takeoff spreadsheet** (`spreadsheetColumns.js`): the cost columns render *Missing information* for `null`, and a **Source** column shows `materialSource` / `laborSource` when they differ from each other, else the one label.
- **Export preview** (`ExportPreview.jsx`): same cells, same words; the CSV carries the source label in its own column and leaves the cost cell empty (not zero) when unresolved.
- **Item panel**: unchanged shape, `null` shown as *Missing information*.
- **Labor and Material workspaces**: unchanged — they already resolve through the chain. After this design they agree with the spreadsheet by construction.

### 5.3 What the engine does at ingest

Unchanged. It runs in the browser-to-`:8100` path without database access and cannot consult the book, so it keeps producing its LLM or deterministic baseline; `Project.pricing_source` keeps recording which. The book wins at read time everywhere. For a name the book covers, the LLM's number is simply never shown. Trimming the LLM *call* to uncovered names is a Phase B change (engine behind the API), and out of scope here.

### 5.4 Precedence order

Unchanged from `2026-08-31-labor-material-pricing-design.md` §"Precedence resolution". Project override → company book → LLM baseline (only when `pricing_source == "llm"`) → *Missing information*. Name matching stays exact on `item.name`.

## 6. Out of scope, named

- Catalog expansion (Phase C §4.3) — the names map bridges to today's eleven catalog items; the rest wait under their own names.
- Assemblies in the app path (Phase C §4.4).
- Fuzzy or alias name matching.
- Any change to the precedence order.
- The Estimate summary workspace and the markup stack's use (Phase E) — recorded here, applied there.
- Trimming the LLM call to uncovered names (Phase B).
- The count sheets as engine assertions — recorded here, asserted by the Counting/Classification eval later.

## 7. Testing

**Synthetic workbooks**, built with `openpyxl` into `tmp_path` on the template, with formulas and literals placed deliberately:
- parse finds the header on row 5 and on row 6; refuses a foreign header;
- section, group, line, subtotal and markup rows are classified; a line under `01 00 00` carries that section; a `LS` line is a line but not a book candidate;
- a typed total that disagrees with `qty × unit` yields a `LineRecord` with `stored ≠ computed` and the column in `literal_totals`; a formula total yields `literal_totals == []`;
- the markup block parses to the four rates and `applies_to`;
- normalize maps a known name, leaves an unknown one unmapped and listed;
- the book takes the latest bid's value, computes spread, flags > 25 %, excludes non-26 and `LS` lines;
- the build is deterministic (two runs, identical bytes).

**Corpus-gated** (skip with a printed reason when `bid_examples/` is absent): FedEx parses to its markup stack exactly (`0.2, 0.08875, 0.015, 0.03`); FedEx row 19 is a stale row; every name in `names.json` that appears in either workbook is mapped; the summary contains no `$` and no decimal that matches a book value.

**Loader** (test database): writes rows and one company action per row with an estimator-facing label; skips an existing name and says so; sets the rate only when zero; a second run writes nothing.

**One pricing truth** (test database): a project with a company-priced item snapshots that item at the company unit price × quantity with `material_source == "Company price"`; an unpriced item on a deterministic project snapshots `total_cost is None`; the snapshot's numbers equal `material-rows` / `labor-rows` for the same project (the invariant, asserted); `mapItem` passes `null` through; the spreadsheet renders *Missing information*, not `$0.00`; the export CSV leaves the cell empty and fills the source column.

**Copy**: every new estimator-facing string — action labels, source labels, the *Missing information* cell — is sentence case with none of the banned words, and names no model, mechanism, or confidence.

## 8. Dependencies

`openpyxl` added to `api/requirements.txt`. Nothing else.
