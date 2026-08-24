/* DESIGN.md: "Selecting a marker selects its takeoff row and, in the
   table view, scrolls to and highlights that row. Selecting a row
   centers the blueprint on that marker and selects it." Selection lives
   in shared state, so both directions are the same one field moving --
   these tests assert the table reads it and writes it. */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import TakeoffSpreadsheet from "./TakeoffSpreadsheet.jsx";

const items = [
  { id: "i1", sheetId: "s1", name: "20A duplex receptacle", description: "", system: "Power", quantity: 12, unit: "ea", status: "ready", notes: "", rejected: false, warnings: [], version: 1 },
  { id: "i2", sheetId: "s2", name: "High bay fixture", description: "", system: "Lighting", quantity: 4, unit: "ea", status: "ready", notes: "", rejected: false, warnings: [], version: 1 },
];

const context = {
  snapshot: {
    sheets: [
      { id: "s1", number: "E1.1", title: "Level 1 power", superseded: false },
      { id: "s2", number: "E2.1", title: "Warehouse power", superseded: false },
    ],
    items,
    totals: { bySystem: {}, approvedCount: 0, remainingCount: 2, attentionCount: 0, missingCount: 0, approvedUnits: 0 },
    undo: { canUndo: false, canRedo: false, label: null, undoBy: null },
    presence: [],
  },
  loading: false,
  loadError: null,
  selectedItemId: null,
  selectItem: vi.fn(),
  sheetId: "s1",
  setSheetId: vi.fn(),
  bulkApprove: vi.fn(),
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

beforeEach(() => {
  context.selectedItemId = null;
  context.selectItem.mockClear();
});

describe("TakeoffSpreadsheet selection", () => {
  it("reports a clicked row to the shared selection", async () => {
    renderSheet();
    await userEvent.click(screen.getByText("High bay fixture"));
    expect(context.selectItem).toHaveBeenCalledWith("i2");
  });

  it("marks the selected row, and marks only that one", () => {
    context.selectedItemId = "i2";
    renderSheet();

    const rows = screen.getAllByRole("row").slice(1);
    const selected = rows.filter((r) => r.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(within(selected[0]).getByText("High bay fixture")).toBeTruthy();
  });

  it("is reachable and selectable from the keyboard", async () => {
    // Spec §8: keyboard navigation through table rows. A row selectable
    // only by mouse is a hover-only control by another name.
    renderSheet();
    const row = screen.getByText("High bay fixture").closest("tr");
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(context.selectItem).toHaveBeenCalledWith("i2");
  });
});
