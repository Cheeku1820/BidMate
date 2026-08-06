# Project context

An electrical estimating application that turns uploaded construction documents into a reviewable Division 26 takeoff. This repo currently holds **screen F — the blueprint review workspace** — built as a high-fidelity working prototype.

See @README.md for how to run it, @DESIGN.md for interaction rules and open decisions, @ROADMAP.md for what's next, and @docs/product-spec.md for the full product specification covering all eleven screens.

## Who this is for

Estimators at electrical contracting firms. They are deep experts in the domain and often uncomfortable with unfamiliar software. Two consequences that should shape every decision:

- The interface must read as an instrument, not a demo. Never surface model names, confidence percentages, processing internals, or AI framing anywhere in the product. The estimator's question is always "what do I do about this," never "how did the software decide."
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

## Architecture

```
src/
  App.jsx                    shell, sync, undo/redo, review actions, modals
  styles.css                 design tokens and every component style
  lib/data.js                seed sheets and items, status definitions
  lib/sync.js                shared state, presence, identity
  components/
    BlueprintCanvas.jsx      pan/zoom viewport, markers, measurements, minimap
    PlanDrawing.jsx          architectural plan geometry per sheet
    Symbols.jsx              electrical symbol glyphs
```

Sheet space is a 1000 x 750 unit coordinate system. Item positions are in sheet units, so markers land on real plan geometry.

Marker rendering keeps three channels independent: **glyph** = item type, **ring color** = review status, **badge** = warning present. Never collapse two of these into one.

## Conventions

- Plain CSS with tokens at the top of `styles.css`. No Tailwind, no CSS-in-JS. Add new colors as tokens, never as inline hex.
- React function components with hooks. No state library — shared state lives in `lib/sync.js`.
- `lucide-react` for interface icons. Electrical symbols are hand-drawn SVG in `Symbols.jsx`, following standard drafting convention.
- Tabular numerals (`className="tabular"`) on every quantity, count, and total.
- Sentence case for all interface copy. No exclamation marks, no "successfully," no "please."
- Run `npm run build` before committing — it catches most breakage.

## Open decisions, do not silently resolve

- **Shared undo model.** The stack is currently shared and linear across reviewers, which means person B can undo person A's approval. Alternatives are per-user stacks with a merge policy, or a CRDT. Needs a product call.
- **Revision conflict flow** (path 4 in the spec) is unbuilt. Open: whether superseded sheets stay browsable read-only, whether approvals carry forward across a revision, and how a mid-review swap surfaces to a second reviewer already in the file.
- **Sync is single-machine** (`BroadcastChannel` + `localStorage`) to demo the interaction model without a backend. Production needs a real service.

## Known scope limits

The blueprint is drawn SVG geometry, not a rendered PDF — production would layer markers over `pdf.js`. No document ingestion, no detection, no export. Screens A–E and G–K are not built.
