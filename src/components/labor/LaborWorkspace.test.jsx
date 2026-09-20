/* ============================================================
   LaborWorkspace.test.jsx — the Labor screen on the pricing grid
   (docs/specs/pricing-grid.md). useWorkspaceContext.js is mocked
   directly, as before; the context now also carries the review
   store's runMutation/showToast/saved/toast/undo, which this screen
   uses for the same save state and toast every other workspace shows.
   ============================================================ */

import { describe, expect, test, vi } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import LaborWorkspace from "./LaborWorkspace.jsx";

const baseRow = {
  itemId: "i1", itemName: "20A duplex receptacle", quantity: 10, hoursPerUnit: null,
  hoursSourceLabel: null, rate: null, rateSourceLabel: null, adjustedHours: null,
  laborCost: null, adjustmentPercent: null, adjustmentReason: "", status: "missing", basisNote: "",
};
const pricedRow = {
  ...baseRow, hoursPerUnit: 0.5, hoursSourceLabel: "Estimated basis", rate: 78,
  rateSourceLabel: "Estimated basis", adjustedHours: 5, laborCost: 390, status: "ready",
  basisNote: "Rate based on Sacramento, CA area cost data.",
};

const NOTE =
  "Rate based on Unalaska, AK area cost data. Branch wiring is estimated at 30 feet per device. Conduit and wire quantities follow that rule rather than a measured route, so check them against the job before the total is relied on.";

let context;

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderLabor({ store, extra = {} }) {
  const review = {
    runMutation: vi.fn((fn) => fn()),
    showToast: vi.fn(),
    saved: { state: "saved", at: Date.parse("2026-08-25T15:00:00Z") },
    toast: null,
    dismissToast: vi.fn(),
    undo: vi.fn().mockResolvedValue(undefined),
  };
  context = { store, projectId: "p1", ...review, ...extra };
  render(
    <MemoryRouter>
      <LaborWorkspace />
    </MemoryRouter>,
  );
  return review;
}

/** The cell under `columnLabel` on the row whose header names `itemName`.
 *  Every column renders one cell in header order (the Item column as a
 *  rowheader, the rest as gridcells), so the column's index in the
 *  header row is its index among the row's cells. The header's
 *  accessible name includes the basis note, hence the regex. */
function cellFor(itemName, columnLabel) {
  const row = screen.getByRole("rowheader", { name: new RegExp(itemName) }).closest("tr");
  const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
  return Array.from(row.querySelectorAll('[role="gridcell"], [role="rowheader"]'))[headers.indexOf(columnLabel)];
}

