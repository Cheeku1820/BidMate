# BidMate Frontend Product Design

**Date:** August 16, 2026  
**Status:** Approved design  
**Product:** Desktop web application for electrical subcontractor estimating

## 1. Purpose

BidMate turns commercial construction documents into a traceable electrical takeoff and estimate. The frontend must help estimators upload evidence, verify machine findings, enter professional judgment, calculate labor and material costs, manage revisions, and export an approved bid.

The primary user understands electrical estimating but may be uncomfortable with unfamiliar technology. BidMate must feel like a dependable estimating instrument rather than an AI demonstration.

The design uses workflow-specific project workspaces:

1. Overview
2. Documents
3. Notes & assumptions
4. Blueprint takeoff
5. Takeoff spreadsheet
6. Assemblies
7. Labor
8. Material pricing
9. Estimate summary
10. Revisions
11. Final review
12. Export
13. Project settings

A persistent, scoped assistant is available throughout the application. It may explain, search, draft, and propose changes, but it never silently changes approved estimate data.

## 2. Product Principles

### 2.1 Evidence before automation

Every quantity, measurement, assumption, labor calculation, and material price must link to its source. Sources may include drawings, specifications, addenda, schedules, site photos, supplier quotes, company standards, or estimator-entered notes.

### 2.2 Structured tools remain authoritative

Chat assists the workflow but does not replace blueprints, tables, forms, or review controls. Final estimate state lives in structured project data rather than conversation history.

### 2.3 Human approval is mandatory

Assistant actions appear as proposals with scope, evidence, affected records, and before/after values. The estimator reviews and applies or cancels them.

### 2.4 Plain construction language

Use “found,” “suggested,” and “automatically detected.” Do not expose model names, prompts, confidence percentages, tokens, or processing internals.

### 2.5 One source of truth

The blueprint and takeoff spreadsheet are synchronized views of the same items. Labor, pricing, summary totals, and exports derive from approved structured records.

### 2.6 Explicit scope

Every note, conversation, rule, correction, or assistant proposal states whether it applies to an item, sheet, document, workspace, project, or company.

## 3. Status Vocabulary

The existing four labels govern every workspace:

| Label | Meaning | Completion behavior |
|---|---|---|
| Ready to review | Sufficient evidence exists, but an estimator has not approved it | Does not block navigation |
| Needs attention | Conflicting or uncertain information requires judgment | May continue only after explicit acknowledgment |
| Missing information | Required evidence such as a scale, legend, or price is absent | Blocks approval or finalization |
| Estimator approved | A person confirmed the result | Included in approved totals |

Status is always shown with color, icon, and text. Green is reserved for estimator-approved content. Unverified measurements also use dashed strokes.

## 4. Global Application Shell

### 4.1 Company navigation

- Projects
- Accuracy
- Company library
  - Notes and standards
  - Assemblies
  - Labor
  - Material pricing
- Integrations
- Company settings
- Help

Use a persistent left navigation with icons and text labels. Essential destinations may not be hidden in icon-only menus.

### 4.2 Project navigation

Inside a project, display the workflow workspaces in the order defined in Section 1. The current stage, completed stages, and unresolved blockers remain visible.

### 4.3 Persistent top bar

- Project name and active revision set
- Current workspace
- Save state: Saving…, Saved [time], or Couldn’t save — retrying
- Undo and redo
- Assigned reviewers/presence
- Help
- Workspace-specific primary action
- Ask BidMate toggle

All edits autosave. There are no ordinary save buttons.

### 4.4 Assistant drawer

“Ask BidMate” opens a resizable drawer on the right. It is always available but does not permanently reduce blueprint or spreadsheet space when closed.

The drawer includes:

- Visible scope selector
- Current context summary
- Conversation history for that context
- Evidence citations
- Text input and file/image attachment where permitted
- Proposed-action cards
- Recent applied actions with undo links

Available scopes:

- Selected item or rows
- Current sheet
- Current document
- Current workspace
- Entire project
- Company standards

The application suggests the most specific relevant scope. The user may change it before sending.

## 5. Company-Level Screens

### 5.1 Projects dashboard

The home page shows all bids in a familiar table.

**Columns**

