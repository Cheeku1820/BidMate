/* ============================================================
   MaterialPricingWorkspace.test.jsx — the Material pricing screen on
   the pricing grid (docs/specs/pricing-grid.md). Context is mocked as
   in LaborWorkspace.test.jsx.
   ============================================================ */

import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import MaterialPricingWorkspace from "./MaterialPricingWorkspace.jsx";
import { REFRESH_BUSY } from "./marketOutcomeCopy.js";

const baseRow = {
  itemId: "i1", itemName: "20A duplex receptacle", quantity: 10, unitPrice: null, source: null,
  sourceLabel: null, reason: "", status: "missing", basisNote: "",
};
const companyRow = { ...baseRow, unitPrice: 12.5, sourceLabel: "Company price", status: "ready" };
const projectRow = { ...baseRow, unitPrice: 15.5, source: "project_price", sourceLabel: "Project price", status: "approved" };

let context;

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderMaterial({ store, extra = {} }) {
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
      <MaterialPricingWorkspace />
    </MemoryRouter>,
  );
  return review;
}

function cellFor(itemName, columnLabel) {
  const row = screen.getByRole("rowheader", { name: new RegExp(itemName) }).closest("tr");
  const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
  return Array.from(row.querySelectorAll('[role="gridcell"], [role="rowheader"]'))[headers.indexOf(columnLabel)];
}

async function loaded(name = /20A duplex receptacle/) {
  await waitFor(() => expect(screen.getByRole("rowheader", { name })).toBeInTheDocument());
}

