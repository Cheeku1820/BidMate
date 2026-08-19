/* ============================================================
   api.fakebackend.js — test-only. Not imported by src/App.jsx or any
   production code path; contract.test.js is the only consumer.

   "Extend the existing contract suite so both stores run the shared
   shape assertions" (task-16-brief.md §5) means running the SAME
   assertions — concurrency, scale release, bulk exclusion, the
   camelCase/array/number contract itself — against createApiStore(),
   not just checking its methods exist. Doing that against a live
   Python process is what the manual verification section is for;
   inside `npm test`, this module stands in for the FastAPI app: it
   wraps a real createSeedStore() (already reviewed, already the
   ground truth for every one of these rules — see seed.js, seed-
   review.js, seed-scale.js, seed-undo.js) and translates its
   camelCase/number results into exactly the wire shape
   api/app/takeoff/schemas.py produces (snake_case, Decimal-as-string,
   ISO-8601 timestamps), then hands that back through a `global.fetch`
   stub. Running contract.test.js's shared assertions against
   `createApiStore()` this way genuinely exercises api.js's own
   request/response mapping code — the actual Task 16 deliverable —
   rather than re-testing seed.js a second time under a different name.

   Deliberately not a byte-for-byte FastAPI reimplementation: no
   Pydantic validation, no tenancy, no real HTTP. Just enough surface
   for every endpoint api.js actually calls to round-trip through wire
   shape and back.
   ============================================================ */

import { createSeedStore } from "./seed.js";

// api/app/errors.py's DomainError carries its own `status`; this module's
// seed store methods throw plain {code, message} without one (rules.js /
// seed-review.js are HTTP-agnostic), so the status a real endpoint would
// answer with is reconstructed here from the code, mirroring the actual
// status each Python route raises with today.
const STATUS_BY_CODE = {
  not_signed_in: 401,
  stale_item_version: 409,
  item_no_longer_exists: 404,
  sheet_not_found: 404,
  missing_information_blocks_approval: 400,
  rejected_item_cannot_be_approved: 400,
  field_not_editable: 422,
  field_cannot_be_empty: 422,
  invalid_quantity: 422,
  no_changes_to_apply: 400,
  // Only invalid_request appears here, not estimator_not_found: the seed
  // store's createProject() has no estimator-org check to throw that
  // code, and this file's own stated scope is "just enough surface for
  // every endpoint api.js actually calls" -- a status for a code nothing
  // throws is speculative, not surface.
  invalid_request: 422,
};

function toWireWarning(w) {
  return { id: w.id, title: w.title, found: w.found, why: w.why, fix: w.fix, where: w.where, reason: w.reason };
}

function toWireItem(item) {
  return {
    id: item.id,
    sheet_id: item.sheetId,
    symbol: item.symbol,
    name: item.name,
    description: item.description,
    system: item.system,
    category: item.category,
    quantity: item.quantity.toFixed(2),
    unit: item.unit,
    status: item.status,
    version: item.version,
    approved_by: item.approvedBy ?? null,
    rejected: item.rejected,
    x: item.x ?? null,
    y: item.y ?? null,
    path: item.path ?? null,
    notes: item.notes,
    evidence: item.evidence ?? null,
    warnings: (item.warnings || []).map(toWireWarning),
  };
}

function toWireSheet(sheet) {
  return {
    id: sheet.id,
    number: sheet.number,
    title: sheet.title,
    discipline: sheet.discipline,
    revision: sheet.revision,
    scale: sheet.scale,
    scale_options: sheet.scaleOptions,
    plan: sheet.plan,
    superseded: sheet.superseded,
  };
}

function toWireTotals(totals) {
  const by_system = {};
  for (const [system, value] of Object.entries(totals.bySystem)) by_system[system] = value.toFixed(2);
  return {
    by_system,
    approved_count: totals.approvedCount,
    remaining_count: totals.remainingCount,
    attention_count: totals.attentionCount,
    missing_count: totals.missingCount,
    approved_units: totals.approvedUnits.toFixed(2),
  };
}

function toWireUndo(undo) {
  return { can_undo: undo.canUndo, can_redo: undo.canRedo, undo_label: undo.undoLabel, undo_by: undo.undoBy, redo_label: undo.redoLabel };
}

function toWirePresence(p) {
  return { user_id: p.userId, name: p.name, color: p.color, sheet_id: p.sheetId, item_id: p.itemId, seen_at: new Date(p.seenAt).toISOString() };
}

// ProjectOut is the one schema in schemas.py that carries its own
// camelCase alias generator (CAMEL_MODEL_CONFIG), so unlike every other
// toWire* helper in this file, this one isn't a snake_case rename -- the
// wire shape and the store shape already agree on field names. Kept as an
// explicit allow-list anyway, matching mapProject's own reasoning in
// api-mapping.js: a field the store adds later shouldn't silently reach
// the wire before anything is designed to send it.
function toWireProject(project) {
  return {
    id: project.id,
    name: project.name,
    number: project.number,
    customer: project.customer,
    location: project.location,
    bidDueDate: project.bidDueDate,
    stage: project.stage,
    revisionSetLabel: project.revisionSetLabel,
    archivedAt: project.archivedAt,
    updatedAt: project.updatedAt,
    estimatorName: project.estimatorName,
    itemsTotal: project.itemsTotal,
    itemsApproved: project.itemsApproved,
    warningsOpen: project.warningsOpen,
    missingInfo: project.missingInfo,
  };
}

