import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PriceSheetImport from "./PriceSheetImport.jsx";

const preview = {
  state: "ready", refused: null, supplierName: "codale", quoteDate: "2026-09-18",
  matched: [{ itemId: "i1", itemName: "20A duplex receptacle", currentUnitPrice: null, currentSourceLabel: null, newUnitPrice: "9.10", partNo: "HBL5362", notes: "", line: 2 }],
  unmatched: [{ itemName: "Something extra", unitPrice: "4", line: 3 }],
  unpriced: [{ itemId: "i2", itemName: "Panelboard" }],
};

function store(overrides = {}) {
  return {
    uploadPriceSheet: vi.fn().mockResolvedValue({ documentId: "d1" }),
    getPriceSheetPreview: vi.fn().mockResolvedValue(preview),
    applyPriceSheet: vi.fn().mockResolvedValue({ rows: [] }),
    ...overrides,
  };
}

describe("PriceSheetImport", () => {
  it("uploads, shows the preview in three groups, and applies the ticked rows", async () => {
    const s = store();
    const onApplied = vi.fn();
    render(<PriceSheetImport projectId="p1" store={s} onApplied={onApplied} onClose={() => {}} />);
    const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await userEvent.upload(screen.getByLabelText("Price sheet"), file);
    expect(await screen.findByText("1 row matched")).toBeInTheDocument();
    expect(screen.getByText("1 row not on this project")).toBeInTheDocument();
    expect(screen.getByText("1 item left unpriced")).toBeInTheDocument();
    expect(screen.getByLabelText("Supplier")).toHaveValue("codale");
    await userEvent.clear(screen.getByLabelText("Supplier"));
    await userEvent.type(screen.getByLabelText("Supplier"), "Codale");
    await userEvent.click(screen.getByRole("button", { name: "Apply 1 price" }));
    await waitFor(() => expect(s.applyPriceSheet).toHaveBeenCalledWith("p1", "d1",
      { itemIds: ["i1"], supplierName: "Codale", quoteDate: "2026-09-18", saveToCompany: false }));
    expect(onApplied).toHaveBeenCalled();
  });

  it("shows a refused sheet's reason and no apply", async () => {
    const s = store({ getPriceSheetPreview: vi.fn().mockResolvedValue({ ...preview, matched: [], refused: "The sheet needs a header row with the columns Item and Unit price." }) });
    render(<PriceSheetImport projectId="p1" store={s} onApplied={() => {}} onClose={() => {}} />);
    await userEvent.upload(screen.getByLabelText("Price sheet"), new File(["x"], "q.csv", { type: "text/csv" }));
    expect(await screen.findByText(/needs a header row/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply/ })).toBeNull();
  });
});
