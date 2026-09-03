"""Pricing agent: what a device actually costs once its supporting
material is counted. Division 26 only."""

import pytest

from app.engine.assemblies import ASSEMBLIES, MATERIALS, expand


def test_a_receptacle_carries_box_plate_wire_and_connectors():
    a = expand("receptacle_20a", 1)
    ids = {l.catalog_id for l in a.lines}
    assert "box_4sq" in ids
    assert "plate_1g" in ids
    assert "thhn_12" in ids, "branch wire is the largest material line and must be present"
    assert "conn_emt_1_2" in ids


def test_quantity_scales_every_line():
    one = expand("receptacle_20a", 1)
    ten = expand("receptacle_20a", 10)
    by_id = {l.catalog_id: l.quantity for l in one.lines}
    for line in ten.lines:
        assert line.quantity == pytest.approx(by_id[line.catalog_id] * 10)


def test_material_cost_is_the_sum_of_its_lines():
    a = expand("receptacle_20a", 2)
    expected = round(sum(l.material_cost * l.quantity for l in a.lines), 2)
    assert a.material_cost == expected


def test_a_luminaire_carries_whip_and_wire_not_a_device_plate():
    a = expand("luminaire_troffer", 1)
    ids = {l.catalog_id for l in a.lines}
    assert "whip_6ft" in ids
    assert "plate_1g" not in ids, "a fixture takes no device plate"


def test_an_unknown_catalog_id_expands_to_an_empty_assembly():
    """An unclassified item has no assembly. It must contribute zero rather
    than guessing material, exactly as pricing.py already refuses to guess a
    price for an unclassified item."""
    a = expand("unclassified", 5)
    assert a.lines == []
    assert a.material_cost == 0.0


def test_every_assembly_line_names_a_known_material():
    for parent, lines in ASSEMBLIES.items():
        for material_id, _qty in lines:
            assert material_id in MATERIALS, f"{parent} references unknown material {material_id}"


def test_every_catalog_device_that_gets_installed_has_an_assembly():
    """A device with no assembly is priced as a bare device, which
    understates it. This asserts the gap is deliberate, not forgotten."""
    from app.engine.catalog import CATALOG

    unpriced = {"luminaire_generic"}  # a generic placeholder, intentionally bare
    missing = [cid for cid in CATALOG if cid not in ASSEMBLIES and cid not in unpriced]
    assert missing == [], f"catalog items with no assembly: {missing}"


def test_every_installed_assembly_carries_a_ground():
    """An equipment grounding conductor is not optional on a Division 26
    installation. exit_sign shipped without one because nothing asserted
    this -- a table this size needs the rule checked rather than eyeballed."""
    grounds = {"ground_12"}
    for parent, lines in ASSEMBLIES.items():
        ids = {material_id for material_id, _qty in lines}
        assert ids & grounds, f"{parent} has no grounding conductor"
