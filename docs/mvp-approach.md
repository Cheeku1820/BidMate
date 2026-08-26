# MVP approach — how the number gets made

**Date:** August 17, 2026
**Status:** Decided in discussion, not yet reflected in `ROADMAP.md` or `BUILD-STAGES.md`

The goal this document serves: **produce a defensible dollar amount for a Division 26 bid** — materials, quantities, and labor — that an estimator can check and sign their name to.

This is not a plan. It is the set of decisions a plan would be built from, with the reasoning attached, so that the reasoning survives the decision.

---

## 1. Geometry counts. Language models read.

**Decision.** Symbol detection and counting on vector drawings is a geometry problem, solved by reading the PDF's own drawing instructions. Language models are used for interpretation, not for localization.

**This split is now an agent boundary, not just a method note.** Counting and Classification are separate agents with separate inputs, outputs, and ways of being measured — Counting is *tested* against known counts, Classification is *evaluated* against expected labels. Counting emits an unlabelled cluster and does not know what anything is. See [`superpowers/specs/2026-08-18-bidmate-agent-architecture-design.md`](superpowers/specs/2026-08-18-bidmate-agent-architecture-design.md) §2.

**Why.** A vector PDF is not a picture. It is a list of operations — draw this line, place this symbol definition at this coordinate. Where a drafter's ninety-six receptacles survive as one definition and ninety-six placements, the coordinates are in the file and can be extracted deterministically.

**Three tiers, and the tier decides the method.** This is the part to verify before building anything on it:

| Tier | What arrives | Method | Expected quality |
|---|---|---|---|
| A | Vector, symbols preserved as reusable definitions | Read the placement list | Near-exact counts and positions |
| B | Vector, symbols exploded into loose line work | Cluster identical geometry patterns | Still deterministic, more engineering |
| C | Raster — scanned, or deliberately flattened | Image processing plus OCR | Materially worse; mark the sheet honestly |

Tier B is the one that is easy to overlook. A drawing can be fully vector and still have every symbol exploded into individual paths by the publishing settings, in which case there is no placement list to read and repeats must be found by matching geometry. Solvable, deterministic, and several times the work of tier A.

A single set can mix all three — new-work sheets published clean, as-built sheets scanned in.

Asking a vision model to locate ninety-six symbols instead produces approximate boxes, some misses, and some inventions. That failure is not recoverable in the interface: a marker floating in empty space tells the estimator the software cannot see the drawing, and they stop trusting every other marker on the page. Precision of placement is not a nice-to-have here — it is the entire basis of the trust the product is asking for.

**What each side does.**

| Geometry / classical CV | Language and vision models |
|---|---|
| Find repeated symbol placements | Read the legend and the fixture schedule |
| Exact coordinates for every marker | Read the title block — sheet, revision, scale |
| Count instances | Match a plan tag to a schedule row |
| Measure between known points | Read the specification for applicable requirements |
| Compare two revisions of a sheet | Normalize "DUPLEX RECEPT, 20A, TYP" into a catalog item |
| | Detect that two documents disagree, and explain it in plain language |

The conflict flow the prototype already demonstrates — plan tag versus luminaire schedule — sits entirely in the right-hand column and is well within current capability.

**Consequence.** Scanned sets do not get this. Without vector geometry the counting falls back to image processing and OCR, and results will be materially worse. Those sheets are marked unreadable with a reason rather than returned as a short list of items. Silence reads as completeness.

---

## 2. What the blueprint is for

**Decision.** The blueprint is where a takeoff is **checked** and **corrected**. It is not where a takeoff is produced from scratch.

Three jobs a blueprint view could do:

1. Where the takeoff gets made — click every device yourself
2. Where the takeoff gets checked — "it found 96; show me where"
3. Where the takeoff gets fixed — "it missed this room; let me add it"

We build 2 and 3. We do not try to win at 1.

**Why.** Winning at 1 means a feature fight with Bluebeam and PlanSwift, products with fifteen years of polish, on their ground — and it demotes the automation to a side feature. But 2 cannot ship without 3: the first time the engine misses forty devices and the estimator has no way to add them, they close the tab.

**The correction that follows from this.** The blueprint does not make an estimate accurate. The engine does. The blueprint makes error **visible**.

That distinction decides which features are worth building. A wrong count is not the dangerous failure — the estimator can see a wrong count. The dangerous failure is a count that was never made: forty devices on a sheet that was read badly, where the page looks fine because there is nothing on it to look wrong.

So the highest-value thing on the canvas is not the measuring tools. It is **showing what was and was not read** — which sheets were understood, which areas were skipped, where the engine stopped looking. An empty region must read as "not examined," never as "nothing here."

---

