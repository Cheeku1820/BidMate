# Claude Design Handoff: Electrical Estimating Desktop App

## 1. Assignment

Design a high-fidelity desktop web application for electrical subcontractors who estimate commercial construction projects from blueprints and specifications.

The application converts uploaded construction documents into a machine-generated Division 26 electrical takeoff. An estimator must review every result, resolve important warnings, and approve the takeoff before export.

Create a coherent product design—not a marketing site, and not a product whose front door is a chat interface. The blueprint review workspace is the primary experience. A conversation panel sits alongside it on every screen, available whenever the estimator wants it, as an additional way to give and receive context rather than as the way the work gets done.

## 2. Users and Design Objective

### Primary user

An electrical estimator or contractor who understands construction documents but may be uncomfortable with unfamiliar software. The user may work in spreadsheets and existing estimating tools daily but should not need to understand artificial intelligence.

### Design objective

Make a complicated estimating workflow feel guided, safe, and familiar while preserving the information density professionals need.

The design should communicate:

- **Trust:** Every result shows where it came from.
- **Control:** The estimator can correct any result.
- **Clarity:** Important issues are stated in plain construction language.
- **Progress:** The user always knows what is finished and what remains.
- **Safety:** Uncertain or unsupported work is never presented as confirmed.

## 3. Product Language

Use “automatically detected,” “found,” or “suggested.” Avoid “the AI thinks,” model names, prompts, tokens, and unexplained confidence percentages.

Use these four review labels consistently:

| Label | Meaning | Color role |
|---|---|---|
| Ready to review | The item has sufficient evidence but has not been approved | Blueprint blue |
| Needs attention | Conflicting or uncertain information requires a decision | Amber |
| Missing information | Required evidence such as scale or legend is absent | Red |
| Estimator approved | A person confirmed the result | Green |

Every warning must answer:

1. What was found?
2. Why does it need attention?
3. What should the estimator check or change?
4. Which sheet, schedule, or specification contains the evidence?

Example:

> **Scale needs confirmation**  
> E2.1 contains two scale labels, so measured conduit lengths may be incorrect. Select the scale for the warehouse plan before approving its measured items.

## 4. Information Architecture

Use a persistent left application navigation with text labels and icons:

- Projects
- Accuracy
- Company settings
- Help

Within a project, the estimator must always see where they are, what is finished, and what the next primary action is. Do not hide required steps in menus.

**The six-step indicator this section originally specified has been superseded.** It read:

> 1. Project details 2. Documents 3. Confirm drawings 4. Process takeoff 5. Review 6. Export

That was written before the workspace model in [`docs/superpowers/specs/2026-08-16-bidmate-frontend-product-design.md`](superpowers/specs/2026-08-16-bidmate-frontend-product-design.md) §4.2, which the product is now built against. Three incompatible enumerations of the same workflow briefly shipped together — a "step 1 of 6" subtitle, seven project stages in `src/lib/projectStage.js`, and thirteen workspaces in the project navigation — so an estimator was told they were on step 1 of 6, landed on a 13-tab nav, and read a stage name from a seven-value vocabulary.

The subtitle was removed rather than reconciled, because inventing a sixth thing to make the number true would have been the wrong repair. What governs now:

- **Thirteen workspaces** in the project navigation (frontend design spec §4.2) — the places an estimator can go.
- **Seven project stages** in `src/lib/projectStage.js` — `setup`, `documents`, `processing`, `review`, `pricing`, `export`, `complete` — reported on the dashboard and the project overview as where the project *is*. This is a separate axis from the four review labels, which describe items rather than projects.

A numbered progress indicator may return, but only once it counts something that exists.

## 5. Required Screens

### Screen A — Projects dashboard

**Purpose:** Help an estimator find existing work and start a new estimate.

**Layout**

- Page title: “Projects”
- Primary button: “New project”
- Search field with visible label
- Filter chips: All, Processing, Needs review, Ready to export, Complete
- Project table or large list rows

**Project columns**

