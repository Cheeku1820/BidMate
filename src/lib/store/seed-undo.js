/* ============================================================
   seed-undo.js — undo and redo, from the hist stack seed.js keeps.

   Mirrors api/app/takeoff/undo.py: reverses (or reapplies) the most
   recent action, generic across every action kind rather than special-
   cased per mutation — the same role undo.py plays for the real
   action log. applyItemPartials below is this module's small
   equivalent of undo_apply.py: merging a compound action's per-item
   snapshot back onto the current item list.

   This is the prototype's simple linear stand-in (ROADMAP.md, "hist.undo
   array capped at 60"), not the backend's append-only action log with
   two-hop parity — there is no server here to make that distinction
   matter, and DESIGN.md's compound-undo requirement (one undo reverses
   a whole scale confirmation) holds either way, because setScale
   already records the whole release as one hist entry.
   ============================================================ */

// Merges each entry's fields into the matching item by id — used to
// restore (undo) or reapply (redo) a scale action's per-item snapshot,
// which is why DESIGN.md's "replaying is a merge rather than a full-
// state restore" holds even for this compound, multi-item action.
function applyItemPartials(items, entries) {
  const m = Object.fromEntries(entries.map((x) => [x.id, x]));
  return items.map((i) => (m[i.id] ? { ...i, ...m[i.id] } : i));
}

const FIELD_LEVEL_KINDS = new Set(["approve", "reject", "unreject", "edit"]);

export function createUndoMethods({ readItems, readSheets, readHist, storageWrite, bumpVersion, getSnapshot }) {
  async function undo() {
    const hist = readHist();
    if (!hist.undo.length) return { performed: false };
    const a = hist.undo[hist.undo.length - 1];

    let items = readItems();
    let sheets = readSheets();

    if (FIELD_LEVEL_KINDS.has(a.kind)) {
      items = items.map((i) => (i.id === a.itemId ? { ...i, ...a.before } : i));
    } else if (a.kind === "delete") {
      items = items.slice();
      items.splice(a.index, 0, a.snapshot);
    } else if (a.kind === "scale") {
      sheets = sheets.map((s) => (s.id === a.sheetId ? { ...s, scale: a.before.scale } : s));
      items = applyItemPartials(items, a.before.items);
    }

    storageWrite("items", items);
    storageWrite("sheets", sheets);
    storageWrite("hist", { undo: hist.undo.slice(0, -1), redo: [...hist.redo, a] });
    bumpVersion();
    return { performed: true, label: `Undid: ${a.label}`, snapshot: await getSnapshot() };
  }

  async function redo() {
    const hist = readHist();
    if (!hist.redo.length) return { performed: false };
    const a = hist.redo[hist.redo.length - 1];

    let items = readItems();
    let sheets = readSheets();

    if (FIELD_LEVEL_KINDS.has(a.kind)) {
      items = items.map((i) => (i.id === a.itemId ? { ...i, ...a.after } : i));
    } else if (a.kind === "delete") {
      items = items.filter((i) => i.id !== a.itemId);
    } else if (a.kind === "scale") {
      sheets = sheets.map((s) => (s.id === a.sheetId ? { ...s, scale: a.after.scale } : s));
      items = applyItemPartials(items, a.after.items);
    }

    storageWrite("items", items);
    storageWrite("sheets", sheets);
    storageWrite("hist", { undo: [...hist.undo, a], redo: hist.redo.slice(0, -1) });
    bumpVersion();
    return { performed: true, label: `Redid: ${a.label}`, snapshot: await getSnapshot() };
  }

  return { undo, redo };
}
