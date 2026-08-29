/* ============================================================
   noteVocabulary.js — the words the notes screen uses, in one place.

   Calculation effect is DERIVED here rather than stored on the record:
   one stored fact (`usage`, plus `scope` for a company standard), one
   rendering. A stored duplicate would drift from the thing it describes.

   These are deliberately not the four review labels. Those describe an
   item's evidence; these describe a note.
   ============================================================ */

export const SCOPE_LABELS = {
  company: "Company standard",
  project: "Project",
  sheet: "Sheet",
  item: "Takeoff item",
};

export const CATEGORY_LABELS = {
  existing_condition: "Existing condition",
  exclusion: "Exclusion",
  customer_instruction: "Customer instruction",
  labor_consideration: "Labor consideration",
  company_rule: "Company rule",
};

export const STATUS_LABELS = { confirmed: "Confirmed", open: "Open" };

/** What this note does to the number. `tone` drives the class, never a
 *  colour on its own — the label carries the meaning in words. */
export function calculationEffect(note) {
  if (note.scope === "company") return { label: "Company standard", tone: "standard" };
  if (note.usage === "context") return { label: "Used in this estimate", tone: "used" };
  return { label: "Reference only", tone: "reference" };
}

/** Notes marked as context that no re-run has carried into the takeoff
 *  yet. The apply banner exists for exactly this set. */
export function unappliedContextNotes(notes) {
  return notes.filter((n) => n.usage === "context" && !n.appliedAt);
}
