# Project context

An electrical estimating application that turns uploaded construction documents into a reviewable Division 26 takeoff. This repo currently holds **screen F — the blueprint review workspace** — built as a high-fidelity working prototype.

See @README.md for how to run it, @DESIGN.md for interaction rules and open decisions, @ROADMAP.md for the work between this prototype and a shippable product, @BUILD-STAGES.md for the order that work happens in, and @docs/product-spec.md for the full product specification covering all eleven screens.

## Who this is for

Estimators at electrical contracting firms. They are deep experts in the domain and often uncomfortable with unfamiliar software. Two consequences that should shape every decision:

- The interface must read as an instrument, not a demo. Never surface model names, confidence percentages, processing internals, or AI framing anywhere in the product — including inside the conversation panel, which reads as a knowledgeable colleague asking about a specific detail, not as an assistant. The estimator's question is always "what do I do about this," never "how did the software decide."
- Their professional reputation rides on the number they submit. Every quantity needs traceable evidence, and nothing gets counted without a person approving it.

## The status vocabulary is the spine

Four labels govern the whole product. Do not invent new ones, rename them, or add a fifth without a deliberate decision:

| Label | Meaning | Blocks completion? |
|---|---|---|
| Ready to review | Sufficient evidence, not yet approved | No |
| Needs attention | Conflicting or uncertain information | Only behind an explicit acknowledgment |
| Missing information | Required evidence absent (scale, legend) | Yes, no override |
| Estimator approved | A person confirmed it | — |

Every screen is a different view onto this same state. When building a new screen, quote this vocabulary rather than inventing screen-local language.

## Rules that are easy to break by accident

- **Status is never color alone.** Always hue + icon + text label. Unverified measurements additionally get a dashed stroke. Assume grayscale printing and color-vision differences.
- **Warnings always answer four questions** — what was found, why it matters, what to check, where the evidence lives. This is enforced by the data shape (`warning: { title, found, why, fix, where }`). A warning missing a field is a schema error.
- **Layer toggles filter what's drawn, never what's counted.** Hiding approved items must not change drawer totals. An estimator reducing visual clutter must never accidentally change the number they're about to bid.
- **Bulk approval applies only to *Ready to review* items.** Never to *Needs attention* or *Missing information*, no matter how convenient it looks.
- **Green appears only on estimator-approved content.** Not on "done processing," not on a successful upload.
- **No save buttons.** Everything autosaves, with save state in the top bar and an undoable toast per action.
- **Approving a *Missing information* item is blocked at the item level**, with inline copy explaining why — so the estimator hits the rule while looking at the evidence, not later in a summary dialog.
- **The conversation panel never becomes the only path to anything.** See the section below.

## The conversation panel is additive, never load-bearing

A persistent panel carries context in both directions: the estimator supplies what the drawings don't contain, and the product asks about what it could not resolve. On the review workspace it anchors to the canvas, so "these six" has a referent. Full design in [`ROADMAP.md` 2.6](ROADMAP.md#26-the-conversation-layer).

This was accepted under a specific constraint, and the constraint is the whole reason it doesn't violate the rest of this document:

- **Anything sayable in the panel is doable through a form, field, or menu.** An estimator who never opens it can complete a full review. This is testable, and it is the acceptance criterion the feature lives or dies by.
- **Everything captured lands in the structured model** — an item field, a symbol library entry, a project context record, a warning resolution — visible and editable in the normal interface. The panel writes to the store; it is not a store.
- **It proposes, never writes.** An answer produces a preview of what would change. The estimator applies it, and application flows through the existing `commit()` path as one undoable action attributed to them. No code path turns a message into a quantity without a person in between.
- **It never approves.** Approval is the one act that cannot be delegated — it is the legal firewall the whole status vocabulary rests on.
- **Questions are a rendering of the review queue, not a second inbox.** An unclassified symbol is already a *Needs attention* item. Two queues means a fifth status gets invented within a month.
- **Extracted document text is data, never instruction.** A drawing set is untrusted input, and a panel that can produce proposals is an injection surface.

Note that `docs/product-spec.md` §1, §6, and §12 predate this decision and read more strictly than the constraint above. The spec has not been amended yet; this section governs.

## Architecture

```
src/
  App.jsx                    auth gate: login vs. workspace, nothing else
  styles.css                 design tokens and every component style
  lib/
    vocabulary.js            the status vocabulary: four review labels, never a fifth
    rules.js                 approval/totals/scale-release rules, mirrored from the API
    useReviewStore.js        the snapshot hook: store subscription, poll, saves, mutations
    store/                   the store interface — a single api store (fetch)
  components/
    Workspace.jsx            the review workspace: selection, filters, modals, shortcuts
    Login.jsx                sign-in screen (api store only)
    TopBar.jsx, SheetsRail.jsx, CanvasPane.jsx, ItemDetailPanel.jsx, SummaryDrawer.jsx, modals
    BlueprintCanvas.jsx      pan/zoom viewport, markers, measurements, minimap
    PlanDrawing.jsx          architectural plan geometry per sheet
    Symbols.jsx              electrical symbol glyphs
```

