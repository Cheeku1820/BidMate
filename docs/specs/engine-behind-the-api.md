# B2 — The engine behind the API

**Date:** 2026-09-15
**Branch:** `feat/engine-behind-api`, stacked on `feat/document-pipeline` (B1)
**Implements:** `docs/roadmap/full-webapp-plan.md` Phase B, second of four sub-projects. Order: B1 documents stored → **B2 engine behind the API with per-sheet jobs** → B3 drawing behind the markers → B4 confirm-drawings write-back and metering.

## 1. What this changes

Today the browser runs the engine. `ProcessingStatus.jsx` fetches every document's bytes back from the API and posts them to `api/estimate_service.py` at `localhost:8100` — a second FastAPI app with no auth, no database and CORS `*` — then posts the result to `POST /projects/{id}/takeoff`, which replaces the project's takeoff in one transaction and refuses when approvals exist. The notes re-run does the same round trip into `POST /projects/{id}/reprocess`. One request, one stage indicator on a timer, a 66-sheet set that lands all at once or not at all, and a page the estimator cannot leave.

After B2 the client talks only to the API. A **worker** process is the only thing that opens a PDF. Work is queued in a `jobs` table and runs in three kinds — `read` per document, `classify` per project run, `sheet` per plan sheet — so that a corrupt file marks one document, a sheet that cannot be counted marks one sheet, and every finished sheet is reviewable while the rest run. Screen E polls real state. "You can leave this page" becomes true.

Two product decisions shape everything below:

1. **Reading is automatic; the takeoff is deliberate.** The moment a file lands, a `read` job opens it, detects sheets and pulls schedule and scope text. Screen C shows the outcome per file; screen D shows real detected sheets and the scope the documents state. **Start takeoff** on screen D queues the counting, classification, pricing and vision work.
2. **The engine never discards a person's judgment.** Every run merges per sheet the way the notes re-run does today — an *Estimator approved* item is never overwritten or removed by processing. The "replacing discards approvals" dialog and the replace path are deleted. A clean slate is a deliberate act: delete the items.

## 2. Data model

Migration `0021_jobs_scope`, reversible.

### 2.1 `jobs`

One row per unit of work. The queue is the table; no Redis.

```
jobs
  id              uuid pk
  org_id          uuid, fk orgs, index
  project_id      uuid, fk projects on delete cascade, index
  kind            str(20)   read | classify | sheet          ck_jobs_kind
  document_id     uuid null, fk documents on delete cascade  set for read
  sheet_id        uuid null, fk sheets on delete cascade     set for sheet
  run_id          uuid null                                  classify and its sheet jobs share one
  requested_by    uuid null, fk users                        the person who pressed Start; classify carries it
  payload         jsonb null                                 a sheet job's clusters (tag, count, placements)
  status          str(20)   queued | running | done | failed ck_jobs_status
  progress        str(20) default ''   a running sheet job reports 'checking' (vision); 'unchecked' when vision failed
  attempts        int default 0
  max_attempts    int default 3
  error           text default ''   estimator-facing reason when failed; never an exception name
  locked_by       str(100) default ''
  queued_at       timestamptz server default now()
  not_before      timestamptz null   the retry backoff
  started_at      timestamptz null
  finished_at     timestamptz null
```

Index `(status, kind, queued_at)` for the poll. Partial unique index on `(document_id) where kind='read' and status in ('queued','running')` so a document has at most one read in flight; likewise `(project_id) where kind='classify' and status in ('queued','running')` — the database enforces "one run at a time", not the route.

### 2.2 `documents` gains

```
  page_count      int null              set by read
  context_text    text default ''       Division 26-relevant text from specs/addenda/scope, ≤ 12 000 chars
```

`status` moves through its existing closed set: `uploaded` → `processing` (read queued or running) → `processed` / `failed`. `error` (already present) carries the read failure copy. **B1 residual I5 is fixed here**: screen C renders only `failed` as failed; `processing` reads "Reading…", `processed` reads "Read".

### 2.3 `sheets` changes meaning

