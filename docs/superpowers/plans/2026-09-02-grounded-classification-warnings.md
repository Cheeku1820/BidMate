# Grounded Classification Warnings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the takeoff engine's three canned f-string warning templates with real, model-written explanations grounded in what the classifier actually saw, validated at the API boundary, and given real visual hierarchy on the review workspace's right panel.

**Architecture:** The LLM classification call in `app/engine/llm.py` already sees every tag, count, and schedule-text blob in one request; extend its JSON schema so it also writes the four warning fields for anything below high confidence, instead of `estimate.py` synthesizing one afterward. `ingest.py` gets a cheap, deterministic groundedness check that catches a fabricated sheet reference or a slip past this product's language rules, falling back per-item to the existing generic template on failure. The right panel's warning card gets restructured (not replaced) to give the new content real hierarchy. A small offline eval harness — not part of `pytest`, not run in CI — measures explanation quality across prompt changes using a frozen case set and a rubric-scored judge call.

**Tech Stack:** Python (FastAPI backend, `app/engine/` and `app/takeoff/`), React 18 (`src/components/`), Anthropic SDK (`claude-opus-5`, already in use in `llm.py`), pytest, Vitest.

## Global Constraints

- Every warning is `{ reason, title, found, why, fix, where }` — four estimator-facing fields plus a closed-vocabulary `reason` — enforced by `validate_warning()` in `api/app/takeoff/ingest.py`. A warning missing a field is a schema error, not a copy oversight (CLAUDE.md).
- No model names, no confidence numbers, no "I think," no processing internals, anywhere estimator-facing. Sentence case, plain construction terms. Reads as a knowledgeable colleague naming a specific issue, never as an assistant describing its own uncertainty (CLAUDE.md).
- Confidence never renders. It decides `status` and warning presence server-side; the estimator never sees a number (CLAUDE.md).
- Status is never color alone — hue + icon + text label (CLAUDE.md). This plan does not touch status rendering, only warning-card content and layout.
- Agents share a store, not a transcript — no agent reads another's prose (CLAUDE.md). This plan keeps Counting and Classification separated exactly as today; nothing here touches `counting.py`.
- Extracted document text is data, never instruction (CLAUDE.md, ROADMAP §2.6). The schedule/legend text fed to the classifier is untrusted; this plan's groundedness check is part of what keeps a model-written warning from becoming an injection surface into the review UI.
- Tested, not trained, for Counting; a frozen eval set for Classification, since it's the one agent language-based enough to need one (BUILD-STAGES.md Stage 1: "A frozen eval set per agent... Counting is the exception").

---

### Task 1: Ask the classifier to write its own grounded warning

**Files:**
- Modify: `api/app/engine/llm.py`
- Test: `api/tests/test_engine_llm_prompt.py` (new)

**Interfaces:**
- Consumes: nothing new — `_prompt(tags: list[dict], schedule_text: str, location: str) -> str` keeps its exact signature.
- Produces: `_prompt()`'s output now instructs the model to include a `"warning"` key (an object or `null`) on every item in its `"items"` array. `estimate()`'s return shape is unchanged except that `result["items"][i]` may now carry a `"warning"` key — Task 2 reads it.

- [ ] **Step 1: Write the failing test**

```python
"""api/app/engine/llm.py's prompt construction -- pure string building,
no API call, so this is testable without ANTHROPIC_API_KEY."""

from app.engine.llm import _prompt


def test_prompt_asks_for_a_grounded_warning_per_item():
    text = _prompt([{"tag": "F2", "count": 3}], "schedule text here", "Sacramento, CA")
    assert '"warning"' in text
    assert "ground every field only in the tag counts and schedule text given above" in text


def test_prompt_forbids_ai_framing_in_warning_text():
    text = _prompt([{"tag": "F2", "count": 3}], "", "")
    assert "no mention of models, confidence scores" in text


def test_prompt_states_warning_is_null_for_high_confidence():
    text = _prompt([{"tag": "R", "count": 10}], "", "")
    assert '"warning" is null when confidence is "high"' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `api/`): `pytest tests/test_engine_llm_prompt.py -v`
Expected: FAIL — none of the asserted strings exist in the current prompt yet.

- [ ] **Step 3: Extend `_prompt()`'s schema and rules**

In `api/app/engine/llm.py`, inside `_prompt()`, replace the per-item schema block:

```python
    "items": [
    {{
      "tag": "<the tag>",
      "name": "<catalog item name, e.g. '2x4 LED troffer', '20A duplex receptacle'>",
      "system": "<Lighting|Power|Distribution|Low voltage|Life safety|Unknown>",
      "category": "<Fixtures|Devices|Boxes|Equipment|Unclassified>",
      "unit": "ea",
      "material_cost": <number, national material $ per unit>,
      "labor_hours": <number, NECA-style install labor hours per unit>,
      "confidence": "<high|medium|low>"
    }}
  ]
