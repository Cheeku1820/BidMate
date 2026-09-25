/* ============================================================
   ItemDetailPanel.suggestions.test.jsx — the "Suggested from the
   legend" block on an unclassified item (Task 10 of the B3c
   legend-named-clusters plan). Task 8 landed `suggestions` on
   mapItem and made `name` editable through
   editItem(id, { name }, version); this is the visible half: buttons
   built from those suggestions, one click away from renaming the
   whole cluster. No review label, no status colour -- it is not a
   status, just a shortcut into the same rename `edit` already offers.
   ============================================================ */

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ItemDetailPanel from "./ItemDetailPanel.jsx";

const baseProps = {
  sheets: [{ id: "sheet-1", number: "E2.1", revision: "A" }],
  edit: null,
  onStartEdit: () => {},
  onChangeEdit: () => {},
  onSaveEdit: () => {},
  onCancelEdit: () => {},
  onApprove: () => {},
  onReject: () => {},
  onRequestDelete: () => {},
  onShowEvidence: () => {},
  onStep: () => {},
  stepIndex: 1,
  stepCount: 3,
  itemError: null,
  onRefreshItem: () => {},
  onDismissItemError: () => {},
  counts: { attention: 1, approved: 2 },
  itemsTotal: 3,
  onNextIssue: () => {},
  currentSheet: null,
  onAcceptSuggestion: () => {},
};

const unclassified = {
  id: "item-1", symbol: "receptacle", status: "attention", rejected: false,
  name: "Unclassified symbol", description: "An unlabelled cluster of 6 shapes", quantity: 6, unit: "ea",
  system: "Power", category: "", sheetId: "sheet-1", evidence: null,
  aiConfirmed: false, approvedBy: null, notes: "", warnings: [],
  suggestions: [
    { name: "Duplex receptacle", sheet: "E0.1" },
    { name: "GFCI receptacle", sheet: "E0.1" },
  ],
};

describe("ItemDetailPanel — legend suggestions", () => {
  it("renders a button per suggestion, labelled name and sheet", () => {
    render(<ItemDetailPanel {...baseProps} sel={unclassified} />);
    expect(screen.getByText("Suggested from the legend")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Duplex receptacle · from E0.1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "GFCI receptacle · from E0.1" })).toBeInTheDocument();
  });

  it("clicking a suggestion calls onAcceptSuggestion with the item and the suggested name", () => {
    const onAcceptSuggestion = vi.fn();
    render(<ItemDetailPanel {...baseProps} sel={unclassified} onAcceptSuggestion={onAcceptSuggestion} />);
    fireEvent.click(screen.getByRole("button", { name: "Duplex receptacle · from E0.1" }));
    expect(onAcceptSuggestion).toHaveBeenCalledWith(unclassified, "Duplex receptacle");
  });

  it("renders no block for a named item, even if suggestions are present", () => {
    const named = { ...unclassified, name: "Duplex receptacle" };
    render(<ItemDetailPanel {...baseProps} sel={named} />);
    expect(screen.queryByText("Suggested from the legend")).toBeNull();
  });

  it("renders no block for an unclassified item with no suggestions", () => {
    const noSuggestions = { ...unclassified, suggestions: [] };
    render(<ItemDetailPanel {...baseProps} sel={noSuggestions} />);
    expect(screen.queryByText("Suggested from the legend")).toBeNull();
  });

  it("renders no block for an unclassified item with an undefined suggestions field", () => {
    const noSuggestions = { ...unclassified, suggestions: undefined };
    render(<ItemDetailPanel {...baseProps} sel={noSuggestions} />);
    expect(screen.queryByText("Suggested from the legend")).toBeNull();
  });

  it("never shows a percentage, a score, or an AI word", () => {
    const { container } = render(<ItemDetailPanel {...baseProps} sel={unclassified} />);
    expect(container.textContent).not.toMatch(/%|\bAI\b|confidence|score/i);
  });

  it("keeps the panel's accessible name intact", () => {
    render(<ItemDetailPanel {...baseProps} sel={unclassified} />);
    expect(screen.getByLabelText("Selected item")).toBeInTheDocument();
  });
});
