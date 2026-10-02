# BidMate — where the project stands

A working summary of the product, what is built, the decisions behind it, and what remains.
Written 2026-09-25 from the tip of `feat/legend-named-clusters`; updated 2026-10-01 from `main`
at `3654789`, after the September parallel streams landed.

---

## 1. The product

**BidMate** turns an uploaded set of construction drawings into a reviewable **Division 26 electrical takeoff**. An estimator uploads a bid set, the engine reads it, and the estimator reviews, corrects, and approves every quantity before it becomes a number they submit.

**Who it is for.** Estimators at electrical contracting firms. They are deep domain experts and often uncomfortable with unfamiliar software. Two consequences shape every decision:

- The interface reads as an instrument, not a demo. No model names, no confidence percentages, no processing internals, no AI framing — anywhere.
- Their professional reputation rides on the number they submit. Every quantity needs traceable evidence, and **nothing is counted without a person approving it**.

The failure mode the whole product is built to prevent is a confidently wrong number at 4pm on bid day. Being wrong is prevented by *visible uncertainty*, never by refusing the file.

### The status vocabulary is the spine

Four labels govern everything. Never a fifth, never renamed.

| Label | Meaning | Blocks completion? |
|---|---|---|
| Ready to review | Sufficient evidence, not yet approved | No |
| Needs attention | Conflicting or uncertain information | Only behind an explicit acknowledgment |
| Missing information | Required evidence absent (scale, legend) | Yes, no override |
| Estimator approved | A person confirmed it | — |

Every screen is a different view onto this same state.

---

## 2. Architecture

```
browser (React + Vite)  →  API (FastAPI)  →  Postgres
                              ↓                 ↑
                         object storage      worker
                         (MinIO / S3)     (the only process
                                           that opens a PDF)
```

**The engine is five agents**, each with exactly one nature, because that is what makes them separately measurable:

| Agent | Nature | Produces |
|---|---|---|
| Documents | Language over a deterministic shell | Sheets, discipline, revision, scale, legend, schedules |
| Counting | Deterministic geometry | Clusters of identical shapes with exact coordinates |
| Classification | Language | A catalog item per cluster, with status and warning |
| Pricing | Lookup, plus a supplier price-sheet round trip | Assemblies, material cost, labour hours |
| Conversation | Language | Intent, target records, routed proposals |

**Counting does not know what anything is.** It emits an unlabelled cluster of 47 shapes; Classification names it. This is why "find every one like this" is a consequence of the architecture rather than a feature bolted on top — a correction lands on a cluster, not on an instance.

**The process boundary is enforced, not described.** `app.worker` is the only package that opens a PDF or imports the engine pipeline; `app.main` imports no engine module and no `cv2`; `app.worker` imports no router. All three are proven by subprocess tests, because a PDF parser is a remote-code-execution surface and the API is not where untrusted bytes get parsed.

---

## 3. What is built

### Merged to `main`

Backend spine · frontend shell and projects · takeoff spreadsheet · API-only foundation · notes and assumptions · blueprint evidence · labor and material pricing · grounded classification warnings · five agents (basic) · engine sheet fidelity · estimate-first pricing · the item panel's "What is this?" decision area.

**The September parallel streams** ([`docs/roadmap/workstreams-2026-09.md`](workstreams-2026-09.md)) all merged on 2026-10-01 except C, each built on its own branch and integrated through a pull request:

- **A — pricing hardening** ([spec](../specs/pricing-hardening.md)). The two parked bugs, plus the price-sheet parser listing any row it cannot read in full by line and reason rather than dropping it.
- **B — spreadsheet-grade grid** ([spec](../specs/spreadsheet-grid.md)). Range selection, fill, sort and column resize under Labor and Material pricing.
- **D — phases and timeline** ([spec](../specs/phases-and-timeline.md)). Phases as a first-class record, the six stages of electrical work sized by the firm's own crew tables, a weekly manpower chart, and long-lead order-by dates. Migration `0028`.
- **E — the conversation panel proposes** ([spec](../specs/conversation-panel-acts.md)). It is no longer read-only: a routed sentence becomes one typed proposal of five kinds (`item`, `note`, `scope`, `plan_line`, `plan_answer`, or a refusal), applied through the same endpoint the equivalent form already posts to. It still never writes directly and never approves.
- **F — project plan screen** ([spec](../specs/project-plan-screen.md)). What the documents say, as six sections over one row shape; it now owns **Start takeoff** and the scope statements. Migration `0026`.

