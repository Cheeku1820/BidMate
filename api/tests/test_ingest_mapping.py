"""app/takeoff/ingest.py -- the engine payload to domain mapping, moved
server-side from the client's seed-ingest.js. Pure functions: no database.
"""
import base64
import pytest

from app.errors import DomainError
from app.takeoff.ingest import infer_symbol, map_payload, normalize_point, validate_warning

SHEET_SPACE_W = 1000
SHEET_SPACE_H = 750


def _payload(**over):
    base = {
        "sheets": [
            {"id": "tk1:0", "number": "E2.1", "takeoff_id": "tk1", "page": 0,
             "width_pt": 2000, "height_pt": 1500, "unreadable": None, "ai_reading": None},
        ],
        "items": [
            {"name": "20A duplex receptacle", "system": "Power", "category": "Devices",
             "unit": "ea", "quantity": 47, "status": "ready", "sheet_id": "tk1:0",
             "symbol": "receptacle", "warning": None, "x": 1000, "y": 750,
             "placements": [[1000, 750], [500, 375]],
             "material_cost": 188.0, "labor_hours": 15.51, "labor_cost": 1209.78,
             "total_cost": 1397.78, "ai_confirmed": False},
        ],
    }
    base.update(over)
    return base


def test_normalize_point_scales_into_sheet_space():
    """A point at the middle of a 2000pt-wide page is the middle of the
    1000-unit sheet space."""
    assert normalize_point(1000, 2000, SHEET_SPACE_W) == 500
    assert normalize_point(0, 2000, SHEET_SPACE_W) == 0
    assert normalize_point(2000, 2000, SHEET_SPACE_W) == 1000


def test_normalize_point_survives_a_zero_extent():
    """A sheet the engine could not measure must not divide by zero and
    take the whole ingest down with it."""
    assert normalize_point(500, 0, SHEET_SPACE_W) == 0


def test_map_payload_normalizes_against_the_items_own_sheet():
    """Two sheets of different sizes: an item's coordinates must be scaled
    by ITS sheet's dimensions, or markers land wrongly on one of them."""
    payload = _payload(
        sheets=[
            {"id": "tk1:0", "number": "E1.1", "takeoff_id": "tk1", "page": 0,
             "width_pt": 2000, "height_pt": 1500, "unreadable": None, "ai_reading": None},
            {"id": "tk1:1", "number": "E2.1", "takeoff_id": "tk1", "page": 1,
             "width_pt": 4000, "height_pt": 3000, "unreadable": None, "ai_reading": None},
        ],
        items=[
            {"name": "Panel", "system": "Distribution", "category": "Gear", "unit": "ea",
             "quantity": 1, "status": "ready", "sheet_id": "tk1:0", "symbol": "panel",
             "warning": None, "x": 1000, "y": 750, "placements": [],
             "material_cost": 0, "labor_hours": 0, "labor_cost": 0, "total_cost": 0},
            {"name": "Panel", "system": "Distribution", "category": "Gear", "unit": "ea",
             "quantity": 1, "status": "ready", "sheet_id": "tk1:1", "symbol": "panel",
             "warning": None, "x": 1000, "y": 750, "placements": [],
             "material_cost": 0, "labor_hours": 0, "labor_cost": 0, "total_cost": 0},
        ],
    )
    mapped = map_payload(payload)
    first = next(i for i in mapped.items if i["sheet_key"] == "tk1:0")
    second = next(i for i in mapped.items if i["sheet_key"] == "tk1:1")
    # The item sits at the exact center of each page (x = width/2, y =
    # height/2), so it must land at the center of the 1000x750 canvas:
    # (500, 375), not (500, 500). x and y scale into DIFFERENT targets
    # (1000 and 750 respectively), so a page-center point does not land
    # on (500, 500) -- do not "fix" this back without re-deriving the
    # geometry first.
    assert (first["x"], first["y"]) == (500, 375)
    assert (second["x"], second["y"]) == (250, 188)


