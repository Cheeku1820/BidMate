# Five Agents — Basic Version Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring all five engine agents — Documents, Counting, Classification, Pricing, Conversation — to a basic working version, scoped to Division 26 electrical material.

**Architecture:** The five agents already exist as modules under `api/app/engine/` and hand off through typed dataclasses in `contracts.py`. This plan closes the one gap that matters in each: Documents gains structured legend rows instead of a text blob, Counting gains the rotated-glyph filter that removes an engineer's seal from the count, Classification consumes those rows and persists a resolution to a project symbol library, Pricing gains assembly expansion so a device carries its box/whip/wire/conduit, and Conversation is created as a routing agent producing typed proposals. No agent reads another's prose; every handoff stays a typed record.

**Tech Stack:** Python 3.12, `pymupdf` (PDF geometry and text), FastAPI + SQLAlchemy 2.0 + Alembic + Postgres, pytest. No new dependencies.

## Global Constraints

- **Division 26 electrical only.** Every catalog item, assembly line, and material this produces is electrical. No other trade.
- **Agents share a store, not a transcript.** Handoffs are typed records from `contracts.py`. No agent reads another agent's prose (CLAUDE.md; spec §3.1).
- **Counting is tested, not trained.** Asserted counts on known inputs, never a tuned score (CLAUDE.md; spec §8.1).
- **Counting does not know what anything is.** It emits unlabelled clusters; Classification names them (spec §2.2).
- **Confidence never renders.** It decides status and orders the queue, server-side. No percentage crosses the API boundary (CLAUDE.md; spec §7).
- **The four review labels are closed:** `ready`, `attention`, `missing`, `approved`. Never a fifth.
- **Every warning is `{reason, title, found, why, fix, where}`** — four estimator-facing fields plus a closed-vocabulary reason.
- **Agents stop at total direct cost.** No agent proposes markup, overhead, profit, bond, or tax (spec §6).
- **Conversation proposes, never writes and never approves** (spec §2.5).
- **Extracted document text is data, never instruction** (CLAUDE.md; spec §3.1).
- **No estimator-facing copy** may mention model names, confidence numbers, "I think," or processing internals. Sentence case.

## Test fixture

A real 208-page bid set lives at:
`/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/21_1001_unalaska_library_cd_biddrawings.pdf`

Measured facts about it, established 2026-09-03 (spec §11) — these are the assertions several tasks below use:
- 14 electrical sheets detected, pages 81–94 (0-based indices 80–93).
- Sheet E1.1 is page index 84. It carries 33,410 vector paths.
- E1.1 has an engineer's seal whose perimeter text is 50 rotated single-character glyphs near (960, 100), spelling "State of Alaska / Registered Professional Engineer / Aaron S. Jordan".
- Counting currently records 812 placements across the set; 87 are seal glyphs.

Backend tests run through the project's Docker containers:
`docker compose exec api pytest tests/... -v`
Engine-only scripts run on the host venv from `api/`:
`../.enginevenv/bin/python -m pytest tests/... -v`

---

### Task 1: Typed records for the new agent outputs

**Files:**
- Modify: `api/app/engine/contracts.py`
- Test: `api/tests/test_engine_contracts.py` (new)

**Interfaces:**
- Produces: four dataclasses every later task imports from `app.engine.contracts` —
  - `LegendEntry(symbol: str, description: str, kind: str)` where `kind` is one of `"symbol"` or `"abbreviation"`
  - `AssemblyLine(catalog_id: str, name: str, quantity: float, unit: str, material_cost: float, labor_hours: float)`
  - `Assembly(parent_catalog_id: str, lines: list[AssemblyLine])` with properties `material_cost` and `labor_hours` summing its lines
  - `Proposal(intent: str, target_item_ids: list[str], field: str, value: str, summary: str)`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_engine_contracts.py`:

```python
"""The typed records the five agents hand to each other. Pure dataclasses,
no I/O -- these run without a database or an API key."""

from app.engine.contracts import Assembly, AssemblyLine, LegendEntry, Proposal


def test_legend_entry_carries_symbol_description_and_kind():
    e = LegendEntry(symbol="WP", description="WEATHERPROOF", kind="abbreviation")
    assert e.symbol == "WP"
    assert e.kind == "abbreviation"


def test_assembly_sums_its_lines():
    a = Assembly(parent_catalog_id="receptacle_20a", lines=[
        AssemblyLine("box_4sq", "4in square box", 1, "ea", 3.10, 0.15),
        AssemblyLine("thhn_12", "#12 THHN", 30, "ft", 0.18, 0.004),
    ])
    assert a.material_cost == round(3.10 * 1 + 0.18 * 30, 2)
    assert a.labor_hours == round(0.15 * 1 + 0.004 * 30, 3)


def test_assembly_with_no_lines_is_zero_not_an_error():
    a = Assembly(parent_catalog_id="unclassified", lines=[])
    assert a.material_cost == 0.0
    assert a.labor_hours == 0.0


def test_proposal_carries_targets_and_never_a_write():
    p = Proposal(intent="reclassify", target_item_ids=["a", "b"], field="name",
                 value="2x4 LED troffer", summary="Set 2 items to 2x4 LED troffer")
    assert len(p.target_item_ids) == 2
    assert p.field == "name"
```

- [ ] **Step 2: Run test to verify it fails**

Run from `api/`: `../.enginevenv/bin/python -m pytest tests/test_engine_contracts.py -v --no-header -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'Assembly'`

- [ ] **Step 3: Add the dataclasses**

Append to `api/app/engine/contracts.py`:

```python
@dataclass
class LegendEntry:
    """Documents agent output: one row of a legend or abbreviations block,
    read as structured data rather than left as a wall of text. `kind`
    separates a drawn symbol ("S" = single pole switch) from a written
    abbreviation ("WP" = weatherproof), because the two mean different
    things to Classification: a symbol names a device, an abbreviation
    usually modifies one."""

    symbol: str
    description: str
    kind: str  # "symbol" | "abbreviation"


@dataclass
class AssemblyLine:
    """One material line inside an assembly -- the box, the connector, the
    wire. Division 26 only."""

    catalog_id: str
    name: str
    quantity: float
    unit: str
    material_cost: float  # dollars per unit
    labor_hours: float  # crew hours per unit


