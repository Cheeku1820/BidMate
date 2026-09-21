# Spreadsheet grid implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Date: 2026-09-21. Spec: [`docs/specs/spreadsheet-grid.md`](../specs/spreadsheet-grid.md). Stream B of `docs/roadmap/workstreams-2026-09.md`.

**Goal:** Make the Labor and Material pricing grids behave like Google Sheets — arrow to any cell, Shift-select a range, copy/paste a block as TSV, fill down, Delete a range, sort by header, resize columns — with every write landing as one existing store call per cell (per row on Material) so undo works per action, and the toast's Undo reversing the whole operation.

**Architecture:** Extend the existing `DataGrid.jsx` (a semantic `<table role="grid">`) rather than adopt a library. A new pure-function module `useGridSelection.js` holds every range rule (normalize, extend, TSV in and out, paste/fill/clear mapping, sort) so it is tested on plain data like `useGridNavigation.js` already is. `DataGrid` gains an anchor for the selection, clipboard/fill/sort/resize handlers, and one new callback `onCommitRange(changes, { kind })`; the two workspaces implement it over the store calls they already make and share two small helpers for the range toast and the N-fold undo.

**Tech Stack:** React 18 function components, vitest + @testing-library/react (jsdom), plain CSS tokens, `lucide-react` icons. No new dependency.

## Global constraints

- No new npm dependency.
- Files this stream may touch: `src/components/grid/**`, `src/components/labor/**`, `src/components/pricing/laborColumns.jsx`, `src/components/pricing/pricingColumns.jsx`, `src/components/pricing/MaterialPricingWorkspace.jsx` and its test, `docs/specs/spreadsheet-grid.md`, `docs/specs/pricing-grid.md`, `docs/plans/spreadsheet-grid.md`. `src/styles.css` only by appending at the very end under `/* ==== stream B: grid ==== */`. Never `src/components/pricing/PriceSheetImport.jsx`, never `api/`, never `CLAUDE.md` / `README.md` / `docs/README.md`.
- Every write goes through `store.setLaborLine`, `store.setMaterialPrice`, or `store.clearMaterialPrice`, one call per cell (Labor) or per row (Material), each through `runMutation`. No bulk endpoint.
- The four review labels only; status is never colour alone; the tier tag is a separate element from the status pill; `className="tabular"` on numbers; sentence case; no exclamation marks; no "successfully"; no "please".
- Selection is drawn in blue (`--blue`) only — never a status colour, never a fill on the focus cell.
- The regression test "Tab from inside the market evidence details is not hijacked back onto the grid" in `MaterialPricingWorkspace.test.jsx` must stay green and unchanged.
- Never `git stash`; never `git add -A`; add files by name. Commit message: one plain sentence, blank line, `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Run tests with `npm test -- --run <path>`; the whole suite with `npm test -- --run`; build with `npm run build`.

## File map

| File | Responsibility |
|---|---|
| `src/components/grid/useGridNavigation.js` | the active cell; `moveActive`: arrows/Home/End over every cell, `next`/`prev` over editable cells (modify) |
| `src/components/grid/useGridSelection.js` | NEW pure functions: `normalize`, `extend`, `selectAll`, `cellText`, `toTsv`, `parseClipboard`, `coerce`, `pasteChanges`, `fillChanges`, `clearChanges`, `sortRows` |
| `src/components/grid/rangeCopy.js` | NEW: `rangeToast(kind, cells, rows, { skipped })`, `rangeFailure(failed, total)`, `reversedToast(cells)` |
| `src/components/grid/useUndoCount.js` | NEW hook: remembers how many `undo()` calls the last toast stands for and reverses them |
| `src/components/grid/DataGrid.jsx` | the component: selection anchor, clipboard, fill handle, Delete over a range, Ctrl+D, Ctrl+Z, sort headers, resize (modify) |
| `src/components/labor/laborColumns.jsx` | `text` and `sortValue` on read-only columns (modify) |
| `src/components/labor/LaborWorkspace.jsx` | `onCommitRange`: one PATCH per cell, sequential; range toast; N-fold undo; `onUndo`/`onRedo` (modify) |
| `src/components/pricing/pricingColumns.jsx` | `text` and `sortValue` (modify) |
| `src/components/pricing/MaterialPricingWorkspace.jsx` | `onCommitRange`: one call per row, allowance rows skipped (modify) |
| `src/styles.css` | appended block (modify, append only) |
| Tests | `useGridNavigation.test.js`, `useGridSelection.test.js` (new), `rangeCopy.test.js` (new), `useUndoCount.test.jsx` (new), `DataGrid.test.jsx`, `LaborWorkspace.test.jsx`, `MaterialPricingWorkspace.test.jsx` |

Selection objects use the same cell shape `useGridNavigation` already uses — `{ row: <displayed row index>, col: <column key> }` — for both `anchor` and `focus`. `normalize()` converts to column indices. (The spec says "col an index"; this plan keeps keys at the edges and indices inside `normalize`, which is the same rectangle.)

---

### Task 1: Arrows visit every cell; Tab stays the entry flow

**Files:**
- Modify: `src/components/grid/useGridNavigation.js`
- Test: `src/components/grid/useGridNavigation.test.js`

**Interfaces:**
- Produces: `moveActive(active, direction, columns, rows)` with `direction` ∈ `"left" | "right" | "up" | "down" | "home" | "end"` moving over **every** column and never returning `null`; `"next" | "prev"` unchanged (editable only, `null` past the ends). `isEditable`, `firstEditable`, `useGridNavigation` unchanged.

- [ ] **Step 1: Replace the arrow/Home/End tests**

In `src/components/grid/useGridNavigation.test.js`, replace the three tests `"left and right step within the row…"`, `"up and down stay in the column…"`, and `"home and end go to the row's first and last editable cell"` with:

```js
  test("left and right step one column, read-only and disabled cells included, and stop at the edges", () => {
    expect(moveActive({ row: 0, col: "name" }, "right", columns, rows)).toEqual({ row: 0, col: "qty" });
    expect(moveActive({ row: 0, col: "qty" }, "right", columns, rows)).toEqual({ row: 0, col: "hours" });
    expect(moveActive({ row: 0, col: "basis" }, "right", columns, rows)).toEqual({ row: 0, col: "basis" });
    expect(moveActive({ row: 0, col: "name" }, "left", columns, rows)).toEqual({ row: 0, col: "name" });
    // Row 2's basis is disabled for editing, but an arrow still lands on it.
    expect(moveActive({ row: 1, col: "note" }, "right", columns, rows)).toEqual({ row: 1, col: "basis" });
  });

  test("up and down stay in the column, one row at a time, whatever the cell is", () => {
    expect(moveActive({ row: 0, col: "hours" }, "down", columns, rows)).toEqual({ row: 1, col: "hours" });
    expect(moveActive({ row: 0, col: "basis" }, "down", columns, rows)).toEqual({ row: 1, col: "basis" });
    expect(moveActive({ row: 2, col: "qty" }, "up", columns, rows)).toEqual({ row: 1, col: "qty" });
    expect(moveActive({ row: 0, col: "hours" }, "up", columns, rows)).toEqual({ row: 0, col: "hours" });
    expect(moveActive({ row: 2, col: "hours" }, "down", columns, rows)).toEqual({ row: 2, col: "hours" });
  });

  test("home and end go to the row's first and last cell of any kind", () => {
    expect(moveActive({ row: 1, col: "note" }, "home", columns, rows)).toEqual({ row: 1, col: "name" });
    expect(moveActive({ row: 1, col: "hours" }, "end", columns, rows)).toEqual({ row: 1, col: "basis" });
  });

  test("next and prev from a read-only cell go to the nearest editable cell in that direction", () => {
    expect(moveActive({ row: 0, col: "name" }, "next", columns, rows)).toEqual({ row: 0, col: "hours" });
    expect(moveActive({ row: 1, col: "qty" }, "prev", columns, rows)).toEqual({ row: 0, col: "basis" });
  });
```

Keep the `next`/`prev` wrap test and the null test as they are.

- [ ] **Step 2: Run to see the new tests fail**

Run: `npm test -- --run src/components/grid/useGridNavigation.test.js`
Expected: FAIL — the four rewritten tests (e.g. `right` from `name` returns `{ row: 0, col: "name" }`).

- [ ] **Step 3: Rewrite `moveActive`**

Replace the `moveActive` function in `src/components/grid/useGridNavigation.js` with:

```js
/** The active cell after moving in `direction`.
 *
 *  Arrows, Home and End move over every cell -- read-only, disabled,
 *  or editable -- one step, clamped at the grid's edges, the way a
 *  spreadsheet does. `next`/`prev` (Tab) are the entry flow: they walk
 *  editable cells only, wrap between rows, and return null past the
 *  grid's last/first editable cell -- the one case focus should leave
 *  the grid, which is what an un-prevented Tab does. */
export function moveActive(active, direction, columns, rows) {
  if (!active) return null;
  const all = columns.map((c) => c.key);
  const ci = all.indexOf(active.col);
  switch (direction) {
    case "left":
      return ci > 0 ? { row: active.row, col: all[ci - 1] } : active;
    case "right":
      return ci < all.length - 1 ? { row: active.row, col: all[ci + 1] } : active;
    case "home":
      return { row: active.row, col: all[0] };
    case "end":
      return { row: active.row, col: all[all.length - 1] };
    case "up":
      return active.row > 0 ? { row: active.row - 1, col: active.col } : active;
    case "down":
      return active.row < rows.length - 1 ? { row: active.row + 1, col: active.col } : active;
    case "next": {
      // The next editable cell strictly after this one in reading order.
      const keys = editableKeys(columns, rows[active.row]);
      const after = keys.find((k) => all.indexOf(k) > ci);
      if (after) return { row: active.row, col: after };
      for (let r = active.row + 1; r < rows.length; r += 1) {
        const k = editableKeys(columns, rows[r]);
        if (k.length) return { row: r, col: k[0] };
      }
      return null;
    }
    case "prev": {
      const keys = editableKeys(columns, rows[active.row]);
      const before = [...keys].reverse().find((k) => all.indexOf(k) < ci);
      if (before) return { row: active.row, col: before };
      for (let r = active.row - 1; r >= 0; r -= 1) {
        const k = editableKeys(columns, rows[r]);
        if (k.length) return { row: r, col: k[k.length - 1] };
      }
      return null;
    }
    default:
      return active;
  }
}
```

Update the file's header comment: replace the sentence beginning "Only editable cells participate" through "rather than stopping on Status and Quantity." with:

```
   Arrows, Home and End visit every cell, as in a spreadsheet. Only Tab
   (`next`/`prev`) is the entry flow: it walks editable cells only, so
   on the labor screen it goes hours → rate → adjustment → reason → the
   next row's hours rather than stopping on Status and Quantity.
```

- [ ] **Step 4: Run the navigation tests**

Run: `npm test -- --run src/components/grid/useGridNavigation.test.js`
Expected: PASS (all).

- [ ] **Step 5: Run the grid test to see which arrow tests now break, and fix them**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: FAIL in `"arrow keys move over editable cells only and focus follows"` and `"Home from the last editable cell lands on the first"` (the cells now land on read-only/disabled cells).

In `src/components/grid/DataGrid.test.jsx` replace those two tests with:

```js
  test("arrow keys move one cell in any direction, read-only cells included, and focus follows", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowRight" });
    expect(cell(0, NOTE)).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(cell(0, NOTE));
    fireEvent.keyDown(cell(0, NOTE), { key: "ArrowDown" });
    expect(cell(1, NOTE)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(1, NOTE), { key: "ArrowRight" }); // row 2's basis is disabled, still reachable
    expect(cell(1, BASIS)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(1, BASIS), { key: "ArrowLeft" });
    fireEvent.keyDown(cell(1, NOTE), { key: "ArrowLeft" });
    fireEvent.keyDown(cell(1, HOURS), { key: "ArrowLeft" });
    expect(cell(1, 0)).toHaveAttribute("aria-selected", "true"); // the read-only Quantity cell
    expect(document.activeElement).toBe(cell(1, 0));
  });

  test("Home and End reach the row's first and last cell; Tab from a read-only cell goes to the next editable one", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "End" });
    expect(cell(0, BASIS)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(0, BASIS), { key: "Home" });
    const header = screen.getAllByRole("rowheader")[0];
    expect(header).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(header);
    fireEvent.keyDown(header, { key: "Tab" });
    expect(cell(0, HOURS)).toHaveAttribute("aria-selected", "true");
  });

  test("Enter, a printable key, and Delete do nothing on a read-only cell", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowLeft" }); // onto Quantity
    expect(cell(0, 0)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(0, 0), { key: "Enter" });
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.keyDown(cell(0, 0), { key: "5" });
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.keyDown(cell(0, 0), { key: "Delete" });
    expect(onCommit).not.toHaveBeenCalled();
  });