## 3. Conduit and wire are judgment, and we say so

**Decision.** Device and fixture counts are a solved-enough problem. Conduit and wire run lengths are not, and the product does not pretend otherwise.

**Why.** The drawing usually does not show where conduit goes. It shows a homerun arrow and leaves routing to the installer. An estimator infers the length from ceiling height, building geometry, and how they would actually pull it. That information is not in the file for anyone — human or machine — to extract.

Wire and conduit are a large share of material cost, so this is the single biggest threat to the "accurate dollar amount" goal.

**How it surfaces.** Produce a run length where the geometry supports one. Where it does not, put the estimator's own rule in front of them — the feet-per-device they normally carry on a job of this type — and have them confirm it. That is still faster than starting from nothing, and it is honest about which half of the number is measured and which is judged.

This is also why *Missing information* blocks on scale: without a confirmed scale, a measured length is not a number, it is a guess wearing a number's clothes.

---

## 4. Most of the estimate is not AI

Worth stating plainly, because it makes the build smaller than it looks.

1. Count the devices — **the hard part; this is the engine**
2. Map counts to assemblies (a fixture needs a whip, a connector, clips) — **a lookup table**
3. Price the materials — **a data feed plus supplier quotes**
4. Calculate labor — **quantity × NECA unit × named adjustments; arithmetic**
5. Tax, overhead, profit — **arithmetic**

Only step 1 is an AI problem. Once counts are approved, the dollar amount follows deterministically and every figure traces back to a quantity and a source. It also means accuracy lives almost entirely in step 1 — no amount of polish downstream rescues a bad count.

### 4.1 Waste, and what "approved quantity" means

**Decided.** *Approved quantity* is the **installed** quantity — what the estimator verified against the drawing. Labor is calculated against it. Waste is applied only when pricing material.

340 feet of feeder drawn is 340 feet approved and 340 feet of labor hours. The purchase quantity of 374 exists only on the material side.

**Store the inputs, never the product.** The measured or counted quantity and the waste factor are separate fields; the purchase quantity is derived at the point it is needed. Storing the multiplied result is what allowed the same 10% to be applied twice in the design deck — 340 becoming 374 on the takeoff and 411 at pricing. Keeping them separate makes that class of error structurally impossible rather than something review has to catch each time, and it leaves either display convention available later without a migration.

**The reasoning to preserve.** Waste is scrap and offcut — material bought and not installed. NECA units price installation, and nobody installs the offcut. Charging labor against the purchased quantity inflates hours on every measured run in the bid, invisibly, in the direction that loses the job.

This also settles what the status vocabulary means for a measured item: approving it means *I agree this is what gets installed*, which is a claim about the drawing rather than about a purchase order.

---

## 5. The MVP wedge

Four things, chosen because each one saves time the estimator can feel on the first sheet.

**Symbol counting with batch verification.** The engine groups symbols by type; the estimator confirms a whole type at once rather than clicking through ninety-six. Replaces hours of highlighter work.

**Find every one like this.** The estimator clicks one symbol, says what it is, and every other instance on the set resolves. This is the most valuable single feature because *it works when the engine is bad* — a symbol type missed entirely becomes thirty seconds of work instead of a dead end. It is also the mechanism that fills the per-firm symbol library.

**Addendum comparison.** Comparing two revisions of a set is mechanical, painful, high-stakes, and something a computer does well on vector PDFs. Missing an addendum change is how estimators lose money. This is currently scheduled for stage 2 and should move earlier.

**Labor and material from lookups**, once counts are approved. Cheap to build, and it is what turns a takeoff into the number they actually need.

**Deliberately held back:** automatic conduit routing, scanned-set support beyond an honest unreadable marking, and anything producing a number the estimator cannot check quickly.

---

## 6. The spreadsheet

Two separate things, decided separately.

### 6.1 Importing the spreadsheet they already keep — yes

Beyond the obvious onboarding value, an imported spreadsheet paired with the drawings it came from is a **graded answer key**: a labeled example of a correct takeoff for that building type. That is the benchmark corpus `ROADMAP.md` says the accuracy screen depends on, and it is otherwise the hardest artifact to obtain.

**Open detail.** An imported row has no drawing behind it, and the product's premise is that every quantity links to evidence. Imported rows carry their own provenance — "from the estimator's file" — and are honest that the evidence is a person's judgment rather than a drawing. Traceable to the truth, which is different from traceable to a sheet.

Note the boundary: importing at the **start** of a project is onboarding. Re-importing **after** review would overwrite the audit trail and is a different, worse feature.

### 6.2 A spreadsheet inside the platform — yes, with a hard limit

Build a **table with spreadsheet manners**, not a spreadsheet engine.

