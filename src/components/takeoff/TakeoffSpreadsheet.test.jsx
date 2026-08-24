import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import TakeoffSpreadsheet from "./TakeoffSpreadsheet.jsx";

const items = [
  { id: "i1", sheetId: "s1", name: "20A duplex receptacle", description: "Duplex, 20A", system: "Power", quantity: 12, unit: "ea", status: "approved", notes: "", rejected: false, warnings: [], version: 1 },
  { id: "i2", sheetId: "s2", name: "High bay fixture", description: "LED high bay", system: "Lighting", quantity: 4, unit: "ea", status: "attention", notes: "", rejected: false, warnings: [{ title: "Schedule conflict" }], version: 1 },
  { id: "i3", sheetId: "s1", name: "Conduit run", description: "3/4in EMT", system: "Power", quantity: 60, unit: "ft", status: "missing", notes: "", rejected: false, warnings: [], version: 1 },
];

const context = {
  snapshot: {
    sheets: [
      { id: "s1", number: "E1.1", title: "Level 1 power", superseded: false },
      { id: "s2", number: "E2.1", title: "Warehouse power", superseded: false },
    ],
    items,
    totals: { bySystem: {}, approvedCount: 1, remainingCount: 2, attentionCount: 1, missingCount: 1, approvedUnits: 12 },
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

describe("TakeoffSpreadsheet", () => {
  it("renders one row per item with proper table semantics", () => {
    renderSheet();
    expect(screen.getAllByRole("row")).toHaveLength(items.length + 1); // + header
    expect(screen.getByRole("columnheader", { name: /status/i })).toBeTruthy();
  });

  it("shows each status as text, not colour alone", () => {
    renderSheet();
    expect(screen.getByText(/estimator approved/i)).toBeTruthy();
    expect(screen.getByText(/needs attention/i)).toBeTruthy();
    expect(screen.getByText(/missing information/i)).toBeTruthy();
  });

  it("does not render columns that have no data behind them", () => {
    // See the plan's Data Reality section: a blank "Waste factor" column
    // reads as "no waste applied", which is a fabricated fact.
    renderSheet();
    for (const absent of [/waste/i, /manufacturer/i, /floor/i, /specification/i]) {
      expect(screen.queryByRole("columnheader", { name: absent })).toBeNull();
    }
  });

  it("filters by status", async () => {
    renderSheet();
    await userEvent.click(screen.getByRole("button", { name: /needs attention/i }));
    expect(screen.getByText("High bay fixture")).toBeTruthy();
    expect(screen.queryByText("20A duplex receptacle")).toBeNull();
  });

  it("searches across item name and description", async () => {
    renderSheet();
    await userEvent.type(screen.getByLabelText(/search items/i), "high bay");
    expect(screen.getByText("High bay fixture")).toBeTruthy();
    expect(screen.queryByText("Conduit run")).toBeNull();
  });

  it("sorts by a column when its header is activated", async () => {
    renderSheet();
    await userEvent.click(screen.getByRole("button", { name: /sort by item/i }));
    // The item name lives in the row's <th scope="row"> (WCAG 2.2 AA),
    // which carries role "rowheader" rather than "cell" -- read it
    // there rather than by cell index, which the rowheader doesn't
    // occupy a slot in.
    const names = screen.getAllByRole("row").slice(1).map((r) => within(r).getByRole("rowheader").textContent);
    expect(names).toEqual([...names].sort());
  });

  it("hides a column without removing its rows", async () => {
    // Column visibility filters what is drawn, never what is counted --
    // the same rule the canvas layer toggles follow.
    renderSheet();
    const before = screen.getAllByRole("row").length;

    await userEvent.click(screen.getByRole("button", { name: /columns/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /system/i }));

    expect(screen.queryByRole("columnheader", { name: /^system$/i })).toBeNull();
    expect(screen.getAllByRole("row")).toHaveLength(before);
  });

  it("names a recovery action when nothing matches", async () => {
    renderSheet();
    await userEvent.type(screen.getByLabelText(/search items/i), "zzzz");
    expect(screen.getByText(/no items match/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /clear search/i })).toBeTruthy();
  });
});
