import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ExportPreview from "./ExportPreview.jsx";

let context;
vi.mock("../project/useWorkspaceContext.js", () => ({ useWorkspaceContext: () => context }));

const sheets = [{ id: "s1", number: "E-1.0", revision: "Rev 1" }];
const items = [
  {
    id: "i1", name: "20A duplex receptacle", description: "", system: "Power", quantity: 14, unit: "ea",
    sheetId: "s1", status: "approved", rejected: false, materialCost: 0, laborHours: 7, totalCost: 0,
    phaseId: "p1", warnings: [],
  },
  {
    id: "i2", name: "Switchboard MSB-1", description: "", system: "Power", quantity: 1, unit: "ea",
    sheetId: "s1", status: "approved", rejected: false, materialCost: 0, laborHours: 42, totalCost: 0,
    phaseId: "p2", warnings: [],
  },
];

function phase(id, name, extra = {}) {
  return {
    id, name, sortOrder: 0, startDate: null, requiredFinishDate: null, notes: "", sheetIds: ["s1"],
    itemsMovedIn: 0, itemsMovedOut: 0, directHours: 100, generalConditionsHours: 7, materialTotal: 0,
    lines: [{ id: `${id}-l1`, label: "Final and daily cleanup", hours: 3, source: "computed", percentOfDirectHours: 3 }],
    bars: [], start: null, end: null, ...extra,
  };
}

function setup(schedule) {
  context = {
    snapshot: { items, sheets, totals: { bySystem: { Power: 15 }, approvedCount: 2, remainingCount: 0 } },
    loading: false, loadError: null, refresh: vi.fn(), projectId: "proj",
    project: { name: "Gerber Collision" },
    store: { getSchedule: vi.fn().mockResolvedValue(schedule) },
  };
}

function renderScreen() {
  return render(
    <MemoryRouter>
      <ExportPreview />
    </MemoryRouter>,
  );
}

const base = {
  multiPhase: false, relative: true, manpower: [], peakCrew: 0, peakWeek: 0, averageCrew: 0,
  leads: [], unscheduledCount: 0, unscheduledNote: "", defaultSplitCount: 0,
  defaultsInUse: { splits: true, crews: true }, expectedAwardDate: null, mobilizationDate: null,
};

describe("the export's phase roll-up", () => {
  it("shows no phase summary on a single-phase project", async () => {
    setup({ ...base, phases: [phase("p1", "Phase 1")] });
    renderScreen();
    await waitFor(() => expect(context.store.getSchedule).toHaveBeenCalled());
    expect(screen.queryByText("Summary by phase")).not.toBeInTheDocument();
  });

  it("carries one lump-sum line per phase once a second exists", async () => {
    setup({ ...base, multiPhase: true, phases: [phase("p1", "E sheets"), phase("p2", "XE sheets")] });
    renderScreen();
    expect(await screen.findByText("Summary by phase")).toBeInTheDocument();
    expect(screen.getByText("E sheets")).toBeInTheDocument();
    expect(screen.getByText("XE sheets")).toBeInTheDocument();
    // hours = direct + general conditions, stated per phase
    expect(screen.getAllByText("107.00")).toHaveLength(2);
  });

  it("states a long-lead item's weeks, or says it isn't quoted", async () => {
    setup({
      ...base,
      phases: [phase("p1", "Phase 1")],
      leads: [
        {
          itemId: "i2", itemName: "Switchboard MSB-1", itemStatus: "approved", phaseId: "p1", phaseName: "Phase 1",
          leadWeeks: 40, source: "supplier_quote", sourceLabel: "Graybar", quotedAt: "2026-09-12",
          neededForStage: "gear", neededBy: "2027-02-22", orderBy: "2026-05-25", orderByWeek: -20,
          passed: true, stale: false, note: "Order date has passed — 40 weeks lead, gear starts Feb 22", warning: null,
        },
        {
          itemId: "i3", itemName: "Pad-mount transformer", itemStatus: "ready", phaseId: "p1", phaseName: "Phase 1",
          leadWeeks: null, source: null, sourceLabel: "", quotedAt: null, neededForStage: "gear",
          neededBy: null, orderBy: null, orderByWeek: null, passed: false, stale: false, note: "", warning: null,
        },
      ],
    });
    renderScreen();
    expect(await screen.findByText("Long-lead items")).toBeInTheDocument();
    expect(screen.getByText("Graybar")).toBeInTheDocument();
    expect(screen.getByText("2026-05-25")).toBeInTheDocument();
    expect(screen.getByText("Not yet quoted")).toBeInTheDocument();
  });
});
