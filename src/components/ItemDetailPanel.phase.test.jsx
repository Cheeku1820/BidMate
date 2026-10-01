import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ItemDetailPanel from "./ItemDetailPanel.jsx";

const props = {
  sheets: [{ id: "s1", number: "EP101", revision: "Rev 1", phaseId: "p1" }],
  currentSheet: null, edit: null,
  onStartEdit: vi.fn(), onChangeEdit: vi.fn(), onSaveEdit: vi.fn(), onCancelEdit: vi.fn(), onRequestDelete: vi.fn(),
  onShowEvidence: vi.fn(), onStep: vi.fn(), stepIndex: 1, stepCount: 3, itemError: null, onRefreshItem: vi.fn(),
  onDismissItemError: vi.fn(), counts: { attention: 1 }, itemsTotal: 3, onNextIssue: vi.fn(),
  onResolve: vi.fn(), onApplyProposal: vi.fn(), onUndo: vi.fn(), onSelectItem: vi.fn(), alsoMatchingItemId: null,
};

const sel = {
  id: "i1", symbol: "receptacle", status: "ready", rejected: false, name: "20A duplex receptacle",
  description: "", quantity: 14, unit: "ea", system: "Power", category: "Devices", sheetId: "s1",
  evidence: null, aiConfirmed: true, approvedBy: null, notes: "", warnings: [], sourceTag: "R",
  path: null, version: 1, phaseId: "p1", phaseOverridden: false,
};

const twoPhases = [{ id: "p1", name: "E sheets" }, { id: "p2", name: "XE sheets" }];

describe("the item panel's phase field", () => {
  it("is absent while the project has one phase", () => {
    render(<ItemDetailPanel {...props} sel={sel} phases={[twoPhases[0]]} />);
    expect(screen.queryByLabelText("Phase")).not.toBeInTheDocument();
  });

  it("appears with a second phase, defaulting to the sheet's", () => {
    render(<ItemDetailPanel {...props} sel={sel} phases={twoPhases} />);
    const field = screen.getByLabelText("Phase");
    expect(field).toHaveValue("");
    expect(screen.getByRole("option", { name: "From its sheet (E sheets)" })).toBeInTheDocument();
  });

  it("moves an item to another phase, and says where it came from", () => {
    const onSetItemPhase = vi.fn();
    const { rerender } = render(
      <ItemDetailPanel {...props} sel={sel} phases={twoPhases} onSetItemPhase={onSetItemPhase} />,
    );
    fireEvent.change(screen.getByLabelText("Phase"), { target: { value: "p2" } });
    expect(onSetItemPhase).toHaveBeenCalledWith("i1", "p2");

    rerender(
      <ItemDetailPanel
        {...props}
        sel={{ ...sel, phaseId: "p2", phaseOverridden: true }}
        phases={twoPhases}
        onSetItemPhase={onSetItemPhase}
      />,
    );
    expect(screen.getByLabelText("Phase")).toHaveValue("p2");
    expect(screen.getByText(/moved from E sheets/)).toBeInTheDocument();
  });

  it("returns an overridden item to its sheet's phase", () => {
    const onSetItemPhase = vi.fn();
    render(
      <ItemDetailPanel
        {...props}
        sel={{ ...sel, phaseId: "p2", phaseOverridden: true }}
        phases={twoPhases}
        onSetItemPhase={onSetItemPhase}
      />,
    );
    fireEvent.change(screen.getByLabelText("Phase"), { target: { value: "" } });
    expect(onSetItemPhase).toHaveBeenCalledWith("i1", null);
  });
});
