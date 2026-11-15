"""The budget range: how wide the number is, and why.

docs/specs/rom-estimate.md. A ROM that prints one number implies a
precision it does not have. A ROM that prints a range has to be able to
say where the range came from, or the range is decoration.

**Linear, not root-sum-square.** Combining spreads in quadrature is the
statistically defensible move if the errors are independent -- and it
produces a narrower range, which is the attractive part and also the
problem. These errors are not independent: a feet-per-device rule that
runs long runs long on every circuit, and a class-average price that is
low is low across the whole switchgear package. Treating them as
independent would narrow the range on an assumption nobody checked.

The second reason is the one that decides it. An estimator standing in
front of a GC has to be able to explain the range in one sentence:
"$180,000 of this is derived rather than counted, and derived numbers on
this kind of work come in within about a quarter either way." Linear
addition is that sentence. Root-sum-square is not a sentence anybody
says out loud, and a number an estimator cannot explain is a number they
should not hand over.

Pure; no database access. Nothing here is stored -- the range is
recomputed from the assumptions in hand every time the document is read,
so an override that changes an assumption changes the range in the same
breath.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.errors import DomainError
from app.estimate.basis import BASIS

_WHOLE_DOLLAR = Decimal("1")


@dataclass(frozen=True)
class Exposure:
    """Dollars in the estimate that rest on one basis.

    Not a count of assumptions -- a count would weigh a $200 ceiling-drop
    assumption the same as a $48,900 switchboard price, and the range
    would then move when a trivial line was added.
    """

    basis: str
    dollars: Decimal


@dataclass(frozen=True)
class RangeResult:
    low: Decimal
    high: Decimal
    spread_dollars: Decimal


def budget_range(direct_cost: Decimal, exposures: list[Exposure]) -> RangeResult:
    """Sum each exposure's dollars against its basis's stated spread.

    An unknown basis is refused rather than skipped: skipping would
    narrow the range, and a range that is too narrow because of an
    internal error is the one failure here that reads as more confidence
    rather than less.

    `low` is clamped at zero -- a negative budget is not a statement
    about anything. `high` is not clamped: it is the arithmetic, and
    rounding it down to look reasonable would be inventing precision in
    the direction that costs the estimator money.
    """
    spread = Decimal("0")
    for exposure in exposures:
        spec = BASIS.get(exposure.basis)
        if spec is None:
            raise DomainError(
                "invalid_assumption",
                f"An assumption carries an unrecognized basis {exposure.basis!r}, so the budget "
                "range cannot be stated. Recognized bases are: " + ", ".join(sorted(BASIS)) + ".",
                status=422,
            )
        if exposure.dollars < 0:
            raise DomainError(
                "invalid_assumption",
                f"An assumption reports negative exposure ({exposure.dollars}) on basis "
                f"{exposure.basis!r}. Exposure is the dollars resting on a basis and cannot be negative.",
                status=422,
            )
        spread += exposure.dollars * spec.spread

    center = Decimal(direct_cost)
    # Rounded outward, never to nearest: a range is a claim that the
    # number lies inside it, and `budget_range(140.49, [])` rounding to
    # [140, 140] put the point estimate outside its own range. Floor the
    # low, ceil the high, and the claim stays true at any spread --
    # including zero, where the range becomes [140, 141] rather than a
    # false point. The spread itself is reported at nearest, because it
    # is a width rather than a bound.
    low = (center - spread).to_integral_value(rounding=ROUND_FLOOR)
    high = (center + spread).to_integral_value(rounding=ROUND_CEILING)
    return RangeResult(
        low=max(Decimal("0"), low),
        high=high,
        spread_dollars=spread.quantize(_WHOLE_DOLLAR, rounding=ROUND_HALF_UP),
    )
