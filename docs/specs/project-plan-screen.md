# Project plan: what the documents say, for an electrical sub

Written 2026-09-21. Stream F of [`docs/roadmap/workstreams-2026-09.md`](../roadmap/workstreams-2026-09.md).

## What this is

A new screen between *Confirm drawings* and *Processing*: one page that
says what the product understood from the uploaded documents, filtered
to what an electrical subcontractor bids. Scope statements (included,
excluded, by others, alternates), the specification sections found in
Division 26, 27 and 28, the fixture and panel schedules found on the
drawings, the phasing the documents call for, and the questions the
documents did not answer. Every line quotes the page it came from and
links to it. Nothing on this screen is counted, and no quantity appears.

The estimator confirms, dismisses, or corrects each line. What is
confirmed — and what is merely found and not dismissed — is what the
takeoff run reads as the settled statement of the work, and therefore
what the blueprint review, labor, and material pricing estimate
against. That is the reason the screen exists: the run should be told
what the bid is before it counts, by a person, on one page, rather than
having scope discovered item by item in review.

The intake path becomes: Upload documents (C) → Confirm drawings (D) →
**Project plan** → Processing (E) → Blueprint review (F). The plan is
also a permanent workspace in the project navigation, under *Evidence*,
so it can be revisited after the run — a re-read changes what it shows,
and a decision made later still reaches the next run.

## Decisions settled during design

- **Placement.** The plan sits after Confirm drawings and owns *Start
  takeoff*. Screen D's primary button becomes *Review the plan*; its
  scope section moves to the plan screen. Screen D keeps the documents
  as stored and the sheets found in each.
- **Storage.** Plan lines are *derived* on every read from what the
  read job already stores (sheets, documents, scope statements); only
  the estimator's decisions are persisted, keyed by a stable entry key.
  Scope statements keep their own table and API. See *Why derive*.
- **No gate.** *Start takeoff* is always available from the plan. An
  undecided line still counts as found and feeds the run, as today.
  The screen says how many lines are not yet decided, and marks them,
  so an estimator who starts early knows what was skipped.
- **Answers are notes.** Answering an open question saves a context
  note in Notes & assumptions, titled with the question. Context notes
  already feed the next run and the notes screen already offers the
  re-run; the plan is not a second store for what the drawings don't
  say.
- **Phases can be added; nothing else can.** Detected phases can be
  confirmed, renamed or dismissed, and the estimator can add a phase
  the documents don't state, marked *stated by you*. Scope, specs and
  schedules are detection-only; anything else the documents don't say
  is a note.
- **Deterministic only.** No language-model call is made to build the
  plan. Everything on it is a heading, a title, a sheet kind, or a gap
  — pattern work, not prose interpretation — and a GET that waits on a
  model is a GET that fails at 4 pm on bid day. Scope statements, the
  one section that is prose, are already extracted by the worker with
  the model when a key is present and validated to verbatim quotes
  (`engine/scope.py`); the plan reads them, it does not re-extract.

## What the corpus says

Both example bid PDFs in `bid_examples/` — *FedEx Office* and *Gerber
Collision & Glass* — are scans with no text layer. Checked against the
Documents agent as built:

- `documents.detect_sheets` finds no title block on a scanned page and
  emits it as a sheet titled *Scanned sheet* with `kind="other"` and
  `unreadable_reason` set (`SCANNED_REASON`). No text, no scale, no
  legend, no schedule text is read from it. `tests/bid_set.py` lists
  both sets under `RASTER_SETS` and the corpus tests assert exactly
  this: every detected page carries `unreadable_reason`.
- `sheet.finish`'s vision pass runs only when `not sheet.unreadable_reason`
  — a scanned sheet is never sent to vision. There is no OCR path
  anywhere in the engine.
- `documents.read` for a Drawings file runs scope extraction over the
  non-plan sheets' text. For a scanned set that text is empty, so
  `scope.extract` returns `[]`.

So for those two sets the plan has no scope statements, no spec
sections, no schedules, and no phases to show. The Gerber Phase 1 /
Phase 2 split the roadmap's §3 describes came from the GC's bid
instructions or the estimator's read of the drawings, not from any
text the engine can reach. **The screen must be designed for that
outcome rather than around it**: the scanned case renders as one open
question per scanned document, saying how many pages could not be
read and what to do, with the phase-add control and the answer form as
the recovery path. That is the whole screen for those sets, and it is
honest. A text layer (an OCR pass on scanned pages) is stream-external
work; when it lands, the same derivation reads the same fields and the
sections fill in.

