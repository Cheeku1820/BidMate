/* ============================================================
   useGridNavigation.js — which cell is active in a DataGrid, and where
   it goes on each key (docs/specs/pricing-grid.md, "Cell states →
   Active").

   The movement rules are pure functions over (columns, rows) so they
   are tested on plain data; the hook underneath is thin. An active
   cell is { row: index, col: column key }. Only editable cells
   participate -- a column with no `edit`, or whose `edit.disabled(row)`
   is true for this row, is stepped over in every direction. That is
   what makes Tab walk hours → rate → adjustment → reason → next row's
   hours on the labor screen rather than stopping on Status and
   Quantity.
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

/** The active cell after moving in `direction`. Returns null only for
 *  "next"/"prev" past the grid's last/first editable cell -- the one
 *  case focus should leave the grid, which is what an un-prevented Tab
 *  does. Every other dead end stays put. */
export function moveActive(active, direction, columns, rows) {
  if (!active) return null;
  const keys = editableKeys(columns, rows[active.row]);
  const i = keys.indexOf(active.col);
  switch (direction) {
    case "left":
      return i > 0 ? { row: active.row, col: keys[i - 1] } : active;
    case "right":
      return i < keys.length - 1 ? { row: active.row, col: keys[i + 1] } : active;
    case "home":
      return keys.length ? { row: active.row, col: keys[0] } : active;
    case "end":
      return keys.length ? { row: active.row, col: keys[keys.length - 1] } : active;
    case "up":
    case "down": {
      const step = direction === "up" ? -1 : 1;
      for (let r = active.row + step; r >= 0 && r < rows.length; r += step) {
        if (editableKeys(columns, rows[r]).includes(active.col)) return { row: r, col: active.col };
      }
      return active;
    }
    case "next": {
      if (i < keys.length - 1) return { row: active.row, col: keys[i + 1] };
      for (let r = active.row + 1; r < rows.length; r += 1) {
        const k = editableKeys(columns, rows[r]);
        if (k.length) return { row: r, col: k[0] };
      }
      return null;
    }
    case "prev": {
      if (i > 0) return { row: active.row, col: keys[i - 1] };
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
