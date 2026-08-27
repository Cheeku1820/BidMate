"""Content-based document classification -- the fallback for a file whose
name didn't say what it is. Runs without the DB harness (pytest
--noconftest locally)."""

from app.engine.documents import classify_content


def test_recognizes_a_spec_section():
    assert classify_content("SECTION 26 05 19 - LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS") == "Specifications"
    assert classify_content("PROJECT MANUAL\nVolume 2 of 2") == "Specifications"


def test_recognizes_an_addendum():
    assert classify_content("ADDENDUM NO. 2\nThe following changes...") == "Addendum"


def test_recognizes_drawings_from_a_title_block():
    assert classify_content("LEVEL 1 LIGHTING PLAN\nSCALE: 1/8\" = 1'-0\"\nSHEET E2.1") == "Drawings"


def test_recognizes_other():
    assert classify_content("GEOTECHNICAL INVESTIGATION REPORT") == "Other"


def test_returns_none_when_inconclusive():
    assert classify_content("Cover page. Table of contents. Index of drawings.") is None
    assert classify_content("") is None
