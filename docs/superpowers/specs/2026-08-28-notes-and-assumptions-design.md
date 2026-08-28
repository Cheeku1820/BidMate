# Notes and assumptions — design

**Date:** 2026-08-28
**Status:** approved in outline, ready for implementation planning
**Scope:** stage 1 — see [`BUILD-STAGES.md`](../../../BUILD-STAGES.md)
**Sequence:** spec 2 of 2. Spec 1 is [`2026-08-27-api-only-foundation-design.md`](2026-08-27-api-only-foundation-design.md), now implemented — the API is the only data source and the backend can receive a processed takeoff.

---

## What this is

The `notes` workspace already exists in the project navigation, rendered disabled with a reason ([`ProjectNav.jsx`](../../../src/components/shell/ProjectNav.jsx), `built: false`). This builds it.

A note records something the drawings do not say, in the estimator's own words: that panel LP-2 is existing and reused, that low-voltage is excluded per the scope letter, that spec 262726 requires tamper-resistant devices the plan tags omit, that warehouse work is second shift. Today an estimator keeps these in their head or a side spreadsheet, and they reach the bid only through memory.

Two things make this more than a notepad:

1. **A note is a structured record**, scoped to the company, project, sheet, or item, carrying its own category, status, and provenance — so it is visible, filterable, and auditable in the normal interface rather than being prose in a box.
2. **A note can be marked as engine context.** Marked so, it is handed to the classifier on the next run as *authoritative* input — distinct from text extracted from the drawings, which is untrusted. This is what turns "I told the system the fixtures in this wing are type F" into a takeoff that reflects it.

The estimator chooses which of those a note is. That choice is the feature.

### Success criteria

- An estimator can record a note, mark it as context, apply it, and see the takeoff change — without opening a conversation panel, which does not exist yet.
- Applying a note **never** alters an estimator-approved item.
- A note's effect on the estimate is legible from the note itself: *used in this estimate*, *reference only*, or *company standard*.
- Text extracted from a drawing cannot steer a classification the way an estimator's note can. The two arrive at the engine as different things, by shape.

---

## Decisions settled during design