`takeoff_id` becomes the **document id** (string form, column unchanged), and `(takeoff_id, page_index)` is a sheet's stable identity across runs: `read` upserts by that key rather than replacing, so a sheet's id — and everything that points at it — survives re-reading. Gains:

```
  schedule_text   text default ''       extracted by read so classify never re-opens the file
  region          jsonb null            [x0, y0, x1, y1] in page points -- counting runs within it
  legend          jsonb null            parsed LegendEntry rows -- the deterministic classifier reads them
```

All three are written by `read` so `classify` and `sheet` never re-open a file for what the Documents agent already found.

No `document_pages` table. The sheets the engine detects are the pages the product cares about; B3 adds a render key to `sheets` directly.

### 2.4 `classifications`

One per run. Written once by `classify`, read by every `sheet` job of that run.

```
classifications
  id, project_id, run_id (unique)
  specs_by_tag    jsonb        tag → the spec the classifier returned (name, catalog id, status, warning…)
  labor_rate      numeric
  material_factor numeric
  source          str(20)      llm | deterministic
  location_note, wiring_note, unmatched_note   text
  created_at
```

Keeps the pricing basis one-per-project; the labor and material workspaces already assume that. On run completion `project.pricing_source` and `pricing_note` are set from this row exactly as `ingest_takeoff` sets them today.

### 2.5 `scope_statements`

What the documents say the electrical work is. Found by the worker, settled by a person.

```
scope_statements
  id, org_id, project_id
  kind            str(20)   included | excluded | by_others | alternate     ck_scope_kind
  text            str(500)  the statement, in the document's words, one sentence
  document_id     uuid, fk documents on delete cascade
  page_index      int
  quote           text      verbatim passage it came from, ≤ 600 chars — what "View source" shows
  status          str(20)   found | confirmed | dismissed                    ck_scope_status
  edited_text     str(500) null   an estimator's rewrite; `text` stays for the audit trail
  run_id          uuid       the read that found it
  decided_by      uuid null, fk users
  decided_at      timestamptz null
  created_at
```

`status` is deliberately not the four review labels — those describe an item's evidence; this describes whether a person has settled a statement. Same separation as a note's `confirmed`/`open`, rendered with the same `--slate`/`--plum` tokens, never with the item-status components.

Re-reading a document keeps every `confirmed` and `dismissed` statement and deletes then re-finds only `found` ones, so decisions survive a re-upload.

### 2.6 What never crosses the wire

`source`, `specs_by_tag`, `attempts`, `locked_by`, job ids, exception names. ROADMAP invariant 7. A test greps the processing and scope responses for `source`, `attempt`, `llm`, `confidence`, `model`.

## 3. The engine split

`estimate.py`'s `_compute` does everything in one pass. It is split along the job boundaries into three entry points that take a path and typed records and return typed records — no database, so the CLI (`python -m app.engine`) and the corpus tests call the same functions the worker does.

```
engine/documents.py
  read(path) -> DocumentReading
      sheets: list[Sheet]            number, title, kind, scale, page_index, width_pt, height_pt,
                                     unreadable_reason, schedule_text   (detect_sheets, as today)
      page_count: int
      context_text: str              extract_context, as today, for non-drawing documents
      scope: list[ScopeStatement]    §4

engine/classification.py
  classify_run(clusters: list[Cluster], schedule_text: str, context: str,
               estimator_notes: list[dict], location: str) -> Classification
      specs_by_tag, labor_rate, material_factor, source, location_note, wiring_note, unmatched_note
      -- today's LLM-or-deterministic branch of _compute, moved, unchanged in behaviour

engine/sheet.py
  finish(path, sheet: Sheet, clusters: list[Cluster], classification: Classification) -> SheetResult
      rows: list[dict]               _row_from_spec / _row_from_catalog for this sheet's clusters
      evidence_png by row            render_evidence_crop, as today
      ai_reading: dict | None        the vision pass, moved here from estimate_service.py
```