The five vector sets (Unalaska, Kittles Saxony, Pulte Sagebriar, TSC
Nutrition, United Utility) carry title blocks, schedule text and — for
the ones with a specification PDF — Division 26 spec pages, so the
derivation below has real input on them. Kittles and Pulte ship
`SPECS/` folders; those are the corpus assertions for spec sections.

## Rules this design keeps

- **The four review labels do not appear.** A plan line's status is its
  own vocabulary — *found*, *confirmed*, *dismissed*, and for a
  question *answered* — the same separation notes and scope statements
  keep (CLAUDE.md: a note's status is not an item's status). Drawn with
  the `.note-status` component and the `--slate` / `--plum` hues, never
  with `Pill.jsx`.
- **Every line links to the page it came from.** The link is the
  document's own page: `GET /api/documents/{id}/content#page=N`, opened
  in a new tab. A drawing sheet and a spec page get the same treatment,
  because the source page is the evidence whether or not a rendered
  tile pyramid exists for it. (Deep-linking a sheet on the blueprint
  canvas is not built; `ProjectWorkspaceLayout` holds its sheet in
  local state with no URL parameter, and adding one is outside this
  stream's files. See *Not built*.)
- **Every question answers four things.** What was found, why it
  matters, what to check, where the evidence lives — the warning shape,
  enforced by the wire schema (`QuestionOut` has all four fields,
  non-empty).
- **Extracted document text is data.** Quotes are rendered in a
  `<blockquote>` as text. The derivation matches patterns in stored
  text; nothing in the text can produce a line of a kind or a decision
  it does not match.
- **Nothing is counted.** No quantity, total, or item count appears on
  the plan. The sheets section says a schedule exists, not what is on
  it.
- **Audited, not undoable.** Every decision goes through
  `actions.commit()` with the actor and a label in the estimator's
  words. Like `scope_decide` and the note actions, `plan_decide` is
  absent from `undo.REVERSIBLE`: reversing it means restoring a prior
  decision from a snapshot, which is its own feature.
- **Nothing on the wire names how a line was produced.** No pattern
  name, no source flag, no attempt count, no run id.
- **Sentence case; no exclamation marks; no "please".**

## The plan record

`GET /api/projects/{project_id}/plan` returns:

```
{
  "read_at":        ISO timestamp of the latest processed document (its upload time — there is no processed_at), or null
  "reading":        true while a drawing set is still being read
  "has_drawings":   true when at least one document is typed Drawings (the client's Start button needs it)
  "undecided":      count of lines in status "found"
  "scope":          [ScopeStatementOut, ...]          the existing shape
  "specs":          [PlanLineOut, ...]                kind "spec_section"
  "schedules":      [PlanLineOut, ...]                kind "schedule"
  "phases":         [PhaseOut, ...]                   detected and added
  "questions":      [QuestionOut, ...]
}
```

`PlanLineOut`:

```
{
  "key":               stable entry key (see below)
  "kind":              "spec_section" | "schedule"
  "text":              what it is, in the estimator's words after a correction
  "found_text":        what the documents said, before any correction
  "edited_text":       the correction, or null
  "status":            "found" | "confirmed" | "dismissed"
  "document_id", "document_filename", "page"   (page is 1-based)
  "quote":             the verbatim line it was taken from
  "division":          "26" | "27" | "28"  (spec sections only)
  "sheet_number":      the sheet's number (schedules only)
  "added":             true for a phase the estimator stated (false otherwise)
  "phase_id":          the stated phase's id, for DELETE (null otherwise)
  "places":            every place a phase appeared: [{document_id, document_filename, page, quote}, ...]
}
```

A phase is a `PlanLineOut` with kind `"phase"`. A detected phase lists
every place it appeared in `places` (the first is also the line's own
citation). A stated phase has `"added": true`, a `phase_id`, no
document, page or quote, a `key` of the form `phase:added:<uuid>`, and
starts as *confirmed* — it is the estimator's own statement, so it is
never counted as undecided; it can still be dismissed or reopened.

`QuestionOut`:

```
{
  "key", "status": "found" | "dismissed" | "answered",
  "title", "found", "why", "fix", "where",
  "document_id" | null, "document_filename" | null,
  "note_id": uuid | null      when answered, the note that answers it
}
```

Exclusions are not a separate array: the client renders the
*Exclusions* section from `scope` lines of kind `excluded` and
`by_others`, and a decision made there is the same PATCH as in *Scope*.

### Stable entry keys

A decision has to survive a re-read that finds the same thing again,
and stop showing when the thing is gone — the rule
`read_job._replace_found_scope` already applies to scope statements,
keyed on `(kind, quote)`. The plan keys each derived line the same way,
on what identifies it rather than on where in the text it sat:

| Kind | Key |
|---|---|
| spec section | `spec:<document_id>:<section number normalised, e.g. 260519>` |
| schedule (a sheet) | `schedule:sheet:<sheet_id>` |
| schedule (a heading inside a sheet) | `schedule:heading:<sheet_id>:<heading normalised, e.g. PANEL SCHEDULE>` |
| detected phase | `phase:<label normalised, e.g. PHASE 1>` — one line per phase across the project, with every place it appears listed |
| added phase | `phase:added:<uuid>` |
| question | `question:<rule>:<document_id or sheet_id or project>` |

Keys are opaque to the client. The server parses nothing out of a key
except in tests.

## Derivation

`api/app/plan/detect.py` — pure functions over rows the API already
reads. No PDF is opened; `app.plan` imports nothing from `app.engine`
that opens a file, and the existing import-boundary tests keep it that
way. Every function takes plain values and returns typed dataclasses,
so the corpus tests can feed it stored text without a database.

**Spec sections** — from `Document.context_text` of every processed
document whose `doc_type` is Specifications, Addendum, Scope or Other
(not Drawings: a drawing's page text is not stored). Pattern: a line
that begins with a Division 26/27/28 section number in any of its
forms — `26 05 19`, `260519`, `26-05-19`, and the level-4 forms
`26 05 33.13` / `26 0533.13` (the suffix is part of the number, so
`26 05 33`, `26 05 33.13` and `26 05 33.16` are three sections) —
followed by a title on the same line or the next. A table of contents
is the usual source: dot leaders and a trailing page reference are cut
from the title (`GENERAL PROVISIONS ........ CDG` → `GENERAL PROVISIONS`);
the quote stays verbatim, and when the title came from the next line
the quote is both lines joined. One line per distinct section number
per document; the first occurrence wins.
`context_text` carries no page markers, so a spec line's `page` is
null, its citation reads the filename alone, and its link opens the
document at page 1 — the one section where "the page it came from"
is the document rather than the page, recorded under *Not built*.

**Schedules and legends** — one line per sheet whose `kind` is
`schedule` or `legend`, quoting the sheet's title, plus one line per
distinct schedule heading found in any sheet's `schedule_text` (the
headings `sheet_kind._SCHEDULE_HEADERS` already looks for: panel,
luminaire, fixture, equipment, mechanical schedule) on a sheet whose
kind is *not* schedule — a plan sheet carrying an embedded schedule
block. Cited to the sheet's document and page.

**Phases** — the pattern `\bPHASE\s+(\d{1,2}|[A-Z]|I{1,3}|IV|V)\b`
(case-insensitive) over sheet titles, sheet `schedule_text`, and
document `context_text`. Grouped by normalised label; each group lists
every place it appeared (document, page, quote) and the first place is
the line's own citation. A label that only appears in a phrase like
"phase" as a verb does not match: the pattern requires the number or
letter.

**Questions** — a closed set of rules, each producing at most one
question per subject, each with all four fields:

| Rule | Subject | Fires when |
|---|---|---|
| `scanned` | a Drawings document | every sheet from it carries `unreadable_reason`, or at least one does (the copy says *N of M pages*) |
| `no_specs` | the project | no processed document of type Specifications |
| `no_scope` | the project | no scope statement at all, and at least one processed document |
| `no_scale` | a sheet | `kind == "plan"`, readable, `scale == ""`, `scale_options == []` |
| `no_phasing` | the project | no detected phase and no added phase, and at least one readable plan sheet |
| `no_schedule` | the project | no schedule or legend sheet and no schedule heading, and at least one readable plan sheet |

Copy for each is in `api/app/plan/copy.py`, the pattern
`api/app/market/copy.py` set. Example, the scanned rule:

> **Pages that could not be read** ·
> found: *12 of 12 pages in Renovation for Gerber Collision & Glass.pdf are scanned images with no readable text.* ·
> why: *Nothing on those pages was read, so the takeoff will count nothing on them and no scope, schedule, or phasing was taken from them.* ·
> fix: *Upload a version exported from the drafting software, or state the scope and phasing here as answers.* ·
> where: *Renovation for Gerber Collision & Glass.pdf, every page.*

`no_scale`'s *fix* names the scale control on the blueprint; its
*where* names the sheet's title block. `no_phasing` and `no_schedule`
are the two questions most often answered *no, this job has one phase*
— the answer form is one sentence and the note carries it.

### Why derive

Three storage options were weighed. Materialising plan lines from the
worker at the end of every read (as scope statements are) means a hook
in `read_job.py` and a second dedupe rule; widening `scope_statements`
to carry spec sections and schedules conflates what the documents say
the work *is* with which schedules *exist*. Deriving on read keeps the
plan a view — the same discipline `ROADMAP.md` invariant 1 applies to
totals: one query, one consumer — and the only rows the plan owns are
the ones a person made. A re-read changes the lines by itself; a
decision whose line vanished stops showing, and comes back if the line
does.

The cost is a GET that scans every sheet and document of a project.
Bounded: `context_text` is capped at 12 000 characters per document,
`schedule_text` is one page of text, and a project has tens of sheets,
not thousands.

## Storage

Migration `0026_plan.py`, `down_revision = "0025"`. Two tables. The
migration spells its constants out; it imports nothing from `app`.

**`plan_decisions`** — one row per line a person has decided.

| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `project_id` | uuid fk projects, cascade, indexed | |
| `entry_key` | string(300) | unique with `project_id` |
| `status` | string(20) | check in `('found', 'confirmed', 'dismissed', 'answered')` |
| `edited_text` | string(500) null | the correction |
| `note_id` | uuid fk notes, set null | the answer, for a question |
| `decided_by` | uuid fk users, set null | |
| `decided_at` | timestamptz | |

A row with status `found` is a *reopened* decision — kept, not deleted,
so the audit trail's before/after has a row to point at.

**`plan_phases`** — phases the estimator stated.

| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `project_id` | uuid fk projects, cascade, indexed | |
| `name` | string(100) | |
| `created_by` | uuid fk users, set null | |
| `created_at` | timestamptz | |

Models live in `api/app/plan/models.py`, on the shared `Base`. Neither
needs a column on `Project`, `Sheet` or `Document`, so
`api/app/takeoff/models.py` is not touched.

Stream D (phases and timeline) will build the phase model proper. This
table is the input it reads — confirmed detected phases and added
phases together are "the phases the estimator agreed to" — not a
competing model. Its migration can add columns or fold the table in.

## Backend

`api/app/plan/` — `models.py`, `schemas.py`, `detect.py`, `copy.py`,
`service.py`, `router.py`. Mounted with one appended line in
`app/main.py`.

**Routes**, every one through `takeoff.router.load_project` (404 for a
project in another org, never 403), rows appended to
`tests/test_tenancy.py`'s table:

| Route | Does |
|---|---|
| `GET /api/projects/{id}/plan` | assembles the plan (above) |
| `PATCH /api/projects/{id}/plan/lines/{key}` | body `{"status": ...}` or `{"edited_text": ...}`, exactly one — the `scope.service.decide` contract; `status` may be `found` to reopen. A line (spec, schedule, phase) accepts `found`, `confirmed`, `dismissed`; a question accepts only `found` and `dismissed` (answering is the route below) and cannot be reworded |
| `POST /api/projects/{id}/plan/questions/{key}/answer` | body `{"body": text}`; creates a context note through `notes.create_note` and marks the question `answered` with `note_id`; one request, two audited actions (`note_add`, `plan_decide`) in one transaction |
| `POST /api/projects/{id}/plan/phases` | body `{"name": text}`; adds a phase, audited `plan_phase_add` |
| `DELETE /api/projects/{id}/plan/phases/{phase_id}` | removes an added phase, audited `plan_phase_remove`; 404 for a detected phase's key |

The answer note: `scope="project"`, `usage="context"`,
`category="customer_instruction"` for `no_phasing`/`no_specs`/
`no_scope`/`scanned`, `"existing_condition"` for `no_scale` and
`no_schedule`; `title` is the question's title, `body` the estimator's
text, `source_ref` the question's *where*. The note is an ordinary note
afterwards — editable and deletable on the notes screen; deleting it
sets `note_id` null and the question reads *found* again.

**Refusals**, estimator-facing, through `DomainError`:

- a `key` the current derivation does not produce → 404 (the line is
  gone; the client re-fetches)
- `status` outside the set, or both/neither of status and edited_text
  → 422 with the same sentences `scope.service.decide` uses
- `edited_text` empty or over 500 characters → 422
- answering a question with an empty body → 422 "Write the answer
  before saving it."
- answering a question that already has an answer → 422 "This question
  already has an answer. Reopen it to answer it again." Reopening
  clears `note_id`; the earlier note stays in Notes & assumptions as
  the estimator's own record, and still feeds the next run until they
  delete it there.
- a phase name empty, over 100 characters, or matching an existing
  phase (detected or added, case-insensitive) → 422 "That phase is
  already on the plan."

**Stage.** `Project.stage` moves to `plan` when the plan is fetched
while the stage is `setup` or `documents`, at least one drawing set
has been read, and none is still being read. It never moves backward —
the move is one conditional `UPDATE … WHERE stage IN ('setup',
'documents')`, so a poll that loaded the project before the worker
moved it to `processing` cannot move it back — and a fetch at
`processing` or later changes nothing. This is the one place the plan is assembled, so
it is the one place that knows the project has reached it. The client
mirror `src/lib/projectStage.js` gains `{ key: "plan", label: "Plan" }`
between `documents` and `processing`; `matchesFilter` is unchanged
(`plan` is neither processing nor complete, so it is *active*).

**Scope statements** are read through `scope.service.list_statements`
and mapped with `scope.router._out`, so the plan's scope array and
`GET /scope` never disagree. Decisions on them go through the existing
`PATCH /api/scope/{id}` — the plan's PATCH refuses a scope statement's
id (it is not an entry key) with a 404, so there is exactly one write
path per record.

## Client

`src/components/plan/`:

- `PlanWorkspace.jsx` — the screen. Loads `store.getPlan(projectId)`;
  while `reading` is true it polls every 3 s, as screen D does. Header:
  title *Project plan*, one sentence, *N lines not yet decided*, *Read
  {time}*. Primary button *Start takeoff*, identical rules and copy to
  screen D's (`store.startTakeoff`, disabled with `READING_HELP` while
  a drawing set is reading, a run already in flight treated as started).
  Secondary link *Back to confirm drawings*. Then the six sections.
