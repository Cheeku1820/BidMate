# Phasing research — what the corpus and the codebase say

**Date:** 2026-09-21
**Stream:** D — Phases and timeline (`workstreams-2026-09.md` §1.D, §3)
**Purpose:** the evidence behind `docs/specs/phases-and-timeline.md`. Structure and counts are quoted from the two example workbooks in `bid_examples/`; no price from them appears here or anywhere in the repo.

## 1. The Gerber Collision workbook (two phases)

`bid_examples/Gerber Collision & Glass Bid/Renovation for Gerber Collision & Glass.xlsx` — three sheets, all on the firm's 17-column template (`SR #`, `DWG. NO.`, `DETAIL NO.`, `CSI NO.`, `DESCRIPTION`, `QTY.`, `WASTE`, `QTY. W/ WASTE`, `UNIT`, `UNIT LABOR HOURS`, `TOTAL LABOR HOURS`, `LABOR RATE`, `TOTAL LABOR COST`, `UNIT MATERIAL COST`, `TOTAL MATERIAL COST`, `TOTAL`, `TOTAL COST`).

### `SUMMARY BID`

Rows 1–5 are the project header (name, location, date of plans, comments, trade). Row 6 is the column header. Then:

| Row | Description | Qty | Unit | Total labor hours |
|---|---|---|---|---|
| 7 | `26 00 00` ELECTRICAL (section) | | | per-hour labor rate stated on this row |
| 8 | Phase 1 | 1 | LS | 329.05 |
| 9 | Phase 2 | 1 | LS | 71.98 |
| 12 | Sub Total | | | |
| 14–19 | SUB-TOTAL, OVERHEAD AND PROFIT, TAX, BID BOND, CONTINGENCIES, TOTAL TRADES COST | | | |

So each phase is **one lump-sum line on the summary** carrying its total labor hours and total material cost, both typed in (hard values, not cross-sheet formulas). Markup — overhead and profit, tax, bond, contingency — is applied **once, on the summary**, to the sum of the phases. The phase sheets carry the same markup block at their foot, but the summary is where the bid number is made.

### `PHASE I` and `PHASE II (2)`

Each phase sheet is a **complete mini-estimate** with the same skeleton:

```
01 00 00  GENERAL CONDITIONS
            Final & Daily Cleanup                       1 LS
            Project Planning, Coordination & Layout     1 LS
          Sub Total
26 00 00  ELECTRICAL
          Demolition          (per-item removal/relocation lines, EA / LF, with unit hours)
          Light Fixtures      (schedule lines: tag, description, manufacturer, model, watts)
          Lighting Controls   (Phase I only)
          Power Fixtures
          Sub Total
SUB-TOTAL / OVERHEAD AND PROFIT / TAX / BID BOND / CONTINGENCIES / TOTAL TRADES COST
"ANYTHING THAT IS NOT MENTIONED IN THIS DETAILED ESTIMATE ..." (exclusion note)
```

Counts by section:

| Section | Phase I lines | Phase II lines |
|---|---|---|
| General conditions | 2 | 2 |
| Demolition | 9 | 2 |
| Light fixtures | 10 | 7 |
| Lighting controls | 6 | 0 |
| Power fixtures | 24 | 3 |
| **Total priced lines** | **51** | **14** |

Things worth noticing:

- **Sheet numbers tell the phases apart.** Phase I lines cite `ED-1.0`, `ED-2.0`, `E-1.0`, `E-2.0`. Phase II lines cite `XED-1.0`, `XE-1.0`, `XE-2.0`, `XES-1.1` — an `X` prefix on a parallel set of sheets. The phasing lives in the drawing index as two sheet families, not on a "phasing plan" sheet. This is the strongest signal a proposer has: **group sheets by number family, and each family is a phase candidate.**
- **Demolition is per phase, with the same hour-per-unit discipline as new work.** "Existing light fixture to be removed" appears in both phases, cited to `ED-1.0`/`ED-2.0` in Phase I and `XED-1.0` in Phase II, with different unit hours (0.10 vs 0.16) — same task, different phase, different conditions.
- **General conditions are two `LS` lines per phase, zero unit hours.** Cleanup and planning/coordination/layout. Their hours were left at zero in this bid; the template has the rows regardless. They are per-phase because the summary rolls the phase up as one line and the phase has to stand alone.
- **Per-line labor** is `UNIT LABOR HOURS × QTY W/ WASTE`, at one labor rate for the whole bid (a `$P$13` cell reference on the phase sheet). No crew mix, no stage split, no duration anywhere in the workbook. Hours are a total, not a schedule.
- **The exclusion note** at the foot ("anything that is not mentioned in this detailed estimate …") is the same on every sheet — phase-level scope exclusions are not a thing this template models.
- The PDF (`Renovation for Gerber Collision & Glass (1).pdf`) is a scan with no text layer. The roadmap's read of its index: demolition plans D1/D2, coordination plans G3 (electrical) and G4 (security), no dedicated phasing plan.

