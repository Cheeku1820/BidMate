# API-only foundation — design

**Date:** 2026-08-27
**Status:** approved, ready for implementation planning
**Scope:** stage 1 — see [`BUILD-STAGES.md`](../../../BUILD-STAGES.md)
**Sequence:** this is spec 1 of 2. Spec 2 is *Notes & assumptions*, which is the feature this work exists to make buildable.

---

## What this is

The client currently ships two data sources behind one adapter: a `localStorage` seed store (the default) and a real API store pointed at the FastAPI/Postgres backend in `api/`. This slice **deletes the seed store entirely** and makes the API the only way the app holds data.

It also fixes the gap that makes API-only impossible today: **the backend can serve a takeoff but cannot receive one.** Processing a document set calls `store.attachEngineTakeoff(projectId, payload)` ([`ProcessingStatus.jsx:97`](../../../src/components/documents/ProcessingStatus.jsx:97)), and that method exists only in the seed store ([`seed.js:344`](../../../src/lib/store/seed.js:344)). The api store has no implementation and the backend has no endpoint. Deleting seed without building ingest would leave an application that cannot turn an uploaded drawing set into anything reviewable.

So this slice is one addition and one large deletion, in that order.

### Why now

The requested feature — notes and assumptions that can be marked as engine context — must persist as structured records that the engine reads on an explicit re-run. Building that twice (once against `localStorage`, once against Postgres) would mean writing the note model, the undo integration, and the engine handoff two ways and keeping them in step. It also directly contradicts the request to work against real data rather than fixtures.

### Success criteria

- A fresh database plus a created account reaches a reviewable takeoff using only real uploaded PDFs. No fixture data at any point.
- `grep -ri "seed" src/` returns nothing but incidental prose.
- Re-processing a project replaces its takeoff rather than duplicating it.
- Warnings that do not carry all four fields are rejected at the API boundary.
- A user in one org cannot ingest into, or read, another org's project — proven by test.
- The spreadsheet, export totals, and canvas markers render from ingested data with nothing lost relative to what the seed path carried.

---

## A reversed decision, recorded

[`2026-08-07-backend-spine-design.md`](2026-08-07-backend-spine-design.md) settled the opposite of this. Its decision table reads *"Demo mode — keep, behind a store adapter,"* and one of its success criteria is *"The seed-data demo still runs with no backend."* The reasoning was that a zero-install link is the most persuasive artifact a prototype has.

That reasoning was sound for a prototype being shown. It stops applying once the work is building product functionality against a real engine: the fixture is now a second implementation to maintain, and a second source of truth to be misled by.

The earlier spec anticipated this exact reversal and paid for it in advance — *"removal later must be deleting one file"* — and the seed store was written to honor that. This slice collects that debt. The earlier spec is not amended; this one supersedes its demo-mode decision, and says so here so the contradiction is not left for the next reader to resolve.

**What is lost, stated plainly:** the zero-install demo link, the `file://` single-file build, and the GitHub Pages deployment all stop being able to show a working application. Accepted deliberately.

---

## Decisions settled during design

| Decision | Choice | Why |
|---|---|---|
| Engine→domain mapping | Moves to the server | Domain logic, and invariant 7 keeps processing internals server-side. Leaving it in the client means deleting seed deletes the mapping. |
| Ingest semantics | Replace the project's takeoff in one transaction | Re-processing is the normal case; append would silently double every count |
| Ingest attribution | Writes one `Action` row | Invariant 8 — every mutation attributable, ingest included |
| Approved items on re-ingest | Out of scope here; ingest replaces wholesale | Preserving approvals across re-processing belongs to spec 2's apply-and-re-run, where it is the point rather than a side effect |
| `seed.py` | Deleted, replaced by `create_admin` | "Remove all seed data" taken literally; but a database with no user cannot be logged into, so account creation must survive |
| `demo/index.html` | Deleted with its build config | A seed-mode artifact by construction; cannot work without a backend |
| GitHub Pages workflow | Deleted | It would publish a client with no reachable API — a page that loads and then fails |
| Migration | Additive columns, no data backfill | No production data exists; the only rows are fixtures being deleted anyway |

---

## Part 1 — Backend ingest

### The endpoint

