/* ============================================================
   api.js — the real backend implementation of the store interface
   (task-15-brief.md). Every method is a `fetch` against the endpoints
   from Tasks 1–14, with `credentials: "include"` so the httpOnly
   session cookie rides along, and this module owns every conversion
   between the API's wire shape and the store's contract (camelCase,
   `warnings` as an array, quantities/totals as numbers) — see
   task-15-report.md and task-16-brief.md section 3 for the full list
   of carry-forwards this file exists to satisfy:

     1. Decimal strings (quantity, approved_units, every by_system
        value) become numbers.
     2. seen_at (ISO-8601) becomes epoch milliseconds via Date.parse.
     3. warnings is never collapsed back to a singular field.
     4. A 304 has an EMPTY body (Cache-Control: no-store means the
        browser has nothing to replay) — the version is held here, in
        this module's own closure state, and a 304 returns the
        previously cached snapshot rather than trying to parse nothing.
     5. If-Match: <item.version> on the five single-item mutations,
        surfacing stale_item_version as an ordinary {code, message}
        rejection.
     6. quantity is sent as a string with at most two decimals, never a
        bare number.
     7. PATCH bodies carry only the five editable fields, never a whole
        ItemOut (EditIn rejects unknown keys with a 422).
     8. Every rejection has the same {code, message} shape the seed
        store throws, so callers cannot tell the two stores apart.
     9. Absent vs explicit-null in undo/redo responses is never
        distinguished (`?? null` treats both identically).
    10. The presence beat is derived from collab/service.py's
        documented ASSUMED_HEARTBEAT_INTERVAL (10s) rather than an
        unrelated fourth magic number — see PRESENCE_BEAT_MS below.

   This module intentionally does not compute anything the server is
   authoritative for (totals, undo state) — see getSnapshot()'s and
   mutateItem()'s comments for how the small local cache stays honest
   about that rather than reconstructing server state by hand.

   Every snake_case -> camelCase / Decimal-string -> number / ISO-8601
   -> epoch-ms conversion lives in api-mapping.js, not here — this file
   is about transport (requests, the version cache, the ten carry-
   forwards); that one is pure field mapping, split out the same way
   seed-fixture.js is split out of seed.js.
   ============================================================ */

import { mapItem, mapProject, mapSnapshot, mapUser } from "./api-mapping.js";

const POLL_INTERVAL_MS = 3000;

// Mirrors api/app/collab/service.py's ASSUMED_HEARTBEAT_INTERVAL (10s),
// the documented assumption its 30s active window is built on three of.
// Half of that, not an unrelated fourth number the way an unexplained
// literal 5000 would be — a beat any slower than the server's own
// assumption risks a reviewer reading as "gone" to a colleague between
// heartbeats.
const ASSUMED_HEARTBEAT_INTERVAL_MS = 10_000;
export const PRESENCE_BEAT_MS = ASSUMED_HEARTBEAT_INTERVAL_MS / 2;

const EDITABLE_FIELDS = ["system", "category", "quantity", "notes", "symbol"];

/* --- error shape --------------------------------------------------------

   Every non-2xx response gets turned into the same {code, message}
   shape rules.js/seed-review.js throw, whatever FastAPI actually put in
   the body: app/errors.py's DomainError handler nests it under
   `detail: {code, message}`; FastAPI's own 422s put a *list* of
   validator errors under `detail`; a bare HTTPException (none of which
   this API raises today, but nothing guarantees that forever) puts a
   plain string there. All three collapse to one shape here so a caller
   never has to know which kind of failure it was looking at. */

async function parseErrorBody(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  const detail = body?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && typeof detail.code === "string" && typeof detail.message === "string") {
    return { code: detail.code, message: detail.message };
  }
  if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") {
    return { code: "invalid_request", message: detail[0].msg };
  }
  if (typeof detail === "string" && detail) {
    return { code: "request_failed", message: detail };
  }
  return { code: "request_failed", message: `The request failed (status ${res.status}). Try again.` };
}

