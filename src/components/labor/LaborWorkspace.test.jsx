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

const NOTE =
  "Rate based on Unalaska, AK area cost data. Branch wiring is estimated at 30 feet per device. Conduit and wire quantities follow that rule rather than a measured route, so check them against the job before the total is relied on.";

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


  test("shows the pricing basis note on a deterministic project, not only an automated one", async () => {
    /* The note was gated behind pricingSource === "llm", so a project
       priced from the regional table -- no key configured, or any
       automated attempt that fell back, which is how this repo runs
       today -- wrote the note and never displayed it. That note is where
       the 30-ft-per-device branch wiring assumption is disclosed, and it
       is half the labour hours on a real set. */
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({
        pricingSource: "deterministic", pricingNote: NOTE, rows: baseRows,
      }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText(/Branch wiring is estimated/)).toBeInTheDocument());
    // Both facts belong on screen: the note, and that nothing was estimated automatically.
    expect(screen.getByText(/no automatic labor-hour estimate/)).toBeInTheDocument();
  });

  test("shows no basis note when the project carries none", async () => {
    const store = {
      getLaborRows: vi.fn().mockResolvedValue({ pricingSource: "deterministic", pricingNote: "", rows: baseRows }),
      setLaborLine: vi.fn(),
    };
    renderLabor({ store });
    await waitFor(() => expect(screen.getByText(/no automatic labor-hour estimate/)).toBeInTheDocument());
    expect(screen.queryByText(/Branch wiring is estimated/)).not.toBeInTheDocument();
  });
});