```

These pass without further changes because `onCellKeyDown` already returns after the moves when `!isEditable(column, row)`. Note the rowheader cell (`Item`) is `role="rowheader"`, so `cell()` (which counts gridcells) does not index it; the test reaches it by role.

- [ ] **Step 6: Run the grid tests**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/components/grid/useGridNavigation.js src/components/grid/useGridNavigation.test.js src/components/grid/DataGrid.test.jsx
git commit -m "Grid: arrows, Home and End visit every cell; Tab stays the editable-only entry flow

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The selection module — ranges, TSV, paste/fill/clear mapping

**Files:**
- Create: `src/components/grid/useGridSelection.js`
- Test: `src/components/grid/useGridSelection.test.js`

**Interfaces:**
- Consumes: `isEditable(column, row)` from `./useGridNavigation.js`.
- Produces (all pure, exported):
  - `normalize({ anchor, focus }, columns)` → `{ r0, c0, r1, c1 }` (row indices, column indices, inclusive)
  - `extend(selection, direction, columns, rows)` → a new selection with the focus moved one cell (`"left" | "right" | "up" | "down"`), clamped; anchor unchanged
  - `selectAll(columns, rows)` → `{ anchor: { row: 0, col: first key }, focus: { row: last, col: last key } }`; `null` when no rows
  - `cellText(column, row)` → string
  - `toTsv(range, columns, rows)` → string
  - `parseClipboard(text)` → `string[][]`
  - `coerce(column, row, text)` → `{ skip: true }` or `{ value }`
  - `pasteChanges(clip, range, columns, rows)` → `[{ row, key, value }]`
  - `fillChanges(range, columns, rows, { to })` → same; `to` optional
  - `clearChanges(range, columns, rows)` → same

- [ ] **Step 1: Write the failing tests**

Create `src/components/grid/useGridSelection.test.js`:

```js
/* ============================================================
   useGridSelection.test.js — the range rules, on plain data
   (docs/specs/spreadsheet-grid.md, "Selection" and "Range
   operations"). Columns: name (row header, read-only, text()),
   qty (read-only), price (number, min 0), basis (select, disabled
   when locked), note (text). Cells are { row index, col key }.
   ============================================================ */

import { describe, expect, test } from "vitest";
import {
  cellText, clearChanges, coerce, extend, fillChanges, normalize, parseClipboard, pasteChanges, selectAll, toTsv,
} from "./useGridSelection.js";

const columns = [
  { key: "name", label: "Item", header: true, render: (r) => r.name, text: (r) => r.name },
  { key: "qty", label: "Quantity", render: (r) => r.qty },
  {
    key: "price", label: "Price", render: (r) => r.price,
    edit: { kind: "number", min: 0, value: (r) => r.price, hasEntry: (r) => r.entered },
  },
  {
    key: "basis", label: "Basis", render: (r) => r.basis,
    edit: {
      kind: "select", value: (r) => r.basis, disabled: (r) => r.locked,
      options: [{ value: "project_price", label: "Project price" }, { value: "allowance", label: "Allowance" }],
    },
  },
  { key: "note", label: "Note", render: (r) => r.note, edit: { kind: "text", value: (r) => r.note, hasEntry: (r) => Boolean(r.note) } },
  { key: "evidence", label: "Evidence", render: (r) => r.evidence },
];
const rows = [
  { name: "One", qty: 1, price: 12.5, entered: true, basis: "project_price", note: "", evidence: { x: 1 } },
  { name: "Two", qty: 2, price: null, entered: false, basis: null, locked: true, note: "keep", evidence: null },
  { name: "Three", qty: 3, price: 7, entered: true, basis: "allowance", note: "", evidence: null },
];
const sel = (r0, c0, r1, c1) => ({ anchor: { row: r0, col: c0 }, focus: { row: r1, col: c1 } });

describe("normalize", () => {
  test("orders any anchor/focus pair into an inclusive rectangle of indices", () => {
    expect(normalize(sel(2, "note", 0, "qty"), columns)).toEqual({ r0: 0, c0: 1, r1: 2, c1: 4 });
    expect(normalize(sel(1, "price", 1, "price"), columns)).toEqual({ r0: 1, c0: 2, r1: 1, c1: 2 });
  });
});

describe("extend", () => {
  test("moves the focus one cell over every column and keeps the anchor", () => {
    expect(extend(sel(0, "price", 0, "price"), "left", columns, rows)).toEqual(sel(0, "price", 0, "qty"));
    expect(extend(sel(0, "price", 0, "qty"), "left", columns, rows)).toEqual(sel(0, "price", 0, "name"));
    expect(extend(sel(0, "price", 0, "price"), "down", columns, rows)).toEqual(sel(0, "price", 1, "price"));
  });
  test("clamps at the edges", () => {
    expect(extend(sel(0, "name", 0, "name"), "left", columns, rows)).toEqual(sel(0, "name", 0, "name"));
    expect(extend(sel(0, "name", 0, "name"), "up", columns, rows)).toEqual(sel(0, "name", 0, "name"));
    expect(extend(sel(0, "note", 2, "evidence"), "right", columns, rows)).toEqual(sel(0, "note", 2, "evidence"));
    expect(extend(sel(0, "note", 2, "evidence"), "down", columns, rows)).toEqual(sel(0, "note", 2, "evidence"));
  });
});

describe("selectAll", () => {
  test("covers the grid, and is null with no rows", () => {
    expect(selectAll(columns, rows)).toEqual(sel(0, "name", 2, "evidence"));
    expect(selectAll(columns, [])).toBeNull();
  });
});

describe("cellText and toTsv", () => {
  test("copies raw editable values, text() for read-only columns, primitives, and nothing for objects", () => {
    expect(cellText(columns[0], rows[0])).toBe("One");
    expect(cellText(columns[1], rows[0])).toBe("1");
    expect(cellText(columns[2], rows[0])).toBe("12.5");
    expect(cellText(columns[2], rows[1])).toBe("");
    expect(cellText(columns[3], rows[2])).toBe("allowance");
    expect(cellText(columns[5], rows[0])).toBe("");
  });
  test("is tab-separated, one line per row, no trailing newline", () => {
    expect(toTsv({ r0: 0, c0: 0, r1: 1, c1: 2 }, columns, rows)).toBe("One\t1\t12.5\nTwo\t2\t");
  });
});

describe("parseClipboard", () => {
  test("splits lines and tabs, tolerates \\r\\n and a trailing newline, keeps empty cells", () => {
    expect(parseClipboard("a\tb\r\nc\t\r\n")).toEqual([["a", "b"], ["c", ""]]);
    expect(parseClipboard("42")).toEqual([["42"]]);
    expect(parseClipboard("x\n\ny")).toEqual([["x"], [""], ["y"]]);
  });
});

describe("coerce", () => {
  const price = columns[2], basis = columns[3], note = columns[4], qty = columns[1];
  test("skips read-only and disabled cells", () => {
    expect(coerce(qty, rows[0], "5")).toEqual({ skip: true });
    expect(coerce(basis, rows[1], "allowance")).toEqual({ skip: true });
  });
  test("parses numbers leniently and applies min", () => {
    expect(coerce(price, rows[1], "$1,234.50")).toEqual({ value: 1234.5 });
    expect(coerce(price, rows[1], " 62 ")).toEqual({ value: 62 });
    expect(coerce(price, rows[1], "+25%")).toEqual({ value: 25 });
    expect(coerce(price, rows[1], "−3")).toEqual({ skip: true }); // below min 0, unicode minus
    expect(coerce(price, rows[1], "abc")).toEqual({ skip: true });
  });
  test("empty clears only a cell with an entry", () => {
    expect(coerce(price, rows[0], "")).toEqual({ value: null });
    expect(coerce(price, rows[1], "   ")).toEqual({ skip: true });
    expect(coerce(note, rows[1], "")).toEqual({ value: null });
    expect(coerce(note, rows[0], "")).toEqual({ skip: true });
  });
  test("matches a select by value or label, case-insensitively", () => {
    expect(coerce(basis, rows[0], "Allowance")).toEqual({ value: "allowance" });
    expect(coerce(basis, rows[0], "ALLOWANCE")).toEqual({ value: "allowance" });
    expect(coerce(basis, rows[0], "project price")).toEqual({ skip: true }); // unchanged
    expect(coerce(basis, rows[0], "other")).toEqual({ skip: true });
  });
  test("skips an unchanged value", () => {
    expect(coerce(price, rows[0], "12.50")).toEqual({ skip: true });
    expect(coerce(note, rows[1], "keep")).toEqual({ skip: true });
    expect(coerce(note, rows[1], " new ")).toEqual({ value: "new" });
  });
});

describe("pasteChanges", () => {
  test("a 1×1 clip fills the whole range", () => {
    const changes = pasteChanges([["9"]], { r0: 0, c0: 2, r1: 2, c1: 2 }, columns, rows);
    expect(changes).toEqual([
      { row: rows[0], key: "price", value: 9 },
      { row: rows[1], key: "price", value: 9 },
      { row: rows[2], key: "price", value: 9 },
    ]);
  });
  test("a block anchors at the top-left, clamps, skips read-only targets, and is row-major", () => {
    const clip = [["1", "5", "Allowance"], ["2", "6", "Allowance"], ["3", "7", "Allowance"], ["4", "8", "Allowance"]];
    const changes = pasteChanges(clip, { r0: 1, c0: 1, r1: 1, c1: 1 }, columns, rows); // top-left on Quantity
    // Columns from Quantity: qty (read-only, skipped), price, basis. Row 1's
    // basis is locked; row 2's is already "allowance"; the clip's fourth
    // line falls off the grid.
    expect(changes).toEqual([
      { row: rows[1], key: "price", value: 5 },
      { row: rows[2], key: "price", value: 7 },
    ]);
  });
  test("an empty pasted cell clears an entry and nothing is emitted when nothing applies", () => {
    expect(pasteChanges([[""]], { r0: 0, c0: 2, r1: 0, c1: 2 }, columns, rows)).toEqual([{ row: rows[0], key: "price", value: null }]);
    expect(pasteChanges([["zzz"]], { r0: 0, c0: 1, r1: 0, c1: 1 }, columns, rows)).toEqual([]);
  });
});

Then, in the same file, the fill and clear tests:

```js
describe("fillChanges", () => {
  test("Ctrl+D: the top row repeats down the range, unchanged and read-only cells skipped", () => {
    const changes = fillChanges({ r0: 0, c0: 1, r1: 2, c1: 2 }, columns, rows);
    expect(changes).toEqual([
      { row: rows[1], key: "price", value: 12.5 },
      { row: rows[2], key: "price", value: 12.5 },
    ]);
  });
  test("a drag target repeats the source rows in order past the range", () => {
    // Source rows 0–1 (prices 12.5 and null), dragged to row 2.
    const changes = fillChanges({ r0: 0, c0: 2, r1: 1, c1: 2 }, columns, rows, { to: 2 });
    expect(changes).toEqual([{ row: rows[2], key: "price", value: 12.5 }]);
    // Source row 1 alone (null price) onto rows 2: clears the entry there.
    expect(fillChanges({ r0: 1, c0: 2, r1: 1, c1: 2 }, columns, rows, { to: 2 })).toEqual([{ row: rows[2], key: "price", value: null }]);
  });
  test("a single-row range with no drag target fills nothing", () => {
    expect(fillChanges({ r0: 0, c0: 2, r1: 0, c1: 2 }, columns, rows)).toEqual([]);
  });
});

describe("clearChanges", () => {
  test("nulls every cell with an entry and nothing else", () => {
    expect(clearChanges({ r0: 0, c0: 0, r1: 2, c1: 5 }, columns, rows)).toEqual([
      { row: rows[0], key: "price", value: null },
      { row: rows[1], key: "note", value: null },
      { row: rows[2], key: "price", value: null },
    ]);
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/grid/useGridSelection.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the module**

Create `src/components/grid/useGridSelection.js`:

```js
/* ============================================================
   useGridSelection.js — the range rules of a DataGrid
   (docs/specs/spreadsheet-grid.md, "Selection" and "Range
   operations"). Pure functions over (columns, rows) and plain
   selection objects, tested on plain data; nothing here touches
   the DOM.

   A selection is { anchor, focus }, each { row: index, col: key } --
   the same cell shape useGridNavigation uses for the active cell,
   which is always the focus. normalize() turns it into an inclusive
   rectangle of indices. Every range operation reads that rectangle
   and produces a list of changes, [{ row, key, value }] in row-major
   order, that the grid hands to the screen; a cell that cannot take
   the value (read-only, invalid, unchanged) is skipped, never an
   error, so one bad cell never blocks its neighbours.
   ============================================================ */