```
POST /api/projects/{project_id}/takeoff
```

Body is the payload `/estimate/project` returns (the shape [`seed-ingest.js`](../../../src/lib/store/seed-ingest.js) maps today). Behavior:

1. Authorize the caller against the project's org, exactly as every other route does.
2. In **one transaction**: delete the project's existing sheets, items, and warnings; insert the mapped rows; set `stage = "review"`.
3. Write one `Action` row (`kind: "ingest"`) carrying who and when.
4. Return the project snapshot, so the client needs no follow-up fetch.

Replacement rather than append is what makes re-processing safe: the same document set processed twice yields one takeoff, not two overlaid.

### The mapping moves to Python

A new `api/app/takeoff/ingest.py` owns what [`seed-ingest.js`](../../../src/lib/store/seed-ingest.js) owns today:

- **Coordinate normalization.** The engine reports PDF points; the canvas works in a fixed 1000×750 space. `x`, `y`, and every entry in `placements` are normalized per sheet using that sheet's `width_pt`/`height_pt`.
- **Symbol inference.** Item name and system to a symbol key, for the marker glyph.
- **Warning shaping,** validated to the four-field schema.

`seed-ingest.js` is then deleted rather than ported twice.

### Warning validation is a boundary rule

A warning missing `title`, `found`, `why`, `fix`, or `where` is **rejected with a 422**, not silently dropped or filled with a placeholder. This is invariant 5, and it is the reason the pipeline cannot emit a partial warning under load. The rejection names the offending field.

### Migration

One Alembic revision, additive. The engine produces — and the built UI already renders — data the current schema has nowhere to put:

**`sheets`:** `takeoff_id`, `page_index`, `width_pt`, `height_pt`, `unreadable_reason`, `ai_reading` (JSONB)

**`items`:** `material_cost`, `labor_hours`, `labor_cost`, `total_cost`, `placements` (JSONB), `ai_confirmed`

Without these, ingesting through the API loses what the seed path carried: the spreadsheet's cost columns, export totals, multi-placement markers, the per-sheet page image lookup, and the unreadable-sheet outcome that [`BUILD-STAGES.md`](../../../BUILD-STAGES.md) requires ("silence reads as completeness"). All nullable or defaulted; no backfill, because the only existing rows are the fixtures this slice deletes.

Cost columns stop at **total direct cost**. No markup, overhead, or profit — invariant 13.

---

## Part 2 — Client: one store

### Deleted

`seed.js`, `seed-fixture.js`, `seed-ingest.js`, `seed-projects.js`, `seed-review.js`, `seed-scale.js`, `seed-undo.js`, `local-transport.js`, and their tests.

`createStore()` collapses to `createApiStore()`; `VITE_DATA_SOURCE` disappears from the code, the compose file, and the docs.

### `data.js` is stripped, not deleted

`lib/data.js` holds two unrelated things. `SHEETS` and `ITEMS` are the twelve-item fixture, imported only by `seed-fixture.js`, and they go. But `STATUS`, `STATUS_ORDER`, and `SYSTEMS` are the **status vocabulary itself** — the spine `CLAUDE.md` protects — imported by nine components including `Pill.jsx`, `BlueprintCanvas.jsx`, `ItemDetailPanel.jsx`, and `spreadsheetColumns.js`. Deleting the file would take the vocabulary with it.

So the fixture arrays are removed and the vocabulary stays. Since the file then contains no data, it is **renamed to `lib/vocabulary.js`** and its nine importers updated — a file called `data.js` holding no data misleads the next reader, and the rename is mechanical. `CLAUDE.md`'s architecture listing is updated to match.

### Added

`attachEngineTakeoff(projectId, payload)` on the api store: POSTs to the new endpoint, caches the returned snapshot through the existing cache path, and surfaces failures as estimator-readable messages the way the rest of `api.js` does.

### Sample-data path removed

`attachSampleTakeoff`, `SampleBanner.jsx`, the `project.sample` flag, and their call sites in [`Workspace.jsx:207`](../../../src/components/Workspace.jsx:207), [`TakeoffSpreadsheet.jsx:218`](../../../src/components/takeoff/TakeoffSpreadsheet.jsx:218), [`ProcessingStatus.jsx:139`](../../../src/components/documents/ProcessingStatus.jsx:139), and `ProjectOverview.jsx` are deleted. A sample takeoff is seed data wearing a different name.