- Project name and number
- Customer/general contractor
- Location
- Bid due date
- Assigned estimator
- Current stage
- Review progress
- Outstanding warnings
- Last updated
- Open-project action

**Controls**

- New project
- Search
- Filters: Active, Processing, Needs review, Ready to export, Complete, Archived
- Sort by bid date, update date, estimator, customer, or project name
- Saved views

Optional summary metrics are limited to active bids, bids due soon, and review backlog. They must support action rather than decorate the page.

The assistant may answer portfolio questions but cannot mutate an estimate until a project and scope are selected.

### 5.2 Accuracy

Report performance by project type, drawing quality, electrical system, and item category. Show sample size with every metric.

- Count accuracy
- Measured-length variance
- Missed required items
- Incorrect additions
- Critical omission rate
- Review time
- Corrections per sheet
- Supported versus experimental categories

Do not present a single overall accuracy score that hides weak segments.

### 5.3 Company library

Centralize reusable, versioned estimating knowledge:

- Company notes and standards
- Installation assemblies
- Wage classes and crew compositions
- Labor adjustments
- Preferred manufacturers
- Price lists
- Waste factors
- Substitution rules

Changes affecting future bids require an authorized role and record the author, effective date, and prior version.

### 5.4 Integration center

Show each integration’s connection state, data authority, last synchronization, and recovery action.

**Initial capabilities**

- Excel export
- PDF drawing/specification ingestion
- Site-image upload
- Licensed NECA labor data
- Regional pricing source
- Supplier quote upload

**Later capabilities**

- Electrical pricing services such as TRA-SER
- Supplier price files and distributor connections
- Procore or Autodesk Construction Cloud
- SharePoint or Google Drive
- Accounting/estimating systems
- SSO

## 6. Project Creation and Overview

### 6.1 New project

Use a short guided form:

- Project name and internal number
- Customer/general contractor
- Address and ZIP code
- Bid due date
- Assigned estimator
- Optional construction type, including Not sure
- Starting company profile

Advanced labor and pricing settings do not appear during creation.

### 6.2 Project overview

This is the project home and return point.

- Project details and bid deadline
- Current workflow stage
- Processing state
- Review progress
- Unresolved warnings
- Recently added documents
- Estimate snapshot
- Assigned team members
- Recent activity
- Continue where you left off

Every card links to the records behind it.

## 7. Documents Workspace

### 7.1 Supported evidence

- Blueprints and schedules
- Specifications
- Addenda
- Scope letters
- Site photographs
- Supplier quotes
- Existing spreadsheets
- Other supporting documents

### 7.2 Upload and classification

Provide drag-and-drop upload with progress, type, size, revision, issue date, and remove/replace actions. Users may correct the detected document type.

Handle duplicate, unsupported, password-protected, and failed files with specific recovery instructions. Successfully processed files remain available when another file fails.

### 7.3 Evidence extraction

**Drawings**

- Sheets and disciplines
- Revisions and supersession
- Scales
- Legends and symbols
- Schedules and notes
- Cross-sheet references

**Specifications**

- Division 26 requirements
- Approved manufacturers
- Installation and testing requirements
- Alternates and substitutions
- Drawing conflicts

**Site photos**

- Caption, date, area, and uploader
- Suggested existing conditions
- Access, height, congestion, demolition, and equipment-location observations
- Links to sheets, takeoff items, or assumptions

Photo observations remain suggestions until confirmed by an estimator.

### 7.4 Document review

Before takeoff processing, confirm:

- Active revision set
- Included electrical sheets
- Applicable specifications and addenda
- Duplicate and superseded exclusions
- Site-photo area associations
- Missing legends or scales

Cross-document conflicts link directly to both sources.

## 8. Notes & Assumptions Workspace

The workspace is the project’s shared memory and includes free-form notes plus structured estimating inputs.

### 8.1 Note scopes

- Company standard
- Project
- Document
- Sheet
- Specification section
- Site photo
- Takeoff item
- Labor or material row
- Revision/addendum

### 8.2 Note categories

- Scope clarification
- Estimating assumption
- Exclusion
- Existing condition
- Labor consideration
- Material requirement
- Pricing note
- RFI needed
- Customer instruction
- Company rule