import { isEditable } from "./useGridNavigation.js";

const colIndex = (columns, key) => columns.findIndex((c) => c.key === key);

export function normalize({ anchor, focus }, columns) {
  const ca = colIndex(columns, anchor.col);
  const cf = colIndex(columns, focus.col);
  return {
    r0: Math.min(anchor.row, focus.row),
    r1: Math.max(anchor.row, focus.row),
    c0: Math.min(ca, cf),
    c1: Math.max(ca, cf),
  };
}

/** The selection with its focus moved one cell, over every column,
 *  clamped to the grid. The anchor stays where it is. */
export function extend(selection, direction, columns, rows) {
  const { focus } = selection;
  const ci = colIndex(columns, focus.col);
  let next = focus;
  if (direction === "left" && ci > 0) next = { row: focus.row, col: columns[ci - 1].key };
  if (direction === "right" && ci < columns.length - 1) next = { row: focus.row, col: columns[ci + 1].key };
  if (direction === "up" && focus.row > 0) next = { row: focus.row - 1, col: focus.col };
  if (direction === "down" && focus.row < rows.length - 1) next = { row: focus.row + 1, col: focus.col };
  return { anchor: selection.anchor, focus: next };
}

export function selectAll(columns, rows) {
  if (!rows.length || !columns.length) return null;
  return {
    anchor: { row: 0, col: columns[0].key },
    focus: { row: rows.length - 1, col: columns[columns.length - 1].key },
  };
}

/** What a cell copies: raw values for editable cells (62, not
 *  $62.00/hr), `text()` where the column supplies one, a primitive
 *  from the row otherwise, and nothing for anything richer. */
export function cellText(column, row) {
  if (column.text) return String(column.text(row) ?? "");
  if (column.edit) return String(column.edit.value(row) ?? "");
  const v = row[column.key];
  return typeof v === "string" || typeof v === "number" ? String(v) : "";
}

export function toTsv(range, columns, rows) {
  const lines = [];
  for (let r = range.r0; r <= range.r1; r += 1) {
    const cells = [];
    for (let c = range.c0; c <= range.c1; c += 1) cells.push(cellText(columns[c], rows[r]));
    lines.push(cells.join("\t"));
  }
  return lines.join("\n");
}

export function parseClipboard(text) {
  const lines = String(text ?? "").split("\n").map((l) => (l.endsWith("\r") ? l.slice(0, -1) : l));
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return lines.map((l) => l.split("\t"));
}

const SKIP = { skip: true };

/** Turns pasted text into a change for one cell, or a skip. The
 *  grid's own validation rules, applied leniently: currency and
 *  percent decoration is stripped from numbers, a select takes its
 *  option's value or label, an empty string clears an entry. */
export function coerce(column, row, text) {
  if (!isEditable(column, row)) return SKIP;
  const edit = column.edit;
  const t = String(text ?? "").trim();
  const current = edit.value(row);
  if (t === "") return edit.hasEntry && edit.hasEntry(row) ? { value: null } : SKIP;
  if (edit.kind === "number") {
    const cleaned = t.replace(/[$,%\s]/g, "").replace(/−/g, "-");
    const n = Number(cleaned);
    if (cleaned === "" || !Number.isFinite(n)) return SKIP;
    if (edit.min != null && n < edit.min) return SKIP;
    if (current != null && Number(current) === n) return SKIP;
    return { value: n };
  }
  if (edit.kind === "select") {
    const lower = t.toLowerCase();
    const opt = (edit.options || []).find((o) => String(o.value).toLowerCase() === lower || String(o.label).toLowerCase() === lower);
    if (!opt) return SKIP;
    if (String(current ?? "") === String(opt.value)) return SKIP;
    return { value: opt.value };
  }
  if (t === String(current ?? "")) return SKIP;
  return { value: t };
}

function push(changes, column, row, text) {
  const result = coerce(column, row, text);
  if (!result.skip) changes.push({ row, key: column.key, value: result.value });
}

/** Where a clip lands: a 1×1 clip fills the range; anything larger
 *  anchors at the range's top-left and extends by its own size,
 *  clamped to the grid. */
export function pasteChanges(clip, range, columns, rows) {
  const changes = [];
  if (!clip.length) return changes;
  const single = clip.length === 1 && clip[0].length === 1;
  if (single) {
    for (let r = range.r0; r <= range.r1; r += 1) {
      for (let c = range.c0; c <= range.c1; c += 1) push(changes, columns[c], rows[r], clip[0][0]);
    }
    return changes;
  }
  for (let i = 0; i < clip.length; i += 1) {
    const r = range.r0 + i;
    if (r >= rows.length) break;
    for (let j = 0; j < clip[i].length; j += 1) {
      const c = range.c0 + j;
      if (c >= columns.length) break;
      push(changes, columns[c], rows[r], clip[i][j]);
    }
  }
  return changes;
}

/** Fill down. Without `to`: the range's top row is the source and the
 *  rows below it in the range are the target (Ctrl+D). With `to`: the
 *  whole range is the source and the rows past it through `to` are the
 *  target (the fill handle), source rows repeating in order. */
export function fillChanges(range, columns, rows, { to } = {}) {
  const changes = [];
  const sourceEnd = to == null ? range.r0 : range.r1;
  const targetStart = to == null ? range.r0 + 1 : range.r1 + 1;
  const targetEnd = to == null ? range.r1 : Math.min(to, rows.length - 1);
  const sourceCount = sourceEnd - range.r0 + 1;
  for (let r = targetStart; r <= targetEnd; r += 1) {
    const src = rows[range.r0 + ((r - targetStart) % sourceCount)];
    for (let c = range.c0; c <= range.c1; c += 1) {
      const column = columns[c];
      if (!column.edit) continue;
      push(changes, column, rows[r], String(column.edit.value(src) ?? ""));
    }
  }
  return changes;
}

export function clearChanges(range, columns, rows) {
  const changes = [];
  for (let r = range.r0; r <= range.r1; r += 1) {
    for (let c = range.c0; c <= range.c1; c += 1) {
      const column = columns[c];
      const row = rows[r];
      if (isEditable(column, row) && column.edit.hasEntry && column.edit.hasEntry(row)) {
        changes.push({ row, key: column.key, value: null });
      }
    }
  }
  return changes;
}
```

- [ ] **Step 4: Run the tests**

Run: `npm test -- --run src/components/grid/useGridSelection.test.js`
Expected: PASS. If `"−3"` does not skip, check the Unicode minus replacement runs before `Number()`.

- [ ] **Step 5: Commit**

```bash
git add src/components/grid/useGridSelection.js src/components/grid/useGridSelection.test.js
git commit -m "Grid: the selection module — ranges, TSV in and out, and paste, fill, and clear mapping as pure functions

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `sortRows`

**Files:**
- Modify: `src/components/grid/useGridSelection.js`
- Test: `src/components/grid/useGridSelection.test.js`

**Interfaces:**
- Produces: `sortRows(rows, column, direction)` → a new array; `direction` ∈ `"ascending" | "descending"`; `column.sortValue(row)` wins, else `column.edit.value(row)`, else `row[column.key]`; `null`/`undefined`/`""` last in both directions; stable.

- [ ] **Step 1: Write the failing tests**

Append to `src/components/grid/useGridSelection.test.js` (add `sortRows` to the import):

```js
describe("sortRows", () => {
  test("sorts numbers numerically and strings by locale, nulls last both ways, stable on ties", () => {
    const price = columns[2], name = columns[0];
    const rs = [
      { name: "b", price: 10 }, { name: "a", price: null }, { name: "c", price: 2 }, { name: "d", price: 10 },
    ];
    expect(sortRows(rs, price, "ascending").map((r) => r.name)).toEqual(["c", "b", "d", "a"]);
    expect(sortRows(rs, price, "descending").map((r) => r.name)).toEqual(["b", "d", "c", "a"]);
    expect(sortRows(rs, name, "ascending").map((r) => r.name)).toEqual(["a", "b", "c", "d"]);
    expect(rs.map((r) => r.name)).toEqual(["b", "a", "c", "d"]); // untouched
  });
  test("sortValue wins over the default, and an empty string counts as missing", () => {
    const status = { key: "status", label: "Status", render: (r) => r.status, sortValue: (r) => ["missing", "ready", "approved"].indexOf(r.status) };
    const rs = [{ status: "approved" }, { status: "missing" }, { status: "ready" }];
    expect(sortRows(rs, status, "ascending").map((r) => r.status)).toEqual(["missing", "ready", "approved"]);
    const note = columns[4];
    const ns = [{ note: "" }, { note: "z" }, { note: "a" }];
    expect(sortRows(ns, note, "descending").map((r) => r.note)).toEqual(["z", "a", ""]);
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/grid/useGridSelection.test.js`
Expected: FAIL — `sortRows` is not exported.

- [ ] **Step 3: Implement**

Append to `src/components/grid/useGridSelection.js`:

```js
function sortValueOf(column, row) {
  if (column.sortValue) return column.sortValue(row);
  if (column.edit) return column.edit.value(row);
  return row[column.key];
}

const missing = (v) => v == null || v === "";

/** A sorted copy. Numbers numerically, strings with localeCompare,
 *  missing values last whichever way, ties in their existing order. */
export function sortRows(rows, column, direction) {
  const sign = direction === "descending" ? -1 : 1;
  return rows
    .map((row, i) => ({ row, i, v: sortValueOf(column, row) }))
    .sort((a, b) => {
      const am = missing(a.v), bm = missing(b.v);
      if (am && bm) return a.i - b.i;
      if (am) return 1;
      if (bm) return -1;
      let cmp;
      if (typeof a.v === "number" && typeof b.v === "number") cmp = a.v - b.v;
      else cmp = String(a.v).localeCompare(String(b.v), undefined, { numeric: true, sensitivity: "base" });
      return cmp !== 0 ? cmp * sign : a.i - b.i;
    })
    .map((e) => e.row);
}
```

- [ ] **Step 4: Run the tests**

