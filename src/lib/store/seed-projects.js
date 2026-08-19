/* ============================================================
   seed-projects.js — the projects list for seed mode.

   The seed fixture is one project (src/lib/store/seed-fixture.js), and
   before this file the seed store had no concept of a project at all.
   Rather than invent a second fixture, the seeded project's counts are
   derived from the snapshot that already exists, through the same
   countsTowardTotals() predicate seed.js's computeTotals() calls
   (rules.js, "written once") -- so the dashboard and the review
   workspace's drawer totals can never disagree about the same project.

   Projects created here live in localStorage alongside the rest of seed
   state. They have no sheets and no items, which is honest: seed mode
   has no ingestion, so a new project genuinely is empty.

   Imports nothing from api.js or api-mapping.js -- deleting seed mode
   must stay a matter of deleting these files (CLAUDE.md, "Sync is
   single-machine"). rules.js is shared client logic, not the API path,
   so importing it here does not cross that boundary.
   ============================================================ */

import { storageRead, storageWrite } from "./local-transport.js";
import { countsTowardTotals } from "../rules.js";

const CREATED_KEY = "projects";
// Exported so seed.js can tell the one fixture project apart from every
// id createProject() hands out below, without seed.js having to
// hard-code this literal a second time.
export const SEED_PROJECT_ID = "seed-project";

function readCreated() {
  const raw = storageRead(CREATED_KEY, []);
  return Array.isArray(raw) ? raw : [];
}

function emptyCounts() {
  return { itemsTotal: 0, itemsApproved: 0, warningsOpen: 0, missingInfo: 0 };
}

/** The one fixture project, with its counts read off the live snapshot so
 *  the dashboard and the review workspace can never disagree. Uses
 *  rules.js's countsTowardTotals() -- not a hand-copied `!item.rejected`
 *  filter -- so a superseded sheet's items are excluded here exactly as
 *  they are from seed.js's computeTotals() and the API's
 *  countable_items(), rather than a second, incomplete copy of that rule
 *  drifting out of sync with it. */
function fixtureProject(snapshot) {
  const sheetsById = Object.fromEntries(snapshot.sheets.map((s) => [s.id, s]));
  const live = snapshot.items.filter((item) => countsTowardTotals(item, sheetsById));
  return {
    id: SEED_PROJECT_ID,
    name: "Meridian Distribution Center",
    number: "26-0207",
    customer: "Bellweather Construction",
    location: "Stockton, CA",
    bidDueDate: null,
    stage: "review",
    revisionSetLabel: "E1.1 Rev 3 · E2.1 Rev 2 · E3.1 Rev 1",
    archivedAt: null,
    updatedAt: new Date().toISOString(),
    estimatorName: null,
    itemsTotal: live.length,
    itemsApproved: live.filter((item) => item.status === "approved").length,
    warningsOpen: live.filter((item) => item.status === "attention").length,
    missingInfo: live.filter((item) => item.status === "missing").length,
  };
}

export function createSeedProjects({ getSnapshot }) {
  // `getSnapshot` here must always resolve to the fixture project's own
  // data, regardless of which project the review workspace currently has
  // active -- seed.js passes its unconditional computeFixtureSnapshot(),
  // not the public, useProject()-gated getSnapshot() the store exposes.
  // The dashboard lists every project on every visit, including whichever
  // one a previous workspace visit last activated, so this call cannot
  // depend on that ambient state without the fixture row's own totals
  // going wrong the next time the dashboard renders.
  async function listProjects({ includeArchived = false } = {}) {
    const snapshot = await getSnapshot();
    const created = readCreated().filter((p) => includeArchived || !p.archivedAt);
    return [fixtureProject(snapshot), ...created];
  }

  async function createProject({
    name,
    location,
    number = "",
    customer = "",
    bidDueDate = null,
    estimatorUserId = null,
    // Accepted for contract parity with the API's createProject (and
    // schemas.py's own "accepted and ignored" construction_type field)
    // but not stored -- the seed Project shape has no field for it yet,
    // same as estimatorUserId below.
    constructionType = "",
  }) {
    // Mirrors ProjectCreateIn's not_only_whitespace validator (schemas.py)
    // so a blank name/location is refused the same way here and there,
    // rather than the seed store silently accepting what the API 422s on.
    if (!name?.trim()) throw { code: "invalid_request", message: "Enter a project name." };
    if (!location?.trim()) throw { code: "invalid_request", message: "Enter a project address." };

    const project = {
      id: `seed-${crypto.randomUUID()}`,
      name: name.trim(),
      number,
      customer,
      location: location.trim(),
      bidDueDate,
      // create_project() (projects.py): stage always starts at "setup" --
      // no document has been uploaded yet, so anything further along
      // would misreport on the dashboard.
      stage: "setup",
      revisionSetLabel: "",
      archivedAt: null,
      updatedAt: new Date().toISOString(),
      // estimatorUserId is accepted (contract parity with the API's
      // createProject) but not stored -- seed mode has no user directory
      // to resolve it against, so estimatorName stays null the way the
      // fixture project's does, rather than carrying a field the other
      // two Project shapes (fixtureProject, api-mapping.js's mapProject)
      // don't have.
      estimatorName: null,
      ...emptyCounts(),
    };
    storageWrite(CREATED_KEY, [...readCreated(), project]);
    return project;
  }

  return { listProjects, createProject };
}
