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
  // Focus -- the one active cell, where the grid scrolls to keep it in
  // view -- is the first cell of the first row, not the last: Ctrl/Cmd+A
  // on a long grid must not jump the estimator to the bottom. normalize()
  // works out the range from anchor and focus regardless of which end
  // each one names, so the selected range is unaffected.
  return {
    anchor: { row: rows.length - 1, col: columns[columns.length - 1].key },
    focus: { row: 0, col: columns[0].key },
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
