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
    understates it.

    This test previously carried a whitelist exempting `luminaire_generic`
    as "a generic placeholder, intentionally bare" -- and that id is what
    every fixture-type letter on a real set resolves to, so the exemption
    hid 97 fixture units being priced with no whip, no wire and no ground.
    There is no whitelist now: every catalog item an estimator can be shown
    is an item that gets installed, so every one needs an assembly."""
    from app.engine.catalog import CATALOG

    missing = [cid for cid in CATALOG if cid not in ASSEMBLIES]
    assert missing == [], f"catalog items with no assembly: {missing}"


def test_a_box_does_not_carry_another_box():
    """junction_box shipped as catalog "Junction box" ($6.00, category
    Boxes) *plus* a box_4sq line in its assembly -- two boxes for one
    junction box, about $170 and 8.25 crew hours on the real set's 55
    units.

    The rule is not "no assembly contains a box": a receptacle is a device
    that needs one, and its assembly is right to carry it. It is that an
    item which already *is* the box must not also drag one along."""
    from app.engine.catalog import CATALOG

    boxes = {"box_4sq"}
    for catalog_id, item in CATALOG.items():
        if item.category != "Boxes":
            continue
        ids = {material_id for material_id, _qty in ASSEMBLIES.get(catalog_id, [])}
        assert not (ids & boxes), f"{catalog_id} is a box and also carries {ids & boxes}"


def test_an_assembly_with_circuit_conductors_carries_a_ground():
    """The rule is not "everything has a ground" -- it is that you never run
    current-carrying conductors without an equipment grounding conductor
    beside them. exit_sign shipped with thhn_12 and no ground because
    nothing checked this.

    Assemblies with no circuit conductor are exempt by the rule itself,
    not by an exemption list: data_outlet is a Division 26 rough-in for a
    Division 27 cable another trade pulls, and junction_box is a splice
    point whose conductors belong to the device assembly feeding through
    it -- grounding either here would double count.
    """
    conductors = {"thhn_12", "thhn_10"}
    for parent, lines in ASSEMBLIES.items():
        ids = {material_id for material_id, _qty in lines}
        if ids & conductors:
            assert "ground_12" in ids, f"{parent} runs conductors with no ground"