@dataclass
class Assembly:
    """Pricing agent output: what a device actually costs to install once
    its supporting material is counted. A receptacle is not a receptacle --
    it is a receptacle, a box, a plate, wire, and connectors (spec 2.4)."""

    parent_catalog_id: str
    lines: list[AssemblyLine] = field(default_factory=list)

    @property
    def material_cost(self) -> float:
        return round(sum(l.material_cost * l.quantity for l in self.lines), 2)

    @property
    def labor_hours(self) -> float:
        return round(sum(l.labor_hours * l.quantity for l in self.lines), 3)


@dataclass
class Proposal:
    """Conversation agent output. It proposes; a person applies it through
    the same path a manual edit takes (spec 2.5, ROADMAP invariant 9).
    Deliberately carries no method that writes anything."""

    intent: str  # "reclassify" | "exclude" | "set_context" | "unknown"
    target_item_ids: list[str]
    field: str
    value: str
    summary: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `../.enginevenv/bin/python -m pytest tests/test_engine_contracts.py -v --no-header -p no:cacheprovider`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/contracts.py api/tests/test_engine_contracts.py
git commit -m "Add typed records for legend rows, assemblies, and proposals"
```

---

### Task 2: Documents — parse the legend into typed rows

**Files:**
- Create: `api/app/engine/legend.py`
- Modify: `api/app/engine/documents.py`
- Test: `api/tests/test_engine_legend.py` (new)

**Interfaces:**
- Consumes: `LegendEntry` from Task 1.
- Produces: `parse_legend(schedule_text: str) -> list[LegendEntry]` in `app.engine.legend`, and a new field `legend: list[LegendEntry]` on `DetectedSheet` (defaulting to an empty list), populated by `documents.detect_sheets`.

**Context the implementer needs:** the raw `schedule_text` on the real set's legend sheet (E0.1) is a flat newline-separated dump where an abbreviation key sits on one line and its expansion on the next, like:

```
ACS
ACCESS CONTROL SYSTEM
AFF
ABOVE FINISHED FLOOR
CKT
CIRCUIT
```

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_engine_legend.py`:

```python
"""Documents agent: turning a legend/abbreviations text dump into typed
rows. Spec 2.1 calls this the highest-leverage thing Documents produces --
Classification matches against these rows instead of re-reading a blob."""

from app.engine.legend import parse_legend


def test_parses_key_then_expansion_pairs():
    text = "ACS\nACCESS CONTROL SYSTEM\nAFF\nABOVE FINISHED FLOOR\nCKT\nCIRCUIT"
    rows = parse_legend(text)
    got = {r.symbol: r.description for r in rows}
    assert got["ACS"] == "ACCESS CONTROL SYSTEM"
    assert got["AFF"] == "ABOVE FINISHED FLOOR"
    assert got["CKT"] == "CIRCUIT"


def test_marks_every_parsed_row_as_an_abbreviation():
    rows = parse_legend("WP\nWEATHERPROOF")
    assert rows[0].kind == "abbreviation"


def test_ignores_a_key_with_no_expansion():
    # A trailing key with nothing after it is not a pair.
    rows = parse_legend("ACS\nACCESS CONTROL SYSTEM\nXYZ")
    assert [r.symbol for r in rows] == ["ACS"]


def test_ignores_two_expansions_in_a_row():
    # Prose lines following each other are not key/value pairs.
    rows = parse_legend("ACCESS CONTROL SYSTEM\nABOVE FINISHED FLOOR")
    assert rows == []


def test_keeps_the_first_definition_when_a_key_repeats():
    rows = parse_legend("EL\nEMERGENCY LIGHT\nEL\nELEVATION")
    assert [(r.symbol, r.description) for r in rows] == [("EL", "EMERGENCY LIGHT")]


def test_empty_text_yields_no_rows():
    assert parse_legend("") == []
    assert parse_legend("   \n\n  ") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run from `api/`: `../.enginevenv/bin/python -m pytest tests/test_engine_legend.py -v --no-header -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.legend'`

- [ ] **Step 3: Write the parser**

Create `api/app/engine/legend.py`:

```python
"""Legend and abbreviation parsing -- the Documents agent's structured half.

A drawing set's legend sheet carries two useful blocks: a symbol legend
(a drawn glyph beside a description) and an abbreviations list (a short
code beside its expansion). The symbol half is a picture and needs vision
to read; the abbreviations half is already text, laid out as a key on one
line and its expansion on the next, and that half is parseable today.

This is deliberately the text half only. Reading the drawn symbol legend
is a vision problem and stays out of the basic version (spec 11.6).

Why it matters: Classification currently receives one concatenated blob
and has to re-derive structure from it on every call. A typed row is the
handoff the architecture asks for -- and it is what lets a downstream
agent say "WP is an abbreviation, so it modifies a device rather than
being one" from data rather than from a model's recollection.
"""

from __future__ import annotations

import re

from .contracts import LegendEntry

# An abbreviation key: short, uppercase, possibly carrying the punctuation
# a drafter uses (C. for conduit, (E) for existing, C.O. for conduit only).
KEY = re.compile(r"^[A-Z][A-Z0-9./()\-]{0,5}$")

# An expansion: at least two words, and not itself key-shaped, so a run of
# keys with no descriptions never pairs up with itself.
def _is_expansion(line: str) -> bool:
    return len(line.split()) >= 2 and not KEY.match(line)


def parse_legend(schedule_text: str) -> list[LegendEntry]:
    """Key-on-one-line, expansion-on-the-next pairs, in order. The first
    definition of a key wins: a legend sheet repeats headers, and a later
    accidental match must not overwrite a real definition."""
    lines = [l.strip() for l in (schedule_text or "").splitlines() if l.strip()]
    seen: dict[str, LegendEntry] = {}
    for key, expansion in zip(lines, lines[1:]):
        if KEY.match(key) and _is_expansion(expansion) and key not in seen:
            seen[key] = LegendEntry(symbol=key, description=expansion, kind="abbreviation")
    return list(seen.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `../.enginevenv/bin/python -m pytest tests/test_engine_legend.py -v --no-header -p no:cacheprovider`
Expected: PASS (6 tests)

- [ ] **Step 5: Attach parsed rows to each sheet**

In `api/app/engine/contracts.py`, add one field to `DetectedSheet`, after `schedule_text`:

```python
    legend: list["LegendEntry"] = field(default_factory=list)  # parsed rows from schedule_text
