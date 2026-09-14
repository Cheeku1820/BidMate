"""Pricing agent (v1).

Attaches cost to each classified item: material from the catalog price
book plus the item's assembly (the box, plate, wire, and conduit it drags
along -- see assemblies.py), labor hours from the catalog plus the
assembly's, labor cost at the firm's blended rate (the labor rate that
already lives on the Company settings screen). The engine stops at total
direct cost -- markup, overhead, and profit are the estimator-owned layer
and no agent proposes them (invariant 13).

An unclassified item has no catalog entry and so no price: it contributes
zero to the total and stays flagged for review, rather than being guessed
a cost. That is honest -- an unpriced, visible item is recoverable; a
fabricated price in a submitted bid is not.
"""

from __future__ import annotations

from .assemblies import expand
from .catalog import CATALOG
from .contracts import ClassifiedItem, PricedItem

# Blended crew rate default, matching the Company settings journeyman rate
# (settingsStore.js COMPANY_DEFAULTS). Passed in so a project override or a
# real rate table can replace it without touching this module.
DEFAULT_LABOR_RATE = 68.0


def price_item(item: ClassifiedItem, labor_rate: float) -> PricedItem:
    cat = CATALOG.get(item.catalog_id)
    if cat is None:  # unclassified -> unpriced, contributes nothing
        return PricedItem(item=item, material_cost=0.0, labor_hours=0.0, labor_cost=0.0, total_direct_cost=0.0)
    asm = expand(item.catalog_id, item.quantity)
    material = round(cat.material_cost * item.quantity + asm.material_cost, 2)
    hours = round(cat.labor_hours * item.quantity + asm.labor_hours, 2)
    labor = round(hours * labor_rate, 2)
    return PricedItem(item=item, material_cost=material, labor_hours=hours, labor_cost=labor,
                      total_direct_cost=round(material + labor, 2), assembly=asm)


def price(items: list[ClassifiedItem], labor_rate: float = DEFAULT_LABOR_RATE) -> list[PricedItem]:
    return [price_item(i, labor_rate) for i in items]
