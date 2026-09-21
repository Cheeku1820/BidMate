# The spreadsheet grid: ranges, clipboard, fill, sort, and resize

Date: 2026-09-21. Stream B of
[`docs/roadmap/workstreams-2026-09.md`](../roadmap/workstreams-2026-09.md).
Extends [`pricing-grid.md`](pricing-grid.md), which remains the design
of the cell — idle / active / editing, validation, clearing, the
allowance-reason flow, save state and the toast. This spec adds what
that one deliberately left out: everything that acts on more than one
cell at a time, and the two header behaviours.

## Scope

The Labor and Material pricing workspaces should feel like Google
Sheets. An estimator with four hundred rows types a rate once and
fills it down, pastes a column of supplier prices copied out of a
spreadsheet, selects a block and clears it, sorts by status to find
what is left, and drags a column wider to read a reason. None of that
exists today: the grid edits one cell at a time.

**Decision: extend `DataGrid`, no dependency.** The roadmap suggested
adopting `react-data-grid` or Glide Data Grid. Read against what the
cells contain, neither fits: `react-data-grid` has no range selection
(the hard part) and fixed row heights, and Glide renders to canvas, so
every Pill, tier tag, four-field warning, and the seller `<details>` in
the Material cell would become custom drawing and the nested-interactive
regression test could not exist. The risks a hand-rolled grid carries —
virtualization, thousands of columns — do not apply to a table with one
row per catalog item and eleven columns.

**In scope**

- Range selection by Shift+arrow and Shift+click; select all; Escape.
- Copy and paste of a rectangular block as tab-separated text, so it
  round-trips with Sheets.
- Fill down: Ctrl/Cmd+D, and a fill handle dragged downward.
- Delete or Backspace over a range clears every entry in it.
- Column resize by dragging a header edge.
- Sort by clicking a header.
- Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z on the grid.
- Every range operation lands as one existing store call per cell (per
  row for the Material trio), so each is its own undoable action, and
  the toast's Undo reverses the whole operation by reversing them all.

**Deliberately out of scope**

- Virtualization. Hundreds of rows in a `<table>` are fine; revisit at
  the 300-sheet scale, per `BUILD-STAGES.md`.
- Freezing columns. The header is already sticky; the first two
  columns are not, and are not made so here.
- Multi-column sort, filter chips, column reorder, hiding columns.
- Screen G (`TakeoffSpreadsheet.jsx`) stays on its own table.
- A bulk-action API. See "The undo of a range operation" — the
  follow-up is written down for the coordinator, not built here.
- A keyboard path for column resize. Resize is a convenience over the
  browser's own layout, not a way to reach anything; noted as a known
  accessibility gap rather than left unsaid.

## Files

```
src/components/grid/
  DataGrid.jsx              the component: cells, editors, now selection, clipboard, fill, sort, resize
  useGridNavigation.js      the active cell and single-cell movement: arrows over every cell, Tab over editable ones
  useGridSelection.js       NEW — pure functions: ranges, TSV, paste/fill/clear mapping, sort
  DataGrid.test.jsx
  useGridNavigation.test.js
  useGridSelection.test.js  NEW
src/components/labor/
  LaborWorkspace.jsx        implements onCommitRange: one PATCH per cell, sequential
  laborColumns.jsx          gains `text` and `sortValue` on read-only columns
src/components/pricing/
  MaterialPricingWorkspace.jsx   implements onCommitRange: one PATCH or DELETE per row
  pricingColumns.jsx             gains `text` and `sortValue`
src/styles.css              appended block under /* ==== stream B: grid ==== */
```

`useGridSelection.js` is the same shape as `useGridNavigation.js`: the
rules are pure functions over `(columns, rows)` and plain selection
objects, tested on plain data; the hook underneath is thin. Nothing in
it touches the DOM.

## Selection

### Model

```js
selection = { anchor: { row, col }, focus: { row, col } }
```

`row` is an index into the displayed rows, `col` an index into
`columns` — **all** columns, read-only ones included. The **focus** is
the active cell: it carries `tabindex="0"`, `data-active`, and the
focus ring, exactly as `active` does today. When anchor and focus are
the same cell the selection is that one cell, which is the state every
existing behaviour was written for.

`normalize(selection)` returns `{ r0, c0, r1, c1 }`, inclusive, with
`r0 ≤ r1` and `c0 ≤ c1`. Every range operation reads the normalized
rectangle.

### How it moves

