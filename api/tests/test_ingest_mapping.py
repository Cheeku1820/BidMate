"""app/takeoff/ingest.py -- the engine payload to domain mapping, moved
server-side from the client's seed-ingest.js. Pure functions: no database.
"""
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
