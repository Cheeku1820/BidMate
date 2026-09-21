# Pricing hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a `price` job from re-queueing itself forever while a market source is down, and make a broken supplier price sheet explain its unreadable rows instead of failing the upload.

**Architecture:** Two contained fixes inside the worker's pricing jobs. The price job gates its follow-on on whether any source call this run got an answer. The price-sheet parser catches per-row failures into a new `unreadable` list that flows through the job payload, the API schema, the store mapping, and a fourth group in the import modal; a `price_sheet` job that dies lands its own estimator copy.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest (backend, `TEST_DATABASE_URL` in `api/.env`). React 18, Vitest, React Testing Library.

**Spec:** [`docs/specs/pricing-hardening.md`](../specs/pricing-hardening.md), written 2026-09-21.

## Global Constraints

- **Files this stream may edit:** `api/app/worker/price_job.py`, `api/app/market/price_sheet.py`, `api/app/worker/price_sheet_job.py`, `api/app/market/copy.py`, `api/app/takeoff/price_sheet_router.py`, `api/app/takeoff/schemas.py` (append only), `src/components/pricing/PriceSheetImport.jsx` and its test, and the tests for those modules. Three shared files get an appended line each, named in the commit message: `api/app/jobs/copy.py`, `api/app/jobs/queue.py` (`terminal_copy`), `src/lib/store/api.js` (`getPriceSheetPreview`).
- **No migrations.** No edits to `CLAUDE.md`, `README.md`, `docs/README.md`, `src/styles.css`.
- **Copy rules:** sentence case, no "please", no exclamation marks, no vendor or model names in estimator-facing text. Every warning carries `title`, `found`, `why`, `fix`, `where`.
- **Git:** never `git stash`; never `git add -A` (the `bid_examples` symlink must never be committed). Commit message: a plain sentence, blank line, `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Backend tests:** `cd api && ../.enginevenv/bin/python -m pytest -q <file>`. Frontend: `npm test -- --run <file>`. `npm run build` before the last commit.

---

## File Structure

**Modified**
- `api/app/worker/price_job.py` — count source answers per run; gate the follow-on.
- `api/app/market/price_sheet.py` — `price_in_range` non-finite; `RowUnreadable`; `_read_price`; `ParsedSheet.unreadable`; per-row try; all-unreadable refusal.
- `api/app/worker/price_sheet_job.py` — `unreadable` on the preview payload.
- `api/app/takeoff/schemas.py` — `PriceSheetPreviewOut.unreadable` (appended field).
- `api/app/jobs/copy.py` — `PRICE_SHEET_FAILED` (appended).
- `api/app/jobs/queue.py` — `terminal_copy` price_sheet case (one added line).
- `src/lib/store/api.js` — map `unreadable` (one added line).
- `src/components/pricing/PriceSheetImport.jsx` — fourth group.
- Tests: `api/tests/test_worker_price.py`, `api/tests/test_market_price_sheet.py`, `api/tests/test_worker_price_sheet.py`, `src/components/pricing/PriceSheetImport.test.jsx`.

---

### Task 1: The price job stops without a follow-on when every source call failed

**Files:**
- Modify: `api/app/worker/price_job.py:99-115` (the budget check) and the `try/except SourceError` block
- Test: `api/tests/test_worker_price.py`

**Interfaces:**
- Produces: no new names. Behaviour: at the budget, `queue.enqueue_price(...)` is called only when `answered > 0 or calls == 0`, where `calls` counts `source.lookup` attempts this run and `answered` those that returned.

- [ ] **Step 1: Write the failing tests** (append to `api/tests/test_worker_price.py`)

```python
def test_a_run_whose_source_calls_all_failed_stops_without_a_follow_on(db, project, sheet, dana, monkeypatch):
    """A source that is down turns every run into `failed` rows and a
    follow-on that does the same -- forever, with Refresh disabled the
    whole time. At the budget, a run that got no answer from any source
    call marks itself done and queues nothing; the rows read 'Market
    estimate didn't complete', and Refresh is the estimator's retry."""
    project.postal_code = "78701"
    src = FakeSource("onebuild", SourceError("timeout"))
    _wire(monkeypatch, db, {"onebuild": src})
    over = price_job.PRICE_JOB_BUDGET_SECONDS + 1
    ticks = iter([0, 0, 0, over])
    monkeypatch.setattr(price_job, "_clock", lambda: next(ticks, over))
    items = [_item(db, project, sheet, f"Item {n}") for n in range(4)]
    first = queue.enqueue_price(db, project, dana.id)
    db.commit()
    assert worker.tick("t")
    db.refresh(first)
    assert first.status == "done" and src.calls == ["Item 0", "Item 1"]
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "price", Job.project_id == project.id)) == 1
    assert [db.get(ItemMarketPrice, i.id).outcome if db.get(ItemMarketPrice, i.id) else None for i in items] == ["failed", "failed", None, None]


