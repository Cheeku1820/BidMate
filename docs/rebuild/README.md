# BidMate rebuild — handoff

**Date:** 2026-09-20
**Source repo:** `github.com/Cheeku1820/BidMate` at commit `f7c80f3` (the "old app")
**Target:** a new repository, built from these five files

This folder is a complete brief for rebuilding BidMate from the ground up. It replaces the old repo's 41,000 lines of specs, roadmaps, and plan transcripts with about 1,500 lines. Everything a new chat needs is here or in the two things it copies from the old repo (the engine and the bid-set corpus).

| File | What it is |
|---|---|
| `README.md` | This page: the stack, the cloud, what to reuse, and the prompt to start the new chat with |
| `SPEC.md` | What the product is — vocabulary, rules, data model, the eleven screens, the conversation panel, the API |
| `DESIGN.md` | How it looks and behaves — design system, interaction rules, states, accessibility |
| `STRUCTURE.md` | The repository layout, file by file, and the conventions each tier follows |
| `PLAN.md` | The build order — seven milestones with acceptance criteria — and the working rules that keep it fast |

---

## The product in one paragraph

An electrical estimating application. An estimator at an electrical contractor uploads a bid set (drawings, specifications, addenda), the engine reads the drawings and produces a Division 26 takeoff — every device counted, classified, priced, and tied to the sheet it came from — and the estimator reviews it on the blueprint, resolves what the engine could not, approves every quantity, and exports a spreadsheet. Nothing is counted in the number they bid without a person approving it.

## Why a rebuild

The old app works — its engine is proven against real bid sets and its review workspace is right — but the codebase grew a process around it (per-feature specs, 3,000-line plan transcripts, a review gate per task, multi-user machinery for a single-user pilot) that made every change slow. The rebuild keeps the engine, the product spec, and the interaction rules, and drops everything else.

## Tech stack

| Tier | Choice | Why |
|---|---|---|
| Web | Vite + React 18 + TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, React Router 6 | Screens become composition of a component kit; no hand-written CSS file; types come from the API |
| API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 (camelCase on the wire) | The engine is Python; one language for everything server-side |
| Worker | Same Python image, `python -m app.worker`; a Postgres-table job queue | The engine runs here, never in the API process |
| Database | Postgres 16 (Aurora Serverless v2 on AWS; a local container in dev) | |
| Files | S3 (`app/storage/blobstore.py`, S3-compatible; MinIO or a local-disk store in dev) | Drawing sets are 100–500 MB; never on the API's disk |
| Model | Anthropic SDK, `claude-opus-5` | Classification, scope extraction, the conversation panel |
| Types across the boundary | FastAPI's OpenAPI → `openapi-typescript` → `openapi-fetch` | Zero hand-written wire mapping |
| Infra | AWS Copilot manifests in `infra/` | One command stands up an environment from a laptop |

## AWS layout

```
CloudFront ── S3 (web static build)
     │
     └── ALB ── App: api (Copilot Load Balanced Web Service, Fargate)
                       │
                       ├── Aurora Serverless v2 (Postgres)   ← Copilot storage addon
                       ├── S3 bucket (documents, renders)    ← Copilot S3 addon
                       └── SSM Parameter Store (secrets)     ← ANTHROPIC_API_KEY, session secret
             App: worker (Copilot Backend Service, Fargate; no ingress; 2 vCPU / 4 GB)
```

- `copilot app init bidmate`, `copilot env init --name dev`, then `copilot deploy` per service. Manifests live in `infra/copilot/`.
- The worker service has no load balancer; it polls the `jobs` table. Its task size is what bounds a hostile PDF.
- Migrations run as a one-off task before each API deploy (`copilot task run` with `alembic upgrade head`), never on container start.
- Local development: `docker compose up` (Postgres + MinIO + api + worker) and `npm run dev` in `web/`, exactly as the old repo does today.

## What to copy from the old repo (verbatim, then adapt only imports)

1. **The engine** — `api/app/engine/` at commit `f7c80f3`. Files: `assemblies.py catalog.py classification.py context.py counting.py documents.py legend.py llm.py page_frame.py pricing.py regions.py rows.py scope.py sheet.py sheet_kind.py tiles.py title_block.py`. Skip `__main__.py`, `pipeline.py`, `contracts.py`, `conversation.py`, `estimate.py` (a CLI, a dataclass layer, and a deterministic router the rebuild does not use; `estimate.py`'s two note-text helpers move into `classify_job`).
2. **The engine's tests** — `api/tests/test_engine_*.py`, `test_corpus_*.py`, `test_eval_rubric.py`, `tests/bid_set.py`, `tests/fixtures/`. They are the proof that counting is exact; keep them green.
3. **The corpus** — `bid_examples/` (gitignored: real, NDA'd drawing sets). Copy the folder to the new repo's `corpus/` on the same machine; it is never committed.
4. **The job queue** — `api/app/jobs/queue.py` (claim with `FOR UPDATE SKIP LOCKED`, retry, stale reclaim). It is 200 lines and correct.
5. **The blob store** — `api/app/documents/blobstore.py` (S3 over boto3 + an in-memory store for tests).
6. **The worker's three job bodies** — `api/app/worker/{read_job,classify_job,sheet_job}.py` and `render_job.py`, minus the `sandbox.py` subprocess wrapper.

Everything else — every screen, the API routes, the schemas, the store, the CSS, the notes/scope/collab/undo machinery, the docs — is rebuilt from `SPEC.md` and `DESIGN.md`.

## The prompt to start the new chat with

Paste this as the first message of a fresh Claude Code session in an empty directory:

> Build BidMate from the handoff in `docs/rebuild/` (I've copied the five files into this repo). Read `README.md`, `SPEC.md`, `DESIGN.md`, `STRUCTURE.md`, and `PLAN.md` in full before doing anything. The old repo is at `~/Documents/takeoff-review` — copy the engine, its tests, the queue, the blob store, and the worker job bodies from there exactly as `README.md` lists them; do not copy anything else from it. Then execute `PLAN.md` milestone by milestone, following its working rules: no per-feature spec documents, no plan transcripts, tests only where `PLAN.md` says they pay, one commit per completed milestone step, and a `CLAUDE.md` under 150 lines that you write in milestone 0 and keep current. Start with milestone 0 and stop at the end of each milestone to show me it running.

Then, for each later session: "Continue `PLAN.md` from milestone N."
