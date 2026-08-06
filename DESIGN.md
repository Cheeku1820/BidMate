# Interaction notes

Annotated behavior for the blueprint review workspace. These are the rules a developer needs that a static mockup can't express.

---

## Autosave and save status

Every mutation writes immediately. There is no save button anywhere in the review workspace.

The top bar shows one of three states: `Saving…` during the write, `Saved 2:41 PM` after it lands, or `Couldn't save — retrying` on failure. The failure copy names a recovery path rather than saying something went wrong.

A toast confirms each action in the estimator's own words ("Approved 20A duplex receptacle") with an inline **Undo**, and dismisses after five seconds. The toast is a convenience; the authoritative undo lives in the top bar and never expires within the session.

---

## Undo semantics

Undo covers approve, reject, edit, delete, and scale confirmation. Each action stores a `before` and `after` snapshot of only the fields it touched, so replaying is a merge rather than a full-state restore — this is what lets two people's concurrent edits to different items coexist.

Scale confirmation is a **compound action**: it changes the sheet's scale *and* re-derives every measured item that was blocked by that scale. Undo reverses both together. An estimator who confirms a scale and immediately regrets it gets one undo, not fourteen.

The history stack is shared across reviewers and capped at 60 actions. The undo button's tooltip names the action about to be reversed, including who performed it, because reversing a colleague's decision should never be accidental.

**Open decision.** A shared linear stack is the simplest model and matches how a small estimating team actually works — but it means person B can undo person A's approval from underneath them. The alternatives are per-user stacks with a merge policy, or a CRDT. This needs a call before production.

---

## Blueprint and table synchronization

The blueprint and the takeoff table (screen G) are two views of one list. Selection is bidirectional and lives in shared state, not in either view.

Selecting a marker opens the item detail panel and, in the table view, scrolls to and highlights that row. Selecting a row centers the blueprint on that marker and selects it. Editing a quantity in either place updates both plus the bottom drawer totals plus the audit history, in the same action.

Remote selection is drawn as a dashed ring in the other reviewer's avatar color. It is deliberately a different treatment from local selection (solid ring plus fill) so the two never read as the same thing.

---

## Status and layer rules

A marker's hue comes from review status, its glyph from item type, and its badge from warning presence. These three channels stay independent — a warning never changes the glyph, and item type never changes the hue.

Layer toggles filter what's drawn but never change what's counted. Hiding approved items does not remove them from the drawer totals. This is deliberate: an estimator who hides a layer to reduce clutter must not accidentally change the number they're about to bid.

Measured items whose scale is unconfirmed are drawn as **dashed** polylines. Confirmed measurements are solid. The dash is a second, redundant channel for the same information the color already carries.

---

## Warning structure

Every warning carries four fields, enforced by the data shape:

```js
warning: {
  title: "Scale needs confirmation",
  found: "E2.1 shows two different scale labels…",   // what was found
  why:   "Measured conduit lengths may be wrong…",   // why it needs attention
  fix:   "Select the scale that applies…",           // what to check or change
  where: "E2.1 title block and enlarged plan note",  // which sheet holds the evidence
}
```

A warning missing a field is a schema error, not a copy oversight. Warnings never mention models, confidence scores, or processing internals — the estimator's question is always "what do I do about this," never "how did the software decide."

---

## Finish review blocking

Selecting **Finish review** opens a summary that sorts unresolved issues into two groups.

*Missing information* items **block** completion. The complete button is disabled, each blocking item is listed with its warning title and a direct **Go to item** link that closes the dialog and selects it on the drawing. There is no override, no "proceed anyway," no acknowledgment path. Missing evidence is not a judgment call.

*Needs attention* items may remain, but only behind an explicit acknowledgment checkbox whose label states the consequence: these become allowances in the exported takeoff. The checkbox resets if new attention items appear.

Approving an item with *Missing information* status is blocked at the item level too, with inline copy explaining why — so the estimator hits the rule while looking at the evidence, not later in a summary dialog.

---

## Revision handling

Each sheet carries a revision and a date; the active set is named in the top bar. A superseded sheet never contributes to totals.

The full revision-conflict flow (prototype path 4 in the spec) is **not yet built**. It needs decisions on: whether superseded sheets remain browsable read-only, whether previously approved items on a superseded sheet carry forward or reset, and how a mid-review revision swap surfaces to a second reviewer already working in the file. These are product decisions, not visual ones.

---

## Calibration

Two clicks on a known dimension. The tool captures the pixel distance, and the confirm step asks for the real-world length. The cursor changes to a crosshair and a banner states which click is expected next, because a modal two-step interaction with no state indicator is where people get lost.

Calibration and scale selection produce the same undoable action, so an estimator who calibrates then realizes the title block was right all along backs out cleanly.
