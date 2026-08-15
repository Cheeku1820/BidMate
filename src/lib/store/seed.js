/* ============================================================
   seed.js — the store adapter's seed implementation.

   Stands in for a real backend the way api/app/seed.py's fixture stands
   in for the takeoff engine: localStorage is the database and
   BroadcastChannel is the realtime layer (ROADMAP.md, "What the
   prototype maps to"). The localStorage/BroadcastChannel/identity
   internals below are moved out of src/lib/sync.js, which App.jsx still
   imports until Task 16 ports it — this module does not import from or
   export to sync.js, and the two intentionally use different storage
   keys (see NS below) so the not-yet-wired-in store never collides with
   the running prototype's own state.

   The contract this module satisfies is documented in full in
   task-15-report.md: camelCase throughout, `warnings` as an array, and
   quantities/totals as JS numbers (the API's Decimal fields arrive as
   strings; api.js, not this file, does that conversion for the real
   backend — this module simply never introduces Decimal-as-string in
   the first place, since it computes everything in JS).

   The client never does arithmetic on totals in production (invariant
   1: totals are computed in exactly one place, the server). This
   module is the one narrow exception, because it *is* standing in for
   that server — computeTotals() below exists only because there is
   nothing else to compute it.
   ============================================================ */

import { SHEETS, ITEMS } from "../data.js";
import { refusalToApprove, countsTowardTotals, scaleWarnings, nonScaleWarnings, isScaleReleasable } from "../rules.js";

/* --- low-level storage: localStorage + BroadcastChannel, with guards ----

   Copied (not imported) from sync.js's own internals, per task-15-brief.md:
   "Move the localStorage, BroadcastChannel, and identity() internals from
   sync.js into this module." A distinct namespace keeps this store's data
   from ever colliding with sync.js's, since App.jsx still reads/writes
   sync.js's keys until Task 16 switches it over. */

const NS = "takeoff-review:store:";

/* jsdom's BroadcastChannel support varies by version and Node's global may
   not survive into it — guarded the same way sync.js guards it, rather than
   assumed present. Missing it just means this store works single-tab. */
let channel = null;
try {
  channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(NS + "bus") : null;
} catch {
  channel = null;
}

/* Sandboxed frames block localStorage; fall back to an in-memory map so a
   single tab still works end to end, matching sync.js's own fallback. */
const memory = new Map();
const backing = (() => {
  try {
    const probe = "__probe__";
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return localStorage;
  } catch {
    return {
      getItem: (k) => (memory.has(k) ? memory.get(k) : null),
      setItem: (k, v) => memory.set(k, v),
      removeItem: (k) => memory.delete(k),
    };
  }
})();

