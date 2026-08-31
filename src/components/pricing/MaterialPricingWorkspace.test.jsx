/* ============================================================
   MaterialPricingWorkspace.test.jsx — Material Pricing workspace tests.
   Follows the same pattern as LaborWorkspace.test.jsx: useWorkspaceContext
   is mocked directly rather than rendering through the real layout.
   ============================================================ */

import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import MaterialPricingWorkspace from "./MaterialPricingWorkspace.jsx";

const baseRows = [
  {
    itemId: "i1",
    itemName: "20A duplex receptacle",
    quantity: 10,
    unitPrice: null,
    sourceLabel: null,
    status: "missing",
  },
];

let context;

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderMaterialPricing({ store }) {
  context = { store, projectId: "p1" };
  return render(
    <MemoryRouter>
      <MaterialPricingWorkspace />
    </MemoryRouter>,
  );
}

describe("MaterialPricingWorkspace", () => {
  test("renders Missing information when nothing resolves", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setMaterialPrice: vi.fn(),
    };
    renderMaterialPricing({ store });
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    expect(screen.getByText(/missing information/i)).toBeInTheDocument();
  });

  test("setting a project price calls setMaterialPrice with source project_price", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setMaterialPrice: vi.fn().mockResolvedValue({}),
    };
    renderMaterialPricing({ store });
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    const priceInput = screen.getByLabelText(/unit price/i);
    fireEvent.change(priceInput, { target: { value: "15.5" } });
    fireEvent.blur(priceInput);
    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", { priceOverride: 15.5, source: "project_price" })
    );
  });
});
