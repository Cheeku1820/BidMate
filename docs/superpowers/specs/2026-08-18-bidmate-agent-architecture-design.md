# Agent architecture — design

**Date:** 2026-08-18
**Status:** accepted. Amended 2026-09-03 against a real bid set — see §11.
**Scope:** stage 1 engine boundaries — see [`BUILD-STAGES.md`](../../../BUILD-STAGES.md)
**Supersedes:** nothing. Extends [`docs/mvp-approach.md`](../../mvp-approach.md) §1 and [`ROADMAP.md`](../../../ROADMAP.md) §2.1 and §2.6.

> **Read §11 first if you are implementing.** The five boundaries below still
> hold, but running the engine against a real 208-page set on 2026-09-03
> answered this document's largest open question and falsified one claim in
> §2.2. §11 records what changed and what the code actually does today.

---

## 1. What this decides

The workflow this product runs — bid invitation to submitted bid — has been drawn as three AI agents with three human approval gates. This document settles what an agent actually is here, where the boundaries fall, what crosses them, and how each one gets measured and improved.

The conclusion is **five agents, not three**, and the reason is not tidiness. It is that "train each agent on its own task" is only possible if each agent has exactly one task of exactly one nature. Two of the original three bundled work that cannot be trained the same way, which would have made their accuracy numbers undiagnosable the first time one moved.

### What this document is not

It is not a plan, and it authorises no code. It fixes boundaries so that the plan which follows has something to be a plan *about*.

### Success criteria

- Every agent has a single nature — deterministic or language — and a stated way of being measured.
- No agent reads another agent's prose. Handoffs are typed records.
- A correction made once resolves every identical instance, and that behaviour is a consequence of the boundaries rather than a feature bolted on top.
- Nothing an agent produces reaches a bid without a named person and a timestamp.

---

## 2. The five agents

| Agent | Nature | Produces | Measured by |
|---|---|---|---|
| **Documents** | Language, over a deterministic shell | Sheet list, discipline, revision, scale, legend, schedules | Eval set of sheets → expected structured output |
| **Counting** | Deterministic geometry | Clusters of identical shapes with exact coordinates | **Tested, not trained.** Known sets, known counts |
| **Classification** | Language | Catalog item per cluster, with status and warning | Eval set of clusters + legend → expected item |
| **Pricing** | Lookup, with one language component | Assemblies, material cost, labour hours | Tested; the quote-line matcher gets its own eval set |
| **Conversation** | Language | Intent, target records, routed proposals | Eval set of utterance + anchor + state → expected routing |

### 2.1 Documents

Splits the uploaded set into sheets, identifies which are electrical, reads the title block for number, title, discipline, revision and date, detects the drawing scale, and extracts the legend and fixture schedule into structured data. Flags anything it cannot read.

The shell is deterministic — page splitting, embedded-text extraction. The core is language: a title block is a picture of a table, and a legend is a picture of a dictionary. The language half dominates and the shell fails loudly rather than silently, so this stays one agent.

**The legend and schedule output is the highest-leverage thing this agent produces.** The conflict flow the prototype already demonstrates depends on the E0.1 luminaire schedule existing as structured rows, not as an image. Everything Classification does downstream is matching against what Documents extracted here.

### 2.2 Counting

Finds symbol placements and their coordinates. On a vector sheet these are *in the file*; they are read, not estimated. Where symbols have been exploded into loose line work, identical geometry is clustered. Where the sheet is raster, this degrades and says so.

> **Amended 2026-09-03 (§11.1).** "They are read, not estimated" holds only for
> tier A — a set carrying reusable symbol definitions. The first real bid set
> examined is tier B, fully exploded, where there is no placement to read and
> the clustering sentence above is the whole job rather than a fallback. The
> shipped code does neither: it matches tag-shaped text tokens, a third method
> this section never contemplated, and it counts an engineer's seal as devices.

**Counting does not know what anything is.** It outputs *one cluster of 47 identical shapes at 47 coordinates* — a shape signature and a position list, unlabelled. Naming them is Classification's job.

This is the agent whose failures are most expensive to trust. A marker whose position came from a guess sits slightly off the symbol, and one visibly wrong marker costs the estimator's confidence in every other marker on the page. It therefore gets asserted counts on known sets, not a tuned score.

### 2.3 Classification

Takes an unlabelled cluster plus the legend, the schedules, and the firm's symbol library, and decides what the cluster is. Matches plan tags to schedule rows. Normalises a source description into a catalog item. Assigns one of the four review statuses and, where warranted, a four-field warning.