- `PlanSection.jsx` — heading, one-sentence description, an empty
  sentence when there are no lines, the list.
- `PlanLine.jsx` — the row: status, text (with *found* text struck
  through above a correction), citation *filename, page N* linking to
  the page, *View source* disclosure with the quote in a blockquote,
  and the decision controls: Confirm, Dismiss, Correct (an inline text
  field with Save and Cancel, as the scope row always had), Reopen on a
  decided row. Every
  control reports the server's answer; a refused decision leaves the
  row as it was with the refusal on the row. Scope rows are the same
  component with `onDecide` bound to `store.decideScope`.
- `QuestionLine.jsx` — the four fields, then *Answer* (a textarea with
  a visible label, Save / Cancel) and *Dismiss*. Answered shows
  *Answered* and *See the note* linking to `/notes`.
- `PhaseSection.jsx` — detected phases as `PlanLine`s (each place it
  appeared listed under the row), added phases with *stated by you*
  and a Remove control, and *Add a phase* — a text field with a
  visible label.
- `ScopeSection.jsx` — moved from `documents/` unchanged in behaviour;
  its import in `ConfirmDrawings.jsx` removed. `ConfirmDrawings.jsx`'s
  primary button becomes *Review the plan*, navigating to `/plan`; its
  disabled rule (a drawing set still reading) and the
  `drawings_still_reading` inline refusal stay on Start takeoff, which
  now lives on the plan. The file's header comment gains one paragraph
  saying so. This is the whole edit to screen D.

