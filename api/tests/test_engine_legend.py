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


def test_rejects_a_sentence_terminal_word_as_a_key():
    """A numbered general-notes block ends lines with a period, and the old
    key pattern accepted the trailing dot -- so BOX., NOTED., OWNER. and
    REUSE. parsed as keys off this set, each paired with the note line
    following it. The dot is out of the character class entirely now, which
    costs the real abbreviations C. and C.O.: that is the trade, because
    admitting a trailing dot admits every sentence-final word."""
    assert parse_legend("BOX.\nSHALL BE FLUSH MOUNTED") == []
    assert parse_legend("NOTED.\nEXCEPT WHERE OTHERWISE SHOWN") == []
    assert parse_legend("C.\nCONDUIT") == [], "the known cost of dropping the dot"


def test_rejects_a_long_word_as_a_key():
    """APPROX, BUTTON, FEEDER, LEGEND, PANEL and two dozen more parsed as
    keys off prose. A key is four characters at most."""
    assert parse_legend("PANEL\nLINE WORK CONVENTION") == []
    assert parse_legend("APPROX\nAPPROXIMATE LOCATION") == []
    assert [r.symbol for r in parse_legend("CKT\nCIRCUIT")] == ["CKT"], "four or fewer still parses"


def test_tightening_the_key_does_not_widen_what_counts_as_an_expansion():
    """The two questions are separate, and sharing one pattern for both is
    a trap: every line a tighter key stops recognising becomes eligible as
    an expansion, so the parser invents new pairs faster than the tighter
    key removes old ones. Measured on the real set, sharing the pattern
    gave 91 keys including five new mis-pairings; keeping the rejection
    loose gives 86 and none.

    S -> J-BOX is the case that matters: S is the switch tag, so this one
    mis-pairing alone would flag every switch on the set for review."""
    assert parse_legend("S\nJ-BOX") == []
    assert parse_legend("J2\nPMP-3") == []
    assert parse_legend("M\nM-23") == []


def test_a_row_records_which_page_it_was_read_from():
    """parse_legend is handed text, not a page, so it cannot know. The
    default is an explicit -1 rather than 0, which would be a wrong sheet
    id stated as a real one."""
    rows = parse_legend("CKT\nCIRCUIT")
    assert rows[0].page_index == -1


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


@pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")
def test_every_real_row_names_the_sheet_it_came_from():
    """A definition read off E0.1 and a device counted on E7.1 are two
    different sheets, and a warning that sends the estimator to the wrong
    one costs more than saying nothing. documents.py stamps each row, so
    nothing on a real set should still carry the -1 default."""
    from app.engine import documents

    sheets = documents.detect_sheets(BID)
    rows = [r for s in sheets for r in s.legend]
    assert rows, "no legend rows parsed -- this test would be vacuous"
    assert all(r.page_index >= 0 for r in rows)
    by_page = {s.page_index: s.number for s in sheets}
    wp = [r for s in sheets for r in s.legend if r.symbol == "WP"]
    assert wp and by_page[wp[0].page_index] == "E0.1", \
        "WP's real definition is on the legend sheet E0.1"