This is the genuinely uncertain work and where a model belongs.

### 2.4 Pricing

Expands each approved item into its assembly — a fixture becomes box, cover, wire, connector, conduit, labour — then applies NECA labour units and supplier pricing to produce direct cost.

Almost all of this is arithmetic over lookup tables, which is why live totals are affordable (§4.2). The one language component is matching a supplier's quote line to a catalog item, and it runs once at classification time rather than on every recompute.

> **Amended 2026-09-03 (§11.3).** The shipped code contradicts this: unit
> material cost, labour hours, the location labour rate and the material
> factor all come back from the Classification model call, not from a lookup.
> That was a deliberate product decision — no hardcoded price table may be
> shown to an estimator as though it were real pricing — and it is recorded
> rather than quietly tolerated. Assembly expansion, the part that turns a
> fixture into box, wire, conduit and connector, is not built at all.

### 2.5 Conversation

Interprets what the estimator says, resolves who and what they mean, decides which domain it belongs to, and assembles the result into a proposal.

An anchor tells you what was pointed at, not what was meant. "Ignore this wing, it's existing to remain" is a scope exclusion. "Ceiling's 14 feet in here" feeds measuring. "We're not doing site lighting on this bid" touches the project record and several sheets at once. None of those route by anchor alone. That interpretation is a model, and giving it a boundary makes it testable: utterance + anchor + project state → intent, target set, domain.

Three limits keep it from absorbing the other four:

1. **It routes; it does not answer.** Given "these six are all type F," Conversation resolves *which six* and *which field*, then hands to Classification for the label. It never classifies itself. Two paths to a classification means two classifiers, and when they drift every per-agent accuracy number stops meaning anything.
2. **It proposes; it never writes.** Its output is a preview with counts. A person applies it, through the same path a manual edit takes. This is [`ROADMAP.md`](../../../ROADMAP.md) invariant 9, unchanged.
3. **Its output shape is constrained.** Proposals are typed against known record types, never arbitrary actions. Conversation is the only agent reading both estimator text and extracted drawing text, so it is the surface invariant 11 was written for.

### 2.6 Why the Counting/Classification split earns its keep

Because it produces "find every one like this" as a consequence rather than a feature.

Counting emits clusters. Classification labels clusters. So the estimator corrects a **cluster**, and one correction resolves 47 items. [`BUILD-STAGES.md`](../../../BUILD-STAGES.md) calls this the most valuable feature in stage 1 — the one that works *when the engine is bad*, turning a wholly missed symbol type into thirty seconds of work instead of a dead end.

Had counting and classification stayed one agent, the same behaviour would require reconstructing clusters after the fact from a flat item list. Same feature, more code, and a reconstruction that drifts from the thing it is reconstructing.

---

## 3. The shared record

Agents share a **store, not a transcript.** This is the same rule [`CLAUDE.md`](../../../CLAUDE.md) already states for the conversation panel — *the panel writes to the store; it is not a store* — applied one level down.

### 3.1 Why not pass context forward

Because errors compound invisibly. Documents hedges, Classification inherits the hedge as fact, and by Pricing there is a confident number resting on an uncertainty nobody can locate.

And because it destroys the training goal. If Classification's input is a typed record, two hundred of them can be frozen as an eval set and replayed forever; changing Documents leaves those evals valid. If the input is "whatever Documents said," every Documents tweak invalidates every Classification measurement, and per-agent training stops being possible in practice.

**The clean handoff is the precondition for the separate training, not a nice-to-have.**

It is also a security control. A typed record with known fields enforces invariant 11 — extracted document text is data, never instruction — by *shape*. Free text spliced into a downstream prompt is an injection surface, and a drawing set is untrusted input from the internet.

### 3.2 The three layers

Context genuinely lives at three different lifespans, and collapsing them is how firm knowledge ends up trapped in one project.

| Layer | Holds | Lifespan |
|---|---|---|
| **Firm** | Labour rates, waste factors, feet-per-device rules, symbol library, catalog | Across projects, indefinitely |
| **Project** | GC, building type, scope in and out, sheets to ignore, drafting conventions, addenda, pinned price basis | One bid |
| **Sheet / item** | Scale, legend, schedules, items with position, type, quantity, status, warning | One document set |

The project layer is captured at intake, before processing. [`ROADMAP.md`](../../../ROADMAP.md) §2.6 already calls it the highest-value context in the system and the cheapest to collect. Collecting it afterwards means processing ran without it.