`counting.count(path, sheets)` stays as it is and runs inside `classify` for every readable plan sheet, wrapped per sheet: a sheet whose counting raises becomes `unreadable_reason = "This sheet couldn't be read."` and the run continues.

`estimate.py` keeps `estimate()` for the CLI and the corpus tests, reimplemented over the three entry points so there is one code path. `estimate_service.py` is deleted.

## 4. Scope statements

The Documents agent is *language over a deterministic shell*. Scope extraction is the language half applied to text the shell already pulls.

**Input.** For a non-drawing document: its `context_text`. For a drawing set: the text of its non-plan sheets (`kind` in `other`, `legend`, `schedule`) — general notes and E0.x sheets are where drawings state scope. Capped at 12 000 chars per document, Division 26-relevant pages first, as `extract_context` already orders them.

**With a key:** `llm.extract_scope(text) -> list[dict]`, a schema-constrained call. The prompt frames the text as material to summarise, asks for statements about electrical scope only, and the output is validated to `{kind ∈ four, text ≤ 500 chars, quote ≤ 600 chars and present verbatim in the input, page_index}`. A statement whose quote is not found verbatim in the input is dropped — the quote is the evidence, and evidence that cannot be located is not evidence. Anything the model returns outside that shape is discarded, which is what keeps document text from becoming an instruction.

**Without a key:** `scope.extract_deterministic(text)`. Headings matched case-insensitively — `SCOPE OF WORK`, `SCOPE`, `INCLUSIONS`, `EXCLUSIONS`, `NOT IN CONTRACT`, `NIC`, `BY OTHERS`, `ALTERNATES`, `SECTION 26 \d\d \d\d` — open a block that ends at the next heading; each line or bullet under it becomes one statement, `kind` from the heading (`excluded` for EXCLUSIONS/NOT IN CONTRACT/NIC, `by_others` for BY OTHERS, `alternate` for ALTERNATES, `included` otherwise). Quote is the line itself.

**What it feeds.** `classify` passes `found` and `confirmed` statements to `build_classifier_context` inside the *document text* block — untrusted, exactly where `context_text` goes today — and skips `dismissed`. Using `edited_text` where present. It does not remove items from a takeoff: an exclusion becoming "these 40 fixtures are out" is a proposal the conversation layer makes and a person applies. B2 builds the record and the structured path so the panel has something to write to.

## 5. The worker

### 5.1 Process

`python -m app.worker` in `api/app/worker/`. A Compose service `worker` from the same image as `api`, `mem_limit: 2g`, `pids_limit: 256`, `ANTHROPIC_API_KEY` passed through, `depends_on` postgres and minio-init. `docker compose up` is the whole stack; the host `.enginevenv` is for running tests only.

`app.worker` is the only package that imports `app.engine` or `pymupdf`. `test_api_import_boundary.py` keeps `app.main` clean; a mirror test asserts `app.worker` imports neither `app.main` nor any `*router*` module.

### 5.2 Loop

Every 2 s:

```sql
SELECT * FROM jobs
 WHERE status = 'queued'
   AND (kind <> 'sheet' OR run_id IN (SELECT run_id FROM jobs WHERE kind = 'classify' AND status = 'done'))
 ORDER BY queued_at
 FOR UPDATE SKIP LOCKED LIMIT 1
```

Mark `running`, `locked_by = <hostname:pid>`, `started_at = now()`, `attempts += 1`, commit. Run. Mark `done` or `failed`. Two workers share the table with no coordinator; the ordering rule lives in the query, not in memory.

### 5.3 Sandbox per job

Every job body runs in a **child process** (`multiprocessing`, spawn) with a hard wall-clock timeout: `read` 120 s, `classify` 300 s, `sheet` 180 s. The child opens the blob into a temp file, does the work, writes to the database, and exits. A parser that hangs or eats memory kills the child; the parent marks the job failed with terminal copy and moves on. Configurable via `WORKER_TIMEOUT_<KIND>` for the corpus tests.

### 5.4 Failure classes

