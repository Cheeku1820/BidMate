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


from app.engine import estimate as estimate_mod
from app.engine.contracts import ClassifiedItem, Placement


class _FakeCluster:
    def __init__(self):
        self.count = 3
        self.tag = "F2"
        self.sheet_page_index = 0
        self.placements = [Placement(x=10, y=20)]


def test_row_from_catalog_carries_symbol_and_warning():
    """classification.py already decided both. Dropping them here is why
    an attention item used to reach review with nothing to act on, and
    why the client had to guess a symbol from the item's name."""
    warning = {
        "reason": "legend", "title": "Symbol not in legend",
        "found": "Tag F2 appears 3 times on E2.1 but isn't a recognized device.",
        "why": "An unclassified symbol has no catalog item, so it isn't counted or priced yet.",
        "fix": "Assign a classification, or reject it if it isn't a device.",
        "where": "E2.1.",
    }
    item = ClassifiedItem(
        catalog_id="unknown", name="Unclassified symbol F2", system="Unknown",
        category="Unclassified", unit="ea", symbol="generic", quantity=3,
        sheet_page_index=0, placements=[Placement(x=10, y=20)],
        status="attention", warning=warning, source_tag="F2",
    )
    row = estimate_mod._row_from_catalog(item, _FakeCluster(), [], 78.0, 1.0)
    assert row["symbol"] == "generic"
    assert row["warning"] == warning


def test_row_from_spec_marks_attention_with_a_warning():
    """The LLM path sets status=attention whenever confidence isn't high.
    An attention item with no warning gives the estimator no recovery
    action, so the row builder supplies the four-field shape."""
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["status"] == "attention"
    assert row["warning"] is not None
    for field in ("reason", "title", "found", "why", "fix", "where"):
        assert row["warning"][field], f"warning is missing {field}"


def test_row_from_spec_high_confidence_carries_no_warning():
    spec = {"name": "20A duplex receptacle", "system": "Power", "category": "Devices",
            "unit": "ea", "confidence": "high", "material_cost": 4, "labor_hours": 0.33}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["status"] == "ready"
    assert row["warning"] is None
