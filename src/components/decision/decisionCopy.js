/* The decision area's words (say-what-it-is spec). Kept out of the
   components so the copy has one home and the tests can quote it. */

export const REJECT_CHIP = "Not a device";
export const EXISTING_CHIP = "Existing to remain";
export const CUSTOM_LINE = "Read from your words as a custom item.";
export const UNKNOWN_COPY = "Couldn't read that — try naming the device (e.g. '20A duplex receptacle').";
export const EMPTY_HELPER = "Say what it is, or pick one above.";

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
  if (proposal.scheduleMatch || proposal.catalogId) parts.push("clears the warning");
  return parts.join(" · ");
}

export function timeShort(iso) {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
}
