/* ============================================================
   ExportPreview.test.jsx — screen H behaviour.

   Two rules do the work: the approved totals shown here come straight
   from the store's own totals (never re-summed, so they can't drift from
   the drawer), and Missing information blocks export with no override,
   mirroring the finish-review gate for the case where the export nav
   item is reached directly.
   ============================================================ */

import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ExportPreview from "./ExportPreview.jsx";

const baseItems = [
  { id: "i1", sheetId: "s1", name: "Panel LP-1", description: "", system: "Distribution", quantity: 1, unit: "ea", status: "approved", rejected: false, warnings: [] },
  { id: "i2", sheetId: "s1", name: "20A receptacle", description: "", system: "Power", quantity: 14, unit: "ea", status: "approved", rejected: false, warnings: [] },
  { id: "i3", sheetId: "s1", name: "High bay", description: "", system: "Lighting", quantity: 2, unit: "ea", status: "attention", rejected: false, warnings: [] },
  { id: "i4", sheetId: "s1", name: "Old feeder", description: "", system: "Power", quantity: 1, unit: "ea", status: "ready", rejected: true, warnings: [] },
];

function makeContext(over = {}) {
  return {
    snapshot: {
      sheets: [{ id: "s1", number: "E1.1", title: "Level 1 power", superseded: false }],
      items: baseItems,
      totals: { bySystem: { Distribution: 1, Power: 14 }, approvedUnits: 15, approvedCount: 2, remainingCount: 2, attentionCount: 1, missingCount: 0 },
      undo: { canUndo: false, canRedo: false },
      presence: [],
    },
    loading: false,
    loadError: null,
    refresh: vi.fn(),
    projectId: "p1",
    project: { id: "p1", name: "Cedar Ridge Warehouse", revisionSetLabel: "E1.1 Rev 3", sample: true },
    ...over,
  };
}

let context = makeContext();
vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

const renderExport = () =>
  render(
    <MemoryRouter>
      <ExportPreview />
    </MemoryRouter>,
  );

describe("ExportPreview", () => {
  it("shows approved totals by system straight from the store totals", () => {
    context = makeContext();
    renderExport();

    const totalsCard = screen.getByRole("heading", { name: /approved totals by system/i }).closest("section");
    const powerRow = within(totalsCard).getByRole("rowheader", { name: "Power" }).closest("tr");
    expect(within(powerRow).getByText("14")).toBeTruthy();
    // The all-systems row equals the store's approvedUnits, not a local re-sum.
    const allRow = within(totalsCard).getByRole("rowheader", { name: /all systems/i }).closest("tr");
    expect(within(allRow).getByText("15")).toBeTruthy();
  });

  it("names the sampled project and its file, and shows the sample banner", () => {
    context = makeContext();
    renderExport();
    expect(screen.getByText("cedar-ridge-warehouse-takeoff.csv")).toBeTruthy();
    expect(screen.getByText(/sample takeoff/i)).toBeTruthy();
  });

  it("enables Export when there are approved items and nothing blocking", () => {
    context = makeContext();
    renderExport();
    for (const button of screen.getAllByRole("button", { name: /export excel/i })) {
      expect(button).toBeEnabled();
    }
  });

  it("blocks export with no override when a Missing information item remains", () => {
    context = makeContext({
      snapshot: {
        ...makeContext().snapshot,
        items: [...baseItems, { id: "i5", sheetId: "s1", name: "Conduit run", description: "", system: "Power", quantity: 1, unit: "ft", status: "missing", rejected: false, warnings: [] }],
        totals: { bySystem: { Distribution: 1, Power: 14 }, approvedUnits: 15, approvedCount: 2, remainingCount: 3, attentionCount: 1, missingCount: 1 },
      },
    });
    renderExport();

    expect(screen.getByText(/missing information blocks export/i)).toBeTruthy();
    for (const button of screen.getAllByRole("button", { name: /export excel/i })) {
      expect(button).toBeDisabled();
    }
  });
});