The project navigation is **fifteen workspaces** — Project plan and Phases and schedule both joined the thirteen the frontend design spec §4.2 names.

Verified on `main` at `3654789`, one run each: **backend 1496 passed / 1 skipped, frontend 687 passed / 75 files**, `npm run build` clean. CI runs both suites on every pull request and `backend` and `frontend` are now **required status checks** on `main`.

Plus three platform phases:

- **B1 — documents stored.** Object storage with tenant-scoped keys, a `documents` row per upload with its hash and storage key, every mutation audited. The API streams and hashes; it never opens.
- **B2 — the engine behind the API.** A `jobs` table claimed with `FOR UPDATE SKIP LOCKED` (no Redis), a worker process, per-job sandboxed child processes with wall-clock timeouts, retries with backoff, and per-sheet partial success — a corrupt file marks its document, a sheet that cannot be counted marks that sheet, everything else stays reviewable.
- **B3 — the drawing behind the markers.** The worker cuts each sheet into a 512 px tile pyramid at ≥150 dpi; the canvas draws those tiles at the page's true paper aspect with markers rescaled to land on real geometry.

### Built but **not yet merged** — two stacked branches

**B3b — accurate symbol marking** (`feat/accurate-symbol-marking`, 37 commits on `main`)

Most vector sets carry no reusable symbol definitions at all — the geometry is exploded. So `engine/glyphs.py` reads small full-tone paths, groups them into glyph candidates, and clusters them by tolerant dihedral shape signature. A device drawn with no legible tag now gets counted. Markers sit on the glyph's own drawn box rather than on its text tag.

**"Find every one like this" is built**: draw a box around one symbol and a `match` job finds every instance on that sheet — by shape signature on a vector sheet, by OpenCV template match against B3's render otherwise — and offers them as a group. Nothing is added until the estimator names it or says they are not sure.

**B3c — legend suggestions** (`feat/legend-named-clusters`, 29 commits on B3b, 64 ahead of `main`)

A drawing set ships with a legend that names its own symbols. The read job now cuts each legend sheet into (glyph, description) rows and stores a 32×32 ink-fraction silhouette per row. An unclassified plan cluster's silhouette is ranked against those rows over eight dihedral transforms, and the top candidates are offered to the estimator as buttons — "Duplex receptacle · from E0.1". One click renames the whole cluster through the existing edit path, as one undoable action. A drawn "find like this" box pre-fills its name field from the same ranking.

Verified on that branch in one run each when it was finished (2026-09-25): **backend 1131 passed / 1 skipped, frontend 458 passed / 52 files, build clean.** Those numbers are the branch's own, and they now predate five merged streams.

**Integrating this stack is no longer a small job, and that is the single most important fact in this document.** Measured 2026-10-01 against `main` at `3654789`:

- **Three colliding migration numbers.** The stack adds `0023_symbol_matches`, `0024_symbol_templates` and `0025_item_name_by_estimator`. `main` now uses all three numbers for different things — `0023_conversation_messages`, `0024_resolve`, `0025_market_pricing` — and runs to `0028`. All three need renumbering to `0029`–`0031`, in order, as stream D's `0026` was renumbered to `0028`.
- **27 files conflict** on a trial merge, out of 39 the stack and `main` both touch. The overlap is in the load-bearing middle: `takeoff/merge.py`, `takeoff/snapshot.py`, `takeoff/snapshots.py`, `takeoff/undo.py`, `takeoff/undo_apply.py`, `takeoff/models.py`, `takeoff/mutations.py`, `jobs/queue.py`, `worker/handlers.py`, plus `CLAUDE.md` and `README.md`.
- **`items.name_by_estimator` needs re-checking against what landed since.** Its whole purpose is that a re-run must not revert an estimator's rename, and `merge.py` — the one write path for engine output — is among the conflicted files. The streams that merged also added fields the merge path has to leave alone (`items.phase_id`, the plan decisions). The same invariant now has more cases.

Every delay makes this worse, because each new stream edits the same spine. The honest options are to integrate it now, or to decide it is not going to be integrated and say so.

---

## 4. The demos — what you can actually walk through

