# Takeoff spreadsheet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the takeoff spreadsheet (spec §10) as a second view of the same item records the blueprint already shows, with selection synchronised in both directions and bulk approval restricted to *Ready to review*.

**Architecture:** The blueprint workspace currently owns the store subscription and the selection state inside one component, so a sibling route would get its own copy of both. This plan lifts both into a **project workspace layout route** that the canvas and the spreadsheet render inside, sharing state through `<Outlet context>` — no new dependency and no state library, matching the existing "shared state comes from the store" rule. The spreadsheet then renders the same `snapshot.items` as a table.

**Tech Stack:** React 18, Vite 5, `react-router-dom` 6 (`HashRouter`), Vitest + `@testing-library/react`, plain CSS with tokens; FastAPI + SQLAlchemy behind the api store.

## Global Constraints

From `CLAUDE.md`, `DESIGN.md`, `BUILD-STAGES.md`, and `docs/superpowers/specs/2026-08-16-bidmate-frontend-product-design.md`. Every task's requirements implicitly include this section.

- **The four review labels are fixed:** `Ready to review`, `Needs attention`, `Missing information`, `Estimator approved`. No fifth. *Missing information* blocks approval with no override; *Needs attention* may proceed only behind an explicit acknowledgment.
- **Bulk approval applies only to *Ready to review* items.** Never to *Needs attention* or *Missing information*, no matter how convenient it looks. `approvableInBulk()` in `src/lib/rules.js` is the single client-side definition; the server enforces it independently.
- **Status is never colour alone** — always hue + icon + text label.
- **Green appears only on estimator-approved content.**
- **Never fabricate a value.** An absent value renders as a blank with meaning, never an invented one and never the literal `"null"`. **This extends to columns: a column with no data behind it is not rendered at all** (see the Data Reality section).
- **Layer toggles and column visibility filter what is *drawn*, never what is *counted*.** Hiding a column or a row must not change drawer totals.
- **Totals are computed in exactly one place.** The drawer, this table, and the export read the same query. Do not compute a second sum.
- **No save buttons.** Everything autosaves; save state lives in the top bar.
- **Selection is bidirectional and lives in shared state, not in either view** (`DESIGN.md`). Selecting a row centres the blueprint on that marker; selecting a marker scrolls to and highlights the row.
- **Never surface model names, confidence percentages, or processing internals.**
- **Tabular numerals** (`className="tabular"`) on every quantity, count, total, and date.
- **Sentence case copy.** No exclamation marks, no "successfully," no "please." Error copy names a recovery action.
- **Real CSS tokens only.** There is **no spacing scale** — `var(--space-N)` does not exist and silently renders as no spacing. Tokens: `--paper-0/1`, `--surface`, `--canvas`, `--sheet`; `--line-1/2/3`; `--ink-1/2/3`; `--blue`, `--green`, `--amber`, `--red` each with `-tint`/`-line`; `--r-sm/md/lg`; `--dur`. Buttons are `.btn` plus `.btn--primary`, `.btn--danger`, `.btn--block`. **`.field` is the input element itself** — form wrappers are `.formfield`. A global `:focus-visible` rule already applies the focus ring; do not add per-component focus outlines. Body text 13–13.5px, secondary 12.5px, not rem.
- **`.chip` is already taken** by `SheetsRail.jsx` at 24px height. The dashboard's filter chips are `.filter-chip`. Reuse or namespace; do not redefine `.chip`.
- **Seed mode must never import from the API path** (`api.js`, `api-mapping.js`).
- **Routing is `HashRouter`** — use `<Link>`/`NavLink`, never a raw `href` to an app route.
- **`<React.StrictMode>` is active.** Mount effects double-invoke in dev; a `mountedRef` must be re-armed at the top of the effect body, not only at creation.
- Desktop only, optimised at 1440px, usable at 1280px. Touch targets ≥40px. **WCAG 2.2 AA**: persistent visible field labels, proper table header semantics, no status by colour alone.
- Run `npm test` and `npm run build` before every commit; both must pass. If a task touches the API, run `docker compose run --rm api pytest -q` too.
- **Never touch port 5173** — an unrelated application holds it. Browser verification uses `npm run dev -- --port 5199`.
- Comments explain *why*, not *what*, and match the surrounding files' density and voice.

---

## Data Reality — read this before Task 3

Spec §10.1 lists thirteen columns. **Four of them have no field anywhere in the system**, and two more are only derivable. This was verified against `api/app/takeoff/models.py`'s `Item` and `src/lib/store/api-mapping.js`'s `mapItem`:

| Spec §10.1 column | Backing data | Decision |
|---|---|---|
| Review status | `item.status` | **Build** |
| System | `item.system` | **Build** |
| Item/assembly | `item.name` | **Build** |
| Description | `item.description` | **Build** |
| Manufacturer/model requirement | *none* | **Do not render** |
| Quantity and unit | `item.quantity`, `item.unit` | **Build** |
| Waste factor | *none* | **Do not render** |
| Approved quantity | derivable: `quantity` when `status === "approved"` | **Build** |
| Floor/area | *none* | **Do not render** |
| Source sheet | `item.sheetId` → `sheet.number` | **Build** |
| Specification reference | *none* | **Do not render** |
| Notes | `item.notes` | **Build** |
| Last edited by | in the action log, not in the snapshot | **Defer** |

**Why not render an empty column.** A "Waste factor" column that is always blank does not read as "not implemented" — it reads as "no waste applied," which is a fabricated fact about the estimator's own numbers. Waste additionally has a settled meaning in [`docs/mvp-approach.md`](../../mvp-approach.md) §4.1 (store the measured quantity and the factor separately; derive the purchase quantity at the point of use) that a column would prejudge. The same logic applies to the other three.

**Why "Last edited by" is deferred rather than built.** The `Action` table carries `actor_user_id` and `created_at`, so the data exists — but the snapshot does not expose it, and adding it means a per-item lookup with the N+1 risk that `api/tests/test_projects.py` already guards against elsewhere. Spec §10.2 also lists "Change history," which needs the same query. Both belong in one later slice, not bolted on here.

## Scope — lean, per BUILD-STAGES

[`BUILD-STAGES.md`](../../../BUILD-STAGES.md) line 57 sanctions "a **lean screen G** — flat table, no grouping, but with bulk approve on *Ready to review*." That governs the scope of this plan.

**In scope:** the columns above, search, sort, status filter, column visibility, multi-row selection, bulk approve with per-item skip reasons, bidirectional selection with the canvas.

