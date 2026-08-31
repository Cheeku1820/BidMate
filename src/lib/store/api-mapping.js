/* ============================================================
   api-mapping.js — every snake_case -> camelCase, Decimal-as-string ->
   number, ISO-8601 -> epoch-ms conversion between the API's wire shape
   (api/app/takeoff/schemas.py, api/app/collab/schemas.py,
   api/app/auth/schemas.py) and the store contract (task-15-report.md).
   Pure functions, no fetch, no state — split out of api.js so that
   file stays about transport (requests, caching, the ten carry-
   forwards) rather than growing past this project's ~300-line
   guideline with field-by-field mapping code, mirroring seed-fixture.js
   playing the same role for the seed store.
   ============================================================ */

export function mapWarning(w) {
  return { id: w.id, title: w.title, found: w.found, why: w.why, fix: w.fix, where: w.where, reason: w.reason };
}

export function mapItem(i) {
  return {
    id: i.id,
    sheetId: i.sheet_id,
    symbol: i.symbol,
    name: i.name,
    description: i.description,
    system: i.system,
    category: i.category,
    quantity: Number(i.quantity),
    unit: i.unit,
    status: i.status,
    version: i.version,
    approvedBy: i.approved_by ?? null,
    rejected: i.rejected,
    x: i.x ?? null,
    y: i.y ?? null,
    path: i.path ?? null,
    notes: i.notes,
    evidence: i.evidence ?? null,
    // Never collapsed to a singular field (carry-forward 3) — an item
    // can carry a scale warning and a legend warning at once.
    warnings: (i.warnings || []).map(mapWarning),
    // Money arrives as a Decimal string, the same way `quantity` does,
    // and is converted here rather than at each of the two places that
    // sum it — a string reaching a `+` is a silent concatenation.
    materialCost: Number(i.material_cost ?? 0),
    laborHours: Number(i.labor_hours ?? 0),
    laborCost: Number(i.labor_cost ?? 0),
    totalCost: Number(i.total_cost ?? 0),
    // Every coordinate this cluster was counted at. Without it a cluster
    // of 47 counted devices would render as one marker.
    placements: i.placements ?? null,
    aiConfirmed: i.ai_confirmed ?? false,
    // Counting's cluster tag, carried through unchanged -- a drafting
    // tag a human drew on the sheet ("R", "F2"), not processing
    // internals. Not rendered anywhere yet (Task 5).
    sourceTag: i.source_tag ?? "",
  };
}

// Built from fields mapItem already carries unchanged from the wire
// (evidence.has_image, id, version). The API sends this endpoint back
// with `Cache-Control: private, no-store` (it holds NDA'd drawing
// content, per api/app/main.py's global response policy), so there is
// no HTTP cache to bust here. The `?v=${item.version}` query param
// exists only to change the URL string when React re-renders after an
// item update, so an `<img src>` that would otherwise look unchanged
// still triggers a fresh fetch -- version already increments on every
// server-side rewrite of the item (approve/edit/reject/reprocess all
// bump it), which makes it a correct trigger for free.
export function evidenceImageUrl(item) {
  if (!item?.evidence?.has_image) return null;
  return `/api/items/${item.id}/evidence-image?v=${item.version}`;
}

export function mapSheet(s) {
  return {
    id: s.id,
    number: s.number,
    title: s.title,
    discipline: s.discipline,
    revision: s.revision,
    scale: s.scale,
    scaleOptions: s.scale_options,
    plan: s.plan,
    superseded: s.superseded,
    // Ingest metadata. The canvas addresses the rendered page image by
    // (takeoffId, pageIndex); the point dimensions are the extents the
    // marker coordinates were normalized against.
    takeoffId: s.takeoff_id ?? "",
    pageIndex: s.page_index ?? 0,
    widthPt: s.width_pt ?? 0,
    heightPt: s.height_pt ?? 0,
    // Non-empty on a sheet the engine could not read. It has to reach
    // the estimator: an unreadable sheet rendered as an empty one lets
    // silence read as completeness.
    unreadableReason: s.unreadable_reason ?? "",
    aiReading: s.ai_reading ?? null,
  };
}

export function mapTotals(t) {
  const bySystem = {};
  for (const [system, value] of Object.entries(t.by_system || {})) bySystem[system] = Number(value);
  return {
    bySystem,
    approvedCount: t.approved_count,
    remainingCount: t.remaining_count,
    attentionCount: t.attention_count,
    missingCount: t.missing_count,
    approvedUnits: Number(t.approved_units),
  };
}