### 8.3 Note record

- Title and content
- Scope and category
- Author and timestamp
- Linked evidence
- Current, temporary, confirmed, or superseded state
- Calculation effect

Calculation effects:

1. Reference only
2. Use in this estimate after review
3. Save as a company standard after authorized approval

Chat may draft or convert a conversation into a note. The user confirms scope, category, and calculation effect.

## 9. Blueprint Takeoff Workspace

### 9.1 Layout

**Left panel**

- Drawing/schedule thumbnails
- Search
- Revision indicators
- Filters: All, Electrical, Needs attention, Reviewed
- Related specifications and site photos

**Center canvas**

- Rendered PDF page
- Pan, zoom, rotate, search, fit page
- Scale selection and two-point calibration
- Count, linear, polyline, and region tools
- Layers: Detected, Approved, Rejected, Measurements, Warnings
- Revision overlays
- Electrical drafting symbols

**Right item panel**

- Status
- Normalized classification and source description
- Quantity or measured length
- Source sheet and coordinates
- Legend/schedule evidence
- Specification, note, and photo references
- Warning explanation
- Approve, edit, reject, delete, and add-note actions

The assistant drawer may open beside the item panel at large widths or temporarily replace it at smaller supported desktop widths.

### 9.2 Takeoff actions

- Approve a detected item
- Correct classification or quantity
- Add a missed item
- Reject a duplicate
- Draw or edit a measured route
- Link evidence
- Add a scoped clarification
- Find similar items
- Propose a correction across selected scope

Missing-information items cannot be approved until the required evidence is supplied.

### 9.3 Canvas invariants

- Marker glyph communicates item type.
- Marker ring communicates review status.
- Badge communicates warning presence.
- Layer visibility never changes totals.
- Superseded sheets never contribute to totals.
- Local and remote selections use distinct treatments.

## 10. Takeoff Spreadsheet

The built-in spreadsheet and blueprint are two views of the same records.

### 10.1 Columns

- Review status
- System
- Item/assembly
- Description
- Manufacturer/model requirement
- Quantity and unit
- Waste factor
- Approved quantity
- Floor/area
- Source sheet
- Specification reference
- Notes
- Last edited by

### 10.2 Behavior

- Search, sort, filter, and group
- Resize, freeze, hide, and reorder columns
- Group by system, floor, sheet, material, or assembly
- Multi-row selection
- Copy/paste and fill-down
- Permitted formulas for derived fields
- Undo/redo
- Change history
- Saved custom views
- Excel export

Source-controlled fields require an explicit correction action. Manual overrides require a reason and retain the calculated value for comparison.

Selecting a row opens and centers its blueprint marker. Selecting a marker highlights and scrolls to its row.

### 10.3 Takeoff completion

Summarize approved quantities, unreviewed items, missing information, allowances, excluded systems, manual overrides, and revision/specification conflicts. Blocking items link to their sheet or row.

## 11. Assemblies Workspace

Map approved takeoff items to installation assemblies containing material components, fittings, conductors, waste, and labor relationships.

Users may:

- Apply a company-standard assembly
- Modify it for this project
- Create a new project assembly
- Apply it to selected takeoff rows
- View all blueprint items using it
- Promote an authorized version to the company library

Assistant suggestions show every component and affected item before application.

## 12. Labor Workspace

Use a spreadsheet-oriented calculation view.

### 12.1 Columns

- Takeoff item/assembly
- Approved quantity
- Licensed NECA reference
- Labor-unit difficulty
- Base hours per unit
- Base labor hours
- Adjustment factors
- Adjusted labor hours
- Crew mix
- Blended labor rate
- Extended labor cost
- Notes and override reason

Calculation:

`approved quantity × NECA labor unit × explicit adjustments = labor hours`

### 12.2 Adjustments

- Height
- Congestion
- Restricted access
- Occupied space
- Shift/overtime
- Weather
- Repetition/productivity
- Prefabrication
- Site conditions
- Company productivity

NECA data must come from a licensed source and deterministic calculations. The assistant may explain or propose mappings but may not invent labor units.

## 13. Material Pricing Workspace

### 13.1 Columns