| class | examples | policy |
|---|---|---|
| transient | blob store unreachable, database connection dropped, classification/vision service 5xx or timeout | back to `queued` with a 30 s backoff while `attempts < max_attempts`; then failed with the "right now" copy |
| terminal | encrypted PDF, parser exception, child timeout, zero pages, not a PDF after all | failed on the first attempt — retrying a corrupt file only delays the honest answer |

A `classify` whose LLM call fails falls back to deterministic classification, as `_compute` does today — that is not a failed job. A `sheet` whose vision read fails keeps its rows and records no `ai_reading` — not a failed job either; the sheet is Complete with the "schedules weren't checked" note.

### 5.5 Stale runs

A `running` job whose `started_at` is older than its kind's timeout plus 60 s belonged to a worker that died. The poll reclaims it as `queued` first, attempt count intact, so it counts against `max_attempts`.

### 5.6 The three kinds

**`read`** (per document)
1. Document `status = processing`.
2. Open the blob; `documents.read(path)`.
3. Upsert sheets by `(takeoff_id = document id, page_index)`: existing rows updated in place (number, title, kind, scale, dims, unreadable_reason, schedule_text); rows for pages no longer detected deleted with their items and warnings; new rows inserted. Sort order by page.
4. Document `page_count`, `context_text`. Delete this document's `found` scope statements; insert the new ones with this job's id as `run_id`. `confirmed`/`dismissed` untouched.
5. Document `status = processed`, `error = ''`. One transaction for 3–5.
On terminal failure: `status = failed`, `error = <copy>`, no sheet changes.

**`classify`** (per project, one per press of Start takeoff)
1. Load the project's `processed` Drawings documents and their sheets. The route already refused when there were none (§7); if a document was deleted between queue and run and none remain, the job fails with "No drawings have been read yet." 
2. For each readable plan sheet, open its document's blob and `counting.count` — wrapped per sheet as §3 says. Clusters kept in memory keyed by sheet id.
3. `schedule_text` = every sheet's, joined; `context` = every non-drawing document's `context_text` + scope statements per §4; `estimator_notes` = the project's `usage = context` notes, read from the database — the browser carries nothing.
4. `classification.classify_run(...)`; insert the `classifications` row.
5. Queue one `sheet` job per readable plan sheet with the same `run_id`, each carrying its clusters in a `payload` jsonb column on the job (clusters are small: tag, count, placements).
6. Set `project.stage = processing`.
A project with zero readable plan sheets completes the run with no sheet jobs and `project.stage = review`; screen E says so in words.

**`sheet`** (per plan sheet, per run)
1. Open the document's blob; `sheet.finish(...)` with the run's classification and the job's clusters.
2. `takeoff.merge.merge_sheet(db, project, sheet, rows, ai_reading, actor=system)` — §6.
3. When this was the run's last `sheet` job (count of siblings not `done`/`failed` is zero, checked under the row lock): `project.stage = review`, `pricing_source`/`pricing_note` from the classification, one `actions.commit` of kind `ingest` with label `Processed N sheet(s) into M item(s)` attributed to the person who pressed Start (their user id is on the `classify` job as `requested_by`).

### 5.7 Who queues what

- `store_upload` (B1) → one `read` job; `status = processing`. Under the same transaction as the document row.
- `set_doc_type` → re-queue `read` (a file retyped Other → Specifications now contributes context).
- `POST /projects/{id}/takeoff` → one `classify` job, fresh `run_id`, `requested_by` = actor. 409 `run_in_flight` while the partial unique index says one exists.
- Notes re-run → the same route. `/reprocess` is deleted.
- `delete_document` → its queued jobs deleted, its sheets (and their items, warnings, evidence) deleted, its scope statements deleted, in the same transaction, row-first as B1 does. **B1 residual I3 fixed here**: the route commits, *then* `store.delete` under `try/except` with a log line; a blob that outlives its row is the reaper's problem (ROADMAP §2.2), never a row that points at nothing.

## 6. One write path: `takeoff/merge.py`

