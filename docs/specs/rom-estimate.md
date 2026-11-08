# The ROM: an estimate that assumes what it cannot read

Written 2026-11-05.

## Why

Today the product produces exactly one number, and that number is the
sum of items a person has approved one at a time. `approved_totals()`
in `api/app/takeoff/totals.py` adds up `ReviewStatus.APPROVED` and
nothing else; everything unapproved increments `remaining_count`. A
project at 0% reviewed has an approved total of zero, and zero is the
only figure the product will state. Export refuses to run while any
*Missing information* item remains (`ExportPreview.jsx`, `disabled={blocking.length > 0 || approved.length === 0}`),
and an item carrying that status cannot be approved at all
(`src/lib/rules.js`, `refusalToApprove`).

That is a defensible way to build a hard bid. It is the wrong shape for
the thing an estimator is asked for most often: a rough order of
magnitude, handed to a general contractor early, conditioned on a page
of stated assumptions. An estimator gives a ROM freely. What makes it
safe is not that every line was approved — it is that every line that
was *guessed* is named, with the basis for the guess, in the document
the GC receives.

This spec builds that artifact. The engine already computes everything
it needs: `resolve_material_price` and `resolve_labor` run on every
item the moment it is counted, without consulting approval status. The
arithmetic exists. The product withholds it. The ROM stops withholding
it, and pays for that by making the assumptions visible.

## The shift in one line

**Before:** the estimate does not exist until approval creates it.
**After:** the estimate exists as soon as the documents are read, and
every line says whether it was read or filled in.

## Goals

- A complete Division 26 number from the moment processing finishes, with
  no human step in between.
- Every line in it tagged with its origin and a basis a reader can check.
- A qualifications page generated from the assumed lines, not written by
  hand — it is the condition of the price and the thing that makes a ROM
  safe to hand over.
- Assumptions generated per section, visible in that section, and
  carried downstream so a later section says when it is pricing an
  earlier section's guess.

## Non-goals

- **Markup, overhead, profit, bond, and tax.** The agents stop at total
  direct cost (`ROADMAP.md` invariant 13) and this changes nothing about
  that. A ROM is a cost number; the spread to a bid stays the
  estimator's.
- **Automatic conduit routing.** Still out, for the reason
  `BUILD-STAGES.md` gives. The ROM applies the firm's feet-per-device
  rule and *says it did* — that is the whole difference between this and
  guessing silently.
- **Redesigning the review workspace.** It keeps working as it does.
- **Phases and schedule.** Untouched by this spec.

## Anti-goals

Things that would make this a failure even if it shipped and worked:

- **A ROM that reads as a bid.** If the document can be mistaken for a
  hard number, the assumptions stop protecting anyone.
- **An assumed line with no basis.** A number the reader cannot trace is
  worse than no number, because it borrows the credibility of the lines
  that *are* traceable.
- **A second exclusion predicate.** `countable_items()` is the one place
  that decides what a total may contain. A hand-copied `!rejected` filter
  next to the ROM query is how the ROM and the drawer quietly disagree.
- **A fifth status label.** `counted` and `assumed` describe where a
  *number* came from. They are a different axis from the four review
  labels, which describe an item's evidence, and they must not be
  rendered with the review-status components or colours — the same
  separation `--slate`/`--plum` already enforce for note status
  (`CLAUDE.md`, "A note's status is not an item's status").

## Decisions already made

These came from the estimator and are not the builder's to revisit.

1. **It is a ROM handed to a GC**, not an internal draft.
2. **Approvals no longer gate anything.** The approve/reject controls and
   the four review labels stay in the review workspace for an
   estimator's own tracking; nothing downstream of them reads their
   state. `approved_totals()` keeps working for that workspace. The ROM
   ignores it.
3. **Two origins, not more:** `counted` and `assumed`.
4. **Scope is rarely the problem.** A scope document usually exists and
   `api/app/engine/scope.py` already extracts statements from it with
   verbatim-quote validation. The assumptions that matter are about
   quantities and items.