**Deliberately deferred** (all spec §10.2): grouping, column resize/freeze/reorder, copy/paste and fill-down, permitted formulas, change history, saved custom views, Excel export (its own slice), and the §10.3 takeoff-completion summary (belongs with final review).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/components/project/ProjectWorkspaceLayout.jsx` | Create: owns `useReviewStore` + selection for every project workspace; provides them via `<Outlet context>` |
| `src/components/project/useWorkspaceContext.js` | Create: the typed accessor for that context, so consumers do not each call `useOutletContext()` raw |
| `src/components/Workspace.jsx` | Modify: consumes the layout's context instead of owning the store and selection |
| `src/components/takeoff/TakeoffSpreadsheet.jsx` | Create: the table screen (spec §10) |
| `src/components/takeoff/spreadsheetColumns.js` | Create: the column definitions, one place |
| `src/components/takeoff/BulkApproveBar.jsx` | Create: selection count, the approve action, and the skipped-reason summary |
| `src/routes.jsx` | Modify: the layout route plus the `spreadsheet` child |
| `src/components/shell/ProjectNav.jsx` | Modify: mark Takeoff spreadsheet built |
| `src/lib/store/seed-review.js` | Modify: seed `bulkApprove` |
| `src/lib/store/api.js` | Modify: api `bulkApprove` |
| `src/lib/store/api.fakebackend.js` | Modify: the bulk-approve route |
| `src/lib/useReviewStore.js` | Modify: expose a `bulkApprove` wrapper |
| `src/styles.css` | Modify: spreadsheet styles |

---

### Task 1: Project workspace layout

**Files:**
- Create: `src/components/project/ProjectWorkspaceLayout.jsx`
- Create: `src/components/project/useWorkspaceContext.js`
- Modify: `src/components/Workspace.jsx`
- Modify: `src/routes.jsx`
- Test: `src/components/project/ProjectWorkspaceLayout.test.jsx`

**Interfaces:**
- Consumes: `store.useProject(projectId)`, `useReviewStore(store, { onSignedOut })`.
- Produces: `useWorkspaceContext()` returning `{ ...reviewStore, projectId, sheetId, setSheetId, selectedItemId, selectItem }`, where `reviewStore` is everything `useReviewStore` returns today (`snapshot`, `loading`, `loadError`, `saved`, `toast`, `dismissToast`, `itemError`, `clearItemError`, `setPresenceTarget`, `refresh`, `approveItem`, `rejectItem`, `unrejectItem`, `editItem`, `deleteItem`, `setScale`, `undo`, `redo`). `selectItem(itemId)` also sets `sheetId` to that item's sheet when the item is on a different one.

**This is the riskiest task in the plan.** It moves state out of a working, previously-shipped screen. The canvas must behave exactly as it does today. Two existing tests guard it — `src/components/Workspace.routeProjectId.test.jsx` (the ordering guarantee that `store.useProject` runs before the first fetch) and `src/components/Workspace.undoScoping.test.jsx` — and both must still pass unchanged.

- [ ] **Step 1: Write the failing test**

```jsx
// src/components/project/ProjectWorkspaceLayout.test.jsx
/* The layout exists so the blueprint and the spreadsheet are two views
   of one set of records rather than two components each holding their
   own copy. What that buys is asserted directly here: one store
   subscription for the whole project, and a selection both children
   read. */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectWorkspaceLayout from "./ProjectWorkspaceLayout.jsx";
import { useWorkspaceContext } from "./useWorkspaceContext.js";

const snapshot = {
  sheets: [
    { id: "s1", number: "E1.1", title: "Level 1 power", scale: '1/8"', superseded: false },
    { id: "s2", number: "E2.1", title: "Warehouse power", scale: '1/8"', superseded: false },
  ],
  items: [
    { id: "i1", sheetId: "s1", name: "20A duplex receptacle", status: "ready", quantity: 4, unit: "ea", rejected: false, warnings: [], version: 1 },
    { id: "i2", sheetId: "s2", name: "High bay fixture", status: "attention", quantity: 2, unit: "ea", rejected: false, warnings: [], version: 1 },
  ],
  totals: { bySystem: {}, approvedCount: 0, remainingCount: 2, attentionCount: 1, missingCount: 0, approvedUnits: 0 },
  undo: { canUndo: false, canRedo: false, label: null, undoBy: null },
  presence: [],
};

function makeStore() {
  return {
    useProject: vi.fn(),
    getSnapshot: vi.fn().mockResolvedValue(snapshot),
    subscribe: vi.fn().mockReturnValue(() => {}),
    setPresence: vi.fn().mockResolvedValue(undefined),
    me: vi.fn().mockResolvedValue({ id: "u1", name: "Dana Whitfield" }),
  };
}

/** A probe child: renders what the context exposes and can drive it. */
function Probe() {
  const { snapshot: snap, sheetId, selectedItemId, selectItem, projectId } = useWorkspaceContext();
  if (!snap) return <p>loading</p>;
  return (
    <div>
      <p data-testid="project">{projectId}</p>
      <p data-testid="sheet">{sheetId}</p>
      <p data-testid="selected">{selectedItemId ?? "none"}</p>
      <p data-testid="item-count">{snap.items.length}</p>
      <button type="button" onClick={() => selectItem("i2")}>
        Select i2
      </button>
    </div>
  );
}