### 3.3 What each agent touches

| Agent | Reads | Writes |
|---|---|---|
| Documents | Uploaded files, project layer | Sheets, scale, legend, schedules |
| Counting | Sheets, rendered geometry | Clusters with coordinates |
| Classification | Clusters, legend, schedules, symbol library, project layer | Items with type, status, warning |
| Pricing | Approved items, firm layer | Assemblies, material, labour |
| Conversation | Any layer, plus the estimator's message and anchor | Nothing — proposals only |

Pricing needs nothing from Documents directly. It needs *items*, and by then items are a settled record. That the boundaries produce no awkward reach-backs is evidence they are drawn in roughly the right places.

### 3.4 Context flows backward

When the estimator says "these six are all type F" during review, that answer reaches the symbol library so Classification stops asking, and reaches Pricing so the right item gets priced. It travels through the store — not by re-running Documents. It takes the same path a manual edit takes, so it lands in the action log attributable to a person, per invariant 8.

---

## 4. The pipeline

### 4.1 Shape

Documents and Counting run once per sheet, as queued jobs, with per-sheet partial success. Classification runs per cluster and re-runs when its inputs change — a corrected legend entry, a new symbol library resolution.

**Pricing does not run as a stage. It is live.**

### 4.2 Live pricing

Totals recompute continuously as items are approved. This is affordable because pricing is lookups: quantity × labour unit, quantity × supplier price. A table join costs nothing to repeat. The one expensive part — matching a supplier quote line to a catalog item — happens once, at classification, and is cached.

Four consequences:

**Pricing is derived, never stored.** The total is recomputed from inputs on every read. This is what keeps invariant 1 honest: one totals query feeding the drawer, the table, the export, and the estimate summary. The moment a current-price column is written onto a row there are two implementations, and they will drift.

**Pricing never enters the undo stack.** Approving an item is one action; the total moving is a consequence. Undo the approval and the total moves back on its own. No compensating price action, nothing new in the log. Same shape as the waste decision in [`docs/mvp-approach.md`](../../mvp-approach.md) §4.1 — *store the inputs, never the product*.

**The price basis is pinned.** A number that is live across a week of review can move for reasons that are not the estimator's edits: a supplier feed updates overnight and Tuesday's total no longer matches Monday's. A bid must be reproducible. The project pins a price-book version and rate set at start, displays it plainly, and refreshing is an explicit act with a visible diff.

**Two numbers, not one.** An estimator at item 220 of 400 needs to know roughly where this lands, but only approved work counts — that is the legal firewall the whole status vocabulary rests on. So the drawer shows approved-and-final alongside a clearly provisional projection. The projection never gets green and never gets exported. Green stays what [`CLAUDE.md`](../../../CLAUDE.md) says it is.

### 4.3 Where measuring sits

Conduit and homerun lengths are not counting and not classification. With automatic routing deliberately out of stage 1 scope, measuring is *apply the firm's feet-per-device rule to counted devices* — arithmetic over the item table, guided by rules the estimator owns.

**Proposed:** measuring is a derived calculation alongside pricing, not a fifth agent. It has no model in it at stage 1.

This is the weakest proposal in this document and is flagged in §10 accordingly.

---

## 5. The three gates

Every gate is a named person, a timestamp, and a frozen state in the append-only action log. That is what makes "nothing ships without human sign-off" provable rather than asserted — an auditor points at one row.

| Gate | Freezes | Reopened by |
|---|---|---|
| **1 — Sheets and revisions** | Which sheets are in scope, which revision is active | Uploading or superseding a sheet |
| **2 — Takeoff review complete** | The approved item set handed to pricing | Changing any item after the checkpoint |
| **3 — Cost basis signed** | Quantities, price basis, rates | Any of the above |

### 5.1 Gate 2 is a checkpoint, not a batch approval

Gates 1 and 3 are single decisions. Gate 2 is not — on a hospital plan it is four hundred decisions made over hours, each already recorded with a name and timestamp by per-item approval.

So two things exist, and both are needed:

- **The per-item approvals** — the actual work. Already built, already logged, already blocking on *Missing information* with no override.
- **The checkpoint on top** — *"Dana Whitfield marked the takeoff review complete at 3:42pm; 412 items approved, 6 acknowledged allowances."* Not a second approval of each item. A record of the state handed forward.