function storageRead(key, fallback) {
  try {
    const raw = backing.getItem(NS + key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function storageWrite(key, value) {
  try {
    backing.setItem(NS + key, JSON.stringify(value));
    channel?.postMessage({ key, at: Date.now() });
    return true;
  } catch {
    return false;
  }
}

function storageSubscribe(handler) {
  const onBus = (e) => handler(e.data?.key);
  const onStorage = (e) => {
    if (e.key && e.key.startsWith(NS)) handler(e.key.slice(NS.length));
  };
  channel?.addEventListener("message", onBus);
  if (typeof window !== "undefined") window.addEventListener("storage", onStorage);
  return () => {
    channel?.removeEventListener("message", onBus);
    if (typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
}

/* --- identity, moved verbatim from sync.js ------------------------------ */

const FIRST = ["Wren", "Sage", "Milo", "Nora", "Theo", "Ivy", "Reid", "Juno", "Amara", "Cole", "Dara", "Otis"];
const LAST = ["Alvarez", "Boyd", "Castro", "Duval", "Ellery", "Fontaine", "Grady", "Hale", "Ibarra", "Kwan"];
const COLORS = ["#23528f", "#1c6f47", "#9c5f06", "#6b3fa0", "#0d7377", "#a8412c"];

function identity() {
  const existing = storageRead("me", null);
  if (existing) return existing;
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const me = {
    id: "u_" + Math.random().toString(36).slice(2, 9),
    name: pick(FIRST) + " " + pick(LAST),
    color: pick(COLORS),
  };
  storageWrite("me", me);
  return me;
}

const uid = (p) => p + "_" + Math.random().toString(36).slice(2, 9);

/* --- presence -------------------------------------------------------------

   30 seconds, not an arbitrary round number: mirrors
   api/app/collab/service.py's ACTIVE_WINDOW (ASSUMED_HEARTBEAT_INTERVAL,
   10s, times three heartbeats' worth of slack), so a reviewer who has
   actually left reads as gone on roughly the same timeline a real backend
   would show, rather than the prototype's previous ad hoc 14s. */
const ACTIVE_WINDOW_MS = 30_000;

function writePresence(sheetId, itemId) {
  const me = identity();
  storageWrite("presence:" + me.id, {
    userId: me.id,
    name: me.name,
    color: me.color,
    sheetId: sheetId ?? null,
    itemId: itemId ?? null,
    seenAt: Date.now(),
  });
}

function listPresenceKeys() {
  // backing has no key()/length API when it's the in-memory fallback, and
  // localStorage's index-based iteration is awkward for a prefix scan
  // either way — keep an explicit index of presence ids instead.
  return storageRead("presence-index", []);
}

function activePresence(excludeUserId) {
  const now = Date.now();
  const ids = listPresenceKeys();
  return ids
    .map((id) => storageRead("presence:" + id, null))
    .filter((p) => p && p.userId !== excludeUserId && now - p.seenAt < ACTIVE_WINDOW_MS);
}

/* --- seeding items/sheets from data.js into the contract shape ---------- */

// api/app/seed.py's own classification table (module docstring, "BLOCKER,
// resolved via migration 0007") for the four warning titles data.js
// actually carries. Duplicated here rather than imported — the two seeds
// are independent fixtures in independent languages — but deliberately
// kept identical in content, since both describe the same four warnings.
const WARNING_REASON_BY_TITLE = {
  "Scale needs confirmation": "scale",
  "Missing scale reference": "scale",
  "Symbol is not in the legend": "legend",
  "Fixture type conflicts with the schedule": "schedule_conflict",
};

/** data.js's singular `warning` field becomes a one-element `warnings`
 *  array; `null` becomes `[]` — task-15-brief.md, decision 2. Never
 *  collapsed back to a single field, and never silently defaulted when a
 *  title has no known reason: an unmapped title is a fixture bug and
 *  should fail loudly here rather than ship an unclassified warning that
 *  setScale() (via scaleWarnings/nonScaleWarnings) would silently
 *  mishandle. */
function toWarnings(itemId, warning) {
  if (!warning) return [];
  const reason = WARNING_REASON_BY_TITLE[warning.title];
  if (!reason) {
    throw new Error(`seed.js: no WARNING_REASON_BY_TITLE entry for "${warning.title}" (item ${itemId})`);
  }
  return [
    {
      id: "w_" + itemId,
      title: warning.title,
      found: warning.found,
      why: warning.why,
      fix: warning.fix,
      where: warning.where,
      reason,
    },
  ];
}

function seedItems() {
  return ITEMS.map((it) => ({
    id: it.id,
    sheetId: it.sheetId,
    symbol: it.symbol,
    name: it.name,
    description: it.description,
    system: it.system,
    category: it.category,
    quantity: it.quantity,
    unit: it.unit,
    status: it.status,
    approvedBy: it.approvedBy ?? null,
    rejected: false,
    x: it.x ?? null,
    y: it.y ?? null,
    path: it.path ?? null,
    notes: it.notes ?? "",
    evidence: it.evidence ?? null,
    warnings: toWarnings(it.id, it.warning),
  }));
}

function seedSheets() {
  // SheetOut (schemas.py) has no revisionDate field — data.js's
  // revisionDate is dropped here to match the contract exactly rather
  // than carrying a field api.js would never be able to produce from the
  // real API.
  return SHEETS.map((s) => ({
    id: s.id,
    number: s.number,
    title: s.title,
    discipline: s.discipline,
    revision: s.revision,
    scale: s.scale,
    scaleOptions: s.scaleOptions,
    plan: s.plan,
    superseded: false,
  }));
}

/* --- reads, materializing the seed on first access ----------------------- */

function readItems() {
  const existing = storageRead("items", null);
  if (existing) return existing;
  const seeded = seedItems();
  storageWrite("items", seeded);
  return seeded;
}

function readSheets() {
  const existing = storageRead("sheets", null);
  if (existing) return existing;
  const seeded = seedSheets();
  storageWrite("sheets", seeded);
  return seeded;
}

function readHist() {
  return storageRead("hist", { undo: [], redo: [] });
}

function readVersion() {
  return storageRead("version", 0);
}

function bumpVersion() {
  const next = readVersion() + 1;
  storageWrite("version", next);
  return next;
}

/* --- totals ---------------------------------------------------------------

   Mirrors api/app/takeoff/totals.py's approved_totals(): grouped by
   system for approved items only, excluding rejected items and items on
   superseded sheets via rules.countsTowardTotals — the same function
   App.jsx (Task 16) and this module both call, so the rule is written
   once. This is the one place in the client allowed to sum quantities,
   because for the seed store this *is* the server. */
function computeTotals(items, sheetsById) {
  const bySystem = {};
  let approvedCount = 0;
  let remainingCount = 0;
  let attentionCount = 0;
  let missingCount = 0;
  let approvedUnits = 0;

  for (const item of items) {
    if (!countsTowardTotals(item, sheetsById)) continue;
    if (item.status === "approved") {
      bySystem[item.system] = (bySystem[item.system] || 0) + item.quantity;
      approvedUnits += item.quantity;
      approvedCount += 1;
    } else {
      remainingCount += 1;
      if (item.status === "attention") attentionCount += 1;
      else if (item.status === "missing") missingCount += 1;
    }
  }

  return { bySystem, approvedCount, remainingCount, attentionCount, missingCount, approvedUnits };
}

function buildUndoOut(hist) {
  const lastUndo = hist.undo[hist.undo.length - 1] ?? null;
  const lastRedo = hist.redo[hist.redo.length - 1] ?? null;
  return {
    canUndo: hist.undo.length > 0,
    canRedo: hist.redo.length > 0,
    undoLabel: lastUndo?.label ?? null,
    undoBy: lastUndo?.by ?? null,
    redoLabel: lastRedo?.label ?? null,
  };
}

/* --- the store -------------------------------------------------------- */

export function createSeedStore() {
  function commitAction(action, nextItems, nextSheets) {
    storageWrite("items", nextItems);
    if (nextSheets) storageWrite("sheets", nextSheets);
    const hist = readHist();
    const nextHist = { undo: [...hist.undo, action].slice(-60), redo: [] };
    storageWrite("hist", nextHist);
    bumpVersion();
  }

  async function me() {
    return identity();
  }

  async function getSnapshot() {
    const items = readItems();
    const sheets = readSheets();
    const hist = readHist();
    const sheetsById = Object.fromEntries(sheets.map((s) => [s.id, s]));
    return {
      version: String(readVersion()),
      sheets,
      items,
      totals: computeTotals(items, sheetsById),
      undo: buildUndoOut(hist),
      presence: activePresence(identity().id),
    };
  }

  function subscribe(handler) {
    return storageSubscribe(handler);
  }

  async function setPresence({ sheetId, itemId }) {
    const actor = identity();
    writePresence(sheetId, itemId);
    const ids = listPresenceKeys();
    if (!ids.includes(actor.id)) storageWrite("presence-index", [...ids, actor.id]);
  }

  async function approveItem(id) {
    const items = readItems();
    const item = items.find((i) => i.id === id);
    if (!item) {
      throw { code: "item_no_longer_exists", message: "This item was deleted by another reviewer. Refresh the sheet to see its current items." };
    }
    const refusal = refusalToApprove(item);
    if (refusal) throw refusal;

    const actor = identity();
    const before = { status: item.status, approvedBy: item.approvedBy };
    const after = { status: "approved", approvedBy: actor.name };
    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after } : i));
    const action = { id: uid("a"), kind: "approve", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Approved ${item.name}` };
    commitAction(action, nextItems);
    return { label: action.label, version: String(readVersion()), item: nextItems.find((i) => i.id === id) };
  }

  async function rejectItem(id) {
    const items = readItems();
    const item = items.find((i) => i.id === id);
    if (!item) {
      throw { code: "item_no_longer_exists", message: "This item was deleted by another reviewer. Refresh the sheet to see its current items." };
    }
    // Rejection is tracked separately from review status (review.py's
    // _apply_reject() never touches item.status) so unrejecting can
    // restore the item exactly as it was, without having to guess what
    // status it used to carry.
    const actor = identity();
    const before = { rejected: item.rejected };
    const after = { rejected: true };
    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after } : i));
    const action = { id: uid("a"), kind: "reject", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Rejected ${item.name}` };
    commitAction(action, nextItems);
    return { label: action.label, version: String(readVersion()), item: nextItems.find((i) => i.id === id) };
  }

  async function unrejectItem(id) {
    const items = readItems();
    const item = items.find((i) => i.id === id);
    if (!item) {
      throw { code: "item_no_longer_exists", message: "This item was deleted by another reviewer. Refresh the sheet to see its current items." };
    }
    const actor = identity();
    const before = { rejected: item.rejected };
    const after = { rejected: false };
    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after } : i));
    const action = { id: uid("a"), kind: "unreject", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Restored ${item.name}` };
    commitAction(action, nextItems);
    return { label: action.label, version: String(readVersion()), item: nextItems.find((i) => i.id === id) };
  }

  // Mirrors review.py's EDITABLE_FIELDS/REQUIRED_TEXT_FIELDS. Deliberately
  // does not replicate Numeric(12,2)'s max-magnitude or two-decimal-place
  // rounding checks — those are a Postgres storage constraint, not a
  // domain rule, and the store's Decimal->number decision (see the module
  // docstring) already means quantity never round-trips through a
  // fixed-precision column on the client. A finite, non-negative number is
  // what this layer can actually promise.
  const EDITABLE_FIELDS = new Set(["system", "category", "quantity", "notes", "symbol"]);
  const REQUIRED_TEXT_FIELDS = new Set(["system", "category", "symbol"]);

  function validateEdit(changes) {
    const unknown = Object.keys(changes).filter((k) => !EDITABLE_FIELDS.has(k));
    if (unknown.length) {
      throw {
        code: "field_not_editable",
        message: `These fields cannot be changed here: ${unknown.sort().join(", ")}. Edit one of: ${[...EDITABLE_FIELDS].sort().join(", ")}.`,
      };
    }
    for (const field of REQUIRED_TEXT_FIELDS) {
      if (field in changes && (typeof changes[field] !== "string" || !changes[field].trim())) {
        throw { code: "field_cannot_be_empty", message: `${field[0].toUpperCase()}${field.slice(1)} cannot be blank. Enter a value before saving this edit.` };
      }
    }
    if ("notes" in changes && changes.notes === null) {
      throw { code: "field_cannot_be_empty", message: "Notes cannot be removed entirely. Send an empty value instead of no value, to clear it." };
    }
    if ("quantity" in changes) {
      const parsed = Number(changes.quantity);
      if (!Number.isFinite(parsed)) {
        throw { code: "invalid_quantity", message: "Quantity must be a number, such as 14 or 3.5. Correct it and save the edit again." };
      }
      if (parsed < 0) {
        throw { code: "invalid_quantity", message: "Quantity cannot be negative. Enter zero or a positive number, such as 14 or 3.5." };
      }
    }
  }

  async function editItem(id, changes) {
    const items = readItems();
    const item = items.find((i) => i.id === id);
    if (!item) {
      throw { code: "item_no_longer_exists", message: "This item was deleted by another reviewer. Refresh the sheet to see its current items." };
    }
    validateEdit(changes);

    const actor = identity();
    const before = {};
    for (const key of Object.keys(changes)) before[key] = item[key];
    const after = { ...before };
    for (const [key, value] of Object.entries(changes)) after[key] = key === "quantity" ? Number(value) : value;

    // review.py's _apply_edit(): an item stuck at Needs attention only
    // because its category was never classified moves to Ready to review
    // the moment a real category is supplied.
    const wasUnclassified = item.status === "attention" && item.category === "Unclassified";
    const stillUnclassified = (after.category ?? item.category) === "Unclassified";
    if (wasUnclassified && !stillUnclassified) {
      before.status = item.status;
      after.status = "ready";
    }

    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after } : i));
    const action = { id: uid("a"), kind: "edit", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Edited ${item.name}` };
    commitAction(action, nextItems);
    return { label: action.label, version: String(readVersion()), item: nextItems.find((i) => i.id === id) };
  }

  async function deleteItem(id) {
    const items = readItems();
    const index = items.findIndex((i) => i.id === id);
    if (index === -1) {
      throw { code: "item_no_longer_exists", message: "This item was deleted by another reviewer. Refresh the sheet to see its current items." };
    }
    const item = items[index];
    const actor = identity();
    const nextItems = items.filter((i) => i.id !== id);
    const action = { id: uid("a"), kind: "delete", itemId: id, index, snapshot: item, by: actor.name, at: Date.now(), label: `Deleted ${item.name}` };
    commitAction(action, nextItems);
    return { label: action.label, version: String(readVersion()), item: null };
  }

  // Compound action: sets the sheet's scale and releases every item that
  // scale was blocking, as one undoable entry (DESIGN.md, "Undo
  // semantics"; scale.py's set_scale()). Only Missing information items
  // on THIS sheet whose Missing information is explained by a scale
  // warning move. An item with a surviving non-scale warning (the legend
  // case) stays Missing information even though its scale problem is
  // resolved — see rules.js's isScaleReleasable/nonScaleWarnings.
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

    const nextItems = items.map((i) => (updates.has(i.id) ? { ...i, ...updates.get(i.id) } : i));
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

  // Merges each entry's fields into the matching item by id — used to
  // restore (undo) or reapply (redo) a scale action's per-item snapshot,
  // which is why DESIGN.md's "replaying is a merge rather than a full-
  // state restore" holds even for this compound, multi-item action.
  function applyItemPartials(items, entries) {
    const m = Object.fromEntries(entries.map((x) => [x.id, x]));
    return items.map((i) => (m[i.id] ? { ...i, ...m[i.id] } : i));
  }

  async function undo() {
    const hist = readHist();
    if (!hist.undo.length) return { performed: false };
    const a = hist.undo[hist.undo.length - 1];

    let items = readItems();
    let sheets = readSheets();

    if (a.kind === "approve" || a.kind === "reject" || a.kind === "unreject" || a.kind === "edit") {
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

    if (a.kind === "approve" || a.kind === "reject" || a.kind === "unreject" || a.kind === "edit") {
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

  return {
    me,
    getSnapshot,
    subscribe,
    setPresence,
    approveItem,
    rejectItem,
    unrejectItem,
    editItem,
    deleteItem,
    setScale,
    undo,
    redo,
  };
}
