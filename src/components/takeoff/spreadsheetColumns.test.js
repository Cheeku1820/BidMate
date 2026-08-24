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
