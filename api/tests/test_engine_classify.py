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


def test_recognizes_drawings_numbered_across_the_corpus_family():
    """Four of five vector sets in the corpus number their sheets
    E-101, EL101, EP-1 or ED-101, not E2.1; a cover carrying only those
    read as inconclusive."""
    assert classify_content("SHEET INDEX\nE-001 ELECTRICAL LEGEND\nED-101 DEMOLITION PLAN\nE-101 LIGHTING PLAN") == "Drawings"
    assert classify_content("EL101 FIRST FLOOR LIGHTING PLAN\nEP101 FIRST FLOOR POWER PLAN") == "Drawings"


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


def test_a_shape_tag_never_reaches_the_model_path_warning_copy():
    """A cluster found by shape carries `shape:<sig>` as its tag -- a
    processing internal. When the model names it but hedges (attention
    with its own warning, or none), the synthesized `found` says "a
    symbol", never the signature."""
    cluster = _FakeCluster(); cluster.tag = "shape:0a1b2c3d"; cluster.count = 12
    spec = {"name": "Type F luminaire", "system": "Lighting", "category": "Fixtures",
            "unit": "ea", "confidence": "low", "material_cost": 120, "labor_hours": 0.5,
            "warning": {"title": "Fixture type needs confirmation", "why": "Which fixture this is depends on the schedule.",
                        "fix": "Check the luminaire schedule."}}
    for s_ in (spec, {k: v for k, v in spec.items() if k != "warning"}):
        row = estimate_mod._row_from_spec(s_, cluster, [], 78.0, 1.0)
        assert "shape:" not in row["warning"]["found"] and "0a1b2c3d" not in row["warning"]["found"]
        assert row["warning"]["found"].startswith("A symbol appears 12 times on")
    assert estimate_mod._unconfirmed_type_warning("shape:0a1b2c3d", 12, "E2.1")["found"] == \
        "A symbol appears 12 times on E2.1 but its type couldn't be confirmed."


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


def test_a_longer_word_containing_a_catalog_word_does_not_corroborate():
    """The substring version read SWITCHBOARD as agreeing with
    "Single-pole switch", so a legend reusing S for a piece of gear
    suppressed the collision warning entirely -- the estimator was never
    told that some of those S placements are a switchboard rather than a
    switch. Suppression is the dangerous direction for this rule: a
    missing warning is silent, a spurious one is merely noise.

    A trailing plural still corroborates, because a legend row reading
    RECEPTACLES is the good drafting this rule exists to leave alone."""
    from app.engine.classification import _legend_corroborates

    assert not _legend_corroborates("Single-pole switch", "SWITCHBOARD")
    assert _legend_corroborates("Panelboard", "PANELBOARDS AND SWITCHBOARDS")
    assert _legend_corroborates("20A duplex receptacle", "DUPLEX RECEPTACLES")
    assert _legend_corroborates("Single-pole switch", "SWITCHES")


def test_a_legend_warning_names_the_sheet_the_definition_came_from():
    """`where` is contractually which sheet holds the evidence. LegendEntry
    already carries page_index; without using it the warning says "the
    legend sheet" and an estimator on a 14-sheet set has to go hunting.

    Follows the inline DetectedSheet/DeviceCluster construction the
    neighbouring tests in this file use -- there is no `_sheet` helper in
    this module to reuse."""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    legend_sheet = DetectedSheet(
        page_index=0, number="E0.1", title="Legend", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="CKT", description="CIRCUIT", kind="abbreviation", page_index=0)],
    )
    plan_sheet = DetectedSheet(
        page_index=1, number="E2.1", title="Power plan", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[],
    )
    cluster = DeviceCluster(tag="CKT", sheet_page_index=1, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [legend_sheet, plan_sheet])

    assert "E0.1" in items[0].warning["where"]
    assert "E2.1" in items[0].warning["where"]


