# BidMate — repository structure

One repo, three deployables (`web`, `api`, `worker` — the worker is the `api` image with a different command), one `infra/` folder. Every path below exists by the end of `PLAN.md`; files marked *(copy)* come from the old repo verbatim.

```
bidmate/
├── CLAUDE.md                      ≤150 lines: the rules that are easy to break, how to run, how to test
├── README.md                      how to run locally and deploy; nothing else
├── docker-compose.yml             postgres, minio, minio-init, api, worker (dev only)
├── .env.example                   ANTHROPIC_API_KEY=, DATABASE_URL=, BLOB_* (root .env is gitignored)
├── docs/
│   ├── SPEC.md  DESIGN.md  STRUCTURE.md  PLAN.md     (this handoff, kept current)
│   └── decisions.md               one line per decision that changed the spec, dated
│
├── web/                           Vite + React 18 + TypeScript + Tailwind + shadcn/ui
│   ├── index.html  vite.config.ts  tailwind.config.ts  tsconfig.json  package.json
│   ├── components.json            shadcn config
│   └── src/
│       ├── main.tsx               QueryClient, Router, providers
│       ├── app/
│       │   ├── routes.tsx         the one place that knows every URL
│       │   ├── AppShell.tsx       rail | screen | conversation panel grid
│       │   ├── CompanyNav.tsx  ProjectNav.tsx  TopBar.tsx
│       │   └── auth/              Login.tsx  Signup.tsx  AcceptInvite.tsx  useSession.ts
│       ├── screens/               one folder per SPEC §7 screen; a screen file plus its parts
│       │   ├── projects/          ProjectsDashboard.tsx  NewProject.tsx  ProjectOverview.tsx
│       │   ├── documents/         UploadDocuments.tsx  ConfirmDrawings.tsx  Processing.tsx  ScopeSection.tsx
│       │   ├── blueprint/         Blueprint.tsx  SheetsRail.tsx  Canvas.tsx  TileLayer.tsx  Markers.tsx
│       │   │                      ItemPanel.tsx  SummaryDrawer.tsx  FinishReviewDialog.tsx  Calibration.tsx
│       │   ├── spreadsheet/       Spreadsheet.tsx  columns.ts  BulkApproveBar.tsx
│       │   ├── notes/             Notes.tsx  NoteForm.tsx  ApplyNotesBanner.tsx
│       │   ├── pricing/           Labor.tsx  MaterialPricing.tsx  columns.ts
│       │   ├── export/            ExportPreview.tsx
│       │   ├── accuracy/          Accuracy.tsx  BenchmarkUpload.tsx
│       │   └── settings/          CompanySettings.tsx  ProjectSettings.tsx
│       ├── conversation/          ConversationPanel.tsx  Thread.tsx  AnswerText.tsx  screenContext.tsx  examples.ts
│       ├── components/
│       │   ├── ui/                shadcn primitives (generated; never hand-edited beyond tokens)
│       │   └── domain/            StatusPill  NotePill  WarningCard  DataGrid  PageHeader  SaveState
│       │                          UndoToast  EmptyState  Drawer  SidePanel  ConfirmDialog  Symbol  Marker
│       ├── lib/
│       │   ├── api/
│       │   │   ├── schema.d.ts    GENERATED from the API's OpenAPI (`npm run api:types`) — never edited
│       │   │   ├── client.ts      openapi-fetch client with credentials: "include" and the error shape
│       │   │   ├── queries.ts     TanStack Query hooks per resource (useSnapshot, useDocuments, …)
│       │   │   └── stream.ts      SSE reader for the conversation panel
│       │   ├── vocabulary.ts      the four statuses, stages, note kinds: keys, labels, icons, tokens
│       │   ├── rules.ts           client mirrors of server rules: canApprove, countsTowardTotals, bulkApprovable
│       │   ├── undo.ts            the per-session inverse-action stack
│       │   ├── selection.ts       shared blueprint/spreadsheet selection (a small store)
│       │   ├── sheetGeometry.ts   1000×750 sheet units ↔ pixels, tile math
│       │   └── format.ts          money, hours, quantities, times
│       └── styles/
│           ├── tokens.css         DESIGN §2 as CSS variables
│           └── globals.css        Tailwind directives + the reset; nothing component-specific
│
├── api/                           Python 3.12, FastAPI, SQLAlchemy 2, Alembic
│   ├── Dockerfile  requirements.txt  alembic.ini  pyproject.toml (ruff, pytest config)
│   ├── migrations/versions/       0001_initial.py … (one migration per milestone, not per table)
│   ├── app/
│   │   ├── main.py                app, middleware (request id, no-store cache headers), routers
│   │   ├── config.py              pydantic-settings; nothing defaults to a real bucket or key
│   │   ├── db.py                  engine, SessionLocal, Base, get_db
│   │   ├── errors.py              DomainError(code, message, status) → {"detail": {code, message}}
│   │   ├── schemas_base.py        CamelModel (alias generator) every schema inherits
│   │   ├── auth/                  router.py  service.py  models.py  passwords.py  dependencies.py (current_user)
│   │   ├── projects/              router.py  service.py  models.py  schemas.py  (projects, overview, invites, archive)
│   │   ├── documents/             router.py  service.py  models.py  schemas.py  presign + record + delete
│   │   ├── storage/               blobstore.py *(copy)*  keys.py (tenant-scoped key builder)
│   │   ├── takeoff/               models.py (sheets, items, warnings, actions, classifications)
│   │   │                          schemas.py  router.py (snapshot, items, sheets, finish-review)
│   │   │                          rules.py (status transitions, approvable, bulk)  totals.py (THE query)
│   │   │                          merge.py (the one engine→store write path)  scale.py (compound)
│   │   │                          actions.py (record(db, actor, project, kind, label, before, after))
│   │   ├── notes/                 router.py  service.py  models.py  schemas.py  (notes incl. scope; apply → run)
│   │   ├── pricing/               router.py  resolve.py (project override → company → baseline)  models.py  schemas.py
│   │   ├── export/                router.py  xlsx.py (openpyxl; reads totals.py)
│   │   ├── accuracy/              router.py  compare.py  models.py (benchmark sets)
│   │   ├── assistant/             router.py  service.py  context.py  prompt.py  llm.py  models.py  schemas.py
│   │   ├── jobs/                  queue.py *(copy)*  models.py  router.py (start run, processing)  status.py
│   │   ├── worker/                __main__.py (poll loop)  handlers.py  read_job.py  classify_job.py
│   │   │                          sheet_job.py  render_job.py *(copy, minus sandbox)*
│   │   ├── engine/ *(copy)*       assemblies catalog classification context counting documents legend llm
│   │   │                          page_frame pricing regions rows scope sheet sheet_kind tiles title_block
│   │   └── observability.py       request-id middleware, logging config
│   └── tests/
│       ├── conftest.py            test database (TEST_DATABASE_URL, never DATABASE_URL), client, org, user, project, sheet, item
│       ├── test_boundary.py       app.main never imports app.engine or pymupdf; worker never imports a router
│       ├── test_tenancy.py        every project-scoped route → 404 cross-org, 401 signed out (table-driven, self-checking)
│       ├── test_rules.py          transitions, Missing blocks approve, bulk = Ready only
│       ├── test_totals.py         superseded and rejected excluded; drawer == export
│       ├── test_merge.py          re-run preserves approved; vanished page → unreadable sheet
│       ├── test_scale.py          compound action + its inverse
│       ├── test_notes.py  test_pricing.py  test_export.py  test_assistant.py (fake model)  test_accuracy.py
│       ├── test_engine_*.py  test_corpus_*.py  test_eval_rubric.py  bid_set.py  fixtures/  *(copy)*
│       └── test_queue.py *(copy)*
│
├── infra/
│   └── copilot/
│       ├── .workspace             application: bidmate
│       ├── environments/dev/manifest.yml     prod/manifest.yml
│       ├── api/manifest.yml       Load Balanced Web Service; health /api/health; secrets from SSM
│       ├── worker/manifest.yml    Backend Service; cpu 2048, memory 4096; count 1
│       ├── web/manifest.yml       Static Site; build from web/dist
│       └── api/addons/            aurora-serverless-v2.yml  documents-bucket.yml
│
└── corpus/                        gitignored; the real bid sets (copied from the old repo's bid_examples/)
```

