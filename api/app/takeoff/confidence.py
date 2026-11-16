"""How much an estimator should trust one line, 1 to 10.

docs/specs/estimate-without-asking.md. **It is a sum of named reasons,
never an opaque score.** Asked "why is this a 4", the product has a
sentence, and that sentence is what this module returns alongside the
number. `ROADMAP.md` invariant 7 bans a confidence figure reaching the
interface and `product-spec.md` §3 bans an *unexplained* confidence
percentage; the estimator's decision was to render an explained 1-10
meter as one sort key, which is why both documents were amended in the
same change rather than quietly worked around.

Two things this is not:

- **Not a probability about the bid.** Nothing here may be multiplied
  by a total. It names what to check, and the copy below is written so
  that a reason never reads as a likelihood -- no percentages, ever.
- **Not a model's self-report.** Every input is a fact about *which
  method produced the number*: counted or guessed, matched to a legend
  or named from context, measured against a confirmed scale or not.
  Those facts are the same for every project and are checkable.

Pure functions over one table, no database, in the shape of
`app.estimate.basis` and `app.schedule.stages`. Shaped so it could later
become a firm-editable table like `app.schedule.defaults` without
restructuring -- it is not firm-editable in this slice.

**THE STARTING NUMBERS ARE EXPECTED TO MOVE.** They are a deliberately
single editable table, set from the spec's own ordering and not yet
calibrated against a real bid set. Changing a row here changes every
line scored by that method, which is the point: tuning belongs in one
place a person can read, never in a branch somewhere in the engine.
"""
from __future__ import annotations

from collections.abc import Sequence

# The top and bottom of the meter. 10 is reserved: see APPROVED_REASON.
FLOOR = 1
CEILING = 10
# Nothing unapproved reaches 10. The top of the scale means "a person
# checked this", which keeps approval worth doing and makes 9 read
# unambiguously as "very likely right, nobody has looked yet".
UNAPPROVED_CEILING = 9

# Where the quantity came from, and what that method is worth. Ordered
# by the same reliability the basis spreads in `app.estimate.basis` are
# ordered by, because the budget range is computed from those spreads
# and a 9 printed beside a +/-25% band would be two parts of the product
# disagreeing about one fact (spec invariant 2; asserted by
# test_base_scores_follow_the_basis_spreads).
BASE_SCORES: dict[str, int] = {
    # Counted off the drawing and matched to a legend row or a schedule
    # line. Both halves known: how many, and what they are.
    "counted_matched": 9,
    # Counted off the drawing, named with high confidence but not from a
    # legend row that defines the tag.
    "counted_high": 8,
    # Read off a schedule stating the quantity. Not built -- slice 4.
    "schedule_read": 8,
    # Measured off the drawing against a scale somebody confirmed.
    "measured_confirmed": 7,
    # Counted, named with medium or low confidence.
    "counted_uncertain": 6,
    # Counted but never identified. The count is as good as any counted
    # line's; the cost is a class average. One number has to carry both
    # and the lower of the two is the honest one.
    "counted_unidentified": 5,
    # The firm's own per-device rule -- their history, not an industry
    # range (`basis.firm_default`, `generate_takeoff.FEET_PER_DEVICE`).
    "firm_rule": 5,
    # Measured off a sheet whose scale is absent or ambiguous. The
    # length rests on a choice nobody made.
    "measured_unconfirmed": 4,
    # Typical for this kind of job, from this project's own sibling
    # sheets. Relative to what was counted here, never a constant.
    "class_average_sibling": 3,
    # Typical for this kind of job, for a system never found at all.
    # The weakest rung the product is willing to produce a number from.
    "class_average_system": 2,
}

# Each applied by name, so the reason list says which ones fired.
ADJUSTMENTS: dict[str, int] = {
    # A schedule count agrees with the placements Counting found.
    "corroborated": +1,
    # They disagree -- the existing `schedule_conflict` warning.
    "sources_disagree": -1,
    # The page read or rendered only partly, so the count is over an
    # incomplete picture of the sheet.
    "partial_page": -1,
    # The symbol is not defined by any legend on the set.
    "not_in_legend": -1,
}

# One estimator-facing sentence per reason. Plain construction language,
# sentence case, no model names, no percentages -- the same register the
# warning and assumption copy uses, for the same reason: the estimator's
# question is "what do I check", never "how did the software decide".
BASE_REASONS: dict[str, str] = {
    "counted_matched": "Counted off the drawing and matched to the legend or a schedule",
    "counted_high": "Counted off the drawing, named without a legend match",
    "schedule_read": "Read off a schedule that states the quantity",
    "measured_confirmed": "Measured against a confirmed scale",
    "counted_uncertain": "Counted off the drawing, name uncertain",
    "counted_unidentified": "Counted off the drawing, but nothing named what these are",
    "firm_rule": "Derived from your firm's own per-device rule",
    "measured_unconfirmed": "Measured on a sheet with no confirmed scale",
    "class_average_sibling": "Typical for the other sheets on this job",
    "class_average_system": "Typical for a job of this kind — nothing was found on the drawings",
}

ADJUSTMENT_REASONS: dict[str, str] = {
    "corroborated": "A schedule count agrees with what was counted",
    "sources_disagree": "The plan and a schedule disagree",
    "partial_page": "The page read only partly",
    "not_in_legend": "The symbol is not in the legend",
}

# Why a line is a 10, and the only way to be one.
APPROVED_REASON = "Approved by an estimator"


def score(
    method: str,
    adjustments: Sequence[str] = (),
    *,
    approved: bool = False,
) -> tuple[int, list[str]]:
    """The score for one line, and the reasons that produced it.

    `method` is how the quantity was obtained -- a key of `BASE_SCORES`.
    `adjustments` are facts about this particular line, each a key of
    `ADJUSTMENTS`. Both are looked up rather than defaulted: an
    unrecognised key raises, because a misspelled reason that scored
    silently would be a reason the product believes it applied and did
    not.

    An approved line is 10 whatever its method was. The method's own
    reason is still reported beside it -- how the number was obtained
    stays true after a person signs off on it, and an estimator looking
    at an approved guess should still be able to see it was a guess.
    """
    value = BASE_SCORES[method]
    reasons = [BASE_REASONS[method]]

    for name in adjustments:
        value += ADJUSTMENTS[name]
        reasons.append(ADJUSTMENT_REASONS[name])

    value = max(FLOOR, min(UNAPPROVED_CEILING, value))

    if approved:
        return CEILING, [APPROVED_REASON, *reasons]
    return value, reasons
