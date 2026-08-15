/* ============================================================
   contract.test.js — pins the store interface Task 16's api.js must
   also satisfy: camelCase field names throughout, `warnings` as an
   array (never collapsed to a singular field — task-15-brief.md,
   decision 2), and the review rules from BUILD-STAGES.md that must
   never regress, mirrored client-side.
   ============================================================ */

import { describe, expect, it, beforeEach } from "vitest";
import { createSeedStore } from "./seed.js";

const METHODS = [
  "me", "getSnapshot", "subscribe", "setPresence",
  "approveItem", "rejectItem", "unrejectItem", "editItem",
  "deleteItem", "setScale", "undo", "redo",
];

describe("seed store", () => {
  let store;
  beforeEach(() => {
    localStorage.clear();
    store = createSeedStore();
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

  it("refuses to approve a missing information item", async () => {
    const { items } = await store.getSnapshot();
    const blocked = items.find((i) => i.status === "missing");
    await expect(store.approveItem(blocked.id)).rejects.toMatchObject({
      code: "missing_information_blocks_approval",
    });
  });

  it("does not count rejected items in totals", async () => {
    const before = (await store.getSnapshot()).totals.approvedUnits;
    const { items } = await store.getSnapshot();
    const approved = items.find((i) => i.status === "approved");
    await store.rejectItem(approved.id);
    const after = (await store.getSnapshot()).totals.approvedUnits;
    expect(after).toBeLessThan(before);
  });

  it("setting a scale releases the blocked items on that sheet only", async () => {
    const { items, sheets } = await store.getSnapshot();
    const sheet = sheets.find((s) => s.scale === "none");
    await store.setScale(sheet.id, '1/8" = 1\'-0"');
    const updated = (await store.getSnapshot()).items;
    const onSheet = updated.filter((i) => i.sheetId === sheet.id);
    expect(onSheet.every((i) => i.status !== "missing")).toBe(true);
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

    await expect(store.me()).resolves.toMatchObject({ id: expect.any(String), name: expect.any(String), color: expect.any(String) });

    const unsubscribe = store.subscribe(() => {});
    expect(typeof unsubscribe).toBe("function");
    unsubscribe();

    await store.setPresence({ sheetId: sheet.id, itemId: readyItem.id });

    const approveResult = await store.approveItem(readyItem.id);
    expect(approveResult.item.status).toBe("approved");

    const rejectResult = await store.rejectItem(anotherReadyItem.id);
    expect(rejectResult.item.rejected).toBe(true);

    const unrejectResult = await store.unrejectItem(anotherReadyItem.id);
    expect(unrejectResult.item.rejected).toBe(false);

    const editResult = await store.editItem(anotherReadyItem.id, { notes: "checked against E1.1" });
    expect(editResult.item.notes).toBe("checked against E1.1");

    const deleteResult = await store.deleteItem(anotherReadyItem.id);
    expect(deleteResult.item).toBeNull();

    const scaleResult = await store.setScale(sheet.id, sheet.scaleOptions[0] ?? "nts");
    expect(scaleResult.snapshot.version).toEqual(expect.any(String));

    const undoResult = await store.undo();
    expect(undoResult.performed).toBe(true);

    const redoResult = await store.redo();
    expect(redoResult.performed).toBe(true);
  });
});
