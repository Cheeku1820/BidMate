# Electrical Estimating Platform: Product and Accuracy Roadmap

**Document purpose:** Define how the product progresses from supervised blueprint takeoff to a complete, auditable electrical estimate.

**Initial market:** Electrical subcontractors bidding commercial construction in the United States.

**Initial automated scope:** Core CSI Division 26. The pilot accepts any commercial project type, classifies it after upload, and reports performance by project type rather than rejecting unfamiliar projects.

**Product principle:** The system may automate interpretation, but it must never hide uncertainty or invent scope. Every quantity, labor hour, and cost must be traceable to its source and remain subject to estimator approval.

---

> **How this relates to [`ROADMAP.md`](../ROADMAP.md).** Two roadmaps in one repository drift, so it is worth stating which does what rather than leaving the next reader to guess.
>
> [`ROADMAP.md`](../ROADMAP.md) is the **governing inventory** of work between the prototype and a shippable product, and [`BUILD-STAGES.md`](../BUILD-STAGES.md) is the order that work happens in. Where the two documents disagree about scope, sequencing, or what is built, those govern.
>
> This document is kept for what it carries that they do not: the **accuracy policy** (§4), the **core information model** (§5), the **validation matrix** (§6), and the **pilot operating model** (§7). Nothing else states how accuracy gets measured or what a validated result has to satisfy, and that is the part worth preserving.
>
> Its §1–§3 overlap with `ROADMAP.md`'s tracks and predate several settled decisions — the five-agent engine boundaries, the conversation layer's additive constraint, and the direct-cost output boundary. Read those sections as historical context, not as current direction.

## 1. Product Outcome

The finished platform converts construction documents into an estimator-reviewed electrical bid:

1. The estimator creates a project and uploads drawings, specifications, schedules, addenda, and scope documents.
2. The platform identifies relevant sheets, revisions, legends, scales, schedules, notes, and electrical systems.
3. It produces a source-linked material takeoff.
4. The estimator resolves warnings and corrects the takeoff in a blueprint-centered review workspace.
5. Approved quantities map to licensed NECA labor units and company-defined labor adjustments.
6. Localized and company-specific prices convert the approved takeoff into cost.
7. The platform produces an auditable estimate and Excel export.

The first milestone stops after estimator-reviewed takeoff and Excel export. Labor, pricing, and proposal generation are gated on measured takeoff performance.

## 2. Scope Boundaries

### Included initially

- Any commercial construction drawing set, regardless of building type
- Drawing and specification PDFs, including scanned pages
- Lighting fixtures and lighting controls
- Receptacles and common electrical devices
- Panels, transformers, switchgear, disconnects, and generators
- Feeders, branch circuits, conduit, conductors, and grounding where the drawing provides sufficient evidence
- Equipment and material schedules
- Drawing revisions and addenda
- Web-based estimator review and Excel export

### Excluded from initial automated totals

- Fire alarm
- Communications and structured cabling
- Security and access control
- Audio/visual systems
- Other specialty low-voltage systems
- Autonomous final-bid approval
- A universal cost-accuracy guarantee based on generalized material prices

Excluded scope may be recorded as a manual allowance. The interface must identify it clearly and must not imply that it was automatically estimated.

## 3. Roadmap and Release Gates

### Stage 0 — Evidence foundation

**Objective:** Create the data and evaluation structure needed to measure progress honestly.

**Capabilities**

- Store each project’s source documents, revisions, estimator takeoff, corrections, and available bid breakdown.
- Record project type, size, drawing format, scan quality, system mix, and document completeness.
- Define a normalized item catalog with names, aliases, units, system classifications, and assembly relationships.
- Separate development projects from untouched benchmark projects.
- Preserve incomplete historical projects while recording which ground-truth fields are missing.

**Preferred design-partner package**

- Original drawing set and addenda
- Specifications and scope letter
- Detailed takeoff export
- NECA labor report and labor adjustments, when available
- Material breakdown and supplier quotes, when available
- Final bid and estimator notes

**Release gate**

- Five representative projects available for development and two untouched projects available for evaluation.
- If fewer projects are available, label the product an exploratory prototype and publish no accuracy claim.

### Stage 1 — General Division 26 takeoff

**Objective:** Produce a structured, source-linked first-pass takeoff from commercial construction documents.

**Capabilities**