def test_a_run_with_one_answer_among_failures_still_queues_the_follow_on(db, project, sheet, dana, monkeypatch):
    project.postal_code = "78701"
    answers = iter([SourceError("timeout"), SourceError("timeout"), _priced()])

    class Flaky(FakeSource):
        def lookup(self, query, unit, loc):
            self.calls.append(query)
            a = next(answers)
            if isinstance(a, Exception):
                raise a
            return a

    src = Flaky("onebuild")
    _wire(monkeypatch, db, {"onebuild": src})
    over = price_job.PRICE_JOB_BUDGET_SECONDS + 1
    ticks = iter([0, 0, 0, 0, over])
    monkeypatch.setattr(price_job, "_clock", lambda: next(ticks, over))
    [_item(db, project, sheet, f"Item {n}") for n in range(5)]
    first = queue.enqueue_price(db, project, dana.id)
    db.commit()
    assert worker.tick("t")
    db.refresh(first)
    assert first.status == "done" and len(src.calls) == 3
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "price", Job.project_id == project.id, Job.status == "queued")) == 1


def test_a_run_past_budget_that_made_no_source_call_still_queues_the_follow_on(db, project, sheet, dana, monkeypatch):
    """Nothing this run did was the problem -- quote-required items cost
    no call -- so the remainder is safe to continue."""
    project.postal_code = "78701"
    src = FakeSource("onebuild", _priced())
    _wire(monkeypatch, db, {"onebuild": src})
    over = price_job.PRICE_JOB_BUDGET_SECONDS + 1
    ticks = iter([0, 0, 0, over])
    monkeypatch.setattr(price_job, "_clock", lambda: next(ticks, over))
    _item(db, project, sheet, "Switch Board MSBS"); _item(db, project, sheet, "Transformer T1"); _item(db, project, sheet, "Item 2")
    first = queue.enqueue_price(db, project, dana.id)
    db.commit()
    assert worker.tick("t")
    db.refresh(first)
    assert first.status == "done" and src.calls == []
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "price", Job.project_id == project.id, Job.status == "queued")) == 1
```

- [ ] **Step 2: Run to verify the first fails** — `cd api && ../.enginevenv/bin/python -m pytest -q tests/test_worker_price.py -k "follow_on"`. Expected: the first test fails on the job count (2, not 1); the other two pass already.

- [ ] **Step 3: Implement** in `price_job.py`: add `calls = answered = 0` after `started = _clock()`; in the budget branch, `queue.mark_done(db, job)` then `if answered or not calls: queue.enqueue_price(...)`; `break`. Increment `calls += 1` before `source.lookup`, `answered += 1` after it returns. Update the module docstring's last paragraph to say when the follow-on is not queued.

- [ ] **Step 4: Run** `pytest -q tests/test_worker_price.py`. Expected: all pass.

- [ ] **Step 5: Commit** `git add api/app/worker/price_job.py api/tests/test_worker_price.py docs/specs/pricing-hardening.md docs/plans/pricing-hardening.md`.

---

### Task 2: The parser reports unreadable rows instead of raising

**Files:**
- Modify: `api/app/market/price_sheet.py`
- Test: `api/tests/test_market_price_sheet.py`

**Interfaces:**
- Produces: `ParsedSheet(rows, refused, unreadable: list[tuple[int, str]])`; `class RowUnreadable(Exception)`; `_read_price(v) -> Decimal | None` (raises `RowUnreadable`); `price_in_range` false for non-finite; `REFUSED_ALL_UNREADABLE = "None of the rows could be read. Start from Download price request."`.

- [ ] **Step 1: Failing tests** (append)

```python
def test_price_in_range_is_false_for_nan_and_infinity():
    assert price_in_range(Decimal("NaN")) is False
    assert price_in_range(Decimal("Infinity")) is False


