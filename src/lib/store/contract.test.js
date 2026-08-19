/* ============================================================
   contract.test.js — pins the store interface Task 16's api.js must
   also satisfy: camelCase field names throughout, `warnings` as an
   array (never collapsed to a singular field — task-15-brief.md,
   decision 2), and the review rules from BUILD-STAGES.md that must
   never regress, mirrored client-side.
   ============================================================ */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { createSeedStore } from "./seed.js";
import { createApiStore } from "./api.js";
import { storageWrite } from "./local-transport.js";
import { installFakeApiBackend } from "./api.fakebackend.js";

const METHODS = [
  "me", "getSnapshot", "subscribe", "setPresence",
  "approveItem", "rejectItem", "unrejectItem", "editItem",
  "deleteItem", "setScale", "undo", "redo",
  "listProjects", "createProject",
];

/* Every assertion below runs twice: once directly against
   createSeedStore(), and once against createApiStore() with `fetch`
   stubbed to api.fakebackend.js's translation of the same seed store
   (task-16-brief.md §5, "extend the existing contract suite so both
   stores run the shared shape assertions"). The seed store IS the
   ground truth for these rules (concurrency, scale release, bulk
   exclusion, the camelCase/array/number contract); running the same
   assertions through api.js's request/response mapping is what proves
   that mapping preserves them, rather than merely checking that
   api.js's methods exist. */