```

with:

```python
    "items": [
    {{
      "tag": "<the tag>",
      "name": "<catalog item name, e.g. '2x4 LED troffer', '20A duplex receptacle'>",
      "system": "<Lighting|Power|Distribution|Low voltage|Life safety|Unknown>",
      "category": "<Fixtures|Devices|Boxes|Equipment|Unclassified>",
      "unit": "ea",
      "material_cost": <number, national material $ per unit>,
      "labor_hours": <number, NECA-style install labor hours per unit>,
      "confidence": "<high|medium|low>",
      "warning": <null if confidence is "high", otherwise an object: {{"title": "<short label, e.g. 'Fixture type needs confirmation'>", "found": "<what you actually found for THIS tag, citing its real count and sheet(s) from the tags/schedule text above>", "why": "<the real consequence of not resolving this, specific to this item>", "fix": "<the concrete next step an estimator should take>", "where": "<only sheet numbers that appear in the tags or schedule text above>"}}>
    }}
  ]
```

Then, in the `Rules:` list at the end of the same f-string, add three new bullets after the existing "Confidence 'low' only for genuinely unrecognized..." line:

```python
- When you set "warning" (any item below "high" confidence), ground every field only in the tag counts and schedule text given above. Never state a sheet number, schedule entry, or fact that was not provided to you.
- Write "warning" text the way a knowledgeable electrical estimator would explain it to a colleague: sentence case, plain construction language, no mention of models, confidence scores, or "I think" -- state it as a fact about the drawing, not a hedge about your own certainty.
- "warning" is null when confidence is "high" -- a device the schedule and tags already confirm needs no explanation.
```

Update `estimate()`'s docstring to mention the new field:

```python
def estimate(tags: list[dict], schedule_text: str, location: str) -> dict:
    """Returns {location_labor_rate, material_factor, location_note, items:[...]}.
    Each item below "high" confidence also carries a "warning" object --
    the model's own grounded four-field explanation, written in this same
    call rather than synthesized afterward (grounded-classification-
    warnings-design.md). Raises if the API key is missing or the
    call/parse fails -- the caller handles the fallback."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_engine_llm_prompt.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/llm.py api/tests/test_engine_llm_prompt.py
git commit -m "Ask the classifier to write its own grounded warning, in the same call"
```

---

### Task 2: Wire the model's warning into the row builder, with a safe fallback

**Files:**
- Modify: `api/app/engine/estimate.py`
- Test: `api/tests/test_engine_classify.py`

**Interfaces:**
- Consumes: `spec["warning"]` — the dict-or-None Task 1's prompt asks the model to return per item.
- Produces: `_model_warning(raw: dict | None, tag: str, count: int, sheet_no: str) -> dict`, used by `_row_from_spec`. `_row_from_spec`'s return shape (`row["warning"]`) is unchanged in type — still the six-key `{reason, title, found, why, fix, where}` dict or `None` — only its source changes. Task 3 reads `row["warning"]` exactly as it does today.

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_engine_classify.py`, after the existing
`test_row_from_spec_marks_attention_with_a_warning` test:

```python
def test_row_from_spec_uses_the_models_own_warning_when_present():
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5,
            "warning": {"title": "Fixture type needs confirmation",
                        "found": "Type F2 appears 3 times on E2.1 but the schedule only lists types A-E.",
                        "why": "F2's exact fixture and price depend on which schedule entry it matches.",
                        "fix": "Check the luminaire schedule for a type F2 entry, or confirm it against the legend.",
                        "where": "E2.1 and the luminaire schedule."}}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["warning"]["found"] == "Type F2 appears 3 times on E2.1 but the schedule only lists types A-E."
    assert row["warning"]["reason"] == "legend"


def test_row_from_spec_falls_back_when_the_model_omits_a_warning():
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["warning"] is not None
    assert "Type F2 appears 3 times on" in row["warning"]["found"]
    assert row["warning"]["fix"] == "Confirm the item type against the schedule, then approve."


def test_row_from_spec_falls_back_when_the_models_warning_is_missing_a_field():
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5,
            "warning": {"title": "x", "found": "y", "why": "z", "fix": "", "where": "E2.1"}}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["warning"]["fix"] == "Confirm the item type against the schedule, then approve."
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `api/`): `pytest tests/test_engine_classify.py -v -k row_from_spec`
Expected: The two new fallback tests pass already (current code always falls back), but `test_row_from_spec_uses_the_models_own_warning_when_present` FAILS — the model's warning text is discarded today.

- [ ] **Step 3: Add `_model_warning` and wire it into `_row_from_spec`**

In `api/app/engine/estimate.py`, add a new function directly after
`_unconfirmed_type_warning` (defined a few lines above `_row_from_spec`):

```python
def _model_warning(raw: dict | None, tag: str, count: int, sheet_no: str) -> dict:
    """The model was asked to write its own four-field warning alongside
    the classification, in the same call (grounded-classification-
    warnings-design.md). Falls back to the deterministic template if the
    model omitted "warning" or returned something malformed -- an
    attention item must never reach ingest with no warning, or the
    estimator gets no recovery action."""
    fields = ("title", "found", "why", "fix", "where")
    if isinstance(raw, dict) and all(str(raw.get(f) or "").strip() for f in fields):
        return {
            "reason": "legend",
            "title": str(raw["title"]).strip(),
            "found": str(raw["found"]).strip(),
            "why": str(raw["why"]).strip(),
            "fix": str(raw["fix"]).strip(),
            "where": str(raw["where"]).strip(),
        }
    return _unconfirmed_type_warning(tag, count, sheet_no)
```

Then change `_row_from_spec`'s warning line from:

```python
    warning = None if status == "ready" else _unconfirmed_type_warning(cluster.tag, qty, sheet_no)
```

to:

```python
    warning = None if status == "ready" else _model_warning(spec.get("warning"), cluster.tag, qty, sheet_no)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_engine_classify.py -v`
Expected: PASS (all tests in the file, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add api/app/engine/estimate.py api/tests/test_engine_classify.py
git commit -m "Use the classifier's own warning text, falling back per item when it's absent or incomplete"
```

---

### Task 3: Validate model-written warnings at the API boundary

**Files:**
- Modify: `api/app/takeoff/ingest.py`
- Test: `api/tests/test_ingest_mapping.py`

**Interfaces:**
- Consumes: `warning` dicts arriving in each item's raw payload (`raw.get("warning")`), already shaped by `validate_warning()` — Task 3 adds a groundedness pass after that shape check, before the warning is stored.
- Produces: `is_warning_grounded(warning: dict, valid_sheet_numbers: set[str]) -> bool` and `fallback_warning(tag: str, count, sheet_number: str) -> dict`, both new module-level functions in `ingest.py`. Nothing outside this module calls them yet.

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_ingest_mapping.py`, after
`test_map_payload_carries_the_cluster_tag`:

```python
def test_map_payload_keeps_a_grounded_warning():
    warning = {"reason": "legend", "title": "Fixture type needs confirmation",
               "found": "Type F2 appears 3 times on E2.1, but the schedule only lists types A-E.",
               "why": "F2's exact fixture and price depend on which schedule entry it matches.",
               "fix": "Check the luminaire schedule for a type F2 entry.",
               "where": "E2.1 and the luminaire schedule."}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    mapped = map_payload(_payload(items=[item]))
    assert mapped.items[0]["warning"]["found"] == warning["found"]


def test_map_payload_replaces_a_warning_that_references_an_unknown_sheet():
    warning = {"reason": "legend", "title": "x",
               "found": "Type F2 appears 3 times on E9.9, but the schedule only lists types A-E.",
               "why": "y", "fix": "z", "where": "E9.9"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2", "quantity": 3}
    mapped = map_payload(_payload(items=[item]))
    assert "E9.9" not in mapped.items[0]["warning"]["found"]
    assert mapped.items[0]["warning"]["title"] == "Item type needs confirmation"


def test_map_payload_replaces_a_warning_carrying_ai_framing():
    warning = {"reason": "legend", "title": "x",
               "found": "The AI is not confident about type F2 on E2.1.",
               "why": "y", "fix": "z", "where": "E2.1"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    mapped = map_payload(_payload(items=[item]))
    assert mapped.items[0]["warning"]["title"] == "Item type needs confirmation"


def test_map_payload_does_not_flag_a_legitimate_word_containing_ai():
    warning = {"reason": "legend", "title": "x",
               "found": "Type F2 appears 3 times on E2.1; explain the schedule detail before approving.",
               "why": "y", "fix": "z", "where": "E2.1"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    mapped = map_payload(_payload(items=[item]))
    assert mapped.items[0]["warning"]["found"] == warning["found"]
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `api/`): `pytest tests/test_ingest_mapping.py -v -k "grounded or unknown_sheet or ai_framing or legitimate_word"`
Expected: `test_map_payload_replaces_a_warning_that_references_an_unknown_sheet` and
`test_map_payload_replaces_a_warning_carrying_ai_framing` FAIL — nothing
replaces an ungrounded warning today. The other two pass already (nothing
currently breaks a grounded warning).

- [ ] **Step 3: Add the groundedness check and wire it into `map_payload`**

In `api/app/takeoff/ingest.py`, add `import re` to the top-level imports
(alongside the existing `import base64`), then add these module-level
definitions after `VALID_REASONS = {r.value for r in WarningReason}`:

```python
# Mirrors app/engine/documents.py's SHEET_ID pattern -- ingest.py stays
# engine-agnostic, working off the payload contract only, so this is a
# deliberate small duplication rather than a cross-module import.
SHEET_ID = re.compile(r"\bE\d{1,2}\.\d{1,2}\b")

# A model-written warning must never carry this product's own forbidden
# framing (CLAUDE.md: no model names, no confidence numbers, no "I
# think," no processing internals). Matched case-insensitively on word
# boundaries, so a real word like "detail" or "explain" is never a false
# positive.
BANNED_PHRASES = (
    re.compile(r"\bclaude\b", re.I),
    re.compile(r"\bgpt\b", re.I),
    re.compile(r"\bchatgpt\b", re.I),
    re.compile(r"\bgemini\b", re.I),
    re.compile(r"\bllm\b", re.I),
    re.compile(r"\bai\b", re.I),
    re.compile(r"\bconfidence\b", re.I),
    re.compile(r"\bi think\b", re.I),
    re.compile(r"\bi believe\b", re.I),
    re.compile(r"\d+\s*%"),
)


def is_warning_grounded(warning: dict, valid_sheet_numbers: set[str]) -> bool:
    """Layer 1 of the grounded-classification-warnings design: a cheap,
    deterministic check that a model-written warning didn't fabricate a
    sheet reference or slip past this product's language rules. Runs on
    every warning regardless of origin -- a deterministic-path warning
    always passes trivially, since its `where` is always the item's own
    real sheet number, sourced the same way this check verifies against."""
    reference_text = " ".join(warning.get(f, "") for f in ("found", "where"))
    referenced = set(SHEET_ID.findall(reference_text))
    if referenced - valid_sheet_numbers:
        return False
    all_text = " ".join(warning.get(f, "") for f in ("title", "found", "why", "fix", "where"))
    return not any(p.search(all_text) for p in BANNED_PHRASES)


def fallback_warning(tag: str, count, sheet_number: str) -> dict:
    """The same generic-but-honest shape estimate.py's deterministic path
    already uses (`_unconfirmed_type_warning`), reconstructed here rather
    than imported -- ingest.py works off the payload contract only and
    does not import from app.engine. This is what a groundedness failure
    falls back to."""
    tag = tag or "?"
    sheet_number = sheet_number or "the sheet"
    return {
        "reason": "legend",
        "title": "Item type needs confirmation",
        "found": f"Type {tag} appears {count} time(s) on {sheet_number}, but its description could not be matched to a schedule with confidence.",
        "why": "The exact item and its price can't be confirmed until the type is matched to the schedule.",
        "fix": "Confirm the item type against the schedule, then approve.",
        "where": f"{sheet_number} and the project schedules.",
    }
```

Then, inside `map_payload`, add one line right after the `sheets` list is
fully built (immediately before `fallback = sheets[0]["key"] if sheets else None`):

```python
    valid_sheet_numbers = {s["number"] for s in sheets}
```

Add one more small helper, right above `map_payload`, that does the
full "validate shape, then check groundedness, then fall back if
needed" sequence in one place:

```python
def _grounded_or_fallback(raw_warning, sheet_number: str, valid_sheet_numbers: set[str], tag: str, quantity) -> dict | None:
    """The single point map_payload calls once an item's own sheet number
    and the document's full valid-sheet set are both known: validate the
    warning's shape, then swap in the deterministic fallback if Layer 1's
    groundedness check fails, otherwise keep the model's own text as-is."""
    if not raw_warning:
        return None
    warning = validate_warning(raw_warning)
    if is_warning_grounded(warning, valid_sheet_numbers):
        return warning
    return fallback_warning(tag, quantity, sheet_number)
