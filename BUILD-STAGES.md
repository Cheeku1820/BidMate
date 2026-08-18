# Build stages

[`ROADMAP.md`](ROADMAP.md) is the inventory of what a shippable product needs. This is the order it gets built in, and — more usefully — what each capability looks like at each stage, since almost nothing is built once and finished.

Stages advance on **exit criteria, not dates**. The engine is the only genuinely unpredictable piece; everything else is estimable work. Any schedule that treats stage 1 as a fixed duration is guessing at the one thing that cannot be guessed at.

| Stage | Name | Who uses it | Exists to prove |
|---|---|---|---|
| 0 | Prototype | Nobody outside the team | The interaction model is right |
| 1 | Design partner MVP | 3–5 firms, hand-held | An estimator will bid off this output, on the sets they actually receive |
| 2 | Paid general availability | Self-serve customers | The business works without us in the room |
| 3 | Scale | Larger firms, bigger sets | It holds under real volume and enterprise procurement |
| 4 | Platform | Ecosystem and adjacent trades | It becomes infrastructure, not a tool |

---

## Stage 0 — Prototype (done)

Screen F, running client-side against seed data.

The output is not code, it is two settled things: the data model (four statuses, the four-field warning schema, the action shape with `before`/`after`/`by`/`at`) and the interaction contract (autosave, compound undo, layer toggles that never touch totals, blocking rules at the item level). Both carry into every later stage. The infrastructure carries into none.

---

## Stage 1 — Design partner MVP

**Goal.** Put a real drawing set through the system and have an estimator submit a real bid off the result. Nothing else in this stage matters.

**Broad by default.** A pilot goes to subcontractors who bid whatever lands in their inbox — a medical office building this week, a school addition next week, a warehouse the week after. Telling them to use it only on one building type means they use it on nothing, because the qualifying step is more work than the tool saves. Accept any commercial Division 26 set: vector or scanned, any building type, any size.

Division 26 stays the boundary. That is a product scope decision, not a drawing-condition one.

**Which moves the quality bar somewhere else.** Breadth means the engine meets unfamiliar symbols, drafting conventions, and sheet organizations constantly, and it will be uneven. The bar cannot be held at intake by refusing work, so it is held at the item level instead — the status vocabulary already does exactly this job:

- Gaps surface as *Needs attention* and *Missing information*, per item, with the four-field warning intact
- A sheet the engine reads poorly is **marked unreadable with a reason**, never returned as a short list of items with no indication that forty were missed. Silence reads as completeness.
- The conversation layer ([`ROADMAP.md` 2.6](ROADMAP.md#26-the-conversation-layer)) is the recovery path, which is why it is stage 1 scope rather than a later refinement. When the engine cannot classify a symbol on an unfamiliar set, the estimator tells it once and the answer applies to every instance in the set.

The failure mode to design against is unchanged — a confidently wrong number at 4pm on bid day. Breadth does not relax that. It means being wrong is prevented by visible uncertainty rather than by refusing the file.

**The density problem this creates.** The prototype has twelve items and four warnings. A hospital power plan can carry four hundred items and a hundred questions, and a review workspace that is pleasant at twelve is unusable at four hundred. Bulk handling — group by warning type, resolve every instance of a symbol at once, filter to one question class — moves from stage 2 nicety to stage 1 requirement.

**What gets built**

- Tenancy and auth — real from day one, because neither can be retrofitted. Email and password, one role, invitations.
- Upload and ingestion (screen C), accepting broadly, with honest per-file failure copy
- The engine across the full breadth, built as **five agents** — Documents, Counting, Classification, Pricing, Conversation. Each has exactly one nature, which is what makes them separately measurable. See [`docs/superpowers/specs/2026-08-18-bidmate-agent-architecture-design.md`](docs/superpowers/specs/2026-08-18-bidmate-agent-architecture-design.md); the geometry-versus-language split behind it is [`docs/mvp-approach.md`](docs/mvp-approach.md) §1.
- **A frozen eval set per agent**, from the first pilot set. Typed inputs, expected outputs, replayable. Without them "the engine got better" is an anecdote, and the separate-agent split buys nothing. **Counting is the exception: it is tested, not trained** — known sets, asserted counts, no tuning.
- **Find every one like this** — the estimator classifies one symbol and every instance on the set resolves. The most valuable feature in the stage, because it works *when the engine is bad*: a symbol type missed entirely becomes thirty seconds of work rather than a dead end. It is also what fills the symbol library. It falls out of the Counting/Classification boundary rather than being built on top — Counting emits clusters, Classification labels clusters, so a correction lands on a cluster.
- **Addendum comparison**, pulled forward from stage 2. Comparing two revisions is mechanical, painful, high-stakes, and something a computer does well on vector sheets. Missing an addendum change is how estimators lose money, so this is a wedge feature rather than a close-out one. The full revision *conflict* flow stays in stage 2 — comparison is not the same as resolution.
- **Spreadsheet import at project start**, which delivers value before the engine is trusted and produces the benchmark corpus as a side effect
- Per-sheet coverage outcomes, including an explicit unreadable result
- Processing status (screen E) with per-sheet partial success
- Review workspace (screen F) ported onto a real API, **with bulk handling built for density**, and with add / reject / delete so a person can close the gap the engine leaves
- **The conversation layer** — anchored to the canvas, project context capture at intake, questions from pipeline gaps, proposals a person applies. Not an add-on here; it is the mechanism that makes broad coverage survivable.
- **The per-firm symbol library**, written to by conversation resolutions
- A **lean screen G** — flat table, no grouping, but with bulk approve on *Ready to review*. This is the difference between a four-hour review and a one-hour one, and review time is the metric the design partners will judge you on.
- Excel export (screen H), reconciling exactly with drawer totals
- Minimal screens A and B — a project list and a create form
- Usage metering events, even though nobody is billed yet
- **Telemetry by drawing condition** — building type, vector or scanned, drafting origin, sheet count, against coverage and review time. Breadth without this teaches nothing; it is how stage 2's priorities get chosen rather than guessed.
- Backups, and one tested restore

**What is deliberately not built**

Billing UI, SSO, public API, integrations, accuracy screen, settings screens, revision conflict flow, mobile anything, per-user undo, cross-project firm memory (the symbol library stays project-scoped until the propagation policy is decided).

**Automatic conduit routing is deliberately out**, and this is a scope decision rather than a schedule one. The drawing shows a homerun arrow, not a route; the run length is judgment from ceiling height and building geometry and is not in the file for anyone to read. Measure where the geometry supports it, and elsewhere ask, carrying the firm's own feet-per-device rule as the starting point. Guessing a length silently is the confidently-wrong-number failure this whole product is built to prevent, and wire is too large a share of material cost to be wrong about quietly.

**Concierge is acceptable here.** When the pipeline misses, someone on the team fixes the data by hand before the estimator sees it, and that gap becomes the engine backlog. Design partners know the product is early — that is what makes them design partners. The product itself never claims more than it delivers.

**Exit criteria**

- A design partner submits a real bid using output from the system
- Review time is meaningfully below their manual baseline, measured, not asserted, across **several building types rather than one**
- No incident where a wrong number reached a submitted bid
- Failure modes are visible uncertainty at review, never silent omission
- **Coverage by drawing condition is known and quantified** — which building types, drafting origins, and document qualities the engine handles well, and which it does not. This is the primary output of a broad pilot and the input to every stage 2 priority.
- Questions asked per sheet trending down as the symbol library fills

---

## Stage 2 — Paid general availability

**Goal.** A firm that has never spoken to us signs up, pays, and gets value. Everything here is about removing the team from the loop.

**What gets built**

- Billing: plans, trials, invoicing, purchase orders and ACH alongside cards, dunning, usage limits with a humane cap policy
- Roles and approval authority — estimator, chief estimator, admin, read-only guest
- Confirm-detected-drawings (screen D) and the settings screens (J, K) with the company-default → project-override resolution chain
- Full screen G, and screen H hardened
- Revision and addendum handling end to end, including the conflict flow. Comparison itself shipped in stage 1; what lands here is resolution — whether approvals carry forward, how a superseded sheet stays browsable, and how a mid-review swap reaches a second reviewer already in the file.
- **Raising the floor on the conditions stage 1 handled badly.** Breadth is already there; this is quality work aimed by the coverage telemetry, not new territory. Expect scanned-set OCR and a handful of building types to dominate the list.
- **Cross-project firm memory**, once the propagation policy is settled — a symbol resolved on one project defaulting on the next, surfaced as *Ready to review* rather than silently pre-approved
- Conversation layer maturity: shared-thread resolution policy, question ranking, answering from screens C, D, and G rather than F alone
- Real collaboration service replacing `sync.js`, with a decided undo model
- Support tooling: audited impersonation, a back-office view, a status page
- Security posture: penetration test, SOC 2 readiness instrumentation, documented incident response
- Terms, DPA, privacy policy, E&O insurance
- Onboarding, documentation, in-product help
- The test suite and CI gate that stage 1 skipped, retrofitted with intent — the review state machine, the totals query, and the blocking rules are the three things that must never regress

**Exit criteria**

- Self-serve signup to first export with no human intervention
- Support load per customer flat or falling
- Churn understood, not just measured
- SOC 2 evidence accumulating

---

## Stage 3 — Scale

**Goal.** Survive larger firms, larger sets, and enterprise procurement.

**What gets built**

- Performance work on 300+ sheet sets: tiling, virtualized rendering, incremental load
- Queue prioritization by bid date, per-tenant concurrency limits, backpressure
- SSO, SCIM, audit log export, data residency answers
- SOC 2 Type II completed
- Integrations that matter: Procore and BuildingConnected inbound, Accubid and ConEst outbound
- The accuracy program — benchmark corpus, then screen I built on top of it
- Multi-project and multi-office rollups
- Cost engineering on the pipeline, since unit economics decide gross margin at this point

**Exit criteria**

- Largest customer set processes within a bid cycle
- Enterprise security review passed without exception
- Contribution margin positive per project at list price

---

## Stage 4 — Platform

**Goal.** Other systems build on it.

Public versioned API and webhooks. Adjacent divisions — 27 and 28 share drawing conventions and are a natural extension of the same pipeline. The later spec stages (labor rates, material pricing, markup) turn a takeoff into an estimate, which is a substantially larger product surface and should not be started before the takeoff itself is trusted.

---

## How each capability builds out

The column-by-column view. Most rows are the same capability getting progressively less manual, which is the honest shape of building this.

| Capability | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|---|---|---|---|---|
| **Takeoff engine** | Broad coverage, uneven quality, gaps surfaced as questions | Floor raised where telemetry says it is lowest | Tuned per customer's drafting conventions | Divisions 27 and 28 |
| **Agent evaluation** | Frozen eval set per agent; Counting tested, not trained | Correction telemetry aggregated across customers | Fine-tuning on consented sets only | Published methodology |
| **Counting method** | Geometry on vector sheets; classification by language | Clustering for exploded vector; better raster | Trained detectors for scanned sets | Unchanged |
| **Measured runs** | Where geometry supports it; elsewhere the firm's own rule, confirmed | Firm rules learned from history | Routing inference where drawings allow | Unchanged |
| **Documents accepted** | Any commercial Division 26 set, vector or scanned | Same breadth, better results | Large sets, odd conventions, mixed disciplines | Any construction document |
| **Coverage honesty** | Per-item status, per-sheet unreadable outcome | Coverage shown before review starts | Predicted at upload, before processing spends | Published methodology |
| **Conversation layer** | Anchored to canvas and items, proposals a person applies | Available on C, D, G; ranked questions; shared-thread policy | Fewer questions per sheet as memory compounds | Available over the API |
| **Project context** | Captured at intake, applied to one project | Reused across a firm's projects | Suggested from the firm's history | Shared across partner ecosystem |
| **Symbol library** | Project-scoped, filled by resolutions | Firm-scoped, defaults surface as *Ready to review* | Regional and drafting-origin patterns | Contributed and versioned |
| **Review at density** | Bulk handling and grouping from day one | Question ranking, resolve-all-instances | Virtualized for 400+ item sheets | Unchanged |
| **Sheet rendering** | Server-rendered tiles, `pdf.js` in the client | Cached and pre-warmed | Progressive and virtualized for 300+ sheets | Unchanged |
| **Identity** | Email and password | Roles, invitations, MFA | SSO, SCIM, deprovisioning | Service accounts, API keys |
| **Approval authority** | Anyone in the org | Roles decide | Optional second approver per project | Policy engine |
| **Tenancy** | Real from day one | Unchanged | Data residency options | Unchanged |
| **Collaboration** | Polling is fine at this size | WebSocket fan-out, presence | Reconnect, replay, offline tolerance | Unchanged |
| **Undo** | Shared linear stack, as today | Decided model, server-backed | Conflict resolution under real concurrency | Unchanged |
| **Storage** | One bucket, tenant-scoped keys | Lifecycle and retention policy | Tiering, cost management | Customer-managed keys |
| **Processing queue** | Simple queue, retries | Partial success, dead-letter, reprocess | Bid-date priority, per-tenant limits, backpressure | Unchanged |
| **Export** | Excel only | Excel plus source references, hardened | Accubid, ConEst, Trimble | Public API and webhooks |
| **Document sources** | Manual upload | Manual upload | Procore, BuildingConnected | Partner ecosystem |
| **Billing** | Meter, invoice by hand | Self-serve, plans, PO and ACH | Enterprise contracts, custom terms | Usage-based API pricing |
| **Security** | Encryption, scanning, sane defaults | Pen test, SOC 2 readiness, incident response | SOC 2 Type II, enterprise review | Customer-specific controls |
| **Observability** | Error tracking and logs | Metrics, alerting, on-call, status page | SLOs and an SLA that means something | Per-tenant health |
| **Accuracy** | Watch design partners work | Internal regression corpus | Benchmark program, screen I | Published methodology |
| **Support** | The team, by name | Audited impersonation, back-office view | Tiered support, SLA | Partner support |
| **Testing** | Smoke tests on the critical path | Full suite, CI gate | Load and soak testing | Contract tests on the public API |

---

## Things that move a stage boundary

Worth naming so the plan can bend without being rewritten.

- **The engine is harder than expected on real sets.** Still the most likely outcome, and broad intake guarantees meeting it early rather than late. The response is *not* to narrow the input — the pilot needs breadth to be used at all. It is to lean harder on visible uncertainty and on the conversation layer, and to accept that early review sessions involve more estimator input than the eventual product will.
- **Question volume overwhelms the review.** The specific failure of a broad pilot: a set arrives where the engine asks about two hundred symbols and answering them is slower than a manual takeoff. Watch questions-per-sheet as a first-class metric from the first pilot set. The mitigation is resolve-all-instances and the symbol library, both of which are already stage 1 scope for this reason.
- **Estimators lean on the conversation panel more than expected.** That is allowed — they can work through it as much as they want, and heavy use is a sign it is doing its job. It is a signal to read, not a behavior to restrain: if reviews are being completed conversationally because the structured interface is slower, the structured interface is what needs fixing. The constraint to hold is only that the structured path keeps working, not that people prefer it.
- **Design partners want the estimate, not the takeoff.** Pricing and labor pull forward from stage 4. This is a real possibility — a takeoff is an input to the thing they actually get paid for.
- **A large customer arrives early** and wants SSO and a security review before signing. Stage 3 items pull into stage 2. Acceptable, as long as the engine is genuinely ready, because their drawing sets will be the largest the system has seen.
- **Unit economics come in worse than modeled.** Metering from stage 1 is what makes this visible in time to change pricing rather than discovering it at renewal.
