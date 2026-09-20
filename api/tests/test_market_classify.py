"""How an item is routed to a market source -- deterministic, no
network (estimate-first-pricing §3 step 1)."""
import pytest

from app.market.classify import classify_for_lookup, extract_model, lookup_key, parse_zip, unit_matches


@pytest.mark.parametrize("location, zip_", [
    ("Unalaska, AK 99685", "99685"),
    ("Springfield, IL 62701 USA", "62701"),
    ("Austin, TX 78701-1234", "78701"),
    ("Springfield, IL", None),
    ("", None),
    ("Suite 12345 Main St", None),      # a number that is not at the end is not a ZIP
])
def test_parse_zip(location, zip_):
    assert parse_zip(location) == zip_


def test_extract_model_reads_manufacturer_and_model_lines():
    desc = "C: 8' LED Vaportite\nManufacturer: Current\nModel: CVT8-LSCS-MV\nWattage: 60"
    assert extract_model(desc) == ("Current", "CVT8-LSCS-MV")


def test_extract_model_needs_a_model_line():
    assert extract_model("A: 8' LED strip fixture\nManufacturer: Signify") is None
    assert extract_model("Duplex Receptacle, 20A Flush Wall Mounted") is None


def test_extract_model_rejects_short_or_wordy_tokens():
    assert extract_model("Model: LED") is None
    assert extract_model("Model: 2x4") is None


@pytest.mark.parametrize("name, description, unit, source, reason", [
    ("Lump sum cost for wiring and conduits", "", "LS", None, "quote_required"),
    ("Switch Board MSBS", "", "EA", None, "quote_required"),
    ("ACME Boost Transformer", "", "EA", None, "quote_required"),
    ("S.P.D (Surge Protective Device)", "Manufacturer: DEHN INC.\nModel: #CG3-060", "EA", None, "quote_required"),
    ("Furnish & install new setup transformer", "", "EA", None, "quote_required"),
    ("Connection to electrical equipments", "", "EA", None, "quote_required"),
    ("Luminaire", "C: 8' LED Vaportite\nManufacturer: Current\nModel: CVT8-LSCS-MV", "EA", "shopping", "model"),
    ("20A duplex receptacle", "", "EA", "onebuild", "name"),
    ("2x4 LED troffer", "A: 8' LED strip\nManufacturer: Signify", "EA", "onebuild", "name"),
])
def test_classify_for_lookup(name, description, unit, source, reason):
    lookup = classify_for_lookup(name, description, unit)
    assert lookup.source == source and lookup.reason == reason


def test_shopping_query_is_manufacturer_then_model():
    lookup = classify_for_lookup("Luminaire", "Manufacturer: Current\nModel: CVT8-LSCS-MV", "EA")
    assert lookup.query == "Current CVT8-LSCS-MV"


def test_onebuild_query_is_the_item_name():
    assert classify_for_lookup("20A duplex receptacle", "Duplex Receptacle", "EA").query == "20A duplex receptacle"


@pytest.mark.parametrize("uom, unit, ok", [
    ("EA", "ea", True), ("EA", "EA", True), ("LF", "ft", True), ("LF", "LF", True),
    ("EA", "ft", False), ("SF", "ea", False), ("", "ea", False),
])
def test_unit_matches(uom, unit, ok):
    assert unit_matches(uom, unit) is ok


def test_lookup_key_normalizes():
    assert lookup_key("  20A  Duplex   Receptacle ") == "20a duplex receptacle"