| Gesture | Anchor | Focus |
|---|---|---|
| Click a cell | that cell | that cell |
| Arrow | the neighbouring cell in that direction, any column | same |
| Home / End | the row's first / last cell, any column | same |
| Tab / Shift+Tab, Enter/Tab out of an editor | the next cell in the entry flow (below) | same |
| Shift+arrow | unchanged | one cell in that direction, clamped to the grid |
| Shift+click | unchanged | the clicked cell |
| Ctrl/Cmd+A | first cell of the first row | last cell of the last row |
| Escape (not editing) | the focus | the focus |
| Any commit, sort, or reload | collapses to the focus | |

**Arrows visit every cell, as in Sheets.** ← → ↑ ↓ move one cell in
that direction over every column, read-only ones included, clamped at
the grid's edges; Home and End go to the row's first and last cell.
This replaces `pricing-grid.md`'s rule that arrows step over read-only
columns. An estimator can arrow onto Item to read a basis note, onto
Status, onto a line total — and copy any of them.

**Tab is the entry flow, and it is unchanged.** Tab / Shift+Tab still
walk editable cells only — hours → rate → adjustment → reason → next
row's hours — wrapping at row ends and leaving the grid past the last
editable cell, exactly as `pricing-grid.md` fixed them. Enter in an
editor still commits and moves **down** one row in the same column;
Tab in an editor still commits and moves to the next editable cell.
Typing a column of rates is Enter-Enter-Enter; typing a row is
Tab-Tab-Tab; neither lands on a cell that cannot take the value.

In `useGridNavigation.js` this is the split between the two kinds of
move: `left / right / up / down / home / end` move over all cells and
never return `null`, `next / prev` move over editable cells and return
`null` past the grid's ends (the one case Tab is allowed to leave).
Enter and F2, a printable character, Space on a select, Delete and
Backspace do nothing on a read-only cell; a second click on it does
nothing. The Clear `×` never renders on one.

### Clicking read-only cells

Any cell can be the active cell by click as well as by arrow. A click
whose target is inside interactive content within the
cell — the same `a, button, summary, input, select, textarea,
[contenteditable]` set the key handler already guards — does **not**
activate the cell or move focus: the seller `<details>` opens and closes
on its own, and its link is a link. This is what keeps the "Tab from
inside the market evidence details is not hijacked" regression test in
`MaterialPricingWorkspace.test.jsx` green.

### Markup and visuals