def test_map_payload_normalizes_every_placement():
    mapped = map_payload(_payload())
    assert mapped.items[0]["placements"] == [[500, 375], [250, 188]]


def test_map_payload_carries_cost_and_sheet_metadata():
    mapped = map_payload(_payload())
    item = mapped.items[0]
    assert item["material_cost"] == 188.0
    assert item["total_cost"] == 1397.78
    sheet = mapped.sheets[0]
    assert sheet["takeoff_id"] == "tk1"
    assert sheet["width_pt"] == 2000
    assert sheet["number"] == "E2.1"


def test_map_payload_prefers_the_engines_symbol():
    """The classifier already chose a symbol; guessing from the name is
    only a fallback for rows that carry none."""
    mapped = map_payload(_payload())
    assert mapped.items[0]["symbol"] == "receptacle"


def test_map_payload_falls_back_to_inferring_a_symbol():
    payload = _payload()
    payload["items"][0]["symbol"] = ""
    mapped = map_payload(payload)
    assert mapped.items[0]["symbol"] == "receptacle"


def test_infer_symbol_maps_names_to_glyphs():
    assert infer_symbol("20A duplex receptacle", "Power") == "receptacle"
    assert infer_symbol("Single-pole switch", "Power") == "switch"
    assert infer_symbol("Panelboard LP-2", "Distribution") == "panel"
    assert infer_symbol("High bay fixture", "Lighting") == "highbay"
    assert infer_symbol("2x4 troffer", "Lighting") == "troffer"
    assert infer_symbol("Data outlet", "Low voltage") == "data"
    assert infer_symbol("Something unheard of", "") == "junction"


def test_validate_warning_accepts_the_full_shape():
    warning = {"reason": "legend", "title": "Symbol not in legend", "found": "f",
               "why": "w", "fix": "x", "where": "E2.1"}
    assert validate_warning(warning)["reason"] == "legend"


@pytest.mark.parametrize("missing", ["title", "found", "why", "fix", "where"])
def test_validate_warning_rejects_a_partial_warning(missing):
    """A warning missing a field is a schema error, not a copy oversight --
    and the refusal names the field so the pipeline can be fixed."""
    warning = {"reason": "legend", "title": "t", "found": "f", "why": "w", "fix": "x", "where": "E2.1"}
    del warning[missing]
    with pytest.raises(DomainError) as exc:
        validate_warning(warning)
    assert exc.value.status == 422
    assert missing in exc.value.message


def test_validate_warning_rejects_an_unknown_reason():
    """WarningReason is a closed vocabulary. A new kind of warning needs a
    migration someone writes on purpose, not a string that slips through."""
    warning = {"reason": "vibes", "title": "t", "found": "f", "why": "w", "fix": "x", "where": "E2.1"}
    with pytest.raises(DomainError) as exc:
        validate_warning(warning)
    assert exc.value.status == 422


def test_map_payload_rejects_an_item_on_an_unknown_sheet():
    payload = _payload()
    payload["items"][0]["sheet_id"] = "tk9:404"
    with pytest.raises(DomainError) as exc:
        map_payload(payload)
    assert exc.value.status == 422


def test_map_payload_normalizes_a_well_formed_ai_reading():
    payload = _payload()
    payload["sheets"][0]["ai_reading"] = {
        "summary": "reads as a power plan",
        "devices": [{"name": "Duplex receptacle", "count": 47}],
    }
    mapped = map_payload(payload)
    assert mapped.sheets[0]["ai_reading"] == {
        "summary": "reads as a power plan",
        "devices": [{"name": "Duplex receptacle", "count": 47}],
    }


def test_map_payload_drops_an_ai_reading_missing_devices():
    """A model-produced reading with no `devices` key is plausible and
    must not reach the client as an object the UI assumes has one."""
    payload = _payload()
    payload["sheets"][0]["ai_reading"] = {"summary": "reads as a power plan"}
    mapped = map_payload(payload)
    assert mapped.sheets[0]["ai_reading"] == {"summary": "reads as a power plan", "devices": []}


