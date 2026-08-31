/* ============================================================
   TakeoffSpreadsheet.cost.test.jsx — the running cost strip.

   Its membership rule is the one that matters here. Totals are computed
   in exactly one place and a superseded sheet never contributes to one,
   so this strip and the export preview must agree on which items count.
   They diverged once: the strip filtered `!rejected` while the export
   used countsTowardTotals, which meant an item on a superseded sheet was
   inside one number and outside the other.
   ============================================================ */

import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TakeoffSpreadsheet from "./TakeoffSpreadsheet.jsx";

const priced = (over) => ({
  id: "x", sheetId: "live", name: "20A duplex receptacle", description: "", system: "Power",
  quantity: 1, unit: "ea", status: "approved", notes: "", rejected: false, warnings: [],
  version: 1, materialCost: 0, laborHours: 0, laborCost: 0, totalCost: 0, ...over,
});

let context;
vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function setContext(items) {
  context = {
    snapshot: {
      sheets: [
        { id: "live", number: "E1.1", title: "Level 1 power", superseded: false },
        { id: "old", number: "E1.1", title: "Level 1 power", superseded: true },
      ],
      items,
      totals: { bySystem: {}, approvedCount: 0, remainingCount: 0, attentionCount: 0, missingCount: 0, approvedUnits: 0 },
      undo: { canUndo: false, canRedo: false, label: null, undoBy: null },
      presence: [],
    },
    loading: false,
    loadError: null,
    selectedItemId: null,
    selectItem: vi.fn(),
    sheetId: "live",
    setSheetId: vi.fn(),
    bulkApprove: vi.fn(),
    projectId: "p1",
  };
}

const renderSheet = () =>
  render(
    <MemoryRouter>
      <TakeoffSpreadsheet />
    </MemoryRouter>,
  );

describe("TakeoffSpreadsheet cost strip", () => {
  it("leaves an item on a superseded sheet out of the running total", () => {
    setContext([
      priced({ id: "live-1", sheetId: "live", totalCost: 1000, laborHours: 10 }),
      priced({ id: "old-1", sheetId: "old", totalCost: 5000, laborHours: 50 }),
      priced({ id: "rej-1", sheetId: "live", totalCost: 700, rejected: true }),
    ]);
    renderSheet();

    // The superseded sheet's 5,000 and the rejected item's 700 are both
    // out; only the live sheet's 1,000 is in.
    const strip = document.querySelector(".estimate-strip");
    expect(within(strip).getByText(/\$1,000/)).toBeTruthy();
    expect(within(strip).queryByText(/\$6,000/)).toBeNull();
    expect(within(strip).queryByText(/\$6,700/)).toBeNull();
    // And the item count behind it excludes them too.
    expect(within(strip).getByText(/^1 items/)).toBeTruthy();
  });

  it("hides the strip entirely on an unpriced takeoff rather than claiming $0", () => {
    setContext([priced({ id: "live-1", sheetId: "live" })]);
    renderSheet();
    expect(screen.queryByText(/estimated total direct cost/i)).toBeNull();
  });
});
