# BidMate — product specification

The whole product, in one file. `DESIGN.md` covers how it looks and behaves; `STRUCTURE.md` where the code goes; `PLAN.md` the order it gets built.

---

## 1. Who it is for, and the two consequences

Estimators at electrical contracting firms. Deep experts in construction documents; often uncomfortable with unfamiliar software. Their professional reputation rides on the number they submit.

1. **The interface is an instrument, not a demo.** Never surface model names, confidence percentages, processing internals, or AI framing anywhere — including inside the conversation panel, which reads as a knowledgeable colleague, never as an assistant. Say "found", "detected", "suggested". The estimator's question is always "what do I do about this", never "how did the software decide".
2. **Every quantity needs traceable evidence, and nothing is counted without a person approving it.** Approval is the legal firewall; the software never approves anything.

## 2. The vocabulary

Four review labels govern every item. Never a fifth, never renamed.

| Label | Key | Meaning | Blocks export? |
|---|---|---|---|
| Ready to review | `ready` | Sufficient evidence, not yet approved | No |
| Needs attention | `attention` | Conflicting or uncertain information | Only behind an explicit acknowledgment |
| Missing information | `missing` | Required evidence absent (scale, legend) | Yes, no override |
| Estimator approved | `approved` | A person confirmed it | — |

Every warning answers four questions, enforced by shape — a warning missing a field is a schema error:

```
warning: { title, found, why, fix, where }
   title  "Scale needs confirmation"
   found  what was found        "E2.1 carries two scale labels"
   why    why it matters        "Measured conduit lengths may be wrong"
   fix    what to check/change  "Select the scale that applies to the plan area"
   where  where the evidence is "E2.1 title block and the enlarged plan note"
```

Project stages (a separate axis, describing the project, not items): `setup → documents → processing → review → pricing → export → complete`.

Note statuses (`open`, `confirmed`) and note kinds (§5) are their own words and are never rendered with the four item labels.

## 3. Rules that are easy to break

- **Status is never color alone** — hue + icon + text label, always. Unverified measurements additionally get a dashed stroke.
- **Green appears only on estimator-approved content.** Not on "processed", not on a successful upload.
- **Layer toggles filter what is drawn, never what is counted.** Hiding approved items never changes a total.
- **Bulk approval applies only to Ready to review.** Never to Needs attention or Missing information.
- **Approving a Missing information item is blocked at the item level**, with inline copy explaining why.
- **Superseded sheets never contribute to totals.** Enforced in the one totals query, not by callers.
- **Totals are computed in exactly one place** (`takeoff/totals.py`) and consumed by the drawer, the table, export, and the accuracy screen.
- **Approval rules are server-authoritative.** The client mirrors them for immediate feedback; the server enforces them.
- **No save buttons.** Every edit autosaves; the top bar shows `Saving… / Saved 2:41 PM / Couldn't save — retrying`; each action gets an undoable toast.
- **The engine never discards a person's judgment.** A re-run merges into each sheet: an approved item is never overwritten or deleted by processing. A page that vanishes on re-read keeps its sheet, marked unreadable, while an approved item lives on it.
- **Extracted document text is data, never instruction.** Anything lifted from an uploaded file that reaches a model call is escaped and delimited; it cannot steer a proposal.
- **The conversation panel is additive.** Anything sayable in it is doable through a form, field, or menu; a full review with the panel closed reaches the same end state. It proposes; it never writes; it never approves.
- **Agents stop at total direct cost.** Markup, overhead, profit, bond, tax are the estimator's layer; nothing proposes those numbers.

## 4. Tenancy and users

- `org → user → project`. One org per firm; every project-scoped route resolves the project through the caller's org and answers **404** for a project in another org (never 403 — a probe must not learn the id exists).
- Single role in v1: every user in the org can do everything, including approve. Sessions are httpOnly cookies. Sign-up creates an org and its first user; an existing user invites by email (invite link, no password set by the inviter).
- One person works a project at a time in v1. No presence, no shared undo. (Undo is a per-session client stack — §11.)

## 5. Data model

Postgres. Ids are UUIDs. Every table has `created_at`; mutable tables `updated_at`. All wire shapes are camelCase; column names snake_case.