Route: `<Route path="plan" element={<PlanWorkspace />} />` appended
inside `ProjectWorkspaceLayout`'s children in `routes.jsx`, so the plan
gets the project nav, the top bar, and the conversation panel like
every other workspace. Nav: one item appended to the *Evidence* group
in `ProjectNav.jsx` after Notes & assumptions — `{ slug: "plan", label:
"Project plan", built: true, Icon: ListChecks }`. (Inserting after the
group's last item is an append within that array; nothing above it
moves.) Screen name `"plan"` appended to `SCREEN_NAMES`, `SCREEN_LABELS`
(*Project plan*) and `BY_SUFFIX` in `screenContext.jsx`, and to
`SCREEN_NAMES` and the `Literal` in `api/app/assistant/schemas.py` —
the mirror the file's own docstring requires — and to `SCREEN_LABELS`
in `api/app/assistant/prompt.py`, a third mirror a test now guards.
`assistant/context.py` gives `plan` the same sections as `confirm`
(documents, sheets, document texts): the plan is a view over the same
material, and the panel proposes nothing here.

Store: `getPlan`, `decidePlanLine`, `answerPlanQuestion`, `addPlanPhase`,
`removePlanPhase` appended to `api.js`; `mapPlan` appended to
`api-mapping.js` (snake → camel, `page` left as the 1-based number).