const renderLayout = (store) =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/takeoff"]}>
      <Routes>
        <Route
          path="/projects/:projectId"
          element={<ProjectWorkspaceLayout store={store} me={{ id: "u1" }} onSignedOut={() => {}} />}
        >
          <Route path="takeoff" element={<Probe />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

describe("ProjectWorkspaceLayout", () => {
  it("points the store at the route's project before fetching anything", async () => {
    const store = makeStore();
    renderLayout(store);
    await screen.findByTestId("item-count");

    expect(store.useProject).toHaveBeenCalledWith("p1");
    const firstUseProject = store.useProject.mock.invocationCallOrder[0];
    const firstFetch = store.getSnapshot.mock.invocationCallOrder[0];
    expect(firstUseProject).toBeLessThan(firstFetch);
  });

  it("hands the snapshot to its child rather than each child fetching its own", async () => {
    const store = makeStore();
    renderLayout(store);

    expect(await screen.findByTestId("item-count")).toHaveTextContent("2");
    expect(screen.getByTestId("project")).toHaveTextContent("p1");
    // One subscription for the whole project, not one per view.
    expect(store.getSnapshot).toHaveBeenCalledTimes(1);
  });

  it("defaults the active sheet to the first one", async () => {
    renderLayout(makeStore());
    expect(await screen.findByTestId("sheet")).toHaveTextContent("s1");
  });

  it("follows a selection onto the sheet the item lives on", async () => {
    // Selecting a row for an item on another sheet has to bring the
    // blueprint with it, or the two views disagree about what is being
    // looked at (DESIGN.md, "Blueprint and table synchronization").
    renderLayout(makeStore());
    await screen.findByTestId("item-count");

    await userEvent.click(screen.getByRole("button", { name: /select i2/i }));

    expect(screen.getByTestId("selected")).toHaveTextContent("i2");
    expect(screen.getByTestId("sheet")).toHaveTextContent("s2");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ProjectWorkspaceLayout`
Expected: FAIL with `Failed to resolve import "./ProjectWorkspaceLayout.jsx"`.

- [ ] **Step 3: Write the context accessor**

```js
// src/components/project/useWorkspaceContext.js
/* ============================================================
   useWorkspaceContext.js — the accessor for what
   ProjectWorkspaceLayout provides.

   A thin wrapper over useOutletContext() rather than raw calls at each
   consumer: the error below is the reason. A component rendered outside
   the layout by mistake otherwise gets `undefined` and fails somewhere
   downstream with a destructuring error that says nothing about the
   actual cause.
   ============================================================ */

import { useOutletContext } from "react-router-dom";

export function useWorkspaceContext() {
  const context = useOutletContext();
  if (!context) {
    throw new Error(
      "useWorkspaceContext() was called outside ProjectWorkspaceLayout. " +
        "Project workspaces must be routed as children of the layout so they " +
        "share one store subscription and one selection.",
    );
  }
  return context;
}
```

- [ ] **Step 4: Write the layout**

```jsx
// src/components/project/ProjectWorkspaceLayout.jsx
/* ============================================================
   ProjectWorkspaceLayout.jsx — the state every project workspace
   shares.

   The blueprint and the takeoff spreadsheet are two views of one set of
   records (spec §10, DESIGN.md's "Blueprint and table
   synchronization"), which means exactly one store subscription and
   exactly one selection between them. Before this layout existed, both
   lived inside the blueprint workspace, so a sibling route would have
   opened a second subscription with its own poll and its own idea of
   what was selected -- two views that agree only by coincidence.

   Selection lives here rather than in either view, which is what
   DESIGN.md asks for in so many words.

   The `key={projectId}` remount that used to sit in Workspace.jsx moves
   here for the same reason it existed there: on a project switch the
   previous project's snapshot and selection must not be visible for the
   duration of the fetch, and a targeted "clear these fields" patch has
   to re-derive by hand what a remount gets for free.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
import { Outlet, useParams } from "react-router-dom";
import { useReviewStore } from "../../lib/useReviewStore.js";

export default function ProjectWorkspaceLayout({ store, me, onSignedOut }) {
  const { projectId } = useParams();
  return (
    <LayoutForProject
      key={projectId}
      projectId={projectId}
      store={store}
      me={me}
      onSignedOut={onSignedOut}
    />
  );
}

function LayoutForProject({ store, me, onSignedOut, projectId }) {
  // Declared ahead of useReviewStore() deliberately. React runs a
  // fiber's passive effects in the order their useEffect calls happened
  // during render, and useReviewStore's mount effect (the one that
  // fetches) is registered inside that call -- so declaring this first
  // is what guarantees the store is pointed at this project before the
  // first fetch, rather than a race that happens to work today.
  useEffect(() => {
    store.useProject(projectId);
  }, [store, projectId]);

  const review = useReviewStore(store, { onSignedOut });

  const [sheetId, setSheetId] = useState(null);
  const [selectedItemId, setSelectedItemId] = useState(null);

  const sheets = review.snapshot?.sheets ?? [];
  const items = review.snapshot?.items ?? [];

  useEffect(() => {
    if (sheets.length && (!sheetId || !sheets.some((s) => s.id === sheetId))) {
      setSheetId(sheets[0].id);
    }
  }, [sheets, sheetId]);

  // Selecting an item on another sheet brings the sheet with it.
  // Without this the blueprint would sit on one sheet while the table
  // highlighted a row belonging to another, and the estimator would have
  // two views telling them different things about what they are
  // looking at.
  const selectItem = useCallback(
    (itemId) => {
      setSelectedItemId(itemId);
      if (!itemId) return;
      const item = items.find((i) => i.id === itemId);
      if (item && item.sheetId !== sheetId) setSheetId(item.sheetId);
    },
    [items, sheetId],
  );

  // A selected item that has been deleted, or that belongs to a sheet
  // that just became superseded, must not stay selected -- the detail
  // panel would render a record that no longer exists.
  useEffect(() => {
    if (selectedItemId && !items.some((i) => i.id === selectedItemId)) {
      setSelectedItemId(null);
    }
  }, [items, selectedItemId]);

  return (
    <Outlet
      context={{
        ...review,
        projectId,
        me,
        sheetId,
        setSheetId,
        selectedItemId,
        selectItem,
      }}
    />
  );
}
```

- [ ] **Step 5: Run the layout tests**

Run: `npm test -- ProjectWorkspaceLayout`
Expected: PASS, all four.

- [ ] **Step 6: Point Workspace at the context instead of owning the state**

In `src/components/Workspace.jsx`:

1. Delete the `Workspace` wrapper that does `key={projectId}` and the `useEffect` calling `store.useProject(projectId)` — both moved to the layout.
2. Replace the `useReviewStore(store, { onSignedOut })` call and the `sheetId`/`selId` `useState` pairs with a single call to `useWorkspaceContext()`.
3. Keep every other piece of local state exactly as it is (`filter`, `sheetQuery`, `railOpen`, `drawerOpen`, `tool`, `canvasQuery`, `showFind`, `layers`, `menu`, `modal`, `edit`, `ack`) — those are canvas-local and do not belong in the layout.

The component becomes:

```jsx
export default function Workspace() {
  const {
    snapshot, loading, loadError, saved, toast, dismissToast,
    itemError, clearItemError, setPresenceTarget, refresh,
    approveItem, rejectItem, deleteItem, editItem, setScale, undo, redo,
    me, sheetId, setSheetId, selectedItemId, selectItem,
  } = useWorkspaceContext();

  // ... every other useState in this component stays exactly as it is ...
```

Then replace `selId` with `selectedItemId` and `setSelId(x)` with `selectItem(x)` throughout the file, and delete the `useEffect` that defaulted `sheetId` to `sheets[0]` — the layout owns that now. Add `import { useWorkspaceContext } from "./project/useWorkspaceContext.js";` and drop the now-unused `useReviewStore`, `useParams`, and `store`/`onSignedOut` props.

**Do not change any other behaviour in this file.** Selection semantics, filters, keyboard shortcuts, layer toggles, presence, and the modals all stay as they are. If a change looks necessary beyond the mechanical substitution above, stop and report rather than improvising.

- [ ] **Step 7: Rewire the routes**

In `src/routes.jsx`, replace the single takeoff route with a layout route:

```jsx
      <Route
        path="/projects/:projectId"
        element={<ProjectWorkspaceLayout store={store} me={me} onSignedOut={onSignedOut} />}
      >
        <Route path="takeoff" element={<Workspace />} />
      </Route>
```

Keep `/projects/:projectId` (the overview) as its own route — it is not a workspace child and fetches its own project row. Order matters: the overview's `index`-style path and the layout's path are the same string, so the overview must be declared as an `index` child of the layout **or** kept as a separate non-nested route declared first. Use the second, simpler form: leave `ProjectOverview` exactly where it is and give the layout route the same path with children only. React Router matches the more specific child path for `/takeoff` and the standalone route for the bare project path.

If that produces an ambiguous-route warning in the test output, make `ProjectOverview` an `index` child of the layout instead and report that you did — but do not leave a warning in the output either way.

- [ ] **Step 8: Verify nothing about the canvas changed**

```bash
npm test
npm run build
```

Expected: every test passes, including `Workspace.routeProjectId.test.jsx` and `Workspace.undoScoping.test.jsx` **unmodified**. If either needs editing to pass, that is a signal the refactor changed behaviour — stop and report rather than adjusting the test.

- [ ] **Step 9: Verify in a browser**

```bash
npm run dev -- --port 5199
```

Open `http://localhost:5199/#/projects` (note the `#` — `HashRouter`), enter the seeded project, and confirm the review workspace is unchanged: markers render, selecting a marker opens the detail panel, `J`/`K` step through items, the drawer totals show, undo works. Stop the server when done and report what you saw.

- [ ] **Step 10: Commit**

```bash
git add src/components/project/ src/components/Workspace.jsx src/routes.jsx
git commit -m "Lift the store subscription and selection into a project workspace layout"
```

---

### Task 2: bulkApprove on both stores

**Files:**
- Modify: `src/lib/store/seed-review.js`
- Modify: `src/lib/store/api.js`
- Modify: `src/lib/store/api.fakebackend.js`
- Modify: `src/lib/useReviewStore.js`
- Test: `src/lib/store/contract.test.js`

**Interfaces:**
- Consumes: `POST /api/projects/{project_id}/items/bulk-approve`, which already exists and returns `{ approved: string[], skipped: { item_id, code, message }[], snapshot }`.
- Produces: on both stores, `bulkApprove(itemIds: string[]) -> Promise<{ approved: string[], skipped: { itemId, code, message }[], snapshot }>`. On `useReviewStore`, a `bulkApprove(itemIds)` wrapper that sets the returned snapshot, shows a toast, and returns the same result so the caller can surface skips.

**Context you need:** the endpoint and the server-side rule already exist. `approvableInBulk()` in `src/lib/rules.js:77` is the client-side mirror and **has no caller yet** — its own test file says "its consumer is screen G, which is a later slice." This is that slice. The server enforces the rule independently; the client's copy exists for immediate feedback, not for correctness.

- [ ] **Step 1: Write the failing contract test**

Add to `src/lib/store/contract.test.js`, inside the block that runs against both stores, and add `"bulkApprove"` to the `METHODS` array at the top of the file:

```js
describe("bulkApprove", () => {
  it("approves Ready to review items and reports the rest as skipped", async () => {
    const snapshot = await store.getSnapshot();
    const ready = snapshot.items.filter((i) => i.status === "ready" && !i.rejected);
    const attention = snapshot.items.filter((i) => i.status === "attention" && !i.rejected);
    expect(ready.length).toBeGreaterThan(0);
    expect(attention.length).toBeGreaterThan(0);

    const result = await store.bulkApprove([...ready.map((i) => i.id), ...attention.map((i) => i.id)]);

    expect(result.approved.sort()).toEqual(ready.map((i) => i.id).sort());
    // Every non-ready item comes back with a reason, not silently dropped
    // -- the estimator has to learn why 6 of 40 did not approve.
    expect(result.skipped.map((s) => s.itemId).sort()).toEqual(attention.map((i) => i.id).sort());
    for (const skip of result.skipped) {
      expect(typeof skip.code).toBe("string");
      expect(skip.message).toMatch(/\S/);
    }
  });

  it("never approves a Missing information item, even when named explicitly", async () => {
    // CLAUDE.md names this as easy to break by accident. Missing
    // information blocks approval with no override, and "the caller
    // asked for it" is not an override.
    const snapshot = await store.getSnapshot();
    const missing = snapshot.items.filter((i) => i.status === "missing" && !i.rejected);
    expect(missing.length).toBeGreaterThan(0);

    const result = await store.bulkApprove(missing.map((i) => i.id));

    expect(result.approved).toEqual([]);
    expect(result.skipped).toHaveLength(missing.length);

    const after = await store.getSnapshot();
    for (const item of missing) {
      expect(after.items.find((i) => i.id === item.id).status).toBe("missing");
    }
  });

  it("returns a snapshot that already reflects the approvals", async () => {
    const snapshot = await store.getSnapshot();
    const ready = snapshot.items.filter((i) => i.status === "ready" && !i.rejected);

    const result = await store.bulkApprove(ready.map((i) => i.id));

    for (const id of result.approved) {
      expect(result.snapshot.items.find((i) => i.id === id).status).toBe("approved");
    }
  });

  it("does nothing and reports nothing on an empty list", async () => {
    const before = await store.getSnapshot();
    const result = await store.bulkApprove([]);
    expect(result.approved).toEqual([]);
    expect(result.skipped).toEqual([]);
    const after = await store.getSnapshot();
    expect(after.items.filter((i) => i.status === "approved").length).toBe(
      before.items.filter((i) => i.status === "approved").length,
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- contract`
Expected: FAIL with `store.bulkApprove is not a function`.

- [ ] **Step 3: Implement it in the seed store**

Add to `src/lib/store/seed-review.js`, inside `createReviewMethods`, and include `bulkApprove` in that module's returned object:

```js
  /** Mirrors api/app/takeoff/bulk.py's bulk_approve(): approve every
   *  Ready to review item named, and report every other one with a
   *  reason rather than dropping it. The reasons matter -- an estimator
   *  who selects forty rows and sees thirty-four approve needs to know
   *  why the other six did not, and "nothing happened" is the answer
   *  that sends them hunting.
   *
   *  Uses approvableInBulk() from rules.js rather than re-deriving the
   *  predicate: CLAUDE.md names bulk approval as easy to break by
   *  accident, and a second copy of "only Ready to review" is exactly
   *  how it breaks. */
  async function bulkApprove(itemIds) {
    const ids = Array.isArray(itemIds) ? itemIds : [];
    const items = readItems();
    const byId = Object.fromEntries(items.map((i) => [i.id, i]));

    const named = ids.map((id) => byId[id]).filter(Boolean);
    const approvable = new Set(approvableInBulk(named).map((i) => i.id));

    const skipped = [];
    for (const id of ids) {
      if (approvable.has(id)) continue;
      const item = byId[id];
      if (!item) skipped.push({ itemId: id, code: "not_in_project", message: "That item is no longer in this takeoff." });
      else if (item.rejected) skipped.push({ itemId: id, code: "rejected", message: "Rejected items are not part of the takeoff." });
      else if (item.status === "approved") skipped.push({ itemId: id, code: "already_approved", message: "Already approved." });
      else if (item.status === "attention") skipped.push({ itemId: id, code: "needs_attention", message: "Needs attention — review it individually before approving." });
      else if (item.status === "missing") skipped.push({ itemId: id, code: "missing_information", message: "Missing information — this cannot be approved until the evidence is supplied." });
      else skipped.push({ itemId: id, code: "not_ready", message: "Not ready to review." });
    }

    const approved = [...approvable];
    if (approved.length === 0) {
      return { approved: [], skipped, snapshot: await getSnapshot() };
    }

    const actor = identity();
    const at = Date.now();
    const nextItems = items.map((i) =>
      approvable.has(i.id) ? { ...i, status: "approved", approvedBy: actor.name, version: i.version + 1 } : i,
    );

    const action = {
      id: uid(),
      kind: "bulk-approve",
      items: approved.map((id) => ({ id, before: { status: byId[id].status, approvedBy: byId[id].approvedBy ?? null } })),
      by: actor.name,
      at,
      label: `Approved ${approved.length} ${approved.length === 1 ? "item" : "items"}`,
    };
    commitAction(action, nextItems);

    return { approved, skipped, snapshot: await getSnapshot() };
  }
```

Add `approvableInBulk` to this file's import from `../rules.js`.

**`seed-undo.js` must learn the new action kind**, or undoing a bulk approval will silently do nothing. In `src/lib/store/seed-undo.js`, add a branch alongside the existing `scale` branch in both `undo()` and `redo()`:

```js
    } else if (a.kind === "bulk-approve") {
      // Same shape as the compound scale action: one entry, many items,
      // one undo. DESIGN.md's rule that an estimator who regrets a
      // compound action gets one undo rather than fourteen applies here
      // exactly as it does to a scale confirmation.
      const before = Object.fromEntries(a.items.map((x) => [x.id, x.before]));
      items = items.map((i) => (before[i.id] ? { ...i, ...before[i.id], version: i.version + 1 } : i));
```

and the mirrored `redo` branch setting `status: "approved"` and `approvedBy: a.by` for each id.

- [ ] **Step 4: Add an undo test**

Add to `src/lib/store/contract.test.js`, in the same `describe("bulkApprove")` block:

```js
  it("is undone as one action, not one per item", async () => {
    // DESIGN.md: a compound action reverses as a unit. An estimator who
    // approves forty rows and immediately regrets it gets one undo.
    const snapshot = await store.getSnapshot();
    const ready = snapshot.items.filter((i) => i.status === "ready" && !i.rejected);
    expect(ready.length).toBeGreaterThan(1);

    await store.bulkApprove(ready.map((i) => i.id));
    const undone = await store.undo();
    expect(undone.performed).toBe(true);

    const after = await store.getSnapshot();
    for (const item of ready) {
      expect(after.items.find((i) => i.id === item.id).status).toBe("ready");
    }
  });
```

- [ ] **Step 5: Implement it in the api store**

In `src/lib/store/api.js`, add the method and include it in the returned object:

```js
  async function bulkApprove(itemIds) {
    const pid = await ensureProjectId();
    const raw = await request(`/api/projects/${pid}/items/bulk-approve`, {
      method: "POST",
      body: { item_ids: itemIds },
    });
    const snapshot = mapSnapshot(raw.snapshot);
    cacheSnapshot(snapshot);
    return {
      approved: raw.approved ?? [],
      skipped: (raw.skipped ?? []).map((s) => ({
        itemId: s.item_id,
        code: s.code,
        message: s.message,
      })),
      snapshot,
    };
  }
```

Check the actual names of the snapshot-mapping and cache helpers in that file and use those; the names above are the expected ones but the file is the authority.

- [ ] **Step 6: Teach the fake backend the route**

In `src/lib/store/api.fakebackend.js`, add a handler for `POST /api/projects/:id/items/bulk-approve` that delegates to the backing seed store's `bulkApprove` and converts the result to the wire shape (`item_id` rather than `itemId`, and a `snapshot` in wire form). Follow the file's existing dispatch pattern exactly — read it first rather than inventing a second style.

- [ ] **Step 7: Expose it through useReviewStore**

In `src/lib/useReviewStore.js`, add alongside the other compound actions (`setScale`, `undo`, `redo`) and include it in the returned object:

```js
  // A compound action, like setScale and undo: it returns a whole
  // authoritative snapshot rather than one item, because many rows move
  // at once. The result is returned to the caller as well as applied,
  // so the screen can tell the estimator which items did not approve
  // and why.
  const bulkApprove = useCallback(
    async (itemIds) => {
      try {
        const res = await runMutation(() => store.bulkApprove(itemIds));
        setSnapshot(res.snapshot);
        if (res.approved.length > 0) {
          showToast(`Approved ${res.approved.length} ${res.approved.length === 1 ? "item" : "items"}`);
        }
        return res;
      } catch (err) {
        handleSignedOut(err);
        throw err;
      }
    },
    [store, runMutation, showToast, handleSignedOut],
  );
```

Match the surrounding `setScale`/`undo` implementations' exact error handling; the sketch above may not mirror them precisely.

- [ ] **Step 8: Run the tests**

```bash
npm test
npm run build
```

Expected: all pass, including both stores through the shared `describe("bulkApprove")` block.

- [ ] **Step 9: Commit**

```bash
git add src/lib/store/ src/lib/useReviewStore.js
git commit -m "Add bulkApprove to both stores, restricted to Ready to review"
```

---

### Task 3: The spreadsheet table

**Files:**
- Create: `src/components/takeoff/spreadsheetColumns.js`
- Create: `src/components/takeoff/TakeoffSpreadsheet.jsx`
- Modify: `src/routes.jsx`
- Modify: `src/components/shell/ProjectNav.jsx`
- Modify: `src/styles.css`
- Test: `src/components/takeoff/TakeoffSpreadsheet.test.jsx`
- Test: `src/components/takeoff/spreadsheetColumns.test.js`

**Interfaces:**
- Consumes: `useWorkspaceContext()` from Task 1.
- Produces: `COLUMNS` — an array of `{ key, label, align, render(item, ctx) }` where `ctx` is `{ sheetsById }`; `DEFAULT_VISIBLE` — the `Set` of column keys shown initially. `<TakeoffSpreadsheet />` at `/projects/:projectId/spreadsheet`.

**Read the Data Reality section above before starting.** Four of spec §10.1's columns have no backing field and are deliberately not rendered. Do not add them, and do not add a placeholder value for them.

- [ ] **Step 1: Write the failing column tests**

```js
// src/components/takeoff/spreadsheetColumns.test.js
/* The column set is data-driven so the table body and the visibility
   control cannot disagree about what exists. These tests pin the
   decision recorded in the plan's Data Reality section: only columns
   with a real field behind them are rendered, because an always-empty
   "Waste factor" column reads as "no waste applied" rather than "not
   built" -- a fabricated fact about the estimator's own numbers. */

import { describe, expect, it } from "vitest";
import { COLUMNS, DEFAULT_VISIBLE } from "./spreadsheetColumns.js";

const sheetsById = { s1: { id: "s1", number: "E1.1", title: "Level 1 power" } };
const item = {
  id: "i1",
  sheetId: "s1",
  name: "20A duplex receptacle",
  description: "Duplex receptacle, 20A, 125V",
  system: "Power",
  quantity: 12,
  unit: "ea",
  status: "approved",
  notes: "Verify mounting height",
  rejected: false,
  warnings: [],
};

describe("COLUMNS", () => {
  it("renders only columns with a field behind them", () => {
    const keys = COLUMNS.map((c) => c.key);
    for (const present of ["status", "system", "name", "description", "quantity", "approvedQuantity", "sheet", "notes"]) {
      expect(keys).toContain(present);
    }
    // No data exists for these anywhere in the item model.
    for (const absent of ["wasteFactor", "manufacturer", "floor", "specReference", "lastEditedBy"]) {
      expect(keys).not.toContain(absent);
    }
  });

  it("gives every column a non-empty label and a renderer", () => {
    for (const column of COLUMNS) {
      expect(column.label).toMatch(/\S/);
      expect(typeof column.render).toBe("function");
    }
  });

  it("resolves the source sheet to its number, not its id", () => {
    const sheet = COLUMNS.find((c) => c.key === "sheet");
    expect(sheet.render(item, { sheetsById })).toBe("E1.1");
  });

  it("shows an approved quantity only once the item is approved", () => {
    // An unapproved quantity in a column headed "Approved" is a number
    // an estimator could carry into a bid before anyone confirmed it.
    const column = COLUMNS.find((c) => c.key === "approvedQuantity");
    expect(column.render(item, { sheetsById })).toContain("12");
    expect(column.render({ ...item, status: "ready" }, { sheetsById })).toBe("—");
  });

  it("defaults to a readable subset rather than every column at once", () => {
    expect(DEFAULT_VISIBLE.size).toBeGreaterThan(3);
    expect(DEFAULT_VISIBLE.size).toBeLessThanOrEqual(COLUMNS.length);
    expect(DEFAULT_VISIBLE.has("status")).toBe(true);
    expect(DEFAULT_VISIBLE.has("name")).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- spreadsheetColumns`
Expected: FAIL with `Failed to resolve import "./spreadsheetColumns.js"`.

- [ ] **Step 3: Write the column definitions**

```js
// src/components/takeoff/spreadsheetColumns.js
/* ============================================================
   spreadsheetColumns.js — what the takeoff table shows.

   Data-driven so the header row, the body, and the column-visibility
   control read one list rather than three that can drift.

   Spec §10.1 lists thirteen columns. Four of them -- manufacturer/model
   requirement, waste factor, floor/area, and specification reference --
   have no field anywhere in the item model, and one more (last edited
   by) lives in the action log rather than the snapshot. They are absent
   here rather than rendered empty: a blank cell under "Waste factor"
   does not read as "not built yet", it reads as "no waste applied",
   which is a fabricated fact about the estimator's own numbers. Waste
   in particular has a settled meaning in docs/mvp-approach.md §4.1 --
   store the measured quantity and the factor separately, derive the
   purchase quantity at the point of use -- that a column here would
   prejudge.
   ============================================================ */

import { STATUS } from "../../lib/data.js";

/** The absent-value mark. A dash reads as "nothing here" where an empty
 *  cell reads as an oversight. */
const NONE = "—";

export const COLUMNS = [
  {
    key: "status",
    label: "Status",
    align: "left",
    // Rendered by the table itself rather than here: status needs an
    // icon and a hue alongside the text (never colour alone), which is
    // markup rather than a string.
    render: (item) => STATUS[item.status]?.label ?? item.status,
  },
  { key: "name", label: "Item", align: "left", render: (item) => item.name },
  { key: "description", label: "Description", align: "left", render: (item) => item.description || NONE },
  { key: "system", label: "System", align: "left", render: (item) => item.system || NONE },
  {
    key: "quantity",
    label: "Quantity",
    align: "right",
    render: (item) => `${item.quantity} ${item.unit}`.trim(),
  },
  {
    key: "approvedQuantity",
    label: "Approved quantity",
    align: "right",
    // Only an approved item has an approved quantity. Showing the raw
    // quantity here for an unapproved row would put a number under an
    // "Approved" heading that nobody has confirmed.
    render: (item) => (item.status === "approved" ? `${item.quantity} ${item.unit}`.trim() : NONE),
  },
  {
    key: "sheet",
    label: "Sheet",
    align: "left",
    render: (item, { sheetsById }) => sheetsById[item.sheetId]?.number ?? NONE,
  },
  { key: "notes", label: "Notes", align: "left", render: (item) => item.notes || NONE },
];

/** Description and notes are long and push the numeric columns off the
 *  visible width at 1280px, so they start hidden and can be switched on.
 *  Everything else starts visible. */
export const DEFAULT_VISIBLE = new Set(
  COLUMNS.map((c) => c.key).filter((key) => key !== "description" && key !== "notes"),
);
```

Check `src/lib/data.js` for the exact shape of `STATUS` — the label lookup above assumes `STATUS[key].label`. Use whatever it actually exports.

- [ ] **Step 4: Run the column tests**

Run: `npm test -- spreadsheetColumns`
Expected: PASS, all five.

- [ ] **Step 5: Write the failing table tests**

```jsx
// src/components/takeoff/TakeoffSpreadsheet.test.jsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import TakeoffSpreadsheet from "./TakeoffSpreadsheet.jsx";

const items = [
  { id: "i1", sheetId: "s1", name: "20A duplex receptacle", description: "Duplex, 20A", system: "Power", quantity: 12, unit: "ea", status: "approved", notes: "", rejected: false, warnings: [], version: 1 },
  { id: "i2", sheetId: "s2", name: "High bay fixture", description: "LED high bay", system: "Lighting", quantity: 4, unit: "ea", status: "attention", notes: "", rejected: false, warnings: [{ title: "Schedule conflict" }], version: 1 },
  { id: "i3", sheetId: "s1", name: "Conduit run", description: "3/4in EMT", system: "Power", quantity: 60, unit: "ft", status: "missing", notes: "", rejected: false, warnings: [], version: 1 },
];

const context = {
  snapshot: {
    sheets: [
      { id: "s1", number: "E1.1", title: "Level 1 power", superseded: false },
      { id: "s2", number: "E2.1", title: "Warehouse power", superseded: false },
    ],
    items,
    totals: { bySystem: {}, approvedCount: 1, remainingCount: 2, attentionCount: 1, missingCount: 1, approvedUnits: 12 },
    undo: { canUndo: false, canRedo: false, label: null, undoBy: null },
    presence: [],
  },
  loading: false,
  loadError: null,
  selectedItemId: null,
  selectItem: vi.fn(),
  sheetId: "s1",
  setSheetId: vi.fn(),
  bulkApprove: vi.fn(),
  projectId: "p1",
};

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

const renderSheet = () =>
  render(
    <MemoryRouter>
      <TakeoffSpreadsheet />
    </MemoryRouter>,
  );

describe("TakeoffSpreadsheet", () => {
  it("renders one row per item with proper table semantics", () => {
    renderSheet();
    expect(screen.getAllByRole("row")).toHaveLength(items.length + 1); // + header
    expect(screen.getByRole("columnheader", { name: /status/i })).toBeTruthy();
  });

  it("shows each status as text, not colour alone", () => {
    renderSheet();
    expect(screen.getByText(/estimator approved/i)).toBeTruthy();
    expect(screen.getByText(/needs attention/i)).toBeTruthy();
    expect(screen.getByText(/missing information/i)).toBeTruthy();
  });

  it("does not render columns that have no data behind them", () => {
    // See the plan's Data Reality section: a blank "Waste factor" column
    // reads as "no waste applied", which is a fabricated fact.
    renderSheet();
    for (const absent of [/waste/i, /manufacturer/i, /floor/i, /specification/i]) {
      expect(screen.queryByRole("columnheader", { name: absent })).toBeNull();
    }
  });

  it("filters by status", async () => {
    renderSheet();
    await userEvent.click(screen.getByRole("button", { name: /needs attention/i }));
    expect(screen.getByText("High bay fixture")).toBeTruthy();
    expect(screen.queryByText("20A duplex receptacle")).toBeNull();
  });

  it("searches across item name and description", async () => {
    renderSheet();
    await userEvent.type(screen.getByLabelText(/search items/i), "high bay");
    expect(screen.getByText("High bay fixture")).toBeTruthy();
    expect(screen.queryByText("Conduit run")).toBeNull();
  });

  it("sorts by a column when its header is activated", async () => {
    renderSheet();
    await userEvent.click(screen.getByRole("button", { name: /sort by item/i }));
    const names = screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[1].textContent);
    expect(names).toEqual([...names].sort());
  });

  it("hides a column without removing its rows", async () => {
    // Column visibility filters what is drawn, never what is counted --
    // the same rule the canvas layer toggles follow.
    renderSheet();
    const before = screen.getAllByRole("row").length;

    await userEvent.click(screen.getByRole("button", { name: /columns/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /system/i }));

    expect(screen.queryByRole("columnheader", { name: /^system$/i })).toBeNull();
    expect(screen.getAllByRole("row")).toHaveLength(before);
  });

  it("names a recovery action when nothing matches", async () => {
    renderSheet();
    await userEvent.type(screen.getByLabelText(/search items/i), "zzzz");
    expect(screen.getByText(/no items match/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /clear search/i })).toBeTruthy();
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `npm test -- TakeoffSpreadsheet`
Expected: FAIL with `Failed to resolve import "./TakeoffSpreadsheet.jsx"`.

- [ ] **Step 7: Write the table**

Build `src/components/takeoff/TakeoffSpreadsheet.jsx` reading `useWorkspaceContext()` for `snapshot`, `loading`, `loadError`, `selectedItemId`, and `selectItem`. It renders:

- An `AppTopBar` with the project title and no primary action yet (Task 5 adds one).
- A controls row: a labelled search field, status filter buttons, and a "Columns" toggle listing each column as a labelled checkbox.

  **On the status filters specifically:** `src/lib/data.js`'s `STATUS` has **five** keys, not four — `ready`, `attention`, `missing`, `approved`, and `rejected`. The fifth is not a review status. `Pill.jsx:18-26` explains why it exists: rejection is a boolean field on the item that the display layer folds into one value for colouring, and the API and both stores keep it separate from `status` on purpose. Build the filters from the four review labels only, and if a rejected view is wanted, treat it as a separate toggle over the `rejected` flag rather than a fifth chip beside the four. Adding a fifth status chip is the exact accident `CLAUDE.md` warns about.
- A `<table className="data-table takeoff-table">` with `<th scope="col">` headers, each header containing a `<button>` named `Sort by {label}` that toggles ascending/descending, and `<th scope="row">` on the item-name cell.
- The status cell rendering hue + icon + text via the existing `Pill.jsx`, which already does exactly that: `<Pill status={displayStatus(item)} />`, importing both from `../Pill.jsx`. Do not write a second status renderer — `displayStatus(item)` is the one place the `rejected` flag folds back into a display value, and a parallel implementation would drift from it.
- Empty states: `loading` shows "Loading takeoff…", `loadError` shows the error with a retry that calls `refresh()`, no items shows "This project has no takeoff items yet.", and no matches shows "No items match" with a "Clear search" button.

Derive rows with `useMemo` over `snapshot.items`, filtering rejected items out of the default view. **Do not compute totals here** — the drawer owns them.

- [ ] **Step 8: Add the route and mark the workspace built**

In `src/routes.jsx`, add inside the layout route from Task 1:

```jsx
        <Route path="spreadsheet" element={<TakeoffSpreadsheet />} />
```

In `src/components/shell/ProjectNav.jsx`, change the `spreadsheet` entry's `built` flag to `true`.

- [ ] **Step 9: Add the styles**

Append to `src/styles.css`, reusing the existing `.data-table` rules from the dashboard and adding only what differs — a denser row, a sticky header, and a horizontal scroll container so wide content never makes the page body scroll sideways:

```css
/* ---- Takeoff spreadsheet (spec §10) ---- */
.takeoff-table-scroll { overflow-x: auto; }
.takeoff-table th, .takeoff-table td { padding: 7px 10px; }
.takeoff-table thead th { position: sticky; top: 0; background: var(--surface); z-index: 1; }
.takeoff-table tbody tr.is-selected { background: var(--blue-tint); }
.takeoff-sort {
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-weight: 600;
  color: var(--ink-2);
  cursor: pointer;
}
.takeoff-columns { display: flex; flex-wrap: wrap; gap: 10px; }
```

- [ ] **Step 10: Run the tests and build**

```bash
npm test
npm run build
```

Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add src/components/takeoff/ src/routes.jsx src/components/shell/ProjectNav.jsx src/styles.css
git commit -m "Add the takeoff spreadsheet with search, filter, sort, and column visibility"
```

---

### Task 4: Bidirectional selection

**Files:**
- Modify: `src/components/takeoff/TakeoffSpreadsheet.jsx`
- Test: `src/components/takeoff/TakeoffSpreadsheet.selection.test.jsx`

**Interfaces:**
- Consumes: `selectedItemId` and `selectItem(itemId)` from the layout context.
- Produces: nothing new; this task wires the table into the selection the layout already owns.

- [ ] **Step 1: Write the failing test**

```jsx
// src/components/takeoff/TakeoffSpreadsheet.selection.test.jsx
/* DESIGN.md: "Selecting a marker selects its takeoff row and, in the
   table view, scrolls to and highlights that row. Selecting a row
   centers the blueprint on that marker and selects it." Selection lives
   in shared state, so both directions are the same one field moving --
   these tests assert the table reads it and writes it. */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import TakeoffSpreadsheet from "./TakeoffSpreadsheet.jsx";

const items = [
  { id: "i1", sheetId: "s1", name: "20A duplex receptacle", description: "", system: "Power", quantity: 12, unit: "ea", status: "ready", notes: "", rejected: false, warnings: [], version: 1 },
  { id: "i2", sheetId: "s2", name: "High bay fixture", description: "", system: "Lighting", quantity: 4, unit: "ea", status: "ready", notes: "", rejected: false, warnings: [], version: 1 },
];

const context = {
  snapshot: {
    sheets: [
      { id: "s1", number: "E1.1", title: "Level 1 power", superseded: false },
      { id: "s2", number: "E2.1", title: "Warehouse power", superseded: false },
    ],
    items,
    totals: { bySystem: {}, approvedCount: 0, remainingCount: 2, attentionCount: 0, missingCount: 0, approvedUnits: 0 },
    undo: { canUndo: false, canRedo: false, label: null, undoBy: null },
    presence: [],
  },
  loading: false,
  loadError: null,
  selectedItemId: null,
  selectItem: vi.fn(),
  sheetId: "s1",
  setSheetId: vi.fn(),
  bulkApprove: vi.fn(),
  projectId: "p1",
};

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

const renderSheet = () =>
  render(
    <MemoryRouter>
      <TakeoffSpreadsheet />
    </MemoryRouter>,
  );

beforeEach(() => {
  context.selectedItemId = null;
  context.selectItem.mockClear();
});

describe("TakeoffSpreadsheet selection", () => {
  it("reports a clicked row to the shared selection", async () => {
    renderSheet();
    await userEvent.click(screen.getByText("High bay fixture"));
    expect(context.selectItem).toHaveBeenCalledWith("i2");
  });

  it("marks the selected row, and marks only that one", () => {
    context.selectedItemId = "i2";
    renderSheet();

    const rows = screen.getAllByRole("row").slice(1);
    const selected = rows.filter((r) => r.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(within(selected[0]).getByText("High bay fixture")).toBeTruthy();
  });

  it("is reachable and selectable from the keyboard", async () => {
    // Spec §8: keyboard navigation through table rows. A row selectable
    // only by mouse is a hover-only control by another name.
    renderSheet();
    const row = screen.getByText("High bay fixture").closest("tr");
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(context.selectItem).toHaveBeenCalledWith("i2");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- TakeoffSpreadsheet.selection`
Expected: FAIL — rows carry no `aria-selected` and no click handler yet.

- [ ] **Step 3: Wire selection into the rows**

Give each `<tr>`: `onClick={() => selectItem(item.id)}`, `aria-selected={item.id === selectedItemId}`, `tabIndex={0}`, an `onKeyDown` that calls `selectItem(item.id)` on `Enter` or `Space` (and calls `preventDefault()` on `Space` so the page does not scroll), and `className={item.id === selectedItemId ? "is-selected" : undefined}`.

Scroll the selected row into view when the selection changes and the row is not already visible:

```jsx
  const selectedRowRef = useRef(null);
  useEffect(() => {
    // Selecting a marker on the canvas has to bring its row into view
    // here, or the two views agree about the selection while showing the
    // estimator different things.
    selectedRowRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedItemId]);
```

Attach `ref={item.id === selectedItemId ? selectedRowRef : null}` to each row. Guard the call with `?.` — `scrollIntoView` is not implemented in jsdom and will be `undefined` there, so an unguarded call fails every test in this file.

- [ ] **Step 4: Run the tests**

```bash
npm test -- TakeoffSpreadsheet
npm run build
```

Expected: PASS.

- [ ] **Step 5: Verify both directions in a browser**

```bash
npm run dev -- --port 5199
```

Open the seeded project's spreadsheet at `http://localhost:5199/#/projects/seed-project/spreadsheet`, click a row, switch to Blueprint takeoff, and confirm the same item is selected and its sheet is showing. Then select a different marker on the canvas, switch back to the spreadsheet, and confirm that row is highlighted and scrolled into view. Report what you saw.

- [ ] **Step 6: Commit**

```bash
git add src/components/takeoff/
git commit -m "Synchronise spreadsheet row selection with the blueprint"
```

---

### Task 5: Multi-row selection and bulk approve

**Files:**
- Create: `src/components/takeoff/BulkApproveBar.jsx`
- Modify: `src/components/takeoff/TakeoffSpreadsheet.jsx`
- Modify: `src/styles.css`
- Test: `src/components/takeoff/TakeoffSpreadsheet.bulk.test.jsx`

**Interfaces:**
- Consumes: `bulkApprove(itemIds)` from the layout context (Task 2), `approvableInBulk(items)` from `src/lib/rules.js`.
- Produces: `<BulkApproveBar checkedItems={Item[]} onApprove={fn} onClear={fn} result={BulkResult|null} />` where `BulkResult` is `{ approved: string[], skipped: { itemId, code, message }[] }`.

- [ ] **Step 1: Write the failing test**

```jsx
// src/components/takeoff/TakeoffSpreadsheet.bulk.test.jsx
/* CLAUDE.md names bulk approval as easy to break by accident: it applies
   only to Ready to review items, never to Needs attention or Missing
   information, "no matter how convenient it looks." These tests are the
   client-side guard. The server enforces the same rule independently. */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import TakeoffSpreadsheet from "./TakeoffSpreadsheet.jsx";

const items = [
  { id: "i1", sheetId: "s1", name: "Receptacle A", description: "", system: "Power", quantity: 1, unit: "ea", status: "ready", notes: "", rejected: false, warnings: [], version: 1 },
  { id: "i2", sheetId: "s1", name: "Receptacle B", description: "", system: "Power", quantity: 1, unit: "ea", status: "ready", notes: "", rejected: false, warnings: [], version: 1 },
  { id: "i3", sheetId: "s1", name: "High bay", description: "", system: "Lighting", quantity: 1, unit: "ea", status: "attention", notes: "", rejected: false, warnings: [], version: 1 },
  { id: "i4", sheetId: "s1", name: "Conduit run", description: "", system: "Power", quantity: 1, unit: "ft", status: "missing", notes: "", rejected: false, warnings: [], version: 1 },
];

const context = {
  snapshot: {
    sheets: [{ id: "s1", number: "E1.1", title: "Level 1 power", superseded: false }],
    items,
    totals: { bySystem: {}, approvedCount: 0, remainingCount: 4, attentionCount: 1, missingCount: 1, approvedUnits: 0 },
    undo: { canUndo: false, canRedo: false, label: null, undoBy: null },
    presence: [],
  },
  loading: false,
  loadError: null,
  selectedItemId: null,
  selectItem: vi.fn(),
  sheetId: "s1",
  setSheetId: vi.fn(),
  bulkApprove: vi.fn().mockResolvedValue({ approved: ["i1", "i2"], skipped: [], snapshot: null }),
  projectId: "p1",
};

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

const renderSheet = () =>
  render(
    <MemoryRouter>
      <TakeoffSpreadsheet />
    </MemoryRouter>,
  );

const checkboxFor = (name) => screen.getByRole("checkbox", { name: new RegExp(`select ${name}`, "i") });

beforeEach(() => {
  context.bulkApprove.mockClear();
});

describe("bulk approve", () => {
  it("offers no approve action until rows are checked", () => {
    renderSheet();
    expect(screen.queryByRole("button", { name: /approve \d+/i })).toBeNull();
  });

  it("approves only the Ready to review rows among those checked", async () => {
    renderSheet();
    await userEvent.click(checkboxFor("Receptacle A"));
    await userEvent.click(checkboxFor("High bay"));
    await userEvent.click(checkboxFor("Conduit run"));

    await userEvent.click(screen.getByRole("button", { name: /approve 1 item/i }));

    expect(context.bulkApprove).toHaveBeenCalledTimes(1);
    expect(context.bulkApprove.mock.calls[0][0]).toEqual(["i1"]);
  });

  it("says plainly why the others were left out", async () => {
    // "Nothing happened" is the answer that sends an estimator hunting.
    renderSheet();
    await userEvent.click(checkboxFor("High bay"));
    await userEvent.click(checkboxFor("Conduit run"));

    expect(screen.getByText(/2 of the 2 selected can't be approved/i)).toBeTruthy();
    expect(screen.getByText(/needs attention/i)).toBeTruthy();
    expect(screen.getByText(/missing information/i)).toBeTruthy();
  });

  it("disables the approve action when nothing checked can be approved", async () => {
    renderSheet();
    await userEvent.click(checkboxFor("Conduit run"));
    expect(screen.queryByRole("button", { name: /^approve/i })).toBeNull();
  });

  it("select-all checks only what is currently visible", async () => {
    // Filtering to Needs attention and hitting select-all must not
    // quietly include the rows the filter is hiding.
    renderSheet();
    await userEvent.click(screen.getByRole("button", { name: /needs attention/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /select all visible/i }));

    expect(screen.getByText(/1 of the 1 selected can't be approved/i)).toBeTruthy();
  });

  it("clears the selection after a successful approval", async () => {
    renderSheet();
    await userEvent.click(checkboxFor("Receptacle A"));
    await userEvent.click(checkboxFor("Receptacle B"));
    await userEvent.click(screen.getByRole("button", { name: /approve 2 items/i }));

    expect(await screen.findByText(/approved 2 items/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^approve \d/i })).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- TakeoffSpreadsheet.bulk`
Expected: FAIL — no checkboxes exist yet.

- [ ] **Step 3: Write the bulk bar**

```jsx
// src/components/takeoff/BulkApproveBar.jsx
/* ============================================================
   BulkApproveBar.jsx — what a multi-row selection can do.

   Bulk approval applies only to Ready to review items. CLAUDE.md names
   this as one of the rules easy to break by accident, so the count on
   the button is the *approvable* count rather than the checked count --
   a button reading "Approve 40 items" that approves 34 is the interface
   telling the estimator something untrue about their own bid.

   The rest are listed with a reason rather than silently ignored. An
   estimator who checks forty rows and sees thirty-four approve needs to
   know why the other six did not; "nothing happened" is the answer that
   sends them hunting through the table by hand.
   ============================================================ */

import { AlertCircle, AlertTriangle } from "lucide-react";
import { approvableInBulk } from "../../lib/rules.js";
import { STATUS } from "../../lib/data.js";

export default function BulkApproveBar({ checkedItems, onApprove, onClear, result }) {
  if (checkedItems.length === 0 && !result) return null;

  const approvable = approvableInBulk(checkedItems);
  const blocked = checkedItems.filter((item) => !approvable.some((a) => a.id === item.id));

  const byStatus = blocked.reduce((acc, item) => {
    acc[item.status] = (acc[item.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="bulk-bar" role="region" aria-label="Selected items">
      {result ? (
        <p className="bulk-bar-result" role="status">
          Approved {result.approved.length} {result.approved.length === 1 ? "item" : "items"}.
        </p>
      ) : null}

      {checkedItems.length > 0 ? (
        <>
          <span className="tabular">
            {checkedItems.length} selected
          </span>

          {approvable.length > 0 ? (
            <button type="button" className="btn btn--primary" onClick={() => onApprove(approvable.map((i) => i.id))}>
              Approve {approvable.length} {approvable.length === 1 ? "item" : "items"}
            </button>
          ) : null}

          {blocked.length > 0 ? (
            <span className="bulk-bar-blocked">
              <span className="tabular">{blocked.length}</span> of the{" "}
              <span className="tabular">{checkedItems.length}</span> selected can&rsquo;t be approved here:
              {Object.entries(byStatus).map(([status, count]) => (
                <span key={status} className={`bulk-bar-reason bulk-bar-reason--${status}`}>
                  {status === "missing" ? (
                    <AlertCircle size={13} aria-hidden="true" />
                  ) : (
                    <AlertTriangle size={13} aria-hidden="true" />
                  )}
                  <span className="tabular">{count}</span> {STATUS[status]?.label ?? status}
                </span>
              ))}
            </span>
          ) : null}

          <button type="button" className="btn" onClick={onClear}>
            Clear selection
          </button>
        </>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Wire checkboxes into the table**

Add a leading `<th scope="col">` whose content is a checkbox labelled `Select all visible`, checked when every visible row is checked, and a leading `<td>` per row with a checkbox labelled `Select {item.name}`.

Hold the checked set in `useState(() => new Set())`. **Select-all must operate on the currently visible rows only**, not on `snapshot.items` — filtering to *Needs attention* and hitting select-all must not silently include hidden rows.

Call `bulkApprove(ids)` on approve, store the returned result in state for the bar to render, and clear the checked set afterwards. Stop the row's `onClick` from firing when the click lands on a checkbox — `event.stopPropagation()` in the checkbox's own handler — or checking a box would also change the shared selection.

- [ ] **Step 5: Add the styles**

```css
/* ---- Bulk selection bar ---- */
.bulk-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px 10px;
  margin-bottom: 10px;
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  background: var(--paper-1);
  font-size: 13px;
}
.bulk-bar-blocked { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 8px; color: var(--ink-2); }
.bulk-bar-reason { display: inline-flex; align-items: center; gap: 4px; }
.bulk-bar-reason--attention { color: var(--amber); }
.bulk-bar-reason--missing { color: var(--red); }
.bulk-bar-result { margin: 0; }
```

- [ ] **Step 6: Run the tests and build**

```bash
npm test
npm run build
```

Expected: all pass.

- [ ] **Step 7: Verify the rule holds against the real store**

```bash
npm run dev -- --port 5199
```

On the seeded project's spreadsheet, check every row including the *Needs attention* and *Missing information* ones, and confirm: the button names only the approvable count, the rest are listed with reasons, approving moves only those rows to *Estimator approved*, the drawer totals update, and a single undo reverses the whole batch. Report what you saw.

- [ ] **Step 8: Commit**

```bash
git add src/components/takeoff/ src/styles.css
git commit -m "Add multi-row selection and bulk approve restricted to Ready to review"
```

---

## Self-review

**Spec coverage.** §10.1 columns → Task 3, with four deliberately absent and one deferred, reasoned in Data Reality. §10.2 search/sort/filter → Task 3; column visibility → Task 3; multi-row selection → Task 5; undo/redo → Task 2 (compound action). §10 "two views of the same records" and `DESIGN.md` bidirectional selection → Tasks 1 and 4. Bulk approval restricted to *Ready to review* → Tasks 2 and 5, enforced on both sides.

**Deliberately out of scope, per `BUILD-STAGES.md`'s "lean screen G":** grouping, column resize/freeze/reorder, copy/paste and fill-down, permitted formulas, change history, saved custom views, Excel export (its own slice), and §10.3's takeoff-completion summary (belongs with final review). §10.2's "source-controlled fields require an explicit correction action" and "manual overrides require a reason and retain the calculated value" are also deferred — there is no calculated-versus-manual distinction in the item model yet, so there is nothing to retain.

**Type consistency.** `selectItem(itemId)` and `selectedItemId` are used identically in Tasks 1, 3, 4, and 5. `bulkApprove(itemIds)` returns `{ approved, skipped, snapshot }` with `skipped[].itemId` camelCase in every task that touches it. `COLUMNS[].render(item, { sheetsById })` has the same signature in its definition and its consumers.

**Two risks worth stating plainly.**

**Task 1 is the dangerous one.** It moves state out of a screen that works today, and the two existing Workspace tests are the only automated guard. Those tests must pass *unmodified* — if either needs editing, behaviour changed and the task should stop rather than adjust the test. The browser check in Step 9 is not optional; the last time this workspace was refactored, the defect that reached review was invisible to both the suite and the build.

**The seed store's bulk approve introduces a new action kind.** `seed-undo.js` handles `approve`, `reject`, `unreject`, `edit`, `delete`, and `scale`. A `bulk-approve` action it does not recognise would fall through every branch, write the unchanged item list back, and report success — an undo that silently does nothing. Task 2 Step 3 adds the branch and Step 4 tests it; do not skip either.