def test_map_payload_drops_an_ai_reading_whose_devices_is_not_a_list():
    payload = _payload()
    payload["sheets"][0]["ai_reading"] = {"summary": "reads as a power plan", "devices": "a lot"}
    mapped = map_payload(payload)
    assert mapped.sheets[0]["ai_reading"] == {"summary": "reads as a power plan", "devices": []}


def test_map_payload_drops_malformed_device_entries_but_keeps_good_ones():
    payload = _payload()
    payload["sheets"][0]["ai_reading"] = {
        "summary": "reads as a power plan",
        "devices": [
            {"name": "Duplex receptacle", "count": 47},
            "not an object",
            {"name": "Switch"},  # missing count -- dropped, not defaulted silently
            {"count": 3},  # missing name -- dropped
            {"name": "Panel", "count": "12"},  # non-numeric count -- dropped
        ],
    }
    mapped = map_payload(payload)
    assert mapped.sheets[0]["ai_reading"]["devices"] == [{"name": "Duplex receptacle", "count": 47}]


def test_map_payload_stores_none_when_ai_reading_is_not_an_object():
    payload = _payload()
    payload["sheets"][0]["ai_reading"] = "reads as a power plan"
    mapped = map_payload(payload)
    assert mapped.sheets[0]["ai_reading"] is None


def test_map_payload_stores_none_when_ai_reading_absent():
    payload = _payload()
    payload["sheets"][0]["ai_reading"] = None
    mapped = map_payload(payload)
    assert mapped.sheets[0]["ai_reading"] is None


def test_map_payload_carries_the_cluster_tag():
    """Counting's tag is the merge key for an approval-preserving re-run.
    Dropped, there is nothing stable to match the same cluster across two
    runs of the same drawing."""
    payload = _payload()
    payload["items"][0]["tag"] = "R"
    mapped = map_payload(payload)
    assert mapped.items[0]["source_tag"] == "R"


def test_map_payload_tolerates_a_missing_tag():
    payload = _payload()
    payload["items"][0].pop("tag", None)
    assert map_payload(payload).items[0]["source_tag"] == ""


def test_map_payload_keeps_a_grounded_warning():
    warning = {"reason": "legend", "title": "Fixture type needs confirmation",
               "found": "Type F2 appears 3 times on E2.1, but the schedule only lists types A-E.",
               "why": "F2's exact fixture and price depend on which schedule entry it matches.",
               "fix": "Check the luminaire schedule for a type F2 entry.",
               "where": "E2.1 and the luminaire schedule."}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    mapped = map_payload(_payload(items=[item]))
    assert mapped.items[0]["warning"]["found"] == warning["found"]


