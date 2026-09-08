# Engine sheet-fidelity findings

Measured against the real bid set (Unalaska Public Library, 94 pages, 14
detected electrical sheets) on `da762f7`. Every number below is
reproducible from `api/` with `.enginevenv/bin/python`.

## 1. Sheet numbers are non-deterministic across processes

`api/app/engine/documents.py:83`

```python
return max(set(ids), key=ids.count)
```

`set()` iterates strings in hash order, randomized per process; `max()`
breaks ties by iteration order. Same PDF, three consecutive processes,
page 89 resolved to `E7.1`, then `E6.2`, then `E4.1`. Stable within a
process, which is why a single test run never catches it.

This breaks the fourth field of the warning schema — `where` can name a
sheet the evidence is not on, and reprocessing shuffles it again.

Fix: deterministic tie-break — most frequent, then first appearance.

```python
counts = Counter(ids)
best = max(counts.values())
return next(i for i in ids if counts[i] == best)
```

## 2. Schedules, legends and one-lines are counted as device plans

No sheet-kind classification exists; every page is treated as a plan.

| page | reads as | actually is | placements |
|---|---|---|---|
| 80 | E0.1 | legend / abbreviations / one-line | 14 |
| 81 | E0.2 | luminaire schedule | 30 |
| 82 | E0.3 | panel schedule | 25 |
| 83 | (varies) | one-line diagram | 7 |
| 90 | E5.1 | equipment schedule | 22 |
| 91 | E6.1 | lighting controls | 8 |
| | | **phantom total** | **106** |
| | | real plans | 197 |

106 of 303 placements — 35% of the takeoff — come from non-plan sheets.
This is the source of the `VA` (12), `CKT` (9), `AMP` (8), `NOT` (3) and
`OFF` (8) clusters: panel-schedule column headers and annotation words.

Constraint on the fix: a skipped sheet must stay visible with its real
role named. A schedule sheet silently absent from the rail reads as
completeness — the failure mode BUILD-STAGES.md stage 1 names explicitly.
E0.1 must still feed `legend.py`; it only stops contributing devices.

## 3. Fourteen pages collapse to eleven sheet numbers

`E5.1`, `E6.1`, `E7.1` each appear twice. Clusters therefore split: E4.1
carries `D` twice, `F` twice, `J` twice. That defeats "find every one
like this" — one correction resolves half the instances.

## 4. Every sheet title is the fallback string "Electrical plan"

All 14. Nothing parses the title-block title field. In the sheet rail the
estimator cannot distinguish the panel schedule from the power plan.

## 5. No drawing-region detection

`region` is `(73, 47)-(2007, 1536)` on every sheet — the full page less a
right strip. A schedule block on a real plan sheet is still counted.

## Downstream effect

45 clusters: 10 `ready`, 35 `attention` (78%). 18 rows priced at zero,
covering 115 of 303 units (38%). Most of that resolves once 2 and 5 land.

Scale is absent on 7 of 14 sheets.

## Suggested order

1 (one line) -> 2 (largest accuracy win) -> 3 and 4 together (both are
title-block parsing) -> 5.