The checkpoint also gives live pricing a defined input: it prices against the checkpoint, and changing an item afterwards visibly reopens it.

### 5.2 What gate 2 must not become

A gate that approves everything at once drives straight through a rule [`CLAUDE.md`](../../../CLAUDE.md) already fixes: bulk approval applies only to *Ready to review* items, never to *Needs attention* or *Missing information*. The checkpoint records approvals that already happened. It does not perform them.

---

## 6. Direct cost is the output

**The agents stop at total direct cost.** Markup, overhead, profit, bond, and tax are an estimator-owned layer on top.

Three rules:

- **No agent proposes a markup number.** Same category as approval: there is judgment that stays with the person, and the spread between cost and bid — often the difference between winning and losing a job — is the most guarded number an estimator has.
- **The markup layer lives in the product but is input, not output.** Visible, editable, saved with the project so the bid is reproducible, and displayed as the estimator's number, distinct from the cost basis beneath it.
- **Markup fields do not get the four status labels.** They are not evidence-backed items; they are project settings. Applying the status vocabulary to them dilutes it.

This is also the lower-liability position. [`ROADMAP.md`](../../../ROADMAP.md) §3.3 calls for terms that disclaim reliance, and *"we produce a cost basis, you produce the bid"* is a far cleaner line than *"we produce a bid you should check."*

---

## 7. Confidence stays inside

Confidence exists in the engine and does exactly two jobs:

1. **It decides the status.** Sufficient evidence → *Ready to review*. Conflicting or uncertain → *Needs attention*. This translation happens server-side, once. What crosses the API boundary is the label.
2. **It orders the queue.** "Review these first" is genuinely valuable and needs no number attached. It is a sort order, not a disclosure.

**It is never rendered.** No per-item percentage, anywhere.

The reason is not rule-following. A visible number invites the estimator to do arithmetic on trust — *87%, that's probably fine, I'll skim it* — which is precisely the reasoning path that produces a confidently wrong number at 4pm on bid day. Four labels force a decision instead of an estimate about an estimate.

There is a calibration problem too. The score is a model's internal number, and it would appear beside quantities and dollar figures that are real measurements. Placing them side by side implies they are the same kind of fact.

This restates [`ROADMAP.md`](../../../ROADMAP.md) §2.1 and invariant 7. It is recorded here because the workflow diagram currently contradicts it (§9).

---

## 8. The training loops

"More users make the agents better" is three loops with very different speeds and very different legal footing. They should not be planned as one thing.

### 8.1 Per-agent evaluation — the precondition

Each agent gets a frozen eval set of typed inputs and expected outputs, per §2. This is what makes the other two loops legible: without it, "the engine got better" is an anecdote.

Counting is the exception and the important one. **It is tested, not trained.** Known sets with known counts, asserted exactly. Tuning a deterministic extractor like a model is how exact work quietly becomes approximate.

### 8.2 Loop one — the firm's own symbol library

An estimator classifies an unfamiliar symbol once; every instance on the set resolves. Next month, same architect, same convention, no question asked. Entirely within one customer's own data: no consent question, no NDA exposure. It compounds in weeks.

[`ROADMAP.md`](../../../ROADMAP.md) §2.1 already calls this the compounding asset and the main reason breadth is affordable. Stated more strongly here: **for the first year this is the entire flywheel.** It works without touching a model weight.

### 8.3 Loop two — correction telemetry across customers

Every estimator correction yields a pair: what the engine said, what a person changed it to, under what drawing conditions. That pair is a label and a context tag — **not the drawing**. It aggregates across customers, and it is what identifies where the engine is actually weak instead of where it is guessed to be weak.

[`BUILD-STAGES.md`](../../../BUILD-STAGES.md) already requires telemetry by drawing condition for exactly this. It is the cheapest loop and the input to the third.

### 8.4 Loop three — fine-tuning on drawing content

The slowest, most constrained, and last to pay off.

[`ROADMAP.md`](../../../ROADMAP.md) §3.3 records that drawing sets frequently arrive under NDA from a general contractor, and §3.4 states that an NDA'd set does not become training data because it arrived through an import button. **That constraint holds unchanged.** A contractor discovering that a competitor's bid set trained the model is a company-ending event, not a bad quarter.

So loop three requires explicit per-customer opt-in, and a meaningful share will decline. That is survivable, because the two things that break on real sets — legend interpretation and symbol classification — improve more from a better reference library and better retrieval than from tuned weights.

### 8.5 The propagation trap