def test_an_ambiguous_tag_warning_also_names_the_defining_sheet():
    """Same fix, other warning -- _ambiguous_tag_warning fires when a
    TAG_TO_CATALOG tag's legend definition doesn't corroborate the catalog
    reading (WP -> WEATHERPROOF vs. the GFCI receptacle catalog entry),
    and it must name the legend sheet exactly like _modifier_warning does."""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    legend_sheet = DetectedSheet(
        page_index=0, number="E0.1", title="Legend", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="WP", description="WEATHERPROOF", kind="abbreviation", page_index=0)],
    )
    plan_sheet = DetectedSheet(
        page_index=1, number="E7.1", title="Power", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[],
    )
    cluster = DeviceCluster(tag="WP", sheet_page_index=1, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [legend_sheet, plan_sheet])

    assert items[0].status == "attention"
    assert "E0.1" in items[0].warning["where"]
    assert "E7.1" in items[0].warning["where"]


def test_a_legend_warning_falls_back_to_generic_wording_when_the_sheet_is_unknown():
    """A LegendEntry built without page_index defaults to -1 -- the
    documented "unknown" sentinel. Naming no sheet is safe; naming the
    wrong one is not, so this must keep the old generic phrasing rather
    than mislabel a sheet."""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    sheet = DetectedSheet(
        page_index=0, number="E7.1", title="Power", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="CKT", description="CIRCUIT", kind="abbreviation")],
    )
    cluster = DeviceCluster(tag="CKT", sheet_page_index=0, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [sheet])

    assert items[0].warning["where"] == "E7.1 and the legend sheet."


def test_a_legend_warning_names_the_sheet_once_when_the_definition_is_on_the_same_sheet():
    """Cross-sheet naming shouldn't turn same-sheet warnings into
    "E7.1 and E7.1." -- pins the existing single-sheet modifier test's
    output shape, which the widened lookup must not change."""
    from app.engine import classification
    from app.engine.contracts import DetectedSheet, DeviceCluster, LegendEntry, Placement

    sheet = DetectedSheet(
        page_index=0, number="E7.1", title="Power", discipline="Electrical",
        scale="", width_pt=100, height_pt=100, region=(0, 0, 100, 100),
        legend=[LegendEntry(symbol="CKT", description="CIRCUIT", kind="abbreviation", page_index=0)],
    )
    cluster = DeviceCluster(tag="CKT", sheet_page_index=0, placements=[Placement(1, 1)] * 3)
    items = classification.classify([cluster], [sheet])

    assert items[0].warning["where"] == "E7.1."


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


def test_a_shape_cluster_lands_unclassified_with_glyph_wording():
    from app.engine.classification import classify
    from app.engine.contracts import DetectedSheet, DeviceCluster, Placement
    sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                          width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    c = DeviceCluster(tag="shape:0a1b2c3d", sheet_page_index=0,
                      placements=[Placement(10, 10, 6, 6)] * 4, exemplar=(7, 7, 13, 13))
    (item,) = classify([c], [sheet])
    assert item.name == "Unclassified symbol" and item.status == "attention"
    assert item.source_tag == "shape:0a1b2c3d" and item.quantity == 4
    assert item.warning["title"] == "Symbol not in legend"
    assert item.warning["found"] == "A symbol appears 4 times on E2.1 but isn't in the legend."
    assert "shape:" not in item.warning["found"]
    assert item.placements[0].w == 6


def test_a_shape_cluster_lands_unclassified_on_the_llm_path_when_catalog_id_is_none():
    """The model was shown this shape's crop (or wasn't, over the per-sheet
    cap, or a crop that failed to render) and answered catalog_id "none"
    -- there is no classification to price either way, and this must land
    exactly as the deterministic path lands an unrecognized shape,
    regardless of whatever confidence or cost the model attached to a name
    it could not tie to a catalog item."""
    from app.engine import sheet
    from app.engine.contracts import Classification, DetectedSheet, DeviceCluster, Placement

    detected_sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                                   width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    cluster = DeviceCluster(tag="shape:abcd1234", sheet_page_index=0,
                            placements=[Placement(10, 10, 6, 6)] * 4, exemplar=(7, 7, 13, 13))
    cls = Classification(
        specs_by_tag={"shape:abcd1234": {"tag": "shape:abcd1234", "name": "Mystery", "catalog_id": "none",
                                          "confidence": "high", "material_cost": 40, "labor_hours": 1}},
        labor_rate=80.0, material_factor=1.0, source="llm", location_note="",
    )
    rows, applied, bare = sheet.rows_for([cluster], cls, [detected_sheet])
    (row,) = rows
    assert row["status"] == "attention"
    assert row["name"] == "Unclassified symbol"
    assert row["warning"]["title"] == "Symbol not in legend"
    assert row["material_cost"] == 0 and row["labor_hours"] == 0 and row["labor_cost"] == 0 and row["total_cost"] == 0


