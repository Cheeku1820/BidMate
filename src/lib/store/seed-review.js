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
   uid, readVersion) — rather than closing over module-level state, so
   this module has no storage of its own and cannot drift from what
   seed.js actually persists.
   ============================================================ */

import { refusalToApprove } from "../rules.js";

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

export function createReviewMethods({ readItems, commitAction, identity, uid, readVersion }) {
  function findItemOrThrow(id) {
    const items = readItems();
    const item = items.find((i) => i.id === id);
    if (!item) throw ITEM_NO_LONGER_EXISTS;
    return { items, item };
  }

  function mutationResult(action, nextItems, id) {
    commitAction(action, nextItems);
    return { label: action.label, version: String(readVersion()), item: nextItems.find((i) => i.id === id) };
  }

  async function approveItem(id) {
    const { items, item } = findItemOrThrow(id);
    const refusal = refusalToApprove(item);
    if (refusal) throw refusal;

    const actor = identity();
    const before = { status: item.status, approvedBy: item.approvedBy };
    const after = { status: "approved", approvedBy: actor.name };
    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after } : i));
    const action = { id: uid("a"), kind: "approve", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Approved ${item.name}` };
    return mutationResult(action, nextItems, id);
  }

  async function rejectItem(id) {
    const { items, item } = findItemOrThrow(id);
    // Rejection is tracked separately from review status (review.py's
    // _apply_reject() never touches item.status) so unrejecting can
    // restore the item exactly as it was, without having to guess what
    // status it used to carry.
    const actor = identity();
    const before = { rejected: item.rejected };
    const after = { rejected: true };
    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after } : i));
    const action = { id: uid("a"), kind: "reject", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Rejected ${item.name}` };
    return mutationResult(action, nextItems, id);
  }

  async function unrejectItem(id) {
    const { items, item } = findItemOrThrow(id);
    const actor = identity();
    const before = { rejected: item.rejected };
    const after = { rejected: false };
    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after } : i));
    const action = { id: uid("a"), kind: "unreject", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Restored ${item.name}` };
    return mutationResult(action, nextItems, id);
  }

  async function editItem(id, changes) {
    const { items, item } = findItemOrThrow(id);
    validateEdit(changes);

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

    const nextItems = items.map((i) => (i.id === id ? { ...i, ...after } : i));
    const action = { id: uid("a"), kind: "edit", itemId: id, before, after, by: actor.name, at: Date.now(), label: `Edited ${item.name}` };
    return mutationResult(action, nextItems, id);
  }

  async function deleteItem(id) {
    const { items, item } = findItemOrThrow(id);
    const index = items.findIndex((i) => i.id === id);
    const actor = identity();
    const nextItems = items.filter((i) => i.id !== id);
    const action = { id: uid("a"), kind: "delete", itemId: id, index, snapshot: item, by: actor.name, at: Date.now(), label: `Deleted ${item.name}` };
    commitAction(action, nextItems);
    return { label: action.label, version: String(readVersion()), item: null };
  }

  return { approveItem, rejectItem, unrejectItem, editItem, deleteItem };
}
