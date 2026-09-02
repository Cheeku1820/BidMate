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