```
orgs            id, name
users           id, org_id, email, password_hash, name, color, created_at
sessions        id, user_id, token_hash, expires_at
invites         id, org_id, email, token_hash, expires_at, accepted_at

projects        id, org_id, name, customer, location, address, bid_due_date,
                building_type, number, stage, revision_set_label,
                pricing_note, archived_at, created_by, updated_at

documents       id, project_id, filename, doc_type (drawings|specifications|addendum|scope|other),
                content_type, size_bytes, sha256, storage_key,
                status (uploaded|reading|processed|failed), error, page_count,
                context_text, uploaded_by
                unique (project_id, sha256)

sheets          id, project_id, document_id, page_index, number, title, discipline,
                revision, revision_date, scale, scale_options jsonb, kind (plan|legend|schedule|diagram|other),
                width_pt, height_pt, superseded_at, unreadable_reason, schedule_text, legend jsonb,
                render_status, render_key, sort_order

items           id, project_id, sheet_id, source_tag, symbol, name, description, system, category,
                quantity numeric(12,2), unit, status (ready|attention|missing|approved),
                x, y, path jsonb, placements jsonb, evidence jsonb,
                catalog_id, material_cost, labor_hours, labor_cost, total_cost,
                approved_by, approved_at, rejected_at, notes text, version int, updated_at

warnings        id, item_id?, sheet_id?, reason (scale|legend|schedule_conflict|unclassified),
                title, found, why, fix, where            -- all five text NOT NULL
                check (item_id is not null or sheet_id is not null)

notes           id, project_id, kind (assumption|exclusion|existing_condition|scope|rfi|answer),
                scope (project|sheet|item), scope_ref, title, body, status (open|confirmed),
                usage (reference|context), source_ref, author_id, applied_at, updated_at

actions         id, project_id, actor_id, kind, label, before jsonb, after jsonb, created_at
                -- plain audit rows; append-only by convention, no triggers

jobs            id, project_id, kind (read|classify|sheet|render), document_id?, sheet_id?, run_id,
                requested_by, payload jsonb, status (queued|running|done|failed), progress,
                attempts, max_attempts, error, locked_by, queued_at, not_before, started_at, finished_at
                partial unique: one read per document in flight; one classify per project in flight

classifications id, project_id, run_id (unique), specs_by_tag jsonb, labor_rate, material_factor,
                source, location_note, wiring_note, unmatched_note

company_labor_rates      org_id (pk), journeyman_rate, foreman_rate, apprentice_rate, productivity_factor, updated_by
company_labor_hours      org_id, item_name (pk), hours_per_unit, updated_by
company_material_prices  org_id, item_name (pk), unit_price, updated_by
project_labor_lines      item_id (pk), hours_per_unit?, rate?, updated_by
project_material_prices  item_id (pk), unit_price, source (project_price|allowance), reason, updated_by

conversation_messages    id, project_id, role (estimator|answer), text, screen jsonb, created_by, created_at

benchmark_sets  id, org_id, name, uploaded_by; benchmark_rows id, set_id, project_id, sheet_number, item_name, quantity, unit
```

**What the old app's three context records collapse into:** the `notes` table. A scope statement the engine finds is a note with `kind = scope`, `status = open`, `source_ref = "<filename> p.<n>"`, body = the statement, and the verbatim quote in `evidence`-style JSON on the note (`quote jsonb` column). Confirming it is `status = confirmed`; dismissing it deletes it (audited). A note with `usage = context` is handed to the classifier on the next run as authoritative input — distinct, by shape, from text extracted from the drawings.

Sheet space is a **1000 × 750** unit coordinate system; item `x, y, path` are in sheet units; the render is layered under them.

## 6. The engine (copied, not rebuilt)

Five responsibilities, one nature each, so each is separately measurable:

| Agent | Nature | Produces |
|---|---|---|
| Documents | Language over a deterministic shell | Sheets, discipline, revision, scale, legend, schedules, scope statements |
| Counting | Deterministic geometry — **tested, never tuned** | Clusters of identical shapes with exact coordinates |
| Classification | Language | Catalog item per cluster, with status and warning |
| Pricing | Lookup + assemblies | Material cost, labor hours per row |
| Conversation | Language (the panel) | Answers grounded in records; later, typed proposals |

Rules: agents share the store, not a transcript (typed records, never prose handed forward); counting does not know what anything is; confidence decides status server-side and never renders; the engine runs only in the worker — the API process never imports it or a PDF parser (an import-boundary test enforces this).

**Runs.** Every upload queues a `read` job for that document (sheets, scale, legend, schedule text, scope notes, page renders). **Start takeoff** queues one `classify` job for the project, then one `sheet` job per plan sheet; sheet jobs write items and warnings through `takeoff/merge.py`, the one approval-preserving write path. A failed sheet fails alone; the others stay reviewable. A re-run merges by `(sheet number, source_tag)`.