Processing with no reachable engine service therefore has no fallback: it reports the failure and names the recovery action (start the service), which is what [`product-spec.md`](../product-spec.md) §10 asks of error copy anyway.

### Login is unconditional

`App.jsx` keeps its shape — it is already an auth gate — but signing in stops being api-mode-only. `Login.jsx`'s comment about rendering only under the api store goes away.

`HashRouter` **stays**. Its justification in `App.jsx` cites Pages and `file://`, both of which this slice removes, but hash routing is also what keeps a dev-server deep link working without a history-fallback rewrite. Changing it is unrelated churn and a separate decision.

---

## Part 3 — Accounts

`api/app/seed.py` and `tests/test_seed.py` are deleted.

They are replaced by `api/app/create_admin.py` — a CLI that creates **an org and one user, and nothing else**. No project, no sheets, no items, no warnings. It reads `ADMIN_EMAIL` and `ADMIN_PASSWORD` from the environment and exits loudly if either is unset, carrying forward the existing rule that there is no default password.

This is not seed data by any reading: without it, a migrated database contains no user and the login screen cannot be passed. It is the account-creation step every real deployment needs.

---

## Part 4 — What else this touches

**`demo/index.html`**, `vite.demo.config.js`, the `build:demo` script, and `vite-plugin-singlefile` are deleted. The README currently advertises this file as the fastest way to see the project; that section is replaced by the real run instructions.

**`.github/workflows/deploy.yml`** is deleted. It builds the client and publishes it to Pages, where it would now load and immediately fail against an unreachable API. A page that renders a login screen it can never satisfy is worse than no page.

**Docs.** `README.md`, `CLAUDE.md`, and `ROADMAP.md` all document seed mode as the default path and the demo link as the entry point. Each needs its statements about how to run the app rewritten to the single API-only path. `ROADMAP.md`'s "What the prototype maps to" table loses the rows that describe the mapping this slice completes.

---

## Testing

**Backend.** Ingest mapping (coordinate normalization against known page dimensions, symbol inference, placements); transactional replacement (ingest twice, assert one takeoff); four-field warning rejection with the field named; org scoping on ingest; `stage` transition; the `Action` row's attribution.

**Client.** The api store's `attachEngineTakeoff` against a mocked fetch, including the failure message. Existing tests that mock a store keep working — they mock the interface, not the implementation. Tests of the seed store are deleted with it. Tests that pulled `SHEETS`/`ITEMS` in as a convenient fixture are repointed at inline literals; tests that import the status vocabulary keep doing so under its new path.

**Not tested here:** a full end-to-end upload-through-review run. It needs Postgres, the API, the engine service, and a real PDF, which is a manual verification step in this slice rather than CI.

---

## The resulting run loop

```bash
docker compose up -d postgres api
docker compose run --rm api alembic upgrade head
docker compose run --rm \
  -e ADMIN_EMAIL="you@example.com" \
  -e ADMIN_PASSWORD="choose-a-password" \
  api python -m app.create_admin
```

Then the engine service, from `api/`:

```bash
uvicorn estimate_service:app --port 8100
```

Then the client, and sign in with those credentials:

```bash
npm run dev
```

New project → upload drawings → process → review. Every row on screen came from a document the estimator uploaded.

---

## Risks

**The application is non-functional partway through.** Ingest and the migration must land and pass before the seed store is deleted. Sequenced that way in the implementation plan; the deletion commit is the last one, not the first.

**Deletion is wide.** Seed touches tests across the client. The risk is a test that quietly loses its meaning by being repointed at a stub rather than deleted or rewritten. Each repointed test gets read, not just made green.

**The run loop got heavier.** Four processes where there was one static file. That is the accepted cost of testing against real data, and it is worth restating to whoever reads this next expecting `npm run dev` to be sufficient.

**Out of scope, deliberately:** preserving approvals across a re-ingest. Wholesale replacement is correct for "process this set again"; it is wrong for "apply a note and re-run," which is spec 2's problem and where the merge rule belongs.