- Accept drawings, specifications, schedules, addenda, and scope documents.
- Identify electrical sheets and classify the project without restricting it by building type.
- Detect legends, symbols, scales, schedules, notes, references, and drawing revisions.
- Count supported fixtures, devices, panels, transformers, switchgear, disconnects, generators, and equipment.
- Measure supported conduit, conductor, branch-circuit, and feeder runs.
- Link every result to a sheet, page region, extraction method, and source evidence.
- Flag unfamiliar symbols, missing or conflicting scale, low-quality scans, conflicting documents, and unsupported systems.
- Keep low-voltage systems outside automated Division 26 totals.

**Release gate**

- A complete document set can be processed without silent failure.
- Every extracted quantity has visible source evidence.
- Unsupported or ambiguous work appears in a review queue instead of being guessed.

### Stage 2 — Estimator review and Excel export

**Objective:** Make machine output faster to verify than a manual takeoff.

**Capabilities**

- Overlay detected items and measured runs on blueprint pages.
- Approve, reject, add, reclassify, move, and edit quantities or lengths.
- Synchronize blueprint selections with takeoff-table rows.
- Explain each warning in plain language and identify the required estimator action.
- Prevent completion while unresolved critical issues remain.
- Record the original result, every correction, reviewer, and timestamp.
- Export approved takeoff data to Excel by system, floor, sheet, item, unit, status, and source.
- Measure processing time, active review time, and estimated manual time.

**Release gate**

- Web and Excel totals match exactly.
- Corrections remain auditable after reopening a project.
- Design-partner estimators complete representative reviews faster than their manual workflow.

### Stage 3 — Accuracy improvement program

**Objective:** Improve supported categories without hiding poor performance behind a single average.

**Evaluation segments**

- Project type
- Electrical system
- Item category
- Vector versus scanned drawing
- Drawing quality and completeness
- New construction versus renovation
- Counted item versus measured run

**Metrics**

- **Count accuracy:** difference between generated and estimator-approved quantities.
- **Length variance:** percentage difference from estimator-approved measured length.
- **Recall:** required scope captured by the system.
- **Precision:** generated items confirmed as valid.
- **Critical omission rate:** safety-, code-, or cost-significant items omitted.
- **Review effort:** corrections and active minutes required per sheet.

**Release gate**

- At least 95% count accuracy for each category advertised as supported.
- Measured quantities within ±5% for drawing conditions advertised as supported.
- No severe regression on any previously supported benchmark segment.
- Accuracy claims name the project types, item categories, and drawing conditions evaluated.

### Stage 4 — NECA labor hours

**Objective:** Convert approved quantities into reproducible labor hours.

**Capabilities**

- Map normalized items and assemblies to properly licensed NECA labor-unit data.
- Keep NECA reference data outside generative model prompts and outputs.
- Calculate labor deterministically:

  `approved quantity × NECA labor unit × project adjustment = labor hours`

- Support permitted labor-unit difficulty levels and contractor-defined adjustments for height, congestion, productivity, crew mix, overtime, and project conditions.
- Display the quantity, labor unit, adjustment, rationale, and result for every calculation.
- Compare generated hours with estimator-approved historical labor breakdowns.

**Release gate**

- Every labor hour traces to an approved quantity, licensed labor unit, and explicit adjustment.
- The design partner agrees on an acceptable labor variance before public claims are made.
- Benchmark reporting separates quantity errors from labor-mapping and adjustment errors.

### Stage 5 — Localized material and labor cost

**Objective:** Produce an auditable budget estimate while distinguishing general prices from bid-grade prices.

**Capabilities**

- Use the project address or ZIP code to select regional defaults.
- Support company settings for wages, payroll burden, benefits, crew rates, waste, tax, equipment, overhead, and profit.
- Support project-level overrides without changing company defaults.
- Load licensed localized cost data for budget estimates.
- Accept company price lists, supplier price files, and later direct pricing integrations.
- Apply the following price precedence:

  1. Project-specific supplier quote
  2. Current company or supplier price
  3. Localized regional baseline
  4. Estimator-entered allowance

- Label every price by source, geography, effective date, and verification status.
- Present a cost range when only generalized prices are available.

**Release gate**

- Labor and material subtotals reproduce from stored inputs.
- Overrides and their authors are visible in the audit history.
- The interface never presents regional baseline pricing as supplier-verified pricing.

### Stage 6 — Complete bid workflow

**Objective:** Turn an approved takeoff into an estimator-approved bid package.

**Capabilities**

