/* ============================================================
   LaborWorkspace.test.jsx — modeled on TakeoffSpreadsheet.test.jsx and
   NotesWorkspace.test.jsx: useWorkspaceContext.js is mocked directly
   rather than rendered through the real ProjectWorkspaceLayout, since
   this screen is a plain child of it and the layout's own behavior is
   covered by ProjectWorkspaceLayout.test.jsx.

   Labor rows are not part of the polled review snapshot (Task 9's
   getLaborRows/setLaborLine are a separate surface, the same way
   Notes's listNotes/createNote are), so the mocked context here carries
   a `store` with those two methods directly and this screen calls them
   itself rather than reading rows off `snapshot`.
   ============================================================ */

import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import LaborWorkspace from "./LaborWorkspace.jsx";

const baseRows = [
  {
    itemId: "i1", itemName: "20A duplex receptacle", quantity: 10, hoursPerUnit: null,
    hoursSourceLabel: null, rate: null, rateSourceLabel: null, adjustedHours: null,
    laborCost: null, status: "missing", basisNote: "",
  },
];

let context;

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderLabor({ store }) {
  context = { store, projectId: "p1" };
  return render(
    <MemoryRouter>
      <LaborWorkspace />
    </MemoryRouter>,
  );
}

describe("LaborWorkspace", () => {
  test("renders a row per item, with the Missing information status when nothing resolves", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    expect(screen.getByText(/missing information/i)).toBeInTheDocument();
  });

  test("shows the source label and basis note when a row resolves from the estimated basis", async () => {
    const rows = [
      {
        ...baseRows[0], hoursPerUnit: 0.5, hoursSourceLabel: "Estimated basis",
        rate: 78, rateSourceLabel: "Estimated basis", adjustedHours: 5, laborCost: 390,
        status: "ready", basisNote: "Rate based on Sacramento, CA area cost data.",
      },
    ];
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "llm", pricingNote: "x", rows }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    // Both tier tags render verbatim, even when the two independent
    // precedence chains land on the same tier. Paraphrasing the second as
    // "same as hours" would read as one field deriving from the other.
    await waitFor(() => expect(screen.getAllByText("Estimated basis")).toHaveLength(2));
    expect(screen.getByText("Rate based on Sacramento, CA area cost data.")).toBeInTheDocument();
  });

  test("editing hours calls setLaborLine and refreshes the row", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setLaborLine: vi.fn().mockResolvedValue({}),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    const hoursInput = screen.getByLabelText(/hours per unit/i);
    fireEvent.change(hoursInput, { target: { value: "0.75" } });
    fireEvent.blur(hoursInput);
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { hoursOverride: 0.75 }));
  });

  test("editing the rate calls setLaborLine with a rate override", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setLaborLine: vi.fn().mockResolvedValue({}),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    const rateInput = screen.getByLabelText(/^rate$/i);
    fireEvent.change(rateInput, { target: { value: "78" } });
    fireEvent.blur(rateInput);
    await waitFor(() => expect(store.setLaborLine).toHaveBeenCalledWith("i1", { rateOverride: 78 }));
  });

  test("clearing the rate field saves nothing -- an empty field is not a $0/hr rate", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: null, pricingNote: "", rows: baseRows }),
      setLaborLine: vi.fn().mockResolvedValue({}),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
    const rateInput = screen.getByLabelText(/^rate$/i);
    fireEvent.change(rateInput, { target: { value: "" } });
    fireEvent.blur(rateInput);
    expect(store.setLaborLine).not.toHaveBeenCalled();
  });
});