- Project name
- Customer
- Location
- Bid date
- Current stage
- Review progress
- Last updated
- Primary row action: “Open project”

**Empty state**

- Heading: “Create your first estimate”
- One-sentence explanation
- Primary action: “New project”
- Secondary action: “See how it works”

### Screen B — Create project

**Purpose:** Collect only the information needed to organize and localize the estimate.

**Fields**

- Project name, required
- Customer, optional
- Project address, required
- Bid due date, optional
- Building type, optional, with “Not sure” available
- Internal project number, optional

Use a single-column form with short helper text. Do not expose labor, pricing, or advanced processing settings here.

**Actions**

- Primary: “Continue to documents”
- Secondary: “Save and exit”

### Screen C — Upload documents

**Purpose:** Upload and classify source documents without making the user organize every sheet manually.

**Layout**

- Large drag-and-drop area with “Choose files” button
- Accepted file description: PDF drawings, specifications, schedules, addenda, and scope documents
- Uploaded-file list showing filename, file type, size, upload state, and remove action
- Editable document-type dropdown: Drawings, Specifications, Addendum, Scope, Other

**States**

- Uploading: progress per file
- Uploaded: clear completion state
- Duplicate: explain which file appears duplicated
- Failure: plain-language cause and retry action
- Password protected: request an unlocked document

**Actions**

- Primary: “Review detected drawings”
- Secondary: “Save and exit”

### Screen D — Confirm detected information

**Purpose:** Let the estimator correct document interpretation before takeoff processing.

**Summary cards**

- Project type: detected value or “Not sure”
- Electrical sheets: count found
- Drawing revisions: latest set and conflicts
- Legends and schedules: count found
- Scale status: confirmed, mixed, or missing

**Electrical sheet table**

- Include checkbox
- Sheet number
- Sheet title
- Detected discipline
- Revision
- Scale
- Status
- “View sheet” action

Use simple actions labeled “Correct” and “Change.” Show a separate “Needs attention” section above the table for duplicate revisions, missing scales, or uncertain disciplines.

**Actions**

- Primary: “Start takeoff”
- Secondary: “Back to documents”

### Screen E — Processing status

**Purpose:** Explain lengthy document processing and allow the user to leave safely.

**Content**

- Overall progress with descriptive stages rather than a fabricated precise time
- Per-sheet states: Waiting, Reading sheet, Finding electrical items, Checking schedules, Complete, Needs attention
- Message: “You can leave this page. We’ll save your progress.”
- Completed sheets remain visible if another sheet fails

**Failure behavior**

- Name the affected document or sheet
- Explain whether the rest of the project completed
- Offer “Retry sheet,” “Replace file,” or “Continue to review” when safe

### Screen F — Blueprint review workspace

**Purpose:** Review source-linked takeoff results. This is the product’s main screen.

#### Persistent top bar

- Back to projects
- Project name and revision set
- Review-status label
- Saved status with timestamp
- Undo and redo with text tooltips
- Help
- Primary action: “Finish review”

#### Left panel: documents and sheets

- Search sheets
- Filter: All sheets, Electrical, Needs attention, Reviewed
- Scrollable sheet thumbnails
- Sheet number and title
- Revision badge
- Warning count
- Reviewed indicator
- Collapse control

#### Center: blueprint canvas

- Maximize available workspace
- Zoom in/out, fit page, pan, rotate, and search
- Page scale and scale-confirmation control
- Layer toggles: Detected items, Approved items, Rejected items, Measurements, Warnings
- Color-coded markers that remain legible without hiding blueprint information
- Selecting a marker selects its takeoff row and opens item details
- Measurement tools: linear run, polyline run, count region, and calibration
- Clear legend for overlay colors and symbols

#### Right panel: selected item

- Review label
- Normalized item name
- Source drawing description
- Quantity or measured length and unit
- System and category
- Sheet and location
- Source evidence with “View evidence” action
- Plain-language warning when applicable
- Editable classification and quantity
- Notes field
- Primary item action: “Approve item”
- Secondary actions: Edit, Reject, Delete
- Navigation: Previous item and Next item