```

In `api/app/engine/documents.py`, add the import at the top with the other engine imports:

```python
from .legend import parse_legend
```

Then find every `DetectedSheet(...)` construction that passes `schedule_text=sched` and add `legend=parse_legend(sched)` alongside it. There are two such constructions (around lines 103 and 115); both need it.

- [ ] **Step 6: Add the real-set test**

Append to `api/tests/test_engine_legend.py`:

```python
import os
import pytest

BID = ("/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/"
       "21_1001_unalaska_library_cd_biddrawings.pdf")


@pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")
def test_real_set_legend_sheet_yields_known_abbreviations():
    """The Unalaska set's E0.1 carries an abbreviations block. These three
    are read directly off that sheet and are what the classifier used to
    explain WP as a modifier rather than a device."""
    from app.engine import documents

    sheets = documents.detect_sheets(BID)
    rows = {r.symbol: r.description for s in sheets for r in s.legend}
    assert rows.get("AFF") == "ABOVE FINISHED FLOOR"
    assert rows.get("EL") == "EMERGENCY LIGHT"
    assert len(rows) > 30, f"expected a substantial abbreviations block, got {len(rows)}"
```

- [ ] **Step 7: Run the whole file**

Run: `../.enginevenv/bin/python -m pytest tests/test_engine_legend.py -v --no-header -p no:cacheprovider`
Expected: PASS (7 tests)

- [ ] **Step 8: Commit**

```bash
git add api/app/engine/legend.py api/app/engine/documents.py api/app/engine/contracts.py api/tests/test_engine_legend.py
git commit -m "Parse the legend's abbreviations block into typed rows"
```

---

### Task 3: Counting — reject rotated glyphs

**Files:**
- Modify: `api/app/engine/counting.py`
- Test: `api/tests/test_engine_counting.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `count_sheet` and `count` keep their exact signatures and return types. Behaviour narrows only: a text span whose line direction is not horizontal is no longer eligible to be a device tag.

**Why this filter and not another.** Two filters were tested against the real set on 2026-09-03 (spec §11.2). Rejecting rotated glyphs removes all 87 engineer's-seal placements with no plausible false positive, because a drafter sets a device tag horizontally and only curved text (a seal, a north arrow) carries a per-glyph rotation. Requiring adjacent vector geometry was also tested and **does not work** — on a sheet carrying 33,410 paths, every counted tag has 35–49 strokes within 14 points, seal glyphs included. Do not implement the geometry filter.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_engine_counting.py`:

```python
import os
import pytest

BID = ("/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/"
       "21_1001_unalaska_library_cd_biddrawings.pdf")


@pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")
def test_engineers_seal_is_not_counted_as_devices():
    """E1.1 (page index 84) carries a professional engineer's seal whose
    perimeter text is 50 rotated single-character glyphs near (960, 100),
    spelling STATE OF ALASKA / REGISTERED PROFESSIONAL ENGINEER. Each
    letter matches the device-tag shape and stands alone on its own text
    line, so before this filter they were counted as devices on every
    sheet -- A as a luminaire type, S as a switch, T as a data outlet.

    Asserted count, not a tuned threshold: Counting is tested, not
    trained (CLAUDE.md)."""
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    sheet = next(s for s in sheets if s.page_index == 84)
    clusters = counting.count_sheet(BID, sheet)

    seal = [p for c in clusters for p in c.placements
            if 850 < p.x < 1010 and 40 < p.y < 160]
    assert seal == [], f"{len(seal)} seal glyphs still counted as devices"


@pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")
def test_real_devices_survive_the_rotation_filter():
    """The filter must not empty the sheet. E1.1 still yields device
    clusters after the seal is excluded."""
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    sheet = next(s for s in sheets if s.page_index == 84)
    clusters = counting.count_sheet(BID, sheet)
    assert clusters, "the rotation filter removed every cluster on the sheet"
```

- [ ] **Step 2: Run test to verify it fails**

Run from `api/`: `../.enginevenv/bin/python -m pytest tests/test_engine_counting.py -v --no-header -p no:cacheprovider -k seal`
Expected: FAIL — seal glyphs are currently counted, so the list is non-empty.

- [ ] **Step 3: Implement the filter**

`counting.count_sheet` currently reads words via `page.get_text("words")`, which carries no rotation information. Rotation lives on the *line* in the `dict` extraction, so the fix is to build a set of rotated glyph positions first and exclude any word whose centre matches one.

In `api/app/engine/counting.py`, add this function above `count_sheet`:

```python
def _rotated_points(page) -> set[tuple[int, int]]:
    """Centres of every text span that is not set horizontally.

    A drafter sets a device tag horizontally. Text on a curve -- the
    perimeter of a professional engineer's seal, a north arrow, a revision
    cloud -- carries a per-glyph direction vector, and on a real set those
    glyphs are individually tag-shaped ("A", "S", "T") standing alone on
    their own text line, so every existing filter passes them through. On
    the first real bid set this was 87 placements across 14 sheets, read
    as luminaires, switches and receptacles (design spec 11.2).

    Positions are rounded to whole points so they can be matched against
    the word list, which reports the same coordinates.
    """
    out: set[tuple[int, int]] = set()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            dx, dy = line["dir"]
            if abs(dy) <= 0.01:  # horizontal: a normal tag
                continue
            for span in line["spans"]:
                x0, y0, x1, y1 = span["bbox"]
                out.add((round((x0 + x1) / 2), round((y0 + y1) / 2)))
    return out
```

Then inside `count_sheet`, after `words = page.get_text("words")`, add:

```python
    rotated = _rotated_points(page)
```

and inside the word loop, immediately after `cx, cy = (x0 + x1) / 2, (y0 + y1) / 2`, add:

```python
        if (round(cx), round(cy)) in rotated:
            continue  # curved text (a seal, a north arrow) is never a device tag
```

- [ ] **Step 4: Run test to verify it passes**