function defineContractSuite(label, setup) {
describe(label, () => {
  let store;
  beforeEach(() => {
    localStorage.clear();
    store = setup();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("implements every method in the store interface", () => {
    for (const method of METHODS) expect(typeof store[method]).toBe("function");
  });

  it("returns a snapshot shaped like the API's", async () => {
    const snapshot = await store.getSnapshot();
    expect(Object.keys(snapshot).sort()).toEqual(
      ["items", "presence", "sheets", "totals", "undo", "version"]
    );
  });

  it("exposes camelCase field names, not the API's snake_case", async () => {
    const { items, sheets, totals, undo } = await store.getSnapshot();
    const item = items[0];
    // A handful of the fields the brief names explicitly as the snake_case
    // -> camelCase mapping api.js (Task 16) must perform at the boundary.
    expect(item).toHaveProperty("sheetId");
    expect(item).not.toHaveProperty("sheet_id");
    expect(item).toHaveProperty("approvedBy");
    expect(item).not.toHaveProperty("approved_by");
    const sheet = sheets.find((s) => s.scaleOptions.length);
    expect(sheet).toHaveProperty("scaleOptions");
    expect(sheet).not.toHaveProperty("scale_options");
    expect(totals).toHaveProperty("approvedUnits");
    expect(totals).not.toHaveProperty("approved_units");
    expect(undo).toHaveProperty("canUndo");
    expect(undo).not.toHaveProperty("can_undo");
  });

  it("exposes warnings as an array, never a singular field", async () => {
    const { items } = await store.getSnapshot();
    // it-02 is data.js's scale-conflicted conduit run -- carries exactly
    // one warning, but as a one-element array, not a bare object.
    const withOneWarning = items.find((i) => i.id === "it-02");
    expect(Array.isArray(withOneWarning.warnings)).toBe(true);
    expect(withOneWarning.warnings).toHaveLength(1);
    expect(withOneWarning.warnings[0]).toMatchObject({ title: "Scale needs confirmation", reason: "scale" });
    expect(withOneWarning).not.toHaveProperty("warning");

    // it-01 has no warning in data.js -- null becomes [], not omitted.
    const withNoWarning = items.find((i) => i.id === "it-01");
    expect(withNoWarning.warnings).toEqual([]);
  });

  it("exposes quantities and totals as numbers, not Decimal-as-string", async () => {
    const { items, totals } = await store.getSnapshot();
    const item = items.find((i) => i.id === "it-03");
    expect(typeof item.quantity).toBe("number");
    expect(typeof totals.approvedUnits).toBe("number");
    // If this were a string, "900" < "1000" is false -- the lexical-vs-
    // numeric bug task-15-brief.md calls out by name. Pin the concrete
    // value (it-01 qty 1 + it-08 qty 38, the fixture's two approved
    // items) so a regression back to strings fails loudly here.
    expect(totals.approvedUnits).toBe(39);
  });

  it("presence entries carry seenAt as epoch milliseconds, not the API's ISO-8601 string", async () => {
    // getSnapshot()'s presence excludes the caller's own identity
    // (activePresence's `exclude`, mirroring api/app/collab/service.py's
    // active_presence()), so an entry has to come from someone else --
    // write one directly, the way a second reviewer's heartbeat would
    // land in the same localStorage a real browser tab would share.
    storageWrite("presence:u_other", {
      userId: "u_other",
      name: "Riley Ashworth",
      color: "#6b3fa0",
      sheetId: "E2.1",
      itemId: "it-03",
      seenAt: Date.now(),
    });
    storageWrite("presence-index", ["u_other"]);

    const { presence } = await store.getSnapshot();
    expect(presence).toHaveLength(1);
    const [entry] = presence;
    expect(entry).toMatchObject({
      userId: "u_other",
      name: "Riley Ashworth",
      color: "#6b3fa0",
      sheetId: "E2.1",
      itemId: "it-03",
    });
    // The type this pins: a number (epoch ms), never a string. An
    // ISO-8601 string here would make activePresence()'s
    // `now - p.seenAt < ACTIVE_WINDOW_MS` comparison NaN silently --
    // no throw, the entry just never expires or never shows up.
    expect(typeof entry.seenAt).toBe("number");
  });

  it("refuses to approve a missing information item", async () => {
    const { items } = await store.getSnapshot();
    const blocked = items.find((i) => i.status === "missing");
    await expect(store.approveItem(blocked.id, blocked.version)).rejects.toMatchObject({
      code: "missing_information_blocks_approval",
    });
  });

  it("does not count rejected items in totals", async () => {
    const before = (await store.getSnapshot()).totals.approvedUnits;
    const { items } = await store.getSnapshot();
    const approved = items.find((i) => i.status === "approved");
    await store.rejectItem(approved.id, approved.version);
    const after = (await store.getSnapshot()).totals.approvedUnits;
    expect(after).toBeLessThan(before);
  });

  it("items carry a numeric version for optimistic concurrency, starting at 1", async () => {
    const { items } = await store.getSnapshot();
    for (const i of items) {
      expect(typeof i.version).toBe("number");
      expect(i.version).toBeGreaterThanOrEqual(1);
    }
  });

  it("refuses a stale version with the same code the API uses (task-13b-brief.md)", async () => {
    const { items } = await store.getSnapshot();
    const readyItem = items.find((i) => i.status === "ready");

    await expect(store.approveItem(readyItem.id, readyItem.version + 1)).rejects.toMatchObject({
      code: "stale_item_version",
    });

    // Refused, so nothing actually moved -- proving the refusal short-
    // circuits before mutation, not after.
    const after = await store.getSnapshot();
    const stillThere = after.items.find((i) => i.id === readyItem.id);
    expect(stillThere.status).toBe("ready");
    expect(stillThere.version).toBe(readyItem.version);
  });

  it("a correct version succeeds and the response carries the new version, so a client can chain writes without refetching", async () => {
    const { items } = await store.getSnapshot();
    const readyItem = items.find((i) => i.status === "ready");

    const first = await store.editItem(readyItem.id, { notes: "first" }, readyItem.version);
    expect(first.item.version).toBe(readyItem.version + 1);

    // Chained directly off the previous result, never off a fresh
    // getSnapshot() -- the point of returning the new version at all.
    const second = await store.editItem(readyItem.id, { notes: "second" }, first.item.version);
    expect(second.item.notes).toBe("second");
    expect(second.item.version).toBe(first.item.version + 1);
  });

  it("undo bumps a reverted item's version forward rather than restoring the old one", async () => {
    const { items } = await store.getSnapshot();
    const readyItem = items.find((i) => i.status === "ready");
    const originalVersion = readyItem.version;

    const approveResult = await store.approveItem(readyItem.id, originalVersion);
    const versionAfterApprove = approveResult.item.version;
    expect(versionAfterApprove).toBe(originalVersion + 1);

    await store.undo();

    const afterUndo = await store.getSnapshot();
    const reverted = afterUndo.items.find((i) => i.id === readyItem.id);
    expect(reverted.status).toBe("ready");
    expect(reverted.version).toBe(versionAfterApprove + 1);
    expect(reverted.version).not.toBe(originalVersion);

    // The concrete consequence: a version held from right after the
    // approve is now stale, not merely different.
    await expect(
      store.rejectItem(readyItem.id, versionAfterApprove)
    ).rejects.toMatchObject({ code: "stale_item_version" });
  });

  it("setting a scale releases the blocked items on that sheet only", async () => {
    const { items, sheets } = await store.getSnapshot();
    const sheet = sheets.find((s) => s.scale === "none");
    await store.setScale(sheet.id, '1/8" = 1\'-0"');
    const updated = (await store.getSnapshot()).items;
    const onSheet = updated.filter((i) => i.sheetId === sheet.id);
    expect(onSheet.every((i) => i.status !== "missing")).toBe(true);
  });

  it("setScale is out of scope for the version CHECK but still bumps released items' version, so a later single-item edit is not fooled by a stale counter", async () => {
    const before = await store.getSnapshot();
    const sheet = before.sheets.find((s) => s.scale === "none");
    const blockedBefore = before.items.filter((i) => i.sheetId === sheet.id && i.status === "missing");
    const versionsBefore = Object.fromEntries(blockedBefore.map((i) => [i.id, i.version]));

    await store.setScale(sheet.id, '1/8" = 1\'-0"');

    const after = await store.getSnapshot();
    for (const item of blockedBefore) {
      const released = after.items.find((i) => i.id === item.id);
      expect(released.version).toBe(versionsBefore[item.id] + 1);
    }
  });

  it("setScale releases only scale-blocked items — an item blocked for a different reason on the same sheet stays blocked", async () => {
    // E2.1 carries both: it-02, Missing information from a scale warning,
    // and it-07, Needs attention from a legend warning (an unclassified
    // symbol). A setScale implementation that naively clears every
    // warning on the sheet -- rather than filtering by Warning.reason,
    // the way scale.py does -- would wrongly touch it-07 too.
    const before = await store.getSnapshot();
    const legendBlocked = before.items.find((i) => i.id === "it-07");
    expect(legendBlocked.status).toBe("attention");
    expect(legendBlocked.warnings).toHaveLength(1);
    expect(legendBlocked.warnings[0].reason).toBe("legend");

    await store.setScale("E2.1", '1/16" = 1\'-0"');

    const after = await store.getSnapshot();
    const stillLegendBlocked = after.items.find((i) => i.id === "it-07");
    expect(stillLegendBlocked.status).toBe("attention");
    expect(stillLegendBlocked.warnings).toHaveLength(1);
    expect(stillLegendBlocked.warnings[0].reason).toBe("legend");

    // it-02, the scale-blocked item on the same sheet, does get released.
    const releasedScaleItem = after.items.find((i) => i.id === "it-02");
    expect(releasedScaleItem.status).toBe("ready");
    expect(releasedScaleItem.warnings).toEqual([]);
  });

  it("layer toggles never change totals — totals are computed from every item, independent of what a component chooses to render", async () => {
    const { items, totals } = await store.getSnapshot();
    // Simulate a component hiding approved items to reduce clutter, purely
    // as a local, client-side render filter -- the kind of thing
    // BlueprintCanvas.jsx's `layers` prop does. This must have no way to
    // reach the store's own totals computation (invariant 3).
    const hidingApproved = items.filter((i) => i.status !== "approved");
    expect(hidingApproved.length).toBeLessThan(items.length);

    const manualApprovedUnits = items
      .filter((i) => i.status === "approved" && !i.rejected)
      .reduce((sum, i) => sum + i.quantity, 0);
    expect(totals.approvedUnits).toBe(manualApprovedUnits);
    expect(totals.approvedUnits).toBe(39);
    expect(totals.approvedCount).toBe(2);
  });

  it("undo reverses a scale confirmation as one step, not one per released item", async () => {
    const before = await store.getSnapshot();
    const sheet = before.sheets.find((s) => s.scale === "none"); // E1.1
    const blockedBefore = before.items.filter((i) => i.sheetId === sheet.id && i.status === "missing");
    expect(blockedBefore.length).toBeGreaterThan(0);

    await store.setScale(sheet.id, '1/8" = 1\'-0"');
    const afterSet = await store.getSnapshot();
    expect(afterSet.undo.canUndo).toBe(true);
    // Exactly one undo entry recorded for the whole compound action.
    expect(afterSet.undo.undoLabel).toMatch(/^Set scale on E1\.1/);

    const result = await store.undo();
    expect(result.performed).toBe(true);

    const afterUndo = await store.getSnapshot();
    const restoredSheet = afterUndo.sheets.find((s) => s.id === sheet.id);
    expect(restoredSheet.scale).toBe("none");
    const restoredItems = afterUndo.items.filter((i) => i.sheetId === sheet.id && i.status === "missing");
    expect(restoredItems.map((i) => i.id).sort()).toEqual(blockedBefore.map((i) => i.id).sort());
    // Every released item's warning came back too -- undo restores the
    // evidence the scale confirmation had cleared, not just the status.
    for (const item of restoredItems) {
      expect(item.warnings.length).toBeGreaterThan(0);
    }
  });

  it("every store method can actually be called without a reference error — a typo'd method that exists but throws is not implemented", async () => {
    const snap = await store.getSnapshot();
    const readyItem = snap.items.find((i) => i.status === "ready");
    const anotherReadyItem = snap.items.filter((i) => i.status === "ready")[1];
    const sheet = snap.sheets[0];
    const originalScale = sheet.scale;
    const scaleValue = sheet.scaleOptions[0] ?? "nts";

    await expect(store.me()).resolves.toMatchObject({
      id: expect.any(String),
      name: expect.any(String),
      email: expect.any(String),
      color: expect.any(String),
    });

    const unsubscribe = store.subscribe(() => {});
    expect(typeof unsubscribe).toBe("function");
    unsubscribe();

    await store.setPresence({ sheetId: sheet.id, itemId: readyItem.id });

    const approveResult = await store.approveItem(readyItem.id, readyItem.version);
    expect(approveResult.item.status).toBe("approved");

    const rejectResult = await store.rejectItem(anotherReadyItem.id, anotherReadyItem.version);
    expect(rejectResult.item.rejected).toBe(true);

    // Each call below chains off the previous result's returned version
    // -- readyItem/anotherReadyItem's own `.version` is now stale, the
    // same reason a real client must not refetch to keep going.
    const unrejectResult = await store.unrejectItem(anotherReadyItem.id, rejectResult.item.version);
    expect(unrejectResult.item.rejected).toBe(false);

    const editResult = await store.editItem(
      anotherReadyItem.id, { notes: "checked against E1.1" }, unrejectResult.item.version
    );
    expect(editResult.item.notes).toBe("checked against E1.1");

    const deleteResult = await store.deleteItem(anotherReadyItem.id, editResult.item.version);
    expect(deleteResult.item).toBeNull();

    // Captured immediately before setScale, not from `snap` at the top of
    // this test -- the mutations above touched other items, not this
    // sheet, but reading fresh keeps this assertion honest either way.
    const beforeScale = await store.getSnapshot();
    const blockedBefore = beforeScale.items.filter((i) => i.sheetId === sheet.id && i.status === "missing");

    const scaleResult = await store.setScale(sheet.id, scaleValue);
    expect(scaleResult.snapshot.version).toEqual(expect.any(String));

    const undoResult = await store.undo();
    expect(undoResult.performed).toBe(true);
    // Full state, mirroring the "undo reverses a scale confirmation"
    // test above -- performed === true alone would also pass a redo
    // branch that merged the wrong snapshot back onto the wrong items.
    const afterUndo = await store.getSnapshot();
    const sheetAfterUndo = afterUndo.sheets.find((s) => s.id === sheet.id);
    expect(sheetAfterUndo.scale).toBe(originalScale);
    const stillMissingAfterUndo = afterUndo.items.filter((i) => i.sheetId === sheet.id && i.status === "missing");
    expect(stillMissingAfterUndo.map((i) => i.id).sort()).toEqual(blockedBefore.map((i) => i.id).sort());

    const redoResult = await store.redo();
    expect(redoResult.performed).toBe(true);
    // Same standard applied to redo: the scale change and every released
    // item's status/warnings must actually be back the way setScale left
    // them, not merely "some snapshot object was returned."
    const afterRedo = await store.getSnapshot();
    const sheetAfterRedo = afterRedo.sheets.find((s) => s.id === sheet.id);
    expect(sheetAfterRedo.scale).toBe(scaleValue);
    for (const releasedId of blockedBefore.map((i) => i.id)) {
      const released = afterRedo.items.find((i) => i.id === releasedId);
      expect(released.status).toBe("ready");
      expect(released.warnings).toEqual([]);
    }
  });

  describe("projects", () => {
    it("lists projects with camelCase fields and numeric counts", async () => {
      const projects = await store.listProjects();

      expect(Array.isArray(projects)).toBe(true);
      expect(projects.length).toBeGreaterThan(0);

      const project = projects[0];
      expect(typeof project.id).toBe("string");
      expect(typeof project.name).toBe("string");
      expect(typeof project.number).toBe("string");
      expect(typeof project.customer).toBe("string");
      expect(typeof project.location).toBe("string");
      expect(typeof project.stage).toBe("string");
      // Counts are numbers, not strings. The dashboard does arithmetic on
      // them (approved / total) and a string here produces "012" rather
      // than a percentage.
      expect(typeof project.itemsTotal).toBe("number");
      expect(typeof project.itemsApproved).toBe("number");
      expect(typeof project.warningsOpen).toBe("number");
      expect(typeof project.missingInfo).toBe("number");
      // Null, never a fabricated date -- an invented bid deadline is worse
      // than a blank cell.
      expect(project.bidDueDate === null || typeof project.bidDueDate === "string").toBe(true);
    });

    it("excludes items on a superseded sheet from its counts, not just rejected items", async () => {
      // E2.1 (data.js) carries 7 of the fixture's 12 items, including
      // both of its "attention" items (it-04, it-07) -- superseding it
      // and only it isolates the sheet-exclusion half of
      // countsTowardTotals() from the rejected-item half, which "counts
      // never exceed the total" above cannot do (rejected and superseded
      // overlap in every other fixture state). A `!item.rejected`-only
      // filter would leave warningsOpen at 2 after this write; the
      // correct predicate drops it to 0.
      const before = (await store.listProjects()).find((p) => p.itemsTotal > 0);
      const { sheets, items } = await store.getSnapshot();
      const target = sheets.find((s) => s.id === "E2.1");
      const onTarget = items.filter((i) => i.sheetId === target.id && !i.rejected);
      expect(onTarget.length).toBeGreaterThan(0);

      // Written directly to storage, mirroring the presence test above --
      // no store mutation exposes "supersede a sheet" yet, and this test
      // only needs the read side (countsTowardTotals) to react correctly.
      storageWrite("sheets", sheets.map((s) => (s.id === target.id ? { ...s, superseded: true } : s)));

      const after = (await store.listProjects()).find((p) => p.id === before.id);
      expect(after.itemsTotal).toBe(before.itemsTotal - onTarget.length);
      expect(after.warningsOpen).toBe(0);
    });

    it("counts never exceed the total", async () => {
      for (const project of await store.listProjects()) {
        expect(project.itemsApproved).toBeLessThanOrEqual(project.itemsTotal);
        expect(project.warningsOpen).toBeLessThanOrEqual(project.itemsTotal);
        expect(project.missingInfo).toBeLessThanOrEqual(project.itemsTotal);
      }
    });

    it("creates a project that then appears in the list", async () => {
      const created = await store.createProject({
        name: "Oakview High School",
        location: "Modesto, CA",
      });

      expect(created.id).toBeTruthy();
      expect(created.name).toBe("Oakview High School");
      expect(created.stage).toBe("setup");
      expect(created.itemsTotal).toBe(0);

      const names = (await store.listProjects()).map((p) => p.name);
      expect(names).toContain("Oakview High School");
    });
  });
});
}

defineContractSuite("seed store", () => createSeedStore());

defineContractSuite("api store", () => {
  const { fetchStub } = installFakeApiBackend();
  vi.stubGlobal("fetch", fetchStub);
  return createApiStore();
});