function toWireSnapshot(snapshot) {
  return {
    version: snapshot.version,
    sheets: snapshot.sheets.map(toWireSheet),
    items: snapshot.items.map(toWireItem),
    totals: toWireTotals(snapshot.totals),
    undo: toWireUndo(snapshot.undo),
    presence: snapshot.presence.map(toWirePresence),
  };
}

function jsonResponse(body, status = 200) {
  if (body === null) return new Response(null, { status });
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function errorResponse(err) {
  const code = err?.code ?? "request_failed";
  const message = err?.message ?? "The request failed.";
  const status = STATUS_BY_CODE[code] ?? 400;
  return jsonResponse({ detail: { code, message } }, status);
}

/** Installs a `global.fetch` stub backed by a fresh createSeedStore(),
 *  and returns that same store so a test can also drive it directly
 *  (mirroring the real API, where the same rules apply whichever door
 *  a change comes through). Callers are responsible for
 *  `vi.unstubAllGlobals()` in an `afterEach`. */
export function installFakeApiBackend() {
  const seed = createSeedStore();

  async function handle(path, init = {}) {
    const method = init.method ?? "GET";
    const headers = init.headers ?? {};
    const body = init.body ? JSON.parse(init.body) : undefined;

    try {
      if (method === "GET" && path === "/api/auth/me") {
        return jsonResponse(await seed.me());
      }

      const projectsMatch = path.match(/^\/api\/projects(?:\?(.*))?$/);
      if (method === "GET" && projectsMatch) {
        const params = new URLSearchParams(projectsMatch[1] ?? "");
        const includeArchived = params.get("includeArchived") === "true";
        const projects = await seed.listProjects({ includeArchived });
        return jsonResponse(projects.map(toWireProject));
      }
      if (method === "POST" && path === "/api/projects") {
        const created = await seed.createProject(body ?? {});
        return jsonResponse(toWireProject(created), 201);
      }

      const snapshotMatch = path.match(/^\/api\/projects\/([^/]+)\/snapshot$/);
      if (method === "GET" && snapshotMatch) {
        const snapshot = await seed.getSnapshot();
        if (headers["If-None-Match"] && headers["If-None-Match"] === snapshot.version) {
          return jsonResponse(null, 304);
        }
        return jsonResponse(toWireSnapshot(snapshot));
      }

      const approveMatch = path.match(/^\/api\/items\/([^/]+)\/approve$/);
      if (method === "POST" && approveMatch) {
        const r = await seed.approveItem(approveMatch[1], Number(headers["If-Match"]));
        return jsonResponse({ label: r.label, version: r.version, item: toWireItem(r.item) });
      }

      const rejectMatch = path.match(/^\/api\/items\/([^/]+)\/reject$/);
      if (method === "POST" && rejectMatch) {
        const r = await seed.rejectItem(rejectMatch[1], Number(headers["If-Match"]));
        return jsonResponse({ label: r.label, version: r.version, item: toWireItem(r.item) });
      }

      const unrejectMatch = path.match(/^\/api\/items\/([^/]+)\/unreject$/);
      if (method === "POST" && unrejectMatch) {
        const r = await seed.unrejectItem(unrejectMatch[1], Number(headers["If-Match"]));
        return jsonResponse({ label: r.label, version: r.version, item: toWireItem(r.item) });
      }

      const itemMatch = path.match(/^\/api\/items\/([^/]+)$/);
      if (method === "PATCH" && itemMatch) {
        const changes = { ...body };
        if ("quantity" in changes) changes.quantity = Number(changes.quantity);
        const r = await seed.editItem(itemMatch[1], changes, Number(headers["If-Match"]));
        return jsonResponse({ label: r.label, version: r.version, item: toWireItem(r.item) });
      }
      if (method === "DELETE" && itemMatch) {
        const r = await seed.deleteItem(itemMatch[1], Number(headers["If-Match"]));
        return jsonResponse({ label: r.label, version: r.version, item: null });
      }

      const scaleMatch = path.match(/^\/api\/sheets\/([^/]+)\/scale$/);
      if (method === "POST" && scaleMatch) {
        const r = await seed.setScale(scaleMatch[1], body.value);
        return jsonResponse({ label: r.label, snapshot: toWireSnapshot(r.snapshot) });
      }

      const undoMatch = path.match(/^\/api\/projects\/([^/]+)\/undo$/);
      if (method === "POST" && undoMatch) {
        const r = await seed.undo();
        if (!r.performed) return jsonResponse({ performed: false });
        return jsonResponse({ performed: true, label: r.label, snapshot: toWireSnapshot(r.snapshot) });
      }

      const redoMatch = path.match(/^\/api\/projects\/([^/]+)\/redo$/);
      if (method === "POST" && redoMatch) {
        const r = await seed.redo();
        if (!r.performed) return jsonResponse({ performed: false });
        return jsonResponse({ performed: true, label: r.label, snapshot: toWireSnapshot(r.snapshot) });
      }

      if (method === "PUT" && path === "/api/presence") {
        await seed.setPresence({ sheetId: body.sheet_id, itemId: body.item_id });
        return jsonResponse(null, 204);
      }

      throw { code: "not_found", message: `fakebackend: no route for ${method} ${path}` };
    } catch (err) {
      if (err && typeof err === "object" && typeof err.code === "string") return errorResponse(err);
      throw err;
    }
  }

  const fetchStub = async (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    return handle(path, init ?? {});
  };

  return { fetchStub, seed };
}