Styles: appended to `styles.css` under `/* ==== stream F: plan ==== */`.
Reuses `.note-status`, `.scope-row__*`, `.btn`, form tokens; new
classes are `.plan-*` only.

**Empty and loading states.** Loading: the header with *Reading the
documents…*. No documents at all: one sentence, *Upload documents to
build the plan*, linking to `/documents`. Every section renders its
empty sentence rather than disappearing, so the shape of the plan is
visible even when it is mostly empty — the scanned-set case.

## Testing

Backend (`api/tests/`):

- `test_plan_detect.py` — every rule on synthetic text: each spec
  number form, a 27 and a 28 section, a section repeated on two pages
  (one line), a schedule sheet, a plan sheet with an embedded panel
  schedule heading, `PHASE 1` / `Phase A` / `PHASE II` grouped, "phase"
  as a verb not matched, each question rule firing and not firing,
  four non-empty fields on every question. Key stability: the same
  input twice gives the same keys; a changed quote on the same section
  gives the same key.
- `test_plan_corpus.py` — under the corpus skip guard: FedEx and Gerber
  produce no spec, schedule or phase lines and exactly one `scanned`
  question each with *N of N pages*; Unalaska produces at least one
  schedule line; a set with a `SPECS/` folder produces Division 26 spec
  sections once its spec PDF is read through `documents.read` (the
  test runs the engine in-process, as `test_corpus_sheets.py` does).
