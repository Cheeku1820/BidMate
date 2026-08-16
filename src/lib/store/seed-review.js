/* ============================================================
   seed-review.js — approve, reject, unreject, edit, delete.

   Mirrors api/app/takeoff/review.py: the five single-item review
   mutations, split into their own module for the same reason
   review.py is its own module rather than folded into scale.py or
   undo.py — a materially different act from the sheet-level compound
   action (seed-scale.js) or from reversing a past action
   (seed-undo.js).

   Every function here takes `deps` — the low-level read/write
   primitives seed.js assembles (readItems, commitAction, identity,
   uid, readVersion, readHist) — rather than closing over module-level
   state, so this module has no storage of its own and cannot drift
   from what seed.js actually persists.

   Each of the five now takes an `expectedVersion` argument (task-13b-
   brief.md), mirroring the server's `If-Match` contract on the same
   five mutations: the item's current `version` must match what the
   caller last saw, or the write is refused with `stale_item_version`
   rather than silently clobbering a concurrent change. There is no
   server behind this store, so the check has to live here instead of
   in a service the client merely calls — the same reason this store
   already enforces refusalToApprove(). The reviewer-naming enrichment
   (staleVersionRefusal() below) is this module's counterpart to
   api/app/takeoff/concurrency.py's _stale_version_message(): rules.js
   owns the plain equality check and its generic message, this module
   layers on a name when the shared `hist` stack has one, the same
   division of labor as review.py (the rule) vs concurrency.py (the
   actor lookup) on the server.
   ============================================================ */

import { refusalToApprove, refusalToStaleVersion } from "../rules.js";

const ITEM_NO_LONGER_EXISTS = {
  code: "item_no_longer_exists",
  message: "This item was deleted by another reviewer. Refresh the sheet to see its current items.",
};

// Mirrors review.py's EDITABLE_FIELDS/REQUIRED_TEXT_FIELDS. Deliberately
// does not replicate Numeric(12,2)'s max-magnitude or two-decimal-place
// rounding checks — those are a Postgres storage constraint, not a
// domain rule, and the store's Decimal->number decision (task-15-report.md)
// already means quantity never round-trips through a fixed-precision
// column on the client. A finite, non-negative number is what this layer
// can actually promise.
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

export function createReviewMethods({ readItems, readHist, commitAction, identity, uid, readVersion }) {
  function findItemOrThrow(id) {
    const items = readItems();
    const item = items.find((i) => i.id === id);
    if (!item) throw ITEM_NO_LONGER_EXISTS;
    return { items, item };
  }

  // The one extra lookup on the refusal path only (never on success),
  // matching concurrency.py's _stale_version_message() -- names whoever
  // the shared hist stack's most recent entry for this item credits,
  // falling back to rules.js's generic message when there is none.
  function staleVersionRefusal(item, expectedVersion) {
    const refusal = refusalToStaleVersion(item, expectedVersion);
    if (!refusal) return null;
    const lastAction = [...readHist().undo].reverse().find((a) => a.itemId === item.id);
    if (lastAction?.by) {
      return {
        code: refusal.code,
        message: `${lastAction.by} changed this item after you loaded it. Refresh the sheet to see the current value, then try again.`,
      };
    }
    return refusal;
  }

  function mutationResult(action, nextItems, id) {
    commitAction(action, nextItems);
    return { label: action.label, version: String(readVersion()), item: nextItems.find((i) => i.id === id) };
  }

  async function approveItem(id, expectedVersion) {
    const { items, item } = findItemOrThrow(id);
    const staleness = staleVersionRefusal(item, expectedVersion);
    if (staleness) throw staleness;
    const refusal = refusalToApprove(item);
    if (refusal) throw refusal;

    const actor = identity();
    const before = { status: item.status, approvedBy: item.approvedBy };
    const after = { status: "approved", approvedBy: actor.name };
    // The version bump is applied to nextItems directly, not folded into
    // `after` -- `after` is what the recorded action replays on
    // undo/redo, and the counter must never be part of that replay (see
    // seed-undo.js: undo/redo bump it forward themselves instead).
    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after, version: i.version + 1 } : i));
    const action = { id: uid("a"), kind: "approve", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Approved ${item.name}` };
    return mutationResult(action, nextItems, id);
  }

  async function rejectItem(id, expectedVersion) {
    const { items, item } = findItemOrThrow(id);
    const staleness = staleVersionRefusal(item, expectedVersion);
    if (staleness) throw staleness;
    // Rejection is tracked separately from review status (review.py's
    // _apply_reject() never touches item.status) so unrejecting can
    // restore the item exactly as it was, without having to guess what
    // status it used to carry.
    const actor = identity();
    const before = { rejected: item.rejected };
    const after = { rejected: true };
    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after, version: i.version + 1 } : i));
    const action = { id: uid("a"), kind: "reject", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Rejected ${item.name}` };
    return mutationResult(action, nextItems, id);
  }

  async function unrejectItem(id, expectedVersion) {
    const { items, item } = findItemOrThrow(id);
    const staleness = staleVersionRefusal(item, expectedVersion);
    if (staleness) throw staleness;
    const actor = identity();
    const before = { rejected: item.rejected };
    const after = { rejected: false };
    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after, version: i.version + 1 } : i));
    const action = { id: uid("a"), kind: "unreject", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Restored ${item.name}` };
    return mutationResult(action, nextItems, id);
  }

  async function editItem(id, changes, expectedVersion) {
    const { items, item } = findItemOrThrow(id);
    validateEdit(changes);
    const staleness = staleVersionRefusal(item, expectedVersion);
    if (staleness) throw staleness;

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

    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after, version: i.version + 1 } : i));
    const action = { id: uid("a"), kind: "edit", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Edited ${item.name}` };
    return mutationResult(action, nextItems, id);
  }

  async function deleteItem(id, expectedVersion) {
    const { items, item } = findItemOrThrow(id);
    const staleness = staleVersionRefusal(item, expectedVersion);
    if (staleness) throw staleness;
    const index = items.findIndex((i) => i.id === id);
    const actor = identity();
    const nextItems = items.filter((i) => i.id !== id);
    const action = { id: uid("a"), kind: "delete", itemId: id, index, snapshot: item, by: actor.name, at: Date.now(), label: `Deleted ${item.name}` };
    commitAction(action, nextItems);
    return { label: action.label, version: String(readVersion()), item: null };
  }

  return { approveItem, rejectItem, unrejectItem, editItem, deleteItem };
}
