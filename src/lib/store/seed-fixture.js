/* ============================================================
   seed-fixture.js — data.js -> contract shape.

   The only place data.js's camelCase-but-singular-warning shape gets
   turned into the store contract's shape: `warning` (singular) becomes
   `warnings` (array, task-15-brief.md decision 2), and every field name
   already matches api/app/takeoff/schemas.py's ItemOut/SheetOut after
   conversion to camelCase (task-15-brief.md decision 1).
   ============================================================ */

import { SHEETS, ITEMS } from "../data.js";

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
 *  rules.js's scaleWarnings/nonScaleWarnings would silently mishandle. */
function toWarnings(itemId, warning) {
  if (!warning) return [];
  const reason = WARNING_REASON_BY_TITLE[warning.title];
  if (!reason) {
    throw new Error(`seed-fixture.js: no WARNING_REASON_BY_TITLE entry for "${warning.title}" (item ${itemId})`);
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

export function seedItems() {
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

export function seedSheets() {
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
