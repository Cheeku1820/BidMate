/* ============================================================
   seed.js — the store adapter's seed implementation.

   Stands in for a real backend the way api/app/seed.py's fixture stands
   in for the takeoff engine: localStorage is the database and
   BroadcastChannel is the realtime layer (ROADMAP.md, "What the
   prototype maps to"). The pieces this file assembles live in their own
   modules, mirroring how the Python side is split (review.py / scale.py
   / undo.py, each a materially different act):

     local-transport.js  storage guards, identity, presence — sync.js's replacement
     seed-fixture.js      data.js -> contract shape
     seed-review.js        approve / reject / unreject / edit / delete
     seed-scale.js          setScale, the compound action
     seed-undo.js             undo / redo

   This file owns what's left: reads, totals, the undo-panel shape, and
   wiring everything above into the createSeedStore() the store
   interface (task-15-brief.md) expects.

   The contract this module satisfies is documented in full in
   task-15-report.md: camelCase throughout, `warnings` as an array, and
   quantities/totals as JS numbers (the API's Decimal fields arrive as
   strings; api.js, not this file, does that conversion for the real
   backend — this module simply never introduces Decimal-as-string in
   the first place, since it computes everything in JS). Presence's
   `seenAt` (local-transport.js) is the same class of decision: epoch
   milliseconds, not the API's ISO-8601 string, so it stays
   arithmetic-ready and api.js must convert it at the boundary too.

   The client never does arithmetic on totals in production (invariant
   1: totals are computed in exactly one place, the server). This
   module is the one narrow exception, because it *is* standing in for
   that server — computeTotals() below exists only because there is
   nothing else to compute it.
   ============================================================ */

import { countsTowardTotals } from "../rules.js";
import { storageRead, storageWrite, storageSubscribe, identity, uid, writePresence, indexPresence, activePresence } from "./local-transport.js";
import { seedItems, seedSheets } from "./seed-fixture.js";
import { createReviewMethods } from "./seed-review.js";
import { createScaleMethod } from "./seed-scale.js";
import { createUndoMethods } from "./seed-undo.js";
import { createSeedProjects } from "./seed-projects.js";

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
    indexPresence(actor.id);
  }

  // Shared low-level primitives, handed to each mutation module as
  // dependencies rather than those modules closing over this file's own
  // state — see seed-review.js / seed-scale.js / seed-undo.js's own
  // header comments for why each is its own file.
  const deps = { readItems, readSheets, readHist, readVersion, bumpVersion, commitAction, storageWrite, identity, uid, getSnapshot };

  const review = createReviewMethods(deps);
  const scale = createScaleMethod(deps);
  const undoing = createUndoMethods(deps);
  const projects = createSeedProjects({ getSnapshot });

  return {
    me,
    getSnapshot,
    subscribe,
    setPresence,
    ...review,
    ...scale,
    ...undoing,
    ...projects,
  };
}
