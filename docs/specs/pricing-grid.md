# The pricing grid: Labor and Material pricing as a spreadsheet

## Scope

The Labor and Material pricing workspaces
([`docs/specs/labor-material-pricing.md`](labor-material-pricing.md))
are the two places an estimator types numbers row after row. Today each
editable cell is a full form control — a bordered number input, and on
the material side a stacked checkbox and reason field inside the price
cell — and every blur triggers a PATCH followed by a refetch of the whole
table. It works, and it is nothing like the spreadsheet the estimator
left to come here.

This spec replaces both tables with **one shared editable grid** that
behaves the way a spreadsheet does at the cell level: cells look like
data until you edit them, the keyboard moves the active cell, typing
starts an edit, leaving a cell commits it. It also wires the two screens
into the save-state indicator and the undoable toast every other
workspace already shows, and adds a pinned totals row to each.

**In scope**

- `DataGrid`, a keyboard-navigable editable grid component, hand-built on
  the existing tokens. No new dependency.
- Labor: hours per unit, rate, **adjustment percent and reason** as
  editable cells. The last two are already accepted and stored by
  `PATCH /api/items/{id}/labor` and never surfaced; the row schema starts
  returning them.
- Material pricing: unit price, a **Basis** select (*Project price* /
  *Allowance*), and a **Reason** text cell replace the stacked checkbox.
  A computed line total column.
- A sticky footer row per screen summing adjusted hours and labor cost,
  or line totals, with an explicit caption for what is not in the sum.
- Save state (`Saving…` / `Saved 2:41 PM` / `Couldn't save — retrying`)
  in the top bar and the five-second undo toast, both through the
  mechanisms `useReviewStore` already has.
- Row-level optimistic update from the PATCH response instead of a
  full-table refetch.

**Deliberately out of scope**

- Crew mix and notes on a labor line (the API takes them; the grid does
  not show them yet).
- Multi-cell selection, fill-down, copy and paste, column resize, sort,
  filter chips. "Sheets-like" here means cell navigation and in-place
  editing, decided in brainstorming; the rest is a later slice.
- Screen G (`TakeoffSpreadsheet.jsx`) stays on its current table. The
  grid is built so it *could* move later, but this slice does not touch
  it.
- Company-level settings tabs (`CompanySettings.jsx`), unchanged.

## The grid

### Files

```
src/components/grid/
  DataGrid.jsx            <table role="grid">, cell rendering, editors
  useGridNavigation.js    active-cell state and the key handling
  DataGrid.test.jsx
```

`DataGrid` takes:

```js
<DataGrid
  columns={COLUMNS}          // see "Column definitions"
  rows={rows}                // plain objects
  rowKey={(row) => row.itemId}
  onCommit={(row, key, value) => ...}   // called once per changed cell
  footer={<tr>…</tr>}        // optional, rendered sticky at the bottom
  caption="Labor by item"    // visually hidden <caption>
/>
```

It owns no data. It renders what it is given, tells the screen when a
cell changed, and the screen decides what that means. The status column
and the source-tier tags are ordinary read-only columns whose `render`
returns the existing `Pill` and `.pill--neutral` markup — the grid never
invents a status treatment.

### Column definitions

`laborColumns.js` and `pricingColumns.js` keep their data-driven shape
(the header and the body read one list) and gain an optional `edit`
descriptor:

```js
{
  key: "rate",
  label: "Rate",
  align: "right",
  render: (row) => (row.rate != null ? money(row.rate) + "/hr" : NONE),
  edit: {
    kind: "number",           // "number" | "text" | "select"
    min: 0,                   // number only; validated on the cell
    value: (row) => row.rate, // what the editor opens with
    options: [...],           // select only: [{ value, label }]
    disabled: (row) => bool,  // optional: this cell is read-only on this row
  },
  header: true,               // optional: <th scope="row"> instead of <td>
}
```

A column with no `edit` is read-only and is skipped by keyboard
traversal.

### Cell states

Three states, matching a spreadsheet:

**Idle.** Every cell shows its `render` output — `$62.00/hr`, `0.75`,
`+25%`, `—`. Editable cells carry a thin right-edge mark in `--ink-3`
(a 2px inset border) so an estimator can tell what is typeable without
relying on colour, and a `cursor: text`. Read-only cells have neither.