When nothing is selected, show review progress and the next recommended issue instead of an empty panel.

#### Bottom summary drawer

- Collapsed by default but always visible as a summary strip
- Items approved
- Items remaining
- Warnings
- Missing information
- Current approved quantity total
- Expand action opens system-level totals

#### Finish-review behavior

Selecting “Finish review” opens a review summary. Critical unresolved issues block completion and link directly to the affected sheet. Noncritical allowances may remain only after the estimator acknowledges them.

### Screen G — Takeoff table

**Purpose:** Provide a spreadsheet-familiar view of the same takeoff shown on the blueprint.

**Controls**

- Search
- Filters for system, category, sheet, floor, and review label
- Group by system, sheet, floor, or material
- Sort and resize columns
- Column visibility control
- Blueprint/table view toggle

**Columns**

- Review status
- Item
- Description
- System
- Quantity
- Unit
- Sheet
- Source
- Notes

Clicking a row opens the associated sheet and centers its marker. Editing a value updates the blueprint view and audit history. Bulk approval is available only for Ready to review items; it is never available for Needs attention or Missing information.

### Screen H — Export preview

**Purpose:** Confirm exactly what will leave the platform.

**Content**

- Project and revision summary
- Approved totals by system
- Remaining acknowledged allowances
- Excluded scope statement
- Export columns preview
- File name

**Actions**

- Primary: “Export Excel”
- Secondary: “Return to review”

The exported workbook must match the approved on-screen totals exactly and include source sheet references.

### Screen I — Accuracy comparison

**Purpose:** Compare the platform takeoff with an estimator-approved reference without reducing performance to one misleading number.

**Sections**

- Project and benchmark-set filters
- Count accuracy by category
- Length variance by system
- Missing items
- Incorrect additions
- Review time
- Drawing conditions and known limitations

Use tables and simple bar charts. Always show sample size. Do not show a 95% badge unless the displayed category and cohort passed the defined threshold.

### Screen J — Company settings

Use tabs with plain-language introductions:

- Company profile
- Labor rates
- Labor adjustments
- Material pricing
- Waste and markup
- Export preferences

Show each value’s source and last-updated date. Clearly distinguish a company default from a project override. Do not include these settings in initial project creation.

### Screen K — Project settings

- Project details and address
- Active drawing revision set
- Scale confirmations
- Labor and pricing overrides, when those stages become available
- Audit history

Every override must offer “Restore company default.”

## 6. Key Interaction Rules

- Autosave every edit and display “Saving…” followed by “Saved [time].”
- Provide undo for add, edit, approve, reject, delete, and reclassification actions.
- Require confirmation before deleting source documents, discarding corrections, or replacing an active revision set.
- Preserve completed work if one document fails.
- Open source evidence in context; never send the estimator hunting through the document.
- Keep blueprint markers and table rows synchronized in both directions.
- Do not allow a superseded sheet to contribute to current totals.
- Allow unfamiliar symbols to remain unclassified and visible in the review queue.
- Use contextual help panels, not disruptive tutorials or chat popups.
- Provide a conversation panel the estimator can open on any screen, to supply context the drawings do not carry and to answer questions raised during review. It anchors to the current selection or to a point on the drawing. It proposes changes for a person to apply and never approves anything itself. Every action available in it is also available through the structured interface.

## 7. Visual Direction

### Personality

Professional, dependable, precise, and approachable. It should feel like a modern estimating instrument built for daily work—not a futuristic AI demonstration.

### Color

- Neutral gray and warm off-white surfaces
- Blueprint blue for primary actions, selection, and Ready to review
- Green only for estimator-approved content
- Amber for Needs attention
- Red only for Missing information, conflicts, and blocking errors
- Do not rely on color alone; pair every status with text and an icon

### Typography

- Highly legible sans-serif typeface
- 16px default body text where practical
- Slightly smaller table text is permitted only with comfortable row height
- Use tabular numerals for quantities, hours, and costs
- Avoid all-caps headings and decorative typography

### Density and components