def _csv(rows: str) -> ParsedSheet:
    return parse_price_sheet(("Item,Unit price\n" + rows).encode(), "q.csv")


def test_parse_lists_a_row_whose_price_is_not_a_number_as_unreadable():
    p = _csv("20A duplex receptacle,call for price\nPanelboard,9.10\n")
    assert [r.item_name for r in p.rows] == ["Panelboard"]
    assert p.unreadable == [(2, "the price isn't a number")] and p.refused is None


def test_parse_lists_a_nan_price_cell_as_unreadable():
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Item", "Unit price"]); ws.append(["Panelboard", float("nan")]); ws.append(["Receptacle", 9.10])
    out = io.BytesIO(); wb.save(out)
    p = parse_price_sheet(out.getvalue(), "q.xlsx")
    assert [r.item_name for r in p.rows] == ["Receptacle"] and p.unreadable == [(2, "the price isn't a number")]


def test_parse_lists_a_row_with_a_price_but_no_item_name_as_unreadable_and_skips_empty_rows():
    p = _csv(",9.10\n,\nPanelboard,9.10\n")
    assert [r.item_name for r in p.rows] == ["Panelboard"]
    assert p.unreadable == [(2, "the row has no item name")]


def test_parse_reports_any_other_row_failure_rather_than_raising(monkeypatch):
    def boom(v):
        raise RuntimeError("openpyxl did something odd")
    monkeypatch.setattr("app.market.price_sheet._read_price", boom)
    p = _csv("Panelboard,9.10\n")
    assert p.rows == [] and p.unreadable == [(2, "the row couldn't be read")]
    assert p.refused == REFUSED_ALL_UNREADABLE


def test_parse_refuses_a_sheet_whose_rows_are_all_unreadable():
    p = _csv("A,call for price\nB,TBD\n")
    assert p.rows == [] and len(p.unreadable) == 2 and p.refused == REFUSED_ALL_UNREADABLE


def test_parse_blank_price_stays_unpriced_not_unreadable():
    p = _csv("Panelboard,\n")
    assert p.rows[0].unit_price is None and p.unreadable == [] and p.refused is None
```

Imports to add at the top of the test file: `ParsedSheet, REFUSED_ALL_UNREADABLE, parse_price_sheet, price_in_range`.

- [ ] **Step 2: Run** `pytest -q tests/test_market_price_sheet.py`. Expected: import error / failures on the new tests.

- [ ] **Step 3: Implement** in `price_sheet.py`:

```python
REFUSED_ALL_UNREADABLE = "None of the rows could be read. Start from Download price request."
NOT_A_NUMBER = "the price isn't a number"
NO_ITEM_NAME = "the row has no item name"
ROW_UNREADABLE = "the row couldn't be read"


def price_in_range(value: Decimal) -> bool:
    return value.is_finite() and Decimal(0) <= value < PRICE_LIMIT


class RowUnreadable(Exception):
    """A row the parser can't read, with the reason in the estimator's words."""


class ParsedSheet(NamedTuple):
    rows: list[ParsedRow]
    refused: str | None
    unreadable: list[tuple[int, str]] = []
