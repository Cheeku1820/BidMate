/* ============================================================
   seed-sample.test.js — attachSampleTakeoff and per-project storage
   isolation.

   Seed mode has no ingestion engine, so a created project is genuinely
   empty. To let the create -> upload -> process -> review -> export loop
   be walked end to end without a real engine, attachSampleTakeoff()
   copies the fixture takeoff into a created project's OWN namespaced
   keys. The rule this file exists to hold: that copy is fully isolated,
   so approving an item in the demo project cannot mutate the real
   Meridian fixture (whose data a reviewer may be trusting for an actual
   bid). The sample is labelled as sample everywhere it surfaces --
   listProjects reports `sample: true` -- so it is never presented as
   derived from a real upload.
   ============================================================ */

import { beforeEach, describe, expect, it } from "vitest";
import { createSeedStore } from "./seed.js";
import { SEED_PROJECT_ID } from "./seed-projects.js";

beforeEach(() => {
  localStorage.clear();
});

async function fixtureSnapshot(store) {
  store.useProject(SEED_PROJECT_ID);
  return store.getSnapshot();
}

describe("attachSampleTakeoff", () => {
  it("a created project is empty until a sample is attached", async () => {
    const store = createSeedStore();
    const project = await store.createProject({ name: "Demo A", location: "Fresno, CA" });

    store.useProject(project.id);
    const before = await store.getSnapshot();
    expect(before.items).toHaveLength(0);
    expect(before.sheets).toHaveLength(0);

    await store.attachSampleTakeoff(project.id);
    const after = await store.getSnapshot();
    expect(after.items.length).toBeGreaterThan(0);
    expect(after.sheets.length).toBeGreaterThan(0);
  });

  it("reports the sampled project on the dashboard with a sample flag and live counts", async () => {
    const store = createSeedStore();
    const project = await store.createProject({ name: "Demo B", location: "Fresno, CA" });
    await store.attachSampleTakeoff(project.id);

    const row = (await store.listProjects({ includeArchived: true })).find((p) => p.id === project.id);
    expect(row.sample).toBe(true);
    expect(row.stage).toBe("review");
    expect(row.itemsTotal).toBeGreaterThan(0);
  });

  it("isolates the demo project: approving in it does not touch the fixture", async () => {
    const store = createSeedStore();
    const project = await store.createProject({ name: "Demo C", location: "Fresno, CA" });
    await store.attachSampleTakeoff(project.id);

    // The fixture and the sample share item ids, since the sample is a
    // copy -- which is exactly why leakage would be invisible without a
    // test. Approve a Ready item in the demo project...
    store.useProject(project.id);
    const demo = await store.getSnapshot();
    const target = demo.items.find((i) => i.status === "ready" && !i.rejected);
    expect(target).toBeTruthy();
    await store.approveItem(target.id, target.version);

    const demoAfter = await store.getSnapshot();
    expect(demoAfter.items.find((i) => i.id === target.id).status).toBe("approved");

    // ...and the same item id in the fixture must be unchanged.
    const fixture = await fixtureSnapshot(store);
    expect(fixture.items.find((i) => i.id === target.id).status).toBe(target.status);
    expect(fixture.items.find((i) => i.id === target.id).status).not.toBe("approved");
  });

  it("undo operates on the demo project's own history, not the fixture's", async () => {
    const store = createSeedStore();
    const project = await store.createProject({ name: "Demo D", location: "Fresno, CA" });
    await store.attachSampleTakeoff(project.id);

    store.useProject(project.id);
    const demo = await store.getSnapshot();
    const target = demo.items.find((i) => i.status === "ready" && !i.rejected);
    const approved = await store.approveItem(target.id, target.version);
    expect(approved.item.status).toBe("approved");

    const undone = await store.undo();
    expect(undone.performed).toBe(true);
    const after = await store.getSnapshot();
    expect(after.items.find((i) => i.id === target.id).status).toBe("ready");
  });

  it("is idempotent: re-attaching a sampled project never wipes review progress", async () => {
    const store = createSeedStore();
    const project = await store.createProject({ name: "Demo E", location: "Fresno, CA" });
    await store.attachSampleTakeoff(project.id);

    store.useProject(project.id);
    const demo = await store.getSnapshot();
    const target = demo.items.find((i) => i.status === "ready" && !i.rejected);
    await store.approveItem(target.id, target.version);

    // A second attach (a direct re-call, or a re-entry the UI guard
    // missed) must not reset the project's items back to the seed.
    await store.attachSampleTakeoff(project.id);

    const after = await store.getSnapshot();
    expect(after.items.find((i) => i.id === target.id).status).toBe("approved");
  });

  it("never overwrites the fixture's own storage", async () => {
    const store = createSeedStore();
    const fixtureBefore = await fixtureSnapshot(store);
    await store.attachSampleTakeoff(SEED_PROJECT_ID);
    const fixtureAfter = await fixtureSnapshot(store);
    expect(fixtureAfter.items).toHaveLength(fixtureBefore.items.length);
  });
});