async function request(path, { method = "GET", body, headers = {} } = {}) {
  const init = { method, credentials: "include", headers: { ...headers } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (!res.ok) throw await parseErrorBody(res);
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

/** Not part of the store interface (METHODS in contract.test.js) — the
 *  seed store has no login concept at all, since it invents an identity
 *  on first use. Login.jsx imports this directly rather than going
 *  through createApiStore(), and only ever renders when the api store
 *  is in use in the first place. */
export async function login(email, password) {
  const raw = await request("/api/auth/login", { method: "POST", body: { email, password } });
  return mapUser(raw);
}

export function createApiStore() {
  // The route owns the project id now (task-6-brief.md Step 7):
  // Workspace.jsx calls store.useProject(projectId) from a useEffect
  // keyed on the route param, before its first snapshot fetch. `null`
  // here just means "nothing has set one yet" — ensureProjectId() below
  // still falls back to "the first project the signed-in account can
  // see" for any caller that hasn't been given one, which after this
  // task is nothing on the review path, but keeps this store usable
  // from a REPL or a future single-project caller without a route.
  let projectId = null;

  // getSnapshot()'s own cache, keyed by the version string this module
  // last saw. Required, not an optimization: carry-forward 4 — a 304's
  // body is empty (Cache-Control: no-store means there is nothing for
  // the browser to replay), so the only way to answer "nothing changed"
  // is to already be holding the last thing that didn't change.
  let cachedVersion = null;
  let cachedSnapshot = null;

  function cacheSnapshot(mapped) {
    cachedVersion = mapped.version;
    cachedSnapshot = mapped;
  }

  // A single-item mutation's response (ItemMutationOut) carries the new
  // project-wide version string, but not fresh totals or undo state —
  // those did change (an approval moves approvedUnits; any mutation
  // moves the undo head) but this module has no way to recompute them
  // without duplicating a server-only computation (invariant 1: totals
  // are computed in exactly one place). Rather than cache a snapshot
  // that is right about its one changed item and quietly wrong about
  // everything else, every mutation just invalidates the cache — the
  // next getSnapshot() (the following poll, at most POLL_INTERVAL_MS
  // away) does a full unconditional fetch instead of risking a 304
  // against state nobody re-derived. Writes are not optimistic
  // (task-16-brief.md, "Constraints") — the mutation's own response is
  // what the caller renders immediately; this cache is purely about
  // what the *next poll* is allowed to skip re-fetching.
  function invalidateCache() {
    cachedVersion = null;
    cachedSnapshot = null;
  }

  // Sets the id the rest of this store's methods resolve against.
  // Synchronous and side-effect-only on purpose: ProjectWorkspaceLayout
  // calls this from a useEffect keyed on useParams().projectId, and that
  // effect has to run — and this assignment has to land — before the
  // same render's data-fetching effect in useReviewStore.js fires its
  // first getSnapshot(). Both effects are declared in the same
  // component; effects run in declaration order, so calling
  // store.useProject(id) ahead of useReviewStore(store) in the layout's
  // body is what keeps this from racing the first fetch, not anything
  // async here.
  function useProject(id) {
    projectId = id;
    invalidateCache();
  }

  async function ensureProjectId() {
    if (projectId) return projectId;
    const projects = await request("/api/projects");
    if (!Array.isArray(projects) || projects.length === 0) {
      throw { code: "no_project_available", message: "No project is available for this account." };
    }
    projectId = projects[0].id;
    return projectId;
  }

  async function me() {
    return mapUser(await request("/api/auth/me"));
  }

  async function getSnapshot() {
    const pid = await ensureProjectId();
    const headers = cachedVersion ? { "If-None-Match": cachedVersion } : {};
    const res = await fetch(`/api/projects/${pid}/snapshot`, { credentials: "include", headers });
    if (res.status === 304) {
      if (cachedSnapshot) return cachedSnapshot;
      // No local cache to answer a 304 with (a fresh store instance
      // that somehow still sent a version, or a cache someone cleared) —
      // fall through to an unconditional fetch rather than returning
      // nothing.
      cachedVersion = null;
      return getSnapshot();
    }
    if (!res.ok) throw await parseErrorBody(res);
    const body = await res.json();
    const mapped = mapSnapshot(body);
    cacheSnapshot(mapped);
    return mapped;
  }

  function subscribe(handler) {
    const iv = setInterval(handler, POLL_INTERVAL_MS);
    return () => clearInterval(iv);
  }

  async function setPresence({ sheetId, itemId }) {
    const pid = await ensureProjectId();
    await request("/api/presence", {
      method: "PUT",
      body: { project_id: pid, sheet_id: sheetId ?? null, item_id: itemId ?? null },
    });
  }

  async function mutateItem(method, path, expectedVersion, body) {
    const raw = await request(path, {
      method,
      headers: { "If-Match": String(expectedVersion) },
      body,
    });
    invalidateCache();
    return { label: raw.label, version: raw.version, item: raw.item ? mapItem(raw.item) : null };
  }

  async function approveItem(id, expectedVersion) {
    return mutateItem("POST", `/api/items/${id}/approve`, expectedVersion);
  }

  async function rejectItem(id, expectedVersion) {
    return mutateItem("POST", `/api/items/${id}/reject`, expectedVersion);
  }

  async function unrejectItem(id, expectedVersion) {
    return mutateItem("POST", `/api/items/${id}/unreject`, expectedVersion);
  }

  function toQuantityString(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) {
      throw { code: "invalid_quantity", message: "Quantity must be a number, such as 14 or 3.5. Correct it and save the edit again." };
    }
    // At most two decimals, always — EditIn's validator refuses more
    // than two and refuses a bare JSON number outright (carry-forward
    // 6). toFixed(2) satisfies both in one step.
    return num.toFixed(2);
  }

  async function editItem(id, changes, expectedVersion) {
    const body = {};
    for (const key of Object.keys(changes)) {
      // Never round-trip a whole ItemOut — only these five fields exist
      // on EditIn, and it rejects anything else with a 422
      // (carry-forward 7). Callers are expected to pass only these,
      // but this filters defensively rather than trusting that.
      if (!EDITABLE_FIELDS.includes(key)) continue;
      body[key] = key === "quantity" ? toQuantityString(changes[key]) : changes[key];
    }
    return mutateItem("PATCH", `/api/items/${id}`, expectedVersion, body);
  }

  async function deleteItem(id, expectedVersion) {
    return mutateItem("DELETE", `/api/items/${id}`, expectedVersion);
  }

  async function setScale(sheetId, value) {
    const raw = await request(`/api/sheets/${sheetId}/scale`, { method: "POST", body: { value } });
    const mapped = { label: raw.label, snapshot: mapSnapshot(raw.snapshot) };
    // Unlike a single-item mutation, this response IS a complete,
    // authoritative snapshot (ScaleMutationOut.snapshot), so it can
    // repopulate the cache directly instead of invalidating it.
    cacheSnapshot(mapped.snapshot);
    return mapped;
  }

  async function undoOrRedo(segment) {
    const pid = await ensureProjectId();
    const raw = await request(`/api/projects/${pid}/${segment}`, { method: "POST" });
    if (!raw.performed) return { performed: false };
    const snapshot = raw.snapshot ? mapSnapshot(raw.snapshot) : null;
    if (snapshot) cacheSnapshot(snapshot);
    // `raw.label` is `null` either because the key was omitted or sent
    // explicitly as null — UndoRedoOut never distinguishes the two, and
    // neither does this (`?? null`), per carry-forward 9.
    return { performed: true, label: raw.label ?? null, snapshot };
  }

  // A compound action like setScale: the response IS a complete,
  // authoritative snapshot (BulkApproveOut.snapshot), so it repopulates
  // the cache directly. `skipped[].item_id` becomes `itemId` here, the
  // same snake_case -> camelCase boundary every other wire shape crosses
  // in this file.
  async function bulkApprove(itemIds) {
    const pid = await ensureProjectId();
    const raw = await request(`/api/projects/${pid}/items/bulk-approve`, {
      method: "POST",
      body: { item_ids: itemIds },
    });
    const snapshot = mapSnapshot(raw.snapshot);
    cacheSnapshot(snapshot);
    return {
      approved: raw.approved ?? [],
      skipped: (raw.skipped ?? []).map((s) => ({ itemId: s.item_id, code: s.code, message: s.message })),
      snapshot,
    };
  }

  async function undo() {
    return undoOrRedo("undo");
  }

  async function redo() {
    return undoOrRedo("redo");
  }

  async function listProjects({ includeArchived = false } = {}) {
    const query = includeArchived ? "?includeArchived=true" : "";
    const raw = await request(`/api/projects${query}`);
    return Array.isArray(raw) ? raw.map(mapProject) : [];
  }

  async function createProject({
    name,
    location,
    number = "",
    customer = "",
    bidDueDate = null,
    estimatorUserId = null,
    // Forwarded, not stored server-side yet: ProjectCreateIn.construction_type
    // (schemas.py) accepts and ignores it by design until a real column
    // lands -- but that only holds if the client actually sends it. Dropping
    // it here, after NewProject.jsx collects it, would make the estimator's
    // answer vanish with no trace instead of merely going unused.
    constructionType = "",
  }) {
    const raw = await request("/api/projects", {
      method: "POST",
      body: {
        name,
        location,
        number,
        customer,
        bidDueDate,
        estimatorUserId,
        constructionType,
      },
    });
    return mapProject(raw);
  }

  /** Writes a processed takeoff into the project. The server replaces
   *  rather than appends, and refuses with `approved_items_present` when
   *  that would discard estimator approvals — pass confirmReplace only
   *  after a person has actually been asked. */
  async function attachEngineTakeoff(id, payload, { confirmReplace = false } = {}) {
    const result = await request(`/api/projects/${id}/takeoff`, {
      method: "POST",
      body: { payload, confirm_replace: confirmReplace },
    });
    invalidateCache();
    return result;
  }

  return {
    me,
    useProject,
    getSnapshot,
    subscribe,
    setPresence,
    approveItem,
    rejectItem,
    unrejectItem,
    editItem,
    deleteItem,
    setScale,
    bulkApprove,
    undo,
    redo,
    listProjects,
    createProject,
    attachEngineTakeoff,
  };
}