Sheet space is a 1000 x 750 unit coordinate system. Item positions are in sheet units, so markers land on real plan geometry.

Marker rendering keeps three channels independent: **glyph** = item type, **ring color** = review status, **badge** = warning present. Never collapse two of these into one.

## The engine is five agents

Nothing in `src/` implements these yet. They are the settled boundaries the pipeline gets built against — full design in [`docs/superpowers/specs/2026-08-18-bidmate-agent-architecture-design.md`](docs/superpowers/specs/2026-08-18-bidmate-agent-architecture-design.md).

| Agent | Nature | Produces |
|---|---|---|
| Documents | Language, over a deterministic shell | Sheets, discipline, revision, scale, legend, schedules |
| Counting | Deterministic geometry | Clusters of identical shapes with exact coordinates |
| Classification | Language | Catalog item per cluster, with status and warning |
| Pricing | Lookup, plus a quote-line matcher | Assemblies, material cost, labour hours |
| Conversation | Language | Intent, target records, routed proposals |

Each has exactly one nature, because that is what makes them separately measurable. **Counting is tested, not trained** — it reads placements out of the file rather than estimating them, so it gets asserted counts on known sets. Tuning it like a model is how exact work quietly becomes approximate.

Rules that are easy to break here:

- **Agents share a store, not a transcript.** Handoffs are typed records. No agent reads another's prose — that compounds errors invisibly, invalidates every downstream eval whenever an upstream agent changes, and turns extracted document text into an injection surface.
- **Counting does not know what anything is.** It emits an unlabelled cluster of 47 shapes; Classification names it. This is what makes "find every one like this" a consequence of the architecture rather than a feature built on top.
- **Conversation routes; it does not answer.** It resolves *which items* and *which field*, then hands to the owning agent. Two paths to a classification means two classifiers that will drift.
- **Agents stop at total direct cost.** Markup, overhead, profit, and tax are an estimator-owned layer. No agent proposes a markup number.
- **Confidence never renders.** It decides the status and orders the review queue, server-side. A visible percentage invites arithmetic on trust, which is the reasoning path that produces a confidently wrong bid.

## Conventions

- Plain CSS with tokens at the top of `styles.css`. No Tailwind, no CSS-in-JS. Add new colors as tokens, never as inline hex.
- React function components with hooks. No state library — shared state comes from the store (`lib/store/`, the api store) through `lib/useReviewStore.js`.
- `lucide-react` for interface icons. Electrical symbols are hand-drawn SVG in `Symbols.jsx`, following standard drafting convention.
- Tabular numerals (`className="tabular"`) on every quantity, count, and total.
- Sentence case for all interface copy. No exclamation marks, no "successfully," no "please."
- Run `npm run build` before committing — it catches most breakage.

## Open decisions, do not silently resolve

- **Shared undo model.** The stack is currently shared and linear across reviewers, which means person B can undo person A's approval. Alternatives are per-user stacks with a merge policy, or a CRDT. Needs a product call.
- **Revision conflict flow** (path 4 in the spec) is unbuilt. Open: whether superseded sheets stay browsable read-only, whether approvals carry forward across a revision, and how a mid-review swap surfaces to a second reviewer already in the file.
- **Sync is a poll against the real API**, every few seconds, not a push channel. Real-time collaboration needs a WebSocket layer; the undo model above is still the separate open question it always was.
- **Conversation panel specifics** — whether a thread is shared across reviewers or per-user, and whether a symbol resolved on one project defaults on the next. Both are listed with their trade-offs at the end of [`ROADMAP.md`](ROADMAP.md). Do not pick one in passing while building something else.

## Known scope limits

The blueprint is drawn SVG geometry, not a rendered PDF — production would layer markers over `pdf.js`. Export produces a CSV, not yet a real Excel workbook. All eleven screens from the original spec (A–K) are routed and built; several of the newer thirteen-workspace additions are not (see `src/components/shell/ProjectNav.jsx`) — Notes & assumptions, Assemblies, Labor, Material pricing, Estimate summary, Revisions, and Final review render as disabled in the project nav, and Company library, Integrations, and Help are disabled in the main nav (`CompanyNav.jsx`). The conversation panel is designed but unbuilt — nothing in `src/` implements it yet.