- Use familiar buttons, labeled icons, tabs, tables, filters, drawers, and confirmation dialogs
- Keep primary actions visually obvious and use one primary action per screen
- Provide generous spacing in setup screens and controlled professional density in the review table
- Keep touch targets at least 40×40px even though the first release is desktop only
- Avoid excessive cards, gradients, glass effects, animation, and hidden hover-only controls

## 8. Accessibility

- Meet WCAG 2.2 AA color contrast.
- Provide visible keyboard focus states.
- Support keyboard navigation through sheets, markers, table rows, and item-review actions.
- Associate every form field with a persistent visible label.
- Provide text alternatives for status icons and blueprint markers.
- Do not communicate status using color alone.
- Respect reduced-motion settings.
- Keep error messages adjacent to the affected field or document.

Recommended shortcuts, with a visible shortcut reference:

- `A`: Approve selected item
- `E`: Edit selected item
- `R`: Reject selected item
- `J` / `K`: Next / previous review item
- `+` / `-`: Zoom
- `0`: Fit page
- `Cmd/Ctrl + Z`: Undo

Do not activate single-key shortcuts while the user is typing in a field.

## 9. Responsive Boundary

Design for desktop widths of 1280px and above, optimized at 1440px. The blueprint workspace may show a clear “Use a larger screen to review drawings” message below the supported width. Mobile layouts are not required.

## 10. Required States

Create component and screen variants for:

- Empty
- Initial loading
- Active processing
- Partial processing success
- Complete processing
- Upload failure
- Unsupported document
- Missing scale
- Conflicting revision
- Unknown symbol
- No search results
- Unsaved edit
- Saved
- Offline or connection interrupted
- Permission denied
- Export ready
- Export failure

Error copy must explain the user’s recovery action. Never use “Something went wrong” by itself.

## 11. Prototype Scenarios

The clickable prototype must demonstrate these complete paths:

### Path 1 — First project

Projects → New project → Enter details → Upload drawings/specifications → Confirm detected sheets → Start takeoff → Processing → Blueprint review.

### Path 2 — Resolve uncertainty

Open a Needs attention item → View source evidence → Correct its classification and quantity → Approve it → Observe updated progress and table row.

### Path 3 — Missing scale

Open a blocking scale warning → Calibrate or select the correct scale → Recalculate measured items → Clear the warning.

### Path 4 — Revision conflict

Open conflicting sheets → Select the active revision → Confirm the older sheet is superseded → Verify it no longer contributes to totals.

### Path 5 — Export

Finish review → Resolve or acknowledge remaining issues → Preview approved totals → Export Excel.

## 12. Design Acceptance Criteria

- A first-time user can create a project, upload documents, and reach processing without training.
- The current workflow stage and next primary action are evident on every setup screen.
- The blueprint remains the largest element in the review workspace.
- Selecting an item from either the blueprint or table reveals the same item details.
- The difference between unreviewed, uncertain, missing, and approved work is unmistakable.
- Every warning includes evidence and a clear recovery action.
- Critical unresolved issues visibly block Finish review.
- Users can undo common review actions and see save status.
- The Excel export preview matches approved takeoff totals.
- The design remains usable at 1280px without hiding required actions.
- Screens include empty, loading, warning, partial-failure, and export states.
- No critical workflow *depends on* a chat interface, hidden menu, unexplained icon, hover-only control, or unexplained confidence percentage. The conversation panel is available on every screen and an estimator may work through it as much as they like — the requirement is that a structured path exists alongside it, so a review completed with the panel closed reaches the same end state.

## 13. Deliverables Requested From Claude Design

Provide:

1. A desktop design system page with color, typography, spacing, buttons, fields, status labels, tables, dialogs, toasts, and blueprint markers.
2. High-fidelity screens A through K.
3. The five clickable prototype paths.
4. Responsive examples at 1440px and 1280px for the blueprint workspace.
5. Empty, loading, warning, partial-failure, and export states.
6. Annotated interaction notes for blueprint/table synchronization, autosave, undo, revision handling, and Finish review blocking behavior.

