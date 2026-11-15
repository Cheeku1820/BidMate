# Estimate without asking: a number that completes itself

**Date:** 2026-11-15
**Status:** Design, approved approach. Builds on
[`docs/specs/rom-estimate.md`](rom-estimate.md); read that first — this
document extends its machinery rather than replacing it.

---

## Why

Drop a bid set into a chat and it comes back with a full estimate:
material breakdown, costs, labor hours. It knows nothing about the
project, so it assumes everything, and the answer is complete in one
pass.

This product knows a great deal about the project and returns *less*.
Two separate causes, and they were being treated as one problem:

**1. It only discloses what it counted.** Every assumption the ROM
writes is derived from items that already exist:

```python
# api/app/estimate/generate_takeoff.py:86
items = [i for i in db.scalars(countable_items(project.id)) ...]
if not items:
    return []
```

So the ROM assumes *about* what was found — this run used the firm's
feet-per-device rule, that sheet had no confirmed scale, these names
were inferred. It has no mechanism to assume the *existence* of
something never found. A sheet the engine read poorly contributes zero
dollars and zero disclosures. A job with no detected fire alarm devices
produces no fire alarm line at all. Handed less information, the product
returns a **smaller** number rather than a wider one.

That is the exact failure `BUILD-STAGES.md` names as the worst outcome
the product can produce: *"Silence reads as completeness."* The ROM was
built to prevent confidently-wrong numbers and currently permits
confidently-incomplete ones, which cost an estimator the same bid.

**2. It asks for confirmation it does not act on.** The Project plan
screen renders ~30 lines, each with Confirm and Dismiss. None of them
gate anything:

```js
// src/components/plan/PlanWorkspace.jsx:90
const canStart = state === "loaded" && plan.hasDrawings && !plan.reading && !starting;
```

Screen D has a Confirm button and, per its own known limitation, nothing
on it can be corrected. These are **implied obligations wearing the
visual language of required steps** — a door with no lock. The real
gate, per-item approval, sits further in and blocks only Export.

## The shift in one line

**Nothing comes back blank, and nothing waits for a press that changes
nothing.** Every quantity resolves through a ladder of methods and
records which rung it landed on; every confirmation that enforces
nothing is removed or demoted to a correction affordance.

## Goals

1. **A complete estimate exists minutes after upload**, with no press
   between the last byte of the upload and a number on screen.
2. **Nothing is silently absent.** Where counting failed, a lower rung
   of the ladder produces a number, and the line says which rung.
3. **Every line is checkable without being checked.** The spreadsheet
   row carries its reason, its confidence, and a link to the drawing and
   symbol it came from.
4. **The review queue is ranked by consequence**, sortable by money,
   labor hours, or confidence, each direction.
5. **Export remains the one blocking gate.** Unchanged.

## Non-goals

- Changing what approval means. Approval still marks an item checked by
  a person and still gates Export. (This was Option 2 in the
  conversation; rejected as surgery on the spine.)
- A second estimate produced before counting runs. (Option 3; deferred —
  see *Where this goes next*.)
- Markup, overhead, profit, or tax. ROADMAP invariant 13 stands.
- Removing the four review labels, renaming them, or adding a fifth.
- Auto-approval. No code path writes *Estimator approved* without a
  person.

## Anti-goals

Things that would make this a failure even if it shipped working:

- **An assumed number that does not say it is assumed.** The whole
  licence to assume comes from disclosure. A completion line without a
  basis and a four-field warning is the bare confidently-wrong number
  this product exists to prevent.
- **A confidence figure an estimator can multiply by the total.** The
  score names what to check. It is not a probability the bid is right,
  and the copy around it must not let it read as one.
- **A completion line that cannot be told from a counted one.** The
  `counted`/`assumed` axis must stay legible at a glance, in grayscale.
- **Guessing in place of reading.** If a schedule states the quantity,
  taking a class average instead is a regression, not a convenience.
  The ladder is ordered for a reason.
- **Un-gating by deleting the control.** A ceremonial Confirm becomes a
  *correction* affordance, not nothing. An estimator who wants to fix a
  scope line must still be able to.

## Constraints

- **Confidence is banned in four places today** — `CLAUDE.md`
  ("Confidence never renders"), `ROADMAP.md` invariant 7, and
  `product-spec.md` §3 and §12. The estimator has decided to render it
  as one of three sort keys; `CLAUDE.md` and invariant 7 must be amended
  in the same change, deliberately, with the reasoning recorded. The
  spec's wording ("*unexplained* confidence percentages") already
  permits an explained one.
