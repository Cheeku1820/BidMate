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


def test_row_from_spec_uses_the_models_own_reasoning_but_synthesizes_found_and_where():
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5,
            "warning": {"title": "Fixture type needs confirmation",
                        "found": "Type F2 appears 8 times across the document.",  # what the model saw -- document-wide, must be discarded
                        "why": "F2's exact fixture and price depend on which schedule entry it matches.",
                        "fix": "Check the luminaire schedule for a type F2 entry, or confirm it against the legend.",
                        "where": "E9.9"}}  # a sheet the model guessed -- must also be discarded
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["warning"]["why"] == "F2's exact fixture and price depend on which schedule entry it matches."
    assert row["warning"]["fix"] == "Check the luminaire schedule for a type F2 entry, or confirm it against the legend."
    # found/where are always this cluster's own real data (tag F2, count 3, sheet "?" since sheets=[] in this test), never the model's:
    assert "Type F2 appears 3 time(s) on" in row["warning"]["found"]
    assert "E9.9" not in row["warning"]["where"]
    assert row["warning"]["reason"] == "legend"


def test_row_from_spec_uses_a_three_field_model_warning():
    """The prompt now asks for title/why/fix only, so this is the shape a
    well-behaved model actually returns -- it must be trusted, not treated
    as incomplete and swapped for the deterministic template."""
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5,
            "warning": {"title": "Fixture type needs confirmation",
                        "why": "F2's exact fixture and price depend on which schedule entry it matches.",
                        "fix": "Check the luminaire schedule for a type F2 entry."}}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["warning"]["why"] == "F2's exact fixture and price depend on which schedule entry it matches."
    assert row["warning"]["fix"] == "Check the luminaire schedule for a type F2 entry."
    assert "Type F2 appears 3 time(s) on" in row["warning"]["found"]
    assert row["warning"]["where"]


def test_row_from_spec_falls_back_when_the_model_omits_a_warning():
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["warning"] is not None
    assert "Type F2 appears 3 time(s) on" in row["warning"]["found"]
    assert row["warning"]["fix"] == "Confirm the item type against the schedule, then approve."


def test_row_from_spec_falls_back_when_the_models_warning_is_missing_a_field():
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5,
            "warning": {"title": "x", "found": "y", "why": "z", "fix": "", "where": "E2.1"}}
    row = estimate_mod._row_from_spec(spec, _FakeCluster(), [], 78.0, 1.0)
    assert row["warning"]["fix"] == "Confirm the item type against the schedule, then approve."
