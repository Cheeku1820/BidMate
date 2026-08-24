/* The layout exists so the blueprint and the spreadsheet are two views
   of one set of records rather than two components each holding their
   own copy. What that buys is asserted directly here: one store
   subscription for the whole project, and a selection both children
   read. */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectWorkspaceLayout from "./ProjectWorkspaceLayout.jsx";
import { useWorkspaceContext } from "./useWorkspaceContext.js";

const snapshot = {
  sheets: [
    { id: "s1", number: "E1.1", title: "Level 1 power", scale: '1/8"', superseded: false },
    { id: "s2", number: "E2.1", title: "Warehouse power", scale: '1/8"', superseded: false },
  ],
  items: [
    { id: "i1", sheetId: "s1", name: "20A duplex receptacle", status: "ready", quantity: 4, unit: "ea", rejected: false, warnings: [], version: 1 },
    { id: "i2", sheetId: "s2", name: "High bay fixture", status: "attention", quantity: 2, unit: "ea", rejected: false, warnings: [], version: 1 },
  ],
  totals: { bySystem: {}, approvedCount: 0, remainingCount: 2, attentionCount: 1, missingCount: 0, approvedUnits: 0 },
  undo: { canUndo: false, canRedo: false, label: null, undoBy: null },
  presence: [],
};

function makeStore() {
  return {
    useProject: vi.fn(),
    getSnapshot: vi.fn().mockResolvedValue(snapshot),
    subscribe: vi.fn().mockReturnValue(() => {}),
    setPresence: vi.fn().mockResolvedValue(undefined),
    me: vi.fn().mockResolvedValue({ id: "u1", name: "Dana Whitfield" }),
  };
}

/** A probe child: renders what the context exposes and can drive it. */
function Probe() {
  const { snapshot: snap, sheetId, selectedItemId, selectItem, projectId } = useWorkspaceContext();
  if (!snap) return <p>loading</p>;
  return (
    <div>
      <p data-testid="project">{projectId}</p>
      <p data-testid="sheet">{sheetId}</p>
      <p data-testid="selected">{selectedItemId ?? "none"}</p>
      <p data-testid="item-count">{snap.items.length}</p>
      <button type="button" onClick={() => selectItem("i2")}>
        Select i2
      </button>
    </div>
  );
}

const renderLayout = (store) =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/takeoff"]}>
      <Routes>
        <Route
          path="/projects/:projectId"
          element={<ProjectWorkspaceLayout store={store} me={{ id: "u1" }} onSignedOut={() => {}} />}
        >
          <Route path="takeoff" element={<Probe />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

describe("ProjectWorkspaceLayout", () => {
  it("points the store at the route's project before fetching anything", async () => {
    const store = makeStore();
    renderLayout(store);
    await screen.findByTestId("item-count");

    expect(store.useProject).toHaveBeenCalledWith("p1");
    const firstUseProject = store.useProject.mock.invocationCallOrder[0];
    const firstFetch = store.getSnapshot.mock.invocationCallOrder[0];
    expect(firstUseProject).toBeLessThan(firstFetch);
  });

  it("hands the snapshot to its child rather than each child fetching its own", async () => {
    const store = makeStore();
    renderLayout(store);

    expect(await screen.findByTestId("item-count")).toHaveTextContent("2");
    expect(screen.getByTestId("project")).toHaveTextContent("p1");
    // One subscription for the whole project, not one per view.
    expect(store.getSnapshot).toHaveBeenCalledTimes(1);
  });

  it("defaults the active sheet to the first one", async () => {
    renderLayout(makeStore());
    expect(await screen.findByTestId("sheet")).toHaveTextContent("s1");
  });

  it("follows a selection onto the sheet the item lives on", async () => {
    // Selecting a row for an item on another sheet has to bring the
    // blueprint with it, or the two views disagree about what is being
    // looked at (DESIGN.md, "Blueprint and table synchronization").
    renderLayout(makeStore());
    await screen.findByTestId("item-count");

    await userEvent.click(screen.getByRole("button", { name: /select i2/i }));

    expect(screen.getByTestId("selected")).toHaveTextContent("i2");
    expect(screen.getByTestId("sheet")).toHaveTextContent("s2");
  });
});
