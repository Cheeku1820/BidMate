/* ============================================================
   ItemDetailPanel.warnings.test.jsx — the warning card's internal
   hierarchy (grounded-classification-warnings-design.md, section C):
   found as the lead statement, why as a supporting line, fix pulled out
   as the one instruction, where treated as a citation. Never touches
   the shared .warncard/.warncard--missing/.warncard--attention base
   classes other screens also use.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
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
};

const sel = {
  id: "item-1", symbol: "luminaire", status: "attention", rejected: false,
  name: "Luminaire type F2", description: "Type F2 luminaire", quantity: 3, unit: "ea",
  system: "Lighting", category: "Fixtures", sheetId: "sheet-1", evidence: null,
  aiConfirmed: false, approvedBy: null, notes: "",
  warnings: [{
    id: "w1", title: "Fixture type needs confirmation",
    found: "Type F2 appears 3 times on E2.1, but the schedule only lists types A-E.",
    why: "F2's exact fixture and price depend on which schedule entry it matches.",
    fix: "Check the luminaire schedule for a type F2 entry.",
    where: "E2.1 and the luminaire schedule.",
  }],
};

describe("ItemDetailPanel — warning card", () => {
  it("renders found, why, fix, and where as distinct, separately styled elements", () => {
    render(<ItemDetailPanel {...baseProps} sel={sel} />);

    const found = screen.getByText(sel.warnings[0].found);
    expect(found).toHaveClass("warncard__found");

    const why = screen.getByText(sel.warnings[0].why);
    expect(why).toHaveClass("warncard__why");

    expect(screen.getByText("What to do")).toBeInTheDocument();
    const fix = screen.getByText(sel.warnings[0].fix);
    expect(fix.closest(".warncard__fix")).not.toBeNull();

    const where = screen.getByText(sel.warnings[0].where);
    expect(where).toHaveClass("warncard__where");
  });

  it("renders every warning when an item carries more than one", () => {
    const twoWarnings = {
      ...sel,
      warnings: [sel.warnings[0], { ...sel.warnings[0], id: "w2", title: "Scale needs confirmation" }],
    };
    render(<ItemDetailPanel {...baseProps} sel={twoWarnings} />);
    expect(screen.getAllByText(sel.warnings[0].found)).toHaveLength(2);
  });
});
