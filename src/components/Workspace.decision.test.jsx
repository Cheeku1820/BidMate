/* ============================================================
   Workspace.decision.test.jsx — task-8-brief.md Step 1: the workspace's
   key handler no longer calls approveItem/rejectItem directly. A/E/R
   dispatch a "decision-cmd" window event that DecisionArea (mounted
   inside ItemDetailPanel) listens for, and the existing "typing" guard
   keeps those keys inert while the box itself has focus.

   Harness copied from Workspace.test.jsx: useWorkspaceContext is mocked
   directly and a fixed context object stands in for
   ProjectWorkspaceLayout, with a "ready" item pre-selected so
   ItemDetailPanel renders DecisionArea rather than the review-progress
   summary.
   ============================================================ */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Workspace from "./Workspace.jsx";

class StubResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", StubResizeObserver);

const items = [
  {
    id: "i1", sheetId: "s1", name: "20A duplex receptacle", description: "Duplex, 20A",
    system: "Power", category: "Receptacle", quantity: 12, unit: "ea", status: "ready",
    notes: "", rejected: false, warnings: [], version: 1, symbol: "receptacle",
  },
];

const baseSnapshot = {
  sheets: [{ id: "s1", number: "E1.1", title: "Level 1 power", superseded: false, scale: "1/8in = 1ft", scaleOptions: [], takeoffId: "t1", pageIndex: 0 }],
  items,
  totals: { bySystem: {}, approvedCount: 0, remainingCount: 1, attentionCount: 0, missingCount: 0, approvedUnits: 0 },
  undo: { canUndo: false, canRedo: false, undoLabel: null, undoBy: null, redoLabel: null },
  presence: [],
};

let context;

vi.mock("./project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderWorkspace() {
  const listNotes = vi.fn().mockResolvedValue([]);
  const resolveItem = vi.fn().mockResolvedValue({
    intent: "unknown", targetItemIds: ["i1"], name: "", system: "", category: "",
    unit: "ea", summary: "", source: "read", versions: {},
  });
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
    applyProposal: vi.fn(),
    me: { id: "u1", name: "Dana Whitfield", color: "#2563eb" },
    sheetId: "s1",
    setSheetId: vi.fn(),
    selectedItemId: "i1",
    selectItem: vi.fn(),
    project: { id: "p1", name: "Riverside", location: "Riverside, CA" },
    projectId: "p1",
    store: { listNotes, resolveItem },
  };
  render(
    <MemoryRouter>
      <Workspace />
    </MemoryRouter>,
  );
  return { resolveItem };
}

function press(key) {
  const evt = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
  window.dispatchEvent(evt);
}

describe("Workspace — decision-cmd keys", () => {
  it("on a classified item the box renders unfocused and J steps without being swallowed", async () => {
    renderWorkspace();
    const box = await screen.findByRole("textbox", { name: "What is this?" });
    expect(document.activeElement).not.toBe(box);

    press("j");

    expect(context.selectItem).toHaveBeenCalledWith("i1");
    expect(box).toHaveValue("");
  });

  it('pressing "a" with the box empty on a Ready item resolves the item by name', async () => {
    const { resolveItem } = renderWorkspace();
    // A classified item: the box renders unfocused, so "a" is a shortcut.
    const box = await screen.findByRole("textbox", { name: "What is this?" });
    expect(document.activeElement).not.toBe(box);

    press("a");

    await waitFor(() => expect(resolveItem).toHaveBeenCalledWith("i1", "20A duplex receptacle"));
  });

  it('pressing "r" resolves with "Not a device"', async () => {
    const { resolveItem } = renderWorkspace();
    const box = await screen.findByRole("textbox", { name: "What is this?" });
    box.blur();

    press("r");

    await waitFor(() => expect(resolveItem).toHaveBeenCalledWith("i1", "Not a device"));
  });

  it('pressing "e" focuses #decision-box', async () => {
    renderWorkspace();
    const box = await screen.findByRole("textbox", { name: "What is this?" });
    box.blur();
    expect(document.activeElement.id).not.toBe("decision-box");

    press("e");

    await waitFor(() => expect(document.activeElement.id).toBe("decision-box"));
  });

  it("keys are ignored while the box has focus", async () => {
    const { resolveItem } = renderWorkspace();
    const box = await screen.findByRole("textbox", { name: "What is this?" });
    box.focus();
    expect(document.activeElement).toBe(box);

    const evt = new KeyboardEvent("keydown", { key: "a", bubbles: true, cancelable: true });
    box.dispatchEvent(evt);

    expect(resolveItem).not.toHaveBeenCalled();
  });
});