- `test_plan_api.py` — GET assembles all arrays; confirm / dismiss /
  correct / reopen each land, are audited with the right label, and
  are not undoable (`plan_decide` is not in `undo.REVERSIBLE`, and an
  undo request after a decision finds nothing to reverse);
  a stale key 404s; both-or-neither 422s; answer creates a context note
  and marks the question, deleting the note reopens it; phase add,
  duplicate refusal, remove; stage moves to `plan` once and never
  backward; scope statements arrive through the plan and a scope id
  is refused as a key.
- `test_tenancy.py` — rows for all five routes.
- `test_api_import_boundary.py` gains nothing: `app.plan` imports no
  engine module, and the existing test of `app.main` covers it.

Frontend (`src/**/*.test.jsx`, vitest):

- `PlanWorkspace.test.jsx` — renders six sections from a fixture plan;
  the scanned-set fixture renders five empty sentences and one
  question; the undecided count; Start takeoff disabled while reading
  with the help copy; a decision follows the server's answer and a
  refusal leaves the row; Answer saves and the row reads *Answered*
  with the note link; Add a phase; the page link's href carries
  `#page=N`.
- `projectStage.test.js` — `plan` labels as *Plan* and matches the
  *active* filter.
- `ConfirmDrawings` existing tests updated for the renamed primary
  button; the scope section's tests move with the component.

Before the last commit: full backend suite, `npm test -- --run`,
`npm run build`.

## Not built in this slice

- **Spec sections cite the document, not the page.** `Document.context_text`
  carries no page markers; adding them is one line in
  `engine/documents.context_pages` owned by another stream. Until then
  a spec line's citation is the filename and its link opens page 1.
- **No deep link onto the blueprint canvas.** A schedule line links to
  the source page of the PDF. Selecting that sheet on the canvas from
  the plan needs a URL parameter in `ProjectWorkspaceLayout`.
- **No text from scanned pages.** The scanned case renders as a
  question. OCR is engine work outside this stream.
- **Confirmed spec sections do not change what the run reads.** The
  run already receives the spec document's Division 26 text; a
  confirmation records the estimator's agreement and a dismissal
  records disagreement, and both are on the audit trail, but neither
  filters `context_text` yet. Doing so is a change in
  `worker/classify_job.py`.
- **Phases stop at names.** Which sheets a phase covers, and its order,
  are stream D's.
- **The conversation panel** answers on the plan screen from the same
  context the confirm screen has; it proposes nothing here. Stream E
  adds proposals.
- **`no_specs` asks only when a drawing set exists**, and `read_at` is
  the latest upload time, not the time of the read — there is no
  `processed_at` on a document.
