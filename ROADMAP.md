# Roadmap

Screen F (blueprint review workspace) is built. The remaining screens are sequenced by what unblocks the most downstream work.

## Next

- **Screen G — takeoff table.** Same data model as the canvas, reshaped. Bidirectional selection sync is already in shared state, so this is mostly table mechanics: grouping, column visibility, and bulk approval restricted to *Ready to review* items only.
- **Revision conflict flow.** Needs the product decisions listed in `DESIGN.md` before design work starts.

## After that

- **Screens A–E** — projects dashboard, create project, upload, confirm detected drawings, processing status. Mostly familiar patterns once the status vocabulary exists.
- **Screen H — export preview.** Must reconcile exactly with the drawer totals.
- **Screen I — accuracy comparison.** Deliberately resists a single headline number; needs sample sizes shown everywhere.
- **Screens J, K — company and project settings.** Every override needs "restore company default."

## Infrastructure

- Replace the `localStorage` sync layer with a real backend and decide the shared-undo model.
- Layer markers over `pdf.js` instead of drawn SVG geometry.
- Per-user undo stacks or a CRDT, depending on the above.