Everything runs against the real stack (`docker compose up -d postgres minio minio-init api worker`, then `npm run dev`). There is no fixture data; every row comes from a document someone uploaded.

- **The intake path.** Create a project, upload a drawing set, watch sheets complete one by one on the processing screen, leave the tab and come back — progress is real and server-backed.
- **Two windows side by side.** Each gets its own estimator identity and coloured avatar. Approve in one, it appears in the other within seconds. Select an item in one and the other draws a dashed ring in that person's colour. Undo pulls from a shared stack, and the tooltip names whose action you are about to reverse.
- **Resolve a conflict.** A *Needs attention* item where plan and schedule disagree — open the evidence, correct it, approve.
- **Fix a missing scale.** Measured items show as *Missing information*, drawn as dashed red polylines. Set the scale or calibrate against a known dimension; the affected items flip to *Ready to review* in one undoable compound action.
- **Classify an unknown symbol.** Type what it is in your own words, see what would change, confirm — the whole cluster is renamed and approved in one press.
- **Hit the blocking rule.** Click **Finish review** with any *Missing information* item outstanding. Completion is blocked with no override; only *Needs attention* items can carry forward, behind an acknowledgment checkbox.
- **Read the project plan.** After a set is read, **Project plan** states what the documents say — scope, spec sections, schedules, the phasing they state, and the open questions — each line confirmable, correctable or dismissable, each citing the page it came from. **Start takeoff** now lives here.
- **Put the hours in time.** **Phases and schedule** splits the resolved labor hours across the six stages electrical work runs in, sizes each by the firm's crew, and draws them as bars on a week grid with the weekly manpower chart a GC asks for. Where the drawings phase the job (`E-1.0` against `XE-1.0`), **Propose phases from sheet numbers** offers the split and writes nothing until you confirm. Flag a switchboard as long-lead and an order-by date is counted back from the stage that installs it — only from a lead time a supplier quoted or the firm entered.
- **Tell the panel something.** The conversation panel now proposes: say it in a sentence, see a card showing exactly what would change, and apply it through the same endpoint the equivalent form posts to. It never approves, and a proposal whose records moved on goes stale rather than applying to something else.
- **Edit pricing like a spreadsheet.** Labor and Material pricing take range selection, fill and sort.

On the two unmerged branches only, not on `main`:

- **Find every one like this** (B3b). Draw a box around a symbol; every copy on the sheet comes back as a group to name.
- **Legend suggestions** (B3c). An unclassified cluster offers the legend's own names to pick from with a click.

---

## 5. Decisions we made, and why

### Product rules that are easy to break by accident

- **Status is never colour alone** — always hue + icon + text label. Unverified measurements additionally get a dashed stroke. Assume grayscale printing and colour-vision differences.
- **Warnings always answer four questions** — what was found, why it matters, what to check, where the evidence lives. Enforced by the data shape (`{title, found, why, fix, where}`); a warning missing a field is a schema error, not a copy oversight.
- **Layer toggles filter what is drawn, never what is counted.** An estimator reducing clutter must never accidentally change the number they are about to bid.
- **Green appears only on estimator-approved content.** Not on "done processing", not on a successful upload.
- **Confidence never renders.** It decides status and orders the queue, server-side. A visible percentage invites arithmetic on trust, which is the reasoning path that produces a confidently wrong bid.
- **A note's status is not an item's status.** Notes carry their own confirmed/open vocabulary. A note pill in amber reads as *Needs attention* and quietly makes four labels into five.
- **The engine never discards a person's judgment.** A run merges into each sheet rather than replacing it. An approved item is never overwritten by processing. A clean slate is a deliberate act, never a side effect.
- **Extracted document text is data, never instruction.** A drawing set is untrusted input and a surface that can produce proposals is an injection surface.
- **Silence reads as completeness.** A sheet the engine reads poorly is marked unreadable *with a reason* — never returned as six items with no indication that forty were missed.

### Design calls made in this stretch of work

**The marker treatment changed.** Markers used to draw an opaque white disc with an app glyph on top, which covered the actual drawn symbol — you could not see what you were looking at. Several options were tried; the chosen treatment is an **outline box on the glyph's own bounding box plus a faint interior tint** (10% fill, 18% when selected). No white disc, no app glyph on the sheet. The item-type channel moved to the hover tooltip. The three independent channels — glyph = type, ring colour = status, badge = warning — are preserved, just redistributed.

