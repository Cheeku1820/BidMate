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
  };
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
