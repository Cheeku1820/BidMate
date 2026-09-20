# BidMate — build plan

Seven milestones. Each ends with something running end to end that you can click through, and each is one prompt to the chat ("Continue `PLAN.md` from milestone N"). Acceptance criteria are what "done" means; nothing else in a milestone is optional. Expect roughly one to three agent-days per milestone.

Read `README.md`, `SPEC.md`, `DESIGN.md`, and `STRUCTURE.md` before milestone 0.

---

## Working rules (these are what make it fast)

1. **No per-feature specs, no plan transcripts.** The spec is `docs/SPEC.md`. When a milestone forces a decision the spec doesn't settle, add one dated line to `docs/decisions.md` and, if the spec changes, edit the spec. Never write a design document for a feature.
2. **No subagent-per-task ceremony.** Work through a milestone in one session. Use a subagent only for something genuinely parallel and independent (e.g. copying the engine and getting its tests green while you scaffold the web app).
3. **Tests only where they pay.** The engine (copied, keep green). The API rules listed in `STRUCTURE.md` (boundary, tenancy, rules, totals, merge, scale, export reconciliation, assistant boundary). The eight client tests named there. Nothing that pins interface copy; nothing that tests a mock.
4. **Build the kit before the screens.** Milestone 1 ends with every `components/domain/*` component; from then on a screen is composition. If a screen needs a new primitive, add it to the kit, not to the screen.
5. **Types from the schema.** Never write a wire type by hand on the client; run `npm run api:types` after any schema change and commit the generated file.
6. **Short code.** One-line docstrings; comments only for a non-obvious *why*, citing `SPEC §n`. A router function fits on a screen. If a file passes ~400 lines, split by responsibility.
7. **Commit at every green step** with a one-line subject in sentence case. Push at the end of each milestone. No commit with failing tests.
8. **`CLAUDE.md` stays under 150 lines** and is edited only when a rule changes. It links to `docs/SPEC.md`; it does not restate it.
9. **Show it running** at the end of each milestone: `docker compose up`, `npm run dev`, walk the acceptance criteria in the browser, then stop and report.
10. **Copy, don't rewrite, the engine.** If a corpus test fails after the copy, the copy is wrong — fix the copy, never the engine, unless the failure is a genuine import path.

---

## Milestone 0 — Skeleton, infra, auth

**Build**
- Repo per `STRUCTURE.md`; `docker-compose.yml` (postgres 16, minio + init, api with `--reload`, worker); root `.env.example`; `.gitignore` (`.env`, `corpus/`, `web/dist`, `node_modules`, `__pycache__`).
- `api/`: FastAPI app with request-id middleware, `DomainError` handler, `CamelModel`, `config.py`, `db.py`, Alembic with migration `0001_initial` covering `orgs users sessions invites projects` (the rest arrive with their milestones).
- Auth: signup (creates org + user), login, logout, me, invite create/accept. Cookie sessions, `httpOnly; SameSite=Lax; Secure` in prod. `current_user` dependency; `load_project` helper that 404s across orgs.
- `web/`: Vite + React + TS + Tailwind + shadcn init; `tokens.css` from `DESIGN §2`; Tailwind theme mapped to the tokens; `routes.tsx` with login/signup/invite and an empty `/projects`; `AppShell` with the three-column grid and a placeholder rail; `lib/api/client.ts`; `npm run api:types` script wired to `http://localhost:8000/openapi.json`.
- `infra/copilot/` manifests for `api`, `worker`, `web`, `dev` env, Aurora + S3 addons. Deploy `dev` once so the pipeline is proven (the app can be the health check and the login screen).
- `CLAUDE.md` (≤150 lines): the rules from `SPEC §1–3` in short form, the run/test commands, the conventions from `STRUCTURE.md`.
- Tests: `test_boundary.py` (passes trivially now, stays forever), `test_tenancy.py` scaffold (table-driven; asserts every project-scoped route in `app.routes` has a row), auth round-trip.

**Accept when:** `docker compose up` + `npm run dev` gives a sign-up → login → empty projects page; the same at the Copilot `dev` URL; `npm run api:types` produces `schema.d.ts`; both test suites run green in CI (GitHub Actions: `npm test`, `pytest`, type-check, generated-types freshness).

## Milestone 1 — Component kit, projects, documents in