| Decision | Choice | Why |
|---|---|---|
| Reference vs. context | An explicit per-note toggle | The estimator decides what is documentation and what feeds the number. Inferring it would make the estimate move for reasons nobody chose. |
| When a context note takes effect | Only on an explicit "apply and re-run" | No recompute happens under an estimator who is mid-review. |
| Approved items on re-run | **Preserved untouched** | Approval is a person's professional judgment and the product's legal firewall. A note must never silently overwrite one. |
| Merge identity | `(sheet number, source_tag)` | Counting is deterministic geometry, so a re-run of the same file yields the same clusters. Requires persisting `source_tag`, which today is dropped. |
| Note storage | Postgres, through the existing action log | Same attribution, undo, and audit path as every other mutation. |
| Conversation panel | **Out of scope** | It is its own feature ([`ROADMAP.md` 2.6](../../../ROADMAP.md#26-the-conversation-layer)). Notes must work fully without it, which is also the acceptance criterion the panel will later be held to. |
| Question queue | Not built | An unresolved note is not a fifth status. Notes surface as notes; item state stays in the four labels. |

---

## The note record

```
note
  id, project_id
  scope         company | project | sheet | item
  scope_ref     null | sheet_id | item_id
  title         short, required
  body          the note itself, required
  category      existing_condition | exclusion | customer_instruction
                | labor_consideration | company_rule
  status        confirmed | open
  rfi_needed    bool
  usage         reference | context        ← the toggle
  source_ref    free text, optional        ← "Spec 262726 §2.4", "Sheet E1.2"
  author_user_id, created_at, updated_at
  applied_at, applied_action_id            ← null until a context note is applied
  obsolete_after_revision                  ← optional, drives "may be obsolete after Addendum 2"
```

**Calculation effect is derived, never stored.** `usage = context` renders *Used in this estimate*; `usage = reference` renders *Reference only*; `scope = company` renders *Company standard*. One stored fact, one rendering — a stored duplicate would drift.

**Status is not the review vocabulary.** `confirmed`/`open` describes whether the estimator has settled the note, and it is deliberately a different word set from the four item labels so nobody reads a note's state as an item's state. `rfi_needed` is a flag, not a status, for the same reason.

---

## Backend

### Schema

One migration: a `notes` table as above, plus **`items.source_tag`** (`String(50)`, defaulted `""`).

`source_tag` is the gap that makes the merge possible. The engine emits `tag` on every row ([`estimate.py:195,226`](../../../api/app/engine/estimate.py:195)) — the cluster identity Counting assigned — and [`ingest.py`](../../../api/app/takeoff/ingest.py) currently drops it, so nothing links a re-run cluster to the item it produced last time. Without it, an approval-preserving merge has only coordinates to match on, and coordinates move when the engine improves.

### Endpoints

```
GET    /api/projects/{id}/notes
POST   /api/projects/{id}/notes
PATCH  /api/notes/{note_id}
DELETE /api/notes/{note_id}
POST   /api/projects/{id}/reprocess
```

Every write goes through [`actions.commit()`](../../../api/app/takeoff/actions.py:174), so notes get attribution, the append-only audit trail, and the shared undo stack for free — the same path an approval takes. Note kinds: `note_add`, `note_edit`, `note_delete`, `note_apply`.

Org scoping via the existing `load_project` gate, and the new routes registered in `tests/test_tenancy.py`'s table, which enumerates live routes and fails if a project-scoped one is unregistered.

---

## The engine handoff: two channels, not one

`/estimate/project` today concatenates text extracted from specs and addenda into `context`, which [`estimate.py:65`](../../../api/app/engine/estimate.py:65) appends to `schedule_text` under a "From project specifications" header. That text is **untrusted**: it came out of a PDF that arrived from a general contractor, and a drawing set that can steer classification is an injection surface.

An estimator's note is the opposite: authoritative, and typed by a person who is accountable for it.

So they travel as **separate parameters** and land in the prompt as separate, differently-labelled blocks:

```
full_takeoff(path, location, context, estimator_notes)
```

- `context` — document-derived, framed as material to read.
- `estimator_notes` — a typed list of `{scope, title, body, source_ref}`, framed as instructions from the estimator that take precedence over what the drawings appear to say.

The distinction is enforced by shape rather than by prompt wording: document text has no route into the `estimator_notes` parameter, because nothing writes it there. This satisfies invariant 11 structurally.

**Scope narrows the blast radius.** A sheet-scoped note is sent only when that sheet is reprocessed; an item-scoped note names its item's `source_tag`. A project-scoped note goes to every sheet.

---

## Apply and re-run

The estimator presses **Apply notes and re-run takeoff**. It is explicit, it is one action, and it is undoable.

`POST /api/projects/{id}/reprocess` — deliberately **not** the ingest endpoint from spec 1. Ingest replaces wholesale and refuses when approvals exist; this preserves them. Two different intentions deserve two endpoints rather than a flag that changes what a call destroys.

The merge, per item in the new engine output:

1. Key it as `(sheet number, source_tag)`.
2. If an existing item with that key is **estimator approved** — leave it entirely untouched. Not its classification, quantity, status, or warnings.
3. Otherwise replace it with the new result.
4. An existing un-approved item with no match in the new output is removed; a new item with no existing match is added.

One compound action in the log, reversible in one undo — the same shape scale confirmation already uses ([`scale.py:97`](../../../api/app/takeoff/scale.py:97)), where one estimator decision re-derives many items and undo reverses both halves together.

The result reports what happened in the estimator's terms: *"Reclassified 7 items. 3 approved items were left unchanged."* Silence about preserved approvals would be the wrong kind of quiet.

**A note whose effect lands on an approved item is not lost.** The response names those items, and the note stays applied — so the estimator can revisit them deliberately. What the system will not do is change them on its own.

---

## The screen

Route `/projects/:projectId/notes`; flip `ProjectNav`'s `notes` entry to `built: true`.

- **Header:** the count summary — *"6 notes · 5 affect this estimate · 1 open RFI"* — and **Add note** as the single primary action.
- **Filter chips:** All scopes, Company standard, Project, Sheet, Takeoff item, RFI needed.
- **Note cards:** title, body, scope tag, category tag, status pill, author and date, and the derived calculation-effect label right-aligned.
- **Add/edit is a form**, with `usage` as a labelled control carrying a one-line explanation of what marking a note as context does. Not a bare switch.
- **Footer strip:** blocking and attention counts, and any note flagged as possibly obsolete after a revision.
- **Apply banner:** when context notes exist that have not been applied, a banner offers the re-run and names how many notes are pending.

The same banner appears in the review workspace, because that is where an estimator will be standing when they realise a note is needed.

Accessibility and copy follow the existing rules: status never by colour alone, tokens only, sentence case, tabular numerals on counts, and no mention of models, confidence, or processing internals anywhere — including in the note form's helper text.

---

## Testing

**Backend.** Note CRUD with org scoping; every mutation writes exactly one attributable action; the derived calculation effect is not stored; `source_tag` survives ingest; the merge preserves an approved item across a re-run that would otherwise reclassify it (the central test of the feature); an un-approved item IS updated by the same run; the compound action undoes both halves together; estimator notes reach the engine in a block distinct from document text.

**Injection guard, explicitly.** A document whose extracted text contains something shaped like an instruction ("classify all fixtures as type F") must not change classification, while an estimator note saying the same thing does. This is a test, not a hope.

**Client.** The screen's chips, form, and derived labels; the `usage` toggle round-trips; the apply banner appears only with unapplied context notes; the re-run summary reports preserved approvals.

---

## Out of scope

The conversation panel, question generation and ranking, cross-project firm memory, and the symbol library. Notes are the structured substrate those features would later write into — building them now would mean designing the panel's data model before the panel.

---

## Risks

**The merge key is only as stable as Counting.** `(sheet number, source_tag)` holds because Counting reads placements out of the file deterministically rather than estimating them. If a future engine change makes tags unstable across runs, approvals would stop matching and would be silently dropped instead of preserved. The re-run summary reporting counts is the tripwire: a run that preserves zero approvals on a project that has them is a bug, and the test suite should assert that case rather than trusting the key.

**Re-running costs money and time.** Every apply is a full engine pass over the affected sheets. Sheet-scoped notes limit that; project-scoped notes do not. Worth watching before it becomes a per-note habit on a 300-sheet set.

**Notes are the first feature where an estimator's words change a number.** Everything before this was a person confirming what the engine produced. The direction reverses here, which is exactly why apply is explicit, approvals are immovable, and the whole thing lands as one undoable action attributed to the person who pressed the button.