`reprocess.py`'s approval-preserving merge, narrowed to one sheet and renamed. `ingest_service.py` and the replace path are deleted; `map_payload`'s per-row validation (warning schema, status set, coordinates) moves with it and still runs on every row before anything is written — invariant 5.

`merge_sheet(db, *, project, sheet, rows, ai_reading)`:
- Key `(sheet id, source_tag)` — sheet id, not sheet number, now that ids are stable.
- An existing **approved** item is never overwritten or deleted.
- An existing un-approved item matched by key is updated in place (id preserved, so undo keeps working — the reason `reprocess.py` documents).
- A deliberately deleted item (live `delete` action) is not resurrected — `_deliberately_deleted` carried over.
- Unmatched incoming rows are inserted; unmatched un-approved existing items are deleted.
- `sheet.ai_reading` replaced. Evidence images upserted per item.
- One transaction per sheet.

`reprocess_takeoff` becomes a thin loop over `merge_sheet` for the CLI and tests, then is deleted once nothing calls it.

## 7. API

All org-scoped through `load_project` → 404 never 403; all registered in `test_tenancy.py`'s tables.

| route | request | response |
|---|---|---|
| `POST /api/projects/{id}/takeoff` | `{}` | `202 {run_id}`; `409 run_in_flight`; `409 no_readable_drawings` |
| `GET /api/projects/{id}/processing` | — | §7.1 |
| `GET /api/projects/{id}/scope` | — | `[ScopeStatementOut]` |
| `PATCH /api/scope/{id}` | `{status}` or `{edited_text}` | `ScopeStatementOut` |

`POST /projects/{id}/takeoff` with a payload body, and `POST /projects/{id}/reprocess`, are removed. The old `TakeoffIngestOut`/`ReprocessOut` schemas go with them.

### 7.1 Processing response

```json
{
  "documents": [
    {"id": "…", "filename": "E-set.pdf", "doc_type": "Drawings",
     "state": "read",            // reading | read | failed
     "reason": "",               // copy when failed
     "sheet_count": 14}
  ],
  "run": {                       // null when no run has been queued
    "state": "running",          // queued | running | complete | complete_with_failures
    "sheets": [
      {"id": "…", "number": "E2.1", "title": "First floor power plan",
       "stage": "complete",      // waiting | finding | checking | complete | attention
       "reason": "",             // copy when attention
       "note": "",               // copy on a complete sheet with a caveat (§9: schedules weren't checked)
       "item_count": 42}
    ],
    "complete_count": 9, "total_count": 14
  }
}
```

Stage words map to spec §5 E: *Waiting* (queued), *Finding electrical items* (running, before rows), *Checking schedules* (running, vision), *Complete*, *Needs attention* (failed, with reason). A sheet unreadable at read time is listed with stage `attention` and its `unreadable_reason` — it never gets a job.

### 7.2 Audit

Scope decisions: `actions.commit` kind `scope_decide`, label `Confirmed: <text>` / `Dismissed: <text>` / `Changed: <text>`, `before`/`after` the status and text. Not undoable, same policy as notes. Start takeoff: kind `takeoff_start`, label `Started takeoff`. Run completion: kind `ingest` as today. Every worker write that is not one of these is attributed to the `requested_by` user through the run.

## 8. Client

**Deleted:** `src/lib/engineClient.js`, `src/components/estimate/EstimateDemo.jsx` and its `/estimate` route and nav entry, `store.fetchDocumentFile`, `store.attachEngineTakeoff`, `store.reprocess`, the replace-confirm dialog in `ProcessingStatus.jsx`, and screen C's content sniff (`classifyDoc`) — deleted without a server-side replacement; the estimator sets a file's type, and the filename guess stands until they do.

**Added to the store:** `startTakeoff(projectId)`, `getProcessing(projectId)`, `listScope(projectId)`, `decideScope(id, {status} | {editedText})`.

**Screen C** — the per-file state cell reads the document's `status`: `uploaded`/`processing` → "Reading…", `processed` → "Read · N sheets", `failed` → the reason, with the retry being "remove and upload an unlocked copy". Polls `/processing` every 3 s while any document is `processing`. Primary action stays **Review detected drawings**.