## 2. The FedEx Office workbook (one phase)

`bid_examples/FedEx Office Bid/Fedex Office.xlsx` — one sheet, `ESTIMATE`, same template, same skeleton with no phase split:

```
01 00 00  GENERAL CONDITIONS          (same two LS lines)
26 00 00  ELECTRICAL
          Power Fixtures              12 lines  (E-003, E-201) — includes "Switch Board MSBS" 1 EA at 42 unit hours,
                                                 "Wireway & Service Disconnect Switch" 1 EA at 12, "Panel Board" 3 EA at 14.5,
                                                 and "Lump sum cost for wiring and conduits" 1 LS at 14
          Low Voltage Fixtures        10 lines  (E-4.00) — data outlets, floor-mounted EMT in LF
          Electrical Panel             2 lines
          Sub Total
markup block, exclusion note
```

24 priced lines. A single-phase bid is the **degenerate case of the phased one**: one phase, whose lump-sum line is the whole bid. The design has to make that case cost nothing — no phase picker, no phase column, no extra sheet in the export — until a second phase exists.

The switchboard, the panels, and the boost transformers on this bid are exactly the rows `api/app/market/classify.py` already classes as `quote_required`. Those are the long-lead candidates: the flag rides the same word list.

## 3. What the codebase already has that this builds on

| Need | Exists as |
|---|---|
| Every countable item, one predicate | `takeoff/totals.py::countable_items` — superseded sheets and rejected items excluded in one place (ROADMAP invariant 1, 2) |
| Hours per item | `takeoff/pricing.py::resolve_labor` — hours per unit × quantity × adjustment × productivity factor; returns `adjusted_hours`. Per-item crew mix (`ProjectLaborLine.crew_*`) is stored, unused |
| Firm-level labor settings | `CompanyLaborRate` — three role rates and one `productivity_factor` (singleton per org) |
| Quote-required detection | `market/classify.py::QUOTE_REQUIRED_WORDS` — switchboard, switchgear, MCC, transformer, SPD, generator, ATS, bus duct, VFD, … |
| The one write path | `takeoff/actions.py::commit()` — every mutation audited, undoable when in `undo.REVERSIBLE` |
| Company-level audit | `pricing_router.py::record_company_action` — for org tables that are never undone |
| Sheet families | `Sheet.number`, `Sheet.discipline`, `Sheet.kind` (plan / schedule / legend / diagram / other) |
| Scope statements | `scope_statements` table, `scope/service.py` — verbatim quotes with a page; stream F's plan record grows from here |
| Project dates | `Project.bid_due_date` only. No award, mobilization, or completion date anywhere |
| Export | `src/components/export/ExportPreview.jsx` builds a CSV client-side from approved + acknowledged rows; no server export module yet. Stream C's Excel-on-the-firm's-template is the eventual home |

Nothing models time. There is no date on any item, sheet, or line; there is no crew table; there is no lead time. The workbook doesn't either — the estimator's schedule, if one existed for these bids, lived somewhere else.

## 4. How the trade sequences the work (from the roadmap's sources)

Per area, in order: **demolition → rough-in (conduit and boxes before walls close) → wire pull (after rough inspection) → gear and panel terminations → trim-out (devices, fixtures, plates) → testing and close-out.** Each stage has its own crew shape (rough-in runs apprentice-heavy under a journeyman; terminations want experienced hands) and its own productivity, so a blended hourly rate over-plans some stages and under-plans others. On a larger job different areas sit at different stages on the same day; a phased renovation like Gerber is the simple version of that — two areas, staggered.

Nothing in an item's labor units says which stage the hours land in. A receptacle's 0.45 hours are split across rough-in (box and conduit), wire pull, and trim (device and plate). A fixture's are mostly trim with some rough-in. A switchboard's 42 hours are mostly gear. The split is a **firm rule per item category**, not a fact in the drawing — the same register as the firm's feet-per-device rule for homeruns (BUILD-STAGES, "measured runs").

## 5. Equipment lead times, 2026

Numbers the roadmap collected (§3, sources linked there):

| Equipment | Lead time |
|---|---|
| Low-voltage switchboards / switchgear | 35–62 weeks |
| Medium-voltage switchgear | 52–80 weeks |
| Pad-mount transformers | ~50 weeks |
| Generators | ~60 weeks |
| Automatic transfer switches | in the same band as the gear they pair with; treat as ~40 weeks until the firm says otherwise |
| Panelboards (standard) | weeks, not quarters — 4–12 typical, but a custom or 4,000 A board is a switchboard in all but name |

