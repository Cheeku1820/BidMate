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
    basisNote: "",
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
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", {
        priceOverride: 15.5,
        source: "project_price",
        reason: "",
      })
    );
  });

  test("marking a price as an allowance sends source allowance and the reason", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setMaterialPrice: vi.fn().mockResolvedValue({}),
    };
    renderMaterialPricing({ store });
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText("Mark as allowance"));
    fireEvent.change(screen.getByLabelText("Allowance reason"), {
      target: { value: "Fixture package not yet selected" },
    });

    const priceInput = screen.getByLabelText(/unit price/i);
    fireEvent.change(priceInput, { target: { value: "40" } });
    fireEvent.blur(priceInput);

    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", {
        priceOverride: 40,
        source: "allowance",
        reason: "Fixture package not yet selected",
      })
    );
  });

  test("an allowance with no reason is not sent, and says why", async () => {
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setMaterialPrice: vi.fn().mockResolvedValue({}),
    };
    renderMaterialPricing({ store });
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText("Mark as allowance"));

    const priceInput = screen.getByLabelText(/unit price/i);
    fireEvent.change(priceInput, { target: { value: "40" } });
    fireEvent.blur(priceInput);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/needs a reason/i));
    expect(store.setMaterialPrice).not.toHaveBeenCalled();
  });

  test("a row that is already an allowance loads with the checkbox checked and the reason filled in", async () => {
    const rows = [
      {
        ...baseRows[0],
        unitPrice: 15.5,
        source: "allowance",
        sourceLabel: "Allowance",
        reason: "no vendor quote yet",
        status: "approved",
      },
    ];
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows }),
      setMaterialPrice: vi.fn(),
    };
    renderMaterialPricing({ store });
    await waitFor(() => expect(screen.getByLabelText("Mark as allowance")).toBeChecked());
    expect(screen.getByLabelText("Allowance reason")).toHaveValue("no vendor quote yet");
  });

  test("editing only the price of an existing allowance keeps it an allowance with its reason", async () => {
    // The regression this guards: without seeding local allowance state from
    // the loaded row, a price-only edit after a reload would silently send
    // source: "project_price" with an empty reason, discarding why the
    // number was a placeholder.
    const rows = [
      {
        ...baseRows[0],
        unitPrice: 15.5,
        source: "allowance",
        sourceLabel: "Allowance",
        reason: "no vendor quote yet",
        status: "approved",
      },
    ];
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows }),
      setMaterialPrice: vi.fn().mockResolvedValue({}),
    };
    renderMaterialPricing({ store });
    await waitFor(() => expect(screen.getByLabelText("Mark as allowance")).toBeChecked());

    const priceInput = screen.getByLabelText(/unit price/i);
    fireEvent.change(priceInput, { target: { value: "20" } });
    fireEvent.blur(priceInput);

    await waitFor(() =>
      expect(store.setMaterialPrice).toHaveBeenCalledWith("i1", {
        priceOverride: 20,
        source: "allowance",
        reason: "no vendor quote yet",
      })
    );
  });

  test("shows the source label and basis note when a row resolves from Regional baseline", async () => {
    const rows = [
      {
        ...baseRows[0],
        unitPrice: 12.5,
        sourceLabel: "Regional baseline",
        status: "ready",
        basisNote: "Price based on Sacramento, CA area cost data.",
      },
    ];
    const store = {
      getMaterialRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "x", rows }),
      setMaterialPrice: vi.fn(),
    };
    renderMaterialPricing({ store });
    await waitFor(() => expect(screen.getByText("Regional baseline")).toBeInTheDocument());
    expect(screen.getByText("Price based on Sacramento, CA area cost data.")).toBeInTheDocument();
  });
});
