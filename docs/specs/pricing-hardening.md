# Pricing hardening: the two parked bugs

Written 2026-09-21. Stream A of [`docs/roadmap/workstreams-2026-09.md`](../roadmap/workstreams-2026-09.md) §1.A. A short design note, not a full spec: both fixes sit inside [`estimate-first-pricing.md`](estimate-first-pricing.md) §3 and §6 and change no data model, no migration, and no route.

## 1. A price job can loop while a source is down

**What happens.** `price_job.py` stops itself at 90 s and queues a follow-on `price` job so the sandbox never kills it mid-call. Every source call has a 20 s timeout, so a source that is down turns each run into four or five `failed` rows and a follow-on — which writes the same rows and queues another, forever. The workspace shows "Refreshing market estimates" with Refresh disabled for as long as the source is down.

**The rule.** The follow-on exists to continue where the budget cut a run off. A run whose budget went on source calls that all failed will do the same again, so at the budget it queues a follow-on only when at least one source call this run came back with an answer (`priced` or `no_match`), **or** when no source call was made at all — a run that ran out of time on cache hits and deterministic outcomes alone can safely continue, because nothing it did was the problem.

Why not "any outcome other than `failed`": `quote_required`, `unavailable`, `location_needed`, `over_budget`, and cache hits are rewritten every run without spending anything. A project with one switchboard and a dead source would pass that test on every run and loop just the same.

**What the estimator sees.** The rows read *Missing information* with the `failed` warning from `market/copy.py` — title "Market estimate didn't complete", fix "Refresh market estimates. If it happens again, enter a price." — which the Material pricing grid renders on every outcome row through one path (`pricingColumns.jsx`, `row-warning`). With no job queued, Refresh is enabled again, so the fix it names is a press away. No new copy.

**Tests** (`api/tests/test_worker_price.py`): a source that always raises `SourceError` with the clock past budget → exactly one `price` job, no follow-on, every row `failed`; a source that fails for two items then answers, past budget → the follow-on is queued as before; a run past budget with no source call at all → follow-on queued.

## 2. A broken spreadsheet fails the upload instead of being explained

**What happens.** A NaN cell in the price column quantizes to NaN and `price_in_range` raises on the comparison. Any exception inside `parse_price_sheet`'s row loop escapes the job body, and the worker lands the generic read copy — "Try re-saving it as PDF" — on a spreadsheet.

**The parser.** `price_in_range` is false for anything non-finite. The row loop reads each row inside a `try`, and a row that cannot be read is reported rather than raised:

| Row | Result |
|---|---|
| Every cell blank | Skipped, as today (a formatted-but-empty row in an .xlsx) |
| Content, but no item name | Unreadable: "the row has no item name" |
| Price cell blank | Read, `unit_price` None — listed as unpriced, as today |
| Price cell present but not a number (text, NaN, infinity, scientific notation, a European "2.250,00") | Unreadable: "the price isn't a number" |
| Price negative or at or over 100,000,000 | Read, `unit_price` None — unpriced, as today |
| Anything else raises | Unreadable: "the row couldn't be read" |

`ParsedSheet` gains `unreadable: list[tuple[int, str]]` — `(line, reason)`. A sheet whose data rows are all unreadable is refused: "None of the rows could be read. Start from Download price request." A sheet with no data rows at all is not refused (unchanged).

The estimator-facing change is that a supplier who wrote "call for price" or "TBD" in the price column now sees that row named with why, instead of the item quietly appearing under "left unpriced". Blank stays blank.

**The preview.** `price_sheet_job` adds `"unreadable": [{"line", "reason"}]` to the payload; `PriceSheetPreviewOut` gains `unreadable: list[dict] = []` (appended); `api.js`'s `getPriceSheetPreview` maps it (one appended line — the store is not in this stream's file list, and the commit says so). The modal shows a fourth group, "N row(s) couldn't be read", each line as "Row 14 — the price isn't a number". An item whose row was unreadable still appears under "left unpriced": both are true, and the second is the one the apply step acts on.

**The job's own failure.** A `price_sheet` job that dies for any other reason — storage, a workbook that opens and then blows up, the 60 s timeout — lands `PRICE_SHEET_FAILED`: "The price sheet couldn't be read. Start from Download price request and upload the filled file." Appended to `api/app/jobs/copy.py`; one case added to `queue.terminal_copy` alongside the sheet, classify, and render cases. The modal already renders `error` on a failed job.

**Tests.** Parser (`test_market_price_sheet.py`): NaN, text, missing name, generic exception, all-unreadable → refused, `price_in_range(NaN)` false. Job (`test_worker_price_sheet.py`): the `unreadable` group on the payload; a body that raises → `failed` with `PRICE_SHEET_FAILED`. Modal (`PriceSheetImport.test.jsx`): the fourth group renders line and reason; the refusal copy renders.

## Not in this stream

No change to what the apply step accepts; no change to matching; no migration; no new status word. The workstream's "one estimator-facing line on the project" for a dead source is the existing `failed` row warning, not a project-level banner — a banner would be a second place the same outcome is described.
