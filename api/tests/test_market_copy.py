"""Every market outcome has four-field warning copy that names no
vendor, no model, and no number (CLAUDE.md, product language)."""
import pytest

from decimal import Decimal

from app.market.copy import OUTCOMES, warning_for, wide_range_warning

BANNED = ("1build", "google", "serpapi", "confidence", "model", "ai ", "llm")


@pytest.mark.parametrize("outcome", [o for o in OUTCOMES if o != "priced"])
def test_each_outcome_has_four_fields_in_plain_words(outcome):
    w = warning_for(outcome, query="20A duplex receptacle", sheet_number="E2.1", description="Duplex receptacle, 20A")
    for key in ("title", "found", "why", "fix", "where"):
        assert w[key].strip(), key
    text = " ".join(w.values()).lower()
    assert not any(b in text for b in BANNED), text
    assert w["title"][0].isupper() and "!" not in text


def test_priced_has_no_warning():
    assert warning_for("priced", query="q", sheet_number="E2.1", description="d") is None


def test_wide_range_warning_has_four_fields_in_plain_words():
    """The one Needs attention a market estimate can carry: the sellers
    disagree by more than half. It names the range, the place, and the
    date -- never a seller, a vendor, or a number's provenance."""
    w = wide_range_warning(low=Decimal("156.75"), high=Decimal("303.33"), location_label="Austin, TX", fetched_note="Sep 18")
    assert set(w) == {"title", "found", "why", "fix", "where"}
    for key in w:
        assert w[key].strip(), key
    assert w["title"] == "Wide price range"
    assert w["found"] == "Sellers quoted between $156.75 and $303.33."
    assert w["where"] == "Austin, TX, Sep 18"
    text = " ".join(w.values()).lower()
    assert not any(b in text for b in BANNED), text
    assert w["title"][0].isupper() and "!" not in text


def test_wide_range_warning_where_tolerates_a_missing_date():
    w = wide_range_warning(low=Decimal("1"), high=Decimal("2"), location_label="ZIP 78701", fetched_note="")
    assert w["where"] == "ZIP 78701"