def test_an_ordinary_text_tag_keeps_the_model_warning_path_when_catalog_id_is_none():
    """The new shape: guard must not swallow a plain text tag's "none"
    answer -- that keeps going through _row_from_spec and _model_warning
    exactly as before."""
    from app.engine import sheet
    from app.engine.contracts import Classification, DetectedSheet, DeviceCluster, Placement

    detected_sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                                   width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    cluster = DeviceCluster(tag="F2", sheet_page_index=0, placements=[Placement(10, 10)] * 3)
    cls = Classification(
        specs_by_tag={"F2": {"tag": "F2", "name": "Type F luminaire", "catalog_id": "none",
                             "confidence": "low", "material_cost": 120, "labor_hours": 0.5}},
        labor_rate=80.0, material_factor=1.0, source="llm", location_note="",
    )
    rows, applied, bare = sheet.rows_for([cluster], cls, [detected_sheet])
    (row,) = rows
    assert row["name"] == "Type F luminaire"
    assert row["status"] == "attention"
    assert row["material_cost"] > 0


def _template(description, silhouette, modifier=""):
    from app.engine.contracts import SymbolTemplate
    return SymbolTemplate(description=description, modifier=modifier, rect=(0, 0, 10, 10),
                          silhouette=silhouette, sheet_number="E0.1")


def _sil(seed):
    import numpy as np
    from app.engine import legend_symbols as ls
    rng = np.random.default_rng(seed)
    return bytes((rng.random((ls.SIL, ls.SIL)) * 255).astype("uint8").ravel())


def test_an_unnamed_cluster_carries_ranked_suggestions():
    from app.engine.classification import classify
    from app.engine.contracts import DetectedSheet, DeviceCluster, Placement
    sil = _sil(1)
    sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                          width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    c = DeviceCluster(tag="shape:0a1b2c3d", sheet_page_index=0, placements=[Placement(10, 10, 6, 6)] * 4,
                      exemplar=(7, 7, 13, 13), exemplar_silhouette=sil)
    (item,) = classify([c], [sheet], templates=[_template("DUPLEX RECEPTACLE", sil), _template("PANEL", _sil(2))])
    assert item.name == "Unclassified symbol" and item.status == "attention"
    assert item.suggestions[0] == {"name": "Duplex receptacle", "sheet": "E0.1"}
    assert item.warning["fix"] == "Pick what this symbol is from the legend entries listed, or classify it by hand."
    assert "0a1b2c3d" not in str(item.suggestions)


def test_a_named_cluster_carries_no_suggestions():
    from app.engine.classification import classify
    from app.engine.contracts import DetectedSheet, DeviceCluster, Placement
    sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                          width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    c = DeviceCluster(tag="R", sheet_page_index=0, placements=[Placement(10, 10)] * 4)
    (item,) = classify([c], [sheet], templates=[_template("DUPLEX RECEPTACLE", _sil(1))])
    assert not item.suggestions


def test_no_templates_means_the_old_wording():
    from app.engine.classification import classify
    from app.engine.contracts import DetectedSheet, DeviceCluster, Placement
    sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                          width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    c = DeviceCluster(tag="shape:0a1b2c3d", sheet_page_index=0, placements=[Placement(10, 10, 6, 6)] * 4,
                      exemplar=(7, 7, 13, 13), exemplar_silhouette=_sil(3))
    (item,) = classify([c], [sheet], templates=[])
    assert item.suggestions == []
    assert item.warning["fix"] == "Assign a classification, or reject it if it isn't a device."