**B3c pivoted from automatic naming to suggestion-only, because a measurement killed the original design.** The spec called for naming a cluster automatically when its silhouette scored above a threshold against a legend row. Measuring on the real corpus showed true matches scoring 0.5–0.88, while a duplex receptacle and a GFI receptacle scored **0.86–0.90 against each other**. No threshold could separate those. Whole-silhouette correlation cannot support automatic naming, so the design changed: **the legend suggests, the estimator picks.** This is recorded in the spec as §1.1 and is the branch's central design fact.

**`MAX_MODIFIER_CHARS` went from 2 to 1.** Two-character qualifiers beside a symbol turned out to be circuit numbers ("43", "31"), which split one corpus sheet from 4 clusters into 19 — double-counting devices. At one character the corpus switch variants still split correctly.

**`items.name_by_estimator` (migration 0025).** Task 8 made an item's `name` estimator-editable; the merge path still treated it as engine-owned, so **Start takeoff again** would have silently reverted every accepted suggestion and hand-typed name on an unapproved item. Cheaper signals were considered and rejected — `version > 1` is bumped by the re-run itself, and the action log can say a rename happened but not that it still stands. One boolean, `NOT NULL DEFAULT false`, a Postgres fast default with no table rewrite.

**A cross-sheet fixture drop was removed entirely.** The spec called for dropping clusters that repeat identically across sheets. Review showed this would silently delete real devices on typical-floor buildings (identical L2/L3 plans) and dropped nothing on the corpus. Deleted rather than tuned.

**The conversation panel is additive, never load-bearing** — and as of stream E this is enforced rather than promised. Anything sayable in it is doable through a form, field, or menu, and there is a test that completes a review with the panel closed and reaches the same end state. It proposes, never writes; it never approves; a proposal is applied through the same endpoint the equivalent form already posts to, so there is no second write path to keep in step. Questions are a rendering of the review queue, not a second inbox — two queues means a fifth status within a month.

**The panel's proposal kinds are a closed set, checked at both ends.** `("item", "note", "scope", "plan_line", "plan_answer", "refused")`, asserted where a proposal is produced and again where it is read back. Extracted document text reaching the routing call is delimited as data, with a test proving a crafted drawing cannot steer a proposal — the injection surface was designed for, not hardened later.

**Counting is tested, not trained.** It reads placements out of the file rather than estimating them, so it gets asserted counts on known sets. Tuning it like a model is how exact work quietly becomes approximate.

---

## 6. Open decisions — do not resolve these in passing

1. **On `feat/legend-named-clusters`, not on `main`:** accepting a legend suggestion writes the name only, per spec §8. The server's *Needs attention* → *Ready to review* flip keys on `category` leaving `"Unclassified"`, so a renamed item keeps *Needs attention* and a warning reading "Pick what this symbol is from the legend entries listed" — while the block that listed them has disappeared. Three options: also send a category; gate the block on `category` instead of the name; or leave it and clear the status through the normal Edit path. Recorded as spec §11.8. This blocks nothing on `main` and only matters if the stack is integrated.
2. **Shared undo model.** The stack is shared and linear, so person B can undo person A's approval. Alternatives are per-user stacks with a merge policy, or a CRDT.
3. **Revision conflict flow.** Whether superseded sheets stay browsable read-only, whether approvals carry forward, and how a mid-review swap surfaces to a second reviewer already in the file.
4. **Cross-tenant document isolation.** Two subs may bid the same job. Content-addressed dedup across tenants would leak that a competitor is bidding — decide before the storage policy hardens.
5. **Whether firm memory applies to new projects automatically.** A symbol resolved wrongly once and reused silently is a systematic error across every future bid. Likely answer: firm defaults surface as *Ready to review*, never pre-approved.
6. **Scope assignment** (`in_contract` / `existing_to_remain` / `by_others`) — a separate axis like note status, not a fifth review label. The largest single lesson from the FedEx teardown: $33k of a $62k subtotal.
7. **The name.** The repo is `BidMate`, the package is `takeoff-review`, the UI says "blueprint". Cheap to fix now.
8. **Whether the B3b/B3c stack is integrated at all.** Not a design question any more but a scheduling one, and it has a cost either way: 27 conflicting files and three migrations to renumber if yes, the loss of exploded-vector glyph counting and legend-named clusters if no. Deciding nothing is the one option that keeps getting more expensive. See §3.

