/* ============================================================
   useGridNavigation.js — which cell is active in a DataGrid, and where
   it goes on each key (docs/specs/pricing-grid.md, "Cell states →
   Active").

   The movement rules are pure functions over (columns, rows) so they
   are tested on plain data; the hook underneath is thin. An active
   cell is { row: index, col: column key }. Arrows, Home and End visit
   every cell, as in a spreadsheet. Only Tab (`next`/`prev`) is the
   entry flow: it walks editable cells only, so on the labor screen it
   goes hours → rate → adjustment → reason → the next row's hours rather
   than stopping on Status and Quantity.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";

export function isEditable(column, row) {
  return Boolean(column.edit) && !(column.edit.disabled && column.edit.disabled(row));
}

function editableKeys(columns, row) {
  return columns.filter((c) => isEditable(c, row)).map((c) => c.key);
}

export function firstEditable(columns, rows) {
  for (let r = 0; r < rows.length; r += 1) {
    const keys = editableKeys(columns, rows[r]);
    if (keys.length) return { row: r, col: keys[0] };
  }
  return null;
}

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

/** Active-cell state for a DataGrid. Starts on the first editable cell
 *  once rows exist (roving tabindex needs one tabbable cell), and moves
 *  back onto the grid if rows shrink under it. */
export function useGridNavigation(columns, rows) {
  const [active, setActive] = useState(null);

  useEffect(() => {
    if (!active || active.row >= rows.length) setActive(firstEditable(columns, rows));
  }, [active, columns, rows]);

  const move = useCallback((direction) => moveActive(active, direction, columns, rows), [active, columns, rows]);

  return { active, setActive, move };
}
