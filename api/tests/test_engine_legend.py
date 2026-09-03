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


def test_rejects_an_expansion_that_is_not_words():
    """The parser pairs a key-shaped line with the line after it, which on a
    real sheet matches coincidental adjacency -- a detail bubble above its
    number, a grid letter above a room name. Requiring a run of letters is
    what separates CIRCUIT from '1'. Without this, J parsed as an
    abbreviation meaning '1' and outranked the junction-box catalog entry."""
    assert parse_legend("J\n1") == []
    assert parse_legend("A\n3.") == []
    assert parse_legend("F\nM-20,22,24") == []


def test_still_accepts_a_single_word_expansion():
    rows = parse_legend("CKT\nCIRCUIT")
    assert [(r.symbol, r.description) for r in rows] == [("CKT", "CIRCUIT")]


import os
import pytest

BID = ("/Users/nikhit/Documents/Sumedh-Nikhit Start-Up/bid_example/"
       "21_1001_unalaska_library_cd_biddrawings.pdf")


@pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")
def test_real_set_legend_sheet_yields_known_abbreviations():
    """The Unalaska set's E0.1 carries an abbreviations block. These three
    are read directly off that sheet. WP is one of the rows here -- under
    the current classification precedence WP is priced as a device (a
    GFCI receptacle) with an ambiguity flag, not demoted to a modifier,
    since it is also a known catalog tag."""
    from app.engine import documents

    sheets = documents.detect_sheets(BID)
    rows = {r.symbol: r.description for s in sheets for r in s.legend}
    assert rows.get("AFF") == "ABOVE FINISHED FLOOR"
    assert rows.get("EL") == "EMERGENCY LIGHT"
    assert len(rows) > 30, f"expected a substantial abbreviations block, got {len(rows)}"
