"""Task 1 of docs/plans/estimate-without-asking.md -- the 1-10 scale.

Its defining property, and the reason it is allowed to render at all
where `ROADMAP.md` invariant 7 bans a confidence number: it is a sum of
named reasons, never an opaque score. Asked "why is this a 4", the
product has a sentence. The spec's own wording bans *unexplained*
confidence; this is the explanation.
"""
import pytest

from app.takeoff.confidence import ADJUSTMENTS, BASE_SCORES, score


def test_a_counted_line_matched_to_a_schedule_scores_nine():
    assert score("counted_matched")[0] == 9


def test_a_counted_but_unidentified_line_scores_five():
    """Quantity as good as any counted line, cost a class average. One
    number carries both, so the lower is the honest one."""
    assert score("counted_unidentified")[0] == 5


def test_a_class_average_for_a_whole_missing_system_scores_two():
    assert score("class_average_system")[0] == 2


def test_corroboration_raises_and_disagreement_lowers():
    assert score("counted_high", ["corroborated"])[0] == 9
    assert score("counted_high", ["sources_disagree"])[0] == 7


def test_nothing_unapproved_reaches_ten():
    assert score("counted_matched", ["corroborated", "corroborated"])[0] == 9


def test_an_approved_line_is_ten_whatever_it_was():
    assert score("class_average_system", approved=True)[0] == 10


def test_the_floor_is_one():
    assert score("class_average_system",
                 ["sources_disagree", "partial_page", "not_in_legend"])[0] == 1


def test_every_score_names_its_reasons():
    _, reasons = score("measured_unconfirmed", ["not_in_legend"])
    assert any("scale" in r.lower() for r in reasons)
    assert any("legend" in r.lower() for r in reasons)


def test_an_approved_line_says_that_is_why_it_is_ten():
    _, reasons = score("class_average_system", approved=True)
    assert any("approved" in r.lower() for r in reasons)


def test_an_unknown_method_is_refused():
    with pytest.raises(KeyError):
        score("vibes")


def test_an_unknown_adjustment_is_refused():
    """A typo'd adjustment that scored silently would be a reason the
    product thinks it applied and did not."""
    with pytest.raises(KeyError):
        score("counted_high", ["probably_fine"])


def test_no_reason_mentions_a_percentage():
    """Anti-goal: a figure an estimator can multiply by the total. The
    scale is a 1-10 meter and the copy must never let it read as a
    probability about the bid."""
    for method in BASE_SCORES:
        _, reasons = score(method, list(ADJUSTMENTS))
        assert not any("%" in r or "percent" in r.lower() for r in reasons)


def test_base_scores_follow_the_basis_spreads():
    """Spec invariant 2: a 9 beside a +/-25% band would be two parts of
    the product disagreeing about one fact."""
    from app.estimate.basis import BASIS
    assert BASE_SCORES["firm_rule"] > BASE_SCORES["class_average_sibling"]
    assert BASIS["rule_of_thumb"].spread >= BASIS["class_average"].spread
