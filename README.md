# Takeoff review workspace

A high-fidelity, working prototype of the **blueprint review workspace** — the primary screen of an electrical estimating application that turns uploaded construction documents into a reviewable Division 26 takeoff.

This is screen F of a larger specification. It was built first because every other screen inherits its status vocabulary and data model.

![status: prototype](https://img.shields.io/badge/status-prototype-23528f) ![react](https://img.shields.io/badge/react-18-1c6f47) ![license](https://img.shields.io/badge/license-MIT-86827a)

---

## Run it

Everything runs against a real backend — Postgres, object storage, the API, a job queue, and the worker that runs the takeoff engine. There is no fixture data: every row comes from a document you upload. You need [Docker](https://www.docker.com/) and Node 18+. A host Python environment is not needed to run the app — `.enginevenv` (`cd api && python3 -m venv ../.enginevenv && ../.enginevenv/bin/pip install -r requirements.txt`) is only for running the backend test suite (`../.enginevenv/bin/python -m pytest`) directly on the host instead of inside the `api` container.

Postgres, object storage (MinIO), the API, and the worker all run in containers — dependencies install inside the image, nothing to set up on the host for this part:

```bash
docker compose up -d postgres minio minio-init api worker
docker compose run --rm api alembic upgrade head
```

Uploaded documents are stored in MinIO, not on the API container's own disk, so an upload survives a reload or a container restart. `minio-init` creates the bucket the API writes to on first start; the dev credentials it uses are in [`docker-compose.yml`](docker-compose.yml), and the MinIO console is at http://localhost:9001 if you want to browse what got stored.

The `worker` container is the only process that opens a PDF. It polls a `jobs` table for documents to read and takeoffs to run, does the work — the same takeoff engine the prototype always had, just no longer reached by the browser directly — and writes sheets, items, and warnings back into the database the API also reads. It runs the same image as `api` with a different command, capped at 2 GB of memory and 256 processes so a hostile or malformed file is a one-container problem, and every job body runs inside a further sandboxed child process with a wall-clock timeout. Put `ANTHROPIC_API_KEY` in `api/.env` (copy `api/.env.example`) before bringing the stack up: both `api` and `worker` read that file, and a shell export alone no longer reaches the containers. The worker uses it for language-model classification and scope extraction and falls back to its deterministic paths without it; the same key powers the conversation panel on the right of every project screen, which says it isn't set up when the key is missing.

`ONEBUILD_API_KEY` and `SERPAPI_KEY` in `api/.env` turn on market estimates for Material pricing. Without them, every market row says so and nothing else is affected.

Create the first account. There is no default password — choose your own:

```bash
docker compose run --rm \
  -e ADMIN_EMAIL="you@example.com" \
  -e ADMIN_PASSWORD="choose-a-password" \
  api python -m app.create_admin
```

Then the client, also on the host:

```bash
npm install
npm run dev
```

Open http://localhost:5173, sign in with the account you created, create a project, upload a drawing set, and process it.

---

## Get the bid corpus

The engine's regression tests measure against eight real contractor bid sets — five vector, two raster, and one not yet asserted against — about 810 MB on disk, 770 MB to download. They are **not in the repo**: they are NDA'd drawings from named firms, so bid confidentiality keeps them out of git history ([`ROADMAP.md`](ROADMAP.md) §3.3), and two of the archives exceed GitHub's 100 MB file cap besides.

They are distributed through an access-controlled bucket instead. Ask for credentials, put them in your environment, and pull the sets in:

```bash
export CORPUS_BUCKET=... CORPUS_ACCESS_KEY=... CORPUS_SECRET_KEY=...
.enginevenv/bin/python scripts/corpus.py fetch
```

That lands them in `bid_examples/`, where [`api/tests/bid_set.py`](api/tests/bid_set.py) expects them. Each archive is verified against the SHA-256 digest committed in [`scripts/corpus-manifest.json`](scripts/corpus-manifest.json) before it is extracted — a mismatch is a hard failure rather than a warning, because the tests would otherwise run against a truncated set and report numbers nobody could reproduce.

Fetch one set rather than all eight — most of the engine assertions only need the Unalaska drawings:

```bash
.enginevenv/bin/python scripts/corpus.py fetch "Unalaska Bid"   # 144 MB
.enginevenv/bin/python scripts/corpus.py list                   # sizes and roles
.enginevenv/bin/python scripts/corpus.py verify                 # check what's on disk
```

`BIDMATE_CORPUS` and `BIDMATE_BID_SET` still override the paths if you keep the sets elsewhere. Without the corpus the engine tests **skip rather than fail**, so a green suite on a fresh checkout does not mean those assertions ran — `verify` is how you tell. Whoever holds the bucket publishes a new set with `scripts/corpus.py upload`, then commits the regenerated manifest.

---

## Try the multi-user behavior

Open the app in **two browser windows side by side**, both signed in against the same project.

- Each window gets its own estimator identity, shown as a colored avatar in the top bar. Both windows see both avatars.
- Approve an item in one window. It changes in the other within a few seconds, and the totals in the bottom drawer update in both.
- Select an item in one window. The other window draws a dashed ring in that person's color around the same symbol, so you can see what a colleague is looking at.
- Press <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>Z</kbd> in either window. Undo pulls from a **shared** history stack, so you can undo a teammate's action — and the tooltip on the undo button names what you're about to reverse.

The client polls the API every few seconds for changes from other reviewers. See [Known limitations](#known-limitations) for what real-time sync would need instead.

---

## Walk through the review flows

Once you've uploaded and processed a drawing set, the workspace surfaces whatever the engine found — including the failure modes that matter:

**Resolve a conflict.** A *Needs attention* item marks where the plan and a schedule disagree. Open its evidence, correct the classification, then approve it.

**Fix a missing scale.** A sheet with no scale in its title block shows measured items as *Missing information*, drawn as dashed red polylines because they can't be measured with confidence. Set the scale, or calibrate against a known dimension on the plan, to clear the warning and flip the affected items to *Ready to review*.

**Classify an unknown symbol.** A symbol that isn't in the legend stays visible and reviewable rather than being silently dropped. Type what it is in your own words — "2x4 LED troffer, type F on the E-501 schedule" — check what would change, and confirm: every one in the cluster is renamed and approved in one press, and the same tag elsewhere on the set is offered next. "Not a device" rejects with your reason.

**Put the hours in time.** Open **Phases and schedule**. The hours the takeoff already resolved are split across the six stages electrical work runs in — demolition, rough-in, wire pull, gear, trim, close-out — sized by the firm's crew for each, and drawn as bars on a week grid with the weekly manpower chart a GC asks for underneath. Everything computed says so and can be typed over; an override says it is yours. Where the drawings phase the job — `E-1.0` against `XE-1.0`, as the example set does — **Propose phases from sheet numbers** offers the split and writes nothing until you confirm, as one undoable action. Flag a switchboard as long-lead and the timeline counts an order-by date back from the stage that installs it, from a lead time a supplier quoted or your firm entered. Nothing here changes what is counted.

**Hand a GC a number before anything is approved.** Open **Estimate summary**. It exists the moment processing does — no approval step, no blocking gate — and every line says whether it was *Counted* from the documents or *Assumed*. An assumed line names what it rests on: a firm default, a market estimate, a rule of thumb, a length scaled off a sheet whose scale nobody confirmed. The budget range underneath the total is those assumptions' spread in dollars, not a confidence score. Type over any assumption and the number moves, attributed to you and undoable, and it survives the next run. Download it and every disclosure goes in the file with the total.

**Hit the blocking rule.** Click **Finish review** while any *Missing information* item remains. Completion is blocked, the blocking items are listed with direct links, and only *Needs attention* items can be carried forward — after an explicit acknowledgment checkbox.

---

## Design system

Everything in the interface resolves to tokens defined at the top of [`src/styles.css`](src/styles.css).

**Color.** Warm drafting-paper neutrals for surfaces, cool gray for ink, and four semantic status roles. Blueprint blue is used for primary actions, selection, and *Ready to review*. Green appears **only** on estimator-approved content. Amber means a decision is needed. Red is reserved for missing evidence and blocking errors.

**Status is never color alone.** Every status appears as a hue *plus* an icon *plus* a text label. Unverified measurements are additionally drawn as dashed polylines, so the distinction survives a grayscale print or a color-vision difference.

| Label | Meaning | Blocking? |
|---|---|---|
| Ready to review | Sufficient evidence, not yet approved | No |
| Needs attention | Conflicting or uncertain information | Only with acknowledgment |
| Missing information | Required evidence absent (scale, legend) | Yes |
| Estimator approved | A person confirmed it | — |

**Every warning answers four questions** — what was found, why it matters, what to do, and where the evidence lives. That structure is enforced by the data shape itself (`warning: { title, found, why, fix, where }`) and validated where a processed takeoff enters the system (`api/app/takeoff/ingest.py`), which refuses any warning missing one of those four, and refuses one whose `reason` is not a recognized kind. A warning that skips a field is a schema error rather than a copy oversight.

**Typography.** System sans stack at a 16px base, with tabular numerals on every quantity, count, and total so digits align in columns.

---

## What's in the drawing

Every sheet comes from an uploaded document, and the canvas now shows the real page: the worker renders each sheet into a tile pyramid at ingest, and the canvas draws those tiles at the page's true paper aspect, with markers rescaled at draw time to land on the real geometry. A sheet still awaiting its render, or one that failed to render, falls back to blank paper carrying the sheet's number, title, and render state — the takeoff still counts it either way.

The rendered page and the item's evidence crop are two witnesses to the same drawing, not one standing in for the other: the page shows where an item sits in context, the evidence — a crop of the source page around where it was counted, from the item detail panel's "View evidence" control — shows exactly what was read to count it.

Takeoff items are drawn as **standard electrical symbols** — a circle with a bisecting line for a receptacle, a circle with an S for a switch, a crossed rectangle for a panel, a crossed circle for a high bay, a triangle for a data outlet — rather than generic pins. The symbol carries the item type, the ring color carries the review status, and the badge carries the warning. Three independent channels, no overloading.

Canvas controls: drag to pan, scroll to zoom toward the cursor, fit-to-page, a live minimap showing item positions and the current viewport, layer toggles, find-on-sheet dimming, hover tooltips, and a two-click calibration tool.

---

## Project structure

```
src/
  App.jsx                      auth gate: login vs. workspace, nothing else
  styles.css                   design tokens and every component style
  lib/
    vocabulary.js              the status vocabulary: four review labels, never a fifth
    rules.js                   approval/totals/scale-release rules, mirrored from the API
    format.js                  time and initials formatting
    sheetGeometry.js           sheet space vs. the page's true paper aspect; the tile-to-marker math
    useReviewStore.js          the snapshot hook: store subscription, poll, saves, mutations
    store/
      index.js                 the single data source: the api store
      api.js + api-mapping.js  the backend store (fetch, caching, wire-shape mapping)
  components/
    Workspace.jsx              the review workspace: selection, filters, modals, shortcuts
    Login.jsx                  sign-in screen (api store only)
    TopBar.jsx, SheetsRail.jsx, CanvasPane.jsx, ItemDetailPanel.jsx, SummaryDrawer.jsx
    Modal.jsx, FinishReviewModal.jsx, MiscModals.jsx, Pill.jsx
    BlueprintCanvas.jsx        pan/zoom viewport, markers, measurements, minimap
    TileLayer.jsx              the rendered page as tiles under the markers, at its true aspect
    Symbols.jsx                electrical symbol glyphs
    notes/                     notes & assumptions — what the drawings don't say
      NotesWorkspace.jsx       the screen: list, filters, apply-and-re-run
      NoteForm.jsx             add/edit, with the context/reference control
      ApplyNotesBanner.jsx     offers the re-run when context notes are pending
      noteVocabulary.js        a note's own words, distinct from the review labels
    decision/                  the item panel's "What is this?" — box, proposal card, statement
    grid/                      the editable grid under Labor and Material pricing
      DataGrid.jsx             cells, in-place editors, validation, the Clear affordance
      useGridNavigation.js     the active-cell movement rules
    labor/, pricing/           Labor and Material pricing on that grid
    documents/                 the intake path — upload (C), confirm (D), processing (E)
      UploadDocuments.jsx      screen C as a view onto the API: uploads persist, progress is real
      ConfirmDrawings.jsx      screen D: the set as stored, plus the scope the documents state
      ScopeSection.jsx         screen D's scope list — found/confirmed/dismissed, not the four review labels
      ProcessingStatus.jsx     screen E: polls per-sheet progress from the worker's queue
      SheetProgressList.jsx    the per-sheet stage list screen E and the notes re-run both render
    conversation/              the panel — read-only in this slice
      ConversationPanel.jsx    the column: header, thread, composer, collapsed strip
      screenContext.jsx        the closed set of screen names (mirrored by api/app/assistant/schemas.py); selection and view reporting
    estimate/                  the ROM — counted and assumed, with a budget range
      EstimateSummary.jsx      the screen: the number, the range, four sections, qualifications
      EstimateSection.jsx      one section's lines, each marked counted or assumed
      OverrideBox.jsx          the estimator typing over an assumption, on the line that states it
      estimateCopy.js          the ROM's own words — counted/assumed, not the four review labels
      romDownload.js           the ROM as a CSV, every disclosure included
```

The API modules behind those screens:

```
api/app/takeoff/
  notes.py                     note CRUD, audited through commit(), not undoable
  merge.py                     the one write path for engine output — approval-preserving, per sheet
api/app/documents/
  blobstore.py                 the storage boundary — S3BlobStore over MinIO, MemoryBlobStore for tests
  service.py                   store / list / retype / delete / stream, each audited, none undoable
  router.py                    the five document routes, org-scoped through the project they belong to
  schemas.py                   the wire shape and the closed sets of document types and statuses
api/app/schedule/
  stages.py                    the six stages of electrical work, and the long-lead word list
  plan.py                      the derivation, pure: hours per stage, durations, working days, order-by
  phases.py                    phases as records — every mutation audited and undoable
  overrides.py                 what the estimator changes on a line, a stage, or a lead time
  assemble.py                  what the screen reads, through the same totals and labor functions
api/app/jobs/
  queue.py                     enqueue / claim / retry / stale-reclaim — the queue is the `jobs` table, no Redis
  status.py                    the stage words screen E polls; never a job id, an attempt count, or a source
api/app/scope/
  service.py                   scope statement CRUD, audited through commit(), not undoable
api/app/tiles/
  router.py                    the one read path for rendered bytes: per-tile and thumbnail routes, cached
api/app/worker/
  __main__.py                  the poll loop — the only process that opens a PDF
  render_job.py                the render job: one sheet's tile pyramid into the blob store, queued by the read
  sandbox.py                   runs every job body in a child process with a per-kind wall-clock timeout
api/app/engine/
  tiles.py                     cuts a sheet into the 512 px tile pyramid, in the visual frame, to ≥150 dpi
api/app/assistant/
  context.py                   what each screen puts in view, through the API's existing read paths
  prompt.py                    the frozen prompt; extracted text rendered as data, never instruction
  service.py, router.py        one thread per project; the answer streams over server-sent events
api/app/estimate/
  basis.py                     the nine bases an assumed number can rest on, and each one's spread
  generate_scope.py            exclusions no document addressed, and the ones the documents stated
  generate_takeoff.py          quantities derived rather than counted — branch footage, unscaled sheets
  generate_cost.py             what priced each line, read back off the existing resolvers
  exclusions.py                the one place an assumption subtracts, through countable_items()
  range.py                     the budget range as a dollar-weighted spread over basis classes
  write.py                     generate / regenerate — an estimator's override survives a re-run
```

Uploaded files are stored in MinIO (S3 in deployment) under a key built from the owning org and project, with one row per upload in the `documents` table carrying its hash and storage key. The API streams and hashes a file; it never opens one — that's the worker's job, inside the sandbox above. Design in [`docs/specs/documents-stored.md`](docs/specs/documents-stored.md) and [`docs/specs/engine-behind-the-api.md`](docs/specs/engine-behind-the-api.md).

If you open this repo in Claude Code, [`CLAUDE.md`](CLAUDE.md) loads automatically and carries the design context — status vocabulary, the rules that are easy to break, and the decisions still open.

Further reading: [`DESIGN.md`](DESIGN.md) covers the interaction rules — blueprint/table synchronization, autosave, undo semantics, revision handling, and the finish-review blocking logic — [`ROADMAP.md`](ROADMAP.md) inventories the work between this prototype and a shippable product, [`BUILD-STAGES.md`](BUILD-STAGES.md) sequences that work from MVP to platform, and [`docs/product/product-spec.md`](docs/product/product-spec.md) is the full eleven-screen specification.

---

## Accessibility

Targets WCAG 2.2 AA. Visible focus rings on every control, symbol markers reachable by keyboard with `Enter`/`Space` to select, `aria-label`s naming the item and its status, form fields with persistent visible labels, `prefers-reduced-motion` respected, and no status conveyed by color alone.

Single-key shortcuts (<kbd>A</kbd> approve, <kbd>E</kbd> edit, <kbd>R</kbd> reject, <kbd>J</kbd>/<kbd>K</kbd> step, <kbd>+</kbd>/<kbd>−</kbd>/<kbd>0</kbd> zoom) are suppressed while focus is in a text field. The item panel's "What is this?" box takes focus by itself only on an unclassified item — a symbol not in the legend — so stepping through classified items never swallows a key; press <kbd>E</kbd> to type on any other item, and <kbd>Esc</kbd> to leave the box.

Below 1024px the workspace shows a "use a larger screen" message rather than degrading the three-panel layout. This is deliberate — reviewing drawings on a phone is not a supported task.

---

## Known limitations

- **Sync is a poll, not a push channel.** The client polls the API every few seconds for changes from other reviewers, rather than receiving them immediately over a WebSocket. Undo is also still a single shared linear stack, so one reviewer can undo another's action from underneath them — shared undo needs conflict resolution, either operational transforms or per-user undo stacks with a merge policy, and that decision is still open.
- **The schedule stops at working days.** Phases, stages, crews, the weekly manpower chart, and long-lead order-by dates are built ([`docs/specs/phases-and-timeline.md`](docs/specs/phases-and-timeline.md)), but the calendar is Monday to Friday with no holidays and no overtime, phases run in order rather than through real dependencies, bars are edited in fields rather than dragged, and nothing imports the GC's own schedule. A lead time comes only from a supplier's quote or the firm's dated entry — flagged gear with neither says "Not yet quoted" and draws no date.
- **Export produces a CSV, not yet a real Excel workbook.** The ROM download is a CSV for the same reason.
- **The ROM stops at total direct cost.** Estimate summary carries no markup, overhead, profit, bond, or tax — that spread is the judgment a contractor is legally bound by, and no part of this system proposes it. Labor returned by the market feed is stored but still not resolved into the number.
- **All eleven screens from the original spec are routed and built**, along with Notes & assumptions. Several of the newer workspace additions in the project nav are not — Assemblies, Revisions, and Final review render as disabled with a reason, same for Company library, Integrations, and Help in the main nav. Labor and Material pricing are now built and routed, each carrying a pricing basis note. Estimate summary is built, and produces a CSV rather than a styled document, same as Export. See [`ROADMAP.md`](ROADMAP.md).
- **The conversation panel is read-only.** It answers questions about the screen in view and says where a change is made; it does not propose or apply changes yet. It needs `ANTHROPIC_API_KEY` on the API container; without one the panel says so and nothing else is affected.
- **Market estimates are catalog and shopping prices, not contractor net pricing.** The supplier price sheet is how a real quote gets in.
- **The pricing grid edits one cell at a time.** Labor and Material pricing behave like a spreadsheet at the cell level — click or type to edit, Tab/Enter/arrows to move, Delete to clear an entry — but there is no range selection, fill-down, or paste yet. Crew mix and per-line notes are stored by the API and not shown; a project default crew mix in project settings is the intended next step.
- **Applying a note is audited but not undoable.** The re-run lands as one attributable entry in the action log; there is no single press that puts the takeoff back. Undo still covers approve, reject, edit, delete, bulk approve, and scale, across a re-run.
- **An upload cancelled after its body was sent may still land.** Removing a row mid-upload aborts the request, but once the last byte has left the browser the server may finish storing the document before the abort reaches it. If that happens the document appears on the next load, "Uploaded", and can be removed like any other.
- **Nothing reaps stored files.** Deleting a document removes its file, but there is no retention policy or sweep: a file whose row was lost, or every file under an archived project, stays in storage indefinitely. See [`ROADMAP.md`](ROADMAP.md) §2.2.
- **Screen D confirms, but doesn't yet correct.** Include/exclude, discipline, revision, and scale corrections have no control on the confirm screen — every listed document runs through the takeoff, and sheet-level detail is whatever the worker's last read reported. See [`docs/roadmap/full-webapp-plan.md`](docs/roadmap/full-webapp-plan.md) Phase B4.
- **The queue has no bid-date priority, per-tenant cap, or dead-letter handling.** Takeoff work is claimed ahead of thumbnail renders, but across projects jobs are claimed oldest-first regardless of whose bid is due sooner, nothing limits how many of one project's jobs a worker pool can be occupied by, and a job that exhausts its three retries just sits `failed` — the recovery is starting the takeoff again, not a separate retry queue. See [`ROADMAP.md`](ROADMAP.md) §2.5.

---

## License

MIT. See [`LICENSE`](LICENSE).
