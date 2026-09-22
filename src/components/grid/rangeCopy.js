/* ============================================================
   rangeCopy.js — what a range operation says (docs/specs/
   spreadsheet-grid.md, "The toast, and the undo of a range
   operation"). One toast per operation, counting what landed; one
   banner line when some of it did not; one toast when it is reversed.
   ============================================================ */

const VERB = { paste: "Pasted", fill: "Filled", clear: "Cleared" };
const n = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

export function rangeToast(kind, cells, rows, { skipped = 0, skippedWhy } = {}) {
  let text = `${VERB[kind]} ${n(cells, "cell")} on ${n(rows, "row")}`;
  if (skipped > 0) text += ` — ${n(skipped, "row")} skipped, ${skippedWhy}`;
  return text;
}

export function rangeFailure(failed, total) {
  return `${failed} of ${n(total, "cell")} couldn't be saved. Try again.`;
}

export function reversedToast(cells) {
  return `Reversed ${n(cells, "cell")}`;
}
