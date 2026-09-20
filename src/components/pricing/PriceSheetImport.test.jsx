import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

// The three group headings and the Apply button wrap only their digit
// in `.tabular` (CLAUDE.md's "tabular numerals on every number"), so
// the count and its label are separate text nodes -- Testing Library's
// getByText only concatenates an element's own direct text-node
// children (getNodeText), not a nested element's, so a plain string
// match against "1 row matched" no longer finds the split-up <h4>. This
// matcher checks the element's full textContent instead, the same
// thing a person or a screen reader reads.
function withText(tagName, text) {
  return (_content, element) =>
    element?.tagName === tagName.toUpperCase() && element.textContent.replace(/\s+/g, " ").trim() === text;
}

describe("PriceSheetImport", () => {
  it("uploads, shows the preview in three groups, and applies the ticked rows", async () => {
    const s = store();
    const onApplied = vi.fn();
    render(<PriceSheetImport projectId="p1" store={s} onApplied={onApplied} onClose={() => {}} />);
    const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await userEvent.upload(screen.getByLabelText("Price sheet"), file);
    expect(await screen.findByText(withText("h4", "1 row matched"))).toBeInTheDocument();
    expect(screen.getByText(withText("h4", "1 row not on this project"))).toBeInTheDocument();
    expect(screen.getByText(withText("h4", "1 item left unpriced"))).toBeInTheDocument();
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

  describe("the reading state", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("polls every 2s while the job is still reading, and stops once it's ready", async () => {
      const getPriceSheetPreview = vi
        .fn()
        .mockResolvedValueOnce({ state: "reading" })
        .mockResolvedValueOnce(preview);
      const s = store({ getPriceSheetPreview });
      render(<PriceSheetImport projectId="p1" store={s} onApplied={vi.fn()} onClose={() => {}} />);

      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      await user.upload(screen.getByLabelText("Price sheet"), file);

      await vi.waitFor(() => expect(getPriceSheetPreview).toHaveBeenCalledTimes(1));
      expect(screen.getByText(/reading the price sheet/i)).toBeInTheDocument();
      expect(screen.queryByText(withText("h4", "1 row matched"))).toBeNull();

      await vi.advanceTimersByTimeAsync(2000);

      expect(getPriceSheetPreview).toHaveBeenCalledTimes(2);
      expect(screen.getByText(withText("h4", "1 row matched"))).toBeInTheDocument();
    });

    it("stops polling once unmounted", async () => {
      const getPriceSheetPreview = vi
        .fn()
        .mockResolvedValueOnce({ state: "reading" })
        .mockResolvedValueOnce(preview);
      const s = store({ getPriceSheetPreview });
      const { unmount } = render(<PriceSheetImport projectId="p1" store={s} onApplied={vi.fn()} onClose={() => {}} />);

      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      await user.upload(screen.getByLabelText("Price sheet"), file);
      await vi.waitFor(() => expect(getPriceSheetPreview).toHaveBeenCalledTimes(1));

      unmount();
      await vi.advanceTimersByTimeAsync(2000);

      expect(getPriceSheetPreview).toHaveBeenCalledTimes(1);
    });
  });
});