describe("MaterialPricingWorkspace", () => {
  test("renders a row per item with the Missing information status when nothing resolves", async () => {
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }) };
    renderMaterial({ store });
    await loaded();
    expect(screen.getByText(/missing information/i)).toBeInTheDocument();
  });

  test("fills the shell so the grid scrolls inside the page and its header and footer pin", async () => {
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }) };
    renderMaterial({ store });
    await loaded();
    expect(screen.getByRole("grid").closest(".page")).toHaveClass("page--fill");
  });

  test("Basis is read-only and shows the resolved tier until a price entry exists", async () => {
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [companyRow] }) };
    renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    expect(basis).toHaveTextContent("Company price");
    expect(basis).not.toHaveAttribute("data-editable");
    expect(cellFor("20A duplex receptacle", "Reason")).not.toHaveAttribute("data-editable");
  });

  test("typing a price sends the trio and patches the row; line total is quantity × price", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [companyRow] }),
      setMaterialPrice: vi.fn().mockResolvedValue(projectRow),
    };
    const review = renderMaterial({ store });
    await loaded();
    const price = cellFor("20A duplex receptacle", "Unit price");
    fireEvent.keyDown(price, { key: "1" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "15.5" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", { priceOverride: 15.5, source: "project_price", reason: "" }),
    );
    await waitFor(() => expect(screen.getByText("Project price")).toBeInTheDocument());
    expect(cellFor("20A duplex receptacle", "Line total")).toHaveTextContent("$155.00");
    expect(store.getMaterialRows).toHaveBeenCalledTimes(1);
    expect(review.showToast).toHaveBeenCalledWith("Set price to $15.50 on 20A duplex receptacle");
  });

  test("editing only the price of an existing allowance keeps it an allowance with its reason", async () => {
    // Guards the one line in commit() that carries row.source and
    // row.reason through a price edit -- without it a price change
    // would quietly turn an allowance back into a project price.
    const allowanceRow = { ...projectRow, source: "allowance", sourceLabel: "Allowance", reason: "No vendor quote yet" };
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [allowanceRow] }),
      setMaterialPrice: vi.fn().mockResolvedValue({ ...allowanceRow, unitPrice: 20 }),
    };
    renderMaterial({ store });
    await loaded();
    // Unit price is the first editable cell, so it is already active on mount.
    const price = cellFor("20A duplex receptacle", "Unit price");
    fireEvent.keyDown(price, { key: "2" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "20" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", { priceOverride: 20, source: "allowance", reason: "No vendor quote yet" }),
    );
  });

  test("Basis becomes a select once an entry exists; choosing Allowance with a reason sends the trio", async () => {
    const allowanceRow = { ...projectRow, source: "allowance", sourceLabel: "Allowance", reason: "No vendor quote yet" };
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [{ ...projectRow, reason: "No vendor quote yet" }] }),
      setMaterialPrice: vi.fn().mockResolvedValue(allowanceRow),
    };
    const review = renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    expect(basis).toHaveAttribute("data-editable");
    fireEvent.click(basis);
    fireEvent.keyDown(basis, { key: " " });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "allowance" } });
    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", { priceOverride: 15.5, source: "allowance", reason: "No vendor quote yet" }),
    );
    expect(review.showToast).toHaveBeenCalledWith("Marked 20A duplex receptacle as allowance");
  });

  test("choosing Allowance with no reason holds the change, opens Reason with the message, and sends on commit", async () => {
    const allowanceRow = { ...projectRow, source: "allowance", sourceLabel: "Allowance", reason: "No vendor quote yet" };
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow] }),
      setMaterialPrice: vi.fn().mockResolvedValue(allowanceRow),
    };
    const review = renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    fireEvent.click(basis);
    fireEvent.keyDown(basis, { key: " " });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "allowance" } });
    expect(store.setMaterialPrice).not.toHaveBeenCalled();
    const reasonInput = screen.getByRole("textbox", { name: "Reason, 20A duplex receptacle" });
    expect(screen.getByRole("alert")).toHaveTextContent("An allowance needs a reason");
    expect(cellFor("20A duplex receptacle", "Basis")).toHaveTextContent("Allowance");
    expect(cellFor("20A duplex receptacle", "Basis")).toHaveClass("is-pending");
    fireEvent.change(reasonInput, { target: { value: "No vendor quote yet" } });
    fireEvent.keyDown(reasonInput, { key: "Enter" });
    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", { priceOverride: 15.5, source: "allowance", reason: "No vendor quote yet" }),
    );
    await waitFor(() => expect(cellFor("20A duplex receptacle", "Basis")).not.toHaveClass("is-pending"));
    // The toast names the held change that finally went, not the reason.
    expect(review.showToast).toHaveBeenCalledWith("Marked 20A duplex receptacle as allowance");
  });

  test("Escape in the held Reason editor reverts Basis and sends nothing", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow] }),
      setMaterialPrice: vi.fn(),
    };
    renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    fireEvent.click(basis);
    fireEvent.keyDown(basis, { key: " " });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "allowance" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    expect(cellFor("20A duplex receptacle", "Basis")).toHaveTextContent("Project price");
    expect(store.setMaterialPrice).not.toHaveBeenCalled();
  });

  test("clearing the price calls DELETE and re-renders the fallen-back row", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow] }),
      clearMaterialPrice: vi.fn().mockResolvedValue(companyRow),
    };
    const review = renderMaterial({ store });
    await loaded();
    const price = cellFor("20A duplex receptacle", "Unit price");
    fireEvent.keyDown(price, { key: "Delete" });
    await waitFor(() => expect(store.clearMaterialPrice).toHaveBeenCalledWith("i1"));
    await waitFor(() => expect(screen.getByText("Company price")).toBeInTheDocument());
    expect(review.showToast).toHaveBeenCalledWith("Cleared price on 20A duplex receptacle — now Company price");
    // Basis and Reason are read-only again.
    expect(cellFor("20A duplex receptacle", "Basis")).not.toHaveAttribute("data-editable");
  });

  test("Delete on Basis or Reason sends nothing", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [projectRow] }),
      setMaterialPrice: vi.fn(),
      clearMaterialPrice: vi.fn(),
    };
    renderMaterial({ store });
    await loaded();
    const basis = cellFor("20A duplex receptacle", "Basis");
    fireEvent.click(basis);
    fireEvent.keyDown(basis, { key: "Delete" });
    const reason = cellFor("20A duplex receptacle", "Reason");
    fireEvent.click(reason);
    fireEvent.keyDown(reason, { key: "Delete" });
    expect(store.setMaterialPrice).not.toHaveBeenCalled();
    expect(store.clearMaterialPrice).not.toHaveBeenCalled();
  });

  test("the footer sums line totals over priced rows and names what is left out", async () => {
    const rows = [projectRow, { ...companyRow, itemId: "i2", itemName: "Exit sign", quantity: 4 }, { ...baseRow, itemId: "i3", itemName: "Unknown symbol" }];
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows }) };
    renderMaterial({ store });
    await loaded(/Exit sign/);
    const footer = document.querySelector("tfoot");
    expect(footer).toHaveTextContent("$205.00"); // 155 + 50
    expect(footer).toHaveTextContent("1 row not yet priced is not in this total");
  });

  test("shows the save state and an undoable toast that reloads", async () => {
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }) };
    const review = renderMaterial({
      store,
      extra: { saved: { state: "error", at: Date.now() }, toast: { id: "t1", text: "Set price to $15.50 on 20A duplex receptacle" } },
    });
    await loaded();
    expect(screen.getByText("Couldn't save — retrying")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(review.undo).toHaveBeenCalled();
    await waitFor(() => expect(store.getMaterialRows).toHaveBeenCalledTimes(2));
  });

  test("a failed undo shows its message instead of failing silently", async () => {
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [baseRow] }) };
    renderMaterial({
      store,
      extra: {
        undo: vi.fn().mockRejectedValue(new Error("Nothing to undo")),
        toast: { id: "t1", text: "Set price to $15.50 on 20A duplex receptacle" },
      },
    });
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Nothing to undo"));
  });

  test("shows the source label and basis note when a row resolves from Regional baseline", async () => {
    const rows = [
      { ...baseRow, unitPrice: 12.5, sourceLabel: "Regional baseline", status: "ready", basisNote: "Price based on Sacramento, CA area cost data." },
    ];
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "x", rows }) };
    renderMaterial({ store });
    await loaded();
    expect(screen.getByText("Regional baseline")).toBeInTheDocument();
    expect(screen.getByText("Price based on Sacramento, CA area cost data.")).toBeInTheDocument();
  });

  test("shows the pricing basis note on a deterministic project, not only an automated one", async () => {
    const NOTE =
      "Rate based on Unalaska, AK area cost data. Branch wiring is estimated at 30 feet per device. Conduit and wire quantities follow that rule rather than a measured route, so check them against the job before the total is relied on.";
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: "deterministic", pricingNote: NOTE, rows: [baseRow] }),
    };
    renderMaterial({ store });
    await loaded();
    // Under the grid, labelled as the basis; the old banner above it is gone.
    const note = screen.getByText(/Branch wiring is estimated/).closest(".pricing-basis");
    expect(note).toBeInTheDocument();
    expect(note).toHaveTextContent(/^Pricing basis/);
    expect(screen.queryByText(/no automatic regional price estimate/)).not.toBeInTheDocument();
    expect(screen.queryByText(/pricing assistant/i)).not.toBeInTheDocument();
  });

  test("shows no basis note when the project carries none", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: "deterministic", pricingNote: "", rows: [baseRow] }),
    };
    renderMaterial({ store });
    await loaded();
    expect(screen.queryByText(/no automatic regional price estimate/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Branch wiring is estimated/)).not.toBeInTheDocument();
    expect(document.querySelector(".pricing-basis")).toBeNull();
  });

  test("shows an empty state when the project has no items", async () => {
    const store = { getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [] }) };
    renderMaterial({ store });
    await waitFor(() => expect(screen.getByText("No items yet")).toBeInTheDocument());
  });

  test("shows a load error with a retry action", async () => {
    const store = {
      getMaterialRows: vi.fn().mockRejectedValueOnce(new Error("network down")).mockResolvedValueOnce({
        pricingSource: null, pricingNote: "", rows: [baseRow],
      }),
    };
    renderMaterial({ store });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("network down"));
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Try again" }));
    await loaded();
    expect(store.getMaterialRows).toHaveBeenCalledTimes(2);
  });

  const marketRow = {
    itemId: "i1", itemName: "2x4 LED troffer", quantity: 12, unitPrice: 169.95, source: null,
    sourceLabel: "Market estimate", reason: "", status: "attention", basisNote: "Austin, TX, Sep 18",
    priceLow: 156.75, priceHigh: 303.33, marketOutcome: "priced", marketWarning: null,
    marketEvidence: [{ seller: "Codale", price: 169.95, link: "https://codale.example/x" }], fetchedAt: "2026-09-18T00:00:00Z",
    supplierName: "", quoteDate: null,
  };

  test("shows the market estimate's range and tier tag beside the status pill", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [marketRow], marketJob: null }),
    };
    renderMaterial({ store });
    await loaded(/2x4 LED troffer/);
    expect(screen.getByText("Market estimate")).toBeInTheDocument();
    expect(screen.getByText("$156.75–$303.33")).toBeInTheDocument();
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
  });

  test("shows the outcome warning on an unpriced row", async () => {
    const row = {
      ...marketRow, unitPrice: null, sourceLabel: null, status: "missing", marketOutcome: "location_needed",
      marketWarning: {
        title: "Project location needed",
        found: 'Looked for "2x4 LED troffer".',
        why: "w",
        fix: "Add the project ZIP code in project settings, then refresh market estimates.",
        where: "E2.1",
      },
    };
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [row], marketJob: null }),
    };
    renderMaterial({ store });
    await loaded(/2x4 LED troffer/);
    expect(screen.getByText("Project location needed")).toBeInTheDocument();
    expect(screen.getByText(/Add the project ZIP code/)).toBeInTheDocument();
  });

  test("refresh queues the job and says so", async () => {
    const refreshMarketEstimates = vi.fn().mockResolvedValue({ queued: true });
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [marketRow], marketJob: null }),
      refreshMarketEstimates,
    };
    renderMaterial({ store });
    await loaded(/2x4 LED troffer/);
    await userEvent.click(await screen.findByRole("button", { name: "Refresh market estimates" }));
    expect(refreshMarketEstimates).toHaveBeenCalled();
    expect(await screen.findByText(/Refreshing market estimates/)).toBeInTheDocument();
  });

  test("refresh already running shows the busy toast instead of a poll", async () => {
    const showToast = vi.fn();
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [marketRow], marketJob: null }),
      refreshMarketEstimates: vi.fn().mockResolvedValue({ queued: false }),
    };
    renderMaterial({ store, extra: { showToast } });
    await loaded(/2x4 LED troffer/);
    await userEvent.click(await screen.findByRole("button", { name: "Refresh market estimates" }));
    expect(showToast).toHaveBeenCalledWith(REFRESH_BUSY);
    expect(screen.queryByText(/Refreshing market estimates/)).not.toBeInTheDocument();
  });

  test("a failed refresh shows the same inline error style as other actions", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [marketRow], marketJob: null }),
      refreshMarketEstimates: vi.fn().mockRejectedValue(new Error()),
    };
    renderMaterial({ store });
    await loaded(/2x4 LED troffer/);
    await userEvent.click(await screen.findByRole("button", { name: "Refresh market estimates" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't refresh market estimates. Check your connection and try again.",
    );
  });

  test("shows sellers as evidence with seller — price text and an external link", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [marketRow], marketJob: null }),
    };
    renderMaterial({ store });
    await loaded(/2x4 LED troffer/);
    expect(screen.getByText("Sellers")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Codale — \$169\.95/ });
    expect(link).toHaveAttribute("href", "https://codale.example/x");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  test("Tab from inside the market evidence details is not hijacked back onto the grid", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: [marketRow], marketJob: null }),
    };
    renderMaterial({ store });
    await loaded(/2x4 LED troffer/);
    const summary = screen.getByText("Sellers");
    summary.focus();
    expect(document.activeElement).toBe(summary);
    fireEvent.keyDown(summary, { key: "Tab" });
    // The grid's own Tab handling must not have fired: focus stays put
    // (jsdom does not itself move focus on Tab) rather than jumping to
    // whatever cell the grid's roving-tabindex logic would pick next.
    expect(document.activeElement).not.toHaveAttribute("role", "gridcell");
    expect(document.activeElement).toBe(summary);
  });
});
