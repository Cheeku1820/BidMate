/* ============================================================
   Workspace.undoScoping.test.jsx — final-review fix 1: a keystroke
   fired while a *different*, sheet-less project is open must not
   mutate the fixture project's data.

   Workspace.jsx's undo/redo keydown handler is registered by a plain
   useEffect declared above the component's `loadError || !sheet` early
   return (line ~195). Hooks run in declaration order every render
   regardless of what the function ultimately returns, so that listener
   is live even on a project with no sheets — and seed-undo.js's
   undo()/redo() read and write the shared `items` / `sheets` / `hist`
   localStorage keys with no awareness of which project is active. The
   result: pressing Ctrl/Cmd+Z on an empty, newly created project pops
   the *fixture* project's shared history stack and silently reverses
   whatever action sits on top of it — including an approval — with no
   toast, because the early-return branch never mounts the toast markup
   in the first place.

   This test renders the real Workspace component against a real
   createSeedStore() (not a mock — the review specifically flagged that
   no test exercised Workspace against a real seed store), approves an
   item on the fixture project to put a real entry on the shared undo
   stack, opens a freshly created (non-fixture) project with no sheets,
   fires the undo keystroke, and asserts the fixture's approval survives
   untouched.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Workspace from "./Workspace.jsx";
import ProjectWorkspaceLayout from "./project/ProjectWorkspaceLayout.jsx";
import { createSeedStore } from "../lib/store/seed.js";
import { SEED_PROJECT_ID } from "../lib/store/seed-projects.js";

function renderWorkspaceAt(store, path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/projects/:projectId"
          element={<ProjectWorkspaceLayout store={store} me={{ id: "u1", name: "Dana Whitfield" }} onSignedOut={() => {}} />}
        >
          <Route path="takeoff" element={<Workspace />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("Workspace undo project scoping", () => {
  it("does not let a keystroke on a sheet-less project reverse an approval on the fixture project", async () => {
    const store = createSeedStore();

    // Put a real entry on the shared undo stack by approving a
    // ready-to-review item on the fixture project.
    const fixtureSnapshot = await store.getSnapshot();
    const target = fixtureSnapshot.items.find((i) => i.status === "ready" && !i.rejected);
    expect(target).toBeTruthy();
    const approveResult = await store.approveItem(target.id, target.version);
    expect(approveResult.item.status).toBe("approved");

    // Open a brand-new, sheet-less project — the state that used to
    // return early in Workspace before the undo listener could be
    // gated on it.
    const created = await store.createProject({ name: "Riverbend Data Center", location: "Reno, NV" });
    renderWorkspaceAt(store, `/projects/${created.id}/takeoff`);
    await screen.findByText(/this project has no sheets yet/i);

    // The regression: Ctrl/Cmd+Z fired here used to pop the fixture
    // project's shared history and un-approve `target`.
    fireEvent.keyDown(window, { key: "z", ctrlKey: true });

    // Give the async doUndo()/store.undo() round trip a tick to settle,
    // then confirm nothing on the fixture project moved.
    await waitFor(async () => {
      store.useProject(SEED_PROJECT_ID);
      const after = await store.getSnapshot();
      const stillTarget = after.items.find((i) => i.id === target.id);
      expect(stillTarget.status).toBe("approved");
      expect(after.undo.canUndo).toBe(true);
    });
  });
});