- The table carries `aria-multiselectable="true"`.
- Every cell in the normalized range carries `aria-selected="true"`.
  The focus cell additionally carries `data-active`. (Today
  `aria-selected` marks only the active cell; the existing test
  "exactly one `aria-selected` cell" becomes "exactly one `data-active`
  cell, and `aria-selected` on every cell in the range".)
- **The ring stays on the focus cell only.** The existing rule
  `.grid [aria-selected="true"]` draws the ring; the appended block
  overrides it for range cells that are not the focus:
  `.grid [aria-selected="true"]:not([data-active]) { box-shadow: none;
  background: var(--grid-range); }`. `--grid-range` is a new token, a
  light wash of `--blue`. Blue is the selection colour everywhere else
  in the product; it is never a status fill, and no other colour is
  introduced.
- The fill handle (below) renders in the range's bottom-right cell.
- The Clear `×` button renders only when the selection is a single
  cell with an entry, as today; over a range, Delete is the path.

## Range operations

### The one rule

Every range operation produces a list of **changes**:

```js
changes = [{ row, key, value }]   // row: the row object; key: column key; value or null
```

in row-major order, and hands it to the screen through a new optional
prop:

```js
<DataGrid … onCommit={commit} onCommitRange={commitRange} />
// onCommitRange(changes, { kind })   kind: "paste" | "fill" | "clear"
```

The grid also takes `onUndo` and `onRedo`, called by Ctrl/Cmd+Z and
Ctrl/Cmd+Shift+Z on a cell; the screens pass the context's `undo` and
`redo` wrapped with their own reload.

A single-cell edit — typing, Enter, a select change, Delete on one
cell, the Clear button — still calls `onCommit(row, key, value)` exactly
as today, with today's toast. `onCommitRange` fires only for a paste, a
fill, or a clear over a range, and only when the list is non-empty. A
grid rendered without `onCommitRange` sends each change through
`onCommit` in order — the screens here both implement the range prop,
so the fallback exists for the next screen, not these.

The grid never sends a change that does nothing: a cell that is
read-only for its row, a value that fails the column's validation, a
value equal to what the cell holds, an empty value on a cell with no
entry — each is **skipped**, silently, and never blocks its neighbours.
This is what makes pasting a whole column copied out of Sheets over a
grid with a few read-only rows work without ceremony.

### Copy

Ctrl/Cmd+C on the grid (focus on a cell, no editor open) copies the
normalized range as tab-separated text, one line per row, `\n`
between lines and no trailing newline. The cell text:

```js
column.text ? column.text(row)
: column.edit ? String(column.edit.value(row) ?? "")
: typeof row[column.key] === "string" || typeof row[column.key] === "number" ? String(row[column.key])
: ""
```

Editable cells copy their **raw** value — `62`, not `$62.00/hr`;
`0.75`, not `0.750` — so a block pasted into Sheets is numbers, and a
block pasted back is the same numbers. Read-only columns whose cell is
not a primitive supply `text`: Status copies the label from
`vocabulary.js` (`Ready to review`), the tier columns copy the tier
label, Item copies the name without the basis note. A `<details>` or a
warning never copies; the row's name does.

The grid handles the `copy` event on the table
(`event.clipboardData.setData("text/plain", tsv)` and
`preventDefault()`), which is what the test suite fires. Because
browsers differ on whether Ctrl/Cmd+C fires `copy` on a focused
non-editable element with no text selection, the cell's keydown handler
also writes the same text through `navigator.clipboard.writeText` when
that API exists. Both may run; they write the same text.

### Paste

Ctrl/Cmd+V on the grid is the `paste` event on the table (`paste` fires
on the focused element in every current browser). The text is split on
`\n` (a trailing `\r` on each line dropped, a trailing empty line
dropped), each line on `\t`. A single value with no tab or newline is a
1×1 clip.

Where it lands:

- **A 1×1 clip over a range of any size fills the range** with that
  value — the Sheets gesture for "set all of these to this".
- **Otherwise the clip anchors at the range's top-left** (`r0, c0`) and
  extends down and right by its own size, clamped to the grid. The
  range's other cells do not matter.

Per target cell, the pasted string becomes a change or a skip:

| Column | Pasted text | Result |
|---|---|---|
| read-only, or `edit.disabled(row)` | anything | skip |
| any editable | empty | `null` if `edit.hasEntry(row)`, else skip |
| number | `$1,234.50`, ` 62 `, `+25%`, `−3%` | leniently parsed: `$`, `,`, `%`, whitespace stripped, Unicode minus → `-`; then the column's own `min` check |
| number | anything that does not parse, or below `min` | skip |
| select | an option's `value` or `label`, case-insensitive | that option's value |
| select | anything else | skip |
| text | the text, trimmed | the text |
| any | equal to the cell's current value | skip |

The empty-value rule means pasting a blank over an entry clears it,
matching what typing nothing and leaving does. `edit.required(row)` —
the allowance reason — is not checked by the grid: the Material screen
handles that row (below).

### Fill

Two gestures, one result:

- **Ctrl/Cmd+D** on a range of two or more rows: each column's top cell
  (`r0`) is written into every row below it in the range. On a
  single-cell selection it does nothing (there is no "cell above" rule;
  select the range first, as in Sheets).
- **The fill handle**: a 7px square at the bottom-right corner of the
  range's bottom-right cell. Mousedown on it, drag downward over rows,
  mouseup. While dragging, the cells the fill would write carry
  `data-fill-target` (a dashed outline in `--ink-3`). On release, the
  **source** is the original range's rows and the **target** is every
  row dragged past `r1`; source rows repeat in order down the target
  (one source row → the same value everywhere; two → alternating, as
  Sheets does with a two-row pattern). Dragging upward or not past `r1`
  does nothing. After the fill, the selection extends to cover source
  and target.

Both produce changes through the paste rules above, with the source
cell's raw value as the "pasted text": read-only targets, disabled
targets, and unchanged cells are skipped. A source cell with no value
(`—`) writes `null` to targets that have an entry — filling down an
empty cell clears, as in Sheets.

### Clear

Delete or Backspace with a range of two or more cells selected produces
a `null` change for every cell in the range where `edit.hasEntry(row)`
is true; everything else is skipped. On a single cell the existing
`clear(row, column)` → `onCommit(row, key, null)` path runs unchanged.
`kind` is `"clear"`.

### What the screens do with a range

Both screens apply every change to local state **first** — the footer
total and each row move at once — then send, one call at a time, in
order, awaiting each. A response replaces its row as today. A failed
call restores the fields it touched on that row (the same "only the
edited fields, on the row as it is now" rule the single-cell path uses)
and the run **continues**; at the end, if anything failed, the existing
banner says "3 of 40 cells couldn't be saved. Try again." — the count,
never a bare failure. Each call goes through `runMutation`, so the top
bar reads `Saving…` across the run and `Saved` after it.

**Labor.** Every change is its own `store.setLaborLine(itemId, { [wire]:
value })`, exactly as one cell commits today: `null` for the numeric
fields, `""` for a cleared reason. Forty changes are forty PATCHes and
forty actions.

**Material.** The PATCH is already the trio, so changes are **grouped by
row** and each row becomes one call, in row order:

1. Fold the row's changes over its current state into `{ priceOverride,
   source, reason }`, as the single-cell `commit` does today.
2. If `unitPrice` ends `null`: `store.clearMaterialPrice(itemId)` if the
   row has an entry, else skip the row.
3. If the row has no entry and no price is in the changes — only a
   basis or reason was pasted — skip: there is no entry to put them on.
4. If the result is `source: "allowance"` with an empty reason, skip the
   row and count it. The single-cell flow opens the Reason editor with
   a message; a range operation cannot ask forty questions, so the row
   is left as it was and the toast says how many were skipped and why.
5. Otherwise `store.setMaterialPrice(itemId, next)`.

A skipped row (2–4) is restored locally to its pre-operation values, so
the screen never shows a state the server did not accept.

### The toast, and the undo of a range operation

One toast per operation, in the estimator's words, counting what
actually landed:

- paste: "Pasted 40 cells on 20 rows"
- fill: "Filled 12 cells on 12 rows"
- clear: "Cleared 8 cells on 4 rows"
- Material, with allowance rows skipped: "Pasted 38 cells on 19 rows —
  2 rows skipped, an allowance needs a reason"

Singular forms when the count is one. For Material, "cells" counts the
cells the estimator changed (the folded trio counts as the cells that
differed), "rows" the calls made. When nothing lands — every cell
skipped — no call is made and no toast shows; the grid's selection
simply stays.

**Undo reverses the whole operation.** The toast's Undo calls the
context's `undo()` once per successful call, newest first, stopping
early if a call reports `performed: false`, then reloads the rows and
shows "Reversed 40 cells" (the per-undo toasts `useReviewStore.undo`
emits are overwritten by this final one). The screen keeps the count in
a ref set alongside `showToast`; a single-cell commit sets it to 1, so
the existing single-cell Undo is the same code path with N = 1.
Ctrl/Cmd+Z on the grid reverses **one** action, as the top bar's undo
button does — one press, one step, the way the shared stack works
everywhere else.

**The honest limit, for the coordinator.** Forty PATCHes are forty
entries on the project's shared, linear undo stack. If a colleague's
action lands between two of them, the toast's Undo reverses that action
too — the existing shared-undo behaviour (`CLAUDE.md`, open decisions),
N-fold. The right fix is a **bulk action**: one `actions` row whose
`before`/`after` carry N row snapshots, applied and reversed by
`undo_apply` in one step, exposed as `POST
/api/projects/{id}/labor/bulk` and `.../material-prices/bulk`. That is
an API change and this stream does not touch the API; it is recorded
here as the follow-up that makes the toast's Undo exactly one action.
Nothing in the client changes shape when it lands: `onCommitRange`
already hands the screen the whole list.

## Headers

### Sort

Each `<th scope="col">` wraps its label in a `<button type="button"
class="grid-sort">`. Clicking cycles **ascending → descending → off**;
the `<th>` carries `aria-sort="ascending" | "descending"` (absent when
off) and the button shows a small `ArrowUp` / `ArrowDown` from
`lucide-react` next to the label, `aria-hidden`. The button's accessible
name is the label; the state is on the header.

The comparator reads `column.sortValue(row)` when present, else
`column.edit.value(row)` for an editable column, else `row[column.key]`.
Numbers compare numerically, strings with `localeCompare`, `null` /
`undefined` / `""` sort last in both directions; the sort is stable, so
ties keep their load order. Column-supplied values:

- Status: the index into `STATUS_ORDER` from `vocabulary.js`, so
  ascending puts *Missing information* first — what is left to do — and
  *Estimator approved* last.
- Item / Material: the name.
- Tier and source columns: the label.
- Line total: `quantity × unitPrice`, `null` when unpriced.

**Sorting reorders once.** The grid keeps `order` — an array of row keys
— in state, recomputed only when the sort changes, when the set of row
keys changes (a reload, an applied price sheet), or when the sort is
cleared (back to load order). A cell edit that changes the sorted
column's value does **not** move its row until the header is clicked
again: rows jumping under an estimator mid-Tab is the failure mode this
avoids, and it is how Sheets behaves. The header keeps showing the
direction that was applied. Rows in `rows` but not in `order` (added
since) render at the end.

Selection, the active cell, and every range operation work in
**displayed** row indices. `onCommit` and `onCommitRange` pass row
objects, so the screens are unaffected by order.

### Resize

A `<div class="grid-resize" role="presentation">` sits at each header's
right edge, 8px wide, `cursor: col-resize`. Mousedown on it starts a
drag; `mousemove` on the document sets that column's width to its
starting width plus the pointer's travel, floor 60px; `mouseup` ends
it. A mousedown on the handle never starts a sort, and a click on the
sort button never starts a resize (the handle sits outside the button).

On the **first** resize the grid snapshots every column's current
`offsetWidth` into `widths` (keyed by column key), renders a
`<colgroup>` with those widths, and sets the table to `table-layout:
fixed` with `width` equal to their sum — so the browser's auto layout
decides the initial widths and the estimator's drag adjusts one column
without the others reflowing. Widths are component state: they last for
the visit and are not persisted.

Text in a narrowed cell wraps, as it does today; nothing is clipped.
There is no keyboard path for resize (see scope).

## Keys on the grid, complete

Read with `pricing-grid.md`'s table. Handled on the active cell when no
editor is open; the nested-interactive guard runs first, as today.

| Key | Does |
|---|---|
| ← → ↑ ↓, Home / End | move the active cell one step over every column; collapse the selection |
| Shift + ← → ↑ ↓ | extend the selection by one cell, over every column |
| Tab / Shift+Tab | next / previous editable cell, as today; collapse the selection |
| Enter, F2, printable, Space on a select | open the editor on the active cell; the selection collapses to it |
| Delete / Backspace | single cell: clear it (as today); range: clear every entry in it |
| Ctrl/Cmd+C | copy the range as TSV |
| Ctrl/Cmd+V | paste (the `paste` event) |
| Ctrl/Cmd+D | fill down within the range |
| Ctrl/Cmd+A | select every cell |
| Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z | `undo()` / `redo()` from the context, then reload |
| Escape | collapse the selection to the active cell |

Inside an editor nothing changes: Ctrl/Cmd+Z there is the browser's own
text undo, and Ctrl/Cmd+C/V act on the input's text.

Modifier keys never open an editor: the existing "printable character
starts an edit" rule already excludes `ctrlKey`/`metaKey`/`altKey`.

## Styling

Appended to `styles.css` under `/* ==== stream B: grid ==== */`; no
existing rule is edited. Tokens only:

- `--grid-range`: `color-mix(in srgb, var(--blue) 12%, transparent)`,
  declared in the same block (a token added at the end rather than at
  the top, per the shared-file rule; the coordinator may move it).
- `.grid [aria-selected="true"]:not([data-active])` — no ring, the
  wash. `.grid [data-active]` — the existing ring, restated here so the
  focus cell keeps it regardless of rule order.
- `.grid-fill-handle` — 7px square, `--blue`, at the cell's bottom-right
  inside edge, `cursor: crosshair`.
- `.grid td[data-fill-target]` — `outline: 1px dashed var(--ink-3);
  outline-offset: -3px`.
- `.grid-sort` — an unstyled button inheriting the header's font, the
  standard focus ring, `cursor: pointer`; its icon 12px, `--ink-2`.
- `.grid-resize` — 8px wide, absolutely positioned at the header's
  right edge, full height, `cursor: col-resize`; `.grid.is-resizing`
  sets `user-select: none` on the table.

## Testing

**`useGridSelection.test.js`** — pure functions on plain columns and
rows:

- `normalize` orders any anchor/focus pair; `extend` moves the focus one
  cell in each direction over all columns and clamps at the edges;
  `selectAll` covers the grid
- `toTsv` copies raw editable values, `text()` for read-only columns,
  an empty string for a non-primitive read-only cell, no trailing
  newline
- `parseClipboard` handles `\r\n`, a trailing newline, a single value,
  an empty cell in the middle of a line
- `pasteChanges`: 1×1 over a range fills it; a block anchors at the
  top-left and clamps; read-only and disabled targets are skipped;
  `$1,234.50`, `+25%`, `−3%` parse; text below `min` and non-numbers
  are skipped; a select matches value or label case-insensitively;
  empty clears only with `hasEntry`; unchanged values are skipped;
  output is row-major
- `fillChanges`: top row repeats down the range; a two-row source
  alternates over a drag target; an empty source writes `null` to
  entries only
- `clearChanges`: `null` for every `hasEntry` cell, nothing else
- `sortRows`: numeric and string, nulls last both ways, stable ties,
  `sortValue` wins over the default

**`useGridNavigation.test.js`** — the arrow cases now assert movement
over every column and clamping at the edges; `next`/`prev` cases are
unchanged.

**`DataGrid.test.jsx`** — existing tests updated for `data-active` (one
per grid), `aria-selected` on the range, and arrows that no longer skip
read-only cells, plus:

- ArrowRight from an editable cell lands on the read-only cell beside
  it; arrows clamp at the grid's edges; Home/End reach the row's first
  and last cell; Tab from that read-only cell goes to the next editable
  cell; Enter, a printable key, and Delete on a read-only cell do
  nothing and open no editor
- Shift+ArrowRight from an editable cell selects two cells including a
  read-only one; Shift+click extends; a plain arrow collapses; Escape
  collapses; Ctrl+A covers the grid
- clicking a read-only cell makes it active without an editor;
  clicking a link or summary inside a cell does not move focus or
  activate
- `copy` on the table sets `text/plain` TSV of the range and calls
  `preventDefault`
- `paste` on the table with a two-line TSV calls `onCommitRange` with
  the mapped changes and `{ kind: "paste" }`, and does not call
  `onCommit`; a paste with nothing applicable calls neither
- `paste` while an editor is open does nothing to the grid
- Ctrl+D over a range calls `onCommitRange` with `{ kind: "fill" }`; on
  a single cell calls nothing
- the fill handle renders only on the range's bottom-right cell;
  mousedown, mouseenter on a lower row, mouseup calls `onCommitRange`
  with the repeated values and extends the selection; releasing on the
  same row calls nothing
- Delete over a range calls `onCommitRange` with `{ kind: "clear" }`;
  on a single cell still calls `onCommit(row, key, null)`
- without `onCommitRange`, a paste calls `onCommit` once per change, in
  order
- a header click sets `aria-sort="ascending"`, reorders the rows,
  second click descending, third clears; editing a sorted cell does not
  move its row; a new `rows` array with the same keys keeps the order,
  with a new key appends it
- mousedown on a resize handle, mousemove +40px, mouseup sets that
  `<col>`'s width to start + 40 and the table to fixed layout; the
  floor is 60px; mousedown on the handle does not sort
- Ctrl+Z on a cell calls `onUndo`; Ctrl+Shift+Z calls `onRedo`; neither
  fires inside an editor
- the nested-interactive Tab guard still holds with a selection active

**`LaborWorkspace.test.jsx`** plus:

- a paste of two rows × two columns calls `setLaborLine` four times, in
  row-major order, one field each, sequentially (the second call starts
  after the first resolves); rows update locally before the first
  response and from each response after
- a failed second call restores that cell, the other three land, and
  the banner reads "1 of 4 cells couldn't be saved. Try again."
- the toast reads "Pasted 4 cells on 2 rows"; its Undo calls `undo()`
  four times, then reloads, then shows "Reversed 4 cells"; a single-cell
  commit's Undo still calls `undo()` once
- Ctrl+Z on a cell calls `undo()` once and reloads

**`MaterialPricingWorkspace.test.jsx`** plus:

- a paste of price and reason on one row sends **one** `setMaterialPrice`
  with both; on two rows, two calls in order
- a pasted empty price on a row with an entry sends `clearMaterialPrice`;
  a pasted basis on a row with no entry sends nothing
- a paste that makes a row an allowance with an empty reason skips that
  row, restores it, and the toast says "— 1 row skipped, an allowance
  needs a reason"
- the existing "Tab from inside the market evidence details is not
  hijacked" test stays exactly as it is and passes; a new one clicks
  the summary and asserts the cell did not become active

**Kept from `pricing-grid.md`:** every existing test not named above
stays green unchanged, the allowance-reason single-cell flow included.

## Not built in this slice

- **The bulk action endpoint**, so the toast's Undo is one action
  rather than N. See "The undo of a range operation".
- **Frozen columns**, **column reorder**, **filters**, **multi-column
  sort**, **persisted widths and sort**.
- **Keyboard column resize.**
- **Virtualization.**
- **Screen G on the grid.**
