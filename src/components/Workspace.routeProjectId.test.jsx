/* ============================================================
   Workspace.routeProjectId.test.jsx — pins the one ordering guarantee
   this task's highest-risk change rests on: store.useProject(projectId)
   must land before the first store.getSnapshot() call, or every review
   mutation on first paint resolves against whatever project the store
   was last pointed at (nothing, on a fresh store) rather than the one
   named in the URL.

   This was originally verified with a throwaway version of this test,
   then deleted before the first commit — a mistake. The guarantee is
   real (Workspace.jsx wraps the workspace in a component keyed by
   projectId and calls store.useProject() from the first effect declared
   in that component, ahead of useReviewStore's own fetch effect — see
   that file's comments), but it currently rests on hook-declaration
   order inside a ~300-line component. Nothing else would catch a future
   reordering that broke it silently. This test is that catch.
   ============================================================ */

import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Workspace from "./Workspace.jsx";

function emptySnapshot() {
  return {
    version: "1",
    sheets: [],
    items: [],
    totals: { missingCount: 0, attentionCount: 0, remainingCount: 0, approvedCount: 0, approvedUnits: 0 },
    undo: { canUndo: false, canRedo: false },
    presence: [],
  };
}

function renderWorkspaceAt(path) {
  const calls = [];
  const store = {
    useProject: (id) => calls.push(["useProject", id]),
    getSnapshot: async () => {
      calls.push(["getSnapshot"]);
      return emptySnapshot();
    },
    subscribe: () => () => {},
    setPresence: async () => {},
  };
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/projects/:projectId/takeoff"
          element={<Workspace store={store} me={{ id: "u1", name: "Dana Whitfield" }} onSignedOut={() => {}} />}
        />
      </Routes>
    </MemoryRouter>,
  );
  return calls;
}

describe("Workspace route project id ordering", () => {
  it("calls store.useProject with the route's id before the first getSnapshot", async () => {
    const calls = renderWorkspaceAt("/projects/proj-9/takeoff");
    await vi.waitFor(() => expect(calls.some((c) => c[0] === "getSnapshot")).toBe(true));

    const firstUseProject = calls.findIndex((c) => c[0] === "useProject");
    const firstGetSnapshot = calls.findIndex((c) => c[0] === "getSnapshot");

    expect(firstUseProject).toBe(0);
    expect(calls[firstUseProject]).toEqual(["useProject", "proj-9"]);
    expect(firstUseProject).toBeLessThan(firstGetSnapshot);
  });

  it("still sets the id first for a different project id, proving this isn't a first-render fluke", async () => {
    const calls = renderWorkspaceAt("/projects/proj-27/takeoff");
    await vi.waitFor(() => expect(calls.some((c) => c[0] === "getSnapshot")).toBe(true));

    expect(calls[0]).toEqual(["useProject", "proj-27"]);
  });
});
