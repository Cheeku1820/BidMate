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


def test_an_abbreviation_tag_is_classified_as_a_modifier():
    """CKT is in the abbreviations block as CIRCUIT, and CKT is not a known
    device tag or fixture-type letter -- it is abbreviation-only, so the
    modifier rule is the only reading that applies and should fire. (WP was
    the original example here, but WP is also in TAG_TO_CATALOG as a GFCI
    receptacle; curated device knowledge now outranks a parsed abbreviation
    for a tag like that -- see test_a_device_tag_that_is_also_an_abbreviation_is_priced_and_flagged
    below -- so WP no longer exercises the modifier-only path.)"""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    sheet = DetectedSheet(
        page_index=0, number="E7.1", title="Power", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="CKT", description="CIRCUIT", kind="abbreviation")],
    )
    cluster = DeviceCluster(tag="CKT", sheet_page_index=0, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [sheet])

    assert items[0].status == "attention"
    assert items[0].warning is not None
    assert "double" in items[0].warning["fix"].lower()
    # The warning names the legend; it never quotes it. The abbreviations
    # block is a line-pair heuristic over messy sheet text, so the parsed
    # expansion is not evidence the estimator can be sent to look for.
    assert "CKT" in items[0].warning["found"]
    for field in ("found", "why", "fix", "where"):
        assert "circuit" not in items[0].warning[field].lower(), \
            f"{field} quotes the parsed legend description"
    # ...and the name comes from the taxonomy, not from the sheet text.
    assert items[0].name == "Unclassified symbol (CKT)"


def test_a_device_tag_that_is_also_an_abbreviation_is_priced_and_flagged():
    """WP resolves to a real catalog device (GFCI receptacle) via
    TAG_TO_CATALOG, and the same sheet's legend also lists WP as an
    abbreviation. Curated device knowledge wins the classification and the
    price -- the item is not silently zeroed to a modifier -- but the
    collision still surfaces as an attention warning so the estimator can
    spot check it."""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    sheet = DetectedSheet(
        page_index=0, number="E7.1", title="Power", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="WP", description="WEATHERPROOF", kind="abbreviation")],
    )
    cluster = DeviceCluster(tag="WP", sheet_page_index=0, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [sheet])

    assert items[0].catalog_id == "receptacle_gfci"
    assert items[0].status == "attention"
    assert items[0].warning is not None
    assert "WP" in items[0].warning["found"]
    for field in ("found", "why", "fix", "where"):
        assert "weatherproof" not in items[0].warning[field].lower(), \
            f"{field} quotes the parsed legend description"


def test_the_first_sheets_legend_definition_wins_across_the_set():
    """parse_legend documents first-definition-wins within one sheet (a
    legend sheet repeats headers, and a later accidental match must not
    overwrite a real definition). classify() must honor the same policy
    across sheets -- a dict comprehension over all sheets' legends is
    last-wins, which on the real set let a mis-paired plan callout on a
    later sheet ('WP' -> 'SEE ENLARGED') silently overwrite the real
    legend-sheet definition ('WP' -> 'WEATHERPROOF')."""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    legend_sheet = DetectedSheet(
        page_index=0, number="E0.1", title="Legend", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="WP", description="WEATHERPROOF", kind="abbreviation")],
    )
    later_sheet = DetectedSheet(
        page_index=1, number="E5.1", title="Power plan", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="WP", description="SEE ENLARGED", kind="abbreviation")],
    )
    cluster = DeviceCluster(tag="WP", sheet_page_index=1, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [legend_sheet, later_sheet])

    # No parsed description reaches estimator copy at all now, so neither
    # spelling can be asserted here. This case pins that the multi-sheet
    # path stays leak-free; the sharper pin on *which* definition wins is
    # test_the_first_definition_decides_whether_the_legend_corroborates.
    for field in ("found", "why", "fix", "where"):
        text = items[0].warning[field].lower()
        assert "weatherproof" not in text and "see enlarged" not in text, \
            f"{field} quotes a parsed legend description"