Sources: [Industrial Sage — switchgear lead times 2026](https://www.industrialsage.com/switchgear-lead-times-2026/), [Terrapin — switchgear, transformer, generator lead times 2026](https://terrapincg.com/news/switchgear-transformer-generator-lead-times-2026), [Electronate — what estimators must build in](https://www.electronate.app/blog/switchgear-lead-times-2026-data-center-boom).

The consequence for a bid: gear at 50 weeks against a 30-week job means the order date is **before award**, and the honest thing a timeline can do is say so — "order by" a date that has already passed, in plain words, rather than compressing the bar to fit.

## 6. What the corpus does not show

- No crew sizes, no durations, no calendar — the workbooks stop at hours.
- No stage split of hours.
- No lead times or order dates.
- No phase-level exclusions or alternates (the summary has room for more lump-sum lines; none are used).
- The remaining six sets in `bid_examples/` are drawings and specs without a finished workbook (`Kittles Saxony`, `Pulte Sagebriar`, the two TSC sets, `Unalaska`, `United Utility Supply`). Whether any of them carries a phasing plan sheet is unchecked in this pass — all are scans, and reading them is stream F's OCR question, not this stream's.

Everything in the spec beyond §1–2 of this file is therefore a **design choice informed by the trade's practice**, not something the two bids demonstrate. The spec says which is which.

## 7. How contractors turn hours into a schedule today (web research, 2026-09-21)

**The arithmetic is simple and everyone uses the same one.** Crew size = total labor hours ÷ working days ÷ productive hours per day. Electrical Contractor Magazine's "Calculating manpower" column warns that eight productive hours a day is a fiction — six is the number to plan against — and that there are about 20 working days in a month. Best Bid's guide uses the same shape in reverse: hours ÷ 40 = weeks for one person; hours ÷ days = hours needed per day; crew = that ÷ 8. Everyone agrees the estimate's hours are *installation* hours and carry no allowance for lost time; the divisor is where lost time goes. Sources: [ECmag — Calculating manpower](https://www.ecmag.com/magazine/articles/article-detail/your-business-calculating-manpower), [Best Bid — crew size and job tracking](https://bestbidestimating.com/crew-size-and-job-tracking-guide/), [Fennec Lab — NECA labor hours calculator](https://thefenneclab.com/electrical-contractor-operations/electrical-estimating-labor-hours-calculator/).

**Crews are planned per phase, and the GC's schedule is the input.** Best Bid's method breaks the job into phases (site work, slab, rough-in walls, branch circuit rough-in, trim…) and applies the crew calculator to each one separately, because each has its own crew size and duration; the sub's job is to "review the electrical schedule closely and provide input or agree to the timeframes allocated for each phase." The GC gives the window; the sub decides the crew that fits it, or pushes back. So the product's timeline has two modes of use: *given a crew, how long* and *given a window, what crew*. Both are one formula solved for a different unknown.

**Diminishing returns are real and quantified.** A two-person crew is ~85% as productive as two individuals; past four or five on one task a non-working foreman is needed. A default crew per stage should stay in the 2–6 range and the product should not silently propose 14 electricians to hit a date. Source: [Fennec Lab](https://thefenneclab.com/electrical-contractor-operations/electrical-estimating-labor-hours-calculator/).

**Field cost codes are the stages.** Commercial subs track labor against five phase codes — ROUGH (conduit, boxes, sleeves), PULL (wire pull), PANEL (panel and switchgear, terminations, breakers), TRIM (devices, fixtures, plates, directories), PUNCH (corrections). PANEL lands "in the final 20% of the job"; TRIM runs concurrently with other trades; PUNCH is kept apart so trim's productivity reads true. Budget-vs-actual is compared *by phase, weekly, mid-job*. Source: [LogLoon — electrical contractor time tracking](https://logloon.com/blog/electrical-contractor-time-tracking/). These are the same six stages the roadmap named, with "demolition" in front on a renovation and "close-out" as the trade's word for punch and testing.

**Estimating software already tags every line with Phase / Area / System.** Accubid Classic's takeoff breakdown is Drawing, Area, Phase, System, Labor factor, Bid item, and its bid summary groups by any of them; McCormick has the same job-phase concept. NECA labor units in all of them are per item, not per stage — there is no published "40% of a receptacle's hours are rough-in" table. The split of an item's hours across stages is a firm rule, entered once. Sources: [Estimating 101 — Accubid program overview](https://www.electricalestimating101.com/wp-content/uploads/2020/09/Volume-2-pages-14-20.pdf), [McCormick — labor units](https://www.mccormicksys.com/blog/how-accurate-construction-labor-units-transform-bidding-for-projects/), [Electrical Estimating 101 — understanding labor](https://electricalestimating101.com/wp-content/uploads/2020/09/Volume-1-pages-58-63.pdf). The one rule of thumb that recurs: trim is 30–50% of rough-in hours on a full new-construction job.

**What a GC actually asks the sub for is a manpower loading chart, not a Gantt.** "How many people will you have on site, and when?" — a histogram of planned hours per week, converted to a crew at ÷ 40, with the classic ramp-up / peak / ramp-down shape, and its cumulative S-curve. Estimators build it from the GC's stated duration and the estimate's total hours: an average crew for the whole job and a peak. Sources: [Field PM — manpower loading chart template](https://www.field-pm.com/templates/manpower-loading-chart), [Mike Holt forum — manpower loading curves](https://forums.mikeholt.com/threads/manpower-loading-curves-charts.97879/), [Fieldwire — manpower on the Gantt chart](https://help.fieldwire.com/hc/en-us/articles/360030865512-Manpower-on-the-Gantt-Chart). A per-stage bar chart with a crew on each bar *is* that histogram, summed per week — the two views come from the same numbers.

**Long-lead items live in a procurement log, tied to the install activity.** The fields a tracker carries: the installation milestone it enables (area, phase, date), the latest needed-by date, the lead owner, the chain (submittal release → approval → fabrication → ship → deliver → receive/inspect → ready), the current forecast. Order-by = needed-by − (submittal review + fabrication lead + shipping + field-prep buffer). Shown on the schedule as a constraint on the install task, not a separate report. Sources: [Outbuild — long-lead items and critical path](https://www.outbuild.com/blog/long-lead-items-and-critical-path-dependency-tracking-guide), [TeamGantt — tracking long-lead materials](https://www.teamgantt.com/blog/material-lead-time-tracking), [Planning Planet thread](https://planningplanet.com/forums/planning-scheduling-programming-discussion/420434/how-do-u-identify-long-lead-equipment-your-).

**2026 lead times, with more resolution than the roadmap had:**

| Equipment | Weeks | Source |
|---|---|---|
| Standard panelboards | 16–24 (tier 2), 28–48 (major brands) | Electronate |
| LV switchboards, MCCB incomers | ~52 | Electronate |
| LV switchboards, power circuit breaker (ACB) | 84+ | Electronate |
| MV switchgear, 5/15 kV metal-enclosed | 52–72 | Terrapin |
| MV switchgear, 15/27 kV metal-clad | 60–80 | Terrapin |
| Motor control centers | 26–40 | Electronate |
| Busway / bus duct | 20–36 | Electronate |
| Dry-type transformers, ≤2 MVA | 20–32 | Terrapin |
| Pad-mount transformers, ≤5 MVA | 40–65 | Terrapin |
| Diesel generators, 500–1,000 kW | 32–48 | Terrapin |
| Diesel generators, 1,500–2,000 kW | 50–66 | Terrapin |
| Automatic transfer switches | 24–40 | Terrapin |
| Static UPS, 100–500 kVA | 20–32 | Terrapin |

Sources: [Terrapin — switchgear, transformer, generator lead times 2026](https://terrapincg.com/news/switchgear-transformer-generator-lead-times-2026), [Electronate — switchgear lead times 2026](https://www.electronate.app/blog/switchgear-lead-times-2026-data-center-boom), [Industrial Sage — switchgear lead times 2026](https://www.industrialsage.com/switchgear-lead-times-2026/). Electronate's advice to estimators is the product's job description: identify every piece of distribution equipment before pricing, get current lead times from the manufacturer rather than memory, **state lead times explicitly in the bid** as a section listing the major items, map them to the schedule, and recommend ordering at award. Industrial Sage adds: standard configurations ship first, custom goes to the back of the queue.

### What this means for the design

1. The numbers are a **computed baseline the estimator overrides**, never the other way round. Every default (productive hours/day, stage split, crew per stage, lead time) is a firm setting; every derived date on a project is editable; an edit is stored as the estimator's and shown as such.
2. Two solve directions: crew → duration (default), and window → crew (when the GC's dates are known). Same arithmetic.
3. The stage view and the weekly manpower histogram are one dataset. Build the bars; the histogram is a sum.
4. Long-lead is a procurement-log row attached to an item, with order-by counted back from the stage bar that installs it, and a plain sentence when order-by is before award.
5. "State lead times in the bid" is an export concern — the roll-up per phase gains a long-lead section.
