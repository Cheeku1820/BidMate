# Documentation

Five documents at the repository root are the entry points: `README.md` (how to run it), `CLAUDE.md` (the rules that are easy to break), `DESIGN.md` (interaction rules), `ROADMAP.md` (the inventory of work to a shippable product), `BUILD-STAGES.md` (the stages that work ships in). Everything else lives here, in folders by what a document *is*, named by what it is about. Dates are in each file's header, not its name — the name is for finding a thing, the header for knowing when it was decided.

| Folder | Holds | When to read it |
|---|---|---|
| `product/` | What the product **is**. Stable references, rarely amended. | Before designing anything: `product-spec.md` (the eleven screens), `frontend-product-design.md` (the thirteen workspaces the product is built against), `agent-architecture.md` (the five engine agents and their contracts), `mvp-approach.md` (the geometry-versus-language split), `accuracy-and-pilot.md` (accuracy policy, information model, pilot operating model). |
| `roadmap/` | What to do next and in what order. | `full-webapp-plan.md` governs sequencing now (phases A–G, with an audit of what each screen actually does). `ROADMAP.md` and `BUILD-STAGES.md` at the root remain the inventory and the stages. |
| `specs/` | One **design** per feature — the decisions, the data shapes, the rules, what is out of scope. | When working on that feature, or on anything that touches it. A spec is amended when execution proves it wrong; the amendment says so. |
| `plans/` | The executable task list for a spec, same file name. A plan in `plans/` is in flight; `plans/done/` holds every executed plan, unchanged — the record of each task, each review, each catch. | `plans/<name>.md` when executing; `plans/done/` when asking "why is it built this way." |
| `archive/` | Superseded documents kept because something still cites them. | Rarely. `full-mvp.md` (superseded by the full plan); `engine-sheet-fidelity-findings.md` (became §1 of that spec). |

## Live and done

| Feature | Spec | Plan | State |
|---|---|---|---|
| Backend spine | `specs/backend-spine.md` | `plans/done/backend-spine.md` | merged |
| Frontend shell and projects | `product/frontend-product-design.md` | `plans/done/frontend-shell-and-projects.md` | merged |
| Takeoff spreadsheet | — | `plans/done/takeoff-spreadsheet.md` | merged |
| API-only foundation | `specs/api-only-foundation.md` | `plans/done/api-only-foundation.md` | merged |
| Notes and assumptions | `specs/notes-and-assumptions.md` | `plans/done/notes-and-assumptions.md` | merged |
| Blueprint evidence | `specs/blueprint-evidence.md` | `plans/done/blueprint-evidence.md` | merged |
| Labor and material pricing | `specs/labor-material-pricing.md` | `plans/done/labor-material-pricing.md` | merged |
| Grounded classification warnings | `specs/grounded-classification-warnings.md` | `plans/done/grounded-classification-warnings.md` | merged |
| Five agents, basic | `product/agent-architecture.md` | `plans/done/five-agents-basic.md` | merged |
| Close the known gaps | — | `plans/done/close-the-known-gaps.md` | merged |
| Engine sheet fidelity | `specs/engine-sheet-fidelity.md` | `plans/done/engine-sheet-fidelity.md` | merged |
| B1 — documents stored | `specs/documents-stored.md` | `plans/done/documents-stored.md` | merged |
| B2 — the engine behind the API | `specs/engine-behind-the-api.md` | `plans/done/engine-behind-the-api.md` | merged |
| Firm price book | `specs/firm-price-book.md` (branch `feat/corpus-price-book`) | — | designed, parked behind Phase B |

## Adding a document

A new feature gets `specs/<feature>.md`, then `plans/<feature>.md` with the same name. When the plan's branch merges, move the plan to `plans/done/` and update the table above. Do not create a `superpowers/` folder or put a date in a filename; the planning tools are told where to write in `CLAUDE.md`.
