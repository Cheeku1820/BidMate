/* ============================================================
   seed-projects.js — the projects list for seed mode.

   The seed fixture is one project (src/lib/store/seed-fixture.js), and
   before this file the seed store had no concept of a project at all.
   Rather than invent a second fixture, the seeded project is derived
   from the snapshot that already exists, so its counts cannot drift
   from what the review workspace shows for the same project.

   Projects created here live in localStorage alongside the rest of seed
   state. They have no sheets and no items, which is honest: seed mode
   has no ingestion, so a new project genuinely is empty.

   Imports nothing from api.js or api-mapping.js -- deleting seed mode
   must stay a matter of deleting these files (CLAUDE.md, "Sync is
   single-machine").
   ============================================================ */

import { storageRead, storageWrite } from "./local-transport.js";

const CREATED_KEY = "projects";
const SEED_PROJECT_ID = "seed-project";

function readCreated() {
  const raw = storageRead(CREATED_KEY, []);
  return Array.isArray(raw) ? raw : [];
}

function emptyCounts() {
  return { itemsTotal: 0, itemsApproved: 0, warningsOpen: 0, missingInfo: 0 };
}

/** The one fixture project, with its counts read off the live snapshot so
 *  the dashboard and the review workspace can never disagree. Mirrors
 *  api/app/takeoff/totals.py's countable_items() predicate: not rejected. */
function fixtureProject(snapshot) {
  const live = snapshot.items.filter((item) => !item.rejected);
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
      estimatorName: null,
      estimatorUserId,
      ...emptyCounts(),
    };
    storageWrite(CREATED_KEY, [...readCreated(), project]);
    return project;
  }

  return { listProjects, createProject };
}
