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

import { refusalToApprove, refusalToStaleVersion, approvableInBulk } from "../rules.js";

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

export function createReviewMethods({ readItems, readHist, commitAction, identity, uid, readVersion, getSnapshot }) {
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

  /** Mirrors api/app/takeoff/bulk.py's bulk_approve(): approve every
   *  Ready to review item named, and report every other one with a
   *  reason rather than dropping it. The reasons matter -- an estimator
   *  who selects forty rows and sees thirty-four approve needs to know
   *  why the other six did not, and "nothing happened" is the answer
   *  that sends them hunting.
   *
   *  Uses approvableInBulk() from rules.js rather than re-deriving the
   *  predicate: CLAUDE.md names bulk approval as easy to break by
   *  accident, and a second copy of "only Ready to review" is exactly
   *  how it breaks.
   *
   *  A compound action, like setScale -- one hist entry covers every
   *  item that moved, so undoing a forty-row approval is one undo, not
   *  forty (DESIGN.md, "Undo semantics"). before/after.items are the
   *  same {id, ...fields} shape setScale already records, so seed-
   *  undo.js's applyItemPartials() reverses/reapplies this the same way
   *  it does a scale confirmation, with no new merge logic. */
  async function bulkApprove(itemIds) {
    const ids = Array.isArray(itemIds) ? itemIds : [];
    const items = readItems();
    const byId = Object.fromEntries(items.map((i) => [i.id, i]));

    const named = ids.map((id) => byId[id]).filter(Boolean);
    const approvableIds = new Set(approvableInBulk(named).map((i) => i.id));

    const skipped = [];
    for (const id of ids) {
      if (approvableIds.has(id)) continue;
      const item = byId[id];
      if (!item) {
        skipped.push({ itemId: id, code: "item_no_longer_exists", message: "This item was deleted by another reviewer. Refresh the sheet to see its current items." });
      } else if (item.rejected) {
        skipped.push({ itemId: id, code: "rejected_item_cannot_be_approved", message: "This item was rejected, so it cannot be approved as-is. Restore it, then approve it." });
      } else if (item.status === "approved") {
        skipped.push({ itemId: id, code: "already_approved", message: "This item is already approved." });
      } else if (item.status === "missing") {
        skipped.push({ itemId: id, code: "missing_information_blocks_approval", message: "This item is missing information it needs, such as a scale or a legend entry. Resolve the warning on its sheet before approving it." });
      } else if (item.status === "attention") {
        skipped.push({ itemId: id, code: "needs_attention", message: "This item needs attention -- review it individually before approving." });
      } else {
        skipped.push({ itemId: id, code: "not_ready", message: "This item is not ready to review." });
      }
    }

    const approved = [...approvableIds];
    if (approved.length === 0) {
      return { approved: [], skipped, snapshot: await getSnapshot() };
    }

    const actor = identity();
    const itemsBefore = approved.map((id) => ({ id, status: byId[id].status, approvedBy: byId[id].approvedBy ?? null }));
    const itemsAfter = approved.map((id) => ({ id, status: "approved", approvedBy: actor.name }));

    const nextItems = items.map((i) =>
      approvableIds.has(i.id) ? { ...i, status: "approved", approvedBy: actor.name, version: i.version + 1 } : i
    );

    const label = `Approved ${approved.length} ${approved.length === 1 ? "item" : "items"}`;
    const action = {
      id: uid("a"), kind: "bulk-approve",
      before: { items: itemsBefore },
      after: { items: itemsAfter },
      by: actor.name, at: Date.now(), label,
    };
    commitAction(action, nextItems);

    return { approved, skipped, snapshot: await getSnapshot() };
  }

  return { approveItem, rejectItem, unrejectItem, editItem, deleteItem, bulkApprove };
}