```

Finally, inside the items loop, change:

```python
            "warning": validate_warning(warning) if warning else None,
```

to:

```python
            "warning": _grounded_or_fallback(warning, sheet_number, valid_sheet_numbers, str(raw.get("tag") or ""), raw.get("quantity") or 0),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_mapping.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add api/app/takeoff/ingest.py api/tests/test_ingest_mapping.py
git commit -m "Reject a fabricated sheet reference or AI framing in a model-written warning"
```

---

### Task 4: Give the warning card real hierarchy

**Files:**
- Modify: `src/components/ItemDetailPanel.jsx:140-153`
- Modify: `src/styles.css:914-932`
- Test: `src/components/ItemDetailPanel.warnings.test.jsx` (new)

**Interfaces:**
- Consumes: `sel.warnings` — an array of `{ id, title, found, why, fix, where }`, unchanged shape from today.
- Produces: no new props, no new exported functions — a JSX/CSS restructure only. `warncard`, `warncard--missing`, `warncard--attention`, `.warncard h4`, `.warncard p` (the shared base rules used by `ConfirmDrawings.jsx`, `ExportPreview.jsx`, `UploadDocuments.jsx`, `NoteForm.jsx`, `NewProject.jsx`, and `NotesWorkspace.jsx`) are untouched.

- [ ] **Step 1: Write the failing test**

Create `src/components/ItemDetailPanel.warnings.test.jsx`:

```jsx
/* ============================================================
   ItemDetailPanel.warnings.test.jsx — the warning card's internal
   hierarchy (grounded-classification-warnings-design.md, section C):
   found as the lead statement, why as a supporting line, fix pulled out
   as the one instruction, where treated as a citation. Never touches
   the shared .warncard/.warncard--missing/.warncard--attention base
   classes other screens also use.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ItemDetailPanel from "./ItemDetailPanel.jsx";

const baseProps = {
  sheets: [{ id: "sheet-1", number: "E2.1", revision: "A" }],
  edit: null,
  onStartEdit: () => {},
  onChangeEdit: () => {},
  onSaveEdit: () => {},
  onCancelEdit: () => {},
  onApprove: () => {},
  onReject: () => {},
  onRequestDelete: () => {},
  onShowEvidence: () => {},
  onStep: () => {},
  stepIndex: 1,
  stepCount: 3,
  itemError: null,
  onRefreshItem: () => {},
  onDismissItemError: () => {},
  counts: { attention: 1, approved: 2 },
  itemsTotal: 3,
  onNextIssue: () => {},
  currentSheet: null,
};

const sel = {
  id: "item-1", symbol: "luminaire", status: "attention", rejected: false,
  name: "Luminaire type F2", description: "Type F2 luminaire", quantity: 3, unit: "ea",
  system: "Lighting", category: "Fixtures", sheetId: "sheet-1", evidence: null,
  aiConfirmed: false, approvedBy: null, notes: "",
  warnings: [{
    id: "w1", title: "Fixture type needs confirmation",
    found: "Type F2 appears 3 times on E2.1, but the schedule only lists types A-E.",
    why: "F2's exact fixture and price depend on which schedule entry it matches.",
    fix: "Check the luminaire schedule for a type F2 entry.",
    where: "E2.1 and the luminaire schedule.",
  }],
};

describe("ItemDetailPanel — warning card", () => {
  it("renders found, why, fix, and where as distinct, separately styled elements", () => {
    render(<ItemDetailPanel {...baseProps} sel={sel} />);

    const found = screen.getByText(sel.warnings[0].found);
    expect(found).toHaveClass("warncard__found");

    const why = screen.getByText(sel.warnings[0].why);
    expect(why).toHaveClass("warncard__why");

    expect(screen.getByText("What to do")).toBeInTheDocument();
    const fix = screen.getByText(sel.warnings[0].fix);
    expect(fix.closest(".warncard__fix")).not.toBeNull();

    const where = screen.getByText(sel.warnings[0].where);
    expect(where).toHaveClass("warncard__where");
  });

  it("renders every warning when an item carries more than one", () => {
    const twoWarnings = {
      ...sel,
      warnings: [sel.warnings[0], { ...sel.warnings[0], id: "w2", title: "Scale needs confirmation" }],
    };
    render(<ItemDetailPanel {...baseProps} sel={twoWarnings} />);
    expect(screen.getAllByText(sel.warnings[0].found)).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --run ItemDetailPanel.warnings`
Expected: FAIL — `warncard__found`, `warncard__why`, `warncard__fix`, and `warncard__where` don't exist yet; today's markup renders `why`/`fix`/`where` inside a `<dl>` with no matching classes.

- [ ] **Step 3: Restructure the JSX**

In `src/components/ItemDetailPanel.jsx`, replace lines 140–153:

```jsx
            {sel.warnings?.map((w) => (
              <div key={w.id} className={"warncard warncard--" + (sel.status === "missing" ? "missing" : "attention")}>
                <h4>{w.title}</h4>
                <p>{w.found}</p>
                <dl style={{ margin: 0 }}>
                  <dt>Why it matters</dt>
                  <dd>{w.why}</dd>
                  <dt>What to do</dt>
                  <dd>{w.fix}</dd>
                  <dt>Where to look</dt>
                  <dd>{w.where}</dd>
                </dl>
              </div>
            ))}
```

with:

```jsx
            {sel.warnings?.map((w) => (
              <div key={w.id} className={"warncard warncard--" + (sel.status === "missing" ? "missing" : "attention")}>
                <h4>{w.title}</h4>
                <p className="warncard__found">{w.found}</p>
                <p className="warncard__why">{w.why}</p>
                <div className="warncard__fix">
                  <span className="warncard__fix-label">What to do</span>
                  <span>{w.fix}</span>
                </div>
                <p className="warncard__where">{w.where}</p>
              </div>
            ))}
```

- [ ] **Step 4: Restyle in `styles.css`**

In `src/styles.css`, replace the `.warncard dt` / `.warncard dd` rules (lines 920–932):

```css
.warncard dt {
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-3);
  margin-top: 7px;
}

.warncard dd {
  margin: 1px 0 0;
  font-size: 12.5px;
}
```

with:

```css
/* Specificity note: .warncard p already sets font-size/color/margin for
   every <p> inside any .warncard (shared by ConfirmDrawings.jsx,
   ExportPreview.jsx, UploadDocuments.jsx, NoteForm.jsx, NewProject.jsx,
   NotesWorkspace.jsx). Each rule below repeats the element+class pair
   (.warncard p.warncard__X) rather than the class alone, so it reliably
   wins over .warncard p regardless of source order -- a bare
   .warncard__found has the SAME specificity as .warncard p and would
   lose ties unpredictably. */
