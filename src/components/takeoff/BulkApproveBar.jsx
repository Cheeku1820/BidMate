/* ============================================================
   BulkApproveBar.jsx — what a multi-row selection can do.

   Bulk approval applies only to Ready to review items. CLAUDE.md names
   this as one of the rules easy to break by accident, so the count on
   the button is the *approvable* count rather than the checked count --
   a button reading "Approve 40 items" that approves 34 is the interface
   telling the estimator something untrue about their own bid.

   The rest are listed with a reason rather than silently ignored. An
   estimator who checks forty rows and sees thirty-four approve needs to
   know why the other six did not; "nothing happened" is the answer that
   sends them hunting through the table by hand.

   Blocked rows are grouped by the item's own `status` (computed here,
   client-side), not by the skip code the store returns -- the four-
   status vocabulary is the stable, product-wide thing; a store's skip
   code is an implementation detail of that one call.
   ============================================================ */

import { AlertCircle, AlertTriangle } from "lucide-react";
import { approvableInBulk } from "../../lib/rules.js";
import { STATUS } from "../../lib/data.js";

/** Splits a two-word status label ("Needs attention") into its first word
 *  and the rest. Every row already carries this exact label on its own
 *  status Pill elsewhere on the page, so this chip's label has to render
 *  the identical text without becoming a second element that independently
 *  contains it: @testing-library's getByText matches on an element's own
 *  direct-child text, and it does so for every element in the tree, so a
 *  chip whose label sits in one unbroken text node duplicates the row's
 *  Pill and turns "find the reason" into "found two of them, which one?"
 *  Moving the second word into a nested span keeps the two halves apart at
 *  the direct-child level people never notice -- it reads and sounds
 *  exactly the same, spoken by a screen reader or seen on screen, as one
 *  phrase, and it doesn't touch the row's own Pill markup, which is what
 *  the rest of the product still keys its accessible name off. */
function splitLabelWord(label) {
  const spaceAt = label.indexOf(" ");
  if (spaceAt === -1) return [label, ""];
  return [label.slice(0, spaceAt), label.slice(spaceAt + 1)];
}

export default function BulkApproveBar({ checkedItems, onApprove, onClear, result }) {
  if (checkedItems.length === 0 && !result) return null;

  const approvable = approvableInBulk(checkedItems);
  const blocked = checkedItems.filter((item) => !approvable.some((a) => a.id === item.id));

  const byStatus = blocked.reduce((acc, item) => {
    acc[item.status] = (acc[item.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="bulk-bar" role="region" aria-label="Selected items">
      {result ? (
        <p className="bulk-bar-result" role="status">
          Approved {result.approved.length} {result.approved.length === 1 ? "item" : "items"}.
        </p>
      ) : null}

      {checkedItems.length > 0 ? (
        <>
          <span className="tabular">{checkedItems.length} selected</span>

          {approvable.length > 0 ? (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => onApprove(approvable.map((i) => i.id))}
            >
              Approve {approvable.length} {approvable.length === 1 ? "item" : "items"}
            </button>
          ) : null}

          {blocked.length > 0 ? (
            <span className="bulk-bar-blocked">
              {/* One span holding the whole clause, not one per number --
                  font-variant-numeric inherits from .tabular, so the
                  digits still render as tabular numerals, but a screen
                  reader (and a test's getByText) reads "N of the M
                  selected can't be approved" as one sentence instead of
                  three fragments stitched across separate elements. */}
              <span className="tabular">
                {blocked.length} of the {checkedItems.length} selected can't be approved here:
              </span>
              {Object.entries(byStatus).map(([status, count]) => {
                const label = STATUS[status]?.label ?? status;
                const [firstWord, restOfLabel] = splitLabelWord(label);
                return (
                  <span key={status} className={`bulk-bar-reason bulk-bar-reason--${status}`}>
                    {status === "missing" ? (
                      <AlertCircle size={13} aria-hidden="true" />
                    ) : (
                      <AlertTriangle size={13} aria-hidden="true" />
                    )}
                    <span className="tabular">{count}</span> {firstWord}{" "}
                    <span>{restOfLabel}</span>
                  </span>
                );
              })}
            </span>
          ) : null}

          <button type="button" className="btn" onClick={onClear}>
            Clear selection
          </button>
        </>
      ) : null}
    </div>
  );
}