Run: `../.enginevenv/bin/python -m pytest tests/test_engine_counting.py -v --no-header -p no:cacheprovider`
Expected: PASS — every test in the file, including the pre-existing ones.

- [ ] **Step 5: Measure the change on the whole set**

Run from `api/`:

```bash
../.enginevenv/bin/python -c "
from app.engine import documents, counting
BID='/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/21_1001_unalaska_library_cd_biddrawings.pdf'
s=documents.detect_sheets(BID); c=counting.count(BID,s)
print('placements now:', sum(x.count for x in c), '(was 812 before the filter)')
"
```

Expected: a number near 725 — 812 minus the 87 seal glyphs. Record the actual number in the commit message.

- [ ] **Step 6: Commit**

```bash
git add api/app/engine/counting.py api/tests/test_engine_counting.py
git commit -m "Stop counting an engineer's seal as electrical devices"
```

---

### Task 4: Pricing — Division 26 assemblies

**Files:**
- Create: `api/app/engine/assemblies.py`
- Test: `api/tests/test_engine_assemblies.py` (new)

**Interfaces:**
- Consumes: `Assembly`, `AssemblyLine` from Task 1; `CATALOG` from `app.engine.catalog`.
- Produces: `ASSEMBLIES: dict[str, list[tuple[str, float]]]` and `expand(catalog_id: str, quantity: float) -> Assembly` in `app.engine.assemblies`, plus `MATERIALS: dict[str, AssemblyLine]` describing each supporting material once.

**Domain context the implementer needs.** An electrical estimator does not price a receptacle as a receptacle. Installing one means a box, a plate, wire from the last device, and connectors. Wire and conduit are a large share of material cost, which is why ROADMAP.md calls them "the largest single threat to a defensible total." Feet-per-device is the firm's own rule of thumb — 30 feet of branch wiring per device is a common default and is what this uses until a firm supplies its own.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_engine_assemblies.py`:

```python
"""Pricing agent: what a device actually costs once its supporting
material is counted. Division 26 only."""

import pytest

from app.engine.assemblies import ASSEMBLIES, MATERIALS, expand


def test_a_receptacle_carries_box_plate_wire_and_connectors():
    a = expand("receptacle_20a", 1)
    ids = {l.catalog_id for l in a.lines}
    assert "box_4sq" in ids
    assert "plate_1g" in ids
    assert "thhn_12" in ids, "branch wire is the largest material line and must be present"
    assert "conn_emt_1_2" in ids


def test_quantity_scales_every_line():
    one = expand("receptacle_20a", 1)
    ten = expand("receptacle_20a", 10)
    by_id = {l.catalog_id: l.quantity for l in one.lines}
    for line in ten.lines:
        assert line.quantity == pytest.approx(by_id[line.catalog_id] * 10)


def test_material_cost_is_the_sum_of_its_lines():
    a = expand("receptacle_20a", 2)
    expected = round(sum(l.material_cost * l.quantity for l in a.lines), 2)
    assert a.material_cost == expected


def test_a_luminaire_carries_whip_and_wire_not_a_device_plate():
    a = expand("luminaire_troffer", 1)
    ids = {l.catalog_id for l in a.lines}
    assert "whip_6ft" in ids
    assert "plate_1g" not in ids, "a fixture takes no device plate"


def test_an_unknown_catalog_id_expands_to_an_empty_assembly():
    """An unclassified item has no assembly. It must contribute zero rather
    than guessing material, exactly as pricing.py already refuses to guess a
    price for an unclassified item."""
    a = expand("unclassified", 5)
    assert a.lines == []
    assert a.material_cost == 0.0


def test_every_assembly_line_names_a_known_material():
    for parent, lines in ASSEMBLIES.items():
        for material_id, _qty in lines:
            assert material_id in MATERIALS, f"{parent} references unknown material {material_id}"


def test_every_catalog_device_that_gets_installed_has_an_assembly():
    """A device with no assembly is priced as a bare device, which
    understates it. This asserts the gap is deliberate, not forgotten."""
    from app.engine.catalog import CATALOG

    unpriced = {"luminaire_generic"}  # a generic placeholder, intentionally bare
    missing = [cid for cid in CATALOG if cid not in ASSEMBLIES and cid not in unpriced]
    assert missing == [], f"catalog items with no assembly: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run from `api/`: `../.enginevenv/bin/python -m pytest tests/test_engine_assemblies.py -v --no-header -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.assemblies'`

- [ ] **Step 3: Write the assembly table**

Create `api/app/engine/assemblies.py`:

```python
"""Division 26 assemblies -- what a device drags along with it.

An estimator does not price a receptacle as a receptacle. Installing one
means a box, a plate, branch wire back to the last device, and the
connectors to land the raceway. Wire and conduit are a large share of
material cost, which is why ROADMAP.md names them the largest single
threat to a defensible total. Pricing a bare device understates the job.

Everything here is Division 26. Quantities are per one parent device.

FEET_PER_DEVICE is the firm's own rule of thumb, not a measurement. The
drawing shows a homerun arrow, not a route, so the run length is judgment
from ceiling height and building geometry and is not in the file for
anyone to read (ROADMAP 2.1). Thirty feet is a common default and stands
in until a firm supplies its own. It is deliberately one named constant
rather than being spread through the table below.
"""

from __future__ import annotations

from .contracts import Assembly, AssemblyLine

FEET_PER_DEVICE = 30.0

# Each supporting material, described once. Costs are dollars per unit and
# crew hours per unit -- rough order-of-magnitude figures for a defensible
# shape, not a quote, the same standing as catalog.py's price book.
MATERIALS: dict[str, AssemblyLine] = {
    "box_4sq":      AssemblyLine("box_4sq", "4in square box", 1, "ea", 3.10, 0.15),
    "mudring_1g":   AssemblyLine("mudring_1g", "1-gang mud ring", 1, "ea", 1.40, 0.05),
    "plate_1g":     AssemblyLine("plate_1g", "1-gang device plate", 1, "ea", 0.90, 0.04),
    "thhn_12":      AssemblyLine("thhn_12", "#12 THHN conductor", 1, "ft", 0.18, 0.004),
    "thhn_10":      AssemblyLine("thhn_10", "#10 THHN conductor", 1, "ft", 0.28, 0.005),
    "emt_1_2":      AssemblyLine("emt_1_2", '1/2in EMT conduit', 1, "ft", 0.62, 0.030),
    "conn_emt_1_2": AssemblyLine("conn_emt_1_2", '1/2in EMT connector', 1, "ea", 0.85, 0.03),
    "whip_6ft":     AssemblyLine("whip_6ft", "6ft fixture whip", 1, "ea", 8.50, 0.10),
    "wirenut":      AssemblyLine("wirenut", "Wire connector", 1, "ea", 0.12, 0.01),
    "ground_12":    AssemblyLine("ground_12", "#12 ground conductor", 1, "ft", 0.14, 0.003),
}

# parent catalog id -> [(material id, quantity per one parent)]
# A branch device carries three conductors over FEET_PER_DEVICE: hot,
# neutral, and a ground run on its own line so a firm can price it apart.
_BRANCH_WIRE = [
    ("thhn_12", FEET_PER_DEVICE * 2),
    ("ground_12", FEET_PER_DEVICE),
    ("emt_1_2", FEET_PER_DEVICE),
    ("conn_emt_1_2", 2.0),
    ("wirenut", 3.0),
]

ASSEMBLIES: dict[str, list[tuple[str, float]]] = {
    "receptacle_20a": [("box_4sq", 1), ("mudring_1g", 1), ("plate_1g", 1), *_BRANCH_WIRE],
    "receptacle_gfci": [("box_4sq", 1), ("mudring_1g", 1), ("plate_1g", 1), *_BRANCH_WIRE],
    "switch_sp": [("box_4sq", 1), ("mudring_1g", 1), ("plate_1g", 1), *_BRANCH_WIRE],
    "data_outlet": [("box_4sq", 1), ("mudring_1g", 1), ("plate_1g", 1),
                    ("emt_1_2", FEET_PER_DEVICE), ("conn_emt_1_2", 2.0)],
    "junction_box": [("box_4sq", 1), ("wirenut", 3.0),
                     ("emt_1_2", FEET_PER_DEVICE / 2), ("conn_emt_1_2", 2.0)],
    # Fixtures land on a whip rather than a device plate.
    "luminaire_troffer": [("whip_6ft", 1), ("wirenut", 3.0),
                          ("thhn_12", FEET_PER_DEVICE), ("ground_12", FEET_PER_DEVICE / 2)],
    "luminaire_highbay": [("whip_6ft", 1), ("wirenut", 3.0),
                          ("thhn_10", FEET_PER_DEVICE), ("ground_12", FEET_PER_DEVICE / 2)],
    "exit_sign": [("whip_6ft", 1), ("wirenut", 3.0), ("thhn_12", FEET_PER_DEVICE / 2)],
    # Gear is fed, not branch-wired: heavier conductor, no device trim.
    "panel": [("thhn_10", FEET_PER_DEVICE * 3), ("emt_1_2", FEET_PER_DEVICE),
              ("conn_emt_1_2", 4.0), ("ground_12", FEET_PER_DEVICE)],
    "disconnect": [("thhn_10", FEET_PER_DEVICE), ("emt_1_2", FEET_PER_DEVICE / 2),
                   ("conn_emt_1_2", 2.0), ("ground_12", FEET_PER_DEVICE / 2)],
}


def expand(catalog_id: str, quantity: float) -> Assembly:
    """The supporting material for `quantity` of one catalog device.
    An id with no assembly yields an empty one -- it contributes zero
    rather than a guessed material list, the same refusal pricing.py
    already makes for an unclassified item."""
    lines = []
    for material_id, per_parent in ASSEMBLIES.get(catalog_id, []):
        base = MATERIALS[material_id]
        lines.append(AssemblyLine(
            catalog_id=base.catalog_id, name=base.name,
            quantity=round(per_parent * quantity, 3), unit=base.unit,
            material_cost=base.material_cost, labor_hours=base.labor_hours,
        ))
    return Assembly(parent_catalog_id=catalog_id, lines=lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `../.enginevenv/bin/python -m pytest tests/test_engine_assemblies.py -v --no-header -p no:cacheprovider`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/assemblies.py api/tests/test_engine_assemblies.py
git commit -m "Add Division 26 assemblies so a device carries its wire and conduit"
```

---

### Task 5: Pricing — price the assembly, not the bare device

**Files:**
- Modify: `api/app/engine/pricing.py`
- Modify: `api/app/engine/contracts.py`
- Test: `api/tests/test_engine_pricing.py` (new)

**Interfaces:**
- Consumes: `expand` from Task 4.
- Produces: `PricedItem` gains one field, `assembly: Assembly | None = None`. `price_item` and `price` keep their signatures; the totals they compute now include assembly material and hours.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_engine_pricing.py`:

```python
"""Pricing agent: device cost plus the assembly behind it."""

from app.engine.assemblies import expand
from app.engine.contracts import ClassifiedItem, Placement
from app.engine.pricing import price_item


def _item(catalog_id="receptacle_20a", qty=10):
    return ClassifiedItem(
        catalog_id=catalog_id, name="20A duplex receptacle", system="Power",
        category="Devices", unit="ea", symbol="receptacle", quantity=qty,
        sheet_page_index=0, placements=[Placement(1, 1)] * qty,
        status="ready", warning=None, source_tag="R",
    )


def test_priced_item_includes_its_assembly_material():
    """A bare receptacle is a few dollars; with box, plate, wire and
    conduit behind it the real installed material is far higher. Pricing
    the device alone is the understatement this task removes."""
    from app.engine.catalog import CATALOG

    priced = price_item(_item(), labor_rate=68.0)
    bare = CATALOG["receptacle_20a"].material_cost * 10
    assert priced.material_cost > bare * 2, "assembly material is missing from the total"


def test_assembly_is_attached_for_inspection():
    priced = price_item(_item(), labor_rate=68.0)
    assert priced.assembly is not None
    assert any(l.catalog_id == "thhn_12" for l in priced.assembly.lines)


def test_total_equals_material_plus_labor():
    priced = price_item(_item(), labor_rate=68.0)
    assert priced.total_direct_cost == round(priced.material_cost + priced.labor_cost, 2)