## Conventions

**Web**
- TypeScript strict. No `any` at a boundary: everything from the API is typed by `schema.d.ts`.
- Data: TanStack Query hooks in `lib/api/queries.ts`; components never call `fetch`. Mutations invalidate the snapshot and push an inverse onto `lib/undo.ts`.
- Styling: Tailwind classes with token names only (`bg-surface`, `text-ink-2`, `border-line-1`, `text-status-attention`). No inline hex, no CSS modules, no styled-components. Component-specific CSS does not exist; if a rule seems needed, it belongs in the kit.
- A screen file composes `components/domain/*`; it does not define its own table, pill, dialog, or toast.
- One `routes.tsx`; one `vocabulary.ts`; one `rules.ts`. Adding a screen is a route, a folder under `screens/`, and a nav entry.
- Tests: Vitest + Testing Library, only for `lib/rules.ts`, `lib/undo.ts`, `lib/sheetGeometry.ts`, `DataGrid`, `Marker`/`StatusPill` (status never color alone), the finish-review dialog's blocking, bulk-approve's filter, and the conversation panel's "never writes". No tests that assert copy strings.

**API**
- Router → service → models. Routers parse and authorize (`load_project`); services hold rules; models are plain. A router function fits on one screen.
- Every schema extends `CamelModel`; the OpenAPI output is the contract; `npm run api:types` regenerates the client types and CI fails if the generated file is stale.
- Every mutation calls `actions.record(...)` and returns `{ ...record, label }`.
- Docstrings: one line saying what, a second only when the *why* is not obvious. No essays. The rule lives in `SPEC.md`; the code cites the section (`# SPEC §3: bulk approve is Ready only`).
- Migrations: one per milestone, hand-checked, with constraints (check constraints on every closed set, the warning columns NOT NULL).
- The worker imports the engine; `app.main` never does; `test_boundary.py` enforces both in a subprocess.
- Tests hit a real Postgres (`TEST_DATABASE_URL`), dropped and recreated per session; the model is faked in `test_assistant.py` and `test_engine_llm_prompt.py`.

**Infra**
- Secrets only in SSM (`/bidmate/dev/ANTHROPIC_API_KEY`, `/bidmate/dev/SESSION_SECRET`); manifests reference them, never contain them.
- `copilot deploy --name api --env dev` builds the Dockerfile; migrations run as `copilot task run --command "alembic upgrade head"` first.
- The web static site is built in CI (`npm ci && npm run build`) and deployed with `copilot deploy --name web`.