export function mapUndo(u) {
  return {
    canUndo: u.can_undo,
    canRedo: u.can_redo,
    undoLabel: u.undo_label ?? null,
    undoBy: u.undo_by ?? null,
    redoLabel: u.redo_label ?? null,
  };
}

export function mapPresence(p) {
  return {
    userId: p.user_id,
    name: p.name,
    color: p.color,
    sheetId: p.sheet_id ?? null,
    itemId: p.item_id ?? null,
    // Epoch milliseconds, never the ISO-8601 string the API sends —
    // local-transport.js:140 does `now - p.seenAt` arithmetic on this,
    // which is a silent NaN against a string (carry-forward 2).
    seenAt: Date.parse(p.seen_at),
  };
}

export function mapSnapshot(s) {
  return {
    version: s.version,
    sheets: s.sheets.map(mapSheet),
    items: s.items.map(mapItem),
    totals: mapTotals(s.totals),
    undo: mapUndo(s.undo),
    presence: s.presence.map(mapPresence),
  };
}

/** Wire note -> client note. `usage` decides whether this note feeds the
 *  engine; the calculation-effect label the screen shows is derived from
 *  it and from scope, never stored. */
export function mapNote(raw) {
  return {
    id: raw.id,
    projectId: raw.project_id,
    scope: raw.scope,
    scopeRef: raw.scope_ref ?? null,
    title: raw.title,
    body: raw.body,
    category: raw.category,
    status: raw.status,
    rfiNeeded: Boolean(raw.rfi_needed),
    usage: raw.usage,
    sourceRef: raw.source_ref ?? "",
    obsoleteAfterRevision: raw.obsolete_after_revision ?? "",
    authorName: raw.author_name ?? "",
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
    appliedAt: raw.applied_at ?? null,
  };
}

/** Client note fields -> the wire shape NoteCreateIn/NoteUpdateIn expect.
 *  The store owns the wire shape in both directions: a caller writes the
 *  same camelCase names it reads back, and nothing has to remember that
 *  one direction is snake_case. Unknown keys are dropped rather than
 *  forwarded -- the server's schema forbids extras, so passing one
 *  through would turn a caller's typo into a 422 about a field they
 *  believe they set. */
export function noteToWire(fields) {
  const KEY_MAP = {
    scope: "scope",
    scopeRef: "scope_ref",
    title: "title",
    body: "body",
    category: "category",
    status: "status",
    rfiNeeded: "rfi_needed",
    usage: "usage",
    sourceRef: "source_ref",
    obsoleteAfterRevision: "obsolete_after_revision",
  };
  const body = {};
  for (const [clientKey, wireKey] of Object.entries(KEY_MAP)) {
    // Only when the caller actually supplied the field -- a PATCH that
    // omits a key must omit it on the wire too, rather than sending it
    // as `undefined` (JSON.stringify drops that anyway) or, worse, as an
    // explicit null that would overwrite the stored value.
    if (Object.prototype.hasOwnProperty.call(fields, clientKey)) {
      body[wireKey] = fields[clientKey];
    }
  }
  return body;
}

export function mapUser(u) {
  return { id: u.id, name: u.name, email: u.email, color: u.color };
}

/** Wire shape -> store shape for a project row. ProjectOut is the one
 *  schema in schemas.py that carries its own camelCase alias generator
 *  (schemas.py's CAMEL_MODEL_CONFIG comment), so this is a field
 *  allow-list rather than a snake_case rename: it keeps a field the API
 *  adds later from silently reaching the client before anything is
 *  designed to render it. */
export function mapProject(raw) {
  return {
    id: raw.id,
    name: raw.name,
    number: raw.number ?? "",
    customer: raw.customer ?? "",
    location: raw.location ?? "",
    bidDueDate: raw.bidDueDate ?? null,
    stage: raw.stage,
    revisionSetLabel: raw.revisionSetLabel ?? "",
    archivedAt: raw.archivedAt ?? null,
    updatedAt: raw.updatedAt,
    estimatorName: raw.estimatorName ?? null,
    itemsTotal: Number(raw.itemsTotal ?? 0),
    itemsApproved: Number(raw.itemsApproved ?? 0),
    warningsOpen: Number(raw.warningsOpen ?? 0),
    missingInfo: Number(raw.missingInfo ?? 0),
  };
}
