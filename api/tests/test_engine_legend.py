"""Documents agent: turning a legend/abbreviations text dump into typed
rows. Spec 2.1 calls this the highest-leverage thing Documents produces --
Classification matches against these rows instead of re-reading a blob."""

from app.engine.legend import parse_legend


def test_parses_key_then_expansion_pairs():
    text = "ACS\nACCESS CONTROL SYSTEM\nAFF\nABOVE FINISHED FLOOR\nCKT\nCIRCUIT"
    rows = parse_legend(text)
    got = {r.symbol: r.description for r in rows}
    assert got["ACS"] == "ACCESS CONTROL SYSTEM"
    assert got["AFF"] == "ABOVE FINISHED FLOOR"
    assert got["CKT"] == "CIRCUIT"


def test_marks_every_parsed_row_as_an_abbreviation():
    rows = parse_legend("WP\nWEATHERPROOF")
    assert rows[0].kind == "abbreviation"


def test_ignores_a_key_with_no_expansion():
    # A trailing key with nothing after it is not a pair.
    rows = parse_legend("ACS\nACCESS CONTROL SYSTEM\nXYZ")
    assert [r.symbol for r in rows] == ["ACS"]


def test_ignores_two_expansions_in_a_row():
    # Prose lines following each other are not key/value pairs.
    rows = parse_legend("ACCESS CONTROL SYSTEM\nABOVE FINISHED FLOOR")
    assert rows == []


def test_keeps_the_first_definition_when_a_key_repeats():
    rows = parse_legend("EL\nEMERGENCY LIGHT\nEL\nELEVATION")
    assert [(r.symbol, r.description) for r in rows] == [("EL", "EMERGENCY LIGHT")]


def test_empty_text_yields_no_rows():
    assert parse_legend("") == []
    assert parse_legend("   \n\n  ") == []


import os
import pytest

BID = ("/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/"
       "21_1001_unalaska_library_cd_biddrawings.pdf")


@pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")
def test_real_set_legend_sheet_yields_known_abbreviations():
    """The Unalaska set's E0.1 carries an abbreviations block. These three
    are read directly off that sheet and are what the classifier used to
    explain WP as a modifier rather than a device."""
    from app.engine import documents

    sheets = documents.detect_sheets(BID)
    rows = {r.symbol: r.description for s in sheets for r in s.legend}
    assert rows.get("AFF") == "ABOVE FINISHED FLOOR"
    assert rows.get("EL") == "EMERGENCY LIGHT"
    assert len(rows) > 30, f"expected a substantial abbreviations block, got {len(rows)}"
