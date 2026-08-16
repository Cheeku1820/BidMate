/* ============================================================
   seed-scale.js — scale confirmation, one compound action.

   Mirrors api/app/takeoff/scale.py's set_scale(): sets a sheet's scale
   and releases every item that scale was blocking, as a single
   undoable entry (DESIGN.md, "Undo semantics"). Split out of
   seed-review.js for the same reason scale.py is split out of
   review.py — a sheet-level change plus a batch of item releases is a
   materially different act from a single item's review state.

   setScale is out of scope for the per-item version CHECK task-13b-
   brief.md adds to the five single-item mutations (sheet-scoped, and a
   deliberate rare action rather than routine editing) — but every item
   it touches still gets its `version` bumped, mirroring scale.py. Every
   candidate here had at least one warning cleared, even when its status
   didn't move (the mixed scale-and-legend case), so its stored shape
   changed and the counter a later single-item edit checks against must
   reflect that.
   ============================================================ */

import { nonScaleWarnings, isScaleReleasable } from "../rules.js";

export function createScaleMethod({ readSheets, readItems, commitAction, identity, uid, getSnapshot }) {
  // Only Missing information items on the sheet whose Missing information
  // is explained by a scale warning move. An item with a surviving
  // non-scale warning (the legend case) stays Missing information even
  // though its scale problem is resolved — see rules.js's
  // isScaleReleasable/nonScaleWarnings, and scale.py's module docstring
  // for the reasoning this mirrors.
  async function setScale(sheetId, value) {
    const sheets = readSheets();
    const sheet = sheets.find((s) => s.id === sheetId);
    if (!sheet) {
      throw { code: "sheet_not_found", message: "This sheet no longer exists. Refresh to see the current sheet list." };
    }
    const items = readItems();
    const candidates = items.filter((i) => i.sheetId === sheetId && isScaleReleasable(i));

    const itemsBefore = candidates.map((i) => ({ id: i.id, status: i.status, warnings: i.warnings }));
    const updates = new Map();
    for (const item of candidates) {
      const remaining = nonScaleWarnings(item);
      const nextStatus = remaining.length === 0 ? "ready" : item.status;
      updates.set(item.id, { warnings: remaining, status: nextStatus });
    }
    const itemsAfter = candidates.map((i) => ({ id: i.id, status: updates.get(i.id).status, warnings: updates.get(i.id).warnings }));

    const nextItems = items.map((i) =>
      updates.has(i.id) ? { ...i, ...updates.get(i.id), version: i.version + 1 } : i
    );
    const nextSheets = sheets.map((s) => (s.id === sheetId ? { ...s, scale: value } : s));

    const actor = identity();
    const count = candidates.length;
    const label = `Set scale on ${sheet.number} — ${count} measured item${count !== 1 ? "s" : ""} recalculated`;
    const action = {
      id: uid("a"), kind: "scale", sheetId,
      before: { scale: sheet.scale, items: itemsBefore },
      after: { scale: value, items: itemsAfter },
      by: actor.name, at: Date.now(), label,
    };
    commitAction(action, nextItems, nextSheets);
    return { label, snapshot: await getSnapshot() };
  }

  return { setScale };
}