**Screen D** — gains the **Scope** section above the sheet table: a summary line ("14 statements found · 3 confirmed · 1 dismissed"), the list grouped by kind (Included / Excluded / By others / Alternates), each row with the sentence (edited text when present, original in a tooltip), the source document and page, **View source** (the quote, inline expand), and **Confirm / Edit / Dismiss**. Status rendered with the note-status tokens and an icon plus label. The sheet table lists sheets from the store (they exist now, from `read`), with unreadable ones marked. **Start takeoff** posts to the new route and navigates to screen E; on `run_in_flight` it navigates to E without posting.

**Screen E** — a real list from the poll, one row per sheet, stage icon + stage label per spec, the document read states above it. Polls every 3 s until the run is `complete`/`complete_with_failures`, then stops. **Continue to review** enables at the first `complete` sheet. Reload-safe: everything is server state. Copy: "You can leave this page. Sheets keep processing and are reviewable as they finish."

**Notes** — Apply-and-re-run calls `startTakeoff` and shows screen E's list inline, as today's banner does with its stages.

**Review workspace** — a sheet still running shows in the rail with its stage word in place of a count; nothing else changes.

## 9. Copy

Every terminal outcome is one of a fixed set, each naming a recovery:

| what happened | reads | do |
|---|---|---|
| encrypted | Couldn't read — the file is password protected. | Upload an unlocked copy. |
| parser failure, timeout, zero pages | Couldn't read this file. | Try re-saving it as PDF from the original and uploading again. |
| storage or database unreachable after retries | Couldn't open this file right now. | Try again in a few minutes. |
| sheet counting raised | This sheet couldn't be read. | (unreadable in the rail, zero items) |
| sheet job failed terminally | This sheet couldn't be processed. | Start the takeoff again to retry it. |
| vision read failed | Complete — schedules weren't checked on this sheet. | Items stay *Needs attention* where a reading would have confirmed them. |
| no readable drawings | No drawings have been read yet. | Upload a drawing set, or wait for reading to finish. |

No "Something went wrong", no exception names, no model names, no "AI".

## 10. Testing

- **Engine** — `documents.read`, `classification.classify_run`, `sheet.finish` against the corpus fixtures in `api/tests/fixtures/sheets/`, with `test_corpus_sheets.py` re-pointed at `read`; a `scope/` fixture per bid set with hand-written expected statements for the deterministic path; the LLM path asserted for schema and the verbatim-quote rule only.
- **Worker** — an in-process harness (`tests/worker_harness.py`) running the loop against the test database with `MemoryBlobStore` and a fake engine module: `sheet` never before `classify`; two workers, skip-locked, no double-run; child timeout kills and fails with the right copy; transient re-queues, terminal does not; stale reclaim; a failed sheet leaves siblings `complete`; the last sheet flips `project.stage` exactly once under concurrency.
- **Merge** — `merge_sheet` inherits `reprocess.py`'s tests: approved untouched, un-approved updated in place, deliberate delete not resurrected, unmatched inserted, id stability under undo.
- **API** — tenancy tables for the four routes; 409s; the forbidden-word grep on both responses; `PATCH /scope` audit label.
- **Client** — screens C/D/E against a mocked poll; scope confirm/edit/dismiss; the workspace with one sheet complete and four running.
- **Boundary** — `app.main` imports no engine (existing); `app.worker` imports no router (new).

## 11. Not built in B2

- Page rendering and tiles — B3.
- Include/exclude on screen D, discipline/revision/scale corrections, metering events — B4.
- Bid-date priority, per-tenant concurrency caps, dead-letter beyond `max_attempts` — ROADMAP 2.5.
- A scope statement changing a quantity or excluding items — the conversation layer proposes, a person applies.
- Multi-worker deployment beyond "two share a table"; a reaper for orphaned blobs.
- Resumable multipart upload — unchanged from B1.