Run: `npm test -- --run src/components/grid/useGridSelection.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/grid/useGridSelection.js src/components/grid/useGridSelection.test.js
git commit -m "Grid: sortRows — stable, missing values last, sortValue over the default

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Range selection in `DataGrid`

**Files:**
- Modify: `src/components/grid/DataGrid.jsx`
- Test: `src/components/grid/DataGrid.test.jsx`

**Interfaces:**
- Consumes: `extend`, `selectAll`, `normalize` from `./useGridSelection.js`.
- Produces: `DataGrid` renders `aria-multiselectable="true"` on the table; `aria-selected="true"` on every cell in the range; `data-active` on the focus cell; the internal `selection` object `{ anchor, focus }` and `range = normalize(selection, columns)` that Tasks 5–6 read. Internal helpers `activate(next)` (collapse + move), `extendTo(next)` (keep anchor + move), `collapse()`.

- [ ] **Step 1: Write the failing tests**

Add to `src/components/grid/DataGrid.test.jsx` (a new `describe`), and update the markup test `"is a grid with a caption, one tabbable cell…"` to also assert `expect(cell(0, HOURS)).toHaveAttribute("data-active")` and `expect(screen.getByRole("grid")).toHaveAttribute("aria-multiselectable", "true")`:

```js
describe("range selection", () => {
  const selected = () => document.querySelectorAll('[aria-selected="true"]');

  test("Shift+ArrowRight extends over a read-only cell; the focus alone is data-active", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowLeft" }); // Quantity
    fireEvent.keyDown(cell(0, 0), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    expect(selected()).toHaveLength(4);
    expect(cell(0, 0)).toHaveAttribute("aria-selected", "true");
    expect(cell(1, HOURS)).toHaveAttribute("aria-selected", "true");
    expect(document.querySelectorAll("[data-active]")).toHaveLength(1);
    expect(cell(1, HOURS)).toHaveAttribute("data-active");
    expect(document.activeElement).toBe(cell(1, HOURS));
  });

  test("a plain arrow collapses the range, and so does Escape", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    expect(selected()).toHaveLength(2);
    fireEvent.keyDown(cell(1, HOURS), { key: "ArrowUp" });
    expect(selected()).toHaveLength(1);
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(1, HOURS), { key: "Escape" });
    expect(selected()).toHaveLength(1);
    expect(cell(1, HOURS)).toHaveAttribute("data-active");
  });

  test("Shift+click extends from the anchor; Ctrl+A covers the grid", () => {
    setup();
    fireEvent.click(cell(2, NOTE), { shiftKey: true });
    expect(selected()).toHaveLength(6); // rows 0–2 × hours, note
    expect(cell(2, NOTE)).toHaveAttribute("data-active");
    fireEvent.keyDown(cell(2, NOTE), { key: "a", ctrlKey: true });
    expect(selected()).toHaveLength(15); // 3 rows × 5 columns, rowheaders included
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  test("clicking a read-only cell makes it active with no editor; clicking a link inside a cell does not", () => {
    const withLink = [...columns];
    withLink[1] = { ...columns[1], render: (r) => <a href="https://example.test">{r.qty}</a> };
    const { onCommit } = setup({ columns: withLink });
    fireEvent.click(cell(1, 0));
    expect(cell(1, 0)).toHaveAttribute("data-active");
    expect(document.activeElement).toBe(cell(1, 0));
    fireEvent.click(cell(1, 0));
    expect(screen.queryByRole("textbox")).toBeNull();
    const link = screen.getAllByRole("link")[2];
    link.focus();
    fireEvent.click(link);
    expect(cell(2, 0)).not.toHaveAttribute("data-active");
    expect(document.activeElement).toBe(link);
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("the Clear button never renders over a multi-cell range", () => {
    setup();
    expect(screen.getByRole("button", { name: "Clear entry" })).toBeInTheDocument();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    expect(screen.queryByRole("button", { name: "Clear entry" })).toBeNull();
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: FAIL — no `aria-multiselectable`, no `data-active`, Shift+arrow moves instead of extending.

- [ ] **Step 3: Add the anchor and the selection**

In `src/components/grid/DataGrid.jsx`:

Import: `import { extend, normalize, selectAll } from "./useGridSelection.js";` and add `useMemo` to the React import.

After `const { active, setActive, move } = useGridNavigation(columns, rows);` add:

```js
  // The other end of the selection. null means "same as the active
  // cell" -- a single-cell selection, the state every earlier
  // behaviour was written for. Shift+arrow and Shift+click set it;
  // every plain move, click, commit, or Escape clears it.
  const [anchor, setAnchor] = useState(null);
  const selection = useMemo(() => (active ? { anchor: anchor || active, focus: active } : null), [anchor, active]);
  const range = useMemo(() => (selection ? normalize(selection, columns) : null), [selection, columns]);
  const isRange = Boolean(range && (range.r0 !== range.r1 || range.c0 !== range.c1));
```

Keep the anchor inside the grid if rows shrink: add next to the existing focus effect

```js
  useEffect(() => {
    if (anchor && anchor.row >= rows.length) setAnchor(null);
  }, [anchor, rows.length]);
```

Replace `activate` and add two helpers:

```js
  function activate(next) {
    if (!next) return;
    focusPending.current = true;
    setAnchor(null);
    setActive(next);
  }

  // Moves the focus and keeps the anchor -- Shift+arrow, Shift+click.
  function extendTo(next) {
    if (!next || !active) return;
    focusPending.current = true;
    if (!anchor) setAnchor(active);
    setActive(next);
  }

  function collapse() {
    setAnchor(null);
  }
```

In `startEdit`, after `setActive({ row, col });` add `setAnchor(null);`.

In `onCellKeyDown`, replace the `MOVES` block with:

```js
    const SHIFT_MOVES = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
    if (event.shiftKey && SHIFT_MOVES[event.key] && selection) {
      event.preventDefault();
      extendTo(extend(selection, SHIFT_MOVES[event.key], columns, rows).focus);
      return;
    }
    if (MOVES[event.key]) {
      event.preventDefault();
      activate(move(MOVES[event.key]));
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      const all = selectAll(columns, rows);
      if (all) {
        focusPending.current = true;
        setAnchor(all.anchor);
        setActive(all.focus);
      }
      return;
    }
    if (event.key === "Escape") {
      collapse();
      return;
    }
```

(`MOVES` stays as it is; `Escape` must come before the `!isEditable` return so it works on read-only cells.)

Replace `onCellClick` with:

```js
  function onCellClick(event, row, column) {
    // A click on interactive content inside a cell -- the seller
    // <details>, a link -- belongs to that content: it neither moves
    // focus onto the cell nor selects it.
    if (event.target !== event.currentTarget && event.target.closest("a, button, summary, input, select, textarea, [contenteditable]")) {
      return;
    }
    const next = { row, col: column.key };
    if (event.shiftKey) {
      extendTo(next);
      return;
    }
    const isActive = active && active.row === row && active.col === column.key;
    if (isActive && !editing && !anchor && isEditable(column, rows[row])) startEdit(row, column.key, { caret: "end" });
    else if (!isActive || anchor) activate(next);
  }
```

and its call site: `onClick={(event) => onCellClick(event, row, column)}`.

In `renderCell`:

```js
    const isActive = Boolean(active && active.row === row && active.col === column.key);
    const ci = columns.indexOf(column);
    const inRange = Boolean(range && row >= range.r0 && row <= range.r1 && ci >= range.c0 && ci <= range.c1);
    ...
    const showClear = isActive && !isRange && !isEditing && editable && column.edit.hasEntry && column.edit.hasEntry(r);
```

and on the `<Tag>`: `aria-selected={inRange || undefined}` and `data-active={isActive || undefined}`.

On the `<table>`: add `aria-multiselectable="true"`.

Also update the file's header comment: after the paragraph ending "reads as 'clear this and fall back to the next source'." add:

```
   Shift+arrow and Shift+click grow a range from an anchor; the focus
   is still the one active cell. Every cell in the range is
   aria-selected; only the focus carries data-active and the ring, so
   a range reads as a wash and never as a status.
```

- [ ] **Step 4: Run the grid tests**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: PASS. If the `"clicking a read-only cell…"` test fails on `getAllByRole("link")[2]`, confirm the custom `qty` column renders a link per row (three links) — index 2 is row 2's.

- [ ] **Step 5: Run the two workspace tests to make sure nothing regressed**

Run: `npm test -- --run src/components/labor src/components/pricing`
Expected: PASS, including "Tab from inside the market evidence details is not hijacked back onto the grid".

- [ ] **Step 6: Commit**

```bash
git add src/components/grid/DataGrid.jsx src/components/grid/DataGrid.test.jsx
git commit -m "Grid: Shift+arrow and Shift+click select a range, Ctrl+A selects all, any cell can be active by click

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Copy, paste, Ctrl+D, Delete over a range, Ctrl+Z — and `onCommitRange`

**Files:**
- Modify: `src/components/grid/DataGrid.jsx`
- Test: `src/components/grid/DataGrid.test.jsx`

**Interfaces:**
- Consumes: `toTsv`, `parseClipboard`, `pasteChanges`, `fillChanges`, `clearChanges`, `range`, `isRange` from Tasks 2 and 4.
- Produces: new `DataGrid` props `onCommitRange(changes, { kind })` (`kind` ∈ `"paste" | "fill" | "clear"`), `onUndo()`, `onRedo()`; internal `dispatchRange(changes, kind)` used by Task 6.

- [ ] **Step 1: Write the failing tests**

Add to `src/components/grid/DataGrid.test.jsx`:

```js
function clipboardEvent(type, data = {}) {
  // jsdom has no ClipboardEvent constructor with clipboardData; a plain
  // Event with the property attached is what fireEvent passes through.
  const store = { ...data };
  return {
    clipboardData: {
      getData: (t) => store[t] ?? "",
      setData: (t, v) => { store[t] = v; },
      types: Object.keys(store),
    },
    _store: store,
  };
}

describe("clipboard, fill, clear, undo", () => {
  test("copy writes the range as TSV and prevents the default", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowLeft" }); // Quantity
    fireEvent.keyDown(cell(0, 0), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    const ev = clipboardEvent("copy");
    const prevented = !fireEvent.copy(screen.getByRole("grid"), ev);
    expect(prevented).toBe(true);
    expect(ev._store["text/plain"]).toBe("1\t0.5\n2\t");
  });

  test("copy inside an open editor is left to the input", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    const ev = clipboardEvent("copy");
    const prevented = !fireEvent.copy(screen.getByRole("textbox"), ev);
    expect(prevented).toBe(false);
  });

  test("paste maps the clip through onCommitRange and never through onCommit", () => {
    const onCommitRange = vi.fn();
    const { onCommit } = setup({ onCommitRange });
    fireEvent.paste(cell(0, HOURS), clipboardEvent("paste", { "text/plain": "2\tfirst\r\n3\tsecond\r\n" }));
    expect(onCommit).not.toHaveBeenCalled();
    expect(onCommitRange).toHaveBeenCalledTimes(1);
    expect(onCommitRange).toHaveBeenCalledWith(
      [
        { row: rows[0], key: "hours", value: 2 },
        { row: rows[0], key: "note", value: "first" },
        { row: rows[1], key: "hours", value: 3 },
        { row: rows[1], key: "note", value: "second" },
      ],
      { kind: "paste" },
    );
  });

  test("a paste with nothing applicable calls nothing; a paste while editing is left to the input", () => {
    const onCommitRange = vi.fn();
    const { onCommit } = setup({ onCommitRange });
    fireEvent.paste(cell(0, HOURS), clipboardEvent("paste", { "text/plain": "abc" }));
    expect(onCommitRange).not.toHaveBeenCalled();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.paste(screen.getByRole("textbox"), clipboardEvent("paste", { "text/plain": "7" }));
    expect(onCommitRange).not.toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("without onCommitRange a paste goes through onCommit once per change, in order", () => {
    const { onCommit } = setup();
    fireEvent.paste(cell(0, HOURS), clipboardEvent("paste", { "text/plain": "2\n3" }));
    expect(onCommit.mock.calls).toEqual([[rows[0], "hours", 2], [rows[1], "hours", 3]]);
  });

  test("Ctrl+D fills the top row down the range; on one cell it does nothing", () => {
    const onCommitRange = vi.fn();
    setup({ onCommitRange });
    fireEvent.keyDown(cell(0, HOURS), { key: "d", ctrlKey: true });
    expect(onCommitRange).not.toHaveBeenCalled();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(1, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(2, HOURS), { key: "d", metaKey: true });
    expect(onCommitRange).toHaveBeenCalledWith(
      [{ row: rows[1], key: "hours", value: 0.5 }, { row: rows[2], key: "hours", value: 0.5 }],
      { kind: "fill" },
    );
  });

  test("Delete over a range clears every entry through onCommitRange; on one cell it still uses onCommit", () => {
    const onCommitRange = vi.fn();
    const { onCommit } = setup({ onCommitRange });
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(1, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(2, HOURS), { key: "Delete" });
    expect(onCommitRange).toHaveBeenCalledWith(
      [{ row: rows[0], key: "hours", value: null }, { row: rows[2], key: "hours", value: null }],
      { kind: "clear" },
    );
    expect(onCommit).not.toHaveBeenCalled();
    fireEvent.keyDown(cell(2, HOURS), { key: "Escape" });
    fireEvent.keyDown(cell(2, HOURS), { key: "Backspace" });
    expect(onCommit).toHaveBeenCalledWith(rows[2], "hours", null);
  });

  test("Ctrl+Z and Ctrl+Shift+Z call onUndo and onRedo on a cell, never inside an editor", () => {
    const onUndo = vi.fn(), onRedo = vi.fn();
    setup({ onUndo, onRedo });
    fireEvent.keyDown(cell(0, HOURS), { key: "z", metaKey: true });
    expect(onUndo).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(cell(0, HOURS), { key: "Z", ctrlKey: true, shiftKey: true });
    expect(onRedo).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "z", metaKey: true });
    expect(onUndo).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: FAIL — copy does not prevent default, paste calls nothing, etc.

- [ ] **Step 3: Implement**

In `src/components/grid/DataGrid.jsx`:

Extend the import: `import { clearChanges, extend, fillChanges, normalize, parseClipboard, pasteChanges, selectAll, toTsv } from "./useGridSelection.js";`

Add the props: `{ columns, rows, rowKey, rowLabel, onCommit, onCommitRange, onCancel, onUndo, onRedo, footer, caption }`.

Add after `collapse()`:

```js
  /** Every range operation ends here: the screen gets the whole list
   *  once (onCommitRange) or, on a grid without it, one onCommit per
   *  change in order. An empty list is nothing -- no call, no toast. */
  function dispatchRange(changes, kind) {
    if (!changes.length) return;
    if (onCommitRange) onCommitRange(changes, { kind });
    else for (const c of changes) onCommit(c.row, c.key, c.value);
  }

  function copyText() {
    return range ? toTsv(range, columns, rows) : "";
  }

  function onCopy(event) {
    if (editing || !range) return; // the input's own copy
    event.clipboardData.setData("text/plain", copyText());
    event.preventDefault();
  }

  function onPaste(event) {
    if (editing || !range) return;
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain");
    dispatchRange(pasteChanges(parseClipboard(text), range, columns, rows), "paste");
  }
```

In `onCellKeyDown`, after the Escape block and before `if (!isEditable(column, rows[row])) return;`, add:

```js
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) onRedo?.();
      else onUndo?.();
      return;
    }
    if (mod && event.key.toLowerCase() === "c") {
      // Browsers differ on whether Ctrl/Cmd+C fires `copy` on a focused
      // non-editable element with no text selection; the copy handler
      // above covers the ones that do, this covers the rest. Both may
      // run and write the same text.
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) navigator.clipboard.writeText(copyText()).catch(() => {});
      return;
    }
    if (mod && event.key.toLowerCase() === "d") {
      event.preventDefault();
      if (range && range.r1 > range.r0) dispatchRange(fillChanges(range, columns, rows), "fill");
      return;
    }
    if ((event.key === "Delete" || event.key === "Backspace") && isRange) {
      event.preventDefault();
      dispatchRange(clearChanges(range, columns, rows), "clear");
      return;
    }
```

On the `<table>`: `onCopy={onCopy} onPaste={onPaste}`.

- [ ] **Step 4: Run the grid tests**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: PASS. If `fireEvent.copy` returns `true` even though `preventDefault` ran, check the handler is on the `<table>` element `getByRole("grid")` returns and that `editing` is null.

- [ ] **Step 5: Commit**

```bash
git add src/components/grid/DataGrid.jsx src/components/grid/DataGrid.test.jsx
git commit -m "Grid: copy and paste a block as TSV, Ctrl+D fills down, Delete clears a range, Ctrl+Z reaches undo — all through onCommitRange

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The fill handle

**Files:**
- Modify: `src/components/grid/DataGrid.jsx`
- Test: `src/components/grid/DataGrid.test.jsx`

**Interfaces:**
- Consumes: `range`, `dispatchRange`, `fillChanges(range, columns, rows, { to })`.
- Produces: a `<div class="grid-fill-handle" aria-hidden="true">` in the range's bottom-right cell; `data-fill-target` on cells the drag would write; after release the selection covers source and target rows.

- [ ] **Step 1: Write the failing tests**

```js
describe("fill handle", () => {
  const handle = () => document.querySelector(".grid-fill-handle");

  test("renders only in the range's bottom-right cell", () => {
    setup();
    expect(cell(0, HOURS).contains(handle())).toBe(true);
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowRight", shiftKey: true });
    expect(cell(0, NOTE).contains(handle())).toBe(true);
    expect(document.querySelectorAll(".grid-fill-handle")).toHaveLength(1);
  });

  test("dragging down repeats the source rows onto the rows passed, then extends the selection", () => {
    const onCommitRange = vi.fn();
    setup({ onCommitRange });
    fireEvent.mouseDown(handle());
    fireEvent.mouseEnter(cell(1, HOURS));
    expect(cell(1, HOURS)).toHaveAttribute("data-fill-target");
    fireEvent.mouseEnter(cell(2, HOURS));
    expect(cell(2, HOURS)).toHaveAttribute("data-fill-target");
    fireEvent.mouseUp(document);
    expect(onCommitRange).toHaveBeenCalledWith(
      [{ row: rows[1], key: "hours", value: 0.5 }, { row: rows[2], key: "hours", value: 0.5 }],
      { kind: "fill" },
    );
    expect(document.querySelectorAll('[aria-selected="true"]')).toHaveLength(3);
    expect(cell(2, HOURS)).toHaveAttribute("data-active");
    expect(cell(2, HOURS)).not.toHaveAttribute("data-fill-target");
  });

  test("releasing on the source row, or above it, fills nothing", () => {
    const onCommitRange = vi.fn();
    setup({ onCommitRange });
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown" });
    fireEvent.mouseDown(handle());
    fireEvent.mouseEnter(cell(0, HOURS));
    fireEvent.mouseUp(document);
    expect(onCommitRange).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: FAIL — no `.grid-fill-handle`.

- [ ] **Step 3: Implement**

In `DataGrid.jsx` add:

```js
  // The fill handle drag. `fillDrag` is the source range while the
  // mouse is down (null otherwise); `fillTo` is the last row the pointer
  // entered -- state so the target cells re-render with their dashed
  // outline, mirrored in a ref so the mouseup handler reads the latest
  // value without a stale closure.
  const fillDrag = useRef(null);
  const fillToRef = useRef(null);
  const [fillTo, setFillTo] = useState(null);

  function startFill(event) {
    event.preventDefault();
    event.stopPropagation();
    if (!range) return;
    fillDrag.current = range;
    fillToRef.current = range.r1;
    setFillTo(range.r1);
    const onUp = () => {
      document.removeEventListener("mouseup", onUp);
      const source = fillDrag.current;
      const to = fillToRef.current;
      fillDrag.current = null;
      fillToRef.current = null;
      setFillTo(null);
      if (source && to != null && to > source.r1) {
        dispatchRange(fillChanges(source, columns, rows, { to }), "fill");
        focusPending.current = true;
        setAnchor({ row: source.r0, col: columns[source.c0].key });
        setActive({ row: to, col: columns[source.c1].key });
      }
    };
    document.addEventListener("mouseup", onUp);
  }

  function onCellMouseEnter(row) {
    if (!fillDrag.current) return;
    fillToRef.current = row;
    setFillTo(row);
  }
```

In `renderCell`:

```js
    const showHandle = Boolean(range && row === range.r1 && ci === range.c1 && !isEditing);
    const drag = fillDrag.current;
    const fillTarget = Boolean(drag && fillTo != null && row > drag.r1 && row <= fillTo && ci >= drag.c0 && ci <= drag.c1);
```

add `data-fill-target={fillTarget || undefined}` and `onMouseEnter={() => onCellMouseEnter(row)}` to the `<Tag>`, and in the non-editing branch after the Clear button:

```jsx
            {showHandle ? <div className="grid-fill-handle" aria-hidden="true" onMouseDown={startFill} /> : null}
```

- [ ] **Step 4: Run the grid tests**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/grid/DataGrid.jsx src/components/grid/DataGrid.test.jsx
git commit -m "Grid: a fill handle at the range's corner drags the source rows down

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Sort by header

**Files:**
- Modify: `src/components/grid/DataGrid.jsx`
- Test: `src/components/grid/DataGrid.test.jsx`

**Interfaces:**
- Consumes: `sortRows(rows, column, direction)`.
- Produces: each `<th scope="col">` wraps a `<button type="button" class="grid-sort">` with the label; `aria-sort` on the `<th>`; the grid renders `displayRows` (an ordered view of `rows`) everywhere it used `rows` for indices.

- [ ] **Step 1: Write the failing tests**

```js
describe("sort", () => {
  const names = () => screen.getAllByRole("rowheader").map((h) => h.textContent);
  const header = (label) => screen.getByRole("columnheader", { name: label });

  test("a header click cycles ascending, descending, off, with aria-sort and a reordered body", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Hours" }));
    expect(header("Hours")).toHaveAttribute("aria-sort", "ascending");
    expect(names()).toEqual(["One", "Three", "Two"]); // 0.5, 1, null last
    fireEvent.click(screen.getByRole("button", { name: "Hours" }));
    expect(header("Hours")).toHaveAttribute("aria-sort", "descending");
    expect(names()).toEqual(["Three", "One", "Two"]);
    fireEvent.click(screen.getByRole("button", { name: "Hours" }));
    expect(header("Hours")).not.toHaveAttribute("aria-sort");
    expect(names()).toEqual(["One", "Two", "Three"]);
  });

  test("editing a sorted cell does not move its row; a reload with the same keys keeps the order; a new key appends", () => {
    const { rerender } = render(<DataGrid columns={columns} rows={rows} rowKey={(r) => r.id} rowLabel={(r) => r.name} onCommit={() => {}} caption="t" />);
    fireEvent.click(screen.getByRole("button", { name: "Hours" }));
    expect(names()).toEqual(["One", "Three", "Two"]);
    const edited = rows.map((r) => (r.id === "r1" ? { ...r, hours: 99 } : r));
    rerender(<DataGrid columns={columns} rows={edited} rowKey={(r) => r.id} rowLabel={(r) => r.name} onCommit={() => {}} caption="t" />);
    expect(names()).toEqual(["One", "Three", "Two"]);
    const added = [...edited, { id: "r4", name: "Four", qty: 4, hours: 0, entered: false, note: "", basis: "a" }];
    rerender(<DataGrid columns={columns} rows={added} rowKey={(r) => r.id} rowLabel={(r) => r.name} onCommit={() => {}} caption="t" />);
    expect(names()).toEqual(["Four", "Three", "One", "Two"]); // re-sorted: the key set changed
  });

  test("selection and commits follow the displayed order", () => {
    const { onCommit } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Hours" }));
    // Displayed row 1 is "Three" now.
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown" });
    fireEvent.keyDown(cell(1, HOURS), { key: "Delete" });
    expect(onCommit).toHaveBeenCalledWith(rows[2], "hours", null);
  });
});
```

Note: the third test's second `rerender` expects the new order `["Four", "Three", "One", "Two"]` — with `hours` 99 on One, ascending is Four (0), Three (1), One (99), Two (null). Correct as written.

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: FAIL — no button named "Hours".

- [ ] **Step 3: Implement**

In `DataGrid.jsx`, import `ArrowDown, ArrowUp` from `lucide-react` alongside `X`, and `sortRows` from the selection module.

Rename the prop `rows` to `sourceRows` in the destructuring and add, before `useGridNavigation`:

```js
  // Sorting reorders once, Sheets-style: `order` (row keys) is set when
  // a header is clicked and again only when the set of keys changes (a
  // reload). A cell edit that changes the sorted value does not move
  // its row until the header is clicked again -- rows jumping under an
  // estimator mid-Tab is the failure this avoids.
  const [sort, setSort] = useState(null); // { key, direction } | null
  const [order, setOrder] = useState(null); // row keys | null = load order
  const keysSignature = sourceRows.map(rowKey).join(" ");
  const rows = useMemo(() => {
    if (!order) return sourceRows;
    const byKey = new Map(sourceRows.map((r) => [rowKey(r), r]));
    const out = [];
    for (const k of order) {
      if (byKey.has(k)) {
        out.push(byKey.get(k));
        byKey.delete(k);
      }
    }
    return [...out, ...byKey.values()];
  }, [sourceRows, order, rowKey]);

  const applySort = (next) => {
    setSort(next);
    if (!next) {
      setOrder(null);
      return;
    }
    const column = columns.find((c) => c.key === next.key);
    setOrder(sortRows(sourceRows, column, next.direction).map(rowKey));
  };

  const firstSignature = useRef(keysSignature);
  useEffect(() => {
    if (firstSignature.current === keysSignature) return;
    firstSignature.current = keysSignature;
    if (sort) applySort(sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keysSignature]);

  function onSortClick(column) {
    const cur = sort && sort.key === column.key ? sort.direction : null;
    const next = cur === null ? "ascending" : cur === "ascending" ? "descending" : null;
    setAnchor(null);
    applySort(next ? { key: column.key, direction: next } : null);
  }
```

`useGridNavigation(columns, rows)` and everything below keep using `rows`, which is now the displayed order. (`setAnchor` is declared in Task 4 — place this block after it, or hoist `useState` for `anchor` above.)

Replace the header row:

```jsx
          <tr role="row">
            {columns.map((c) => {
              const dir = sort && sort.key === c.key ? sort.direction : null;
              return (
                <th key={c.key} scope="col" role="columnheader" aria-sort={dir || undefined} style={{ textAlign: c.align }}>
                  <button type="button" className="grid-sort" onClick={() => onSortClick(c)}>
                    {c.label}
                    {dir === "ascending" ? <ArrowUp size={12} aria-hidden="true" /> : null}
                    {dir === "descending" ? <ArrowDown size={12} aria-hidden="true" /> : null}
                  </button>
                </th>
              );
            })}
          </tr>
```

- [ ] **Step 4: Run the grid tests and the workspace tests**

Run: `npm test -- --run src/components/grid src/components/labor src/components/pricing`
Expected: PASS. The workspace tests' `cellFor` reads `columnheader` `textContent`, which is still the label (the icon is an SVG with no text).

- [ ] **Step 5: Commit**

```bash
git add src/components/grid/DataGrid.jsx src/components/grid/DataGrid.test.jsx
git commit -m "Grid: click a header to sort ascending, descending, off; the order holds until the next click

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Column resize

**Files:**
- Modify: `src/components/grid/DataGrid.jsx`
- Test: `src/components/grid/DataGrid.test.jsx`

**Interfaces:**
- Produces: a `<div class="grid-resize" role="presentation">` in each `<th>`; on the first drag a `<colgroup>` with one `<col style="width: Npx">` per column and `table-layout: fixed` on the table; `.is-resizing` on the table during a drag.

- [ ] **Step 1: Write the failing tests**

```js
describe("resize", () => {
  const handles = () => document.querySelectorAll(".grid-resize");

  test("dragging a header edge widens that column and freezes the layout; the floor is 60px; the drag does not sort", () => {
    setup();
    expect(handles()).toHaveLength(5);
    const h = handles()[2]; // Hours
    fireEvent.mouseDown(h, { clientX: 100 });
    expect(screen.getByRole("grid")).toHaveClass("is-resizing");
    fireEvent.mouseMove(document, { clientX: 140 });
    fireEvent.mouseUp(document);
    const cols = document.querySelectorAll("colgroup col");
    expect(cols).toHaveLength(5);
    // jsdom reports offsetWidth 0, so the snapshot falls back to 120px.
    expect(cols[2].style.width).toBe("160px");
    expect(cols[1].style.width).toBe("120px");
    expect(screen.getByRole("grid").style.tableLayout).toBe("fixed");
    expect(screen.getByRole("grid")).not.toHaveClass("is-resizing");
    expect(screen.getByRole("columnheader", { name: "Hours" })).not.toHaveAttribute("aria-sort");
    fireEvent.mouseDown(h, { clientX: 100 });
    fireEvent.mouseMove(document, { clientX: -500 });
    fireEvent.mouseUp(document);
    expect(document.querySelectorAll("colgroup col")[2].style.width).toBe("60px");
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: FAIL — no `.grid-resize`.

- [ ] **Step 3: Implement**

In `DataGrid.jsx`:

```js
  const DEFAULT_WIDTH = 120;
  const MIN_WIDTH = 60;
  const [widths, setWidths] = useState(null); // Map key -> px, once any column has been resized
  const [resizing, setResizing] = useState(false);
  const headers = useRef(new Map());

  function startResize(event, key) {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    // First drag: snapshot what the browser's auto layout gave every
    // column, so only the dragged one moves from here on.
    const base = widths || new Map(columns.map((c) => [c.key, headers.current.get(c.key)?.offsetWidth || DEFAULT_WIDTH]));
    const startWidth = base.get(key);
    setWidths(base);
    setResizing(true);
    const onMove = (e) => {
      const next = new Map(base);
      next.set(key, Math.max(MIN_WIDTH, startWidth + e.clientX - startX));
      setWidths(next);
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      setResizing(false);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }
```

Header cell: add `ref={(el) => (el ? headers.current.set(c.key, el) : headers.current.delete(c.key))}` on the `<th>`, and after the sort button:

```jsx
                  <div className="grid-resize" role="presentation" onMouseDown={(event) => startResize(event, c.key)} />
```

Table:

```jsx
      <table
        className={"data-table takeoff-table grid" + (resizing ? " is-resizing" : "")}
        role="grid"
        aria-multiselectable="true"
        style={widths ? { tableLayout: "fixed", width: [...widths.values()].reduce((a, b) => a + b, 0) + "px" } : undefined}
        onCopy={onCopy}
        onPaste={onPaste}
      >
        <caption className="sr-only">{caption}</caption>
        {widths ? (
          <colgroup>
            {columns.map((c) => (
              <col key={c.key} style={{ width: widths.get(c.key) + "px" }} />
            ))}
          </colgroup>
        ) : null}
```

- [ ] **Step 4: Run the grid tests**

Run: `npm test -- --run src/components/grid/DataGrid.test.jsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/grid/DataGrid.jsx src/components/grid/DataGrid.test.jsx
git commit -m "Grid: drag a header edge to resize a column

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Styles

**Files:**
- Modify: `src/styles.css` (append only)

- [ ] **Step 1: Append the block**

At the very end of `src/styles.css`:

```css
/* ==== stream B: grid ==== */
/* docs/specs/spreadsheet-grid.md, "Styling". A range is a wash of the
   selection blue; the focus cell alone keeps the ring. Nothing here is
   a status colour. --grid-range sits here rather than with the tokens
   at the top per the shared-file rule; the coordinator may move it. */
:root { --grid-range: color-mix(in srgb, var(--blue) 12%, transparent); }
.grid [aria-selected="true"]:not([data-active]) { box-shadow: none; background: var(--grid-range); }
.grid [data-active] { box-shadow: inset 0 0 0 2px var(--blue); }
.grid td[data-fill-target], .grid th[data-fill-target] { outline: 1px dashed var(--ink-3); outline-offset: -3px; }
.grid-fill-handle {
  position: absolute; right: 1px; bottom: 1px; width: 7px; height: 7px;
  background: var(--blue); cursor: crosshair;
}
.grid-sort {
  display: inline-flex; align-items: center; gap: 4px;
  font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer;
}
.grid-sort svg { color: var(--ink-2); }
.grid-sort:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.grid th[aria-sort] .grid-sort { font-weight: 600; }
.grid-resize {
  position: absolute; top: 0; right: -4px; width: 8px; height: 100%;
  cursor: col-resize; user-select: none;
}
.grid-resize:hover { background: var(--grid-range); }
.grid.is-resizing, .grid.is-resizing * { user-select: none; cursor: col-resize; }
```

Check the token names exist: `grep -n "^  --blue\|^  --ink-2\|^  --ink-3" src/styles.css` should show all three; if a name differs, use the one in the file.

- [ ] **Step 2: Build**

Run: `npm run build`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add src/styles.css
git commit -m "Grid styles: the range wash, fill handle, sort button, and resize handle, appended under the stream B banner

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Range copy and the N-fold undo, shared by both screens

**Files:**
- Create: `src/components/grid/rangeCopy.js`, `src/components/grid/useUndoCount.js`
- Test: `src/components/grid/rangeCopy.test.js`, `src/components/grid/useUndoCount.test.jsx`

**Interfaces:**
- Produces:
  - `rangeToast(kind, cells, rows, { skipped = 0, skippedWhy } = {})` → string, e.g. `"Pasted 40 cells on 20 rows"`, `"Cleared 1 cell on 1 row"`, `"Pasted 38 cells on 19 rows — 2 rows skipped, an allowance needs a reason"`
  - `rangeFailure(failed, total)` → `"3 of 40 cells couldn't be saved. Try again."`
  - `reversedToast(cells)` → `"Reversed 40 cells"`
  - `useUndoCount({ undo, load, showToast })` → `{ remember({ calls, cells }), undoLast() }`. `undoLast` awaits `undo()` `calls` times (stopping when a result has `performed === false`), then `load()`, then — when `calls > 1` — `showToast(reversedToast(cells))`. Rejections propagate to the caller. After `undoLast`, the count resets to `{ calls: 1, cells: 1 }`.

- [ ] **Step 1: Write the failing tests**

`src/components/grid/rangeCopy.test.js`:

```js
import { describe, expect, test } from "vitest";
import { rangeFailure, rangeToast, reversedToast } from "./rangeCopy.js";

describe("rangeToast", () => {
  test("names the operation and the counts, singular when one", () => {
    expect(rangeToast("paste", 40, 20)).toBe("Pasted 40 cells on 20 rows");
    expect(rangeToast("fill", 12, 12)).toBe("Filled 12 cells on 12 rows");
    expect(rangeToast("clear", 1, 1)).toBe("Cleared 1 cell on 1 row");
  });
  test("appends the skipped rows and why", () => {
    expect(rangeToast("paste", 38, 19, { skipped: 2, skippedWhy: "an allowance needs a reason" })).toBe(
      "Pasted 38 cells on 19 rows — 2 rows skipped, an allowance needs a reason",
    );
    expect(rangeToast("paste", 3, 3, { skipped: 1, skippedWhy: "an allowance needs a reason" })).toBe(
      "Pasted 3 cells on 3 rows — 1 row skipped, an allowance needs a reason",
    );
  });
});

test("rangeFailure and reversedToast", () => {
  expect(rangeFailure(3, 40)).toBe("3 of 40 cells couldn't be saved. Try again.");
  expect(rangeFailure(1, 1)).toBe("1 of 1 cell couldn't be saved. Try again.");
  expect(reversedToast(40)).toBe("Reversed 40 cells");
  expect(reversedToast(1)).toBe("Reversed 1 cell");
});
```

`src/components/grid/useUndoCount.test.jsx`:

```js
import { describe, expect, test, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useUndoCount } from "./useUndoCount.js";

describe("useUndoCount", () => {
  test("reverses one action by default, then reloads, with no extra toast", async () => {
    const undo = vi.fn().mockResolvedValue({ performed: true });
    const load = vi.fn().mockResolvedValue(undefined);
    const showToast = vi.fn();
    const { result } = renderHook(() => useUndoCount({ undo, load, showToast }));
    await act(() => result.current.undoLast());
    expect(undo).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledTimes(1);
    expect(showToast).not.toHaveBeenCalled();
  });

  test("reverses every call the last toast stood for, newest first, then says so, then resets", async () => {
    const undo = vi.fn().mockResolvedValue({ performed: true });
    const load = vi.fn().mockResolvedValue(undefined);
    const showToast = vi.fn();
    const { result } = renderHook(() => useUndoCount({ undo, load, showToast }));
    act(() => result.current.remember({ calls: 3, cells: 5 }));
    await act(() => result.current.undoLast());
    expect(undo).toHaveBeenCalledTimes(3);
    expect(load).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalledWith("Reversed 5 cells");
    await act(() => result.current.undoLast());
    expect(undo).toHaveBeenCalledTimes(4);
  });

  test("stops when the stack runs dry, and a rejection reaches the caller", async () => {
    const undo = vi.fn().mockResolvedValueOnce({ performed: true }).mockResolvedValueOnce({ performed: false });
    const load = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useUndoCount({ undo, load, showToast: vi.fn() }));
    act(() => result.current.remember({ calls: 4, cells: 4 }));
    await act(() => result.current.undoLast());
    expect(undo).toHaveBeenCalledTimes(2);
    const failing = renderHook(() => useUndoCount({ undo: vi.fn().mockRejectedValue(new Error("Nothing to undo")), load, showToast: vi.fn() }));
    await expect(failing.result.current.undoLast()).rejects.toThrow("Nothing to undo");
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/grid/rangeCopy.test.js src/components/grid/useUndoCount.test.jsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write the modules**

`src/components/grid/rangeCopy.js`:

```js
/* ============================================================
   rangeCopy.js — what a range operation says (docs/specs/
   spreadsheet-grid.md, "The toast, and the undo of a range
   operation"). One toast per operation, counting what landed; one
   banner line when some of it did not; one toast when it is reversed.
   ============================================================ */

const VERB = { paste: "Pasted", fill: "Filled", clear: "Cleared" };
const n = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

export function rangeToast(kind, cells, rows, { skipped = 0, skippedWhy } = {}) {
  let text = `${VERB[kind]} ${n(cells, "cell")} on ${n(rows, "row")}`;
  if (skipped > 0) text += ` — ${n(skipped, "row")} skipped, ${skippedWhy}`;
  return text;
}

export function rangeFailure(failed, total) {
  return `${failed} of ${n(total, "cell")} couldn't be saved. Try again.`;
}

export function reversedToast(cells) {
  return `Reversed ${n(cells, "cell")}`;
}
```

`src/components/grid/useUndoCount.js`:

```js
/* ============================================================
   useUndoCount.js — how many undo() calls the toast's Undo stands
   for (docs/specs/spreadsheet-grid.md, "The toast, and the undo of a
   range operation").

   A range operation lands as N store calls, each its own action on
   the project's shared undo stack. Its toast's Undo reverses all of
   them: undo() N times, newest first, then a reload, then one toast
   naming the count. A single-cell commit is the same path with N = 1.
   The count is a ref, not state: it is written right before showToast
   and read only from the toast's button.
   ============================================================ */

import { useCallback, useRef } from "react";
import { reversedToast } from "./rangeCopy.js";

const ONE = { calls: 1, cells: 1 };

export function useUndoCount({ undo, load, showToast }) {
  const count = useRef(ONE);

  const remember = useCallback(({ calls, cells }) => {
    count.current = { calls, cells };
  }, []);

  const undoLast = useCallback(async () => {
    const { calls, cells } = count.current;
    count.current = ONE;
    for (let i = 0; i < calls; i += 1) {
      const res = await undo();
      if (res && res.performed === false) break;
    }
    await load();
    if (calls > 1) showToast(reversedToast(cells));
  }, [undo, load, showToast]);

  return { remember, undoLast };
}
```

- [ ] **Step 4: Run the tests**

Run: `npm test -- --run src/components/grid/rangeCopy.test.js src/components/grid/useUndoCount.test.jsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/grid/rangeCopy.js src/components/grid/rangeCopy.test.js src/components/grid/useUndoCount.js src/components/grid/useUndoCount.test.jsx
git commit -m "Grid: the range toast copy and the N-fold undo the two pricing screens share

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Labor — columns and `onCommitRange`

**Files:**
- Modify: `src/components/labor/laborColumns.jsx`, `src/components/labor/LaborWorkspace.jsx`
- Test: `src/components/labor/LaborWorkspace.test.jsx`

**Interfaces:**
- Consumes: `rangeToast`, `rangeFailure` from `../grid/rangeCopy.js`; `useUndoCount` from `../grid/useUndoCount.js`; `DataGrid` props `onCommitRange`, `onUndo`, `onRedo`; `STATUS_ORDER`, `STATUS` from `../../lib/vocabulary.js`.
- Produces: Labor sends one `store.setLaborLine` per change, sequentially; toast via `rangeToast`; Undo through `useUndoCount`.

- [ ] **Step 1: Write the failing tests**

Add to `src/components/labor/LaborWorkspace.test.jsx`. It needs a paste helper:

```js
function pasteEvent(text) {
  const store = { "text/plain": text };
  return { clipboardData: { getData: (t) => store[t] ?? "", setData: () => {}, types: ["text/plain"] } };
}
const rowTwo = { ...baseRow, itemId: "i2", itemName: "High bay fixture" };
```

and tests:

```js
  test("a pasted block sends one PATCH per cell, in row-major order, one after another", async () => {
    const calls = [];
    let release;
    const first = new Promise((r) => { release = r; });
    // The server resolves the whole row on every PATCH, so the mock keeps
    // per-item state and returns it cumulatively -- a rate response
    // still carries the hours the previous call set.
    const state = { i1: { ...baseRow }, i2: { ...rowTwo } };
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow, rowTwo] }),
      setLaborLine: vi.fn((itemId, changes) => {
        calls.push([itemId, changes]);
        const s = state[itemId];
        if ("hoursOverride" in changes) Object.assign(s, { hoursPerUnit: changes.hoursOverride, hoursSourceLabel: "Estimator entered" });
        if ("rateOverride" in changes) Object.assign(s, { rate: changes.rateOverride, rateSourceLabel: "Estimator entered" });
        const updated = { ...s };
        return calls.length === 1 ? first.then(() => updated) : Promise.resolve(updated);
      }),
    };
    const review = renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    fireEvent.paste(cellFor("20A duplex receptacle", "Hours/unit"), pasteEvent("0.5\t60\n0.75\t70"));
    // Local state moved before any response.
    expect(cellFor("High bay fixture", "Rate")).toHaveTextContent("$70.00/hr");
    expect(calls).toHaveLength(1); // the second waits on the first
    release();
    await waitFor(() => expect(calls).toHaveLength(4));
    expect(calls).toEqual([
      ["i1", { hoursOverride: 0.5 }], ["i1", { rateOverride: 60 }],
      ["i2", { hoursOverride: 0.75 }], ["i2", { rateOverride: 70 }],
    ]);
    await waitFor(() => expect(review.showToast).toHaveBeenCalledWith("Pasted 4 cells on 2 rows"));
    expect(store.getLaborRows).toHaveBeenCalledTimes(1); // no refetch
    expect(screen.getAllByText("Estimator entered")).toHaveLength(4);
  });

  test("a failed call restores that cell, the rest land, and the banner counts", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow, rowTwo] }),
      setLaborLine: vi.fn()
        .mockResolvedValueOnce({ ...baseRow, hoursPerUnit: 0.5, hoursSourceLabel: "Estimator entered" })
        .mockRejectedValueOnce(new Error("boom"))
        .mockResolvedValueOnce({ ...rowTwo, hoursPerUnit: 0.75, hoursSourceLabel: "Estimator entered" })
        .mockResolvedValueOnce({ ...rowTwo, hoursPerUnit: 0.75, hoursSourceLabel: "Estimator entered", rate: 70, rateSourceLabel: "Estimator entered" }),
    };
    const review = renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    fireEvent.paste(cellFor("20A duplex receptacle", "Hours/unit"), pasteEvent("0.5\t60\n0.75\t70"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("1 of 4 cells couldn't be saved. Try again."));
    expect(cellFor("20A duplex receptacle", "Rate")).toHaveTextContent("—");
    expect(cellFor("High bay fixture", "Rate")).toHaveTextContent("$70.00/hr");
    expect(review.showToast).toHaveBeenCalledWith("Pasted 3 cells on 2 rows");
  });

  test("the toast's Undo after a range operation reverses every call, reloads, and says so", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow, rowTwo] }),
      setLaborLine: vi.fn((itemId, changes) => Promise.resolve({ ...(itemId === "i1" ? baseRow : rowTwo), hoursPerUnit: changes.hoursOverride, hoursSourceLabel: "Estimator entered" })),
    };
    const undo = vi.fn().mockResolvedValue({ performed: true });
    const review = renderLabor({ store, extra: { undo, toast: { id: "t1", text: "Pasted 2 cells on 2 rows" } } });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    fireEvent.paste(cellFor("20A duplex receptacle", "Hours/unit"), pasteEvent("0.5\n0.75"));
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(undo).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(store.getLaborRows).toHaveBeenCalledTimes(2));
    expect(review.showToast).toHaveBeenLastCalledWith("Reversed 2 cells");
    expect(review.dismissToast).toHaveBeenCalled();
  });

  test("Ctrl+Z on a cell reverses one action and reloads; Ctrl+Shift+Z redoes", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    const undo = vi.fn().mockResolvedValue({ performed: true });
    const redo = vi.fn().mockResolvedValue({ performed: true });
    renderLabor({ store, extra: { undo, redo } });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    fireEvent.keyDown(cellFor("20A duplex receptacle", "Hours/unit"), { key: "z", metaKey: true });
    await waitFor(() => expect(undo).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(store.getLaborRows).toHaveBeenCalledTimes(2));
    fireEvent.keyDown(cellFor("20A duplex receptacle", "Hours/unit"), { key: "z", metaKey: true, shiftKey: true });
    await waitFor(() => expect(redo).toHaveBeenCalledTimes(1));
  });

  test("copying the status and item columns gives their labels, not markup", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows: [pricedRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    const status = cellFor("20A duplex receptacle", "Status");
    fireEvent.click(status);
    fireEvent.click(cellFor("20A duplex receptacle", "Hours source"), { shiftKey: true });
    const store2 = {};
    fireEvent.copy(screen.getByRole("grid"), { clipboardData: { setData: (t, v) => { store2[t] = v; }, getData: () => "" } });
    expect(store2["text/plain"]).toBe("Ready to review\t20A duplex receptacle\t10\t0.5\tEstimated basis");
  });
```

The existing test `"shows the save state in the top bar and an undoable toast"` keeps passing: with no range remembered, Undo calls `undo()` once and reloads (`getLaborRows` twice). The existing `"a failed undo shows its message"` test keeps passing because `undoLast`'s rejection is caught the same way.

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/labor/LaborWorkspace.test.jsx`
Expected: FAIL — the five new tests.

- [ ] **Step 3: Columns**

In `src/components/labor/laborColumns.jsx` import `STATUS, STATUS_ORDER` from `"../../lib/vocabulary.js"` and add `text` / `sortValue`:

```js
  { key: "status", label: "Status", align: "left", render: (row) => <Pill status={row.status} />,
    text: (row) => STATUS[row.status]?.label ?? "", sortValue: (row) => STATUS_ORDER.indexOf(row.status) },
  { key: "itemName", ..., text: (row) => row.itemName, sortValue: (row) => row.itemName },
  { key: "hoursSourceLabel", ..., text: (row) => row.hoursSourceLabel ?? "" },
  { key: "rateSourceLabel", ..., text: (row) => row.rateSourceLabel ?? "" },
```

(`quantity`, `adjustedHours`, `laborCost` are primitives on the row and need nothing.)

- [ ] **Step 4: The workspace**

In `src/components/labor/LaborWorkspace.jsx`:

Imports:

```js
import { rangeFailure, rangeToast } from "../grid/rangeCopy.js";
import { useUndoCount } from "../grid/useUndoCount.js";
```

Destructure `redo` from the context too. After `load` is defined:

```js
  const undoCount = useUndoCount({ undo, load, showToast });
```

In `commit`, before `showToast(...)`: `undoCount.remember({ calls: 1, cells: 1 });`.

Add `commitRange`:

```js
  // A range lands as one PATCH per cell, sequentially, each its own
  // action (docs/specs/spreadsheet-grid.md, "What the screens do with a
  // range"). Every change is applied locally first so the footer moves
  // at once; each response replaces its row, keeping any value on that
  // row still waiting to be sent; a failure restores that one cell and
  // the run continues.
  const commitRange = async (changes, { kind }) => {
    setSaveError(null);
    setRows((cur) =>
      cur.map((r) => {
        const mine = changes.filter((c) => c.row.itemId === r.itemId);
        if (!mine.length) return r;
        const next = { ...r };
        for (const c of mine) next[c.key] = c.value;
        return next;
      }),
    );
    let done = 0;
    let failed = 0;
    const touched = new Set();
    for (let i = 0; i < changes.length; i += 1) {
      const c = changes[i];
      const field = FIELDS[c.key];
      const wire = c.key === "adjustmentReason" && c.value === null ? "" : c.value;
      try {
        const updated = await runMutation(() => store.setLaborLine(c.row.itemId, { [field.wire]: wire }));
        const pending = changes.slice(i + 1).filter((p) => p.row.itemId === c.row.itemId);
        const merged = { ...updated };
        for (const p of pending) merged[p.key] = p.value;
        replaceRow(c.row.itemId, merged);
        done += 1;
        touched.add(c.row.itemId);
      } catch {
        setRows((cur) => cur.map((r) => (r.itemId === c.row.itemId ? { ...r, [c.key]: c.row[c.key] } : r)));
        failed += 1;
      }
    }
    if (failed) setSaveError(rangeFailure(failed, changes.length));
    if (done) {
      undoCount.remember({ calls: done, cells: done });
      showToast(rangeToast(kind, done, touched.size));
    }
  };
```

Pass to the grid:

```jsx
              onCommit={commit}
              onCommitRange={commitRange}
              onUndo={() => undo().then(load).catch((err) => setSaveError(err?.message || "That change couldn't be undone. Try again."))}
              onRedo={() => redo().then(load).catch((err) => setSaveError(err?.message || "That change couldn't be redone. Try again."))}
```

Replace the toast button's handler:

```jsx
            onClick={() => {
              undoCount.undoLast().catch((err) => setSaveError(err?.message || "That change couldn't be undone. Try again."));
              dismissToast();
            }}
```

Update the header comment's last paragraph to mention that a range operation is N calls and the toast's Undo reverses them all through `useUndoCount`.

- [ ] **Step 5: Run the labor tests**

Run: `npm test -- --run src/components/labor`
Expected: PASS. If the "one after another" test sees `calls` at 2 before `release()`, the loop is not awaiting — check `await runMutation(...)`.

- [ ] **Step 6: Commit**

```bash
git add src/components/labor/laborColumns.jsx src/components/labor/LaborWorkspace.jsx src/components/labor/LaborWorkspace.test.jsx
git commit -m "Labor: a pasted, filled, or cleared range lands as one PATCH per cell, and the toast's Undo reverses them all

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Material pricing — columns and `onCommitRange` per row

**Files:**
- Modify: `src/components/pricing/pricingColumns.jsx`, `src/components/pricing/MaterialPricingWorkspace.jsx`
- Test: `src/components/pricing/MaterialPricingWorkspace.test.jsx`

**Interfaces:**
- Consumes: as Task 11, plus `ALLOWANCE_REASON_MESSAGE`.
- Produces: Material groups changes by row into one `setMaterialPrice` / `clearMaterialPrice` per row; allowance-without-reason rows skipped and counted; `text`/`sortValue` on columns.

- [ ] **Step 1: Write the failing tests**

Add the same `pasteEvent` helper as Task 11 to `MaterialPricingWorkspace.test.jsx`, plus:

```js
const rowTwo = { ...baseRow, itemId: "i2", itemName: "High bay fixture" };
const loaded = async (name) => waitFor(() => expect(screen.getByRole("rowheader", { name })).toBeInTheDocument());
```

(`loaded` may already exist in the file — reuse it.)

Tests:

```js
  test("a pasted price and reason on one row send one PATCH with both; two rows send two, in order", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow, { ...projectRow, itemId: "i2", itemName: "High bay fixture" }], marketJob: null }),
      setMaterialPrice: vi.fn((itemId, next) => Promise.resolve({ ...projectRow, itemId, itemName: itemId === "i1" ? projectRow.itemName : "High bay fixture", unitPrice: next.priceOverride, source: next.source, reason: next.reason })),
    };
    const review = renderMaterial({ store });
    await loaded(/20A duplex receptacle/);
    // Columns from Unit price: Unit price, Range (read-only), Basis, Reason
    // -- so the clip carries an empty second column.
    fireEvent.paste(cellFor("20A duplex receptacle", "Unit price"), pasteEvent("9\t\tProject price\tquote A\n8\t\tProject price\tquote B"));
    await waitFor(() => expect(store.setMaterialPrice).toHaveBeenCalledTimes(2));
    expect(store.setMaterialPrice.mock.calls).toEqual([
      ["i1", { priceOverride: 9, source: "project_price", reason: "quote A" }],
      ["i2", { priceOverride: 8, source: "project_price", reason: "quote B" }],
    ]);
    await waitFor(() => expect(review.showToast).toHaveBeenCalledWith("Pasted 4 cells on 2 rows"));
    expect(cellFor("High bay fixture", "Line total")).toHaveTextContent("$80.00");
  });

  test("a pasted empty price on an entry clears it; a pasted basis on a row with no entry sends nothing", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow, { ...companyRow, itemId: "i2", itemName: "High bay fixture" }], marketJob: null }),
      setMaterialPrice: vi.fn(),
      clearMaterialPrice: vi.fn().mockResolvedValue({ ...companyRow, sourceLabel: "Company price" }),
    };
    const review = renderMaterial({ store });
    await loaded(/20A duplex receptacle/);
    // Row 1: an empty price on an entry. Row 2: nothing on price or range,
    // "Allowance" on Basis -- disabled there, since the row has no entry.
    fireEvent.paste(cellFor("20A duplex receptacle", "Unit price"), pasteEvent("\n\t\tAllowance"));
    await waitFor(() => expect(store.clearMaterialPrice).toHaveBeenCalledWith("i1"));
    expect(store.setMaterialPrice).not.toHaveBeenCalled();
    await waitFor(() => expect(review.showToast).toHaveBeenCalledWith("Pasted 1 cell on 1 row"));
  });

  test("a paste that makes a row an allowance without a reason skips that row and says so", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow, { ...projectRow, itemId: "i2", itemName: "High bay fixture" }], marketJob: null }),
      setMaterialPrice: vi.fn((itemId, next) => Promise.resolve({ ...projectRow, itemId, itemName: "High bay fixture", unitPrice: next.priceOverride, source: next.source, reason: next.reason, sourceLabel: "Allowance" })),
    };
    const review = renderMaterial({ store });
    await loaded(/20A duplex receptacle/);
    fireEvent.paste(cellFor("20A duplex receptacle", "Basis"), pasteEvent("Allowance\t\nAllowance\tstand-in"));
    await waitFor(() => expect(store.setMaterialPrice).toHaveBeenCalledTimes(1));
    expect(store.setMaterialPrice).toHaveBeenCalledWith("i2", { priceOverride: 15.5, source: "allowance", reason: "stand-in" });
    expect(cellFor("20A duplex receptacle", "Basis")).toHaveTextContent("Project price"); // restored
    await waitFor(() =>
      expect(review.showToast).toHaveBeenCalledWith("Pasted 2 cells on 1 row — 1 row skipped, an allowance needs a reason"),
    );
  });

  test("clicking the market evidence summary does not make its cell active", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [marketRow], marketJob: null }),
    };
    renderMaterial({ store });
    await loaded(/2x4 LED troffer/);
    const summary = screen.getByText("Sellers");
    fireEvent.click(summary);
    expect(summary.closest("[role='rowheader']")).not.toHaveAttribute("data-active");
  });
```

(`marketRow` already exists in the file for the evidence tests.)

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- --run src/components/pricing/MaterialPricingWorkspace.test.jsx`
Expected: FAIL — the four new tests.

- [ ] **Step 3: Columns**

In `src/components/pricing/pricingColumns.jsx` import `STATUS, STATUS_ORDER` from `"../../lib/vocabulary.js"` and add:

```js
  status:   text: (row) => STATUS[row.status]?.label ?? "", sortValue: (row) => STATUS_ORDER.indexOf(row.status)
  itemName: text: (row) => row.itemName, sortValue: (row) => row.itemName
  range:    text: (row) => (row.priceLow != null && row.priceHigh != null ? `${row.priceLow}–${row.priceHigh}` : ""), sortValue: (row) => row.priceLow ?? null
  source:   text: (row) => row.sourceLabel ?? "", sortValue: (row) => row.sourceLabel ?? null
  lineTotal: text: (row) => (row.unitPrice != null ? String(Number(row.quantity) * Number(row.unitPrice)) : ""), sortValue: (row) => (row.unitPrice != null ? Number(row.quantity) * Number(row.unitPrice) : null)
```

(Add each as properties on the existing column objects.)

- [ ] **Step 4: The workspace**

In `MaterialPricingWorkspace.jsx`:

Imports `rangeFailure, rangeToast` and `useUndoCount` as in Task 11; destructure `redo`; `const undoCount = useUndoCount({ undo, load, showToast });` after `load`. In `send`, before `showToast(...)`: `undoCount.remember({ calls: 1, cells: 1 });`.

Add:

```js
  // A range lands as one call per row, because the PATCH is already the
  // trio (docs/specs/spreadsheet-grid.md, "What the screens do with a
  // range → Material"). Changes are grouped by row and folded over the
  // row's state; a row whose result would be an allowance with no
  // reason is skipped and counted, since a range cannot ask forty
  // questions the way the single-cell flow asks one.
  const commitRange = async (changes, { kind }) => {
    setSaveError(null);
    const groups = new Map();
    for (const c of changes) {
      if (!groups.has(c.row.itemId)) groups.set(c.row.itemId, { row: c.row, changes: [] });
      groups.get(c.row.itemId).changes.push(c);
    }
    setRows((cur) =>
      cur.map((r) => {
        const g = groups.get(r.itemId);
        if (!g) return r;
        const next = { ...r, pendingSource: undefined };
        for (const c of g.changes) next[c.key] = c.value;
        return next;
      }),
    );
    const restore = (row) =>
      setRows((cur) =>
        cur.map((r) => (r.itemId === row.itemId ? { ...r, unitPrice: row.unitPrice, source: row.source, reason: row.reason, pendingSource: undefined } : r)),
      );
    let calls = 0;
    let cells = 0;
    let failedCells = 0;
    let skipped = 0;
    for (const { row, changes: mine } of groups.values()) {
      const merged = { ...row };
      for (const c of mine) merged[c.key] = c.value;
      const hasEntry = row.source != null;
      let request;
      if (merged.unitPrice == null) {
        if (!hasEntry) { restore(row); continue; }
        request = () => store.clearMaterialPrice(row.itemId);
      } else if (!hasEntry && !mine.some((c) => c.key === "unitPrice")) {
        restore(row);
        continue;
      } else {
        const next = { priceOverride: merged.unitPrice, source: merged.source || "project_price", reason: merged.reason || "" };
        if (next.source === "allowance" && !next.reason.trim()) {
          skipped += 1;
          restore(row);
          continue;
        }
        request = () => store.setMaterialPrice(row.itemId, next);
      }
      try {
        const updated = await runMutation(request);
        replaceRow(row.itemId, updated);
        calls += 1;
        cells += mine.length;
      } catch {
        restore(row);
        failedCells += mine.length;
      }
    }
    if (failedCells) setSaveError(rangeFailure(failedCells, changes.length));
    if (calls) {
      undoCount.remember({ calls, cells });
      showToast(rangeToast(kind, cells, calls, { skipped, skippedWhy: "an allowance needs a reason" }));
    }
  };
```

Pass `onCommitRange={commitRange}`, `onUndo`, `onRedo` to the grid exactly as in Task 11, and switch the toast button to `undoCount.undoLast()` as in Task 11.

- [ ] **Step 5: Run the pricing tests**

Run: `npm test -- --run src/components/pricing`
Expected: PASS — including the unchanged "Tab from inside the market evidence details is not hijacked back onto the grid" and the `PriceSheetImport` tests.

- [ ] **Step 6: Commit**

```bash
git add src/components/pricing/pricingColumns.jsx src/components/pricing/MaterialPricingWorkspace.jsx src/components/pricing/MaterialPricingWorkspace.test.jsx
git commit -m "Material pricing: a range lands as one call per row, allowance rows without a reason skipped and counted

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Whole-suite verification, a look in the browser, and the spec's final state

**Files:**
- Modify: `docs/specs/spreadsheet-grid.md` (only if something was found), `docs/specs/pricing-grid.md`

- [ ] **Step 1: Full suite and build**

Run: `npm test -- --run`
Expected: all green. Then `npm run build` — clean.

- [ ] **Step 2: Try it in the browser**

Start the dev server on this stream's port through the browser tool (`.claude/launch.json` entry `"grid-b"`: `npm`, `["run", "dev", "--", "--port", "5174"]`, port 5174). The backend is the shared `docker compose` stack in the main checkout — if the API at `http://localhost:8000` is not up, ask the user to start it rather than starting one here. Sign in, open a project with material rows, and check on Material pricing:

1. Arrow onto the Material cell and the Status cell; the ring moves, no editor opens.
2. Shift+ArrowDown twice on Unit price: three cells washed blue, one ring.
3. Cmd/Ctrl+C, then paste into a text editor: three lines of raw numbers.
4. Type `1\t2\t3` in a text editor, copy, Cmd/Ctrl+V on Unit price: three PATCHes, one toast "Pasted 3 cells on 3 rows", Saving… → Saved; Undo reverses all three.
5. Drag the fill handle down two rows; toast "Filled 2 cells on 2 rows".
6. Click the Status header: Missing information rows first; click twice more to clear.
7. Drag the Material header's right edge: only that column widens.
8. Open a row's "Sellers" details and Tab through its links: focus stays in the details.

Take a screenshot of the washed range and the sort arrow and share it. If step 4's paste event does not fire in the browser, the fallback is a hidden `<textarea>` — stop and report rather than improvising.

- [ ] **Step 3: Update `pricing-grid.md`'s arrow rule**

In `docs/specs/pricing-grid.md` under "Cell states → Active", the key table row `| ← → ↑ ↓ | one editable cell in that direction; ↑/↓ stay in the column |` becomes `| ← → ↑ ↓ | one cell in that direction, any column — see spreadsheet-grid.md |`, and the sentence "Only editable cells participate. On the labor screen Tab walks…" keeps its Tab half and drops "Only editable cells participate."

- [ ] **Step 4: Commit**

```bash
git add docs/specs/pricing-grid.md docs/specs/spreadsheet-grid.md .claude/launch.json
git commit -m "Spreadsheet grid: the arrow rule in the cell spec points at the new one; launch entry for the stream's dev server

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Only add `.claude/launch.json` if it was created in this worktree and is not gitignored; otherwise leave it out of the commit.

---

## Self-review against the spec

- Selection (model, movement table, arrows over every cell, Tab entry flow, read-only clicks, nested-interactive guard, markup, wash + ring): Tasks 1, 4, 9.
- Copy (raw values, `text`, TSV, both event and keydown path): Tasks 2, 5, 11, 12.
- Paste (1×1 fill, anchoring, per-cell rules, skips): Tasks 2, 5.
- Fill (Ctrl+D, handle, repeat, target marking, selection after): Tasks 2, 5, 6.
- Clear over a range: Tasks 2, 5.
- Screens (local-first, sequential, per-cell / per-row, failure count, allowance skip, toast copy, N-fold undo, Ctrl+Z): Tasks 10, 11, 12.
- Sort (button, `aria-sort`, comparator, `sortValue` per column, reorder once): Tasks 3, 7, 11, 12.
- Resize (handle, snapshot, `colgroup`, fixed layout, floor, no sort on drag): Task 8.
- Styles: Task 9.
- Bulk endpoint follow-up: recorded in the spec, no task (by design).
