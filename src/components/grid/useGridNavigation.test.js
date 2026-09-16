/* ============================================================
   useGridNavigation.test.js — the movement rules, on plain data.
   Column keys: name (row header, read-only), qty (read-only),
   hours / note / basis (editable; basis disabled on row 2).
   ============================================================ */

import { describe, expect, test } from "vitest";
import { firstEditable, isEditable, moveActive } from "./useGridNavigation.js";

const columns = [
  { key: "name", label: "Item", header: true, render: (r) => r.name },
  { key: "qty", label: "Quantity", render: (r) => r.qty },
  { key: "hours", label: "Hours", render: (r) => r.hours, edit: { kind: "number", value: (r) => r.hours } },
  { key: "note", label: "Note", render: (r) => r.note, edit: { kind: "text", value: (r) => r.note } },
  {
    key: "basis", label: "Basis", render: (r) => r.basis,
    edit: { kind: "select", value: (r) => r.basis, options: [], disabled: (r) => r.locked },
  },
];
const rows = [
  { name: "One", qty: 1, hours: 0.5, note: "", basis: "a" },
  { name: "Two", qty: 2, hours: null, note: "x", basis: "b", locked: true },
  { name: "Three", qty: 3, hours: 1, note: "", basis: "a" },
];

describe("isEditable", () => {
  test("needs an edit descriptor and not to be disabled on the row", () => {
    expect(isEditable(columns[1], rows[0])).toBe(false);
    expect(isEditable(columns[2], rows[0])).toBe(true);
    expect(isEditable(columns[4], rows[0])).toBe(true);
    expect(isEditable(columns[4], rows[1])).toBe(false);
  });
});

describe("firstEditable", () => {
  test("is the first editable cell of the first row that has one", () => {
    expect(firstEditable(columns, rows)).toEqual({ row: 0, col: "hours" });
    expect(firstEditable(columns, [])).toBeNull();
    expect(firstEditable([columns[0], columns[1]], rows)).toBeNull();
  });
});

describe("moveActive", () => {
  test("left and right step within the row over editable cells only, and stop at the edges", () => {
    expect(moveActive({ row: 0, col: "hours" }, "right", columns, rows)).toEqual({ row: 0, col: "note" });
    expect(moveActive({ row: 0, col: "note" }, "right", columns, rows)).toEqual({ row: 0, col: "basis" });
    expect(moveActive({ row: 0, col: "basis" }, "right", columns, rows)).toEqual({ row: 0, col: "basis" });
    expect(moveActive({ row: 0, col: "hours" }, "left", columns, rows)).toEqual({ row: 0, col: "hours" });
    // Row 2's basis is disabled, so right from note stays on note.
    expect(moveActive({ row: 1, col: "note" }, "right", columns, rows)).toEqual({ row: 1, col: "note" });
  });

  test("up and down stay in the column and skip rows where it is not editable", () => {
    expect(moveActive({ row: 0, col: "hours" }, "down", columns, rows)).toEqual({ row: 1, col: "hours" });
    expect(moveActive({ row: 0, col: "basis" }, "down", columns, rows)).toEqual({ row: 2, col: "basis" });
    expect(moveActive({ row: 2, col: "basis" }, "up", columns, rows)).toEqual({ row: 0, col: "basis" });
    expect(moveActive({ row: 0, col: "hours" }, "up", columns, rows)).toEqual({ row: 0, col: "hours" });
    expect(moveActive({ row: 2, col: "hours" }, "down", columns, rows)).toEqual({ row: 2, col: "hours" });
  });

  test("next and prev wrap between rows and return null past either end of the grid", () => {
    expect(moveActive({ row: 0, col: "basis" }, "next", columns, rows)).toEqual({ row: 1, col: "hours" });
    expect(moveActive({ row: 1, col: "hours" }, "prev", columns, rows)).toEqual({ row: 0, col: "basis" });
    expect(moveActive({ row: 2, col: "basis" }, "next", columns, rows)).toBeNull();
    expect(moveActive({ row: 0, col: "hours" }, "prev", columns, rows)).toBeNull();
  });

  test("home and end go to the row's first and last editable cell", () => {
    expect(moveActive({ row: 1, col: "note" }, "home", columns, rows)).toEqual({ row: 1, col: "hours" });
    expect(moveActive({ row: 1, col: "hours" }, "end", columns, rows)).toEqual({ row: 1, col: "note" });
  });

  test("a null active cell moves nowhere", () => {
    expect(moveActive(null, "right", columns, rows)).toBeNull();
  });
});