- **No confidence is stored.** `rows.py:186` consumes it to choose a
  status and discards it. Items already in the database have no
  confidence to recover and never will; the column is null for them
  until a re-run.
- **`classification_basis` already exists** on `Item` (`String(30)`,
  nullable) and already carries `"inferred"`. The per-line reason is a
  display change, not a schema one.
- **`total_cost`, `labor_hours`, and `evidence` all already exist** on
  `Item`. Three of the four sort keys are free.
- **Money comes from `totals.resolved_lines()`, never `Item`'s stored
  cost columns.** A resolved supplier quote is never written back. The
  sort must use resolved values or it will sort a $5,000 run by its
  stale $1,000.
- **Approval-preserving merge.** `takeoff/merge.py` is the one write
  path for engine output. Completion lines are engine output and must
  merge through it — a re-run must not duplicate or resurrect them, and
  must never overwrite an approved item.
- **Agents hand off typed records** (invariant 12). A completion pass
  reads stored rows, not another agent's prose.

## Approaches

Three were considered, with the estimator choosing (1).

**1. Lead with the estimate; review grades it. — CHOSEN.**
The unfiltered total (`rom_totals()`, no status filter) already exists
beside the approved one. Promote the Estimate summary to the landing
screen, extend the ROM's generators with a completion pass, surface
reason/confidence/evidence as spreadsheet columns with the three-way
sort, and un-gate the presses that enforce nothing. Approval keeps its
current meaning and its single gate on Export.
*Trade-off:* two totals become visible in the product — "everything
found and assumed" and "what a person has checked." Both exist today;
promoting the ROM makes the pair legible and they need unambiguous
labels.
*Chosen because* the machinery was built for exactly this and has been
through review twice, and it delivers the goals without touching the
four labels, which is where the risk concentrates.

**2. Make approval a grade rather than a gate.**
Rework the status vocabulary so every item is in the number and status
only records whether a human looked. The most faithful version of what
was described.
*Rejected:* the labels are referenced across both frontend and backend
and a large share of the test suite asserts current approval semantics.
High chance of breaking things in unrelated places.

**3. Produce a number before counting anything.**
A job firing the moment files are read, estimating the whole job from
building type and sheet count alone, with the real takeoff progressively
replacing guesses.
*Deferred, not rejected:* closest to the chat experience, but it creates
two estimates that can disagree, and explaining a total sliding from
$480k to $390k as counting lands is a design problem of its own. Once
the ladder below exists, this is its degenerate case (zero items found
→ pure class average), so it becomes an addition rather than a build.

## Decisions already made

Settled in the design conversation. Do not reopen them while building.

