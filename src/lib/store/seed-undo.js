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

   Undo and redo bump each touched item's `version` forward rather than
   restoring whatever it held before (task-13b-brief.md, mirroring
   api/app/takeoff/undo_apply.py's discipline): undo/redo are themselves
   mutations, so a client holding a version from before the undo must
   not be able to write again just because the item's fields happened to
   move back to values that version once described. `a.before`/`a.after`
   never carry a `version` key in the first place (seed-review.js), so
   this bump is always relative to whatever the item currently holds,
   never a value read back out of the hist stack.
   ============================================================ */

// Merges each entry's fields into the matching item by id, bumping its
// version — used to restore (undo) or reapply (redo) a scale action's
// per-item snapshot, which is why DESIGN.md's "replaying is a merge
// rather than a full-state restore" holds even for this compound,
// multi-item action.
function applyItemPartials(items, entries) {
  const m = Object.fromEntries(entries.map((x) => [x.id, x]));
  return items.map((i) => (m[i.id] ? { ...i, ...m[i.id], version: i.version + 1 } : i));
}

const FIELD_LEVEL_KINDS = new Set(["approve", "reject", "unreject", "edit"]);

export function createUndoMethods({ readItems, readSheets, readHist, storageWrite, scopedKey, bumpVersion, getSnapshot }) {
  async function undo() {
    // readHist/readItems/readSheets and scopedKey are all active-project
    // scoped (seed.js), so undo operates on whichever project is open:
    // the fixture's own stack, a sampled demo project's own stack, or --
    // for a created project with no history at all -- an empty stack that
    // yields "nothing happened" without ever touching another project's
    // keys. That scoping is what makes reversing a colleague's approval
    // by accident impossible across projects, the rule final-review fix 1
    // first enforced with a coarser is-this-the-fixture guard.
    const hist = readHist();
    if (!hist.undo.length) return { performed: false };
    const a = hist.undo[hist.undo.length - 1];

    let items = readItems();
    let sheets = readSheets();

    if (FIELD_LEVEL_KINDS.has(a.kind)) {
      items = items.map((i) => (i.id === a.itemId ? { ...i, ...a.before, version: i.version + 1 } : i));
    } else if (a.kind === "delete") {
      items = items.slice();
      // The restored item starts a fresh version lineage at 1, never the
      // pre-delete value the snapshot happens to carry -- nothing could
      // have held a valid reference to this row while it did not exist,
      // so resetting is both simplest and safe (mirrors
      // undo_apply.py's _apply_delete(), which gets the same outcome for
      // free from Item.version's column default once the snapshot's
      // "version" key is excluded).
      items.splice(a.index, 0, { ...a.snapshot, version: 1 });
    } else if (a.kind === "scale") {
      sheets = sheets.map((s) => (s.id === a.sheetId ? { ...s, scale: a.before.scale } : s));
      items = applyItemPartials(items, a.before.items);
    } else if (a.kind === "bulk-approve") {
      // Same shape as the compound scale action: one entry, many items,
      // one undo. DESIGN.md's rule that an estimator who regrets a
      // compound action gets one undo rather than fourteen applies here
      // exactly as it does to a scale confirmation.
      items = applyItemPartials(items, a.before.items);
    }

    storageWrite(scopedKey("items"), items);
    storageWrite(scopedKey("sheets"), sheets);
    storageWrite(scopedKey("hist"), { undo: hist.undo.slice(0, -1), redo: [...hist.redo, a] });
    bumpVersion();
    return { performed: true, label: `Undid: ${a.label}`, snapshot: await getSnapshot() };
  }

  async function redo() {
    // Same active-project scoping as undo() above: replays the open
    // project's own history and no one else's.
    const hist = readHist();
    if (!hist.redo.length) return { performed: false };
    const a = hist.redo[hist.redo.length - 1];

    let items = readItems();
    let sheets = readSheets();

    if (FIELD_LEVEL_KINDS.has(a.kind)) {
      items = items.map((i) => (i.id === a.itemId ? { ...i, ...a.after, version: i.version + 1 } : i));
    } else if (a.kind === "delete") {
      items = items.filter((i) => i.id !== a.itemId);
    } else if (a.kind === "scale") {
      sheets = sheets.map((s) => (s.id === a.sheetId ? { ...s, scale: a.after.scale } : s));
      items = applyItemPartials(items, a.after.items);
    } else if (a.kind === "bulk-approve") {
      items = applyItemPartials(items, a.after.items);
    }

    storageWrite(scopedKey("items"), items);
    storageWrite(scopedKey("sheets"), sheets);
    storageWrite(scopedKey("hist"), { undo: [...hist.undo, a], redo: hist.redo.slice(0, -1) });
    bumpVersion();
    return { performed: true, label: `Redid: ${a.label}`, snapshot: await getSnapshot() };
  }

  return { undo, redo };
}