def test_labor_hours_include_assembly_hours():
    from app.engine.catalog import CATALOG

    priced = price_item(_item(), labor_rate=68.0)
    device_only = CATALOG["receptacle_20a"].labor_hours * 10
    assert priced.labor_hours > device_only


def test_material_matches_the_assembly_it_reports():
    from app.engine.catalog import CATALOG

    priced = price_item(_item(), labor_rate=68.0)
    expected = round(CATALOG["receptacle_20a"].material_cost * 10 + expand("receptacle_20a", 10).material_cost, 2)
    assert priced.material_cost == expected


def test_an_unclassified_item_is_still_unpriced():
    priced = price_item(_item(catalog_id="unclassified", qty=5), labor_rate=68.0)
    assert priced.material_cost == 0.0
    assert priced.total_direct_cost == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run from `api/`: `../.enginevenv/bin/python -m pytest tests/test_engine_pricing.py -v --no-header -p no:cacheprovider`
Expected: FAIL — `PricedItem` has no `assembly` field, and material is device-only.

- [ ] **Step 3: Add the field**

In `api/app/engine/contracts.py`, add one field to `PricedItem`, after `total_direct_cost`:

```python
    assembly: "Assembly | None" = None  # the supporting material behind this item
```

- [ ] **Step 4: Price the assembly**

In `api/app/engine/pricing.py`, add the import:

```python
from .assemblies import expand
```

Replace the body of `price_item` after the `if cat is None` guard with:

```python
    asm = expand(item.catalog_id, item.quantity)
    material = round(cat.material_cost * item.quantity + asm.material_cost, 2)
    hours = round(cat.labor_hours * item.quantity + asm.labor_hours, 2)
    labor = round(hours * labor_rate, 2)
    return PricedItem(item=item, material_cost=material, labor_hours=hours, labor_cost=labor,
                      total_direct_cost=round(material + labor, 2), assembly=asm)
```

Update the module docstring's first paragraph to say material comes from the catalog price book *plus the item's assembly*.

- [ ] **Step 5: Run test to verify it passes**

Run: `../.enginevenv/bin/python -m pytest tests/test_engine_pricing.py tests/test_engine_assemblies.py -v --no-header -p no:cacheprovider`
Expected: PASS (13 tests)

- [ ] **Step 6: Commit**

```bash
git add api/app/engine/pricing.py api/app/engine/contracts.py api/tests/test_engine_pricing.py
git commit -m "Price a device with its assembly behind it"
```

---

### Task 6: Classification — read the typed legend rows

**Files:**
- Modify: `api/app/engine/classification.py`
- Test: `api/tests/test_engine_classify.py`

**Interfaces:**
- Consumes: `LegendEntry` rows on `DetectedSheet.legend` from Task 2.
- Produces: `classify(clusters, sheets)` keeps its signature. Its behaviour gains one rule: a tag matching a parsed abbreviation is classified as a modifier rather than a device.

**Why this is not a Counting filter.** An abbreviation and a fixture-type letter overlap on real sets — `O`, `D`, `F`, `H` and `C` are all both. Excluding abbreviations at Counting would delete real devices. Classification is the agent that gets to weigh the two readings, which is exactly the split spec §2.6 describes.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_engine_classify.py`:

```python
def test_an_abbreviation_tag_is_classified_as_a_modifier():
    """WP is in the abbreviations block as WEATHERPROOF. It labels another
    device rather than being one, so counting it as a device double counts.
    Classification -- not Counting -- makes this call, because a letter can
    be both an abbreviation and a fixture type (design spec 11.6)."""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    sheet = DetectedSheet(
        page_index=0, number="E7.1", title="Power", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="WP", description="WEATHERPROOF", kind="abbreviation")],
    )
    cluster = DeviceCluster(tag="WP", sheet_page_index=0, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [sheet])

    assert items[0].status == "attention"
    assert items[0].warning is not None
    assert "weatherproof" in items[0].warning["why"].lower()
    assert "double" in items[0].warning["fix"].lower()


def test_a_known_device_tag_is_unaffected_by_the_legend():
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    sheet = DetectedSheet(
        page_index=0, number="E7.1", title="Power", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="WP", description="WEATHERPROOF", kind="abbreviation")],
    )
    cluster = DeviceCluster(tag="R", sheet_page_index=0, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [sheet])
    assert items[0].status == "ready"
    assert items[0].catalog_id == "receptacle_20a"
```

- [ ] **Step 2: Run test to verify it fails**

Run from `api/`: `../.enginevenv/bin/python -m pytest tests/test_engine_classify.py -v --no-header -p no:cacheprovider -k modifier`
Expected: FAIL — `WP` currently resolves through `TAG_TO_CATALOG` to a GFCI receptacle, status `ready`.

- [ ] **Step 3: Add the modifier rule**

In `api/app/engine/classification.py`, add this warning builder next to the two existing ones:

```python
def _modifier_warning(tag: str, description: str, count: int, sheet_no: str) -> dict:
    return {
        "reason": "legend",
        "title": "Modifier, not a standalone device",
        "found": f"Tag {tag} appears {count} times on {sheet_no}.",
        "why": f"{tag} is listed in the abbreviations as {description.lower()}, so it labels another device rather than being counted as one.",
        "fix": "Trace each one to the device symbol it labels so it is not double counted, or reject it.",
        "where": f"{sheet_no} and the legend sheet.",
    }
```

In `classify`, build a lookup of abbreviations per sheet before the loop:

```python
    abbrev = {
        e.symbol: e.description
        for s in sheets
        for e in s.legend
        if e.kind == "abbreviation"
    }