.warncard p.warncard__found {
  font-size: 13px;
  font-weight: 600;
  margin: 0 0 6px;
}

.warncard p.warncard__why {
  font-size: 11.5px;
  color: var(--ink-3);
  margin: 0 0 10px;
}

.warncard__fix {
  display: flex;
  align-items: baseline;
  gap: 7px;
  padding: 7px 9px;
  margin: 0 0 8px;
  background: var(--surface);
  border: 1px solid var(--line-1);
  border-radius: var(--r-md);
  font-size: 12.5px;
}

.warncard__fix-label {
  flex: none;
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-3);
}

.warncard p.warncard__where {
  font-size: 12px;
  color: var(--blue);
  margin: 0;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- --run ItemDetailPanel.warnings`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full frontend suite and the build**

Run: `npm test -- --run && npm run build`
Expected: PASS — no other test references the removed `.warncard dt`/`dd`
markup (`grep -rn "warncard" src/components` confirms no other component
renders a `<dl>` inside a `.warncard`).

- [ ] **Step 7: Commit**

```bash
git add src/components/ItemDetailPanel.jsx src/components/ItemDetailPanel.warnings.test.jsx src/styles.css
git commit -m "Give the warning card real hierarchy: found leads, fix is pulled out, where reads as a citation"
```

---

### Task 5: A frozen eval set and rubric judge for warning quality

**Files:**
- Create: `api/eval/__init__.py`
- Create: `api/eval/warning_eval_cases.py`
- Create: `api/eval/rubric.py`
- Create: `api/eval/run_warning_eval.py`
- Create: `api/eval/README.md`
- Test: `api/tests/test_eval_rubric.py` (new)

**Interfaces:**
- Consumes: `app.engine.llm.estimate()` and `app.engine.llm.available()` (Task 1, unchanged signatures).
- Produces: `eval.warning_eval_cases.CASES` (a list of input fixtures), `eval.rubric.grade(tags, schedule_text, warning) -> dict` and `eval.rubric.CRITERIA` (a tuple of criterion names), `eval.run_warning_eval.main() -> int`. Nothing in `app/` imports from `eval/` — it's one-directional tooling, not part of the request path.

- [ ] **Step 1: Create the eval package and frozen case set**

Create `api/eval/__init__.py`:

```python
"""Offline quality evaluation for the takeoff engine's grounded
classification warnings -- not part of the pytest suite. See
run_warning_eval.py and README.md."""
```

Create `api/eval/warning_eval_cases.py`:

```python
"""Frozen eval set for grounded classification warnings
(docs/superpowers/specs/2026-09-01-grounded-classification-warnings-design.md,
section D). Fixed inputs -- a score change on a prompt edit is
attributable to the prompt, not to different test data. Extend this list
once real design-partner drawing sets exist (BUILD-STAGES.md's "frozen
eval set per agent"); for now it mirrors the fixtures already exercised
in api/tests/test_engine_classify.py.
"""

CASES = [
    {
        "id": "unlisted-fixture-letter",
        "tags": [{"tag": "F2", "count": 3}, {"tag": "R", "count": 40}],
        "schedule_text": "LUMINAIRE SCHEDULE\nTYPE A - 2x4 LED TROFFER\nTYPE B - LED HIGH BAY\nTYPE C - EXIT SIGN",
        "location": "Sacramento, CA",
    },
    {
        "id": "unrecognized-tag",
        "tags": [{"tag": "Z9", "count": 4}],
        "schedule_text": "",
        "location": "Chicago, IL",
    },
    {
        "id": "recognized-device-no-warning-expected",
        "tags": [{"tag": "R", "count": 22}],
        "schedule_text": "",
        "location": "Denver, CO",
    },
    {
        "id": "fixture-letter-in-schedule",
        "tags": [{"tag": "A", "count": 18}],
        "schedule_text": "LUMINAIRE SCHEDULE\nTYPE A - 2x4 LED TROFFER, 3500 LUMEN",
        "location": "Austin, TX",
    },
]
```

- [ ] **Step 2: Write the failing test for the rubric's validation logic**

Create `api/tests/test_eval_rubric.py`:

```python
"""eval/rubric.py's grade() response-validation -- the parts that don't
need a live API call. eval/ is offline tooling with real API calls in
its main path (see eval/README.md); this test exercises only the
deterministic validation around that call, using a mocked Anthropic
client."""

from unittest.mock import MagicMock, patch

import pytest

from eval.rubric import grade
from eval.warning_eval_cases import CASES


def test_eval_cases_are_well_formed():
    for case in CASES:
        assert case["id"]
        assert case["tags"]
        for t in case["tags"]:
            assert "tag" in t and "count" in t


def _fake_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


def test_grade_rejects_an_invalid_criterion_score():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        '{"specificity": "pass", "faithfulness": "maybe", "actionability": "pass", "consequence_realism": "pass", "notes": ""}'
    )
    with patch("anthropic.Anthropic", return_value=fake_client):
        with pytest.raises(ValueError, match="faithfulness"):
            grade([{"tag": "F2", "count": 3}], "", {"title": "x", "found": "y", "why": "z", "fix": "w", "where": "v"})


