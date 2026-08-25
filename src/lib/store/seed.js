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
import { createSeedProjects, SEED_PROJECT_ID } from "./seed-projects.js";

// The revision label a sampled demo project reports, matching the
// fixture project's own (seed-projects.js) since the sample IS the
// fixture takeoff copied in.
const SAMPLE_REVISION_LABEL = "E1.1 Rev 3 · E2.1 Rev 2 · E3.1 Rev 1";

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

/** The honest answer for any project id that isn't the fixture: no
 *  sheets, no items, nothing to undo. Workspace.jsx already renders
 *  "This project has no sheets yet." for an empty-but-successful
 *  snapshot (its `loadError || !sheet` branch), so this needs no new UI
 *  path -- it only has to stop seed mode from serving the fixture's
 *  twelve items under a project that never had them (task-8 review
 *  finding 1b). `version` is a literal "0" rather than the shared
 *  version counter: that counter tracks the fixture's own mutation
 *  history, and reusing it here would claim a revision history this
 *  project doesn't have. */
function emptySnapshot() {
  return {
    version: "0",
    sheets: [],
    items: [],
    totals: { bySystem: {}, approvedCount: 0, remainingCount: 0, attentionCount: 0, missingCount: 0, approvedUnits: 0 },
    undo: { canUndo: false, canRedo: false, undoLabel: null, undoBy: null, redoLabel: null },
    presence: activePresence(identity().id),
  };
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
  // Writes go to the *active* project's own namespaced keys (scopedKey
  // below), so a demo project's approvals never mutate the fixture's
  // shared items/sheets/hist. For the fixture the keys are unchanged
  // ("items"/"sheets"/"hist"), so every existing behaviour and the whole
  // contract suite are untouched.
  function commitAction(action, nextItems, nextSheets) {
    storageWrite(scopedKey("items"), nextItems);
    if (nextSheets) storageWrite(scopedKey("sheets"), nextSheets);
    const hist = readActiveHist();
    const nextHist = { undo: [...hist.undo, action].slice(-60), redo: [] };
    storageWrite(scopedKey("hist"), nextHist);
    bumpActiveVersion();
  }

  async function me() {
    return identity();
  }

  // Records the id Workspace.jsx's routed :projectId last asked for, the
  // same way api.js's useProject(id) records it into its own `projectId`
  // closure variable -- mirrored here (task-8 review finding 1b) so
  // getSnapshot() below can tell the one fixture project apart from every
  // other id the same way the real backend already can. `null` (nothing
  // asked yet) defaults to the fixture in getSnapshot(), matching api.js's
  // ensureProjectId() falling back to "the first project" when nothing
  // has called useProject() yet -- contract.test.js's shared suite relies
  // on exactly that fallback for both stores.
  let activeProjectId = null;
  function useProject(projectId) {
    activeProjectId = projectId;
  }

  // Same test getSnapshot() already applies (line ~201) — the fixture is
  // active by default (nothing has called useProject() yet) or once it
  // has been named explicitly. Handed to seed-undo.js so undo()/redo()
  // can refuse to touch the shared items/sheets/hist keys while a
  // *different*, sheet-less project is open (final-review fix 1):
  // those keys hold only the fixture project's history, and every other
  // project id is honestly empty, so there is nothing of theirs to
  // undo. Without this, a keystroke on an empty project pops the
  // fixture's shared undo stack and can silently reverse an approval —
  // the one thing this product cannot do by accident.
  function isFixtureProjectActive() {
    return !activeProjectId || activeProjectId === SEED_PROJECT_ID;
  }

  // The fixture reads and writes the bare keys ("items", "sheets", ...);
  // every other project namespaces its own under `${base}:${id}`. This
  // is the one place the two are distinguished -- the fixture's data and
  // a demo project's sample takeoff are fully isolated stores that never
  // share a key. `activeProjectId` null means "nothing asked yet", which
  // is the fixture, so the default caller (and the contract suite) sees
  // exactly today's behaviour.
  const isFixtureId = (id) => !id || id === SEED_PROJECT_ID;
  const scopedKey = (base) => (isFixtureId(activeProjectId) ? base : `${base}:${activeProjectId}`);

  // Active-project-scoped reads, handed to the mutation modules as deps.
  // For the fixture they resolve to the module-level readers (which
  // materialise the seed on first access); for any other project they
  // read that project's own keys, empty until attachSampleTakeoff()
  // writes a sample into them -- so a created project with no takeoff is
  // still honestly empty.
  function readActiveItems() {
    return isFixtureId(activeProjectId) ? readItems() : storageRead(scopedKey("items"), []);
  }
  function readActiveSheets() {
    return isFixtureId(activeProjectId) ? readSheets() : storageRead(scopedKey("sheets"), []);
  }
  function readActiveHist() {
    return isFixtureId(activeProjectId) ? readHist() : storageRead(scopedKey("hist"), { undo: [], redo: [] });
  }
  function readActiveVersion() {
    return isFixtureId(activeProjectId) ? readVersion() : storageRead(scopedKey("version"), 0);
  }
  function bumpActiveVersion() {
    if (isFixtureId(activeProjectId)) return bumpVersion();
    const next = readActiveVersion() + 1;
    storageWrite(scopedKey("version"), next);
    return next;
  }

  // Reads any project's scoped takeoff by id, independent of which one is
  // active -- seed-projects.js's listProjects() uses this to compute a
  // sampled demo project's dashboard counts the same way the fixture
  // row's are computed, so the two can never disagree.
  function readScopedTakeoff(projectId) {
    return {
      items: storageRead(`items:${projectId}`, []),
      sheets: storageRead(`sheets:${projectId}`, []),
      hist: storageRead(`hist:${projectId}`, { undo: [], redo: [] }),
    };
  }

  // Unconditional: seed mode's one fixture project's real data,
  // regardless of which project is currently active. This is what
  // seed-projects.js's listProjects() calls (see its own comment) so the
  // dashboard's fixture row never goes empty just because the workspace
  // last had a different project open.
  async function computeFixtureSnapshot() {
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

  // The public, useProject()-gated snapshot the store interface exposes.
  // Seed mode has exactly one fixture project's worth of sheets and
  // items in storage -- serving them under a *different* project's id
  // would be presenting one project's evidence as another's, which is
  // exactly the failure task-8 review finding 1 flagged. A project id
  // that isn't the fixture's genuinely has no sheets yet, so it gets the
  // honest empty snapshot instead.
  async function getSnapshot() {
    if (isFixtureId(activeProjectId)) return computeFixtureSnapshot();
    const items = readActiveItems();
    const sheets = readActiveSheets();
    // A created project with no sample attached genuinely has nothing --
    // the honest empty snapshot, exactly as before. A sampled demo
    // project has its own isolated sheets and items and gets a real
    // snapshot computed off them.
    if (!items.length && !sheets.length) return emptySnapshot();
    const hist = readActiveHist();
    const sheetsById = Object.fromEntries(sheets.map((s) => [s.id, s]));
    return {
      version: String(readActiveVersion()),
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
  const deps = {
    readItems: readActiveItems,
    readSheets: readActiveSheets,
    readHist: readActiveHist,
    readVersion: readActiveVersion,
    bumpVersion: bumpActiveVersion,
    commitAction,
    storageWrite,
    scopedKey,
    identity,
    uid,
    getSnapshot,
    isFixtureProjectActive,
  };

  const review = createReviewMethods(deps);
  const scale = createScaleMethod(deps);
  const undoing = createUndoMethods(deps);
  const { markProjectSampled, ...projectApi } = createSeedProjects({
    getSnapshot: computeFixtureSnapshot,
    readHist,
    readScopedTakeoff,
  });

  // Seed-only: stands in for the ingestion pipeline the real backend
  // runs. Copies the fixture takeoff into a *created* project's own
  // isolated keys and flags the project row as carrying sample data, so
  // the review/export loop can be walked end to end without a real
  // engine -- the review workspace shows a "sample data" banner off that
  // flag, so nothing here is ever presented as derived from the
  // estimator's own upload. Never touches the fixture's own storage.
  async function attachSampleTakeoff(projectId) {
    if (isFixtureId(projectId)) return;
    storageWrite(`items:${projectId}`, seedItems());
    storageWrite(`sheets:${projectId}`, seedSheets());
    storageWrite(`hist:${projectId}`, { undo: [], redo: [] });
    storageWrite(`version:${projectId}`, 1);
    markProjectSampled(projectId, { revisionSetLabel: SAMPLE_REVISION_LABEL });
  }

  return {
    me,
    useProject,
    getSnapshot,
    subscribe,
    setPresence,
    attachSampleTakeoff,
    ...review,
    ...scale,
    ...undoing,
    ...projectApi,
  };
}