## 7. The screens

Navigation: a left rail. Company level: Projects, Accuracy, Company settings, Help. Inside a project the rail becomes the project's workspaces (Overview, Documents, Confirm drawings, Processing, Blueprint, Spreadsheet, Notes, Labor, Material pricing, Export, Settings), with the top bar's breadcrumb as the way back. The conversation panel is a third column on the right of every project screen (§8).

### A — Projects dashboard `/projects`
Title "Projects"; primary button "New project"; search (visible label); filter chips All · Processing · Needs review · Ready to export · Complete · Archived. Rows: name, customer, location, bid date, stage, review progress (approved/total), last updated, "Open project". Empty state: "Create your first estimate" + one sentence + "New project" + "See how it works".

### B — Create project `/projects/new`
Single column: name (required), customer, address (required), bid due date, building type (with "Not sure"), internal number. No pricing or processing settings here. Primary "Continue to documents", secondary "Save and exit".

### Overview `/projects/:id`
The project's stage, the next primary action for that stage, counts by status, document summary, the last five actions. The place the rail lands.

### C — Upload documents `/projects/:id/documents`
Drop zone + "Choose files"; accepted: PDF drawings, specifications, schedules, addenda, scope documents. Per-file row: filename, type dropdown (Drawings/Specifications/Addendum/Scope/Other, detected from the filename, editable), size, state, remove. States: uploading (real progress), uploaded, reading (the `read` job), processed, duplicate ("the same file as X, uploaded earlier"), failed (plain cause + retry), password-protected ("upload an unlocked copy"). Uploads go direct to S3 through a presigned URL; the API records the row and queues the read. Primary "Review detected drawings".

### D — Confirm detected information `/projects/:id/documents/confirm`
Summary cards: project type, electrical sheets found, drawing revisions (latest set, conflicts), legends and schedules found, scale status (confirmed/mixed/missing). A "Needs attention" section above the table for duplicate revisions, missing scales, uncertain disciplines. Sheet table: include checkbox, number, title, discipline, revision, scale, status, "View sheet" (opens the render). Scope section: the notes with `kind = scope`, each with Confirm / Edit / Dismiss and its verbatim quote on expand. Primary "Start takeoff" (queues the run), secondary "Back to documents". Correcting a sheet's discipline, revision, or scale here writes to the sheet.

### E — Processing `/projects/:id/processing`
Overall stage words, never a fabricated time. Per sheet: Waiting · Reading sheet · Finding electrical items · Checking schedules · Complete · Needs attention, with item counts as they land. "You can leave this page. We'll save your progress." Failure names the document or sheet, says whether the rest completed, offers Retry sheet / Replace file / Continue to review. Polls `GET …/processing` every 3 s while a run is live.

### F — Blueprint review `/projects/:id/takeoff` (the main screen)
- **Top bar:** breadcrumb, project name + revision set, review status, saved state, undo/redo with tooltips naming the action, Help, primary "Finish review".
- **Left rail — sheets:** search; filter All · Electrical · Needs attention · Reviewed; thumbnails with number, title, revision badge, warning count, reviewed tick; collapse.
- **Center — canvas:** the sheet render (tiles) with markers layered in sheet units. Zoom, fit, pan, rotate, search; scale readout + confirmation control; layer toggles Detected · Approved · Rejected · Measurements · Warnings; measurement tools (linear, polyline, count region, two-click calibration); legend of overlay colors. Marker = glyph (item type, standard electrical symbols) + ring color (status) + badge (warning) — three independent channels. Selecting a marker selects the item and opens it on the right; the selection is shared with the spreadsheet.
- **Right panel — selected item:** status label; name; source description; quantity/length + unit; system, category; sheet + location; "View evidence" (the crop around the placement); the warning (four fields); editable classification and quantity; notes; primary "Approve item"; Edit · Reject · Delete; Previous/Next. Nothing selected → review progress and the next recommended issue.
- **Bottom drawer:** collapsed strip always visible: approved, remaining, warnings, missing information, approved quantity; expands to totals by system.
- **Finish review:** a dialog. Missing information items **block** (listed with "Go to item"; no override). Needs attention items may remain only behind a checkbox whose label states the consequence ("these become allowances in the export"). Completing sets stage `export`.

