"""Task 3 of docs/plans/rom-estimate.md -- the budget range as a
dollar-weighted linear spread over named basis classes. Pure; no
database.
"""
from decimal import Decimal

import pytest

from app.errors import DomainError
from app.estimate.range import Exposure, budget_range


def test_zero_spread_bases_contribute_nothing():
    r = budget_range(Decimal("1000"), [Exposure("supplier_quote", Decimal("1000"))])
    assert (r.low, r.high) == (Decimal("1000"), Decimal("1000"))


def test_single_exposure_applies_its_spread():
    r = budget_range(Decimal("1000"), [Exposure("rule_of_thumb", Decimal("400"))])
    assert r.spread_dollars == Decimal("100")  # 400 * 0.25
    assert (r.low, r.high) == (Decimal("900"), Decimal("1100"))


def test_exposures_combine_linearly_not_in_quadrature():
    r = budget_range(Decimal("1000"), [
        Exposure("rule_of_thumb", Decimal("400")),   # 100
        Exposure("class_average", Decimal("200")),   # 40
    ])
    assert r.spread_dollars == Decimal("140")


def test_low_never_goes_below_zero():
    r = budget_range(Decimal("100"), [Exposure("rule_of_thumb", Decimal("1000"))])
    assert r.low == Decimal("0")
    # The high side is not clamped -- it is the honest arithmetic.
    assert r.high == Decimal("350")


def test_no_exposures_gives_a_point_range():
    # Review Focus 1 -- a project with nothing in it must not divide by zero
    r = budget_range(Decimal("0"), [])
    assert (r.low, r.high, r.spread_dollars) == (Decimal("0"), Decimal("0"), Decimal("0"))


def test_a_fully_counted_estimate_gives_a_point_range():
    """Nothing assumed means no spread: the range collapses onto the
    number rather than acquiring a decorative width."""
    r = budget_range(Decimal("50000"), [])
    assert (r.low, r.high) == (Decimal("50000"), Decimal("50000"))


def test_an_unknown_basis_is_refused_rather_than_silently_ignored():
    """Dropping it would quietly narrow the range, which is the one
    direction an error here must never go."""
    with pytest.raises(DomainError):
        budget_range(Decimal("1000"), [Exposure("vibes", Decimal("400"))])


def test_negative_exposure_is_refused():
    with pytest.raises(DomainError):
        budget_range(Decimal("1000"), [Exposure("rule_of_thumb", Decimal("-400"))])


def test_results_are_rounded_to_whole_dollars():
    r = budget_range(Decimal("1000.00"), [Exposure("market_estimate", Decimal("333.33"))])
    assert r.spread_dollars == Decimal("50")   # 333.33 * 0.15 = 49.9995
    assert (r.low, r.high) == (Decimal("950"), Decimal("1050"))


def test_exposure_dollars_may_exceed_the_total_without_breaking():
    """Material and labor exposures both reference the same items, so a
    generator can legitimately hand in more exposure than direct cost.
    The arithmetic must stay defined."""
    r = budget_range(Decimal("100"), [
        Exposure("firm_default", Decimal("100")),
        Exposure("market_estimate", Decimal("100")),
    ])
    assert r.spread_dollars == Decimal("25")
    assert (r.low, r.high) == (Decimal("75"), Decimal("125"))