```

`_read_price(v)`: bool → `None`; `None`/`""` → `None`; number → quantize inside try; `InvalidOperation` → `raise RowUnreadable(NOT_A_NUMBER)`; NaN survives quantize, so `if not d.is_finite(): raise RowUnreadable(NOT_A_NUMBER)`; then `return d if price_in_range(d) else None`. String → strip as today; if it matches neither regex → `raise RowUnreadable(NOT_A_NUMBER)`; `Decimal(s)` failure → same; range as before. `_price(v)` becomes `try: return _read_price(v) except RowUnreadable: return None`.

Row loop: each row inside `try`; `if all(c is None or not str(c).strip() for c in row): continue`; blank name → `raise RowUnreadable(NO_ITEM_NAME)`; `except RowUnreadable as exc: unreadable.append((n, str(exc)))`; `except Exception: unreadable.append((n, ROW_UNREADABLE))`. After the loop: `refused = REFUSED_ALL_UNREADABLE if unreadable and not rows else None`; `return ParsedSheet(rows, refused, unreadable)`. Update the module docstring.

- [ ] **Step 4: Run** `pytest -q tests/test_market_price_sheet.py`. Expected: all pass.

- [ ] **Step 5: Commit** `git add api/app/market/price_sheet.py api/tests/test_market_price_sheet.py`.

---

### Task 3: The job carries the group, the failure copy fits a spreadsheet

**Files:**
- Modify: `api/app/worker/price_sheet_job.py`, `api/app/takeoff/schemas.py` (append field), `api/app/jobs/copy.py` (append), `api/app/jobs/queue.py:181-187` (one line)
- Test: `api/tests/test_worker_price_sheet.py`

**Interfaces:**
- Produces: preview payload key `"unreadable": [{"line": int, "reason": str}]`; `PriceSheetPreviewOut.unreadable: list[dict] = []`; `copy.PRICE_SHEET_FAILED`.

- [ ] **Step 1: Failing tests** (append)

```python
def test_preview_lists_unreadable_rows_with_line_and_reason(db, project, sheet, item, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _sheet_doc(db, project, dana, inline, f"Item,Unit price\n{item.name},call for price\n,4\n".encode(), name="q.csv")
    job = queue.enqueue_price_sheet(db, d, dana.id); _run_all(db)
    db.refresh(job)
    p = job.payload["preview"]
    assert job.status == "done" and p["refused"] is not None
    assert p["unreadable"] == [{"line": 2, "reason": "the price isn't a number"}, {"line": 3, "reason": "the row has no item name"}]
    assert p["matched"] == [] and [u["item_id"] for u in p["unpriced"]] == [str(item.id)]


def test_a_price_sheet_job_that_dies_lands_spreadsheet_copy_not_pdf_copy(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    def boom(data, filename):
        raise RuntimeError("workbook exploded")
    monkeypatch.setattr("app.worker.price_sheet_job.parse_price_sheet", boom)
    d = _sheet_doc(db, project, dana, inline, b"Item,Unit price\nx,1\n", name="q.csv")
    job = queue.enqueue_price_sheet(db, d, dana.id); _run_all(db)
    db.refresh(job)
    assert job.status == "failed" and job.error == copy.PRICE_SHEET_FAILED
    assert "PDF" not in job.error


def test_preview_schema_accepts_a_payload_without_the_unreadable_group():
    assert PriceSheetPreviewOut(state="ready").unreadable == []
```

Imports: `from app.jobs import copy, queue`; `from app.takeoff.schemas import PriceSheetPreviewOut`.

- [ ] **Step 2: Run** `pytest -q tests/test_worker_price_sheet.py`. Expected: the three new tests fail.

- [ ] **Step 3: Implement** — job: `"unreadable": [{"line": line, "reason": reason} for line, reason in parsed.unreadable]` in the preview dict. Schema: `unreadable: list[dict] = []` after `unpriced`. `jobs/copy.py` append: `PRICE_SHEET_FAILED = "The price sheet couldn't be read. Start from Download price request and upload the filled file."`. `queue.terminal_copy`: `if job.kind == "price_sheet" and message in ("", copy.UNREADABLE): return copy.PRICE_SHEET_FAILED` before the final return; extend the docstring's list of kinds.

- [ ] **Step 4: Run** `pytest -q tests/test_worker_price_sheet.py tests/test_jobs_queue.py tests/test_worker_sandbox.py`. Expected: pass.

- [ ] **Step 5: Commit** by path, message noting the appended lines in `jobs/copy.py` and `queue.py`.

---

### Task 4: The modal shows the fourth group

**Files:**
- Modify: `src/lib/store/api.js` (one line in `getPriceSheetPreview`), `src/components/pricing/PriceSheetImport.jsx`
- Test: `src/components/pricing/PriceSheetImport.test.jsx`

- [ ] **Step 1: Failing tests** (append inside the `describe`)

```jsx
  it("lists the rows that couldn't be read, with the line and the reason", async () => {
    const s = store({ getPriceSheetPreview: vi.fn().mockResolvedValue({
      ...preview, unreadable: [{ line: 4, reason: "the price isn't a number" }, { line: 7, reason: "the row has no item name" }],
    }) });
    render(<PriceSheetImport projectId="p1" store={s} onApplied={vi.fn()} onClose={() => {}} />);
    const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await userEvent.upload(screen.getByLabelText("Price sheet"), file);
    expect(await screen.findByText(withText("h4", "2 rows couldn't be read"))).toBeInTheDocument();
    expect(screen.getByText(withText("li", "Row 4 — the price isn't a number"))).toBeInTheDocument();
    expect(screen.getByText(withText("li", "Row 7 — the row has no item name"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply 1 price" })).toBeInTheDocument();
  });

  it("shows the refusal when none of the rows could be read, with nothing to apply", async () => {
    const s = store({ getPriceSheetPreview: vi.fn().mockResolvedValue({
      state: "ready", refused: "None of the rows could be read. Start from Download price request.",
      matched: [], unmatched: [], unpriced: [], unreadable: [{ line: 2, reason: "the price isn't a number" }],
      supplierName: "", quoteDate: null,
    }) });
    render(<PriceSheetImport projectId="p1" store={s} onApplied={vi.fn()} onClose={() => {}} />);
    const file = new File(["x"], "codale.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await userEvent.upload(screen.getByLabelText("Price sheet"), file);
    expect(await screen.findByRole("alert")).toHaveTextContent("None of the rows could be read. Start from Download price request.");
    expect(screen.queryByRole("button", { name: /Apply/ })).not.toBeInTheDocument();
  });
```

Also add `unreadable: []` to the shared `preview` fixture.

- [ ] **Step 2: Run** `npm test -- --run src/components/pricing/PriceSheetImport.test.jsx`. Expected: the first new test fails.

- [ ] **Step 3: Implement** — `api.js`: `unreadable: (p.unreadable ?? []).map((u) => ({ line: u.line, reason: u.reason })),`. Modal: after the unpriced group,

```jsx
          {(preview.unreadable ?? []).length > 0 ? (
            <div className="pricesheet-group">
              <h4><CountLabel n={preview.unreadable.length} singular="row couldn't be read" plural="rows couldn't be read" /></h4>
              <ul className="pricesheet-plainlist">
                {preview.unreadable.map((row) => (
                  <li key={row.line}>
                    Row <span className="tabular">{row.line}</span> — {row.reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
```

Update the header comment's "three groups" to four.

- [ ] **Step 4: Run** the modal test, then `npm test -- --run`, then `npm run build`. Expected: green, clean.

- [ ] **Step 5: Full backend suite** `cd api && ../.enginevenv/bin/python -m pytest -q`. Expected: green.

- [ ] **Step 6: Commit** by path, message noting the appended line in `api.js`.
