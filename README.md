# Takeoff review workspace

A high-fidelity, working prototype of the **blueprint review workspace** — the primary screen of an electrical estimating application that turns uploaded construction documents into a reviewable Division 26 takeoff.

This is screen F of a larger specification. It was built first because every other screen inherits its status vocabulary and data model.

![status: prototype](https://img.shields.io/badge/status-prototype-23528f) ![react](https://img.shields.io/badge/react-18-1c6f47) ![license](https://img.shields.io/badge/license-MIT-86827a)

---

## Take a look

**Fastest — no install.** Open [`demo/index.html`](demo/index.html) directly in a browser. It's a single self-contained file with everything inlined. Download the repo as a ZIP, double-click that file, done.

**Run the dev server.**

```bash
git clone https://github.com/<your-username>/takeoff-review.git
cd takeoff-review
npm install
npm run dev
```

Then open http://localhost:5173. You need Node 18 or newer.

**Build and preview a production bundle.**

```bash
npm run build
npm run preview     # serves the built app on http://localhost:4173
```

**Publish it.** Push to GitHub and enable Pages (Settings → Pages → Source: GitHub Actions). The included workflow at `.github/workflows/deploy.yml` builds and deploys on every push to `main`, giving you a shareable URL.

---

## Try the multi-user behavior

Open the app in **two browser windows side by side**, both pointed at `localhost:5173`.

- Each window gets its own estimator identity, shown as a colored avatar in the top bar. Both windows see both avatars.
- Approve an item in one window. It changes in the other within a few seconds, and the totals in the bottom drawer update in both.
- Select an item in one window. The other window draws a dashed ring in that person's color around the same symbol, so you can see what a colleague is looking at.
- Press <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>Z</kbd> in either window. Undo pulls from a **shared** history stack, so you can undo a teammate's action — and the tooltip on the undo button names what you're about to reverse.

State syncs over `BroadcastChannel` + `localStorage`, which behaves like a real backend for demo purposes without needing one. See [Known limitations](#known-limitations) for what a production version would need instead.

---

## Run the full stack

Everything above runs the client alone, against `localStorage` — no install beyond Node. There is also a real backend (`api/`): Postgres, a FastAPI service, and a login screen in front of the same review workspace. You need [Docker](https://www.docker.com/) for this path.

```bash
docker compose up -d postgres api
docker compose run --rm api alembic upgrade head
```

Seed the demo project. The seed reads its login credential from the environment and refuses to run without one — there is no default password, so **choose your own** `SEED_EMAIL` and `SEED_PASSWORD` here:

```bash
docker compose run --rm \
  -e SEED_EMAIL="you@example.com" \
  -e SEED_PASSWORD="choose-a-password" \
  api python -m app.seed
```

Then bring up the web container and open **http://localhost:5174** (not 5173 — that port is commonly already in use, so the containerised client publishes on 5174 instead):

```bash
docker compose up -d web
```

Sign in with the `SEED_EMAIL`/`SEED_PASSWORD` you chose above. From here, the multi-user walkthrough above works the same way, except the "backend" is now Postgres: open a second browser window, sign in, approve an item in one, and watch it — and the presence avatar — appear in the other within a few seconds.

**`npm run dev` alone still runs the seed/`localStorage` mode**, API stopped or not — that's deliberate. The client picks its backend from `VITE_DATA_SOURCE`: unset (the default, including plain `npm run dev` on the host) means seed mode; `api` (set automatically inside the `web` container above) means the real backend. Seed mode never imports anything from the API path, which is what makes it possible to delete later without touching the rest of the client.

If you're running `npm run dev` on the host **against** the containerised API (`docker compose up postgres api`, then `npm run dev` separately), it talks to `http://localhost:8000` automatically — no extra configuration needed.

---

## Walk through the review flows

The seed project has 12 takeoff items across 3 sheets, deliberately seeded with the failure modes that matter.

**Resolve a conflict.** Open E2.1 and click the high-bay fixture symbol at grid D-2 (amber). The panel explains that the plan tag and the E0.1 luminaire schedule disagree about the fixture type. Press <kbd>E</kbd> to edit, correct the classification, then <kbd>A</kbd> to approve.

**Fix a missing scale.** Open E1.1. The banner says no scale was found in the title block, and the conduit run is drawn as a dashed red polyline because it couldn't be measured with confidence. Click **Set scale**, choose one — or pick **Calibrate against a known dimension**, then click the two ends of the 185'-0" dimension string across the top of the plan. Both paths clear the warning and flip the affected measured items to *Ready to review* in one undoable action.

**Classify an unknown symbol.** Also on E2.1, near the dock office, a dashed circle with a question mark marks a symbol that isn't in the legend. It stays visible and reviewable rather than being silently dropped. Edit it to assign a real classification.

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

**Every warning answers four questions** — what was found, why it matters, what to do, and where the evidence lives. That structure is enforced by the data shape itself (`warning: { title, found, why, fix, where }`), so a warning that skips one is a schema error rather than a copy oversight.

**Typography.** System sans stack at a 16px base, with tabular numerals on every quantity, count, and total so digits align in columns.

---

## What's in the drawing

The canvas isn't a placeholder rectangle. Each sheet is drafted with double-line exterior walls, a dashed column grid with lettered and numbered bubbles, structural columns at grid intersections, door swings, dimension strings, room tags with numbers, a north arrow, a graphic scale bar, and a title block carrying the sheet number and a revision triangle.

Takeoff items are drawn as **standard electrical symbols** — a circle with a bisecting line for a receptacle, a circle with an S for a switch, a crossed rectangle for a panel, a crossed circle for a high bay, a triangle for a data outlet — rather than generic pins. The symbol carries the item type, the ring color carries the review status, and the badge carries the warning. Three independent channels, no overloading.

Canvas controls: drag to pan, scroll to zoom toward the cursor, fit-to-page, a live minimap showing item positions and the current viewport, layer toggles, find-on-sheet dimming, hover tooltips, and a two-click calibration tool.

---

## Project structure

```
src/
  App.jsx                      auth gate: login vs. workspace, nothing else
  styles.css                   design tokens and every component style
  lib/
    data.js                    seed fixture: sheets, items, status definitions
    rules.js                   approval/totals/scale-release rules, mirrored from the API
    format.js                  time and initials formatting
    useReviewStore.js          the snapshot hook: store subscription, poll, saves, mutations
    store/
      index.js                 picks seed or api by VITE_DATA_SOURCE
      seed.js + seed-*.js       the localStorage/BroadcastChannel store
      api.js + api-mapping.js  the real backend store (fetch, caching, wire-shape mapping)
  components/
    Workspace.jsx              the review workspace: selection, filters, modals, shortcuts
    Login.jsx                  sign-in screen (api store only)
    TopBar.jsx, SheetsRail.jsx, CanvasPane.jsx, ItemDetailPanel.jsx, SummaryDrawer.jsx
    Modal.jsx, FinishReviewModal.jsx, MiscModals.jsx, Pill.jsx
    BlueprintCanvas.jsx        pan/zoom viewport, markers, measurements, minimap
    PlanDrawing.jsx            architectural plan geometry per sheet
    Symbols.jsx                electrical symbol glyphs
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

This is a design prototype, not a product. Specifically:

- **Two sync modes, neither production-grade.** The default `localStorage` + `BroadcastChannel` mode is single-machine, demonstrating the interaction model across tabs without a server. The optional `docker compose` mode (see "Run the full stack" above) is a real Postgres-backed API, but sync there is a three-second poll, not a push channel — real-time collaboration needs a WebSocket layer. Both modes share the same open question: undo is a single linear stack, so one reviewer can undo another's action from underneath them. Shared undo needs conflict resolution — either operational transforms or per-user undo stacks with a merge policy — and that decision is still open regardless of which sync mode is in front of it.
- **The blueprint is drawn geometry, not a rendered PDF.** A production build would layer markers over `pdf.js` output.
- **No takeoff is actually computed.** Items are seed data. There is no document ingestion, no detection, no export.
- **Screens A–E and G–K are not built.** See [`ROADMAP.md`](ROADMAP.md).

---

## License

MIT. See [`LICENSE`](LICENSE).