- Material
- Manufacturer/equivalent
- Quantity and unit
- Waste-adjusted quantity
- Unit price
- Price source
- Effective date
- Location
- Tax and freight
- Extended cost
- Verification status
- Notes

### 13.2 Price precedence

1. Project supplier quote
2. Current company price
3. Supplier price file
4. Localized regional baseline
5. Estimator allowance

Every row visibly labels its source, date, and status: Supplier verified, Company price, Regional baseline, Allowance, or Stale price.

### 13.3 Supplier quotes

Upload PDF or spreadsheet quotes. BidMate proposes matches and shows unmatched lines, quantity differences, substitutions, freight, expiration, and exclusions. Approval updates prices while preserving the quote as evidence.

## 14. Estimate Summary

### 14.1 Totals

- Material cost
- Labor hours and cost
- Equipment/rentals
- Supplier/subcontractor quotes
- Allowances
- Direct cost
- Tax
- Overhead
- Profit
- Final bid amount
- Cost per square foot when area is known

### 14.2 Breakdowns

- System
- Floor/area
- Cost code
- Material class
- Drawing sheet
- Base bid/alternates
- Labor versus material
- Confirmed versus allowance

Every total drills into its contributing rows.

### 14.3 Scenarios

Create non-destructive scenarios for supplier choice, fixture package, overtime, labor factor, or value engineering. The assistant may compare scenarios but cannot replace the active estimate without confirmation.

## 15. Revisions and Addenda

Display:

- Active revision set
- New, superseded, and unchanged files
- Added, removed, and modified takeoff items
- Quantity, labor, and cost impact
- Approvals affected
- Potentially obsolete notes and assumptions

Superseded sheets remain browsable read-only and contribute nothing to active totals. The estimator decides whether approvals carry forward. Mid-review changes notify other active reviewers.

## 16. Final Review

The guided checklist confirms:

- Takeoff approval
- Missing-information resolution
- Acknowledged assumptions and exclusions
- Labor mappings
- Current prices or explicit allowances
- Supplier quote exceptions
- Tax, freight, overhead, and profit
- Active revision set
- Alternates
- Export reconciliation

Missing information blocks finalization. Needs-attention items may continue only through explicit acknowledgment and become visible allowances.

Final approval records the estimator, timestamp, active revisions, applied company settings, and unresolved allowances.

## 17. Export and Proposal

Available outputs:

- Excel estimate workbook
- Material takeoff
- Labor report
- Supplier RFQ list
- Assumptions/exclusions
- Revision-impact report
- Audit history
- PDF estimate summary
- Draft customer proposal

The user selects sections and previews them. Export totals must match approved on-screen totals exactly. The first release supports Excel export, not two-way Excel synchronization.

## 18. Settings and Permissions

### 18.1 Company settings

- Offices and operating areas
- Default taxes, overhead, and profit
- Branding/export preferences
- Wages, burden, benefits, and crews
- Productivity and overtime rules
- NECA configuration
- Preferred manufacturers and suppliers
- Price lists and waste factors
- Assembly library

### 18.2 Project settings

- Project details and address
- Active revision set
- Assigned estimators
- Labor adjustments
- Price, tax, freight, waste, overhead, and profit overrides
- Export preferences
- Audit history

Every project override provides Restore company default.

### 18.3 Roles

- Estimator
- Senior estimator
- Project administrator
- Company administrator
- Read-only reviewer

Only authorized roles may promote project knowledge into company standards or change organization-wide calculation defaults.

## 19. Assistant Behavior

### 19.1 Supported tasks

- Answer questions with document citations
- Explain findings, warnings, and calculations
- Search drawings, specifications, notes, photos, and quotes
- Compare documents and revisions
- Draft notes, assumptions, exclusions, and RFIs
- Propose item and bulk corrections
- Prepare spreadsheet rows and permitted formulas
- Suggest assemblies and adjustments
- Match supplier quote lines
- Navigate to evidence
- Summarize unresolved decisions

### 19.2 Proposed-action contract

Every mutation proposal displays:

- Plain-language action
- Selected scope
- Evidence consulted
- Affected record count
- Before/after values
- Quantity, labor, and cost impact
- Review affected records
- Apply
- Cancel

