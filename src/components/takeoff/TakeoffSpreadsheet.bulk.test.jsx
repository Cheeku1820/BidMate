/* CLAUDE.md names bulk approval as easy to break by accident: it applies
   only to Ready to review items, never to Needs attention or Missing
   information, "no matter how convenient it looks." These tests are the
   client-side guard. The server enforces the same rule independently. */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
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

    // Scoped to the bulk bar: "Needs attention" and "Missing information"
    // also appear on the two checked rows' own status Pills elsewhere on
    // the page, so an unscoped query is ambiguous about *which* occurrence
    // it means. The bar is its own labelled region -- query inside it.
    const bar = screen.getByRole("region", { name: /selected items/i });
    expect(within(bar).getByText(/2 of the 2 selected can't be approved/i)).toBeTruthy();
    expect(within(bar).getByText(/needs attention/i)).toBeTruthy();
    expect(within(bar).getByText(/missing information/i)).toBeTruthy();
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
