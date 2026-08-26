/* ============================================================
   seed.test.js — seed-store-only regression coverage for task-8 review
   finding 1(b): getSnapshot() must not serve the fixture project's
   sheets and items under a *different* project's id.

   This is deliberately not in contract.test.js's shared suite. The
   "api store" variant there runs through api.fakebackend.js, whose
   /api/projects/:id/snapshot handler ignores the :id in the URL and
   always calls the backing seed store's getSnapshot() without first
   telling it which project the request was for (it never calls
   seed.useProject()) -- a pre-existing simplification of that test
   double ("just enough surface for every endpoint api.js actually
   calls", per its own header), not a claim about the real backend.
   Asserting this behavior through the shared suite would either fail
   against that gap or require extending the fake backend to route
   project ids through to the seed store it wraps -- a second, separable
   change this fix does not need. Testing createSeedStore() directly
   here covers the actual fix without depending on that gap closing.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { createSeedStore } from "./seed.js";

describe("seed store project scoping", () => {
  it("defaults to the fixture project before useProject() is called, matching api.js's fallback-to-first-project", async () => {
    const store = createSeedStore();
    const snapshot = await store.getSnapshot();
    expect(snapshot.sheets.length).toBeGreaterThan(0);
    expect(snapshot.items.length).toBeGreaterThan(0);
  });

  it("still serves the fixture once useProject() names the fixture project explicitly", async () => {
    const store = createSeedStore();
    const [fixture] = await store.listProjects();
    store.useProject(fixture.id);
    const snapshot = await store.getSnapshot();
    expect(snapshot.items.length).toBe(fixture.itemsTotal);
  });

  it("returns an honest empty snapshot for a project that isn't the fixture, instead of the fixture's items", async () => {
    const store = createSeedStore();
    const created = await store.createProject({ name: "Riverbend Data Center", location: "Reno, NV" });

    store.useProject(created.id);
    const snapshot = await store.getSnapshot();

    expect(snapshot.sheets).toEqual([]);
    expect(snapshot.items).toEqual([]);
    expect(snapshot.totals).toEqual({
      bySystem: {},
      approvedCount: 0,
      remainingCount: 0,
      attentionCount: 0,
      missingCount: 0,
      approvedUnits: 0,
    });
    expect(snapshot.undo).toEqual({ canUndo: false, canRedo: false, undoLabel: null, undoBy: null, redoLabel: null });
  });

  it("keeps reporting the fixture project's own totals on the dashboard after the workspace last had a different project active", async () => {
    // The cross-consumer regression this fix has to avoid: listProjects()
    // (the dashboard) computes the fixture row's counts through the same
    // getSnapshot() the workspace uses, and that call must not go empty
    // just because a *different* project's workspace was visited most
    // recently and left useProject() pointed at it.
    const store = createSeedStore();
    const before = (await store.listProjects()).find((p) => p.itemsTotal > 0);
    expect(before).toBeTruthy();

    const created = await store.createProject({ name: "Riverbend Data Center", location: "Reno, NV" });
    store.useProject(created.id);
    await store.getSnapshot(); // as Workspace.jsx's useReviewStore would, on mount

    const after = (await store.listProjects()).find((p) => p.id === before.id);
    expect(after.itemsTotal).toBe(before.itemsTotal);
    expect(after.itemsApproved).toBe(before.itemsApproved);
  });
});