A flywheel that propagates a *wrong* resolution is worse than no flywheel. One misclassification becomes a default and is then silently wrong on every future bid: a systematic error rather than a one-off.

[`ROADMAP.md`](../../../ROADMAP.md) already leans toward firm-level defaults surfacing as *Ready to review* rather than pre-approved. **Cross-customer defaults must clear a higher bar than that** — agreement across several independent firms before becoming a default anywhere. The specific threshold is open (§10).

---

## 9. What this changes in the existing documents

| Document | Change |
|---|---|
| [`CLAUDE.md`](../../../CLAUDE.md) | Add the five agents and the store-not-transcript rule to Architecture |
| [`ROADMAP.md`](../../../ROADMAP.md) §2.1 | Split symbol detection into Counting and Classification as named agents |
| [`ROADMAP.md`](../../../ROADMAP.md) §2.6 | Conversation is an agent that routes, not a panel that answers |
| [`ROADMAP.md`](../../../ROADMAP.md) invariants | Add: agents hand off typed records, never prose |
| [`BUILD-STAGES.md`](../../../BUILD-STAGES.md) | Stage 1 engine line names the five agents; add per-agent eval sets |
| [`docs/mvp-approach.md`](../../mvp-approach.md) §1 | Geometry/language split is now an agent boundary, not just a method note |
| Workflow diagram | Three wording fixes, below |

### 9.1 Workflow diagram corrections

Three lines in the current diagram contradict decisions already recorded in the repository:

1. **"Assigns confidence score per item"** → the score exists but never renders (§7). "Sorts by review priority" is correct as written and should stay.
2. **"Reviews low-confidence flags first"** → *reviews by review priority*. The behaviour survives; the number does not.
3. **"Bid number = total direct cost"** followed by "apply markup & margin" → self-contradictory. It should read *total direct cost*, with the bid being what the estimator produces from it (§6).

Also: the diagram's Agent 2 spans counting and matching, and Agent 3 spans pricing and assembly. Redrawing against §2 gives five boxes.

---

## 10. Still open

- **Where measuring lives.** §4.3 proposes a derived calculation rather than an agent. It is the weakest claim here. If measuring later acquires real inference — reading ceiling heights off sections, inferring routes where geometry supports it — it becomes an agent and should be split then, not retrofitted into Counting.
- **The cross-customer default threshold.** §8.5 says several independent firms must agree before a resolution becomes a default anywhere. How many, and over what window, is undecided. It must be settled before the shared library is built, not after.
- **Whether Documents should split.** Its deterministic shell and language core are kept together on the argument that the shell fails loudly. If page splitting or embedded-text extraction turns out to fail *quietly* on real sets, that argument dissolves and it splits like Agent 2 did.
- **The unmeasured time claim.** The workflow diagram asserts 3–5 days becomes 2–4 hours. [`BUILD-STAGES.md`](../../../BUILD-STAGES.md) requires review time be measured, not asserted, and names it an exit criterion. The claim should carry no number until a design partner produces one.
- ~~**Which PDF tier real bid sets arrive in.**~~ **Answered 2026-09-03 — see §11.1.** The first real set is tier B: vector, fully exploded, no reusable symbol definitions. One observation is not a distribution, so the question narrows rather than closes — but the tier that Counting's design most depends on is now a measured fact for at least one set, not a guess.

---

## 11. Amendments from the first real bid set (2026-09-03)

The engine was run against the Unalaska Public Library expansion package — 208
pages, 14 electrical sheets — twice: once deterministic, once with the
classification model live. What follows is measured, not argued.

### 11.1 The PDF tier is B, and §2.2's central claim does not survive it

Two representative sheets:

| Sheet | Vector paths | Raster images | Form XObjects |
|---|---|---|---|
| E1.1 lighting plan | 33,410 | 2 | 1 |
| E6.1 | 68,601 | 2 | 1 |

One XObject per sheet, and it is not a symbol block. So every symbol is
exploded into loose line work: **tier B** in [`docs/mvp-approach.md`](../../mvp-approach.md) §1.

This matters because §2.2 says placements "are *in the file*; they are read,
not estimated." On tier B nothing is placed — there is no instance to read.
Grouping fragments back into symbols is the entire job, and it is a materially
harder one. A first attempt measured this directly: signature-matching whole
path objects reduced 33,410 paths to 365 distinct shapes, but only **20
placements** across four clusters once filtered to symbol-sized multi-stroke
shapes, because exploded CAD emits each stroke as its own path object. Real
tier-B counting needs spatial grouping of fragments before any signature is
computed.

