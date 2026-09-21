from eval.pricing_coverage import classify_lines

LINES = [
    {"name": "Duplex Receptacle", "description": "", "unit": "EA", "unit_material": 15},
    {"name": "Switch Board MSBS", "description": "", "unit": "EA", "unit_material": 14500},
    {"name": "C: 8' LED Vaportite", "description": "Manufacturer: Current\nModel: CVT8-LSCS-MV", "unit": "EA", "unit_material": 250},
    {"name": "Lump sum cost for wiring and conduits", "description": "", "unit": "LS", "unit_material": 1850},
]


def test_classify_lines_counts_by_route():
    assert classify_lines(LINES) == {"lines": 4, "onebuild": 1, "shopping": 1, "quote_required": 2}