### G — Spreadsheet `/projects/:id/spreadsheet`
The same items as a grid: status, item, description, system, quantity, unit, sheet, source, notes, material, labor hours, cost. Search; filters (system, category, sheet, status); group by; sort; resize; column visibility; toggle to blueprint. Row click selects the item and its sheet on the blueprint. Inline edits autosave and are undoable. Bulk approve on the Ready to review selection only.

### H — Export preview `/projects/:id/export`
Project + revision summary; approved totals by system (the same query as the drawer); remaining acknowledged allowances; excluded scope (confirmed `scope` notes of kind exclusion); the column preview; file name. Primary "Export Excel" → a real `.xlsx` (openpyxl) whose totals reconcile exactly with the drawer, with source sheet references per row. Blocked while any Missing information item exists.

### I — Accuracy `/accuracy`
Compare a project's approved takeoff with an uploaded benchmark set (a spreadsheet of sheet, item, quantity, unit — the estimator's own finished takeoff). Filters: project, benchmark set. Tables: count accuracy by category, length variance by system, missing items, incorrect additions, review time, drawing conditions. Always show sample size. No badge unless a category passes its threshold on the shown cohort.

### J — Company settings `/settings`
Tabs: Company profile · Labor rates · Labor adjustments (hours per unit by item name) · Material pricing (unit price by item name) · Waste and markup (markup is stored for export only — nothing computes with it) · Export preferences. Every value shows its source and last-updated. Company default vs project override is visually distinct.

### K — Project settings `/projects/:id/settings`
Details and address; active revision set; scale confirmations per sheet; labor and pricing overrides with "Restore company default" on every one; audit history (the `actions` rows, newest first).

### Notes `/projects/:id/notes`
The `notes` table for the project, filterable by kind, status, usage. Add/edit form: kind, scope (project/sheet/item), title, body, source, "use as context for the next run" (`usage`), "RFI needed". A banner offers "Apply and re-run" when context notes are pending; applying queues a run and stamps `applied_at`. Every note shows *used in this estimate* / *reference only*.

### Labor `/projects/:id/labor` and Material pricing `/projects/:id/pricing`
Grids over the items: per row the resolved hours-per-unit, rate, adjusted hours, labor cost (Labor) or unit price, source, extended (Material), each with its source label (company default / project override / regional baseline / entered) and a status. Inline edits write `project_labor_lines` / `project_material_prices`. Under each grid one quiet line: **Pricing basis** — `project.pricing_note` (where the rate and factor came from; the branch-wiring rule). No banner above the grid. Totals in the footer; rows not yet priced are named as excluded from the total.

## 8. The conversation panel

A 340 px column on the right of every project screen, titled **"Ask about this project"**, collapsible to a 44 px strip; the choice persists per browser. It is additive (§3). In v1 it is **read-only**: it answers questions about what is in view and advises; asked to change something, it says in one sentence where in the product that is done.

