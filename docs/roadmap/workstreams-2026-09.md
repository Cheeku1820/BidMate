# Workstreams — September 2026

Six pieces of work, each sized to run in its own worktree and its own Claude session at the same time. §1 is the list. §2 and §3 are the research two of them asked for. §4 is how to run them in parallel without stepping on each other.

Every stream follows the repo's normal path: brainstorm → `docs/specs/<name>.md` → `docs/plans/<name>.md` → build with tests → review → merge. Small streams (A) can skip straight to a plan.

## 1. The streams

| # | Stream | Size | Touches | Wait for |
|---|---|---|---|---|
| A | Pricing hardening — the two parked bugs | Small | `api/app/worker/price_job.py`, `api/app/market/price_sheet.py`, `api/app/worker/price_sheet_job.py`, their tests | nothing |
| B | Spreadsheet-grade grid for Labor and Material pricing | Medium | `src/components/grid/`, `src/components/labor/`, `src/components/pricing/`, `src/styles.css` | nothing |
| C | Connectors — where bids come from and where estimates go | Research → spec first | new `api/app/integrations/`, `docs/specs/connectors.md` | nothing |
| D | Phases and timeline | Research → spec → build | new phase model + migration, `api/app/takeoff/`, a new `src/components/schedule/` | nothing for the spec; build after A |
| E | Conversation panel that proposes and applies changes | Large | `api/app/assistant/`, `api/app/engine/conversation.py`, every screen's `screenContext` | B and F merged first (it touches every screen) |
| F | Project plan screen — what the documents say, for an electrical sub | Medium | `api/app/scope/`, `api/app/engine/scope.py`, new `src/components/plan/`, routing | nothing |

### A. Pricing hardening

Two bugs the final review of estimate-first pricing parked.

1. **A price job can loop while a source is down.** `price_job.py` stops at a 90 s budget and queues a follow-on job; if every call is timing out, the follow-on writes the same `failed` rows and queues another. Fix: only queue the follow-on when this run priced at least one item past `failed`; when a whole run produces only `failed` outcomes, stop and write one estimator-facing line on the project ("Market estimates couldn't be reached — try Refresh later") through the existing outcome copy. Test: a FakeSource that always raises → one job, no follow-on, every row `failed`.
2. **A broken spreadsheet fails the upload instead of being explained.** `price_sheet.py` raises on a NaN cell; more generally any parser exception ends the job with the generic "re-save as PDF" copy. Fix: `price_in_range` treats non-finite as out of range; `parse_price_sheet` catches per-row exceptions and lists that row under a new preview group `unreadable` with its line number and a one-line reason ("Row 14: the price isn't a number"); the modal shows the group. A sheet where *every* row is unreadable is `refused` with "None of the rows could be read. Start from Download price request." Tests for both.

### B. Spreadsheet-grade grid

The Labor and Material pricing screens should feel like Google Sheets: cells, arrow keys, Shift-select a range, fill-down, copy and paste a block, Delete clears a range, column resize, a frozen header, sort by column, and edits landing one at a time through the existing `commit()` path so undo still works per cell.

Decision to make first (brainstorm): extend `src/components/grid/DataGrid.jsx` (small, ours, keyboard rules in `useGridNavigation.js`) or adopt an MIT grid — `react-data-grid` or Glide Data Grid — and keep our cell editors and status pills. Recommendation: adopt, because range selection, clipboard, and virtualization are where hand-rolled grids spend months. Whatever the choice, the four review labels, the tier tag, and "status is never colour alone" hold in every cell.

### C. Connectors — see §2

### D. Phases and timeline — see §3

### E. Conversation panel that acts

Today the panel only answers. The doctrine in `CLAUDE.md` already says what "acting" means: it **proposes**, the estimator applies, the change flows through `commit()` as one undoable action, and it never approves. Build order:

