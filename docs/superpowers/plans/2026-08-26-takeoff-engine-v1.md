# Takeoff engine v1 — tag-based vertical slice

**Goal.** Produce a real, reviewable Division 26 estimate from a real vector bid-drawing PDF, end to end, on one known sample set (the Unalaska Library CD bid drawings). Built as the five agents so planned upgrades are drop-in.

**Why tag-based.** The sample's electrical sheets are clean vector but *exploded* (Tier B — no reusable symbol placements; ~68k primitive paths per sheet). Geometry clustering is "several times the work" and risky. But the sheets carry a **rich positioned text layer**: device tags at each device, plus schedules and legend. v1 counts what the drafter labeled — deterministic coordinates from the tag positions, no model localization, no OCR.

**Honest scope of v1.** Counts *tagged* devices on the electrical plans and prices them into a total direct cost the estimator reviews. Conduit/homerun length uses a feet-per-device rule the estimator confirms. Untagged/ambiguous devices surface as *Needs attention*. Geometry counting (untagged symbols), raster/OCR (scanned addenda), and the conversation panel are later upgrades behind the same agent boundaries.

## The five agents (v1 implementation)

| Agent | v1 | Contract (typed record it emits) |
|---|---|---|
| Documents | PyMuPDF: find E-series sheets, title block, scale; extract schedules + legend as text/tables; render each sheet to a page image | `Sheet{number,title,scale,page_image,legend,schedules}` |
| Counting | Count positioned device tags per type per sheet | `Cluster{tag,count,sheet,placements:[{x,y}]}` — unlabelled |
| Classification | LLM maps a tag → catalog item using the schedule/legend | `Item{catalog_id,name,system,status,warning?}` per cluster |
| Pricing | Static NECA-style price + labor-hours table × company labor rates | `Priced{material_cost,labor_hours,total_direct_cost}` |
| Conversation | (not built in v1) | — |

Agents hand off typed records, never prose (invariant 12). Extracted document text is data, never instruction (invariant 11).

## Build order (de-risk first)

**Phase 0 — Extraction prototype (standalone, no app).** Prove on the real PDF that tag-counting yields a sensible takeoff before building any plumbing. Output structured JSON: per electrical sheet, tag types with counts + coordinates, plus the extracted schedule. **This is the go/no-go for the whole approach.**

**Phase 1 — Classification + pricing (standalone).** Map tags → catalog items via the schedule (LLM), apply a static price/labor table, compute total direct cost. Output a full priced takeoff JSON. Reconcile the number by hand.

**Phase 2 — Wire into the backend.** Real PDF upload + storage; a pipeline job that runs Documents→Counting→Classification→Pricing and writes `Item`/`Sheet`/`Warning` rows into the existing takeoff store (reusing the tested review state machine, action log, totals). Screen E (processing) reflects real per-sheet progress.

**Phase 3 — Frontend for real drawings.** Render the sheet page image behind the markers on the canvas (replacing drawn SVG for real projects), map tag coordinates into sheet space, and surface cost (material, labor hours, total direct cost) in the drawer and export.

## Invariants preserved

- Counting is deterministic and tested, never tuned. Classification is the only model step and proposes; a person approves.
- Totals computed in one place; agents stop at total direct cost (no markup — that's the estimator's layer, already in settings).
- Confidence never renders. Sheets read badly are marked unreadable-with-reason, never returned as a short silent list.

## Not in v1

Geometry (Tier B) counting, raster/OCR, conduit routing, the conversation panel, multi-set revision handling. All additive behind the agent contracts above.