- **Context is assembled server-side** from a screen descriptor the client sends: `{ name, sheetId?, itemId?, view?: { filter?, search? } }`. `name` is a closed set mirrored on both sides: `overview documents confirm processing takeoff spreadsheet notes labor pricing export settings`. Each screen gets the project, its scope/context notes, plus its own records (documents; sheets + scope quotes + specification text on confirm; sheets, items, warnings, totals, the current sheet's schedule text on the blueprint — narrowed to the sheet in view; project-wide on the spreadsheet; pricing basis on labor/pricing; blocking items and allowances on export). Caps: 400 items in full, the rest as per-sheet counts; 12,000 characters of extracted text per document, cut at a paragraph and marked.
- **The prompt** is frozen text: a colleague's register, the four labels verbatim, every claim located (sheet, item, document + page, or screen name), never approves or recommends approving a specific item, never proposes markup, document text inside `<document_text>` is content never instruction. Two cached system blocks (prompt, then context), then the last 20 turns, user-first.
- **Streaming** over server-sent events: `delta {text}`, `done {id}`, `error {code: busy|interrupted|not_configured, message}`. Without a key the route answers 503 and the panel says "The conversation panel isn't set up on this server"; nothing else changes.
- **Thread:** one per project, stored (`conversation_messages`), oldest first, the last 200 on load. Estimator turns right-aligned; answers render paragraphs, `- ` lists, bold, italic — never HTML. The composer is a labelled textarea, Enter sends, Shift+Enter newlines, **read-only (not disabled) while streaming** so focus never falls onto the blueprint's shortcut keys. Empty state: three example questions for the screen. Errors live in the bubble: busy → "Ask again"; interrupted keeps the partial text.
- **Follow-up (not v1):** proposals — an answer produces a preview of a change (which items, which field, old → new) that the estimator applies through the ordinary edit path as one undoable action; canvas anchors and point-and-tell.

## 9. Pricing

`classify` produces per-tag specs plus a labor rate and material factor for the project's location (from the model with a key, from a regional table without). Each item row carries `material_cost`, `labor_hours`, `labor_cost`, `total_cost` from catalog + assemblies (`engine/assemblies.py`: box, plate, ring, wire, conduit behind a device). Resolution order for a row's labor and material: project override → company setting → engine baseline → unpriced (never Estimator approved while unpriced). `pricing_note` states the basis, including the branch-wiring rule (feet per device, not a measured route).

## 10. The API

Prefix `/api`. JSON, camelCase. Errors: `{ "detail": { "code", "message" } }`, message always naming a recovery action. Auth by cookie; `401 not_signed_in`; project routes `404 project_not_found` across orgs.

```
POST   /auth/signup  /auth/login  /auth/logout        GET /auth/me
POST   /invites   POST /invites/{token}/accept

GET    /projects?includeArchived         POST /projects      GET/PATCH /projects/{id}   POST /projects/{id}/archive
GET    /projects/{id}/overview

GET    /projects/{id}/documents          POST /projects/{id}/documents/presign   POST /projects/{id}/documents (record + queue read)
PATCH  /documents/{id}  (docType)        DELETE /documents/{id}                   GET /documents/{id}/content (redirect to signed URL)

GET    /projects/{id}/sheets             PATCH /sheets/{id}  (discipline, revision, scale, included)
GET    /sheets/{id}/tiles/{z}/{x}/{y}    GET /sheets/{id}/render (signed URL)

POST   /projects/{id}/takeoff  (start a run)     GET /projects/{id}/processing
GET    /projects/{id}/snapshot   → { version, sheets, items(with warnings), totals }   (ETag/304 on version)
POST   /items/{id}/approve  /reject  /unreject    PATCH /items/{id}   DELETE /items/{id}   POST /projects/{id}/items
POST   /projects/{id}/items/bulk-approve          POST /sheets/{id}/scale   (compound: scale + re-derived measurements)
POST   /projects/{id}/finish-review   { acknowledgeAttention: bool }

GET/POST /projects/{id}/notes            PATCH/DELETE /notes/{id}      POST /projects/{id}/notes/apply (queue a run)

GET    /projects/{id}/labor              PATCH /items/{id}/labor
GET    /projects/{id}/material-pricing   PATCH /items/{id}/material-price
GET/PUT /company/labor-rates  /company/labor-hours/{itemName}  /company/material-prices/{itemName}  /company/profile

GET    /projects/{id}/export/preview     POST /projects/{id}/export   (xlsx)
GET    /projects/{id}/actions

GET    /projects/{id}/conversation       POST /projects/{id}/conversation/messages (SSE)

POST   /benchmarks (xlsx upload)   GET /benchmarks   GET /accuracy?projectId&benchmarkId
GET    /health
```

Every mutation writes one `actions` row (`kind`, `label`, `before`, `after`, `actor_id`) and returns the updated record plus `{ label }` for the toast. The snapshot's `version` is `max(items.updated_at, sheets.updated_at)`; the client polls it every 4 s while a project is open and on window focus.

## 11. Undo

Per session, client-side. Every mutation the client makes pushes `{ label, inverse }` onto a stack (approve ↔ unreject-to-previous-status, edit ↔ edit with `before`, delete ↔ create with the old record, scale ↔ scale with the old value); undo pops and replays the inverse through the same endpoint; redo re-applies. Cap 60. The server needs no undo machinery; it only needs endpoints that are inverses of each other, which the list above is. Scale confirmation is one compound action on the server, so its undo is one call.

## 12. Acceptance criteria

- A first-time user creates a project, uploads a set, reaches processing, and reviews without training.
- Every screen states the current stage and next primary action.
- The blueprint is the largest element on F at 1280 px and 1440 px.
- Selecting from blueprint or spreadsheet reveals the same item.
- Unreviewed, uncertain, missing, and approved are unmistakable without color.
- Every warning has four fields; Missing information visibly blocks finish and export.
- Undo and save state work on every review action.
- The exported workbook's totals equal the drawer's, to the cent.
- A full review completed with the conversation panel closed reaches the same end state as one that used it.
- The API process never imports the engine (test), cross-org access is 404 on every project route (test), the totals query excludes superseded and rejected items (test), bulk approve refuses non-Ready items (test).