**Active.** Exactly one cell in the grid is the focus target. It carries
`tabindex="0"` (every other cell `-1`), `aria-selected="true"`, and the
existing `--blue` focus ring. Keys:

| Key | Moves |
|---|---|
| ← → ↑ ↓ | one editable cell in that direction; ↑/↓ stay in the column |
| Tab / Shift+Tab | next / previous editable cell, wrapping to the next / previous row |
| Enter | opens the editor (see below); in an editor, commits and moves down |
| Home / End | first / last editable cell in the row |
| Any printable character | opens the editor with that character as the whole value |
| F2 | opens the editor with the current value, caret at the end |

Only editable cells participate. On the labor screen Tab walks
hours → rate → adjustment % → reason → next row's hours; Status, Item,
Quantity, the two source tags, Adj. hours and Labor cost are stepped
over. Tab out of the last editable cell of the last row leaves the grid.

Clicking any editable cell makes it active; double-click or a second
click on the active cell opens the editor.

**Editing.** The cell's content is replaced by an `<input>` (or
`<select>`) that fills the cell. The input inherits the cell's alignment
and `tabular` class, so the digits do not jump when the editor opens.

| Key | Does |
|---|---|
| Enter | commit, move down |
| Tab / Shift+Tab | commit, move right / left |
| Escape | discard, stay active, editor closes |
| Blur (click elsewhere) | commit |

`number` editors are `<input type="text" inputmode="decimal">`, not
`type="number"` — the spinner and the browser's own validation get in the
way of Tab-through entry, and the grid validates itself. `select`
editors are a native `<select>`: Space or Enter opens it, arrow keys
change it, a change commits at once. No custom dropdown.

A commit fires `onCommit` **only if the value changed** — Enter or Tab
through an untouched cell sends nothing.

### Validation on the cell

Invalid input keeps the editor open, does not commit, and renders a
one-line message directly under the cell (`role="alert"`, tied to the
input with `aria-describedby`):

- not a number → "Enter a number"
- below `min` → "Hours can't be negative" / "Rate can't be negative" /
  "Price can't be negative" / "Adjustment can't be below −100%" (the
  column supplies the copy through `edit.minMessage`)

Clearing a number cell to empty and leaving it is **not** a commit —
today's rule ("an estimator clearing the field is not a value to save")
carries over, because the API has no "unset this override" operation
and inventing one is out of scope.

### Accessibility

`<table role="grid">`, rows `role="row"`, cells `role="gridcell"`, the
item-name cell `<th scope="row">` exactly as `TakeoffSpreadsheet.jsx`
does. Roving tabindex as above. The visually hidden `<caption>` names
the grid. The editor input carries an `aria-label` of the column label
plus the row's item name ("Rate, 20A duplex receptacle"). Focus never
disappears: after a commit the active cell moves and receives focus
synchronously, before any network round-trip.

## The two screens

### Labor

| Column | Edit | Commits | Shown as |
|---|---|---|---|
| Status | — | | `Pill` |
| Item | — | | row header; `basisNote` as a muted second line |
| Quantity | — | | |
| Hours/unit | number, min 0 | `hoursOverride` | `0.750` or `—` |
| Hours source | — | | `.pill--neutral` tag |
| Rate | number, min 0 | `rateOverride` | `$62.00/hr` or `—` |
| Rate source | — | | `.pill--neutral` tag |
| Adjustment | number, min −100 | `adjustmentPercent` | `+25%`, `−3%`, or `—` |
| Adjustment reason | text | `adjustmentReason` | the text, or `—` |
| Adj. hours | — | | `12.50` |
| Labor cost | — | | `$775` |

Each edit is its own PATCH with one field, as today. The two adjustment
fields are independent on the wire (`LaborLineUpdateIn` already takes
each one nullable), so a reason typed before the percent, or after, is
never lost.

**Backend change.** `LaborRowOut` gains `adjustment_percent:
Decimal | None` and `adjustment_reason: str` (both already on the
`ProjectLaborLine` row `pricing.py` resolves from); `mapLaborRow` carries
them as `adjustmentPercent` / `adjustmentReason`. No new endpoint, no
migration.