What estimators want from Excel is muscle memory: tab and enter to move, copy a column, fill down, multi-select, undo. All of that belongs in the table.

What must not ship is an arbitrary formula engine. The moment someone types `=SUM(D2:D40)*1.1` into a cell there is a number in the product that cannot be traced, reconciled against the export, or explained — which breaks invariant 1, totals computed in exactly one place.

Embedding real Excel has the same defect in a different costume: the data would live in a Microsoft document rather than the domain model, so it could not be linked to the blueprint, audited, or reconciled. It would look like the requested feature while removing the reason the product exists.

**Worth considering:** an explicit scratch area that is visibly *not* part of the bid. Estimators do side math constantly. Somewhere sanctioned to do it beats them doing it in a separate file nobody can see.

---

## 7. Adding, removing, and changing

**Changing** — select the marker, edit classification or quantity in the item panel, approve. Already built.

**Removing** — keep *reject* and *delete* distinct and do not merge them. Reject means "found, but not real" — a duplicate, or existing-to-remain. Delete means it should not be in the file at all. Rejected items stay visible on their own layer, because an estimator needs to see what they discarded, especially a week later.

**Adding** — three paths, in build order:

1. **Find similar.** Start from an existing item, review the found set, approve as a batch. Fastest, and it needs no new interface.
2. **Pick a type and click.** A palette of recent types plus the project's symbol library, then click to place. This is the Bluebeam pattern; estimators already know it.
3. **Region and describe.** Drag a box: "everything in here is type F, there are nine." Far faster than nine clicks.

Measured runs are drawn as a polyline against a confirmed scale.

**The principle that holds it together:** a manually added item is *the same kind of record* as a found item. Same panel, same fields, same undo, same contribution to totals. Its evidence is "added by Dana on E2.1" rather than a set of coordinates. A separate flow with a separate shape means two systems that will disagree.

**Instrument it.** Count items added by hand. Two hundred manual additions on a set means the engine failed on that set, and that number is the best available signal for what to fix next.

**Division of labor between the two views:** the plan is where spatial corrections happen ("six more fixtures in this room"); the table is where bulk corrections happen ("all 96 of these are tamper-resistant"). Selection is already synchronized in both directions, which is the right foundation for exactly this.

---

## 8. What this changed in the existing documents

Applied August 17, 2026. Recorded here so the amendments can be traced back to the reasoning above rather than appearing as unexplained edits.

| Document | Was | Now |
|---|---|---|
| [`ROADMAP.md`](../ROADMAP.md) 2.1 | "Symbol detection and classification against the set's own legend" | Split into two bullets — geometry finds and counts, models interpret |
| [`ROADMAP.md`](../ROADMAP.md) 2.1 | "Conduit and homerun tracing for measured runs" | Reframed as partly judgment; measure where geometry allows, otherwise ask |
| [`ROADMAP.md`](../ROADMAP.md) 2.1 | PDF ingestion as a vector/raster split | Three tiers, since exploded vector is its own case |
| [`ROADMAP.md`](../ROADMAP.md) 2.8, 3.4 | No mention of spreadsheet import | Added, with the confidentiality boundary and the benchmark-corpus link |
| [`BUILD-STAGES.md`](../BUILD-STAGES.md) stage 1 | "conduit tracing" inside the engine list | Removed from the promise; stated as a deliberate scope decision with its reason |
| [`BUILD-STAGES.md`](../BUILD-STAGES.md) stage 1 | — | Added find-every-one-like-this, addendum comparison, spreadsheet import, add/reject/delete |
| [`BUILD-STAGES.md`](../BUILD-STAGES.md) stage 2 | "Revision and addendum handling end to end" | Comparison moved to stage 1; resolution stays here |
| [`BUILD-STAGES.md`](../BUILD-STAGES.md) capability table | — | Two rows added: counting method and measured runs |

---

## 9. Still open

- **Which tier do real bid sets actually arrive in?** §1 rests on it. A pilot that is mostly tier A is a different product from one that is mostly tier B, and no amount of reasoning substitutes for opening real files. This is the cheapest high-value thing outstanding.
- **NECA labor unit licensing and a regional pricing feed.** Both are contracts, and two workspaces are inert without them.
- **Naming.** The product says "blueprint"; the trade says drawings, plans, prints, or sheets. Bluebeam, PlanSwift, and Procore all avoid the word. Cheap to change now, expensive once it is in URLs and habits.
- **What "accurate" is measured against.** There is rarely a perfect reference takeoff; the real test is whether the job made money. This constrains what the accuracy screen can honestly claim.
- Everything already listed as open in [`CLAUDE.md`](../CLAUDE.md) — shared undo, revision conflict flow, approval authority — is unaffected by this document and still needs a call.
