# From prototype to a working product — the full plan

**Date:** 2026-09-13
**Status:** Proposed; corpus facts and estimates updated 2026-09-13 after the eight bid folders were measured. This is a roadmap-level plan. Each phase below needs its own executable, task-level plan before anyone builds it.
**Supersedes for sequencing:** `docs/archive/full-mvp.md` (its keystone — injecting engine JSON into a localStorage seed store — is gone; the api store replaced it). `ROADMAP.md` and `BUILD-STAGES.md` remain the inventory; this document is what to do with it given what the code actually does today and what the seven real bids give us.

---

## 0. Where things actually stand

The docs say eleven screens are "routed and built." Routed is true. Here is what each one does when a real estimator sits down in front of it, verified against the code on `integration/full-stack` (the local branch that stacks PRs #2 → #3 → #4 → #5, none of which are merged).

### 0.1 The four facts that shape everything else

**1. The browser talks to an unauthenticated engine directly, and no document is ever stored.**
`src/lib/engineClient.js` posts the raw PDF from the browser to `http://localhost:8100` — `api/estimate_service.py`, a separate FastAPI app with no auth, no database, and CORS `*`. The File objects live in a module-level `Map` (`src/lib/uploadedFiles.js`); a page reload during processing loses the upload. There is no `Document` model in the API, no object storage, no job queue, no per-sheet job records. `ProcessingStatus.jsx` drives its stage indicator on a timer while one HTTP request is in flight. This was the right shortcut for a demo and is the single biggest structural gap between here and a product.

**History as of B2.** Everything in this fact was true when it was written (2026-09-13) and is no longer true on `feat/engine-behind-api`: `engineClient.js` and `estimate_service.py` are both deleted, documents are stored (B1) and read by a worker off a `jobs` table (B2, [`docs/specs/engine-behind-the-api.md`](../specs/engine-behind-the-api.md)), and screen E polls real per-sheet state. Left as written below because it is the audit that motivated Phase B and the corpus work; do not read it as the current state of `main`, where none of Phase A–B has merged yet either.

**2. The canvas has no drawing behind it.**
`PlanDrawing.jsx` is "honest blank paper" — the `2026-08-30-blueprint-evidence` spec removed the full-page backdrop rather than fixing it ("the full-page backdrop is gone, not fixed"). Markers float on a page carrying only the sheet number and title; the per-item evidence crop is the only view of the real drawing. The signature screen of the product — "it found 96; show me where" — does not exist yet. Calibration UI exists but has nothing to calibrate against.

**3. The engine cannot read any of the seven bids as they are.**
Counting is text-tag based (`^[A-Z]{1,3}\d{0,2}$` tokens standing alone in the text layer). On the one real vector set it was built against (Unalaska, tier B) it counted 812 placements of which ≥21% were seal letters and schedule headers before the rotation filter. Measured on 2026-09-13 across all eight folders in `bid_examples/`: **five sets are vector with a text layer** (Unalaska, Kittles Saxony, Pulte Sagebriar, TSC Nutrition & Technology, United Utility Supply) and **three are raster** (FedEx and Gerber are PlanSwift overlays printed via "Microsoft: Print To PDF" — zero paths, zero text; TSC Harrison fire alarm is scanned). The engine reads the vector five in principle and marks the raster three unreadable. On the one vector set it has been run against it still counts schedule headers, legend entries and one-line diagrams as devices — 106 of 303 placements — see §4.1. So "reads" today means "produces a takeoff that needs those fixes before the numbers mean anything."

**3b. The corpus is smaller on the pricing side than on the drawings side.** Four folders carry the estimator's Excel workbook (FedEx, Gerber, Pulte Sagebriar, TSC Nutrition); four do not (Kittles Saxony, United Utility, TSC Harrison, Unalaska). Two folders — Pulte Sagebriar and TSC Nutrition — carry all three of drawings, workbook and the estimator's own lighting counts, which makes them the only complete (drawings → approved takeoff) pairs and the anchors for every accuracy claim.

**4. Pricing is a language-model guess or *Missing information*, and nothing else.**
`llm.py` returns material cost, labor hours, a location labor rate and a material factor from one Claude call. Without a key, every labor and material row shows *Missing information* by design (`docs/specs/labor-material-pricing.md`, "no hardcode"). The static `catalog.py` price book is eleven items with placeholder figures. There is no assembly expansion in the shipped path, no supplier quotes, no price-book import. The four Excel workbooks are a real firm's unit labor hours and unit material costs across ~150 line items — the first real pricing source this project has had.

### 0.2 Screen by screen

| Screen | Routed | What works | What doesn't |
|---|---|---|---|
| Login | ✓ | Email/password sessions, one org, one role | No invitations, no MFA, no password reset, no roles |
| A Projects dashboard | ✓ | List, filters, stage from `projectStage.js` | Stage is inferred client-side; no "needs review" counts from the server |
| B New project | ✓ | Name, location, bid date | No building type flowing anywhere that uses it |
| Project overview | ✓ | Stage, counts | — |
| C Upload documents | ✓ | Multi-file drop, per-file type, content sniff via `/classify` | **Nothing is uploaded.** Files stay in browser memory. No duplicate, password-protected, or corrupt handling |
| D Confirm drawings | ✓ | Renders detected sheets | Sheet list comes from the same in-flight engine call; no include/exclude that survives; no revision or scale correction that reaches the engine |
| E Processing | ✓ | Real error copy when the service is down | Progress is a timer, not per-sheet state; not resumable; one request for the whole set |
| F Blueprint takeoff | ✓ | Markers, selection, status rings, evidence crops, item panel, approve/edit/reject/delete, undo/redo (server-backed, compound scale action), presence, finish-review blocking, shortcuts | **No drawing image.** No add-item, no find-similar, no measured runs (`Item.path` never populated), no region select, no "not examined" overlay, no layer for rejected |
| G Takeoff spreadsheet | ✓ | Flat table, sort, bulk approve restricted to *Ready to review*, cost columns | No grouping, column visibility, resize, fill-down, multi-select, keyboard manners; no import |
| Notes & assumptions | ✓ | CRUD, apply-and-re-run through `reprocess.py` | Not undoable; no `applied_action_id`, no sheet-scoping, no item-scoped notes (spec's own "not built" list) |
| Labor | ✓ | Per-item hours, company overrides, rate precedence, staleness | No crew mix, no adjustments UI, no NECA units — the "units" are LLM output |
| Material pricing | ✓ | Per-item price, company price list, precedence, audit via `company_actions` | No supplier quotes, no price-sheet upload, exact-name matching only, no assemblies |
| Assemblies | disabled | — | Unbuilt; `assemblies.py` exists in the engine but nothing in the app reads it |
| Estimate summary | disabled | — | Unbuilt. Markup/tax/bond/contingency live nowhere — `CompanySettings` "markup" tab is on `localStorage` |
| Revisions | disabled | — | Unbuilt; `Sheet.superseded` exists and is never set |
| Final review | disabled | — | Unbuilt; `FinishReviewModal` on F does part of this |
| H Export | ✓ | CSV reconciled to the totals query, blocking rules | CSV, not `.xlsx`; no exclusions/clarifications block, no revision stamp |
| I Accuracy | ✓ | An honest empty state | Nothing to compare against; no benchmark corpus |
| J Company settings | ✓ | Labor rates and material prices via API | Profile, markup, export-preferences tabs on `localStorage` |
| K Project settings | ✓ | — | Entirely `localStorage`; no overrides reach the server |
| Instant estimate | ✓ | Demo page against the standalone service | Demo; should not ship as a nav item |
| Company library, Integrations, Help | disabled | — | Unbuilt |
| Conversation panel | — | `engine/conversation.py` routes an utterance to a typed proposal (80 lines, tested) | No panel, no threads, no anchors, no proposals reaching the store |

### 0.3 Infrastructure

- **Tests:** 40 backend files (~590 `def test_`), 38 frontend files. CI runs both on PRs and pushes to `main`; green on #5. It is the first thing that ever exercised the Alembic chain.
- **Branches:** four open stacked PRs. `main` is a month behind. A "Deploy to GitHub Pages" workflow ran and failed twice on `main` and the file no longer exists — there is **no deployment target of any kind**.
- **Sync:** poll. **Undo:** shared linear stack. **Roles:** none. **Storage:** none. **Queue:** none. **Observability:** `observability.py` structured logs, no error tracker, no metrics.
- **Two stale worktrees** under `.claude/worktrees/` carry full copies of the repo (excluded from vitest since #5; should be deleted).

---

## 1. What the eight bids are, and what to do with them before building anything

What each folder actually holds, measured 2026-09-13 (`bid_examples/`, gitignored — NDA'd):

| Bid | Drawings | Tier | Workbook | Count truth |
|---|---|---|---|---|
| Pulte Sagebriar Clubhouse | PLANS / SPECS | vector + text | ✓ | lighting counts |
| TSC Nutrition & Technology | PLANS / SPECS / ADDENDUMS | vector + text | ✓ | lighting counts |
| Kittles Saxony | PLANS / SPECS / ADDENDUMS | vector + text | — | — |
| United Utility Supply | PLANS / SPECS / Addenda | vector + text | — | — |
| Unalaska Library | full bid set + addenda | vector + text | — | (engine tests) |
| FedEx Office | PlanSwift overlay only | raster | ✓ | overlay legend |
| Gerber Collision & Glass | PlanSwift overlay only | raster | ✓ | overlay legend |
| TSC Harrison HS Fire Alarm | 15 sheet PDFs + manual | raster (scan) | — | — |

The workbook is the answer key — line items, quantities, unit labor hours, unit material, the markup stack. A PlanSwift overlay is the estimator's own count markers over the sheets they took off, with per-type totals in a legend. The FedEx teardown showed the counts transfer cleanly between the two; the errors are all downstream of counting — scope, stale cells, notes never converted to lines.

**These are the most valuable files the project has**, and they are worth a deliberate week before any feature work, because they change what the engine is built against and what the pricing layer is seeded with.

### 1.1 The question that was to be answered first — answered

**Do the original bid drawing sets exist?** Yes for five of eight, and they are vector with a text layer. That settles two things this plan previously hedged on:

- `docs/product/mvp-approach.md` §9's question — which tier real sets arrive in — has a measured answer: **5 vector, 3 raster**, across eight sets from one firm. Vector is the majority. Tier-B geometry clustering (4.2) is therefore the engine priority and has five fixtures instead of one; tier-C raster counting is needed for three sets and can follow.
- The benchmark corpus `ROADMAP.md` 3.4 depends on exists in embryo: **two complete (drawings → approved takeoff) pairs** — Pulte Sagebriar and TSC Nutrition — plus three vector sets with no answer key and two answer keys with no vector drawings. Every accuracy number in Phase C is anchored on the two complete pairs until more arrive.

What remains to ask the contractor: the source drawings for FedEx and Gerber (they were printed from a GC's PDF set, which the contractor received), and workbooks for Kittles Saxony, United Utility and Harrison. Each one obtained turns a half-pair into a full one.

### 1.2 Corpus tasks (do these now, in parallel with Phase A)

1. **Normalize the four workbooks into one dataset.** A script (`api/eval/corpus/`) that parses each `ESTIMATE` sheet into rows: `{bid, csi, description, qty, unit, unit_hours, unit_material, sheet_ref}` plus the markup stack per bid. Keep formulas-vs-hardcoded per cell — it is the stale-row signal.
2. **Derive the firm's price book and labor units** from those rows: every distinct item name, its unit hours and unit material, how many bids it appears in, variance across bids. This is the seed for company labor-hours overrides and material prices — a real firm's numbers instead of Claude's. Their $85/hr blended rate, 0.45 hr per duplex, and additive 33.375% markup stack are more defensible than anything the engine currently produces.
3. **Build the catalog taxonomy from the union of item names.** The engine catalog has 11 entries; one bid alone has 24 line types (boost transformer, SPD, floor-mounted EMT, Level-5 cable outlets by drop count, telephone board…). Map each to a normalized Division 26 catalog id with system/category/unit. This is `ROADMAP.md` 2.1's "item normalization," with real inputs.
4. **Annotate the PlanSwift overlays as count truth.** Per sheet, per symbol type: the legend count. Store as `api/eval/counting/<bid>/<sheet>.json`. This is what Counting is tested against, regardless of tier.
5. **Extract the scope signals.** From each set's responsibility schedule and keyed notes (where the source drawings exist): which items are *existing to remain*, *by others*, *by landlord*. This becomes the eval set for the scope-assignment feature in Phase C.
6. **Record the markup structure per bid** as the design input for the Estimate summary workspace (Phase E). Seven real answers to "what does the estimator-owned layer look like."

**Done when:** one command regenerates the dataset from the eight folders, and there is a short written summary — tiers, sheet counts, item-type union, price-book coverage — that Phase C and E plans cite.

---

## 2. Phase A — Land it and make it deployable

*Size: M. Nothing new for users; everything after this depends on it.*

- [ ] **Merge the stack.** #2 → #3 → #4 → #5 into `main`, in order, rebasing each. Then delete `integration/full-stack`, the two `.claude/worktrees/`, and the `claude/*` branches. Make CI a required check.
- [ ] **A deployment target.** Pick one (Fly.io / Render / a single VM with Compose) and stand up API + Postgres + a worker. The current setup — `docker compose up` on a developer's laptop, web via Vite dev server — cannot be handed to anyone, B2's worker container included. Includes secrets management (`ANTHROPIC_API_KEY` today is an env var on a laptop), TLS, and a real `VITE_API_BASE`.
- [ ] **Backups, and one tested restore.** `BUILD-STAGES.md` stage 1 lists it; it does not exist.
- [ ] **Move every remaining `localStorage` store to the API:** `settingsStore.js`, `CompanySettings` profile/markup/export tabs, all of `ProjectSettings`. With `company_actions` auditing the org-level ones. Until this is done, two reviewers see different markup settings.
- [ ] **Delete the Instant estimate nav item and route.** It is a demo surface against the no-auth service and will be gone once Phase B lands the engine behind the API.
- [ ] **Correct the docs.** `CLAUDE.md` and `README.md` say the screens are built; write down what §0 says instead. Retire `docs/archive/full-mvp.md`.
- [ ] **Decide the name.** The repo is `BidMate`, the package is `takeoff-review`, the UI says "blueprint." `docs/product/mvp-approach.md` §9 flagged this as cheap now and expensive later. It is later.

**Done when:** a stranger with a URL and an account can sign in, create a project, and reach the (still empty) upload screen on a server that is not a laptop, and `main` is green.

---

## 3. Phase B — A real document pipeline

*Size: XL. This is the structural change; most of Track 2 "platform" lives here.*

Replaces browser → `:8100` with browser → API → storage → worker → store. Everything in §0.1 fact 1. **B1 and B2 have landed** (unmerged, on `feat/document-pipeline` and `feat/engine-behind-api`); the boxes below are ticked for what those two branches actually built, against [`docs/specs/documents-stored.md`](../specs/documents-stored.md) and [`docs/specs/engine-behind-the-api.md`](../specs/engine-behind-the-api.md), not against this section's original wording where the two disagree.

- [ ] **Document storage.** `documents` (project, filename, type, sha256, size, uploaded_by, status) is built (B1). `document_pages` (document, page index, width/height pt, tier, render key) is **deliberately not built**: B2 found no need for a table separate from `sheets`, which already carries `page_index`, `width_pt`, `height_pt`, and gained `region`/`legend`/`schedule_text` directly — one row per sheet stays the identity a worker upserts against across re-reads, rather than a page row and a sheet row that could drift apart. A render key still needs a home when page rendering (B3) lands; whether that reopens `document_pages` or adds a column to `sheets` is an open call for that phase. Object storage with tenant-scoped keys — MinIO locally, S3 in deployment — is built (B1), hash-scoped within a project, never shared across orgs, matching the recommendation below.
- [ ] **Upload endpoint.** Signed-URL direct-to-storage multipart upload for 100–500 MB sets; the API records the document when the upload completes. Duplicate-in-project, password-protected, corrupt, and unsupported-type outcomes each get their own state on screen C (spec §5 C). Direct-to-storage multipart is not built — B1 uploads through the API, which streams to MinIO without opening the file; duplicate, password-protected and corrupt outcomes are handled, but resumable multipart is not.
- [x] **Job queue and worker.** Built (B2): a `jobs` table (`read` per document, `classify` per project run, `sheet` per plan sheet — a closer shape than "project, document, page, stage" once a run's classification turned out to be shared by every sheet it counts) and a worker process polling it, `FOR UPDATE SKIP LOCKED`, no Redis. One job per sheet so a sheet fails alone (spec §5 E). Retries with backoff are built; **dead-letter after N and a per-tenant concurrency cap are not** — a job that exhausts its attempts just sits `failed`.
- [x] **Move the engine behind the API.** Built (B2): `estimate_service.py` is deleted, the engine (`api/app/engine/`) is called only from `api/app/worker/`, and `engineClient.js` is deleted along with `EstimateDemo.jsx` and the `/estimate` route. The worker runs in its own Compose service with memory/pid limits, and every job body additionally runs in a sandboxed child process with a wall-clock timeout — the minimum sandbox plus one more layer.
- [ ] **Page rendering at ingest.** Render every sheet to a PNG (or a small tile pyramid for E-size) into storage; serve through an authenticated API route. This is what puts the drawing back behind the markers. Not built — B3.
- [x] **Processing status for real.** Built (B2): `GET /projects/{id}/processing` returns per-sheet stage built from the `jobs` table; screen E polls it every 3 s; "you can leave this page" is true — sheets keep processing and are reviewable as they finish. Completed sheets are reviewable while others run.
- [ ] **Confirm drawings (screen D) writes back.** Include/exclude, discipline correction, revision, and scale corrections persist and gate which pages get jobs. Today none of that survives — screen D shows the sheets and scope a `read` job found, real and server-backed since B2, but every listed document still runs through the takeoff with no per-document exclusion. (The original wording said this persists to `document_pages`; that table doesn't exist — see above.) Not built — B4.
- [ ] **Metering events.** Emit `sheet_processed` with tenant, project, page, tier, duration from the worker. Not billed, but `ROADMAP.md` 3.1 is right that this cannot be retrofitted. Not built — B4.

**Done when:** an estimator uploads a set, closes the tab, comes back, watches sheets complete one by one, and opens the review workspace with the real drawing rendered behind the markers. Not yet — page rendering (B3) is the piece still missing from that sentence; everything before "rendered behind the markers" is true today.

---

## 4. Phase C — An engine that reads real sets

*Size: XL, and the only genuinely uncertain part. Gate it on the corpus from §1.*

The five-agent structure and its contracts are sound and stay. What changes is each agent's reach.

### 4.1 Documents
- [ ] **The five sheet-fidelity defects first** — measured on Unalaska and recorded with reproductions in `docs/archive/engine-sheet-fidelity-findings.md` (worktree `fix/engine-sheet-fidelity`): non-deterministic sheet numbers across processes (`documents.py:83`, a one-line fix); schedules, legends and one-lines counted as device plans (106 of 303 placements); 14 pages collapsing to 11 sheet numbers; every title the fallback "Electrical plan"; no drawing-region detection. These are cheaper than anything else in this section and they gate whether the vector five can be measured at all.
- [ ] **Sheet numbering that survives real conventions.** `SHEET_ID` is `E\d.\d`; the FedEx set is `E-1.0`, `DC-1.0`; others use `E101`, `E-101`, `EP1.1`. Read from the title block, with a per-set learned pattern.
- [ ] **Tier detection per page** (A/B/C) written to `document_pages.tier` and shown on screen D. Honest before processing, per `BUILD-STAGES.md`.
- [ ] **Typed schedule and legend rows** (the five-agents-basic Task 2 direction) — extend to the **responsibility schedule** and **keyed notes**, which is where scope lives. On the FedEx set the answer to "is this ours" was in a table on E-1.0 and three notes on E-3.0.
- [ ] **Raster title-block OCR** for tier C, so at least sheet number, title, revision, and scale are read even when counting is not attempted.

### 4.2 Counting
- [ ] **Tier B geometry clustering** — the research task §11.1 of the agent-architecture spec names. Spatial grouping of exploded strokes into candidate symbols, signature, cluster, emit `DeviceCluster` with exact coordinates. Fixture: the five vector sets — Unalaska, Kittles Saxony, Pulte Sagebriar, TSC Nutrition, United Utility. **Tested, not trained**: asserted counts in CI from §1.2 task 4.
- [ ] **Tier C raster counting** — needed for three of eight sets (FedEx, Gerber, Harrison), so it is real scope, but it follows tier B, which covers the majority. Template matching from legend crops is the honest first version. Until it exists, raster pages are *unreadable with a reason*, never a short list.
- [ ] **Per-sheet coverage outcome** as a first-class record: read fully / read partially (which regions) / unreadable (why). Rendered on the canvas as the "not examined" overlay `docs/product/mvp-approach.md` §2 calls the highest-value thing on the page.
- [ ] **Measured runs** where geometry supports them: polylines against a confirmed scale, populating `Item.path`, so the dashed-line treatment on F finally has data. Homeruns without a route get the feet-per-device rule the estimator confirms (`Assemblies.FEET_PER_DEVICE` exists; surface it).

### 4.3 Classification
- [ ] **Project-scoped symbol library** (`symbol_resolutions`: org, project, cluster signature or tag, catalog id, resolved_by, at). One correction resolves every instance — "find every one like this" falls out of the Counting/Classification split as designed. Firm-scoped propagation stays an open decision; when it lands, defaults surface as *Ready to review*, never pre-approved.
- [ ] **Catalog expansion** from §1.2 task 3 — the union of the seven bids' item types, normalized.
- [ ] **Scope assignment as an item field**, never inferred: `in_contract | existing_to_remain | by_others | unresolved`, set from the responsibility schedule and keyed notes where they are readable, with a warning (`reason: scope`) when a counted symbol sits on existing/gray line work or in a room the key plan marks as the landlord's. This is the single largest lesson from the FedEx teardown — $33k of a $62k subtotal — and it needs a deliberate decision about whether it is a fifth review label or a separate axis. **Recommendation: a separate axis**, like note status is. Four labels stay four.
- [ ] **Per-agent eval sets frozen from the corpus**, run in CI: Documents (sheet ids, scales, schedule rows), Classification (tag → catalog id), warnings rubric (already in `api/eval/`).

### 4.4 Pricing
- [ ] **Assembly expansion in the app path**, not just the CLI: device → box, plate, ring, whip, conductors, conduit per `assemblies.py`; waste applied to material only, inputs stored and product derived (`docs/product/mvp-approach.md` §4.1).
- [ ] **Firm price book as the default tier.** Seed company material prices and labor-hours overrides from the corpus; the LLM prices only what the book does not cover, and the row says which. The precedence chain in the pricing spec already supports this.
- [ ] **A real pricing source contract** (regional feed or supplier pricing) — a business task, tracked here so the "Missing information on every row" default does not become permanent.

### 4.5 Conversation
- [ ] Nothing new in this phase. `conversation.py` routes; the panel is Phase F.

**Done when:** the engine produces a takeoff on at least four of the five vector sets whose per-sheet counts are within an agreed tolerance of the PlanSwift truth, with every miss surfaced as *Needs attention* or an unreadable region rather than silence — and the numbers are in `api/eval/` where CI can hold them.

---

## 5. Phase D — Finish the review workspace

*Size: L. The screens exist; this is the functionality the specs promise and the density a real set demands.*

- [ ] **Drawing behind the markers.** Canvas renders the page image from Phase B; markers map page points → 1000×750 sheet space; calibration finally has something to measure against.
- [ ] **Add an item** — pick a type (recent + project library), click to place. Same record shape as a found item; evidence reads "added by <name> on <sheet>". Count manual additions per set as engine telemetry.
- [ ] **Find every one like this** — from any item, resolve its cluster, review the set, approve as a batch.
- [ ] **Bulk handling for density**: group the queue by warning type, resolve all instances of a symbol at once, filter to one warning class. A hospital sheet is four hundred items; the current panel is built for twelve.
- [ ] **Rejected layer** distinct from deleted, visible and toggleable. Layer toggles remain client-only and never touch totals.
- [ ] **Scope filter and column** (from 4.3) on F and G.
- [ ] **Spreadsheet manners on G**: grouping by system/sheet/floor, column visibility, resize, tab/enter navigation, fill-down, multi-select — and no formula engine (`docs/product/mvp-approach.md` §6.2).
- [ ] **Spreadsheet import at project start**, using the `ESTIMATE` layout from the corpus as the first supported format. Imported rows carry provenance "from the estimator's file." Never re-import after review.
- [ ] **Finish review on the server**: blocking evaluated in the API, the *Needs attention* acknowledgment recorded as an action with a name and time on it.
- [ ] **Undo covers evidence and pricing on delete** (evidence image restoration is listed as a known limitation; the pricing-row half landed in #5).
- [ ] **Required states** from spec §10 that have no design: offline / connection interrupted, permission denied, export failure, no search results, unsaved edit.

**Done when:** an estimator completes a full review of a real set — including the forty devices the engine missed — without leaving the product, and the panel closed reaches the same end state as the panel open (the constraint the conversation layer is accepted under).

---

## 6. Phase E — From takeoff to estimate

*Size: L. This is what the seven bids show the customer actually submits. Four workspaces are disabled in the nav for exactly this.*

- [ ] **Assemblies workspace** — per catalog item, what a unit expands into; company defaults with per-project overrides; waste factor per material. Pricing (4.4) reads it.
- [ ] **Labor completeness** — crew mix and adjustments (spec §12.2), NECA units or the firm's own units as the source of record, productivity factor. Approved (installed) quantity drives hours; never the purchase quantity.
- [ ] **Material pricing completeness** — supplier quote upload with line matching, price-sheet import, staleness threshold configurable, price precedence visible on the row.
- [ ] **General conditions** as real lines: cleanup, coordination/layout, permits, temporary power, lift rental, as-builts. Every one of the seven bids will have a version of this block; FedEx carried it at $0.
- [ ] **Estimate summary workspace** — the estimator-owned layer, built exactly as the corpus shows it and never proposed by an agent: direct cost → overhead & profit → tax (material-only by default, rate by project location — the FedEx sheet taxed labor at NYC's rate on a Charlotte job) → bond → contingency → bid. Defaults from company settings, overrides per project, every dial attributed and audited. Scenarios (spec §14.3) later.
- [ ] **Final review workspace** — the finish-review summary as its own screen: blockers, acknowledgments, exclusions and clarifications block (which the FedEx sheet reduced to one empty sentence), assumptions from Notes, revision and plan-date stamp.
- [ ] **Real Excel export** — an `.xlsx` workbook (a library, server-side) that reconciles exactly with the totals query, carries source sheet references per row, and can be templated on the firm's own `ESTIMATE` layout so it drops into their existing process. CSV stays as a secondary.
- [ ] **Totals in one place, still.** Drawer, G, H, Estimate summary, and the workbook read one server query. Add the integration test that proves it.

**Done when:** the product produces a bid-ready workbook for one of the seven jobs that the contractor would recognize as their own — and it does not contain the five errors the FedEx teardown found.

---

## 7. Phase F — Multiple people, multiple revisions, and the panel

*Size: L–XL. Stage-2 territory; needed before a second firm.*

- [ ] **Push, not poll.** WebSocket fan-out for item changes, presence, selection; reconnect and replay. `collab/` is the seam.
- [ ] **Undo model — decide it.** The stack is shared and linear; person B can undo person A's approval. This is a product call listed in `CLAUDE.md`; it must be made before push sync lands, because the current model does not survive a real network.
- [ ] **Roles and approval authority** — estimator, chief estimator, admin, read-only guest; whether a project can require a second approver. Invitations, deprovisioning, MFA. The whole status vocabulary rests on "a person confirmed it."
- [ ] **Revisions and addenda** — document sets with active/superseded sheets; `Sheet.superseded` actually set; superseded sheets excluded inside the totals query; **addendum comparison** (vector diff of two revisions, pulled into stage 1 by `docs/product/mvp-approach.md` §5); the conflict flow (carry-forward of approvals, mid-review swap surfacing) after the open decisions are made.
- [ ] **The conversation panel** — threads scoped to project/sheet/item, anchored messages in sheet space, proposals that flow through `commit()` as one attributed undoable action, questions rendered from the review queue rather than a second inbox. Built last on purpose: it is additive, and the structured paths it must never replace have to exist first. `conversation.py` already routes to typed proposals.
- [ ] **Notifications** — processing complete, addendum landed, teammate approved your sheet.
- [ ] **Observability** — error tracking, metrics, alerting, a status page; support impersonation written to the action log.

---

## 8. Phase G — Commercial readiness

*Size: ongoing. Track 3 as written; nothing here is disputed.*

Metering is already emitted (Phase B). Billing with PO/ACH/invoicing, terms that make the *Estimator approved* gate the legal firewall, DPA and bid-confidentiality language for NDA'd sets, E&O insurance, SOC 2 instrumentation, penetration test, onboarding without a call, in-product help (nav item exists, disabled), documentation, and the benchmark program that lets screen I show a number.

---

## 9. Decisions to make now

Each of these blocks something above. None should be resolved in passing while building something else.

| Decision | Blocks | Recommendation |
|---|---|---|
| ~~Can we get the source drawing sets?~~ **Answered 2026-09-13: five of eight are vector.** | — | Remaining ask: FedEx and Gerber source PDFs; workbooks for Kittles, United Utility, Harrison |
| Cross-tenant document dedup | Phase B storage | Never share blobs across orgs; hash within a project only |
| Scope assignment: fifth label or separate axis? | Phase C 4.3, D | Separate axis, like note status. Four labels stay four. |
| Pricing source of record | Phase C 4.4, E | The firm's own book from the corpus as the default tier; LLM only for uncovered rows, and the row says so |
| Shared undo model | Phase F | Needs a product call; do not let push sync land on the linear stack |
| Approval authority / second approver | Phase F roles | Needs a product call |
| Revision carry-forward and superseded browsing | Phase F | Needs a product call |
| Firm-level symbol memory propagation | Phase C 4.3 | Defaults surface as *Ready to review*, never pre-approved; decide before the library is firm-scoped |
| Product name | Phase A | Decide once; it goes into URLs |
| Deployment target | Phase A | Anything with Postgres, a worker, and object storage; optimize later |

---

## 10. Sequencing

```
now ──► §1 corpus (1 wk, parallel)
        Phase A land + deploy (1–2 wks)
              │
              ▼
        Phase B document pipeline (4–6 wks) ──┐
              │                                │
              ▼                                │
        Phase C engine (open-ended; gate on ───┘ corpus results, run in parallel with B once storage exists)
              │
              ▼
        Phase D review completeness (3–4 wks) ── can start on the spreadsheet/import half during B
              │
              ▼
        Phase E takeoff → estimate (4–5 wks) ── Estimate summary + xlsx can start once A moves settings to the API
              │
              ▼
        Phase F multi-user / revisions / panel
              │
              ▼
        Phase G commercial
```

The durations are shapes, not commitments. Phase C is the only genuinely unpredictable piece, and `BUILD-STAGES.md` is right that stages advance on exit criteria, not dates.

**This week:**
1. ~~Get the bid folders in and answer the source-drawings question.~~ Done 2026-09-13 — eight folders, five vector.
2. Write the corpus script (§1.2 tasks 1–3) — one day, and it informs everything.
3. Merge the PR stack and pick a deployment target.
4. Write the executable plan for Phase B; it is the least uncertain large piece and everything downstream needs it.

---

## 11. Time estimates, Claude running continuously

The sizes above (M / L / XL) are the shape of the work for a human team. This section restates them as **continuous-Claude days**: subagent-driven development as it has run on this repo — implementer and reviewer per task, fix loops, whole-branch review, one fix wave — with a person available to make decisions and merge, but not writing code.

### Calibration

Measured, not guessed. The four stacked PRs (#2–#5, 203 commits) landed across ten active days, 2026-08-26 → 09-08:

| Plan | Size | Commits | Active days |
|---|---|---|---|
| Labor & material pricing (two workspaces, migrations, settings off `localStorage`) | L | 118 | 5 |
| Grounded classification warnings | M | 17 | 1 |
| Five agents, basic version | L | 47 | 1 |
| Close the known gaps (CI, undo restore, company audit) | M | 21 | 1–2 |

So: **M ≈ 1 day, L ≈ 1–5 days depending on how many subsystems it crosses, XL ≈ 1–2 weeks.** Writing each phase's executable plan (spec → task-level plan, the brainstorming and writing-plans steps) costs about half a day per phase and is included below. Nineteen of the controller's brief errors across those three plans were caught by reviewers rather than shipped; the review loop is what makes continuous running safe, and it is roughly a third of the wall-clock.

### Estimates

| Phase | Claude days | What the clock does *not* cover |
|---|---|---|
| **§1 Corpus** | **2–3** | Nothing. Parsing four workbook layouts is fiddly but fully specified by the files. |
| **A — Land and deploy** | **3–4** | Choosing the host and creating the account; DNS; the product name. The merge is an hour; `localStorage` → API is a day; deployment is a day *once credentials exist*. |
| **B — Document pipeline** | **8–12** | The dedup policy (recommendation stands: never across orgs). MinIO locally needs no decision; S3 needs an account. Eight subsystems, each roughly M, sequentially dependent. |
| **C — Engine on real sets** | **15–25, open-ended** | Accuracy is not a function of hours. The deterministic half — sheet-fidelity fixes (1–2 days), sheet-number conventions, tier detection, typed schedules, coverage outcomes, symbol library, catalog expansion, scope axis, assembly expansion, price-book seeding — is 8–12 days of ordinary work. **Tier-B geometry clustering is research**: 3–10 days with five vector fixtures, and no guarantee it reaches tolerance on all of them. Tier-C raster is a further 5+ and should be deferred until B is measured. |
| **D — Review completeness** | **6–9** | Nothing. Drawing-behind-markers depends on B's rendering; the spreadsheet and import half can start during B. |
| **E — Takeoff → estimate** | **7–10** | Which `.xlsx` layout to template on (the corpus has one firm's; pick it). Estimate summary and export can start once A moves settings to the API. |
| **F — Multi-user, revisions, panel** | **10–15** | **Three product decisions gate it** — undo model, approval authority, revision carry-forward — and none should be made in passing. Push sync must not land on the linear undo stack. |
| **G — Commercial** | not Claude work | Billing plumbing is 3–5 days; terms, insurance, SOC 2, DPA and the pricing-source contract are business work on a calendar of their own. |

**Through Phase E: roughly 40–60 continuous days.** Through F: 50–75. Against the human-team shape in §10 (4–6 months to the same point) that is a 2–3× compression, not 10× — because Phase C's uncertainty, the ten decisions in §9, and the review loop all sit outside the part that parallelises.

### What makes the estimate wrong

- **Decisions waiting.** Every row in §9 that sits unanswered when its phase starts costs a day of context-rebuilding when it is finally answered. Batch them before the phase, not during.
- **Phase C ending early or late.** The 15–25 range assumes tier B reaches tolerance on three of five vector sets. If it reaches it on all five, C is 12 days. If clustering fails on exploded-stroke sets, C is a month and the plan changes shape at 4.2.
- **The corpus growing.** Each drawings-plus-workbook pair the contractor adds is worth more than a week of engine work. Ask for FedEx's and Gerber's source PDFs before Phase C starts.
- **Continuity itself.** "Continuous" assumes the human side turns around merges and decisions within a day. A week of silence is a week of nothing; the clock is on the pair, not on Claude.