def test_grade_parses_a_well_formed_response():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        '{"specificity": "pass", "faithfulness": "fail", "actionability": "pass", "consequence_realism": "pass", "notes": "cites a sheet not in the input"}'
    )
    with patch("anthropic.Anthropic", return_value=fake_client):
        result = grade([{"tag": "F2", "count": 3}], "", {"title": "x", "found": "y", "why": "z", "fix": "w", "where": "v"})
    assert result["faithfulness"] == "fail"
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `api/`): `pytest tests/test_eval_rubric.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.rubric'` — `rubric.py` doesn't exist yet.

- [ ] **Step 4: Write the rubric and judge**

Create `api/eval/rubric.py`:

```python
"""Rubric-based judge for grounded classification warnings
(design doc section D, Layer 2). Scores each generated warning against
independent, atomic criteria rather than one holistic verdict --
decomposed criteria are what keeps an LLM-as-judge's output reliable and
comparable run to run. Not a runtime check: this runs offline, against
the frozen eval set, when the prompt in app/engine/llm.py changes.
"""

from __future__ import annotations

import json

MODEL = "claude-opus-5"

CRITERIA = ("specificity", "faithfulness", "actionability", "consequence_realism")

_JUDGE_PROMPT = """You are grading one warning an electrical-estimating tool generated to explain why an item needs a person's attention.

Input the classifier saw:
Tags counted: {tags}
Schedule/legend text: \"\"\"{schedule_text}\"\"\"

The warning it generated:
Title: {title}
Found: {found}
Why: {why}
Fix: {fix}
Where: {where}

Score each criterion "pass" or "fail":
- specificity: does "found" cite this item's actual tag, count, and sheet, or could this sentence be pasted onto any item unchanged?
- faithfulness: does every claim in the warning trace back to something in the tags or schedule text above? A claim not supported by that input is a fail, even if it sounds plausible.
- actionability: is "fix" a step an estimator could actually go do, or a restatement of the problem dressed up as an instruction?
- consequence_realism: does "why" state a real, item-specific consequence, or generic boilerplate that would fit any warning?

Return ONLY JSON: {{"specificity": "pass"|"fail", "faithfulness": "pass"|"fail", "actionability": "pass"|"fail", "consequence_realism": "pass"|"fail", "notes": "<one sentence on the clearest failure, or \\"\\" if all pass>"}}"""


def grade(tags: list[dict], schedule_text: str, warning: dict) -> dict:
    """One judge call, one warning. Returns a dict with "pass"/"fail"
    per criterion in CRITERIA, plus "notes". Raises on an API failure or
    a response that doesn't parse -- an eval run should surface that
    loudly, not silently skip a case."""
    from anthropic import Anthropic

    client = Anthropic()
    tag_text = ", ".join(f"{t['tag']} x{t['count']}" for t in tags)
    prompt = _JUDGE_PROMPT.format(
        tags=tag_text, schedule_text=(schedule_text or "")[:2000],
        title=warning.get("title", ""), found=warning.get("found", ""),
        why=warning.get("why", ""), fix=warning.get("fix", ""), where=warning.get("where", ""),
    )
    msg = client.messages.create(
        model=MODEL, max_tokens=500, output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    result = json.loads(text)
    for c in CRITERIA:
        if result.get(c) not in ("pass", "fail"):
            raise ValueError(f"judge returned an invalid score for {c!r}: {result.get(c)!r}")
    return result
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_eval_rubric.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Write the runner and the README**

Create `api/eval/run_warning_eval.py`:

```python
"""Run the grounded-warnings eval set against the current prompt in
app/engine/llm.py, and print per-criterion pass rates.

Usage (from api/, with ANTHROPIC_API_KEY set):
    python -m eval.run_warning_eval

This is a development-time gate, not a CI test: it makes real API calls
(one classification call plus one judge call per non-"ready" item), and
its purpose is to compare quality across a prompt change -- run it before
and after editing app/engine/llm.py's _prompt(), and read the diff in
pass rates, not just whether it printed 100%.

Before trusting the printed rates: grade 15-20 warnings by hand and
check them against the judge's verdicts (design doc section D,
"Calibration"). If they disagree, fix the rubric wording in rubric.py --
don't override the judge's score case by case.
"""

