/* ============================================================
   Workspace.test.jsx — task-8-brief.md Step 4: the apply-notes banner
   must appear on the review workspace (screen F) exactly when an
   unapplied context note exists on the project, and be absent
   otherwise. Modelled on TakeoffSpreadsheet.test.jsx: useWorkspaceContext
   is mocked directly rather than rendered through the real
   ProjectWorkspaceLayout, since this screen is a plain child of it.

   Unlike NotesWorkspace, this screen never triggers the re-run itself --
   its banner links back to the notes workspace, so there is exactly one
   place a re-run is triggered from (DESIGN.md / ROADMAP.md 2.6).
   ============================================================ */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Workspace from "./Workspace.jsx";

// jsdom has no ResizeObserver -- BlueprintCanvas.jsx uses one to track its
// viewport size, which is real behaviour worth having in this render
// (unlike TakeoffSpreadsheet.test.jsx's table view, this screen mounts the
// canvas), so this is a minimal stand-in rather than mocking the canvas
// away.
class StubResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", StubResizeObserver);

const items = [
  { id: "i1", sheetId: "s1", name: "20A duplex receptacle", description: "Duplex, 20A", system: "Power", category: "Receptacle", quantity: 12, unit: "ea", status: "approved", notes: "", rejected: false, warnings: [], version: 1, symbol: "receptacle" },
];

const baseSnapshot = {
  sheets: [{ id: "s1", number: "E1.1", title: "Level 1 power", superseded: false, scale: "1/8in = 1ft", scaleOptions: [] }],
  items,
  totals: { bySystem: {}, approvedCount: 1, remainingCount: 0, attentionCount: 0, missingCount: 0, approvedUnits: 12 },
  undo: { canUndo: false, canRedo: false, undoLabel: null, undoBy: null, redoLabel: null },
  presence: [],
};

const NOTE = {
  id: "n1",
  projectId: "p1",
  scope: "project",
  scopeRef: null,
  title: "Existing panel LP-2 assumed reused",
  body: "Panel schedule shows LP-2 as existing to remain.",
  category: "existing_condition",
  status: "confirmed",
  rfiNeeded: false,
  usage: "context",
  sourceRef: "",
  obsoleteAfterRevision: "",
  authorName: "Dana Whitfield",
  createdAt: "2026-08-28T10:00:00Z",
  updatedAt: "2026-08-28T10:00:00Z",
  appliedAt: null,
};

let context;

vi.mock("./project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderWorkspace({ notes = [] } = {}) {
  const listNotes = vi.fn().mockResolvedValue(notes);
  context = {
    snapshot: baseSnapshot,
    loading: false,
    loadError: null,
    saved: { state: "saved", at: Date.now() },
    toast: null,
    dismissToast: vi.fn(),
    itemError: null,
    clearItemError: vi.fn(),
    setPresenceTarget: vi.fn(),
    refresh: vi.fn(),
    approveItem: vi.fn(),
    rejectItem: vi.fn(),
    deleteItem: vi.fn(),
    editItem: vi.fn(),
    setScale: vi.fn(),
    undo: vi.fn(),
    redo: vi.fn(),
    me: { id: "u1", name: "Dana Whitfield", color: "#2563eb" },
    sheetId: "s1",
    setSheetId: vi.fn(),
    selectedItemId: null,
    selectItem: vi.fn(),
    project: { id: "p1", name: "Riverside", location: "Riverside, CA" },
    projectId: "p1",
    store: { listNotes },
  };
  const result = render(
    <MemoryRouter>
      <Workspace />
    </MemoryRouter>,
  );
  return { ...result, listNotes };
}

describe("Workspace — apply notes banner", () => {
  it("appears when an unapplied context note exists on the project", async () => {
    renderWorkspace({ notes: [{ ...NOTE, usage: "context", appliedAt: null }] });
    expect(await screen.findByText(/marked to feed the takeoff/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /notes & assumptions/i })).toBeInTheDocument();
  });

  it("is absent when there is no unapplied context note", async () => {
    const { listNotes } = renderWorkspace({ notes: [{ ...NOTE, usage: "reference", appliedAt: null }] });
    // Let the notes fetch resolve before asserting absence.
    await waitFor(() => expect(listNotes).toHaveBeenCalled());
    await Promise.resolve();
    expect(screen.queryByText(/marked to feed the takeoff/i)).not.toBeInTheDocument();
  });

  it("is absent when there are no notes at all", async () => {
    const { listNotes } = renderWorkspace({ notes: [] });
    await waitFor(() => expect(listNotes).toHaveBeenCalled());
    await Promise.resolve();
    expect(screen.queryByText(/marked to feed the takeoff/i)).not.toBeInTheDocument();
  });
});
