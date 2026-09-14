/* ============================================================
   ItemDetailPanel.aiReading.test.jsx — the no-selection state renders
   `currentSheet.aiReading`, which comes from the sheet's `ai_reading`
   column: unvalidated JSONB a language model produced. A value with no
   `devices` key, or a `devices` that isn't an array, is plausible and
   must not blank the whole review workspace with a TypeError.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ItemDetailPanel from "./ItemDetailPanel.jsx";

const baseProps = {
  sel: null,
  sheets: [],
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
  stepIndex: 0,
  stepCount: 0,
  itemError: null,
  onRefreshItem: () => {},
  onDismissItemError: () => {},
  counts: { ready: 2, approved: 1 },
  itemsTotal: 3,
  onNextIssue: () => {},
};

describe("ItemDetailPanel — aiReading resilience", () => {
  it("renders normal content when aiReading has no devices key", () => {
    const currentSheet = { number: "E2.1", aiReading: { summary: "reads as a power plan" } };
    render(<ItemDetailPanel {...baseProps} currentSheet={currentSheet} />);

    expect(screen.getByText(/reads as a power plan/i)).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 items approved|of 3 items approved/i)).toBeInTheDocument();
  });

  it("renders normal content when devices is present but not an array", () => {
    const currentSheet = { number: "E2.1", aiReading: { summary: "reads as a power plan", devices: "a lot" } };
    render(<ItemDetailPanel {...baseProps} currentSheet={currentSheet} />);

    expect(screen.getByText(/reads as a power plan/i)).toBeInTheDocument();
  });
});