from __future__ import annotations

import sys

from app.engine import llm
from eval.rubric import CRITERIA, grade
from eval.warning_eval_cases import CASES


def main() -> int:
    if not llm.available():
        print("ANTHROPIC_API_KEY is not set -- this eval makes real model calls and needs it.")
        return 1

    totals = {c: [0, 0] for c in CRITERIA}  # criterion -> [passes, total]
    warned = 0

    for case in CASES:
        try:
            result = llm.estimate(case["tags"], case["schedule_text"], case["location"])
        except Exception as exc:  # noqa: BLE001 -- report and keep going
            print(f"[{case['id']}] classification call failed: {exc}")
            continue

        for item in result.get("items", []):
            warning = item.get("warning")
            if not warning:
                continue
            warned += 1
            try:
                verdict = grade(case["tags"], case["schedule_text"], warning)
            except Exception as exc:  # noqa: BLE001 -- one bad judge call must not stop the run
                print(f"[{case['id']}] tag {item.get('tag')}: judge call failed: {exc}")
                continue
            print(f"[{case['id']}] tag {item.get('tag')}: {verdict}")
            for c in CRITERIA:
                totals[c][1] += 1
                if verdict[c] == "pass":
                    totals[c][0] += 1

    print(f"\n{warned} warnings graded across {len(CASES)} cases.\n")
    for c in CRITERIA:
        passes, total = totals[c]
        rate = f"{passes}/{total}" if total else "no warnings graded"
        print(f"  {c}: {rate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Create `api/eval/README.md`:

```markdown
# Grounded classification warnings — eval

What this measures: whether `app/engine/llm.py`'s classification call is
writing warnings that are specific, faithful to what it was actually
given, actionable, and stating a real consequence — not just whether the
four fields are present (that's `ingest.py`'s job, enforced on every real
request).

Design: `docs/superpowers/specs/2026-09-01-grounded-classification-warnings-design.md`, section D.

## Running it

From `api/`, with `ANTHROPIC_API_KEY` set:

    python -m eval.run_warning_eval

This makes real API calls (a classification call per eval case, plus a
judge call per generated warning) — it is not part of `pytest` and does
not run in CI. Run it when you change the prompt in `app/engine/llm.py`,
before and after, and compare the printed pass rates.

## Before trusting the numbers

Grade 15–20 of the generated warnings by hand and compare your grading to
the judge's verdicts. If they disagree, fix the wording in `rubric.py`'s
`_JUDGE_PROMPT` — don't override individual scores. Once your grading and
the judge's line up, trust it for the full set.

## Growing the eval set

`warning_eval_cases.py`'s `CASES` list starts from the fixtures already
used in `api/tests/test_engine_classify.py`. Add a case here whenever a
real design-partner drawing set surfaces a warning that was wrong in a
new way — the eval set should grow from real failures, not be padded out
speculatively.
```

- [ ] **Step 7: Verify the module runs (without an API key, as the documented failure path)**

Run (from `api/`): `python -m eval.run_warning_eval`
Expected: prints `ANTHROPIC_API_KEY is not set -- this eval makes real model calls and needs it.` and exits 1 — confirms the module imports cleanly and the no-key path works, without spending real API calls in this step.

- [ ] **Step 8: Commit**

```bash
git add api/eval/ api/tests/test_eval_rubric.py
git commit -m "Add a frozen eval set and rubric judge for warning quality"
```

---

## Self-Review

**Spec coverage:**
- Section A (real explanations from the existing call) → Task 1 (prompt/schema) + Task 2 (wiring, fallback).
- Section B (validation at the boundary, Layer 1) → Task 3.
- Section C (warning card hierarchy) → Task 4.
- Section D (eval, both layers) → Layer 1 is Task 3 itself; Layer 2 is Task 5.
- Scope section's exclusions (Counting placement, conversation panel) → untouched by every task; `counting.py` and any chat/conversation code are not referenced anywhere in this plan.

**Placeholder scan:** No TBD/TODO. Every step carries real code, real
file paths, and real test assertions.

**Type consistency:** `warning` stays a `{reason, title, found, why, fix,
where}` dict (or `None`) across every task — Task 1's prompt produces a
4-field sub-object, Task 2's `_model_warning` adds `reason: "legend"` to
match the shape `validate_warning()` (Task 3) already expects, and Task
4's frontend renders exactly those same five estimator-facing keys. No
task introduces a field name another task doesn't already use.