1. Proposals for the screen in view — item edits, classification, quantities, a note, a scope statement, a price — each rendered as a preview card with Apply / Dismiss.
2. Route to the owning module rather than re-implementing it (`engine/conversation.py`'s routing exists but is not wired).
3. Every section: review workspace, takeoff table, notes, labor, material pricing, plan screen (F), phases (D).
4. Acceptance test that already exists in spirit: a full review completed with the panel closed reaches the same end state.

Wait for B and F to merge; this stream edits every screen's context and would conflict with both.

### F. Project plan screen

A new screen between *Upload documents* and *Blueprint review*: everything the product understood from the documents, filtered to what an electrical sub bids — scope statements, specification sections (Division 26/27/28), fixture and panel schedules found, phasing the drawings call for, the exclusions, the questions it could not answer. Every line links to the page it came from; nothing is counted here.

Foundations exist: `api/app/scope/` extracts scope statements with verbatim quotes; the Documents agent reads schedules. What is new: a structured "plan" record per project (scope, specs, schedules found, phases, open questions), the screen, and the intake step in the project stages. **Note from the corpus:** both example bid sets are scans with no text layer, so this screen depends on the OCR/vision path being reliable — check that first.

## 2. Research: connectors worth building

Where an electrical sub's bid starts and where the estimate ends up. Ranked by how much each one removes from the estimator's day.

| Rank | Platform | What it gives us | How | Evidence |
|---|---|---|---|---|
| 1 | **Autodesk BuildingConnected** (Bid Board) | Bid invitations *arrive* here — the drawings, specs, due date. Pull them in and a project exists before the estimator opens our app. | Public REST API with bid packages, invites, bids ([APS docs](https://aps.autodesk.com/en/docs/buildingconnected/v2/developers_guide/overview/)); Bid Forwarding aggregates invites sent outside it | Most GCs send invites through it; free tier for subs |
| 2 | **Procore** | GCs run the job here. Push our RFIs/questions, read drawings and addenda, later submittals and change orders. | Versioned REST APIs for RFIs, submittals, drawings, cost codes; sandbox with seeded data; Marketplace ([developers.procore.com](https://developers.procore.com/)) | 95%+ of Procore customers use an integration; subs get free project access |
| 3 | **Excel / the estimator's own template** | The 17-column template in `bid_examples/` *is* the firm's system. Export must match it column for column. | Already partly built (CSV); make it a real `.xlsx` on their template | Both example bids use the same template |
| 4 | **McCormick / Accubid / ConEst** (estimating) | Where pricing and labor units live for firms that already own one. Export our takeoff as their import; later import their price database. | McCormick imports CSV and NetPricer/Trade Service files; Accubid has an "Integrator" export; ConEst links to accounting | These three own the commercial electrical estimating market |
| 5 | **Foundation / Sage / QuickBooks** (accounting) | A won estimate becomes a job budget. | McCormick→Foundation is a native CSV path; QuickBooks via CSV | Job costing is where the number is judged after the bid |
| 6 | **Kojo** (procurement) | The material list becomes requisitions and POs; real net pricing comes back from Graybar and other suppliers. | Kojo has supplier catalog/pricing integrations (Graybar direct) | Closes the loop the price-sheet upload approximates today |
| 7 | **Bluebeam** | Estimators mark up PDFs here. Round-trip markups later, not now. | Bluebeam Studio API | Common, but our canvas replaces most of it |

Recommended first connector: **BuildingConnected inbound** (bid invite → project with documents) plus **Excel export on the firm's template**. Both are read-mostly, both are what the design partners already do by hand. Procore second. Spec each as `docs/specs/connector-<name>.md`.

Sources: [BuildingConnected API overview](https://aps.autodesk.com/en/docs/buildingconnected/v2/developers_guide/overview/), [GET bids](https://aps.autodesk.com/en/docs/buildingconnected/v2/reference/http/buildingconnected-bids-GET), [Procore Developers](https://developers.procore.com/), [Procore integration guide 2026](https://www.bolderapps.com/blog-posts/procore-integration-custom-construction-apps-2026), [McCormick + Foundation](https://www.foundationsoft.com/partner/mccormick-systems-inc/), [McCormick 2026 guide](https://www.mccormicksys.com/blog/the-best-electrical-estimating-software-2026-guide/), [Accubid export thread](https://forums.mikeholt.com/threads/exporting-accubid-accounting-data-into-quickbooks.110176/latest), [Kojo supplier integrations](https://www.prnewswire.com/news-releases/kojo-launches-new-integrations-with-nations-largest-electrical-suppliers-301983209.html).

## 3. Research: phases and timeline

### What the two example bids show

- **Gerber Collision (renovation, occupied shop):** the estimator split the whole bid into **Phase 1** and **Phase 2** as separate sheets, each with its own General Conditions (cleanup, planning/coordination/layout), its own Demolition section, and its own full line list. The summary sheet carries each phase as one lump sum: Phase 1 = 329 labor hours, Phase 2 = 72 hours, both at $85/hr. So a phase is a *complete mini-estimate* for one area or stage, not a tag on a line.
- **FedEx Office (tenant improvement):** one phase, one sheet. General Conditions first, then Division 26 lines, then a markup block.
- Both PDFs are scans (no text layer); the drawing index for Gerber shows demolition plans (D1, D2) and coordination plans (G3 electrical, G4 security) but no dedicated "phasing plan" sheet — the phasing came from the GC's bid instructions or the estimator's read of the drawings.

### How the trade thinks about time

Electrical work on a commercial job runs in a fixed order per area: **demolition → rough-in (conduit before walls close) → wire pull (after inspection) → gear and panel terminations → trim-out (devices, fixtures) → testing and close-out**. Each stage has a different crew mix (rough-in leans on apprentices under a journeyman; terminations need experienced hands) and a different productivity rate, so hours should be planned per stage, not at one blended rate. On larger jobs each area can be at a different stage at once. Subs run a weekly "look-ahead" against the GC's schedule. Sources: [rough-in to trim milestones](https://violetrayelectric.com/electrical-milestones-contractors-need-on-project-timelines/), [scheduling electrical work](https://lookaheadwall.com/blog/scheduling-electrical-work-in-construction), [phase-based scheduling](https://exoserva.com/blog/multi-day-electrical-projects?lang=en), [Procore on project phasing](https://www.procore.com/library/construction-project-phasing).

The biggest schedule risk in 2026 is **equipment lead time**, not labor: low-voltage switchboards are running 35–62 weeks, medium-voltage switchgear 52–80 weeks, pad-mount transformers ~50 weeks, generators ~60 weeks. Gear has to be ordered at award, sometimes before mobilization. Sources: [switchgear lead times 2026](https://www.industrialsage.com/switchgear-lead-times-2026/), [lead-time numbers](https://terrapincg.com/news/switchgear-transformer-generator-lead-times-2026), [what estimators must build in](https://www.electronate.app/blog/switchgear-lead-times-2026-data-center-boom).

### What to build (for the spec)

1. **Phases as a first-class record**: a project has one or more phases (name, area/sheets it covers, order). Every item belongs to a phase; general conditions and demolition are lines per phase, as the Gerber template does. Export rolls each phase up as the summary sheet does.
2. **Stages inside a phase**: rough-in / wire pull / gear / trim / close-out, with hours per stage derived from labor units and the firm's own stage productivity, and a crew size per stage → duration. A simple Gantt per phase, nothing more.
3. **Long-lead flag**: the quote-required items (switchboards, transformers, generators, ATS) carry a lead-time-in-weeks field with a default table the firm can edit; the timeline shows "order by" dates counted back from the stage that needs them.
4. **The drawings' own phasing**: when the documents carry a phasing plan or phased demolition sheets, the plan screen (F) proposes the phases; the estimator confirms.

## 4. Running streams in parallel

One worktree, one branch, one Claude session per stream. The repo already keeps worktrees under `.worktrees/`.

### Setup, per stream

```bash
scripts/worktree.sh <name>
```

creates `.worktrees/<name>` on branch `feat/<name>`, links `node_modules` and the Python venv, copies `api/.env` with its own test database name (`takeoff_test_<name>`) so two suites never fight over one database, and prints the Vite port to use (`5173 + n`). Then open a new Claude session in the app, pick the repo folder, and start with:

> Work in the worktree `.worktrees/<name>` (already created — enter it, don't create another). Implement stream <letter> from `docs/roadmap/workstreams-2026-09.md`: brainstorm, write `docs/specs/<name>.md`, then `docs/plans/<name>.md`, then execute with subagent-driven development. Only touch the files that stream lists; if you need to change a shared file (see §4 of that doc), add to it at the end rather than editing existing lines. Commit on the branch. Do not merge, push, or touch other worktrees. Run the backend suite with the `TEST_DATABASE_URL` already set in `api/.env` there.

### What collides, and the rule for each

| Shared thing | Rule |
|---|---|
| Migrations (`api/migrations/versions/`) | Write it as `00XX_<name>.py` with the next number you see; **renumber at integration** to sit behind whatever landed first — the repo has done this twice already (0024 resolve, 0025 market_pricing). One head at a time. |
| `api/app/takeoff/models.py`, `schemas.py`, `pricing_router.py`, `router.py` | New models and routes go in new modules where possible (`price_sheet_router.py` is the pattern); when you must edit these, append, don't reorder. |
| `api/app/main.py` (router mounts), `src/routes.jsx`, `src/components/shell/ProjectNav.jsx` | Append one line; expect a trivial merge conflict and resolve it by keeping both. |
| `src/styles.css` | Append your block at the end under a `/* ==== <stream> ==== */` banner. |
| `CLAUDE.md`, `README.md`, `docs/README.md` | Edit only at integration, in the merge commit. |
| `api/tests/test_tenancy.py` tables | Append rows. |
| Postgres | Shared server, separate test databases per worktree (the script sets this). The dev database `takeoff` is shared — only run `alembic upgrade head` on it from `main`. |
| Vite dev server | One per port; the script tells you which. |
| The conversation panel (stream E) | Waits for B and F. |

### Merge order

A → B → F → C → D → E. A is tiny and unblocks D's schedule work. B and F are independent of each other but E needs both. C and D are spec-first, so their builds naturally come later.

### Finishing a stream

From that session: `superpowers:finishing-a-development-branch` → merge locally → run both suites on merged `main` → remove the worktree. If the migration number clashes, renumber in the merge commit and say so in its message, as `bbd9757` does.