**Footer.** Sums Adj. hours and Labor cost across rows that have both.
Rows whose status is *Missing information* have neither, so they cannot
be in the sum; the footer's first cell says so — "8 rows not yet priced
are not in this total" — so the number is never quietly short. When
every row is priced the caption is omitted.

### Material pricing

| Column | Edit | Commits | Shown as |
|---|---|---|---|
| Status | — | | `Pill` |
| Material | — | | row header; `basisNote` underneath |
| Quantity | — | | |
| Unit price | number, min 0 | `priceOverride` | `$12.50` or `—` |
| Basis | select | `source` | see below |
| Reason | text | `reason` | the text, or `—` |
| Line total | — | | `quantity × unitPrice`, `$1,250.00`, or `—` |

**Basis** is the one cell that is sometimes read-only and sometimes a
select, and the rule is the row's `source`:

- No project override yet (`source` is `company_price`,
  `regional_baseline`, or null): the cell renders the resolved tier as
  the existing `.pill--neutral` tag (*Company price*, *Regional
  baseline*) or `—`, and `edit.disabled(row)` returns true. Typing a
  price is what creates an override; until then there is no basis to
  choose.
- An override exists (`source` is `project_price` or `allowance`): the
  cell is a select with those two options, rendered idle as the tier
  tag it already shows.

**One PATCH for the trio.** `PATCH /api/items/{id}/material-price` takes
`priceOverride`, `source`, and `reason` together, so a commit on any of
the three cells sends all three from the row's current state plus the
one change. Setting Basis to *Allowance* on a row with a price and then
typing a reason produces two PATCHes and loses nothing.

**Allowance needs a reason.** The server refuses `source = allowance`
with an empty `reason` (422). The screen catches it before the wire,
the same way today's code does, but on the cell: choosing *Allowance*
in Basis when Reason is empty holds the change locally (the row shows
*Allowance* with a pending mark), moves the active cell to Reason, opens
the editor, and shows "An allowance needs a reason — say what it's
standing in for, so the total can be traced back" under it. The PATCH
goes when the reason commits. Escape in that Reason editor reverts Basis
to *Project price* and sends nothing. Clearing an existing allowance's
reason to empty is refused the same way.

**Footer.** Sums Line total across rows with a price; the same "N rows
not yet priced are not in this total" caption.

## Saving

### Commit flow

1. The grid calls `onCommit(row, key, value)`.
2. The screen patches its local `rows` state with the new value and any
   locally derivable figure (line total), so the footer moves at once.
3. The screen sends the PATCH through `runMutation` (below).
4. On success, the screen replaces that one row with the mapped response
   — the endpoints already return the full recomputed row, including the
   resolved rate, adjusted hours, cost, status, and source labels — and
   shows the toast.
5. On failure, the screen restores the row's pre-edit values and shows
   the existing `load-error` banner with the server's message or "That
   change couldn't be saved. Try again."

No full-table refetch on save. The active cell is untouched by any of
this: it moved when the commit fired, and a row re-render does not steal
focus because the grid keys cells by `rowKey` and column key, not by
value.

### Save state and undo

`useReviewStore` already holds `runMutation` (the `Saving…` / `Saved` /
`Couldn't save — retrying` tracker, with the stale-version exception)
and `showToast`, and uses them for every item mutation. Both are added to
its return value, and `ProjectWorkspaceLayout` passes them through the
workspace context unchanged. Nothing new is invented — screen G reads
`saved` and `toast` off the same context today.

Both screens then:

- render `saveStateText(saved)` in `AppTopBar`'s `saveState` slot, the
  helper lifted out of `TakeoffSpreadsheet.jsx` into `lib/format.js` so
  there is one copy;
- call `showToast(label)` after each successful commit, in the
  estimator's words: "Set rate to $62.00/hr on 20A duplex receptacle",
  "Set adjustment to +25% on High bay fixture", "Marked LED troffer as
  allowance", "Set price to $12.50 on 20A duplex receptacle";
- render the same toast markup screen G renders, with its Undo button
  calling the context's `undo()` and then the screen's `load()`, since
  the reversal lands in the action log and the polled snapshot but not
  in this screen's own rows.