def test_a_modifier_tag_the_model_echoed_gets_its_row():
    """`shape:<sig>:<modifier>` is a tag like any other once the prompt
    describes it: the spec keyed on it prices the cluster normally."""
    from app.engine import sheet
    from app.engine.contracts import Classification, DetectedSheet, DeviceCluster, Placement

    detected_sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                                   width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    cluster = DeviceCluster(tag="shape:abcd1234:3", sheet_page_index=0,
                            placements=[Placement(10, 10, 6, 6)] * 4, exemplar=(7, 7, 13, 13), modifier="3")
    cls = Classification(
        specs_by_tag={"shape:abcd1234:3": {"tag": "shape:abcd1234:3", "name": "Three-way switch",
                                            "catalog_id": "switch_3way", "confidence": "high",
                                            "material_cost": 12, "labor_hours": 0.4}},
        labor_rate=80.0, material_factor=1.0, source="llm", location_note="",
    )
    rows, _applied, _bare = sheet.rows_for([cluster], cls, [detected_sheet])
    (row,) = rows
    assert row["name"] == "Three-way switch"
    assert row["quantity"] == 4


def test_a_modifier_tag_the_model_normalised_away_still_lands_as_an_item():
    """The honest failure. The model answered about `shape:abcd1234`
    while the cluster is tagged `shape:abcd1234:3`, so the exact-key
    lookup misses. That used to produce no row, no warning and no count
    -- a silently omitted device, which is the one outcome
    BUILD-STAGES.md names first. It now lands the way the deterministic
    path lands an unrecognised shape: an item that needs attention."""
    from app.engine import sheet
    from app.engine.contracts import Classification, DetectedSheet, DeviceCluster, Placement

    detected_sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                                   width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    cluster = DeviceCluster(tag="shape:abcd1234:3", sheet_page_index=0,
                            placements=[Placement(10, 10, 6, 6)] * 4, exemplar=(7, 7, 13, 13), modifier="3")
    cls = Classification(
        specs_by_tag={"shape:abcd1234": {"tag": "shape:abcd1234", "name": "Three-way switch",
                                          "catalog_id": "switch_3way", "confidence": "high",
                                          "material_cost": 12, "labor_hours": 0.4}},
        labor_rate=80.0, material_factor=1.0, source="llm", location_note="",
    )
    rows, _applied, _bare = sheet.rows_for([cluster], cls, [detected_sheet])
    (row,) = rows
    assert row["status"] == "attention"
    assert row["quantity"] == 4
    assert row["warning"]["title"] == "Symbol not in legend"


def test_a_text_tag_the_model_never_answered_still_lands_as_an_item():
    """Same hole, wider: the model is free to drop any tag from its
    answer, not only a shape one. A tag the deterministic chain knows
    comes back named and ready; one it does not comes back as an item
    that needs attention. Either beats no row at all."""
    from app.engine import sheet
    from app.engine.contracts import Classification, DetectedSheet, DeviceCluster, Placement

    detected_sheet = DetectedSheet(page_index=0, number="E2.1", title="", discipline="Electrical", scale="",
                                   width_pt=1000, height_pt=800, region=(0, 0, 1000, 800))
    known = DeviceCluster(tag="WP", sheet_page_index=0, placements=[Placement(10, 10)] * 7)
    unknown = DeviceCluster(tag="ZQ9", sheet_page_index=0, placements=[Placement(20, 20)] * 2)
    cls = Classification(specs_by_tag={}, labor_rate=80.0, material_factor=1.0, source="llm", location_note="")
    rows, _applied, _bare = sheet.rows_for([known, unknown], cls, [detected_sheet])
    by_tag = {r["tag"]: r for r in rows}
    assert by_tag["WP"]["quantity"] == 7 and by_tag["WP"]["status"] == "ready"
    assert by_tag["ZQ9"]["quantity"] == 2 and by_tag["ZQ9"]["status"] == "attention"
    assert by_tag["ZQ9"]["warning"]["title"]