---

## 7. What is left

### Immediately

- **Decide the B3b/B3c stack** — integrate it or retire it. §3 has the measured cost. It is the oldest open item here and the only one that grows while it waits.
- **Stream C — connectors.** The one September stream that never ran. It was spec-first and neither `docs/specs/connectors.md` nor `api/app/integrations/` exists, so it starts from the research in [`workstreams-2026-09.md`](workstreams-2026-09.md) §2.
- **Reconcile `CLAUDE.md` with what shipped.** Its *Known scope limits* still describe the conversation panel as read-only and proposing nothing, which stream E replaced; the project plan screen is not mentioned in the architecture tree or the scope limits at all. The streams' own rule put those edits in the merge commit, and two merges skipped them.
- **Exclude `.worktrees/**` from the Vitest config.** `vite.config.js` excludes `**/.claude/worktrees/**` but not `.worktrees/**`, where three sibling checkouts live, so a local `npm test` reports 216 files / 1857 tests instead of 75 / 687 — it is running the other branches' suites as well. CI is unaffected (a fresh clone has no worktrees), which is exactly why this went unnoticed.

### Phase A — make it deployable

Pick a deployment target, stand up API + Postgres + worker somewhere that is not a laptop, secrets management, TLS, backups with one tested restore, move the remaining `localStorage` stores to the API. **CI is now a required check** — `backend` and `frontend` both gate `main` through branch protection, so that part is done.

### Phase B4 — finish the pipeline

Confirm-drawings (screen D) writes back — include/exclude, discipline, revision and scale corrections that actually gate which pages get jobs. Metering events from the worker (`sheet_processed` with tenant, project, page, duration) — not billed yet, but this cannot be retrofitted.

### Phase C — an engine that reads real sets

The only genuinely uncertain part. Sheet numbering that survives real conventions; tier detection per page; typed schedule, legend and keyed-note rows; raster title-block OCR; tier C raster counting; per-sheet coverage outcomes as a first-class record; measured runs; a project-scoped symbol library; catalog expansion; per-agent eval sets frozen from the corpus and run in CI.

The research note sequences this (`docs/roadmap/blueprint-analysis-research.md` — which lives on the B3b/B3c branches and is **not on `main`**, so it goes with the §3 decision too): legend-named clusters (**built, on the unmerged B3c branch**) → set-wide match and a symbol library → the raster track → verification signals → primitive spotting. The first step of that sequence is therefore gated on the §3 decision.

### Phases D–G

Finish the review workspace · takeoff to estimate · multiple people, revisions and the conversation panel · commercial readiness (billing, SOC 2, terms, support).

### Housekeeping

- **Dev MinIO is now entirely orphaned.** Re-measured 2026-10-01: the bucket holds **8,372 objects under three org prefixes, and none of those three orgs exists in the database any more** — so every object is unreachable, not the ~3,894 this note previously recorded. Cleanup is written and still deliberately not run. Nothing reaps stored files in the product either (`ROADMAP.md` §2.2), and a reaper needs a retention policy first.
- A GitHub PAT found in a deleted `BidMate/.git/config` was never confirmed revoked. **Still unverified** — this has been open since 2026-09-25 and is the one item here with a security consequence.
- Docker currently has `postgres`, `minio`, `api` and `worker` all up.
- Three sibling worktrees live at `.worktrees/` (`accurate-symbol-marking`, `corpus-price-book`, `legend-named-clusters`) and several more under `.claude/worktrees/`. The `.worktrees/` three are what inflate a local `npm test`; see *Immediately* above.

---

## 8. Conventions

- Specs go to `docs/specs/<feature>.md`, plans to `docs/plans/<feature>.md` — same name, no date in the filename, date in the header. `docs/README.md` indexes everything.
- Plain CSS with tokens at the top of `styles.css`. No Tailwind, no CSS-in-JS, no inline hex.
- React function components with hooks. No state library — shared state comes from the store through `lib/useReviewStore.js`.
- Tabular numerals on every quantity, count, and total.
- Sentence case everywhere. No exclamation marks, no "successfully", no "please".
- Run `npm run build` before committing.
