# Project context

An electrical estimating application that turns uploaded construction documents into a reviewable Division 26 takeoff. This repo currently holds **screen F — the blueprint review workspace** — built as a high-fidelity working prototype.

See @README.md for how to run it, @DESIGN.md for interaction rules and open decisions, @ROADMAP.md for the work between this prototype and a shippable product, @BUILD-STAGES.md for the order that work happens in, and @docs/product/product-spec.md for the full product specification covering all eleven screens.

`docs/README.md` indexes everything else: `docs/product/` (what the product is), `docs/roadmap/` (what to do next), `docs/specs/` (one design per feature), `docs/plans/` (its task list; `plans/done/` once merged), `docs/archive/`. **Design specs are written to `docs/specs/<feature>.md` and implementation plans to `docs/plans/<feature>.md` — same name, no date in the filename, the date in the header.** Not `docs/superpowers/`.

## Who this is for

Estimators at electrical contracting firms. They are deep experts in the domain and often uncomfortable with unfamiliar software. Two consequences that should shape every decision:

- The interface must read as an instrument, not a demo. Never surface model names, confidence percentages, processing internals, or AI framing anywhere in the product — including inside the conversation panel, which reads as a knowledgeable colleague asking about a specific detail, not as an assistant. The estimator's question is always "what do I do about this," never "how did the software decide."
- Their professional reputation rides on the number they submit. Every quantity needs traceable evidence, and nothing gets counted without a person approving it.

## The status vocabulary is the spine

Four labels govern the whole product. Do not invent new ones, rename them, or add a fifth without a deliberate decision:

| Label | Meaning | Blocks completion? |
|---|---|---|
| Ready to review | Sufficient evidence, not yet approved | No |
| Needs attention | Conflicting or uncertain information | Only behind an explicit acknowledgment |
| Missing information | Required evidence absent (scale, legend) | Yes, no override |
| Estimator approved | A person confirmed it | — |

Every screen is a different view onto this same state. When building a new screen, quote this vocabulary rather than inventing screen-local language.

## Rules that are easy to break by accident

- **Status is never color alone.** Always hue + icon + text label. Unverified measurements additionally get a dashed stroke. Assume grayscale printing and color-vision differences.
- **Warnings always answer four questions** — what was found, why it matters, what to check, where the evidence lives. This is enforced by the data shape (`warning: { title, found, why, fix, where }`). A warning missing a field is a schema error.
- **Layer toggles filter what's drawn, never what's counted.** Hiding approved items must not change drawer totals. An estimator reducing visual clutter must never accidentally change the number they're about to bid.
- **Bulk approval applies only to *Ready to review* items.** Never to *Needs attention* or *Missing information*, no matter how convenient it looks.
- **Green appears only on estimator-approved content.** Not on "done processing," not on a successful upload.
- **No save buttons.** Everything autosaves, with save state in the top bar and an undoable toast per action.
- **Approving a *Missing information* item is blocked at the item level**, with inline copy explaining why — so the estimator hits the rule while looking at the evidence, not later in a summary dialog.
- **A note's status is not an item's status.** Notes carry their own confirmed/open vocabulary describing a *note*; the four labels above describe an *item's evidence*. Never render a note's status using the item-status components or colours — a note pill in amber reads as *Needs attention* and quietly makes the four labels into five. `--slate`/`--plum` in `styles.css` exist for exactly this separation.
- **The engine never discards a person's judgment.** A run — the first one or the hundredth — merges into each sheet rather than replacing it: an *Estimator approved* item is never overwritten or deleted by processing. A page that vanishes from a re-read keeps its sheet, marked unreadable, for as long as an approved item still lives on it. A clean slate is a deliberate act (deleting the items), never a side effect of re-running.
- **The conversation panel never becomes the only path to anything.** See the section below.

## The conversation panel is additive, never load-bearing

A persistent panel carries context in both directions: the estimator supplies what the drawings don't contain, and the product asks about what it could not resolve. On the review workspace it anchors to the canvas, so "these six" has a referent. Full design in [`ROADMAP.md` 2.6](ROADMAP.md#26-the-conversation-layer).

