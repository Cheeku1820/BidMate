# Backend spine — design

**Date:** 2026-08-07
**Status:** approved, ready for implementation planning
**Scope:** stage 1, first slice — see [`BUILD-STAGES.md`](../../../BUILD-STAGES.md)

---

## What this is

The prototype in `src/` runs entirely in the browser: `localStorage` is the database, `BroadcastChannel` is the realtime layer, and the twelve takeoff items are hand-written seed data. This slice replaces that with a real API, a real database, and real identity — and ports the review workspace onto it — without building the takeoff engine, PDF ingestion, billing, or SSO.

The deliverable is not "a backend." It is the cross-service invariants in [`ROADMAP.md`](../../../ROADMAP.md) becoming enforced facts rather than documented intentions. Eight of the eleven are in scope here; invariants 9–11 govern the conversation layer, which this slice does not build.

### Success criteria

- Two browser windows, two real accounts, one project. An approval in one appears in the other within a poll cycle, with correct attribution.
- Approving a *Missing information* item is refused by the server, not merely hidden by the client.
- Drawer totals come from the same query an export would use.
- A user in one org cannot read or mutate another org's project, proven by test.
- The seed-data demo still runs with no backend.

---

## Decisions settled during design

| Decision | Choice | Why |
|---|---|---|
| Demo mode | Keep, behind a store adapter | The zero-install link is the most persuasive artifact; removal later must be deleting one file |
| Realtime | Polling, full parity | Presence, remote selection, and shared undo all survive; BUILD-STAGES calls polling adequate at this scale |
| Slice width | Backend + login + port screen F | Approval attribution requires real identity; project list can wait |
| Undo | Shared linear stack, field-level merge | Matches `DESIGN.md`; undo appends a compensating action rather than deleting history |
| Auth | Session cookie, invited users | No credential in `localStorage`; behind a boundary so a managed IdP can replace it |
| Architecture | Domain modules with a service layer | Rules live in one findable place per concern |
| `rejected` | Its own field, not a fifth status | Rejection is an inclusion concern, not a review state |

### On `rejected`

`src/lib/data.js` carries `rejected` as a fifth `STATUS` key. It does not become a fifth enum value.

The four labels describe evidence and approval. Rejection describes whether an item belongs in the takeoff at all — wrong trade, duplicate, out of scope. Merging them means every review-state query special-cases one value and the vocabulary CLAUDE.md protects grows a fifth member by accident.

Modelled as `rejected_at` and `rejected_by_user_id`, un-rejecting is also lossless: with an enum, rejection overwrites the previous status and restoring it requires a guess.

### On auth replacement

Stage 1 auth is email, password, and a server-side session. It is written to be replaced:

- Every handler depends on a single `current_user` dependency, never on cookies directly.
- `users.external_id` is nullable from the first migration, so a future identity provider maps onto existing rows instead of forcing a migration mid-rollout.

---

## Architecture

The client stays at the repository root. Moving it would break `.github/workflows/deploy.yml` and the `demo/index.html` path, for no gain.

```
takeoff-review/
  api/
    app/
      main.py              app assembly, router registration
      config.py            settings from environment
      db.py                engine, session dependency
      auth/                password hashing, session cookie, current_user
      identity/            orgs, users, memberships
      takeoff/
        models.py          SQLAlchemy tables
        schemas.py         Pydantic request and response models
        service.py         the only writer — every rule lives here
        totals.py          the single totals query
        router.py          thin HTTP layer
      collab/              presence, snapshot polling
    migrations/            alembic
    tests/
    requirements.txt
  src/                     existing client, unchanged location
  docker-compose.yml       postgres, api, web
```

### Structural rules

1. **Files split by role, not by entity.** `models` / `schemas` / `service` / `totals` / `router`. No searching to find where a thing lives.
2. **Dependencies point one direction.** `router → service → models`. A service never imports a router; nothing imports `main`. This is what allows `takeoff/` to become its own process later without untangling.
3. **Nothing over ~300 lines.** Past that, a file is doing two jobs. `src/App.jsx` at 734 lines is the in-repo cautionary example.
4. **Debuggability is designed in.** Request id threaded through structured JSON logs; Alembic migrations from the first table, never `create_all`.