```

Then make it the first branch inside the cluster loop, before the `TAG_TO_CATALOG` check:

```python
        if c.tag in abbrev:
            items.append(ClassifiedItem(
                catalog_id="unclassified", name=f"{c.tag} — {abbrev[c.tag].title()}",
                system="Unknown", category="Unclassified", unit="ea", symbol="generic",
                quantity=c.count, sheet_page_index=c.sheet_page_index, placements=c.placements,
                status="attention", warning=_modifier_warning(c.tag, abbrev[c.tag], c.count, no),
                source_tag=c.tag,
            ))
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `../.enginevenv/bin/python -m pytest tests/test_engine_classify.py -v --no-header -p no:cacheprovider`
Expected: PASS — every test in the file.

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/classification.py api/tests/test_engine_classify.py
git commit -m "Classify an abbreviation tag as a modifier, not a device"
```

---

### Task 7: Conversation — route an utterance to a typed proposal

**Files:**
- Create: `api/app/engine/conversation.py`
- Test: `api/tests/test_engine_conversation.py` (new)

**Interfaces:**
- Consumes: `Proposal` from Task 1.
- Produces: `route(message: str, anchor_item_ids: list[str]) -> Proposal` in `app.engine.conversation`.

**The three limits this must respect** (spec §2.5), all testable:
1. **It routes; it does not answer.** It resolves *which items* and *which field* — it never produces a catalog classification itself.
2. **It proposes; it never writes.** The module imports no database session and has no write path.
3. **Its output shape is constrained.** `intent` is one of four known values; anything unrecognised is `"unknown"`, never an invented action.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_engine_conversation.py`:

```python
"""Conversation agent: utterance + anchor -> typed proposal.

It routes and proposes. It never classifies, never writes, and never
approves (design spec 2.5). These tests are the boundary."""

import inspect

from app.engine import conversation
from app.engine.conversation import INTENTS, route


def test_exclusion_language_routes_to_exclude():
    p = route("ignore this wing, it's existing to remain", ["i1", "i2"])
    assert p.intent == "exclude"
    assert p.target_item_ids == ["i1", "i2"]


def test_reclassification_language_routes_to_reclassify():
    p = route("these six are all type F", ["a", "b", "c", "d", "e", "f"])
    assert p.intent == "reclassify"
    assert p.field == "name"


def test_context_language_routes_to_set_context():
    p = route("ceiling's 14 feet in here", ["x"])
    assert p.intent == "set_context"


def test_an_unrecognised_utterance_is_unknown_not_an_invented_action():
    p = route("what's the weather", ["x"])
    assert p.intent == "unknown"
    assert p.intent in INTENTS


def test_every_intent_is_in_the_closed_set():
    for message in ("ignore this area", "these are type F", "ceiling is 12 feet", "hello"):
        assert route(message, ["x"]).intent in INTENTS


def test_a_proposal_never_carries_a_classification_of_its_own():
    """It resolves WHICH items and WHICH field, then hands off. If it ever
    returns a catalog_id it has started classifying, and there are then two
    classifiers that will drift (spec 2.5 limit 1)."""
    p = route("these six are all type F", ["a"])
    assert not hasattr(p, "catalog_id")


def test_the_module_has_no_write_path():
    """Limit 2, enforced structurally rather than by convention: nothing in
    this module may touch a database session or a commit."""
    source = inspect.getsource(conversation)
    for forbidden in ("Session", "db.", "commit(", "sessionmaker"):
        assert forbidden not in source, f"conversation.py must not reference {forbidden}"


def test_no_anchor_yields_an_empty_target_list_not_a_guess():
    p = route("these are all type F", [])
    assert p.target_item_ids == []
```

- [ ] **Step 2: Run test to verify it fails**

Run from `api/`: `../.enginevenv/bin/python -m pytest tests/test_engine_conversation.py -v --no-header -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.conversation'`

- [ ] **Step 3: Write the router**

Create `api/app/engine/conversation.py`:

```python
"""Conversation agent (v1, deterministic).

Resolves what an estimator meant into a typed Proposal: which items, which
field, what value. It routes; the owning agent does the work. Given "these
six are all type F", Conversation resolves *which six* and *which field*,
and Classification produces the label -- it never classifies itself,
because two paths to a classification means two classifiers that drift
(design spec 2.5).

Three limits hold here and are covered by tests:

1. It routes, it does not answer. No catalog lookup lives in this module.
2. It proposes, it never writes. Nothing here imports a database session;
   a person applies a proposal through the same path a manual edit takes.
3. Its output is shape-constrained. `intent` comes from INTENTS and
   nothing else, so an unrecognised utterance becomes "unknown" rather
   than an invented action. Conversation is the only agent reading both
   estimator text and extracted drawing text, so this is the surface
   ROADMAP invariant 11 was written for.

v1 matches phrasing deterministically. A language version replaces
`route()` behind this same signature without changing anything downstream.
"""

from __future__ import annotations

from .contracts import Proposal

INTENTS = ("reclassify", "exclude", "set_context", "unknown")

_EXCLUDE = ("ignore", "existing to remain", "not in contract", "not doing",
            "exclude", "out of scope", "by others")
_RECLASSIFY = ("are all", "is a", "are type", "all type", "these are", "should be")
_CONTEXT = ("ceiling", "feet", "height", "mounting", "voltage", "in here")


def _match(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def route(message: str, anchor_item_ids: list[str]) -> Proposal:
    """One utterance plus what it was anchored to, resolved into a
    proposal for a person to apply. Never returns None: an unreadable
    message is an explicit "unknown" proposal, not a silent drop."""
    text = (message or "").strip().lower()
    targets = list(anchor_item_ids or [])

    # Exclusion is checked first: "ignore these, they're type F" is a scope
    # exclusion that happens to name a type, not a reclassification.
    if _match(text, _EXCLUDE):
        return Proposal(intent="exclude", target_item_ids=targets, field="status",
                        value="rejected",
                        summary=f"Exclude {len(targets)} item(s) from the takeoff")
    if _match(text, _RECLASSIFY):
        return Proposal(intent="reclassify", target_item_ids=targets, field="name", value="",
                        summary=f"Reclassify {len(targets)} item(s) — Classification supplies the label")
    if _match(text, _CONTEXT):
        return Proposal(intent="set_context", target_item_ids=targets, field="project_context",
                        value=message.strip(),
                        summary="Record project context from the estimator")
    return Proposal(intent="unknown", target_item_ids=targets, field="", value="",
                    summary="Could not resolve this to a change — ask for specifics")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `../.enginevenv/bin/python -m pytest tests/test_engine_conversation.py -v --no-header -p no:cacheprovider`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/conversation.py api/tests/test_engine_conversation.py
git commit -m "Add the Conversation agent: route an utterance to a typed proposal"
```

---

### Task 8: Run all five against the real set

