/* ============================================================
   TakeoffSpreadsheet.saveState.test.jsx — this screen mutates (bulk
   approve), so it owes the estimator the same two feedback surfaces
   every other screen shows: the save-state indicator in the top bar
   and a five-second undoable toast per action (DESIGN.md, "Autosave and
   save status" / "Undo semantics"; CLAUDE.md, "No save buttons ...
   save state in the top bar and an undoable toast per action").

   The blueprint workspace renders both off the one shared store
   subscription. The spreadsheet reads that same subscription through
   useWorkspaceContext(), so it can and must render the same two. Before
   this coverage the screen mutated silently -- bulkApprove called
   showToast on the store, but nothing on this view displayed it, and
   AppTopBar got no saveState.
   ============================================================ */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import TakeoffSpreadsheet from "./TakeoffSpreadsheet.jsx";

const items = [
  { id: "i1", sheetId: "s1", name: "Receptacle A", description: "", system: "Power", quantity: 1, unit: "ea", status: "ready", notes: "", rejected: false, warnings: [], version: 1 },
];

const context = {
  snapshot: {
    sheets: [{ id: "s1", number: "E1.1", title: "Level 1 power", superseded: false }],
    items,
    totals: { bySystem: {}, approvedCount: 0, remainingCount: 1, attentionCount: 0, missingCount: 0, approvedUnits: 0 },
    undo: { canUndo: true, canRedo: false, label: "Approved 2 items", undoBy: null },
    presence: [],
  },
  loading: false,
  loadError: null,
  selectedItemId: null,
  selectItem: vi.fn(),
  sheetId: "s1",
  setSheetId: vi.fn(),
  bulkApprove: vi.fn().mockResolvedValue({ approved: ["i1"], skipped: [], snapshot: null }),
  projectId: "p1",
  // The three feedback surfaces this screen must render off the shared
  // store subscription.
  saved: { state: "saved", at: Date.parse("2026-08-25T15:00:00Z") },
  toast: { text: "Approved 2 items" },
  dismissToast: vi.fn(),
  undo: vi.fn(),
};

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

const renderSheet = () =>
  render(
    <MemoryRouter>
      <TakeoffSpreadsheet />
    </MemoryRouter>,
  );

beforeEach(() => {
  context.undo.mockClear();
  context.dismissToast.mockClear();
});

describe("save state and undoable toast on the takeoff spreadsheet", () => {
  it("shows the shared save-state indicator in the top bar", () => {
    renderSheet();
    // Not "Saving…" and not the retry copy -- the settled "Saved <time>"
    // state, the same string TopBar.jsx renders for the blueprint.
    expect(screen.getByText(/^Saved /)).toBeTruthy();
  });

  it("renders the undoable toast, and Undo reverses through the shared stack then dismisses", async () => {
    renderSheet();

    expect(screen.getByText("Approved 2 items")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /undo/i }));

    // Undo must go through the same store undo the blueprint's toast
    // uses (one action reversed off the shared stack), and the toast
    // dismisses after -- both, in that order.
    expect(context.undo).toHaveBeenCalledTimes(1);
    expect(context.dismissToast).toHaveBeenCalledTimes(1);
  });
});