### Running it

Everything runs in Compose — `postgres`, `api`, `web` — with source mounted into `api` and `web` for hot reload. One command onboards a new machine.

Dev is same-origin: Vite proxies `/api` to the API container, so the httpOnly session cookie works with no CORS configuration and no `SameSite` surprises.

Python is a plain venv with a pinned `requirements.txt`. The machine has Python 3.12 and no `uv`, `poetry`, or `pipenv`; adding a package manager has no upside in this slice.

---

## Data model

| Table | Contents |
|---|---|
| `orgs` | tenant root |
| `users` | `org_id`, email, password hash, display name, avatar colour, nullable `external_id` |
| `sessions` | server-side; the cookie carries an opaque id, so revocation is real |
| `projects` | `org_id`, name, active revision set label |
| `sheets` | number, title, discipline, revision, revision date, scale, `scale_options`, `superseded_at` |
| `items` | sheet ref, symbol, name, description, system, category, quantity, unit, status, `approved_by_user_id`, `approved_at`, `rejected_at`, `rejected_by_user_id`, `x`/`y` or `path`, notes, evidence |
| `warnings` | `item_id` or `sheet_id` (one of), plus `title`, `found`, `why`, `fix`, `where` — the five content fields all NOT NULL |
| `actions` | kind, actor, timestamp, label, `before`/`after` JSON, nullable `undoes_action_id` |
| `presence` | user, project, current sheet and item, last seen |

### Deliberate choices

**`status` is a native Postgres enum** with exactly four values. Adding a fifth then requires a migration written on purpose — the deliberate decision CLAUDE.md asks for. A text column would let one careless insert invent `in_review`.

**The warning's content fields are NOT NULL columns.** A warning row is optional — most items have none — but a row that exists cannot be partial. Invariant 5 says validate at the API boundary; non-nullable columns make a half-written warning unrepresentable rather than merely rejected.

**`superseded_at` is a timestamp, not a boolean.** The totals query filters on it, so invariant 2 lives inside the query rather than in callers' memory.

**The action log has no update or delete path.** Undo appends a row with `undoes_action_id` set. The undo stack is *derived* — actions with no live compensating action, ordered by time — so the shared stack falls out of the data instead of being maintained as separate state.

---

## API surface

```
POST   /api/auth/login              sets session cookie
POST   /api/auth/logout
GET    /api/auth/me

GET    /api/projects
GET    /api/projects/{id}           project, sheets, scale state
GET    /api/projects/{id}/snapshot  items + sheets + presence + undo head
GET    /api/projects/{id}/totals

PATCH  /api/items/{id}              classification, quantity, notes
POST   /api/items/{id}/approve
POST   /api/items/{id}/reject
POST   /api/items/{id}/unreject
DELETE /api/items/{id}
POST   /api/projects/{id}/items/bulk-approve

POST   /api/sheets/{id}/scale       compound action
POST   /api/projects/{id}/undo
POST   /api/projects/{id}/redo
PUT    /api/presence
```

`/snapshot` is the polling workhorse: one request returning everything the workspace renders, carrying a version derived from the latest action id, so an unchanged project answers `304`.

### Where each invariant is enforced

| Invariant | Enforced in |
|---|---|
| Totals computed once | `totals.py`, the only aggregate; `/totals` and the future export both call it |
| Superseded sheets excluded | a clause inside that query, alongside rejected items |
| Layer toggles client-only | no endpoint exists, by design |
| Approval rules authoritative | `service.approve_item`; bulk-approve filters to *Ready to review* and reports what it skipped |
| Warning schema | NOT NULL columns plus the response model |
| Action log append-only | no update or delete path in code, **and a Postgres trigger rejecting `UPDATE`/`DELETE` on `actions`** |
| Internals stop at the boundary | explicit Pydantic response models; ORM objects never serialized directly |
| Every mutation attributable | `commit()` takes an actor; there is no write path around it |