Large or cross-project changes require a dedicated review screen. Applying a proposal writes the same audit record as a manual edit.

### 19.3 Audit record

- User request
- Assistant interpretation
- Scope
- Evidence
- Proposed operations
- Approving user
- Before/after values
- Timestamp
- Undo reference

## 20. Error Handling and Recovery

- Preserve successful work when one file or sheet fails.
- Name the failed record and explain the recovery action.
- Never show “Something went wrong” without actionable detail.
- Autosave retries connection failures and makes offline state visible.
- Conflicting concurrent edits prompt users to compare versions rather than silently overwriting.
- Unknown symbols remain visible and unclassified.
- Missing scale blocks measured-item approval.
- Missing or stale prices become explicit warnings or allowances.
- Unsupported systems are excluded and labeled rather than guessed.

## 21. Accessibility and Usability

- Target WCAG 2.2 AA.
- Desktop support begins at 1280px and is optimized at 1440px.
- Use visible field labels and keyboard focus states.
- Do not communicate status by color alone.
- Use tabular numerals for quantities, hours, and costs.
- Provide large primary actions and at least 40×40px interactive targets.
- Support keyboard review actions without activating shortcuts inside text fields.
- Respect reduced-motion preferences.
- Keep contextual help outside chat as well.
- Use sentence case, plain language, and familiar spreadsheet patterns.

## 22. Data Flow and Boundaries

1. Project evidence enters through Documents.
2. Extraction creates source-linked findings and warnings.
3. Notes add scoped human knowledge without mutating calculations by default.
4. Blueprint and spreadsheet review produce approved takeoff records.
5. Assemblies map takeoff records to materials and labor relationships.
6. Labor calculations use licensed units and explicit adjustments.
7. Pricing uses source-labeled values and precedence rules.
8. Summary derives from approved records.
9. Revisions invalidate or preserve records through explicit review.
10. Final review gates exports.

Each workspace consumes the approved output of the preceding stage but may link back to original evidence. Changes upstream mark dependent calculations stale and require recalculation or review.

## 23. Testing and Acceptance Criteria

### 23.1 End-to-end workflows

- Create a project, upload drawings/specifications/photos, and begin processing without training.
- Correct document classifications and active revisions.
- Review an item in the blueprint and observe the spreadsheet update.
- Edit a spreadsheet quantity and open its blueprint source.
- Add a scoped note and control whether it affects calculations.
- Ask a scoped question and follow its evidence citation.
- Preview and apply an assistant bulk change.
- Map takeoff rows to an assembly and NECA labor.
- Apply a project labor adjustment with visible cost impact.
- Match a supplier quote to material rows.
- Compare estimate scenarios without changing the active estimate.
- Process an addendum without double-counting superseded sheets.
- Resolve final-review blockers and export reconciled Excel totals.

### 23.2 Invariants

- Hidden blueprint layers never change totals.
- Superseded sheets never contribute to active totals.
- Missing-information items cannot be approved.
- Bulk approval applies only to Ready to review items.
- Assistant actions never mutate data before approval.
- Blueprint and spreadsheet selections and values remain synchronized.
- Manual overrides retain original values and reasons.
- Company-standard promotion requires authorization.
- Every labor hour traces to quantity, labor unit, and adjustment.
- Every material price traces to source and effective date.
- Web and exported totals match exactly.

### 23.3 Usability

- First-time estimators can identify the next action on every workflow screen.
- Users can distinguish item, sheet, project, and company assistant scope.
- Users can recover from upload, processing, save, and export failures.
- Blueprint remains the dominant element in takeoff review.
- Common spreadsheet actions behave predictably.
- Critical actions have visible undo or confirmation.

## 24. Initial Release Boundary

The first release includes the complete workflow shell and manual-capable estimating workspaces, even where automation is limited.

Automated capability focuses first on core Division 26 takeoff. Users may manually enter or adjust assemblies, labor, pricing, notes, assumptions, and estimate totals. NECA and regional pricing depend on licensed sources. Excel export is included; two-way spreadsheet synchronization is excluded.

Human review remains mandatory for takeoff, assistant changes, labor adjustments, pricing overrides, revisions, and final approval.