describe("LaborWorkspace", () => {
  test("renders a row per item, with the Missing information status when nothing resolves", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    expect(screen.getByText(/missing information/i)).toBeInTheDocument();
  });

  test("fills the shell so the grid scrolls inside the page and its header and footer pin", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("grid")).toBeInTheDocument());
    expect(screen.getByRole("grid").closest(".page")).toHaveClass("page--fill");
  });

  test("shows both tier tags and the basis note when a row resolves from the estimated basis", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "x", rows: [pricedRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getAllByText("Estimated basis")).toHaveLength(2));
    expect(screen.getByText("Rate based on Sacramento, CA area cost data.")).toBeInTheDocument();
  });

  test("renders the adjustment percent and reason", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({
        pricingSource: "llm", pricingNote: "",
        rows: [{ ...pricedRow, adjustmentPercent: 25, adjustmentReason: "Mounting height above 16 ft" }],
      }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText("+25%")).toBeInTheDocument());
    expect(screen.getByText("Mounting height above 16 ft")).toBeInTheDocument();
  });

  test("editing hours sends hoursOverride, patches the row from the response, and toasts", async () => {
    // Still "missing": hours alone resolve no cost, so the API keeps the row at Missing information.
    const updated = { ...baseRow, hoursPerUnit: 0.75, hoursSourceLabel: "Estimator entered", status: "missing" };
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn().mockResolvedValue(updated),
    };
    const review = renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    const hours = cellFor("20A duplex receptacle", "Hours/unit");
    fireEvent.keyDown(hours, { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Hours/unit, 20A duplex receptacle" });
    fireEvent.change(input, { target: { value: "0.75" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { hoursOverride: 0.75 }));
    await waitFor(() => expect(screen.getByText("Estimator entered")).toBeInTheDocument());
    expect(store.getLaborRows).toHaveBeenCalledTimes(1); // no refetch
    expect(review.runMutation).toHaveBeenCalled();
    expect(review.showToast).toHaveBeenCalledWith("Set hours to 0.75 on 20A duplex receptacle");
  });

  test("editing the rate sends rateOverride and toasts the rate", async () => {
    const updated = { ...pricedRow, rate: 62, rateSourceLabel: "Estimator entered", laborCost: 310, status: "approved" };
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows: [pricedRow] }),
      setLaborLine: vi.fn().mockResolvedValue(updated),
    };
    const review = renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    const rate = cellFor("20A duplex receptacle", "Rate");
    fireEvent.click(rate); // not the first editable cell, so activate it first
    fireEvent.keyDown(rate, { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Rate, 20A duplex receptacle" });
    fireEvent.change(input, { target: { value: "62" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { rateOverride: 62 }));
    await waitFor(() => expect(screen.getByText("Estimator entered")).toBeInTheDocument());
    expect(review.showToast).toHaveBeenCalledWith("Set rate to $62.00/hr on 20A duplex receptacle");
  });

  test("editing the adjustment sends adjustmentPercent, and the reason sends adjustmentReason", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows: [pricedRow] }),
      setLaborLine: vi.fn().mockImplementation((_id, changes) =>
        Promise.resolve({ ...pricedRow, ...(changes.adjustmentPercent != null ? { adjustmentPercent: changes.adjustmentPercent } : {}),
          ...(changes.adjustmentReason != null ? { adjustmentReason: changes.adjustmentReason } : {}) }),
      ),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    const adj = cellFor("20A duplex receptacle", "Adjustment");
    fireEvent.click(adj);
    fireEvent.keyDown(adj, { key: "2" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "25" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Tab" }); // commits, moves to Adjustment reason
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { adjustmentPercent: 25 }));
    const reason = cellFor("20A duplex receptacle", "Adjustment reason");
    fireEvent.keyDown(reason, { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Mounting height above 16 ft" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() =>
      expect(store.setLaborLine).toHaveBeenCalledWith("i1", { adjustmentReason: "Mounting height above 16 ft" }),
    );
  });

  test("clearing hours sends null, re-renders from the fallen-back row, and names the new source", async () => {
    const entered = { ...pricedRow, hoursPerUnit: 0.75, hoursSourceLabel: "Estimator entered", status: "approved" };
    const fallenBack = { ...pricedRow, hoursPerUnit: 0.4, hoursSourceLabel: "Company standard" };
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows: [entered] }),
      setLaborLine: vi.fn().mockResolvedValue(fallenBack),
    };
    const review = renderLabor({ store });
    await waitFor(() => expect(screen.getByText("Estimator entered")).toBeInTheDocument());
    const hours = cellFor("20A duplex receptacle", "Hours/unit");
    fireEvent.keyDown(hours, { key: "Delete" });
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { hoursOverride: null }));
    await waitFor(() => expect(screen.getByText("Company standard")).toBeInTheDocument());
    expect(review.showToast).toHaveBeenCalledWith("Cleared hours on 20A duplex receptacle — now Company standard");
  });

  test("clearing hours with nothing behind them says so in the toast", async () => {
    const entered = { ...baseRow, hoursPerUnit: 0.75, hoursSourceLabel: "Estimator entered" };
    const fallenBack = { ...baseRow, hoursSourceLabel: null, hoursPerUnit: null, status: "missing" };
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [entered] }),
      setLaborLine: vi.fn().mockResolvedValue(fallenBack),
    };
    const review = renderLabor({ store });
    await waitFor(() => expect(screen.getByText("Estimator entered")).toBeInTheDocument());
    fireEvent.keyDown(cellFor("20A duplex receptacle", "Hours/unit"), { key: "Delete" });
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { hoursOverride: null }));
    await waitFor(() => expect(screen.queryByText("Estimator entered")).not.toBeInTheDocument());
    expect(review.showToast).toHaveBeenCalledWith("Cleared hours on 20A duplex receptacle — nothing else is set");
  });

  test("a failed save restores the row and shows the error", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows: [pricedRow] }),
      setLaborLine: vi.fn().mockRejectedValue(new Error("Network down")),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    const hours = cellFor("20A duplex receptacle", "Hours/unit");
    fireEvent.keyDown(hours, { key: "9" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Network down"));
    expect(cellFor("20A duplex receptacle", "Hours/unit")).toHaveTextContent("0.500");
  });

  test("a failed save restores only the edited field, not a later commit on the same row", async () => {
    let rejectHours;
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows: [pricedRow] }),
      setLaborLine: vi.fn().mockImplementation((_id, changes) =>
        changes.hoursOverride != null
          ? new Promise((_, reject) => { rejectHours = reject; })
          : Promise.resolve({ ...pricedRow, rate: 62, rateSourceLabel: "Estimator entered" }),
      ),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    // Hours: sent, still in flight.
    fireEvent.keyDown(cellFor("20A duplex receptacle", "Hours/unit"), { key: "9" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Tab" });
    // Rate: sent and landed while hours is still pending.
    const rate = cellFor("20A duplex receptacle", "Rate");
    fireEvent.keyDown(rate, { key: "6" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "62" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() => expect(screen.getByText("Estimator entered")).toBeInTheDocument());
    // Now hours fails: it goes back to 0.500, and the landed rate stays.
    await act(async () => rejectHours(new Error("Network down")));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Network down"));
    expect(cellFor("20A duplex receptacle", "Hours/unit")).toHaveTextContent("0.500");
    expect(cellFor("20A duplex receptacle", "Rate")).toHaveTextContent("$62.00/hr");
  });

  test("the footer sums adjusted hours and labor cost over priced rows and names what is left out", async () => {
    const rows = [
      pricedRow,
      { ...pricedRow, itemId: "i2", itemName: "Exit sign", adjustedHours: 2.5, laborCost: 195 },
      { ...baseRow, itemId: "i3", itemName: "Unknown symbol" },
    ];
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "", rows }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /Exit sign/ })).toBeInTheDocument());
    const footer = document.querySelector("tfoot");
    expect(footer).toHaveTextContent("7.50");
    expect(footer).toHaveTextContent("$585");
    expect(footer).toHaveTextContent("1 row not yet priced is not in this total");
  });

  test("shows the save state in the top bar and an undoable toast", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    const review = renderLabor({
      store,
      extra: { saved: { state: "saving", at: Date.now() }, toast: { id: "t1", text: "Set hours to 0.75 on 20A duplex receptacle" } },
    });
    await waitFor(() => expect(screen.getByText("Saving…")).toBeInTheDocument());
    // Not getByRole("status") -- AppTopBar's own save-state span (shown
    // right above, "Saving…") also carries role="status" (shell.test.jsx
    // pins that), so with both mounted at once the role is ambiguous.
    // TakeoffSpreadsheet.saveState.test.jsx hits the same pairing and
    // resolves it the same way: query the toast by its text.
    expect(screen.getByText("Set hours to 0.75 on 20A duplex receptacle")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(review.undo).toHaveBeenCalled();
    expect(review.dismissToast).toHaveBeenCalled();
    await waitFor(() => expect(store.getLaborRows).toHaveBeenCalledTimes(2)); // reloads after undo
  });

  test("a failed undo shows its message instead of failing silently", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({
      store,
      extra: {
        undo: vi.fn().mockRejectedValue(new Error("Nothing to undo")),
        toast: { id: "t1", text: "Set hours to 0.75 on 20A duplex receptacle" },
      },
    });
    await waitFor(() => expect(screen.getByRole("rowheader", { name: /20A duplex receptacle/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Nothing to undo"));
  });

  test("never shows the old no-automatic-estimate banner, whatever the pricing source", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "deterministic", pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("grid")).toBeInTheDocument());
    expect(screen.queryByText(/no automatic labor-hour estimate/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/pricing assistant/i)).not.toBeInTheDocument();
  });

  test("shows the pricing basis note on a deterministic project, not only an automated one", async () => {
    /* The note was gated behind pricingSource === "llm", so a project
       priced from the regional table -- no key configured, or any
       automated attempt that fell back -- wrote the note and never
       displayed it. That note is where the 30-ft-per-device branch
       wiring assumption is disclosed, and it is half the labour hours
       on a real set. */
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({
        pricingSource: "deterministic", pricingNote: NOTE, rows: [baseRow],
      }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText(/Branch wiring is estimated/)).toBeInTheDocument());
    // Under the grid, labelled as the basis, not as a banner above it.
    const note = screen.getByText(/Branch wiring is estimated/).closest(".pricing-basis");
    expect(note).toBeInTheDocument();
    expect(note).toHaveTextContent(/^Pricing basis/);
    const table = screen.getByRole("grid");
    expect(table.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("shows no basis note when the project carries none", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "deterministic", pricingNote: "", rows: [baseRow] }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByRole("grid")).toBeInTheDocument());
    expect(screen.queryByText(/Branch wiring is estimated/)).not.toBeInTheDocument();
    expect(document.querySelector(".pricing-basis")).toBeNull();
  });
});