**Consequence for planning.** Geometry-based counting is a research task, not a
task. It is explicitly out of the "basic version of each agent" scope and
should be planned on its own, against this set as the test fixture.

### 11.2 What the shipped Counting agent actually does, and what it costs

It matches text tokens shaped like a tag (`^[A-Z]{1,3}\d{0,2}$`) that stand
alone on their own text line inside the drawing region. On this set that
counted 812 placements, of which at least 21% are identifiably not devices:

| Source | Placements | What it is |
|---|---|---|
| Engineer's seal | 87 | The perimeter text of a professional engineer's stamp, set on a curve, so each letter is its own rotated single-character span. Reads as "State of Alaska · Registered Professional Engineer". `A` became *Luminaire type A*, `S` a switch, `T` a data outlet, `R` a receptacle — on all 14 sheets. |
| Panel-schedule headers | 35 | `VA`, `CKT`, `AMP` |
| Prose in general notes | 11 | `NOT`, `OFF` |

**Two candidate filters were tested; only one works.**

- **Reject rotated glyphs — works.** Every seal letter carries its own text
  direction vector; a drafter sets a device tag horizontally. This removes all
  87 seal placements with no plausible false positive.
- **Require adjacent vector geometry — does not work, and the idea should not
  be revived without new evidence.** The intuition is that a real tag sits
  beside a symbol. Measured on E1.1, every counted tag has 35–49 strokes within
  14 points, seal letters included, because a plan carrying 33,000 paths has
  geometry everywhere. The filter does not discriminate on a dense sheet.

### 11.3 Pricing is currently a language call

`llm.estimate()` returns `material_cost`, `labor_hours`, `location_labor_rate`
and `material_factor` — the whole of Pricing's output — inside the
Classification call. §2.4 describes Pricing as lookup arithmetic with one
language component.

This is a deliberate deviation, not drift. The alternative was a small
hardcoded regional table, and showing an estimator a fabricated number as
though it were real pricing is the failure this product exists to prevent. The
guard that makes it safe is already built and verified on this set: a project
records which mechanism priced it, and one not priced by the model shows
*Missing information* on every labour and material row rather than a borrowed
figure.

The deviation stands until there is a real pricing source to look up against —
see [`docs/superpowers/specs/2026-09-01-...`] and the pricing-source survey.
**What is genuinely missing is assembly expansion:** a fixture is priced as a
fixture, with no box, whip, connector, wire or conduit behind it. For an
electrical subcontractor that is the largest hole in the estimate, since wire
and conduit are a large share of material cost.

### 11.4 Where the model does help, measured

With classification live, distinct warning titles went from 2 to 14 across 106
warnings, and the text became specific enough to act on:

- `NOT` → *"part of general note wording such as not to scale or not in contract"* → **exclude from the takeoff**
- `WP` → *"listed in the abbreviations as weatherproof, so it modifies another device rather than being counted on its own"* → **trace each to the device it labels so it is not double counted**
- `O` → *"appears in the legend as an occupancy sensor symbol but is also in the range of letters used for fixture types, so the count may mix lighting controls with luminaires"*

Eight tags came back titled *Not a device*. **Classification can see a
substantial part of Counting's noise and say so, without being able to remove
it** — the separation in §2.6 is what forces that, and it is the right trade:
a flagged phantom is one click to reject, a silent one is a wrong bid.

### 11.5 Documents produces text, not rows

§2.1 calls structured legend and schedule extraction "the highest-leverage
thing this agent produces." Today `schedule_text` is a raw blob concatenated
across sheets and handed to the model. Every *"type F needs confirmation"*
warning on this set traces to that gap: the model is reading an unparsed wall
of text and correctly declining to guess.

### 11.6 What "a basic version of each" means, given the above

| Agent | Basic version scoped here |
|---|---|
| Documents | Parse the extracted schedule text into typed rows — type letter, description, mounting — instead of a blob |
| Counting | The rotated-glyph filter and schedule-region exclusion. **Not** geometry clustering, which is §11.1's separate research task |
| Classification | Read those typed rows, and persist a resolution to a project-scoped symbol library so one correction holds |
| Pricing | Assembly expansion as a real lookup: a device becomes its box, connector, whip, wire and conduit |
| Conversation | Intent routing to a typed proposal record. No panel, no writes |

Division 26 remains the boundary. Every material this produces is electrical.
