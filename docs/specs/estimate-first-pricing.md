# Estimate-first pricing — design

**Date:** 2026-09-18
**Status:** Draft for review.
**Builds on:** `labor-material-pricing.md` (the company tables and the precedence chain), `firm-price-book.md` on `feat/corpus-price-book` (the firm's previous bids as the company book — unchanged by this design, still parked).
**Changes:** the precedence chain gains two tiers; `regions.py`'s hand-typed table stops being the only thing that prices a project without a model key.

## 1. What this is for

Today a project processed without a model key prices almost every material row *Missing information*, and one processed with a key prices them from a model's guess dressed as a "Regional baseline." Neither is a number an estimator can start from.

After this design, every countable item gets a **market estimate** on the day it is counted — a real, dated, located unit price from a commercial data source, labeled as an estimate and never as the bid — and an estimator who has better numbers from their supplier uploads a price sheet that outranks it. The order a price is trusted in becomes:

1. **Project price** or **Allowance** — typed by the estimator (existing)
2. **Supplier quote** — uploaded from a supplier's price sheet, applied by the estimator (new)
3. **Company price** — the firm's own price book (existing; filled by the parked corpus loader)
4. **Market estimate** — looked up for this item in this location (new)
5. **Regional baseline** — the model's ingest-time figure, only when `pricing_source == "llm"` (existing, now rarely reached)
6. **Missing information** — nothing resolved, with a warning that names the fix

This matches how the rest of the market is built. Accubid, ConEst, and McCormick price from the firm's database first, a licensed price service (Trade Service, NetPricer) as the fill, and Excel imports of supplier pricing on top. Countfire exports an unpriced product list for the supplier to fill in and imports it back. Beam and Togal do not own pricing at all. No one in the takeoff category treats an external feed as the bid number, and neither does this.

## 2. Sources, and what the coverage test showed

Tested on 2026-09-17 against the firm's actual bid lines from the FedEx Office and Gerber Collision workbooks (`bid_examples/`):

| Item class from the bids | Home Depot / Lowe's | Distributor sites with public list prices | Google Shopping |
|---|---|---|---|
| Commodity devices (toggle switch $8, duplex/GFCI receptacles, boxes) | Yes, by store | Yes | Yes |
| Commodity gear (30A 480V NEMA 3R disconnect — Siemens HNF361R, Eaton DH361NRK) | Yes | Yes | Yes |
| Spec'd fixtures by model (Signify FLP8140L850, Current CVT8-LSCS-MV, Keystone KT-RHLED150PS, ILP Skyline) | **No** | Yes — CVT8 at $156.75 / $169.95 / $256.25 / $303.33 across four sellers | Yes |
| Engineered gear (14,500 switchboard, DEHN CG3-060 SPD, ACME boost transformer) | No | No — quote items | No |
| Lump sums and custom (wiring LS, plywood backboard, "connection to equipment") | — | — | — |

Two facts drive the design. A single retailer misses the lines that carry the money — fixtures and gear are most of the FedEx material dollars. And the same fixture spreads 2× across sellers, so a market figure has to carry its range and its sellers, never one number alone.

Two paid sources, chosen for coverage and cost:

| Source | Used for | Location | Returns | Cost |
|---|---|---|---|---|
| **1build Cost Data API** (GraphQL, `sources` query) | Every countable item — the primary estimate | ZIP → nearest county (3,000+ counties) | `materialRateUsdCents`, `laborRateUsdCents`, `uom` per source | Billed per `Source` returned; trial available; plan on request |
| **SerpApi Google Shopping** | Items whose description carries a manufacturer model number — the fixture schedule | `location` (city) | Price and seller per listing, across distributor and retail sites | 250/month free, $75/month for 5,000 |

Both need an account; neither key is in the repo. `api/.env.example` gains `ONEBUILD_API_KEY=` and `SERPAPI_KEY=`, each with the same "optional; absence is not an error" comment `ANTHROPIC_API_KEY` carries. Craftsman's *National Electrical Estimator* (9,000 electrical items, area factors by three-digit ZIP, Excel download, updated about every three quarters) is the fallback seed if 1build's electrical depth disappoints in the test — a sample-data request, not a build.

**The coverage test runs after this design is approved and the keys exist**, not before — see §10. Its result decides whether 1build alone is enough; the design assumes both.

## 3. Where the lookup runs

In the worker, as a new job kind `price`, never in the API process. The API has no egress today and should not gain some for a price feed; the worker already makes outbound calls (the classification model) and already runs every job body in `sandbox.py`'s child process with a timeout. A `price` job gets a 120 s wall clock.

**Queued** when a run's last `sheet` job completes (`queue.py` already knows when a run finishes — the same place `classify` is closed out), once per run, `run_id` carried. Also queued by the estimator from the Material pricing workspace ("Refresh market estimates"), and by the ZIP being set on a project that has items but no estimates.

**What one job does**, for every countable item on the project (rows that map 1:1 to an item, same set the Material pricing workspace lists):

1. **Classify the item for lookup**, deterministically:
   - `unit == "LS"` or a name/description matching the *quote-required* list (switchboard, switchgear, MCC, transformer, SPD, generator, ATS, bus duct, VFD, "furnish and install", "connection to", "provide power for") → `quote_required`. No lookup is spent.
   - A manufacturer model number present in `item.description` (the schedule line the engine already carries — a token of 6+ characters mixing letters, digits, and hyphens on a line starting `Model`, or following `Manufacturer:` on the next line) → **shopping** lookup on `"<manufacturer> <model>"`.
   - Otherwise → **1build** lookup on `item.name`, with `item.description`'s first line as a fallback query when the name returns nothing.
2. **Check the cache** (`market_lookups`, §4) for the same source, query key, and location key fetched within 30 days. A hit costs nothing and is reused across projects and orgs — the data is public market data, not a tenant's.
3. **Call the source**, one request per distinct query. 1build: `sources(searchTerm, zip)`, top 5, then the first whose `uom` matches the item's unit (`EA`↔`ea`, `LF`↔`ft`); no unit match → `no_match`. Shopping: every listing with a parseable USD price and an `https` link; fewer than 2 listings → `no_match`; otherwise low, median, high, and the seller list.
4. **Write** an `ItemMarketPrice` row per item (§4), and mark the job's outcome per item so the workspace can say what happened.

**Budget.** `MARKET_LOOKUP_MONTHLY_CAP` (default 2,000 per org per calendar month, config) — a job that would exceed it stops, marks the remaining items `over_budget`, and the workspace says so in the estimator's words ("Market estimates paused for this month — 2,000 lookups used"). Every billed call writes its `market_lookups` row, which is the meter; ROADMAP 3.1's "metering first" rule applies to this feed from its first paid call.

**Location.** `Project.location` is free text ("Sacramento, CA"). A ZIP is what both sources want. `Project` gains `postal_code` (`String(10)`, nullable); screen B's address form and project settings gain the field; a ZIP already inside `location` is parsed once, by the same trailing-token rule `regions.py` uses, into the new column by the migration. No ZIP → every lookup is `location_needed`, and the row's warning says to add the project ZIP code in project settings. Not a national fallback: a number with no place attached is the confidently-wrong figure this product exists to prevent.

**Keys absent.** The job runs, finds no key for a source, and marks that source's items `unavailable`. The row reads *Missing information* with the fix "Market estimates aren't set up for this workspace" — the same register as the conversation panel with no key. Never an error, never a stack trace.

**Reprocess.** A re-run re-queues `price`, which re-checks the cache and only calls the source for items with no fresh lookup. An estimator's `ProjectMaterialPrice` rows are never touched by any of this — the tier above wins at read time, and the job writes only its own table.

## 4. Data model

```python
class MarketLookup(Base):
    """One call to one source, cached. Org-independent: public market
    data keyed by what was asked and where. The row is also the meter."""
    __tablename__ = "market_lookups"
    __table_args__ = (UniqueConstraint("source", "query_key", "location_key", name="uq_market_lookup"),)
    id: Mapped[uuid.UUID]
    source: Mapped[str]            # "onebuild" | "shopping"
    query_key: Mapped[str]         # normalized query text, lowercase, whitespace-collapsed
    location_key: Mapped[str]      # ZIP for onebuild; city+state for shopping
    status: Mapped[str]            # "priced" | "no_match" | "failed"
    result: Mapped[dict | None]    # JSONB, the source's answer, trimmed (§7)
    fetched_at: Mapped[datetime]
    billed: Mapped[bool]           # False on a cache hit re-read, True on a call that counted
    org_id: Mapped[uuid.UUID]      # who paid for the call, for the cap


class ItemMarketPrice(Base):
    """The market estimate for one item, resolved from a lookup. One row
    per item at most, same pattern as ItemEvidenceImage and the two
    project-level pricing tables -- and, like them, outside
    ITEM_SNAPSHOT_TYPES: it is derived, not a person's judgment."""
    __tablename__ = "item_market_prices"
    item_id: Mapped[uuid.UUID]                 # PK, FK items.id ON DELETE CASCADE
    lookup_id: Mapped[uuid.UUID | None]        # FK market_lookups.id, null when nothing was called
    outcome: Mapped[str]                       # "priced" | "no_match" | "quote_required" | "location_needed" | "unavailable" | "over_budget" | "failed"
    source: Mapped[str | None]                 # "onebuild" | "shopping"
    query: Mapped[str]                         # what was asked, for the row's evidence
    unit_price: Mapped[Decimal | None]         # median for shopping, the source's rate for onebuild
    price_low: Mapped[Decimal | None]
    price_high: Mapped[Decimal | None]
    labor_rate_per_unit: Mapped[Decimal | None]  # onebuild only; stored, not yet resolved (§9)
    unit: Mapped[str]
    location_label: Mapped[str]                # "Travis County, TX" / "Austin, TX"
    fetched_at: Mapped[datetime | None]
    run_id: Mapped[uuid.UUID | None]
```

`ProjectMaterialPrice.source` gains a third value, `"supplier_quote"`, beside `"project_price"` and `"allowance"`. Two nullable columns join it: `supplier_name: String(200)` and `quote_date: Date`. Migration `0024_market_pricing` adds both tables, the `postal_code` column and its backfill, and the two `project_material_prices` columns.

## 5. Precedence resolution, changed

`pricing.resolve_material_price` gains one parameter, `market: ItemMarketPrice | None`, and one tier:

```
1. ProjectMaterialPrice, source "project_price"   → "Project price"     approved
2. ProjectMaterialPrice, source "allowance"       → "Allowance"         approved
3. ProjectMaterialPrice, source "supplier_quote"  → "Supplier quote"    approved   basis: "<supplier_name>, <quote_date>"
4. CompanyMaterialPrice by item.name              → "Company price"     ready | attention when > 180 days
5. ItemMarketPrice, outcome "priced"              → "Market estimate"   ready | attention when (high − low) / median > 0.5
6. item.material_cost / quantity, llm only        → "Regional baseline" ready
7. nothing                                        → None                missing
```

Tiers 1–3 are all `ProjectMaterialPrice` rows, so the "an estimator entered it" rule is unchanged: a supplier quote the estimator applied is *Estimator approved*. Tier 5's *Needs attention* case is "Wide price range" — the sellers disagree by more than half, and a person should look before it stands. Its `basis_note` is `"<location_label>, <fetched_at as Mon D>"` for 1build and `"<n> sellers, <location_label>, <fetched_at>"` for shopping. The source vendor's name is not in the row; the evidence is.

An item whose `ItemMarketPrice.outcome` is anything but `priced` falls through to tier 6 and then to *Missing information*, and the row's warning names the outcome in the estimator's words:

| outcome | title | fix |
|---|---|---|
| `quote_required` | Quote required | Engineered equipment is priced by quote. Enter the supplier's price, or upload their price sheet. |
| `no_match` | No market price found | Enter a price, add a company price for this item, or upload a supplier price sheet. |
| `location_needed` | Project location needed | Add the project ZIP code in project settings, then refresh market estimates. |
| `unavailable` | Market estimates aren't set up | Enter a price, or ask an administrator to set up market estimates. |
| `over_budget` | Market estimates paused this month | Enter a price, or upload a supplier price sheet. |
| `failed` | Market estimate didn't complete | Refresh market estimates. If it happens again, enter a price. |

Four fields every time (`found` and `where` follow the same pattern: what was asked, and the item's description on its sheet), validated where every other warning is.

**The takeoff spreadsheet, export, and item panel** read the same resolution once `firm-price-book.md` §5 ("one pricing truth") lands. Until it does, they keep reading the engine's stored `total_cost`, as they do today. This design does not pull that work forward; it adds a tier to the chain that work will read through.

## 6. Supplier price sheets

The proven shape — Countfire's — rather than parsing an arbitrary emailed quote. The platform writes the list; the supplier fills it in; the estimator uploads what came back and applies it.

**Request.** *Material pricing* gains **Download price request** — an `.xlsx` (openpyxl, new to `requirements.txt`; the corpus branch's design wants it too) with one row per countable item: `Item`, `Description`, `Qty`, `Unit`, `Unit price` (blank), `Supplier part no.` (blank), `Notes` (blank), and a hidden `Row key` column carrying the item id. The hidden key is what makes the round trip exact; matching on names is the fallback, not the plan. File name `<project> — price request — <date>.xlsx`. A filter lets the estimator send only *Missing information* rows.

**Upload.** **Upload supplier pricing** takes `.xlsx` or `.csv`. The API streams and stores it through `documents.service` as `doc_type = "Pricing"` (a sixth `DOC_TYPES` value in `documents/schemas.py`; `doc_type` is validated in `service.set_doc_type`, not by a database constraint, so no migration change for it) — it is a project document, audited and kept like one. Parsing happens in the worker (`price_sheet` job, 60 s), never in the API: a spreadsheet parser is a parser. The job produces a **preview**, stored on the job's payload, never applied:

- **Matched** — row key found, or exact name match when the key column is absent; the current unit price, the sheet's price, and the difference
- **Unmatched** — rows the sheet has that the project does not (an extra line, a renamed item); listed, never guessed
- **Unpriced** — project items the sheet left blank
- A header row that does not carry `Unit price` is a refused sheet, with copy saying which columns were expected

**Apply.** The estimator reviews the preview in a modal on the workspace, unticks any row, names the supplier and the quote date (prefilled from the filename when it parses), and applies. One `commit()` action, kind `supplier_quote_apply`, label "Applied supplier pricing from <supplier> for 41 items", `before`/`after` per row, in `undo.REVERSIBLE`. It writes `ProjectMaterialPrice(source="supplier_quote", supplier_name, quote_date, price_override)` per ticked row, replacing an existing project price on that item (the replaced value is in `before`). A checkbox, off by default, also writes each price to `CompanyMaterialPrice` with `effective_date = quote_date` through `record_company_action` — the corpus loader's rule holds: an existing company row is left alone and reported, never overwritten.

Nothing here reads the model. A sheet is untrusted input: cell text is data, rendered as text; the only cells interpreted are the price column (a number) and the row key (an id that must belong to this project).

## 7. Security and language

- The worker is the only process with these keys and the only one that calls out. The API never contacts either source.
- A source's response is trimmed before storage: 1build to `name, uom, materialRateUsdCents, laborRateUsdCents`; shopping to `title, price, source (seller name), link` per listing, links kept only when `https`. Titles are seller-written text — displayed as text in the evidence list, never fed to a prompt.
- Copy rules hold: the tier label is "Market estimate," the basis note names a place and a date, the evidence list names sellers. No vendor name, model name, or confidence on any row. The words "estimate" and "quote" do the work "AI" never does here.
- The per-org cap and the cache are what stop a 400-item hospital set from spending the month's budget on one run, and a second firm bidding the same set from spending it again.

## 8. API surface and frontend

New routes on `pricing_router.py`, same tenancy pattern as its neighbours:

```
POST /api/projects/{project_id}/market-pricing/refresh        -> 202, queues a price job (idempotent while one is in flight)
GET  /api/projects/{project_id}/material-pricing              -> MaterialRowOut gains: price_low, price_high, market_outcome, evidence (sellers list), fetched_at
GET  /api/projects/{project_id}/material-pricing/price-request -> the .xlsx
POST /api/projects/{project_id}/material-pricing/price-sheets  -> 202, stores the upload, queues price_sheet; returns the document id
GET  /api/projects/{project_id}/material-pricing/price-sheets/{document_id}/preview -> the preview, or "still reading"
POST /api/projects/{project_id}/material-pricing/price-sheets/{document_id}/apply   -> body: rows to apply, supplier_name, quote_date, save_to_company; one commit()
GET  /api/company/market-pricing/usage                         -> lookups used this month, the cap
```

`postal_code` rides the existing project create/patch routes and `ProjectOut`.

Frontend, following the one-file-one-responsibility convention:

```
src/components/pricing/
  MaterialPricingWorkspace.jsx   gains the three actions in its header, and the tier tag + range on each row
  pricingColumns.jsx             a Range column ("$157–303") shown only for Market estimate rows
  PriceSheetImport.jsx           the upload → preview → apply modal
  marketOutcomeCopy.js           the six outcomes' warning copy, one place
src/components/settings/ProjectSettings.jsx   the ZIP field
```

The tier tag stays its own element beside the status pill, `--slate`, as `labor-material-pricing.md` set out — a *Needs attention* "Wide price range" row still shows "Market estimate" next to its amber pill.

## 9. Out of scope, named

- **Labor from the market feed.** 1build's `laborRateUsdCents` is stored on `ItemMarketPrice` and not resolved. `resolve_labor` needs hours and a rate; 1build gives a cost per unit, and turning that into hours means dividing by a rate the firm may not have set. A follow-on design decides whether that tier exists.
- **Assemblies.** Rows map 1:1 to items, as before. Wire, conduit, boxes, and plates from `engine/assemblies.py` are not market-priced here.
- **Parsing an arbitrary supplier quote** — a PDF, an email screenshot, a distributor's own export with its own columns. The price request's round trip is the plan; the quote-line matcher `CLAUDE.md` names for the Pricing agent is the later design that reads anything else.
- **Store-level retail lookups by ZIP** (Home Depot/Lowe's). The test showed they cover only the cheapest rows; if county-level 1build proves too coarse on commodity items, they are a refinement tier, not a replacement.
- **Choosing among 1build candidates with a model.** Top result with matching unit, deterministically. A wrong pick is visible — the row's evidence shows what was matched — and correctable by typing a price.
- **Distributor account integrations** (Graybar's API, punchout, EDI 832). Real net pricing needs the contractor's credentials; a design of its own.
- **Editing a Regional baseline's rank.** Tier 6 stays where it is; it is reached only when both the company book and the market feed have nothing.

## 10. Testing

**Unit, no database** (`pricing.py` stays pure):
- Tier order: a supplier quote outranks a company price; a company price outranks a market estimate; a market estimate outranks a regional baseline; each lower tier is skipped when a higher one resolves.
- The wide-range boundary: (high − low) / median of 0.49 → *Ready to review*; 0.51 → *Needs attention*.
- Every non-`priced` outcome falls through, and its warning carries all four fields.
- Lookup classification: `LS` → `quote_required`; "Switch Board MSBS" → `quote_required`; "Model: CVT8-LSCS-MV" on the description → shopping with query "Current CVT8-LSCS-MV"; "20A duplex receptacle" → onebuild; a description with `Manufacturer:` but no model line → onebuild.
- Unit matching: 1build `LF` accepts item unit `ft`; `EA` rejects `ft`.
- ZIP parsing from `location`: "Unalaska, AK 99685" → 99685; "Springfield, IL" → none.

**Worker, sources stubbed** (an in-process fake per source, same pattern as the classification model's fake):
- A cache hit within 30 days calls nothing and writes `billed = False`; a miss calls once and writes `billed = True`.
- The cap: with 3 lookups left and 5 items, 3 are priced and 2 are `over_budget`; the job completes, not fails.
- No key → every item of that source `unavailable`; the job completes.
- A 1build response with no unit match → `no_match`; a shopping response with one listing → `no_match`.
- The response is trimmed to the allowed fields before storage; an `http://` link is dropped.
- A re-run prices only items without a fresh lookup.

**Price sheets:**
- The request `.xlsx` carries one row per countable item and a hidden row-key column; the filter to *Missing information* rows works.
- Upload → preview: a row key matches its item; a renamed item without a key is *unmatched*, not guessed; a blank price is *unpriced*; a sheet without a `Unit price` header is refused with the expected columns named.
- Apply writes one action with `before`/`after` per row, in `REVERSIBLE`; undo restores the prior project price or removes the row; `save_to_company` writes company rows and skips existing names.
- A row key from another project is refused (tenancy row in `test_tenancy.py`'s table, as every new route gets).

**Copy:** every new string is sentence case, names no vendor, model, or confidence, and every warning has four fields.

**Coverage, after the keys exist** — `python -m eval.pricing_coverage`, run from `api/`, with the corpus present: takes every per-unit Division 26 line from the two workbooks, classifies it as the job would, calls both sources for the FedEx and Gerber ZIPs, and prints a table — lines, priced by 1build, priced by shopping, quote-required, no-match — and, for priced lines, the market figure beside the firm's own unit cost with the ratio. No price lands in the repo (the output goes to `bid_examples/_derived/`, gitignored). This is the number that decides whether both sources stay in the design; the spec is amended with the result.

## 11. Dependencies and configuration

- `openpyxl` added to `api/requirements.txt`.
- `api/.env.example`: `ONEBUILD_API_KEY=`, `SERPAPI_KEY=`, `MARKET_LOOKUP_MONTHLY_CAP=2000`.
- `config.py`: the three settings, the key strings defaulting to `""`.
- `docker-compose.yml`: the worker already reads `api/.env`; nothing new.