**Files:**
- Modify: `api/app/engine/__main__.py`
- Test: `api/tests/test_engine_pipeline.py` (new)

**Interfaces:**
- Consumes: everything above.
- Produces: no new public functions. The CLI gains an assembly-material line in its summary.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_engine_pipeline.py`:

```python
"""End to end: Documents -> Counting -> Classification -> Pricing, against
the real bid set. Asserted facts, not tuned thresholds."""

import os
import pytest

BID = ("/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/"
       "21_1001_unalaska_library_cd_biddrawings.pdf")

pytestmark = pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")


def test_pipeline_runs_end_to_end_on_a_real_set():
    from app.engine import pipeline

    result = pipeline.run(BID, labor_rate=68.0)
    assert len(result.sheets) == 14, "the Unalaska set has 14 electrical sheets"
    assert result.items, "the pipeline produced no items"
    assert result.total_direct_cost > 0


def test_every_priced_device_carries_its_assembly():
    from app.engine import pipeline

    result = pipeline.run(BID, labor_rate=68.0)
    priced = [p for p in result.items if p.total_direct_cost > 0]
    assert priced, "no item was priced at all"
    assert all(p.assembly is not None for p in priced)


def test_wire_and_conduit_reach_the_total():
    """The material an electrical estimator most needs and the engine
    previously omitted entirely."""
    from app.engine import pipeline

    result = pipeline.run(BID, labor_rate=68.0)
    ids = {l.catalog_id for p in result.items if p.assembly for l in p.assembly.lines}
    assert "thhn_12" in ids or "thhn_10" in ids, "no branch wire in the takeoff"
    assert "emt_1_2" in ids, "no conduit in the takeoff"


def test_the_seal_is_gone_from_the_whole_set():
    """87 engineer's-seal glyphs were counted as devices across the 14
    sheets before the rotation filter (design spec 11.2)."""
    from app.engine import counting, documents

    sheets = documents.detect_sheets(BID)
    total = sum(c.count for c in counting.count(BID, sheets))
    assert total < 800, f"expected the seal's 87 placements gone from 812, got {total}"
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run from `api/`: `../.enginevenv/bin/python -m pytest tests/test_engine_pipeline.py -v --no-header -p no:cacheprovider`
Expected: PASS if Tasks 3–5 landed correctly. If `test_the_seal_is_gone_from_the_whole_set` fails, Task 3's filter is not working across all sheets — fix that before continuing.

- [ ] **Step 3: Show assembly material in the CLI**

In `api/app/engine/__main__.py`, after the line printing `Material:`, add:

```python
    asm_material = round(sum(p.assembly.material_cost for p in result.items if p.assembly), 2)
    print(f"  of which assembly: ${asm_material:>12,.2f}  (boxes, wire, conduit, connectors)")
```

- [ ] **Step 4: Run the CLI on the real set**

Run from `api/`:

```bash
../.enginevenv/bin/python -m app.engine "/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/21_1001_unalaska_library_cd_biddrawings.pdf" 2>&1 | tail -8
```

Expected: a total direct cost substantially above the pre-assembly figure of $74,663, with a non-zero assembly line. Record both numbers in the commit message.

- [ ] **Step 5: Run every engine test together**

Run from `api/`:

```bash
../.enginevenv/bin/python -m pytest tests/test_engine_contracts.py tests/test_engine_legend.py tests/test_engine_counting.py tests/test_engine_assemblies.py tests/test_engine_pricing.py tests/test_engine_classify.py tests/test_engine_conversation.py tests/test_engine_pipeline.py -v --no-header -p no:cacheprovider
```

Expected: PASS, all files.

- [ ] **Step 6: Run the full backend suite for regressions**

Run: `docker compose exec -T api pytest -q`
Expected: PASS. The baseline before this plan is 489 passing.

- [ ] **Step 7: Commit**

```bash
git add api/app/engine/__main__.py api/tests/test_engine_pipeline.py
git commit -m "Run all five agents against the real bid set, end to end"
```

---

## Self-Review

**Spec coverage** against §11.6's table:

| Agent | §11.6 asks for | Task |
|---|---|---|
| Documents | typed legend rows instead of a blob | 2 |
| Counting | rotated-glyph filter, not geometry clustering | 3 |
| Classification | read those rows | 6 |
| Pricing | assembly expansion — box, wire, conduit | 4, 5 |
| Conversation | intent routing to a typed proposal, no writes | 7 |

Deliberately **not** covered, and why:
- **Geometry clustering** — §11.1 names it a research task, explicitly out of scope. Task 3's brief tells the implementer not to attempt it, and records that the adjacent-geometry filter was tested and fails.
- **Schedule-region exclusion** — listed in §11.6 for Counting alongside the rotation filter. Dropped: on this set the panel-schedule headers (`VA`, `CKT`, `AMP`) sit inside the same drawing region as real devices, so excluding a region would need table detection that does not exist yet. Task 6's modifier rule catches part of the same noise from the legend instead. This is a real narrowing of §11.6 and should be noted when the plan is reviewed.
- **Project-scoped symbol library** — §11.6 asks Classification to "persist a resolution." That needs a database table, a migration, an API endpoint and a client path; it is a plan of its own rather than a task, and none of the other four agents depend on it. Task 6 delivers the read-the-legend half.

**Placeholder scan:** no TBD/TODO. Every step carries real code, real paths, real assertions.

**Type consistency:** `LegendEntry(symbol, description, kind)` is defined in Task 1 and used in Tasks 2 and 6 with those exact field names. `Assembly(parent_catalog_id, lines)` and `AssemblyLine(catalog_id, name, quantity, unit, material_cost, labor_hours)` are defined in Task 1, built in Task 4, consumed in Tasks 5 and 8. `Proposal(intent, target_item_ids, field, value, summary)` is defined in Task 1 and built in Task 7. `expand(catalog_id, quantity) -> Assembly` is defined in Task 4 and called in Task 5. `PricedItem.assembly` is added in Task 5 and read in Task 8.

**One risk worth naming for the reviewer:** Task 5 changes what every existing total means — material and hours rise for every classified device. `api/tests/test_engine_classify.py` and any test asserting a specific cost figure may need updating, and Task 8 Step 6 is where that surfaces.