def test_the_first_definition_decides_whether_the_legend_corroborates():
    """The sharper first-wins pin. Corroboration reads the description, so
    which definition won is observable again in the item's status: the
    legend sheet's R -> RECEPTACLE agrees with the catalog and leaves the
    item ready, while a later sheet's mis-paired R -> ROOM FINISH SCHEDULE
    does not. Under last-wins this item would be attention."""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    legend_sheet = DetectedSheet(
        page_index=0, number="E0.1", title="Legend", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="R", description="RECEPTACLE", kind="abbreviation")],
    )
    later_sheet = DetectedSheet(
        page_index=1, number="E5.1", title="Power plan", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="R", description="ROOM FINISH SCHEDULE", kind="abbreviation")],
    )
    cluster = DeviceCluster(tag="R", sheet_page_index=1, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [legend_sheet, later_sheet])

    assert items[0].catalog_id == "receptacle_20a"
    assert items[0].status == "ready"
    assert items[0].warning is None

    # ...and reversed, the conflicting definition wins and does warn.
    flipped = classification.classify([cluster], [later_sheet, legend_sheet])
    assert flipped[0].status == "attention"


def test_a_corroborating_legend_leaves_a_device_ready():
    """WP -> WEATHERPROOF, R -> RECEPTACLE and S -> SWITCH are well-drafted
    legends confirming what the catalog already says. Flagging them makes
    the review noisier the better the drafting is."""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    def _classify(tag, description):
        sheet = DetectedSheet(
            page_index=0, number="E0.1", title="Legend", discipline="Electrical",
            scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
            legend=[LegendEntry(symbol=tag, description=description, kind="abbreviation")],
        )
        cluster = DeviceCluster(tag=tag, sheet_page_index=0, placements=[Placement(1, 1)] * 3)
        return classification.classify([cluster], [sheet])[0]

    for tag, description in (("R", "RECEPTACLE"), ("S", "SWITCH")):
        item = _classify(tag, description)
        assert item.status == "ready", f"{tag} -> {description} is good drafting, not a conflict"
        assert item.warning is None


def test_a_conflicting_legend_still_warns():
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    sheet = DetectedSheet(
        page_index=0, number="E0.1", title="Legend", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="R", description="ROOM FINISH SCHEDULE", kind="abbreviation")],
    )
    cluster = DeviceCluster(tag="R", sheet_page_index=0, placements=[Placement(1, 1)] * 3)
    item = classification.classify([cluster], [sheet])[0]
    assert item.status == "attention"
    assert item.warning is not None
    assert item.warning["title"] == "Tag also appears in the legend"


def test_weatherproof_does_not_corroborate_a_gfci_receptacle():
    """Pins a known limit rather than a desired behaviour, so the next
    person meets it deliberately.

    Finding 6 was written around WP -> WEATHERPROOF as its example of good
    drafting that should stay ready. The word-overlap rule does not deliver
    that: WP's catalog name is "20A GFCI receptacle", whose significant
    words are "gfci" and "receptacle", and neither appears in
    "weatherproof". That a weatherproof receptacle is a GFCI one lives in
    TAG_TO_CATALOG and in the NEC, not in either string.

    So WP keeps its warning on the real set. If a curated list of legend
    spellings per catalog item is ever added, this test is the one to
    revisit -- deliberately, not by accident."""
    from app.engine.classification import _legend_corroborates

    assert not _legend_corroborates("20A GFCI receptacle", "WEATHERPROOF")
    assert _legend_corroborates("20A duplex receptacle", "RECEPTACLE")
    assert _legend_corroborates("Single-pole switch", "SWITCH")


def test_a_known_device_tag_is_unaffected_by_the_legend():
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    sheet = DetectedSheet(
        page_index=0, number="E7.1", title="Power", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="WP", description="WEATHERPROOF", kind="abbreviation")],
    )
    cluster = DeviceCluster(tag="R", sheet_page_index=0, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [sheet])
    assert items[0].status == "ready"
    assert items[0].catalog_id == "receptacle_20a"
