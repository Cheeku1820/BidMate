/* The decision area's words (say-what-it-is spec). Kept out of the
   components so the copy has one home and the tests can quote it. */

export const REJECT_CHIP = "Not a device";
export const EXISTING_CHIP = "Existing to remain";
export const CUSTOM_LINE = "Read from your words as a custom item.";
export const UNKNOWN_COPY = "Couldn't read that — try naming the device (e.g. '20A duplex receptacle').";
export const EMPTY_HELPER = "Say what it is, or pick one above.";
export const RESOLVE_ERROR = "Couldn't read that right now — try again.";

/** An item with no usable name — the "Symbol not in legend" case. The
    engine writes these rows as category "Unclassified", named
    "Unclassified symbol (TAG)", with a warning whose reason is `legend`
    (engine/classification.py); a person may also leave the name blank.
    The box takes focus by itself only on such an item — on every other
    item the single-key shortcuts (J/K/A/E/R, zoom) keep working and E
    puts the cursor in the box. */
export function isUnclassified(item) {
  if ((item.warnings || []).some((w) => w.reason === "legend")) return true;
  const name = String(item.name || "").trim();
  return !name || item.category === "Unclassified" || /^unclassified symbol/i.test(name);
}

/** Whether applying `proposal` clears a warning the item carries: a
    legend warning on any reading (the estimator has just said what the
    symbol is), a schedule-conflict warning only once the reading is
    matched to the schedule or the catalog. A scale warning is the
    sheet's, never cleared here. Mirrors resolve_apply's rule. */
export function clearsWarning(item, proposal) {
  const matched = Boolean(proposal.scheduleMatch || proposal.catalogId);
  return (item.warnings || []).some((w) => w.reason === "legend" || (matched && w.reason === "schedule_conflict"));
}

/** The count the primary button names: the corrected one, else the item's. */
export function approveCount(item, proposal) {
  return proposal.quantity != null ? proposal.quantity : item.quantity;
}

/** "Applies to all 30 · renames "Luminaire type F" · count 30 → 28 · clears the warning"
    The applies-to count is the item's count as it stands today; a stated
    correction shows up separately as "count 30 → 28" so the estimator sees
    both the scope of the change and what it corrects. A measured item's
    own length/count is edited below the box, not restated here. */
export function changesLine(item, proposal) {
  const n = item.quantity;
  const parts = [n > 1 ? `Applies to all ${n}` : "Applies to this item"];
  if (proposal.name !== item.name) parts.push(`renames "${item.name}"`);
  if (!item.path && proposal.quantity != null && Number(proposal.quantity) !== Number(item.quantity)) {
    parts.push(`count ${item.quantity} → ${proposal.quantity}`);
  }
  if (clearsWarning(item, proposal)) parts.push("clears the warning");
  return parts.join(" · ");
}

export function timeShort(iso) {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
}