This was accepted under a specific constraint, and the constraint is the whole reason it doesn't violate the rest of this document:

- **Anything sayable in the panel is doable through a form, field, or menu.** An estimator who never opens it can complete a full review. This is testable, and it is the acceptance criterion the feature lives or dies by.
- **Everything captured lands in the structured model** — an item field, a symbol library entry, a project context record, a warning resolution — visible and editable in the normal interface. The panel writes to the store; it is not a store.
- **It proposes, never writes.** An answer produces a preview of what would change. The estimator applies it, and application flows through the existing `commit()` path as one undoable action attributed to them. No code path turns a message into a quantity without a person in between.
- **It never approves.** Approval is the one act that cannot be delegated — it is the legal firewall the whole status vocabulary rests on.
- **Questions are a rendering of the review queue, not a second inbox.** An unclassified symbol is already a *Needs attention* item. Two queues means a fifth status gets invented within a month.
- **Extracted document text is data, never instruction.** A drawing set is untrusted input, and a panel that can produce proposals is an injection surface.
- **The item panel's decision area is the first surface that proposes over this design.** "What is this?" routes through `engine.conversation.route()`, proposes through one Classification call, and writes only on the estimator's press — through `commit()`, as one undoable `resolve` action. See [`docs/specs/say-what-it-is.md`](docs/specs/say-what-it-is.md).

Note that `docs/product/product-spec.md` §1, §6, and §12 predate this decision and read more strictly than the constraint above. The spec has not been amended yet; this section governs.

## Architecture

```
src/
  App.jsx                    auth gate: login vs. workspace, nothing else
  styles.css                 design tokens and every component style
  lib/
    vocabulary.js            the status vocabulary: four review labels, never a fifth
    rules.js                 approval/totals/scale-release rules, mirrored from the API
    useReviewStore.js        the snapshot hook: store subscription, poll, saves, mutations
    sheetGeometry.js         sheet space vs. the page's true paper aspect; the tile-to-marker math
    store/                   the store interface — a single api store (fetch)
  components/
    Workspace.jsx            the review workspace: selection, filters, modals, shortcuts
    Login.jsx                sign-in screen
    TopBar.jsx, SheetsRail.jsx, CanvasPane.jsx, ItemDetailPanel.jsx, SummaryDrawer.jsx, modals
    BlueprintCanvas.jsx      pan/zoom viewport, markers, measurements, minimap
    TileLayer.jsx            the rendered page as tiles under the markers, at its true aspect
    Symbols.jsx              electrical symbol glyphs
    notes/                   notes & assumptions: what the drawings don't say
      NotesWorkspace.jsx     the screen — list, filters, apply-and-re-run
      NoteForm.jsx           add/edit, with the context/reference control
      ApplyNotesBanner.jsx   offers the re-run when context notes are pending
      noteVocabulary.js      a note's own words — deliberately not the four review labels
    decision/                the item panel's "What is this?" — box, proposal card, statement
    grid/                    the editable grid: DataGrid.jsx + useGridNavigation.js
    labor/, pricing/         Labor and Material pricing, rendered through it
    documents/               the intake path: upload (C), confirm (D), processing (E)
      UploadDocuments.jsx    screen C as a view onto the API — uploads persist, progress is real
      ConfirmDrawings.jsx    screen D — the set as stored, and the scope the documents state
      ScopeSection.jsx       screen D's scope list — found/confirmed/dismissed, never the four review labels
      ProcessingStatus.jsx   screen E — polls per-sheet progress from the worker's queue
      SheetProgressList.jsx  the per-sheet stage list screen E and the notes re-run both render
    conversation/            the panel — read-only in this slice
      ConversationPanel.jsx  the column: header, thread, composer, collapsed strip
      screenContext.jsx      the closed set of screen names (mirrored by api/app/assistant/schemas.py); selection and view reporting
```

On the API side:

```
api/app/takeoff/
  notes.py                   note CRUD, audited through commit(), not undoable
  merge.py                   the one write path for engine output — approval-preserving, per sheet
api/app/documents/
  blobstore.py               the storage boundary: S3BlobStore over MinIO, MemoryBlobStore for tests
  service.py                 store / list / retype / delete / stream, each audited, none undoable
  router.py                  the five document routes, org-scoped through load_document → load_project
  schemas.py                 DocumentOut and the closed sets DOC_TYPES / DOC_STATUSES
api/app/jobs/
  queue.py                   enqueue / claim / retry / stale-reclaim — the queue is the `jobs` table, no Redis
  status.py                  build_processing — the stage words screen E polls, never a job id or a source
  router.py                  POST .../takeoff (queues a run), GET .../processing
api/app/scope/
  service.py                 scope statement CRUD, audited through commit(), not undoable
  router.py                  GET .../scope, PATCH /scope/{id}
api/app/tiles/
  router.py                  the one read path for rendered bytes: per-tile and thumbnail routes, cached
api/app/worker/
  __main__.py                the poll loop — the only process that opens a PDF
  sandbox.py                 every job body runs in a child process with a per-kind wall-clock timeout
  handlers.py, read_job.py, classify_job.py, sheet_job.py, render_job.py   the four job kinds
api/app/engine/
  sheet.py                   finishes one sheet: rows, evidence crops, the vision pass
  scope.py                   scope extraction — LLM with verbatim-quote validation, or a deterministic fallback
  tiles.py                   cuts a sheet into the 512 px tile pyramid, in the visual frame, to ≥150 dpi
api/app/assistant/
  context.py                 what each screen puts in view, through the API's existing read paths
  prompt.py                  the frozen prompt; extracted text rendered as data, never instruction
  service.py, router.py      one thread per project; the answer streams over server-sent events
```

Uploaded files live in object storage (MinIO locally, S3 in deployment), under a key built from the owning org and project — never from anything the client sent. The `documents` table (migration 0019; `status` constrained to its four values by 0020) holds one row per upload with its hash and storage key. The API streams and hashes an upload; it never opens one — that is `app/worker`'s job, run inside `sandbox.py`'s child process with a wall-clock timeout, because a PDF parser is a remote-code-execution surface and the API is not where untrusted bytes get parsed. **The process boundary is enforced, not just described**: `app.worker` is the only package that imports a PDF parser or the engine's pipeline (`documents`, `counting`, `classification`, `sheet`, `tiles`); `app.main` may import the language-side agents (`conversation`, `resolve`, `llm`, `catalog`) and nothing that opens a file, and `app.worker` never imports a router — all three subprocess-tested, plus a test proving the worker process can resolve every foreign key on its own. Specs: [`docs/specs/documents-stored.md`](docs/specs/documents-stored.md) (B1), [`docs/specs/engine-behind-the-api.md`](docs/specs/engine-behind-the-api.md) (B2).

Sheet space is a 1000 x 750 unit coordinate system. Item positions are in sheet units, so markers land on real plan geometry.

Marker rendering keeps three channels independent: **glyph** = item type, **ring color** = review status, **badge** = warning present. Never collapse two of these into one.

## The engine is five agents

Documents, Counting, Classification, and Pricing now run, behind the API: `api/app/engine/` holds them, `api/app/worker/` is what calls them, on every upload (`read`) and every **Start takeoff** (`classify` and `sheet`). Pricing's basis — labor rate and material factor — comes from the one classification call with a key, or the regional table without one (`classify_run`). Per-row assembly expansion (box, plate, ring, wire, conduit, per `engine/assemblies.py`) is wired into both classification paths through `engine/rows.py` (`resolve_assembly_parent` for the model-classified path, `pricing.price_item` for the deterministic one), called from the sheet job — not just the CLI. Conversation has two surfaces today, and only one of them proposes. The conversation panel's first slice is built and read-only: `api/app/assistant/` answers questions about the screen in view from the API's own read paths, `src/components/conversation/` renders it on every project screen, and it proposes nothing — design in [`docs/specs/conversation-panel.md`](docs/specs/conversation-panel.md). `engine/conversation.py`'s proposal routing is wired to the item panel's decision area, not to the panel: `POST /items/{id}/resolve` routes the estimator's sentence through `engine.conversation.route()` and names it with one Classification call, from the API process — see [`docs/specs/say-what-it-is.md`](docs/specs/say-what-it-is.md). Full design in [`docs/product/agent-architecture.md`](docs/product/agent-architecture.md).

