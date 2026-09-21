/* ============================================================
   useGridSelection.test.js — the range rules, on plain data
   (docs/specs/spreadsheet-grid.md, "Selection" and "Range
   operations"). Columns: name (row header, read-only, text()),
   qty (read-only), price (number, min 0), basis (select, disabled
   when locked), note (text). Cells are { row index, col key }.
   ============================================================ */

import { describe, expect, test } from "vitest";
import {
  cellText, clearChanges, coerce, extend, fillChanges, normalize, parseClipboard, pasteChanges, selectAll, sortRows, toTsv,
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
  test("covers the grid, focused on the first cell of the first row so a long grid does not scroll to the bottom", () => {
    // anchor is the last cell of the last row, focus the first cell of
    // the first row -- normalize() below still resolves the same range
    // regardless of which end is which.
    expect(selectAll(columns, rows)).toEqual(sel(2, "evidence", 0, "name"));
    expect(normalize(selectAll(columns, rows), columns)).toEqual({ r0: 0, c0: 0, r1: 2, c1: 5 });
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
    // Columns from Quantity: qty (read-only, skipped), price, basis. Clip line 1 lands on row 1, line 2 on row 2; lines 3 and 4 fall off the grid. Row 1's basis is locked; row 2's is already "allowance".
    expect(changes).toEqual([
      { row: rows[1], key: "price", value: 5 },
      { row: rows[2], key: "price", value: 6 },
    ]);
  });
  test("an empty pasted cell clears an entry and nothing is emitted when nothing applies", () => {
    expect(pasteChanges([[""]], { r0: 0, c0: 2, r1: 0, c1: 2 }, columns, rows)).toEqual([{ row: rows[0], key: "price", value: null }]);
    expect(pasteChanges([["zzz"]], { r0: 0, c0: 1, r1: 0, c1: 1 }, columns, rows)).toEqual([]);
  });
});

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
