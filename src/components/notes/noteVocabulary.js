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
 *  colour on its own — the label carries the meaning in words.
 *
 *  `usage` is checked FIRST, unconditionally: a company-scoped note only
 *  reads "Company standard" once it is actually marked to feed the
 *  takeoff. Fix round 1 caught the bug this guards against -- checking
 *  `scope === "company"` before `usage` meant a company-scoped note
 *  saved with "Feeds the takeoff" left unchecked still showed "Company
 *  standard" (which reads as "this is in force") while
 *  `unappliedContextNotes` (below, keyed on `usage` alone) correctly
 *  ignored it. Two different answers to "does this affect the
 *  estimate?" on the one screen whose job is to say what moves the
 *  number. Ordering `usage` first makes `tone !== "reference"` and
 *  `usage === "context"` the same set of notes, by construction, so the
 *  header count and the apply banner can never disagree again. */
export function calculationEffect(note) {
  if (note.usage !== "context") return { label: "Reference only", tone: "reference" };
  if (note.scope === "company") return { label: "Company standard", tone: "standard" };
  return { label: "Used in this estimate", tone: "used" };
}

/** Notes marked as context that no re-run has carried into the takeoff
 *  yet. The apply banner exists for exactly this set. */
export function unappliedContextNotes(notes) {
  return notes.filter((n) => n.usage === "context" && !n.appliedAt);
}