5. **Everything carries evidence**, assumed lines included, so a reader
   who doubts a number can land on the reason.
6. **It lives in the Estimate summary workspace**, the nav slot that
   currently renders disabled with "not built yet".
7. **The approved mockup** is `docs/specs/assets/rom-mockup.html`:
   section header with a counted/assumed tally, one row per line with an
   origin tag and a basis line beneath it, assumed rows carrying a dashed
   left edge, a generated qualifications block, and a budget range beside
   the headline figure.

## The model

### Origin

Every line the ROM renders carries an origin:

- **`counted`** — the number came from the documents. A quantity
  Counting read off a sheet, a scope statement extracted with a verbatim
  quote, a material price fetched from a market source, a supplier's
  quoted figure.
- **`assumed`** — the number was filled in because the documents did not
  supply it. A firm default, a rule of thumb, a class average, a standard
  exclusion, a length scaled off a plan.

An estimator who types over an assumed value turns that line
`counted`, with a basis reading `Entered by <name>, <date>`. *Builder's
call, flagged here for review:* from the GC's side the useful
distinction is "the contractor knows this" versus "the contractor filled
this in," and an estimator's own knowledge belongs in the first bucket.
The basis line keeps it honest about not having come from the drawing.

### The assumption record

An assumption is a first-class row, not a string on an item. It mirrors
the four-field warning shape the product already enforces, because the
qualifications page is written from these fields directly:

| Field | Meaning |
|---|---|
| `section` | `scope`, `takeoff`, `labor`, `material` |
| `subject` | the item, sheet, or project the assumption attaches to |
| `title` | the one-line statement, as it appears in the ROM |
| `found` | what the documents did or did not say |
| `why` | what the number would be missing without it |
| `basis` | the named rule that produced the value (below) |
| `where` | which sheet, schedule, or document was read for it |
| `value` / `unit` | what was filled in |
| `source` | `engine` or `estimator` |

A record missing `basis` or `where` is a schema error, refused at the
boundary, exactly as a four-field warning is today in
`api/app/takeoff/ingest.py`. That refusal is what keeps the anti-goal
above from happening by accident.

### Basis classes

A closed set, mirrored on both sides, in the manner of
`api/app/schedule/stages.py`. Each names where a filled-in number came
from, and each carries the spread used for the budget range:

| Basis | Example | Spread |
|---|---|---|
| `supplier_quote` | a price somebody quoted | 0% |
| `firm_default` | the firm's labor rate table, crew mix, stage split | ±10% |
| `market_estimate` | catalog or shopping price by ZIP | ±15% |
| `class_average` | 1200A switchboard with no quote on file | ±20% |
| `inferred` | a device named from context, not from the legend | ±25% |
| `rule_of_thumb` | 62 ft of homerun per device | ±25% |
| `scaled` | a feeder length measured off a site plan | ±20% |
| `standard_exclusion` | temp power excluded, nothing said | 0% |

`firm_default` already exists in substance — `api/app/schedule/defaults.py`
seeds crew sizes and stage splits per org and its header is explicit that
these are "the default" until a firm edits one. This spec gives that
idea a name and extends it across the other three sections.

### Why the range is not a confidence score

`CLAUDE.md` forbids rendering confidence, and it is right to: a
percentage attached to a model's belief invites arithmetic on trust.
The ROM's range is a different object. It is a spread over named
assumption classes, each listed in the qualifications block, each
traceable to a rule the firm can read and change. It says "this number
rests on a 62 ft per device rule," not "the software is 80% sure."
Nothing model-derived reaches it. Keep it that way.

## Where assumptions come from, by section

The cascade the estimator described: each section assumes what it must,
and later sections price earlier sections' assumptions and say so.

### 1 · Scope

Mostly counted. `engine/scope.py` extracts statements with verbatim
quotes; those render `counted` with the quote as `where`. What gets
assumed is the absence — a standard exclusion applied because no
document addressed it. `api/app/plan/copy.py` already writes
estimator-facing copy for several of these gaps (`no_specs`,
`no_scope`); its wording is the starting point, re-pointed from "state
it here as an answer" to "assumed, change it if wrong."

