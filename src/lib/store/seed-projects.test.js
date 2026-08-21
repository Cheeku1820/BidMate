/* ============================================================
   seed-projects.test.js — final-review fix 2: the fixture project's
   "Updated" value must not be `Date.now()` recomputed on every read.

   Mirrors api/tests/test_projects.py's two new cases for the API side
   of the same fix: the dashboard's "Updated" column must reflect real
   activity (the latest recorded action), not "whenever this row was
   last rendered." Before this fix, seed-projects.js's fixtureProject()
   stamped `updatedAt: new Date().toISOString()` at read time, so the
   fixture always read as touched right now regardless of whether
   anyone had done anything, and always sorted first for a reason that
   had nothing to do with actual activity.

   Both tests pin the system clock with vi.useFakeTimers() and move it
   between calls that perform no mutation, or read well after a
   mutation happened -- a bare "read it twice quickly" assertion would
   pass even against the old Date.now()-at-read-time bug, since two
   real-clock reads back to back can land in the same millisecond by
   luck. Advancing fake time is what actually distinguishes "derived
   from recorded activity" from "whatever time it is right now."
   ============================================================ */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { createSeedStore } from "./seed.js";
import { SEED_PROJECT_ID } from "./seed-projects.js";

describe("seed store fixture project updatedAt", () => {
  // The seed store persists to localStorage, which outlives an individual
  // test, so without this each case inherits the previous one's action
  // stack. That is not merely untidy: it silently defeated the undo case
  // below, which passed against the very bug it was written to catch
  // because a prior test's action was still sitting on the undo stack
  // carrying the same timestamp.
  beforeEach(() => {
    localStorage.clear();
  });

  it("is stable across reads at different points in time when nothing happened in between", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-06-10T00:00:00.000Z"));
      const store = createSeedStore();
      const first = (await store.listProjects()).find((p) => p.id === SEED_PROJECT_ID);

      vi.setSystemTime(new Date("2026-06-10T01:00:00.000Z")); // an hour later, no mutation
      const second = (await store.listProjects()).find((p) => p.id === SEED_PROJECT_ID);

      expect(second.updatedAt).toBe(first.updatedAt);
    } finally {
      vi.useRealTimers();
    }
  });

  it("advances to the action's own recorded timestamp, not to whatever time the dashboard is read at", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-06-10T00:00:00.000Z"));
      const store = createSeedStore();
      const snapshot = await store.getSnapshot();
      const target = snapshot.items.find((i) => i.status === "ready" && !i.rejected);
      expect(target).toBeTruthy();

      vi.setSystemTime(new Date("2026-06-10T02:00:00.000Z")); // the mutation itself
      await store.approveItem(target.id, target.version);

      vi.setSystemTime(new Date("2026-06-15T00:00:00.000Z")); // read happens days later
      const after = (await store.listProjects()).find((p) => p.id === SEED_PROJECT_ID);

      expect(after.updatedAt).toBe(new Date("2026-06-10T02:00:00.000Z").toISOString());
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not travel backwards when the action is undone", async () => {
    // The API's log is append-only, so max(actions.created_at) only ever
    // advances and an undo there appends a compensating action. Reading
    // only the undo stack made the seed side disagree: undo pops the
    // entry onto the redo stack, so "Updated" jumped back to the
    // fixture's creation moment -- a project that had plainly been worked
    // on reporting that nothing had ever happened to it.
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-06-10T00:00:00.000Z"));
      const store = createSeedStore();
      const snapshot = await store.getSnapshot();
      const target = snapshot.items.find((i) => i.status === "ready" && !i.rejected);
      expect(target).toBeTruthy();

      vi.setSystemTime(new Date("2026-06-10T02:00:00.000Z"));
      await store.approveItem(target.id, target.version);
      const afterApprove = (await store.listProjects()).find((p) => p.id === SEED_PROJECT_ID);

      vi.setSystemTime(new Date("2026-06-10T03:00:00.000Z"));
      await store.undo();
      const afterUndo = (await store.listProjects()).find((p) => p.id === SEED_PROJECT_ID);

      expect(afterUndo.updatedAt).toBe(afterApprove.updatedAt);
    } finally {
      vi.useRealTimers();
    }
  });
});