| Agent | Nature | Produces |
|---|---|---|
| Documents | Language, over a deterministic shell | Sheets, discipline, revision, scale, legend, schedules |
| Counting | Deterministic geometry | Clusters of identical shapes with exact coordinates |
| Classification | Language | Catalog item per cluster, with status and warning |
| Pricing | Lookup, plus a quote-line matcher | Assemblies, material cost, labour hours |
| Conversation | Language | Intent, target records, routed proposals |

Each has exactly one nature, because that is what makes them separately measurable. **Counting is tested, not trained** — it reads placements out of the file rather than estimating them, so it gets asserted counts on known sets. Tuning it like a model is how exact work quietly becomes approximate.

Rules that are easy to break here:

- **Agents share a store, not a transcript.** Handoffs are typed records. No agent reads another's prose — that compounds errors invisibly, invalidates every downstream eval whenever an upstream agent changes, and turns extracted document text into an injection surface.
- **Counting does not know what anything is.** It emits an unlabelled cluster of 47 shapes; Classification names it. This is what makes "find every one like this" a consequence of the architecture rather than a feature built on top.
- **Conversation routes; it does not answer.** It resolves *which items* and *which field*, then hands to the owning agent. Two paths to a classification means two classifiers that will drift.
- **Agents stop at total direct cost.** Markup, overhead, profit, and tax are an estimator-owned layer. No agent proposes a markup number.
- **Confidence never renders.** It decides the status and orders the review queue, server-side. A visible percentage invites arithmetic on trust, which is the reasoning path that produces a confidently wrong bid.

## Conventions

- Plain CSS with tokens at the top of `styles.css`. No Tailwind, no CSS-in-JS. Add new colors as tokens, never as inline hex.
- React function components with hooks. No state library — shared state comes from the store (`lib/store/`, the api store) through `lib/useReviewStore.js`.
- `lucide-react` for interface icons. Electrical symbols are hand-drawn SVG in `Symbols.jsx`, following standard drafting convention.
- Tabular numerals (`className="tabular"`) on every quantity, count, and total.
- Sentence case for all interface copy. No exclamation marks, no "successfully," no "please."
- Run `npm run build` before committing — it catches most breakage.

## Open decisions, do not silently resolve

- **Shared undo model.** The stack is currently shared and linear across reviewers, which means person B can undo person A's approval. Alternatives are per-user stacks with a merge policy, or a CRDT. Needs a product call.
- **Revision conflict flow** (path 4 in the spec) is unbuilt. Open: whether superseded sheets stay browsable read-only, whether approvals carry forward across a revision, and how a mid-review swap surfaces to a second reviewer already in the file.
- **Sync is a poll against the real API**, every few seconds, not a push channel. Real-time collaboration needs a WebSocket layer; the undo model above is still the separate open question it always was.
- **Conversation panel specifics** — whether a thread is shared across reviewers or per-user, and whether a symbol resolved on one project defaults on the next. Both are listed with their trade-offs at the end of [`ROADMAP.md`](ROADMAP.md). Do not pick one in passing while building something else.

## Known scope limits

Export produces a CSV, not yet a real Excel workbook. All eleven screens from the original spec (A–K) are routed and built; several of the newer thirteen-workspace additions are not (see `src/components/shell/ProjectNav.jsx`) — Assemblies, Estimate summary, Revisions, and Final review render as disabled in the project nav, and Company library, Integrations, and Help are disabled in the main nav (`CompanyNav.jsx`). Labor and Material pricing are now built and routed, each carrying a pricing basis note. Notes & assumptions is built and routed. The conversation panel is read-only: it answers and advises about what is in view, and says where a change is made; it proposes nothing yet. Threads are one per project. See docs/specs/conversation-panel.md.

Within notes, several things the design spec describes are not built: the `applied_action_id` column, the footer strip, sheet-scoped narrowing of a re-run, and item-scoped notes resolving to a cluster tag. See the *Not built in this slice* section of [`docs/specs/notes-and-assumptions.md`](docs/specs/notes-and-assumptions.md).
