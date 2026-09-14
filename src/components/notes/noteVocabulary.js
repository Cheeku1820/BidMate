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
 *  yet. The apply banner exists for exactly this set: it answers "is
 *  there anything new to apply?", which is a question about what has
 *  *not* been applied.
 *
 *  This is deliberately NOT the set sent to the engine -- see
 *  `standingContextNotes` below for why the two must differ. */
export function unappliedContextNotes(notes) {
  return notes.filter((n) => n.usage === "context" && !n.appliedAt);
}

/** Every note marked as context, applied or not -- the full standing
 *  context this project is estimated under, and the set that goes to
 *  the engine on a re-run.
 *
 *  These two selectors answer two different questions and must not be
 *  collapsed into one. The engine is stateless: it classifies from the
 *  drawings plus the notes it is handed on that run, and it has no
 *  memory of a previous run's notes. The merge
 *  (`api/app/takeoff/reprocess.py`) then overwrites every matched
 *  un-approved item from whatever payload it is given.
 *
 *  So sending only the *unapplied* notes silently reverts every earlier
 *  note. Apply note A ("west wing fixtures are type F") and items
 *  reclassify; later add note B and apply, and a payload built from B
 *  alone carries no trace of A -- every item A had changed is
 *  overwritten back to the pre-A result, while the screen still reads
 *  "Used in this estimate" for A and nothing anywhere says it was
 *  undone. That is a wrong bid total produced by using the feature
 *  normally twice.
 *
 *  The applied stamp therefore records "this note has been carried into
 *  the takeoff at least once" -- it is banner state, not a filter on
 *  what the engine is allowed to see. Every standing context note is
 *  re-sent on every run. */
export function standingContextNotes(notes) {
  return notes.filter((n) => n.usage === "context");
}
