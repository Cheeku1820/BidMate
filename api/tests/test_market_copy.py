"""Every market outcome has four-field warning copy that names no
vendor, no model, and no number (CLAUDE.md, product language)."""
import pytest

from app.market.copy import OUTCOMES, warning_for

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