The trigger matters: code discipline holds until someone writes a cleanup migration at 2am. A trigger fails loudly instead.

### Errors

One `DomainError` carrying a machine-readable code and estimator-facing copy, mapped to 4xx centrally. Approving a *Missing information* item returns the reason, and the client shows it inline against the evidence — the estimator meets the rule while looking at the drawing, not later in a dialog.

Unexpected errors return a request id that appears in the message, so support conversations start with something greppable.

---

## Client port

The store adapter is defined in domain terms rather than storage terms:

```
getSnapshot()          approveItem(id)        setScale(sheetId, value)
me()                   rejectItem(id)         undo() / redo()
setPresence(...)       unrejectItem(id)       deleteItem(id)
                       editItem(id, fields)
```

`bulk-approve` exists as an endpoint but has no adapter method yet — its consumer is screen G, which is a later slice. It is built now because the rule it enforces belongs with the other approval rules, and testing it here is cheaper than retrofitting it alongside a new UI.

Two implementations — `src/lib/store/seed.js` (today's `localStorage` and `BroadcastChannel`, seeded from `data.js`) and `src/lib/store/api.js` — selected in `src/lib/store/index.js` by `VITE_DATA_SOURCE`. Removing seed mode later is deleting one file and one branch.

Both return the shape components already consume — `{ items, sheets, hist }` — so `BlueprintCanvas.jsx`, `PlanDrawing.jsx`, and `Symbols.jsx` are untouched. Blast radius is `App.jsx` and `sync.js`.

**Writes are not optimistic.** A mutation calls the API, the top bar shows `Saving…`, the response carries updated state plus the action, and the client renders that. `DESIGN.md`'s save-state design was built for this rhythm, and it avoids a class of reconciliation bugs. Toast labels come from the server's action, keeping action wording in one place.

Polling is `/snapshot` every three seconds with an ETag, plus a presence `PUT` on a slower beat.

Login is a new route: if `/auth/me` returns 401, show it. Nothing else in the app knows about cookies.

---

## Testing

Tests run against **real Postgres in Compose, not SQLite** — enums, the append-only trigger, and JSONB all behave differently, and testing against a substitute is the corner that bites later.

pytest, written before implementation:

1. **Review state machine** — transitions; approving a *Missing information* item is refused server-side
2. **Bulk approve** — accepts only *Ready to review*, reports what it skipped
3. **Totals** — excludes superseded sheets and rejected items; equals the sum of approved
4. **Action log** — the trigger rejects `UPDATE` and `DELETE`; every mutation writes exactly one action
5. **Undo/redo** — compensating action appended; field-level merge preserves a concurrent edit; scale undo reverses both halves as one
6. **Tenancy** — a user in org A cannot read or mutate org B's project
7. **Auth** — session issue and revoke; unauthenticated requests rejected

Tests 1, 2, and 3 are the three things BUILD-STAGES says must never regress. Test 6 must be proven rather than assumed; a tenancy leak is not a bug you fix quietly.

Client tests stay light: a contract test asserting both store implementations satisfy the same interface, since that is what silently drifts once seed mode stops being exercised.

---

## Out of scope

The takeoff engine, PDF ingestion and rendering, the conversation layer, billing and metering, SSO and SCIM, integrations, screens A–E and G–K, the revision conflict flow, WebSocket fan-out, and per-user undo.

Seed data is loaded into the database as one demo project so the workspace has something to render. It is a fixture, not an engine.

## Deferred, with a known home

- **WebSocket fan-out** replaces polling in stage 2; `/snapshot` remains the reconnect path.
- **Managed identity provider** replaces password auth; `external_id` and the `current_user` boundary are the seams.
- **Roles and approval authority** stay open — every account can approve in this slice. `ROADMAP.md` carries the decision.
