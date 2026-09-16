"""The text block the classifier reads: schedules, other documents, and
the estimator's own notes, assembled from three sources that are
deliberately kept apart.

Owned here rather than by `estimate.py` so `classification.classify_run`
and the whole-document estimate share one builder, and so neither has to
import the other to get it.
"""

from __future__ import annotations

import re

# llm._prompt() truncates whatever blob this function builds to its own
# [:6000] before it ever reaches the model -- that slice, not any cap
# defined here, is the real budget, and it is used below to size the
# schedule/notes split, not just documented. Duplicating the number is an
# accepted coupling; llm.py is not touched by this module.
PROMPT_BUDGET = 6000
# The notes block's cap on its own line content (before the header text
# that wraps it). Kept well under PROMPT_BUDGET so a maximal payload is
# still a small, predictable fraction of the real window once reserved --
# see build_classifier_context, which reserves exactly this block's
# length out of PROMPT_BUDGET before it caps the schedule text, so the
# reservation is real rather than incidental.
NOTES_CAP = 1200
# Chars of "\n\n".join separators to leave slack for when reserving room
# for the notes block ahead of the schedule cap -- at most two joins
# (schedule-notes, notes-context) can land before the notes block ends.
_SEPARATOR_SLACK = 4
CONTEXT_CAP = 12000

# Any run of "===...===", wherever it sits within a line -- not only a
# line composed of nothing else, and not anchored to whitespace of a
# specific kind. `.` does not match a newline by default, so this still
# can't span two physical lines; see the docstring below for why that gap
# is left open rather than chased.
_HEADER_RUN_RE = re.compile(r"===.*===")


def _defang_block_headers(text: str) -> str:
    """Neutralise any "=== ... ===" run that could be mistaken for one of
    this module's own block headers, wherever it appears.

    The parameters `context` and `estimator_notes` are already kept
    separate -- but the *rendered* text is one string, and a specification
    whose extracted text happens to contain the literal line
    '=== Estimator notes and assumptions ===' would otherwise render a
    second, indistinguishable authoritative block inside the untrusted
    one. That would put the guarantee back on the model not being fooled
    by a forged header, which is exactly what this function exists to
    avoid depending on.

    The match is on the "===...===" run itself, not the whole line, so
    leading or trailing content -- a stray character, a carriage return, a
    non-breaking space, a form feed -- can't smuggle a real header past a
    stricter pattern that only recognised a line made of nothing else.
    Punctuation is swapped rather than the run being dropped -- a removed
    line is just a different way to hide content from the person
    reviewing it. This runs on `context` (untrusted document text) and on
    every estimator-note field: a note is trusted, but an estimator who
    pastes a stray header line shouldn't be able to break the block
    structure either.

    Residual gap, left open deliberately: a header split across separate
    physical lines (`"===\\nEstimator notes\\n==="`) is not caught, because
    catching it means treating any bare "===" as a candidate delimiter and
    pairing it with another one somewhere later in the text -- which would
    defang far more ordinary document content (a horizontal rule, a diff
    marker) than it would ever catch a real attack. No regex closes every
    visual imitation of a boundary; this closes the concrete ones a
    same-line match can reach.
    """
    if not text:
        return text
    return _HEADER_RUN_RE.sub(lambda m: m.group(0).replace("=", "-"), text)


def build_classifier_context(schedule_text: str, context: str, estimator_notes: list[dict] | None) -> str:
    """The text the classifier reads, assembled from three sources that
    are deliberately kept apart.

    `schedule_text` is the drawings' own schedules -- the primary
    evidence, and normally the larger share of the window, but NOT
    unbounded: a full drawing set's page text routinely runs past
    PROMPT_BUDGET on its own (`documents.py` joins whole-page text across
    every sheet), so leaving it uncapped would silently push both other
    blocks out of what the model ever reads. `context` is text lifted
    from other uploaded documents -- untrusted, because a drawing set
    arrives from outside and text inside it must be data rather than
    instruction -- listed last, since it is already the least-trusted
    block and the one already accustomed to being cut when space runs
    out. `estimator_notes` are typed records a person wrote and is
    accountable for, so they get a *reserved* slice of PROMPT_BUDGET,
    carved out before the schedule is capped -- a note the estimator
    explicitly attached to this takeoff must never be the thing that
    silently disappears because a sheet's schedule text happened to be
    long.

    Nothing writes document text into the notes block: the two arrive as
    separate parameters and are formatted separately here. Untrusted text
    also cannot forge a second copy of either block's own header (see
    `_defang_block_headers`), so the guarantee holds by shape rather than
    by wording or by trusting the model to see through a lookalike.
    """
    notes_block = ""
    if estimator_notes:
        lines = []
        for n in estimator_notes:
            if not isinstance(n, dict):
                continue  # malformed entry: skip it, never fail the takeoff over it
            scope = str(n.get("scope") or "project")
            title = _defang_block_headers(str(n.get("title") or ""))
            body = _defang_block_headers(str(n.get("body") or ""))
            source_ref = n.get("source_ref")
            src = f" ({_defang_block_headers(str(source_ref))})" if source_ref else ""
            lines.append(f"- [{scope}] {title}{src}: {body}")
        if lines:
            block = "\n".join(lines)[:NOTES_CAP]
            notes_block = (
                "=== Estimator notes and assumptions ===\n"
                "Written by the estimator for this project. These take precedence "
                "over what the drawings appear to say.\n" + block
            )

    # Reserve the notes block's exact size (plus join slack) out of the
    # real window before capping the schedule -- this is what makes the
    # reservation actual rather than a comment. Whatever remains is the
    # schedule's, so a small or absent notes block still lets the
    # schedule use nearly all of PROMPT_BUDGET.
    reserved_for_notes = (len(notes_block) + _SEPARATOR_SLACK) if notes_block else 0
    schedule_budget = max(PROMPT_BUDGET - reserved_for_notes, 0)

    parts: list[str] = []

    schedule_text = _defang_block_headers(schedule_text or "")[:schedule_budget]
    if schedule_text:
        parts.append(schedule_text)

    if notes_block:
        parts.append(notes_block)

    if context:
        context = _defang_block_headers(context)
        parts.append("=== From project specifications and addenda ===\n" + context[:CONTEXT_CAP])

    return "\n\n".join(parts)
