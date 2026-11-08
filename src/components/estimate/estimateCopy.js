/* ============================================================
   estimateCopy.js — every word the ROM estimate screen says.

   One register for the whole document, the way scheduleCopy.js and
   noteVocabulary.js hold theirs. Sentence case. No model names, no
   confidence, no processing internals.

   The two origin words are the spine of this screen and are
   deliberately NOT the four review labels. Those describe an item's
   evidence and decide whether it may be approved; these describe where
   a number came from on a document that has no approval step at all.
   Rendering one with the other's component or colour is how the four
   labels quietly become five — the same separation noteVocabulary.js
   exists to hold for a note's status.
   ============================================================ */

export const ORIGIN = {
  counted: { label: "Counted", title: "Read from the documents" },
  assumed: { label: "Assumed", title: "Derived, with the basis stated" },
};

export const COPY = {
  kicker: "Rough order of magnitude · Division 26",
  rangeLabel: "Budget range",
  loading: "Loading the estimate…",
  loadError: "The estimate could not be loaded. Reload the page to try again.",

  // The footer. This is the sentence that keeps the document from being
  // read as a bid, and it is the reason approvals are absent rather
  // than missing.
  footer:
    "Rough order of magnitude for budgeting. Lines marked Assumed were not read from the drawings and are " +
    "stated above with the basis used. Not a bid. Supersede with a hard number once the assumptions below " +
    "are confirmed or priced.",

  qualificationsTitle: "Qualifications — what this number assumes",
  qualificationsLead: "Generated from every assumed line above. This list is the condition of the price.",

  notPriced: "Not priced",
  notPricedTitle: "Nothing priced this line. It carries no cost in the total above.",
  excludedLabel: "removed from the total",
  subtotalLabel: "Subtotal",

  download: "Download estimate",

  /* The override. "Enter" rather than "Confirm" throughout: this
     corrects a number, it is not an approval, and a ROM has no
     approval step to borrow words from. */
  overrideOpen: "I know this one",
  overrideLabel: "Enter the value",
  overrideSave: "Enter",
  overrideSaving: "Saving…",
  overrideCancel: "Cancel",
  overrideError: "That value could not be saved. Check it and try again.",
};

export function sectionTally(section) {
  const counted = `${section.countedCount} read from documents`;
  const assumed = `${section.assumedCount} assumed`;
  return { counted, assumed };
}

export function dollars(value) {
  if (value == null) return null;
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/* The headline sentence under the number. Reads as one sentence an
   estimator can say out loud, which is the test the budget range was
   designed against (api/app/estimate/range.py). */
export function rangeNote(estimate) {
  const { assumedCount, countedCount } = estimate;
  if (!assumedCount) {
    return `Every line was read from the documents. ${countedCount} counted ${
      countedCount === 1 ? "line" : "lines"
    }.`;
  }
  return `${assumedCount} ${assumedCount === 1 ? "line is" : "lines are"} assumed; every one is listed below.`;
}