**Scope filters the number.** An exclusion — stated or assumed —
removes the items it covers from the ROM total, and the qualifications
block names what was removed and what it was worth. "Fire alarm by
others" with fire-alarm devices still in the total is a document whose
stated scope and actual number disagree, which is the one way a ROM
misleads while every individual line is correct. Flipping an exclusion
changes the total, which is what makes the scope section worth reading.

This is the cascade's start and the sharpest edge in the spec: a wrongly
assumed exclusion removes real money silently. Two consequences for the
build — an assumed exclusion must always be listed in the
qualifications block even though it subtracts rather than adds, and the
excluded value is carried on the record so the block can state it.

### 2 · Takeoff quantities

Counted placements stay counted — this is the half of the engine that
reads rather than estimates, and nothing here loosens it. The assumed
lines are the ones Counting cannot produce: homerun and branch footage
(`rule_of_thumb`, the firm's feet-per-device), ceiling heights with no
RCP in the set, feeder lengths the one-line implies but does not
dimension (`scaled`).

**The scale case.** A sheet with no scale currently makes its measured
items *Missing information* and blocks. Under the ROM those items get a
`scaled` or `rule_of_thumb` value instead — but the error on a guessed
scale multiplies across every measured run on the sheet rather than
staying local to one line. The spec's position: a missing scale produces
an assumption at the **sheet** level, listed once in the qualifications
block as affecting every measured run on that sheet, rather than
quietly per-item. The estimator sees one statement they can act on, and
the GC sees one condition rather than forty.

**A cluster nothing can name.** Counting emits 47 identical shapes;
Classification cannot match them to a legend row or a schedule line.
Today that is a *Needs attention* item and a dead end. The ROM resolves
it the way an estimator reading the whole set resolves it — by
inference — and then says that is what it did.

The gap is not that these symbols are unknowable. It is that the
classifier is given far less than the set contains.
`api/app/engine/context.py` assembles schedules, documents, and notes,
and `llm.py`'s `_prompt()` then truncates the result to
`(schedule_text or "").strip()[:6000]` with `max_tokens=1500` to answer
in. Six thousand characters is a keyhole onto a set whose legend sheet
alone can exceed it. A person — or a model given the same material —
resolves most unmatched tags by reading the legend and the schedule
together, plus the sheet the tag sits on and what it is circuited with.

So the build does two things in order:

1. **Widen the keyhole.** Give Classification the legend sheet and the
   full schedule text rather than a 6000-character slice, and the
   neighbouring context on the sheet. Most unmatched clusters resolve
   outright and become `counted`, with the legend or schedule row as
   their `where`. This is worth doing on its own merits and is
   independently measurable against the frozen eval set
   (`BUILD-STAGES.md`, stage 1).
2. **Tag what is left.** A cluster that still cannot be matched takes a
   best-inference name with basis `inferred`, is priced at that name,
   and appears in the qualifications block naming the tag, the count,
   the sheet, and what it was taken to be.

What this deliberately does **not** copy from a chat-produced bid is the
silence. A chat returns a confident, complete number and never says
which lines were inferred. That is not better capability; it is absent
disclosure, and it is the confidently-wrong-number failure this product
exists to prevent. Inference is welcome. Unlabelled inference is not.

Counting is untouched by any of this — it still reads placements out of
the file rather than estimating them, and stays tested rather than
tuned. Only the naming of what it found becomes more willing.

### 3 · Labor

Almost entirely assumed today and already honest about it. Rates come
from the firm table when no project rate is set, hours from the firm's
labor-unit table, crew mix from `CREW_SEED`. `resolve_labor` already
returns a basis note per line; this section surfaces those notes as
assumption records rather than as a footnote.

### 4 · Material

Market-priced lines are `counted` with the source and fetch date as
`where` — `api/app/market/copy.py` already holds the outcome words.
Lines with no market result and no supplier quote take `class_average`.
Wire and conduit are the cascade's endpoint: they are priced against
section 2's assumed footage, and the basis line must say so, because a
reader who accepts the footage accepts this dollar figure with it.

### Combining spreads into the range

Dollar-weighted and linear. Each assumption's spread applies to the
dollars that depend on it; the ROM's range is the sum of those dollar
swings, not a root-sum-square of them. Quadrature would produce a
tighter and more statistically respectable band, and it is the wrong
choice here: an estimator has to be able to explain the range to a GC
in one sentence, and "these four assumptions could move it by this
much, added up" is a sentence. A line with `supplier_quote` or
`standard_exclusion` basis contributes nothing to the spread. *Builder's
call.*

### A re-run never discards an override

`CLAUDE.md` holds that the engine never discards a person's judgment —
a run merges into each sheet rather than replacing it, and an
*Estimator approved* item is never overwritten by processing. An
estimator's override of an assumed value is the same kind of thing, and
gets the same protection: a later run may add, revalue, or remove
engine-generated assumptions, and must leave any assumption whose
`source` is `estimator` exactly as it found it. This belongs in
`api/app/takeoff/merge.py` alongside the approval-preserving logic
already there. *Builder's call, by analogy to an existing rule.*

### A line nothing can price

An item with no market result, no supplier quote, and no class average
renders with its quantity and a blank cost rather than a zero, and
appears in the qualifications block as excluded from the number. A zero
reads as "free"; a blank with a statement reads as "not priced," which
is what is true. *Builder's call.*

## The artifact

A new **Estimate summary** workspace, filling the disabled nav slot,
rendering the approved mockup. Four sections in the order above, a
generated qualifications block, and a footer stating that assumed
quantities were not read from the drawings.

The existing **Export** workspace is untouched by this spec. It keeps
previewing approved totals and downloading the approved-items CSV,
blocking on *Missing information* exactly as it does today. Downloading
the ROM is a control on the Estimate summary workspace, not a change to
Export — two outputs, two paths, no shared gate. Whether Export should
eventually be folded into this is a later decision and not one to make
in passing here.

Two rules the mockup encodes and the build must keep:

- **Origin is never colour alone.** The tag carries a word, and assumed
  rows carry a dashed left edge, so the distinction survives a
  black-and-white print — the same discipline the product applies to
  review status and to unverified measurements.
- **Green does not appear.** It remains reserved for estimator-approved
  content, which the ROM does not contain.

## Totals

The risk here is `ROADMAP.md` invariant 1 — totals computed in exactly
one place. The design:

- `countable_items()` stays the single exclusion predicate (not
  superseded, not rejected) and both aggregations build on it.
- `approved_totals()` keeps its `ReviewStatus.APPROVED` filter, unchanged,
  serving the review workspace and the dashboard.
- `rom_totals()` lands beside it in the same module and applies no status
  filter at all.

Two aggregations over one predicate, in one file. They are different
numbers on purpose and must never be presented as the same one.

## What is left to the builder

- Schema and migration for the assumption record, and whether origin is
  stored on the item or derived at read time from the presence of an
  assumption against it. Derivation is cheaper to keep correct; storage
  is cheaper to query. Either is acceptable.
- Where the per-section generation runs. The worker already resolves
  pricing and labor per item; scope and takeoff assumptions may belong
  to the sheet job. Keep it out of the API process — `app.main` may not
  import anything that opens a file.
- The qualifications block's ordering and deduplication. Forty items
  sharing one ceiling-height assumption must produce one line, not forty.
- Whether an estimator's override writes back to the firm's default
  tables or stays project-local. The symbol-library propagation question
  in `ROADMAP.md` is the same question and is still open; do not settle
  it in passing here.
- Copy for each basis class, in the product's register: no model names,
  no processing internals, plain construction terms.

## What this does not change

`countable_items()` and its exclusions. The four review labels, within
the review workspace. The action log and `commit()`. Layer toggles
never touching totals. The engine's five-agent split and the
Counting/Classification boundary. The rule that agents stop at direct
cost. Phases and schedule.