**Build**
- The kit: every `components/domain/*` component from `DESIGN §3`, with `vocabulary.ts` behind `StatusPill`/`NotePill`, and `DataGrid` complete (sort, resize, visibility, group, inline editors, selection, footer, keyboard).
- `projects/`: models + migration `0002`; A (dashboard, filters, empty state), B (create), Overview, K's details tab, archive. `projectStage.ts` derives the stage filter.
- `documents/` + `storage/`: presign → direct S3 upload → record row → queue `read`; list; retype; delete (row first, then blob); duplicate detection by sha256; C (upload) with real per-file progress and every state in `SPEC §7 C`.
- `jobs/`: queue *(copy)*, `jobs` table, `worker/__main__.py` poll loop, `read_job` *(copy)* wired so an uploaded drawing set produces `sheets` rows (models + migration `0003`), page renders to S3, and scope `notes` (kind `scope`).
- Copy the engine and its tests; get `pytest tests/test_engine_* tests/test_corpus_*` green against `corpus/`.
- Screen D (Confirm drawings): cards, needs-attention section, sheet table with corrections writing to `PATCH /sheets/{id}`, scope section over notes, "Start takeoff" (queues `classify` + `sheet` jobs — the jobs exist even though F isn't built yet).
- Screen E (Processing): polls `GET …/processing`; per-sheet stage words; failure states.

**Accept when:** create a project, upload the corpus's smallest set, watch it read, correct a sheet's scale on D, confirm and dismiss a scope note, press Start takeoff, watch E reach Complete with item counts per sheet. Tenancy test covers every new route. `DataGrid` tests green.

## Milestone 2 — Blueprint review (F)

**Build**
- `takeoff/`: `items`, `warnings`, `actions`, `classifications` (migration `0004`); `merge.py` *(adapted)* as the one write path from `sheet_job`; `rules.py`; `totals.py`; `scale.py` (compound); snapshot route with `version` + ETag; item mutations (approve, reject, unreject, edit, delete, create); `actions.record`.
- `web/screens/blueprint/`: sheets rail, canvas with `TileLayer` + `Markers` in sheet units (`sheetGeometry.ts`), zoom/fit/pan/rotate, layer toggles, measurement + calibration, item panel with evidence crop, summary drawer, finish-review dialog, keyboard shortcuts, `lib/undo.ts`, `lib/selection.ts`, `SaveState`, `UndoToast`, snapshot polling every 4 s.
- `PATCH /sheets/{id}` gains `superseded`; superseded sheets read-only with the banner.

**Accept when:** the corpus set's items appear as markers on the right sheets; select → panel → approve/reject/edit/delete each autosaves with a toast and undoes; layer toggles never change the drawer; a Missing information item cannot be approved (inline copy) and blocks Finish review; a Needs attention item needs the acknowledgment; calibrating a sheet re-derives its measured items in one undoable action; `test_rules`, `test_totals`, `test_merge`, `test_scale` green; re-running the takeoff preserves every approved item.

## Milestone 3 — Spreadsheet (G), export (H), settings (J/K)

**Build**
- G over `DataGrid`: all columns, search, filters, group-by, bulk approve (Ready only, `POST …/bulk-approve`), shared selection with F, blueprint toggle.
- `export/`: preview route (totals by system from `totals.py`, allowances, excluded scope, columns, file name) and `POST …/export` producing `.xlsx` with openpyxl; H screen; blocked while any Missing information item exists.
- `pricing/` models for company settings (migration `0005`); J with all six tabs (markup stored, never computed); K with overrides + "Restore company default" + audit history from `actions`.

**Accept when:** editing a quantity in G updates F's marker panel and the drawer; bulk approve refuses non-Ready rows (test); the exported workbook's totals equal the drawer's to the cent (test reads the xlsx back); every K override has a working restore; `finish-review` sets stage `export`.

## Milestone 4 — Labor and material pricing

**Build**
- `classify_job` *(copy, adapted)* writes `classifications` and per-item costs via catalog + assemblies; `pricing/resolve.py` (project override → company → baseline → unpriced); `project_labor_lines`, `project_material_prices` (migration `0006`); routes.
- Labor and Material pricing screens over `DataGrid` with source labels, inline edits, footer totals, the "Pricing basis" line under the grid — no banner above it.
- Overview and dashboard show cost totals once priced.

**Accept when:** a priced run shows rates and factors from the engine, a company rate overrides the baseline on every row that uses it, a project line overrides the company rate on one row and shows its source label, an unpriced row is never approved-priced in the total (named as excluded in the footer), `test_pricing` green.

## Milestone 5 — Notes and the conversation panel

**Build**
- Notes screen: list with kind/status/usage filters, form, `usage = context` handed to `classify_job` as authoritative input (separate channel from extracted text — by shape), Apply-and-re-run banner, `applied_at`.
- `assistant/`: `conversation_messages` (migration `0007`), screen-descriptor schema (closed set), context builder over the existing read paths with the caps in `SPEC §8`, frozen prompt with `esc()` and `<document_text>` delimiting, SSE route with the error mapping (auth → `not_configured`, rate limit → `busy`, else `interrupted`; every failure logged with the request id), `history_for_model` user-first.
- `web/conversation/`: panel column, thread, `AnswerText` (paragraphs/lists/bold/italic only), read-only composer while streaming, SSE reader, screen context (name from the route table; the blueprint reports sheet + item; the spreadsheet reports filter + search), persistence of open/closed.

**Accept when:** with a key in `.env` the panel answers grounded questions on every project screen and names where a change is made when asked to change something; without a key it says it isn't set up and everything else works; a full review with the panel closed reaches the same state (the milestone-2 acceptance path, re-run); `test_assistant` (fake model) green: stores both turns, streams `delta`/`done`, stores nothing on error, escapes hostile document text, 404 cross-org, 503 without a key, the API process still never imports the engine.

## Milestone 6 — Accuracy (I), operations, polish

**Build**
- `accuracy/`: benchmark upload (xlsx: sheet, item, quantity, unit), comparison against a project's approved items (`compare.py`: count by category, length variance by system, missing, incorrect additions, review time from `actions`), I screen with sample sizes; migration `0008`.
- Operations: structured logs with request ids, `/api/health` checking DB and S3, Copilot `prod` env, backups (Aurora automated + one tested restore, documented in README), a CI deploy from `main`.
- Polish pass against `DESIGN §7` (every required state present on every screen) and `§8` (keyboard through markers, rows, and actions; focus rings; reduced motion); the shortcut reference under Help; the offline banner.
- Delete anything unused: run `ts-prune`/`ruff --select F401`, remove dead exports, confirm no file over 400 lines.

**Accept when:** a benchmark xlsx uploads and the accuracy tables render with sample sizes for a corpus project; `prod` deploys from `main` and serves the app at its CloudFront URL; every acceptance criterion in `SPEC §12` holds in a final click-through; both suites green; `CLAUDE.md` still under 150 lines.

---

## After v1 (not in this plan)

Conversation proposals (preview → apply through the edit path), canvas anchors and point-and-tell, firm-level symbol memory, multi-user (presence, shared undo policy), Cognito/SSO, Accubid/ConEst export, Procore intake, billing. Each is one milestone of the same shape when its time comes.