`labor_edit` and `material_price_edit` are already in
`undo.REVERSIBLE`; nothing changes server-side for undo.

### Concurrency

Two estimators editing the same row still last-write-wins, as today.
The screens do not poll their own rows; a colleague's edit shows up on
the next load or after an undo. This is the same limit the
labor-material-pricing spec accepted and is unchanged here.

## Styling

All in `styles.css`, tokens only:

- `.grid` extends `.data-table.takeoff-table` (sticky header, 7px 10px
  cells, `tabular` on numeric cells).
- `.grid td[data-editable]` — the 2px right inset mark in `--ink-3`,
  `cursor: text`.
- `.grid td[aria-selected="true"]` — the existing focus ring
  (`box-shadow: inset 0 0 0 2px var(--blue)`), no fill change, so
  selection never reads as a status.
- `.grid .grid-editor` — the in-place input: fills the cell, inherits
  alignment, no border of its own, `tabular`.
- `.grid .grid-cell-error` — the one-line message under a cell, in
  `--red` with the alert icon, matching existing inline field errors.
- `.grid tfoot tr` — `position: sticky; bottom: 0; background:
  var(--surface)`, top border in `--line-2`, bold totals.
- `.grid td.is-pending` — the held-locally allowance state: a dashed
  outline in `--ink-3`, consistent with "unverified is dashed."

No colour is introduced for any of this. Status is the `Pill`; nothing
else on the row is coloured.

## Testing

**`DataGrid.test.jsx`** (vitest + testing-library, as the rest of the
suite):

- arrow keys move the active cell and skip read-only columns; ↑/↓ stay
  in the column; Tab wraps to the next row; Shift+Tab wraps back;
  Home/End
- a printable key opens the editor with that character as the whole
  value; Enter opens it with the current value; F2 places the caret at
  the end
- Enter commits and moves down; Tab commits and moves right; Escape
  discards and stays; blur commits
- `onCommit` fires once per changed cell and not at all for an untouched
  cell
- a `select` cell opens on Space/Enter and commits on change
- `edit.disabled(row)` makes a cell read-only for that row only
- invalid number input keeps the editor open, shows the column's message,
  and does not call `onCommit`
- markup: `role="grid"`, exactly one `tabindex="0"` cell, `aria-selected`
  on it, editor `aria-label` is "Column, Item name"
- focus moves synchronously on commit, before any promise resolves

**`LaborWorkspace.test.jsx`** (existing, updated for the grid) plus:

- adjustment percent and reason render from the row and commit
  `adjustmentPercent` / `adjustmentReason` as separate PATCHes
- a commit patches the one row from the response without refetching the
  list
- footer sums only rows with both figures and captions the excluded
  count; no caption when every row is priced
- the top bar shows `Saving…` during a commit and `Saved` after
- a successful commit shows the toast with the expected label; Undo
  calls the context's `undo()` then reloads

**`MaterialPricingWorkspace.test.jsx`** (existing, updated) plus:

- Basis is read-only until a price exists, a select after
- editing any of price / basis / reason sends all three
- choosing *Allowance* with an empty reason sends nothing, moves focus
  to Reason, opens the editor, shows the message; committing a reason
  then sends `source: "allowance"`; Escape reverts Basis
- line total is `quantity × unitPrice` and `—` when unpriced
- footer and toast, as for labor

**Backend** (`test_pricing_endpoints.py`, existing suite):

- `GET /api/projects/{id}/labor` returns `adjustment_percent` and
  `adjustment_reason` for a row that has them, `null` / `""` for one
  that doesn't

**Removed:** the tests that assert the checkbox and the stacked reason
field, and any that assert a refetch after save.

## Not built in this slice

Named so the next person does not read absence as oversight:

- **Unsetting an override.** The grid cannot clear an estimator-entered
  hours or rate back to the company or baseline tier, because the API
  has no delete for a `ProjectLaborLine` field. Needs an endpoint
  decision.
- **Crew mix and notes** on labor rows.
- **Range selection, fill-down, paste**, the next natural step toward a
  spreadsheet and the one that makes a 400-row hospital set tolerable.
- **Sort and status filter chips** on these two screens.
- **Screen G on the grid.**
