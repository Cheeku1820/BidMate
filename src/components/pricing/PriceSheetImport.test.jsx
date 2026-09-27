import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PriceSheetImport from "./PriceSheetImport.jsx";

const preview = {
  state: "ready", refused: null, supplierName: "codale", quoteDate: "2026-09-18",
  matched: [{ itemId: "i1", itemName: "20A duplex receptacle", currentUnitPrice: null, currentSourceLabel: null, newUnitPrice: "9.10", partNo: "HBL5362", notes: "", line: 2 }],
  unmatched: [{ itemName: "Something extra", unitPrice: "4", line: 3 }],
  unpriced: [{ itemId: "i2", itemName: "Panelboard" }],
  unreadable: [],
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

  it("needs a quote date before Apply is enabled, and prefills today when the filename carried none", async () => {
    // The API refuses an apply without a quote date; the button waits
    // for one rather than sending a request that comes back 422.
    const s = store({ getPriceSheetPreview: vi.fn().mockResolvedValue({ ...preview, quoteDate: null }) });
    render(<PriceSheetImport projectId="p1" store={s} onApplied={vi.fn()} onClose={() => {}} />);
    const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await userEvent.upload(screen.getByLabelText("Price sheet"), file);
    const apply = await screen.findByRole("button", { name: "Apply 1 price" });

    const d = new Date();
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    expect(screen.getByLabelText("Quote date")).toHaveValue(today);
    expect(apply).toBeEnabled();

    await userEvent.clear(screen.getByLabelText("Quote date"));
    expect(screen.getByLabelText("Quote date")).toHaveValue("");
    expect(apply).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Quote date"), { target: { value: "2026-09-18" } });
    expect(apply).toBeEnabled();
    await userEvent.click(apply);
    await waitFor(() => expect(s.applyPriceSheet).toHaveBeenCalledWith("p1", "d1",
      expect.objectContaining({ quoteDate: "2026-09-18" })));
  });

  it("keeps a date the filename carried rather than overwriting it with today", async () => {
    const s = store();
    render(<PriceSheetImport projectId="p1" store={s} onApplied={vi.fn()} onClose={() => {}} />);
    await userEvent.upload(screen.getByLabelText("Price sheet"), new File(["x"], "codale_2026-09-18.xlsx"));
    await screen.findByRole("button", { name: "Apply 1 price" });
    expect(screen.getByLabelText("Quote date")).toHaveValue("2026-09-18");
  });

  it("shows a dash, not a broken amount, for an unmatched row the sheet left unpriced", async () => {
    const s = store({ getPriceSheetPreview: vi.fn().mockResolvedValue({
      ...preview, unmatched: [{ itemName: "Something extra", unitPrice: null, line: 3 }],
    }) });
    render(<PriceSheetImport projectId="p1" store={s} onApplied={vi.fn()} onClose={() => {}} />);
    await userEvent.upload(screen.getByLabelText("Price sheet"), new File(["x"], "codale.xlsx"));
    const item = await screen.findByText(/Something extra/);
    expect(item.textContent).toContain("—");
    expect(item.textContent).not.toContain("NaN");
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
  it("lists the rows that couldn't be read, with the line and the reason", async () => {
    // A row the parser could not read is named, not silently dropped
    // under "left unpriced" -- and it takes nothing away from the rows
    // that did read: Apply still offers the matched one.
    const s = store({ getPriceSheetPreview: vi.fn().mockResolvedValue({
      ...preview, unreadable: [{ line: 4, reason: "the price isn't a number" }, { line: 7, reason: "the row has no item name" }],
    }) });
    render(<PriceSheetImport projectId="p1" store={s} onApplied={vi.fn()} onClose={() => {}} />);
    const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await userEvent.upload(screen.getByLabelText("Price sheet"), file);
    expect(await screen.findByText(withText("h4", "2 rows couldn't be read"))).toBeInTheDocument();
    expect(screen.getByText(withText("li", "Row 4 — the price isn't a number"))).toBeInTheDocument();
    expect(screen.getByText(withText("li", "Row 7 — the row has no item name"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply 1 price" })).toBeInTheDocument();
  });

  it("shows the refusal when none of the rows could be read, with nothing to apply", async () => {
    const s = store({ getPriceSheetPreview: vi.fn().mockResolvedValue({
      state: "ready", refused: "None of the rows could be read. Start from Download price request.",
      matched: [], unmatched: [], unpriced: [], unreadable: [{ line: 2, reason: "the price isn't a number" }],
      supplierName: "", quoteDate: null,
    }) });
    render(<PriceSheetImport projectId="p1" store={s} onApplied={vi.fn()} onClose={() => {}} />);
    const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await userEvent.upload(screen.getByLabelText("Price sheet"), file);
    expect(await screen.findByRole("alert")).toHaveTextContent("None of the rows could be read. Start from Download price request.");
    expect(screen.queryByRole("button", { name: /Apply/ })).not.toBeInTheDocument();
  });
});
