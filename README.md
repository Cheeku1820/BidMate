# Takeoff review workspace

A high-fidelity, working prototype of the **blueprint review workspace** — the primary screen of an electrical estimating application that turns uploaded construction documents into a reviewable Division 26 takeoff.

This is screen F of a larger specification. It was built first because every other screen inherits its status vocabulary and data model.

![status: prototype](https://img.shields.io/badge/status-prototype-23528f) ![react](https://img.shields.io/badge/react-18-1c6f47) ![license](https://img.shields.io/badge/license-MIT-86827a)

---

## Run it

Everything runs against a real backend — Postgres, the API, and the takeoff engine. There is no fixture data: every row comes from a document you upload. You need [Docker](https://www.docker.com/), Python 3.12, and Node 18+.

Postgres and the API run in containers — dependencies install inside the image, nothing to set up on the host for this part:

```bash
docker compose up -d postgres api
docker compose run --rm api alembic upgrade head
```

Create the first account. There is no default password — choose your own:

```bash
docker compose run --rm \
  -e ADMIN_EMAIL="you@example.com" \
  -e ADMIN_PASSWORD="choose-a-password" \
  api python -m app.create_admin
```

The takeoff engine runs directly on your machine, not in a container — the browser reaches it at `localhost:8100` directly, so it needs its own Python environment. Install its dependencies once into a virtual environment, then start it, from `api/`:

```bash
cd api
python3 -m venv ../.enginevenv
../.enginevenv/bin/pip install -r requirements.txt
../.enginevenv/bin/uvicorn estimate_service:app --port 8100
```

Then the client, also on the host:

```bash
npm install
npm run dev
```

Open http://localhost:5173, sign in with the account you created, create a project, upload a drawing set, and process it.

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

**Classify an unknown symbol.** A symbol that isn't in the legend stays visible and reviewable rather than being silently dropped. Edit it to assign a real classification.

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

Every sheet comes from an uploaded document, so the canvas shows the honest surface for that: blank paper carrying just the sheet number and title, because there is no drawn geometry that could stand in for a page nobody in this codebase has seen. What grounds each item in the real drawing is its evidence — a crop of the source page around where it was counted, available from the item detail panel's "View evidence" control.

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
    PlanDrawing.jsx            honest blank-paper base layer under markers
    Symbols.jsx                electrical symbol glyphs
    notes/                     notes & assumptions — what the drawings don't say
      NotesWorkspace.jsx       the screen: list, filters, apply-and-re-run
      NoteForm.jsx             add/edit, with the context/reference control
      ApplyNotesBanner.jsx     offers the re-run when context notes are pending
      noteVocabulary.js        a note's own words, distinct from the review labels
```

The two API modules behind that screen:

```
api/app/takeoff/
  notes.py                     note CRUD, audited through commit(), not undoable
  reprocess.py                 the approval-preserving merge behind a re-run
```

If you open this repo in Claude Code, [`CLAUDE.md`](CLAUDE.md) loads automatically and carries the design context — status vocabulary, the rules that are easy to break, and the decisions still open.

Further reading: [`DESIGN.md`](DESIGN.md) covers the interaction rules — blueprint/table synchronization, autosave, undo semantics, revision handling, and the finish-review blocking logic — [`ROADMAP.md`](ROADMAP.md) inventories the work between this prototype and a shippable product, [`BUILD-STAGES.md`](BUILD-STAGES.md) sequences that work from MVP to platform, and [`docs/product-spec.md`](docs/product-spec.md) is the full eleven-screen specification.

---

## Accessibility

Targets WCAG 2.2 AA. Visible focus rings on every control, symbol markers reachable by keyboard with `Enter`/`Space` to select, `aria-label`s naming the item and its status, form fields with persistent visible labels, `prefers-reduced-motion` respected, and no status conveyed by color alone.

Single-key shortcuts (<kbd>A</kbd> approve, <kbd>E</kbd> edit, <kbd>R</kbd> reject, <kbd>J</kbd>/<kbd>K</kbd> step, <kbd>+</kbd>/<kbd>−</kbd>/<kbd>0</kbd> zoom) are suppressed while focus is in a text field.

Below 1024px the workspace shows a "use a larger screen" message rather than degrading the three-panel layout. This is deliberate — reviewing drawings on a phone is not a supported task.

---

## Known limitations

- **Sync is a poll, not a push channel.** The client polls the API every few seconds for changes from other reviewers, rather than receiving them immediately over a WebSocket. Undo is also still a single shared linear stack, so one reviewer can undo another's action from underneath them — shared undo needs conflict resolution, either operational transforms or per-user undo stacks with a merge policy, and that decision is still open.
- **The blueprint is drawn geometry, not a rendered PDF.** A production build would layer markers over `pdf.js` output.
- **Export produces a CSV, not yet a real Excel workbook.**
- **All eleven screens from the original spec are routed and built**, along with Notes & assumptions. Several of the newer workspace additions in the project nav are not — Assemblies, Labor, Material pricing, Estimate summary, Revisions, and Final review render as disabled with a reason, same for Company library, Integrations, and Help in the main nav. See [`ROADMAP.md`](ROADMAP.md).
- **Applying a note is audited but not undoable.** The re-run lands as one attributable entry in the action log; there is no single press that puts the takeoff back. Undo still covers approve, reject, edit, delete, bulk approve, and scale, across a re-run.

---

## License

MIT. See [`LICENSE`](LICENSE).
