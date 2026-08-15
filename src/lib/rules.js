/* ============================================================
   rules.js — approval, totals, and scale-release rules.

   Mirrors api/app/takeoff/review.py (_apply_approve's refusal order),
   api/app/takeoff/scale.py (which warnings a scale confirmation is
   allowed to clear), and api/app/takeoff/totals.py (_countable) on the
   Python side. It does not share code with them — the two languages
   cannot share a module, and the server stays authoritative regardless
   (ROADMAP.md invariant 4: "Approval rules are server-authoritative").

   What this file prevents is the same rule being written twice
   *within* the client: src/lib/store/seed.js enforces these rules
   because there is no server behind it to enforce them for real, and
   (Task 16) App.jsx checks them for immediate feedback with the
   evidence on screen, per DESIGN.md's "Approving an item with Missing
   information status is blocked at the item level."
   ============================================================ */

// The closed vocabulary Warning.reason serializes as (schemas.py
// WarningOut.reason). A domain fact, not a processing internal — see
// schemas.py's own comment on why this crosses the API boundary at all.
export const WARNING_REASONS = {
  SCALE: "scale",
  LEGEND: "legend",
  SCHEDULE_CONFLICT: "schedule_conflict",
};

export const BLOCKED_BY_MISSING_INFORMATION = {
  code: "missing_information_blocks_approval",
  message:
    "This item is missing information it needs, such as a scale or a legend entry. " +
    "Resolve the warning on its sheet before approving it.",
};

export const BLOCKED_BY_REJECTION = {
  code: "rejected_item_cannot_be_approved",
  message: "This item was rejected, so it cannot be approved as-is. Restore it, then approve it.",
};

/** Returns null when the item may be approved, or the refusal describing why not.
 *
 *  Checks Missing information before rejection, in that order — the same
 *  order review.py's _apply_approve() checks item.status before
 *  item.rejected_at, so an item that is somehow both gets the more
 *  specific, more actionable reason first. */
export function refusalToApprove(item) {
  if (item.status === "missing") return BLOCKED_BY_MISSING_INFORMATION;
  if (item.rejected) return BLOCKED_BY_REJECTION;
  return null;
}

/** Bulk approval accepts Ready to review only — never Needs attention,
 *  Missing information, or a rejected item, no matter how convenient it
 *  looks (CLAUDE.md, "Rules that are easy to break by accident"). */
export function approvableInBulk(items) {
  return items.filter((i) => i.status === "ready" && !i.rejected);
}

/** Superseded sheets and rejected items never contribute to a total —
 *  mirrors totals.py's _countable(), which excludes both inside the
 *  query rather than trusting callers to filter (invariant 2 and the
 *  rejected-item half of invariant 1). */
export function countsTowardTotals(item, sheetsById) {
  return !item.rejected && !sheetsById[item.sheetId]?.superseded;
}

/** An item's warnings whose reason is "scale" — the set scale.py's
 *  set_scale() deletes when the sheet's scale is confirmed. */
export function scaleWarnings(item) {
  return (item.warnings || []).filter((w) => w.reason === WARNING_REASONS.SCALE);
}

/** An item's warnings whose reason is not "scale" — these survive a
 *  scale confirmation untouched. If any remain after the scale warnings
 *  are cleared, the item stays Missing information: confirming a scale
 *  must never delete the warning that explains why a symbol was never
 *  countable (scale.py's module docstring, "the mixed scale-and-legend
 *  case"). */
export function nonScaleWarnings(item) {
  return (item.warnings || []).filter((w) => w.reason !== WARNING_REASONS.SCALE);
}

/** Whether a scale confirmation would fully release this item to Ready
 *  to review — true only for a Missing information item, not already
 *  rejected, that carries a scale warning and has no other warning left
 *  once the scale warnings are cleared. Mirrors scale.py's set_scale()
 *  candidate filter (status MISSING, not rejected, has a scale-reason
 *  warning) plus its "only fully release once nothing else is still
 *  blocking it" check. */
export function isScaleReleasable(item) {
  return item.status === "missing" && !item.rejected && scaleWarnings(item).length > 0;
}