def test_map_payload_replaces_a_warning_that_references_an_unknown_sheet():
    warning = {"reason": "legend", "title": "x",
               "found": "Type F2 appears 3 times on E9.9, but the schedule only lists types A-E.",
               "why": "y", "fix": "z", "where": "E9.9"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2", "quantity": 3}
    mapped = map_payload(_payload(items=[item]))
    assert "E9.9" not in mapped.items[0]["warning"]["found"]
    assert mapped.items[0]["warning"]["title"] == "Item type needs confirmation"


def test_map_payload_replaces_a_warning_that_references_an_unknown_sheet_in_fix():
    """found/where are synthesized upstream now, so a fabricated sheet
    number can only arrive inside the model-written title/why/fix."""
    warning = {"reason": "legend", "title": "x", "found": "y",
               "why": "z", "fix": "Check the schedule on E9.9 for this type.", "where": "v"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    mapped = map_payload(_payload(items=[item]))
    assert mapped.items[0]["warning"]["title"] == "Item type needs confirmation"


def test_map_payload_replaces_a_warning_carrying_ai_framing():
    warning = {"reason": "legend", "title": "x",
               "found": "The AI is not confident about type F2 on E2.1.",
               "why": "y", "fix": "z", "where": "E2.1"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    mapped = map_payload(_payload(items=[item]))
    assert mapped.items[0]["warning"]["title"] == "Item type needs confirmation"


def test_map_payload_does_not_flag_a_legitimate_word_containing_ai():
    warning = {"reason": "legend", "title": "x",
               "found": "Type F2 appears 3 times on E2.1; explain the schedule detail before approving.",
               "why": "y", "fix": "z", "where": "E2.1"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    mapped = map_payload(_payload(items=[item]))
    assert mapped.items[0]["warning"]["found"] == warning["found"]


def test_fallback_warning_text_matches_the_deterministic_engine_template():
    """ingest.py's fallback_warning() and estimate.py's
    _unconfirmed_type_warning() are a deliberate duplication across the
    engine/API module boundary (ingest.py doesn't import app.engine) --
    nothing else ties them together, so this asserts they stay aligned."""
    from app.engine.estimate import _unconfirmed_type_warning
    from app.takeoff.ingest import fallback_warning
    assert fallback_warning("F2", 3, "E2.1") == _unconfirmed_type_warning("F2", 3, "E2.1")


def test_fallback_warning_is_always_grounded():
    from app.takeoff.ingest import fallback_warning, is_warning_grounded

    warning = fallback_warning("F2", 3, "E2.1")
    assert is_warning_grounded(warning, {"E2.1"})


def test_grounded_or_fallback_preserves_the_warnings_own_reason():
    """scale.set_scale() clears only warnings whose reason is "scale" -- a
    groundedness swap that rewrote the reason would leave a Missing
    information item with no path to resolution."""
    from app.takeoff.ingest import fallback_warning
    result = fallback_warning("F2", 3, "E2.1", reason="scale")
    assert result["reason"] == "scale"


def test_map_payload_carries_a_scale_reason_through_a_groundedness_swap():
    warning = {"reason": "scale", "title": "x",
               "found": "Type F2 appears 3 times on E9.9, an unknown sheet.",
               "why": "y", "fix": "z", "where": "E9.9"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    mapped = map_payload(_payload(items=[item]))
    assert mapped.items[0]["warning"]["title"] == "Item type needs confirmation"
    assert mapped.items[0]["warning"]["reason"] == "scale"


def test_map_payload_replaces_a_warning_leaking_a_confidence_tier():
    warning = {"reason": "legend", "title": "x",
               "found": "Type F2 appears 3 times on E2.1, medium confidence match to the schedule.",
               "why": "y", "fix": "z", "where": "E2.1"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    mapped = map_payload(_payload(items=[item]))
    assert mapped.items[0]["warning"]["title"] == "Item type needs confirmation"


def test_map_payload_logs_the_fallback_count_for_a_document():
    """The design asks for the fallback RATE to be visible over time, so a
    swap has to leave a trace -- a count, never the warning's own text."""
    from unittest.mock import patch

    warning = {"reason": "legend", "title": "x",
               "found": "Type F2 appears 3 times on E9.9, an unknown sheet.",
               "why": "y", "fix": "z", "where": "E9.9"}
    item = {**_payload()["items"][0], "status": "attention", "warning": warning, "tag": "F2"}
    with patch("app.takeoff.ingest.logger") as mock_logger:
        map_payload(_payload(items=[item]))
    mock_logger.info.assert_called_once()
    assert mock_logger.info.call_args.kwargs["extra"] == {"fallback_count": 1, "item_count": 1}


def test_map_payload_does_not_log_when_no_warning_falls_back():
    from unittest.mock import patch

    with patch("app.takeoff.ingest.logger") as mock_logger:
        map_payload(_payload())
    mock_logger.info.assert_not_called()


def test_map_payload_populates_evidence_metadata():
    payload = _payload()
    payload["items"][0]["evidence_png_b64"] = base64.b64encode(b"fake-png").decode("ascii")
    mapped = map_payload(payload)
    item = mapped.items[0]
    assert item["evidence"]["sheet"] == "E2.1"
    assert item["evidence"]["has_image"] is True
    assert "2 locations" in item["evidence"]["detail"]
    assert item["evidence_png"] == b"fake-png"


def test_map_payload_evidence_has_image_false_without_a_crop():
    payload = _payload()
    mapped = map_payload(payload)
    item = mapped.items[0]
    assert item["evidence"]["has_image"] is False
    assert item["evidence_png"] is None


def test_map_payload_evidence_detail_is_singular_for_one_location():
    payload = _payload()
    payload["items"][0]["placements"] = [[1000, 750]]
    mapped = map_payload(payload)
    assert "1 location" in mapped.items[0]["evidence"]["detail"]
    assert "1 locations" not in mapped.items[0]["evidence"]["detail"]


def test_the_basis_note_carries_both_engine_notes():
    """`location_note` says what the costs are indexed to; `wiring_note`
    says branch wiring was assumed rather than measured. Both are pricing
    basis, both belong in the note the pricing screens show, and the
    engine keeps them as separate fields so neither is buried in the
    other's sentence upstream."""
    from app.takeoff.ingest import basis_note

    note = basis_note({
        "location_note": "Rate based on Unalaska, AK area cost data.",
        "wiring_note": "Branch wiring is estimated at 30 feet per device.",
    })
    assert note == ("Rate based on Unalaska, AK area cost data. "
                    "Branch wiring is estimated at 30 feet per device.")


def test_a_payload_with_neither_note_yields_an_empty_basis_note():
    """A payload that repriced nothing has always yielded "", and that is
    load-bearing: ingest_service falls back to the project's existing note
    rather than clearing it, and clearing flips every labor and material
    row to Missing information."""
    from app.takeoff.ingest import basis_note

    assert basis_note({}) == ""
    assert basis_note({"location_note": None, "wiring_note": ""}) == ""


def test_a_payload_from_before_the_wiring_note_still_maps():
    """Every stored payload and every test fixture written before this
    field existed carries only location_note. Those must map to exactly
    what they always did."""
    from app.takeoff.ingest import basis_note

    assert basis_note({"location_note": "National average rate (no local data matched)."}) == \
        "National average rate (no local data matched)."


def test_a_model_written_note_that_breaks_the_language_rules_is_dropped():
    """On the LLM path `location_note` is written by the model, and
    basis_note is what puts it on an estimator's screen. BANNED_PHRASES
    was applied only to warnings, so a note naming a model or quoting a
    confidence figure crossed the boundary untouched -- while the
    code-written half beside it was the only part anything checked."""
    from app.takeoff.ingest import basis_note

    wiring = "Branch wiring is estimated at 30 feet per device."
    for bad in ("Confidence in this rate is 80%.", "Claude priced this location.",
                "I think this is about right.", "Rate set by the LLM."):
        note = basis_note({"location_note": bad, "wiring_note": wiring})
        assert note == wiring, f"{bad!r} reached the estimator"


def test_a_clean_note_is_untouched_by_the_language_check():
    from app.takeoff.ingest import basis_note

    note = basis_note({"location_note": "Rate based on Unalaska, AK area cost data.",
                       "wiring_note": "Branch wiring is estimated at 30 feet per device."})
    assert note.startswith("Rate based on Unalaska, AK area cost data.")


def test_the_engine_half_is_kept_when_the_model_half_fails():
    """Dropping the failing half rather than the whole note: the wiring
    assumption is the one an estimator most needs, and it is not the half
    that broke the rules."""
    from app.takeoff.ingest import basis_note

    assert basis_note({"location_note": "Confidence 90%.", "wiring_note": "Branch wiring is estimated."}) \
        == "Branch wiring is estimated."
    assert basis_note({"location_note": "Confidence 90%."}) == ""