1. **A guessed quantity becomes a real takeoff line, not a disclosure
   beside the total.** Only items add money — `rom_totals()` sums
   `countable_items()`, and assumptions are display rows that can
   subtract and never add (`CLAUDE.md`: "Scope is the only assumption
   that changes a number, and it only ever subtracts"). Writing
   completion as assumptions would have produced an honest sentence next
   to a total that still counted an unreadable sheet as $0. Completion
   therefore writes `Item` rows, priced by the path every other item
   uses, and invariant 1 holds with no rule bent.
2. **The building type is inferred from the drawings *and* asked.** It
   is itself a laddered value: inferred where the documents imply it,
   disclosed as inferred, and surfaced as a non-blocking question the
   estimator can correct. It never gates processing — that would
   reintroduce exactly the turnstile this work removes.
3. **Confidence renders**, as one of three sort keys, and `CLAUDE.md`
   plus ROADMAP invariant 7 are amended in the same change with the
   reasoning recorded. The estimator's call, made against the stated
   objection.
4. **Export stays the only blocking gate.** Reaffirmed explicitly.

5. **A guessed line reads "Guessed", not *Needs attention*.** It is not
   a fifth label: `origin` is the second axis `CLAUDE.md` already
   establishes for counted/assumed, and the row leads with it. The
   underlying review status is `ready` — nothing blocks, a person has
   not looked. *Needs attention* was the first proposal and was rejected
   for a good reason: attention items demand an acknowledgment at
   Export, which is exactly the nagging this work removes. The
   confidence meter, not a warning label, is what tells an estimator
   whether to check.
6. **Every guessed line points at specific evidence.** `Item.sheet_id`
   is NOT NULL, so there is no such thing as a line without a sheet, and
   the requirement falls out of the schema. Three kinds, strongest
   first: a **document page** that names work never counted (a spec
   section, a schedule — a real quote on a real page), a **sheet that
   came back empty**, or the **building type alone**, which is the
   weakest and must say so on the line.
7. **Confidence is a 1–10 meter, rendered as a bar.** See
   *The confidence scale* below. The digit carries in the tooltip and
   the accessible label, because a bar alone is shape-only and
   `CLAUDE.md` requires a text alternative for every status channel.

### Consequences of (1), for the builder

- **A new column, not `source_tag`.** `source_tag` carries the
  drawing's own symbol tag and drives cluster identity and symbol
  resolution (`takeoff/resolve_apply.py:103`, `:200`). Writing a
  synthetic tag there would fabricate a cluster and corrupt
  "find every one like this." Add `Item.origin` with the same two values
  `Assumption.origin` already uses — `counted` / `assumed` — so one
  vocabulary covers both records.
- **Completion items have no location.** `x`/`y` stay null and there is
  no evidence crop, because nothing was read. `BlueprintCanvas.jsx`
  filters markers only on `path` (`:254`, `:308`) with no coordinate
  guard, so it must gain an explicit filter or these render at an
  undefined position. The row shows *why the work is believed to be
  there* in place of an evidence link.
- **They default to *Needs attention*.** A guessed quantity is uncertain
  information requiring a decision, which is that label's definition. It
  surfaces in the queue, blocks nothing on its own, and reaches Export
  only through the existing acknowledgment path.
- **They must merge idempotently.** Completion is engine output and goes
  through `takeoff/merge.py`. A re-run must neither duplicate a
  completion line nor resurrect one the estimator deleted, so it needs a
  stable identity in the shape of `estimate/write.py`'s `_identity`.
- **Pricing is automatic.** `price_job` prices every countable item, so
  completion lines acquire material cost and labor hours with no new
  wiring.

## The ladder

The organising idea, and the estimator's own framing: *wherever you
can't count, you can read, or scale, or guess.* Never nothing.

Resolve by the most reliable method available and record the rung. There
are **two ladders**, not one — how many there are, and what each costs —
and conflating them is the error to avoid. Both draw their rungs from
`basis.py`'s existing classes, which already carry the spread that
widens the budget range.

**How many there are** (what slice 2 adds to):

| Rung | Basis key | Spread | Means |
|---|---|---|---|
| 1 | *(counted)* | — | Counted off the drawing; `origin = counted` |
| 2 | *(schedule)* | — | Read off a schedule — **not built, slice 4** |
| 3 | `scaled` | 0.20 | Measured off a drawing |
| 4 | `rule_of_thumb` | 0.25 | A per-device rule |
| 5 | `class_average` | 0.20 | Typical for this kind of job |
| 6 | `inferred` | 0.25 | Existence inferred from context |

**What each costs** (already built, listed so the two are not confused):

| Rung | Basis key | Spread |
|---|---|---|
| 1 | `supplier_quote` | 0 |
| 2 | `firm_default` | 0.10 |
| 3 | `market_estimate` | 0.15 |
| 4 | `class_average` | 0.20 |

A completion line therefore carries two bases: one for why we think the
work exists, one for what we think it costs. The qualifications block
already groups by basis, so both appear without new machinery.

Reading a quantity off a schedule is the highest-value missing quantity
rung and **does not exist yet**: schedules are stored as
`Sheet.schedule_text` (raw text) plus `Sheet.legend` (parsed rows), so
pulling a quantity out requires a parse. It is scoped as slice 4 rather
than assumed free.

`class_average` is today wired only into *cost* (`generate_cost.py:53`,
regional baseline) and never into *quantity*. Wiring it into quantity is
the core of slice 2.

## The confidence scale

A number from 1 to 10 saying how much an estimator should trust one
line. Its defining property: **it is a sum of named reasons, never an
opaque score.** Asked "why is this a 4", the product has a sentence.
That is also what keeps it on the right side of the spec's ban on
*unexplained* confidence percentages.

**Where it lives.** One module — `api/app/takeoff/confidence.py` — pure
functions over a single table, no database access, in the shape of
`estimate/basis.py` and `schedule/stages.py`. The starting numbers are
expected to move once a real estimator uses them, so they are one
editable table with the reasoning beside each row, never constants
scattered through the engine. Shaped so it could later become a
firm-editable table like `schedule/defaults.py` without restructuring;
not firm-editable in this slice.

**Starting score, by how the quantity was obtained:**

| How the number was obtained | Start |
|---|---|
| Counted off the drawing, matched to the legend or a schedule | 9 |
| Counted off the drawing, classified with high confidence | 8 |
| Read off a schedule (slice 4) | 8 |
| Measured against a confirmed scale | 7 |
| Counted, classified with medium or low confidence | 6 |
| Counted but never identified — quantity solid, cost assumed | 5 |
| The firm's own per-device rule | 5 |
| Measured with no confirmed scale | 4 |
| Class average, from this project's sibling sheets | 3 |
| Class average, for a system never found at all | 2 |

A counted-but-unidentified line sits at 5 deliberately: its quantity is
as good as any counted line's, and its cost is a class average. One
number has to carry both, and the lower of the two is the honest one.

**Adjustments, each recorded by name:**

| Reason | Change |
|---|---|
| A second source agrees — a schedule count matches the placements | +1 |
| The two sources disagree (the existing `schedule_conflict` warning) | −1 |
| The page read or rendered only partly | −1 |
| The symbol was not in the legend | −1 |
| A person approved the line | set to 10 |

**Two invariants on the scale:**

1. **Nothing unapproved reaches 10.** Clamp unapproved lines to 9. The
   top of the scale means "a human checked this", which keeps approval
   worth doing and makes 9 read unambiguously as "very likely right,
   nobody has looked."
2. **It can never contradict the budget range.** The range is built from
   basis spreads, and the starting scores above are ordered by those
   same spreads. A 9 beside a ±25% band would be two parts of the
   product disagreeing about the same fact. A test should assert the
   ordering rather than trusting the table to stay aligned by hand.

**Storage.** `Item.confidence` as a small integer so SQL can sort on it,
plus `Item.confidence_reasons` as JSONB holding the named reasons that
produced it. Null for items processed before this slice; the column
renders empty, sorts last, and a re-run fills it.

## What gets built, in four slices

Each slice ships independently and leaves the product coherent.

### Slice 1 — Stop asking for nothing

No new data. Routing, defaults, and job chaining.

- **Documents → takeoff chains itself.** When every document's read job
  finishes, queue the takeoff rather than waiting for a press. Screen D
  and Project plan stay reachable and keep their controls; they stop
  being turnstiles.
- **Project plan becomes a digest.** Default every derived line to
  accepted. Render a summary ("18 scope statements read, 2 contradict
  each other") and surface only contradictions as wanting a look. Confirm
  and Dismiss survive as corrections on an expanded line.
- **Notes re-run on save**, debounced, rather than behind
  *Apply notes and re-run*.
- **Phases auto-apply** when proposed, marked as proposed, undoable.
  Safe by construction: doctrine already holds that a phase never moves
  a number, a status, or an approval.
- **Estimate summary becomes the landing screen** for a project with a
  completed run.

### Slice 2 — The completion pass ← **building this one first**

Chosen ahead of slice 1: it is the real engineering and the reason the
number currently comes out too small.

**Scope note.** A completion line that lands invisibly is worthless, so
this slice absorbs the minimum of slice 3 needed to make one legible:
the `Guessed` origin tag, the confidence bar, and the evidence link on
the row. The sort-and-filter control stays in slice 3.

A new generator writing `Item` rows with `origin = "assumed"` for work
never counted, each paired with an `Assumption` row that discloses it.

**Every guessed quantity is relative to what this project itself
counted, never an absolute constant.** A sheet that failed to read is
guessed from its sibling sheets' counts; a missing system is a share of
the electrical work actually found. An invented constant is a
placeholder wearing an estimate's clothes — one number cannot serve both
a single-line diagram and a 40,000 sf floor plan — and it degrades
dishonestly, because a project where nothing counted would still produce
a number. The relative form degrades correctly: nothing counted means
nothing guessed.

Cases, in priority order. **The ordering reflects where the engine
actually struggles** — per the estimator, reading a drawing is reliable
today and identifying symbols, resolving scale, and counting are not.

1. **A cluster counted but never identified.** Counting found 47 shapes
   and Classification could not name them. The count is not missing —
   the *catalog item* is, so the line carries no dependable price.
   Assume a cost from the class average for its system, `class_average`,
   and keep the count as counted. This is the most common gap and the
   only one where quantity is solid and money is not.
2. **A sheet with no confirmed scale carrying measured items.** Today
   these are *Missing information* and contribute nothing to the number.
   Assume a scale from the sheet's siblings or the firm's rule, basis
   `scaled`, and disclose it. **The item keeps its `missing` status** —
   Export still blocks until a person sets the scale, which is the
   firewall working exactly as designed. What changes is that the ROM
   stops being silently short while that is outstanding.
3. **A sheet counted implausibly thin** relative to its siblings. Top it
   up to the sibling median, `class_average`. The threshold is a product
   question — see *left to the builder* — and this case shares its whole
   calculation with case 4, so build them together.
4. **A plan sheet that produced no items at all** — read failed, render
   failed, or counting returned nothing. Guess from sibling sheets,
   `class_average`, naming the sheet. Rare if reading is as reliable as
   expected, which is why it is no longer first.
5. **A system absent from the whole job** that a job of this type
   carries. No panels, no lighting, no fire alarm. A share of the
   counted electrical work, `class_average`. Needs the building type —
   see below.

Every completion line's disclosure carries the four fields (`found`,
`why`, `fix`/`where`), an `origin` of `assumed`, and its basis —
identical in shape to what `generate_takeoff.py` already emits, so the
ROM, the range, the qualifications block, and the CSV download absorb
them with no change. The difference from the existing generators is that
these also write the item whose existence is being assumed, so the
number moves rather than only the prose.

### The building type

Case 2 cannot run without knowing what kind of job this is, and building
type is optional at project creation with "Not sure" allowed. Per
decision (2): **infer it, disclose it, ask about it, never block on it.**

- Infer from what the read job already stored — sheet titles, the
  drawing index, schedule text, scope statements.
- Record it as a laddered value with basis `inferred`, so it appears in
  the qualifications block like any other assumption: what was found,
  why it matters, what it rests on, where to look.
- Surface a non-blocking question so the estimator can correct it. A
  correction re-runs the completion pass, exactly as a scope decision
  already re-queues the estimate.
- Where it cannot be inferred at all, run case 1 only and say so. A
  system-level allowance invented without any sense of the building is
  the fabricated number this product exists to prevent.

### Slice 3 — The spreadsheet row tells its own story

- **New column `Item.confidence`** (migration), written by the engine at
  `rows.py:186` instead of being discarded. Null for pre-existing items;
  the column renders "—" and sorts last, and a re-run fills it.
- **Reason column** from the existing `classification_basis`, in words:
  "Matched to the E-501 schedule", "Inferred from context", "Typical for
  this kind of job".
- **Evidence on the row.** The crop and the marker already exist behind
  item selection; surface a link per line that flies the canvas to the
  symbol and opens the crop.
- **Sort and filter** on money, labor hours, and confidence, each
  direction. Money and hours read through `resolved_lines()`, never the
  stored cost columns.
- **Default sort: money, descending** — an expensive guess outranks a
  cheap certainty, which is the ranking that makes a 400-item sheet
  reviewable.

### Slice 4 — Read it off the schedule

Extract quantities from `Sheet.schedule_text` so a schedule stating
"Type F — 24" produces 24 rather than a class average. One rung, high
value, and a language call — so it routes through the single
Classification path (`CLAUDE.md`: "Conversation routes; it does not
answer"), never a second parser.

## Totals, and the two numbers

| Number | Query | Shown on | Means |
|---|---|---|---|
| Estimate total | `rom_totals()` / `resolved_lines()` | Estimate summary, spreadsheet footer | Everything found and assumed |
| Approved total | `approved_totals()` | Export preview, finish review | What a person has checked |

Both exist today. The change is that the first one leads. They must be
labelled so the pair is never ambiguous, and the Export preview must
continue to show only the second.

## What this does not change

- The four review labels, their meanings, their colours, their count.
- Approval as the only gate on Export, with *Missing information*
  blocking and no override.
- `counted` vs `assumed` as a separate axis from the four labels, in
  `--slate`/`--plum`, never borrowing `--amber`.
- Layer toggles filtering what is drawn and never what is counted.
- Agents stopping at total direct cost.
- The worker as the only process that opens a PDF.

## What is left to the builder

- **The implausibly-thin threshold** (slice 2, case 3). Deliberately
  unspecified. Pick something defensible, make it one named constant,
  and state it in the disclosure copy; do not tune it quietly.
- **Class-average sources.** Where "typical for this kind of job" comes
  from — the firm's seeded tables are the obvious first home, since
  `defaults.py` already holds firm-level tables and the resolution chain
  is company default → project override.
- **Confidence banding in the UI.** Whether the column prints a figure
  or a short band. The estimator chose a sortable score; how it reads on
  the row is a presentation call, provided it never implies a
  probability about the bid.
- **A completion item's confidence.** It has no engine confidence, since
  no classification ran. Derive it from the reliability of its rung —
  the basis spread is already an ordered measure of exactly that — and
  keep the mapping in one place.
- **How the building-type question is surfaced.** The conversation panel
  and the Project plan digest are both plausible homes; it must be
  answerable through a normal control either way, because the panel is
  never the only path to anything.
- **Digest wording** on the Project plan screen.
- **Where the auto-chain stops** if a document fails its read. Partial
  success is already the rule for sheets; mirror it rather than
  inventing a second policy.

## Where this goes next

Option 3 — a number before counting — becomes available once slice 2
lands, because "no items at all" is simply the completion pass with
nothing to complete around. Worth doing only after watching how the two
totals read to a real estimator.
