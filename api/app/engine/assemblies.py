"""Division 26 assemblies -- what a device drags along with it.

An estimator does not price a receptacle as a receptacle. Installing one
means a box, a plate, branch wire back to the last device, and the
connectors to land the raceway. Wire and conduit are a large share of
material cost, which is why ROADMAP.md names them the largest single
threat to a defensible total. Pricing a bare device understates the job.

Everything here is Division 26. Quantities are per one parent device.

FEET_PER_DEVICE is the firm's own rule of thumb, not a measurement. The
drawing shows a homerun arrow, not a route, so the run length is judgment
from ceiling height and building geometry and is not in the file for
anyone to read (ROADMAP 2.1). Thirty feet is a common default and stands
in until a firm supplies its own. It is deliberately one named constant
rather than being spread through the table below.
"""

from __future__ import annotations

from .contracts import Assembly, AssemblyLine

FEET_PER_DEVICE = 30.0

# Each supporting material, described once. Costs are dollars per unit and
# crew hours per unit -- rough order-of-magnitude figures for a defensible
# shape, not a quote, the same standing as catalog.py's price book.
MATERIALS: dict[str, AssemblyLine] = {
    "box_4sq":      AssemblyLine("box_4sq", "4in square box", 1, "ea", 3.10, 0.15),
    "mudring_1g":   AssemblyLine("mudring_1g", "1-gang mud ring", 1, "ea", 1.40, 0.05),
    "plate_1g":     AssemblyLine("plate_1g", "1-gang device plate", 1, "ea", 0.90, 0.04),
    "thhn_12":      AssemblyLine("thhn_12", "#12 THHN conductor", 1, "ft", 0.18, 0.004),
    "thhn_10":      AssemblyLine("thhn_10", "#10 THHN conductor", 1, "ft", 0.28, 0.005),
    "emt_1_2":      AssemblyLine("emt_1_2", '1/2in EMT conduit', 1, "ft", 0.62, 0.030),
    "conn_emt_1_2": AssemblyLine("conn_emt_1_2", '1/2in EMT connector', 1, "ea", 0.85, 0.03),
    "whip_6ft":     AssemblyLine("whip_6ft", "6ft fixture whip", 1, "ea", 8.50, 0.10),
    "wirenut":      AssemblyLine("wirenut", "Wire connector", 1, "ea", 0.12, 0.01),
    "ground_12":    AssemblyLine("ground_12", "#12 ground conductor", 1, "ft", 0.14, 0.003),
}

# parent catalog id -> [(material id, quantity per one parent)]
# A branch device carries three conductors over FEET_PER_DEVICE: hot,
# neutral, and a ground run on its own line so a firm can price it apart.
_BRANCH_WIRE = [
    ("thhn_12", FEET_PER_DEVICE * 2),
    ("ground_12", FEET_PER_DEVICE),
    ("emt_1_2", FEET_PER_DEVICE),
    ("conn_emt_1_2", 2.0),
    ("wirenut", 3.0),
]

ASSEMBLIES: dict[str, list[tuple[str, float]]] = {
    "receptacle_20a": [("box_4sq", 1), ("mudring_1g", 1), ("plate_1g", 1), *_BRANCH_WIRE],
    "receptacle_gfci": [("box_4sq", 1), ("mudring_1g", 1), ("plate_1g", 1), *_BRANCH_WIRE],
    "switch_sp": [("box_4sq", 1), ("mudring_1g", 1), ("plate_1g", 1), *_BRANCH_WIRE],
    "data_outlet": [("box_4sq", 1), ("mudring_1g", 1), ("plate_1g", 1),
                    ("emt_1_2", FEET_PER_DEVICE), ("conn_emt_1_2", 2.0)],
    "junction_box": [("box_4sq", 1), ("wirenut", 3.0),
                     ("emt_1_2", FEET_PER_DEVICE / 2), ("conn_emt_1_2", 2.0)],
    # Fixtures land on a whip rather than a device plate, but they carry the
    # same conductor model as a device: a switched hot, a neutral, and a
    # ground over FEET_PER_DEVICE. The rule of thumb is uniform, so the
    # conductor count is too -- an asymmetry here would be arbitrary rather
    # than a measurement, and FEET_PER_DEVICE is already openly a firm's
    # rule rather than a routed length.
    "luminaire_troffer": [("whip_6ft", 1), ("wirenut", 3.0),
                          ("thhn_12", FEET_PER_DEVICE * 2), ("ground_12", FEET_PER_DEVICE)],
    "luminaire_highbay": [("whip_6ft", 1), ("wirenut", 3.0),
                          ("thhn_10", FEET_PER_DEVICE * 2), ("ground_12", FEET_PER_DEVICE)],
    "exit_sign": [("whip_6ft", 1), ("wirenut", 3.0),
                  ("thhn_12", FEET_PER_DEVICE * 2), ("ground_12", FEET_PER_DEVICE)],
    # Gear is fed, not branch-wired: heavier conductor, no device trim.
    "panel": [("thhn_10", FEET_PER_DEVICE * 3), ("emt_1_2", FEET_PER_DEVICE),
              ("conn_emt_1_2", 4.0), ("ground_12", FEET_PER_DEVICE)],
    "disconnect": [("thhn_10", FEET_PER_DEVICE), ("emt_1_2", FEET_PER_DEVICE / 2),
                   ("conn_emt_1_2", 2.0), ("ground_12", FEET_PER_DEVICE / 2)],
}


def expand(catalog_id: str, quantity: float) -> Assembly:
    """The supporting material for `quantity` of one catalog device.
    An id with no assembly yields an empty one -- it contributes zero
    rather than a guessed material list, the same refusal pricing.py
    already makes for an unclassified item."""
    lines = []
    for material_id, per_parent in ASSEMBLIES.get(catalog_id, []):
        base = MATERIALS[material_id]
        lines.append(AssemblyLine(
            catalog_id=base.catalog_id, name=base.name,
            quantity=round(per_parent * quantity, 3), unit=base.unit,
            material_cost=base.material_cost, labor_hours=base.labor_hours,
        ))
    return Assembly(parent_catalog_id=catalog_id, lines=lines)