- Combine quantities, labor hours, wages, material, equipment, allowances, taxes, overhead, and profit.
- Break down results by system, floor, sheet, item class, and cost code.
- Compare drawing revisions and show additions, deletions, and quantity changes.
- Generate draft assumptions, exclusions, alternates, clarifications, and proposal summaries.
- Require estimator approval before marking any estimate final.

**Release gate**

- All estimate totals reconcile to their underlying quantities, hours, rates, and adjustments.
- Revision comparisons do not double-count superseded sheets.
- Final approval records the estimator, timestamp, document revision set, and unresolved allowances.

## 4. Accuracy Policy

“95% accurate” is not a single product metric. The platform must report counts, lengths, scope capture, labor, and cost independently.

| Result | Initial target | Required qualification |
|---|---:|---|
| Supported counted materials | At least 95% | Reported by category and project segment |
| Supported measured materials | Within ±5% | Only when drawing scale and routing evidence are sufficient |
| Scope recall | Report separately | Omissions cannot be offset by extra items |
| False positives | Report separately | Incorrect additions cannot be offset by omissions |
| Labor hours | Agreed benchmark variance | Compared only after quantities are approved |
| Generalized cost | Range, not ±5% promise | Must display source and effective date |
| Unsupported work | No accuracy claim | Must be flagged for manual review |

Confidence labels are workflow signals, not accuracy claims. Only comparison with estimator-approved ground truth establishes accuracy.

## 5. Core Information Model

### Project

- Name, customer, address, ZIP code, bid date, project type, and classification confidence
- Uploaded document set and active revision set
- Company profile and project-specific overrides
- Processing, review, and approval status

### Document and sheet

- Document type, filename, revision, issue date, and supersession state
- Sheet number, title, discipline, page index, detected scale, and quality warnings

### Takeoff item

- Normalized catalog item and source description
- Quantity or measured length and unit
- System, floor, area, sheet, and drawing coordinates
- Source evidence and extraction method
- Review label: Ready to review, Needs attention, Missing information, or Estimator approved
- Original value, approved value, reviewer, notes, and correction history

### Labor calculation

- Approved takeoff item or assembly
- Licensed NECA reference and labor unit
- Difficulty selection and explicit project adjustments
- Calculated hours and estimator override history

### Price record

- Item, unit price, source type, source name, geography, effective date, and verification status
- Company and project overrides with audit history

## 6. Validation Matrix

Test every release against:

- Vector and scanned PDFs
- Rotated pages, mixed sizes, and low-resolution sheets
- Known and unknown project types
- Missing legends or missing scales
- Multiple scales on one sheet
- Symbol variants, overlapping marks, and repeated plans
- Equipment, fixture, and panel schedules
- Conflicts between drawings and specifications
- Duplicate, revised, and superseded sheets
- Unfamiliar symbols and excluded low-voltage systems
- Blueprint/table synchronization
- Web/Excel total reconciliation
- Saved corrections and audit history
- First-time estimator usability

## 7. Pilot Operating Model

- Begin with one design-partner contractor in the Memphis–Chattanooga region.
- Accept every commercial bid the contractor is willing to test.
- Classify results after upload and build benchmark cohorts as data accumulates.
- Review all takeoffs with an estimator before using them in a bid.
- Conduct a brief post-project review covering errors, time saved, confusing interactions, and missing scope.
- Promote categories from experimental to supported only after they pass their release gate on untouched projects.

## 8. Product Risks and Controls

| Risk | Control |
|---|---|
| A plausible but incomplete takeoff | Source-linked results, recall testing, and mandatory review |
| Different symbols across engineers | Legend extraction, project-specific symbol mapping, and unknown-symbol queue |
| Incorrect drawing scale | Scale validation and manual confirmation before length totals |
| Superseded drawings counted twice | Explicit active revision set and revision comparison |
| NECA licensing misuse | Licensed integration and deterministic access controls |
| Volatile material prices | Source/date labels, precedence rules, and estimate ranges |
| New project types weaken averages | Segmented benchmarks and category-specific claims |
| Technology-averse users abandon the tool | Guided workflow, plain language, familiar tables, and usability testing |

## 9. Immediate Next Steps

1. Secure the first blueprint/specification set and any related takeoff breakdown.
2. Define the normalized catalog for the first observed Division 26 scope.
3. Create the benchmark annotation and comparison format.
4. Prototype document ingestion and estimator review before labor or pricing.
5. Measure accuracy and review time on each new project.
6. Add NECA labor only after takeoff results meet the agreed gate.

