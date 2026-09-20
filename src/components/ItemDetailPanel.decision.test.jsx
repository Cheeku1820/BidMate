import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ItemDetailPanel from "./ItemDetailPanel.jsx";

const props = {
  sheets: [{ id: "s1", number: "EP101", revision: "Rev 1" }], currentSheet: null, edit: null,
  onStartEdit: vi.fn(), onChangeEdit: vi.fn(), onSaveEdit: vi.fn(), onCancelEdit: vi.fn(), onRequestDelete: vi.fn(),
  onShowEvidence: vi.fn(), onStep: vi.fn(), stepIndex: 1, stepCount: 3, itemError: null, onRefreshItem: vi.fn(),
  onDismissItemError: vi.fn(), counts: { attention: 1 }, itemsTotal: 3, onNextIssue: vi.fn(),
  onResolve: vi.fn().mockResolvedValue({ intent: "unknown", targetItemIds: ["i1"], name: "", system: "", category: "", unit: "ea", summary: "", source: "read", versions: {} }),
  onApplyProposal: vi.fn(), onUndo: vi.fn(), onSelectItem: vi.fn(), alsoMatchingItemId: null,
};
const sel = { id: "i1", symbol: "luminaire", status: "attention", rejected: false, name: "Luminaire type F", description: "",
  quantity: 30, unit: "ea", system: "Lighting", category: "Fixtures", sheetId: "s1", evidence: null, aiConfirmed: false,
  approvedBy: null, notes: "", warnings: [], sourceTag: "F", path: null, version: 1 };

describe("ItemDetailPanel with the decision area", () => {
  it("shows the box above the warning and no approve/edit/reject row", () => {
    render(<ItemDetailPanel {...props} sel={{ ...sel, warnings: [{ id: "w1", title: "Fixture type needs confirmation", found: "f", why: "w", fix: "x", where: "E-501" }] }} />);
    const box = screen.getByRole("textbox", { name: "What is this?" });
    const warning = screen.getByText("Fixture type needs confirmation");
    expect(box.compareDocumentPosition(warning) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("button", { name: /approve item/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^reject$/i })).not.toBeInTheDocument();
  });

  it("delete lives behind the overflow menu with its confirmation", () => {
    render(<ItemDetailPanel {...props} sel={sel} />);
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /delete item/i }));
    expect(props.onRequestDelete).toHaveBeenCalledWith(sel);
  });

  it("a measured item keeps the length editor and still gets the box", () => {
    render(<ItemDetailPanel {...props} sel={{ ...sel, path: [[0, 0], [10, 10]], unit: "ft", quantity: 120 }} />);
    expect(screen.getByRole("textbox", { name: "What is this?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /edit length/i })).toBeInTheDocument();
  });
});
