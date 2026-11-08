"""Labor and material assumptions, read off the resolvers' own bases.

docs/specs/rom-estimate.md. Nothing here recomputes a price or an hour.
`app.takeoff.pricing` already resolves every line through the firm's
precedence chain and reports which tier won; this module's whole job is
to translate that signal into the basis vocabulary and say so in words a
GC can read. Recomputing would mean two pricing implementations that
drift, and the drift would show up as a document whose disclosures
describe a different number than the one printed on it.

**Where the counted/assumed line falls.** A number is *counted* when it
came from this job: a supplier's quote for this item, a price an
estimator typed, a market lookup for this item in this ZIP on a date.
It is *assumed* when it was derived from somewhere other than this job
-- the firm's tables, what gear of a class costs, a rule.

That puts a market estimate on the counted side while it still widens
the budget range, which is not a contradiction: the origin tag answers
"did somebody have to invent this number", and the basis spread answers
"how firm is the method". A catalog price for the right item on a known
date is a real price that is nonetheless not contractor net pricing.
Hence two outputs from the same walk -- `*_assumptions` for what gets
disclosed, `cost_exposures` for what widens the range.

Grouping is deliberate and not uniform. Firm-table bases are grouped
into one line naming the count, because forty identical disclosures is a
page nobody reads. A class average is named per item, because "which
piece of gear is carrying a price nobody quoted" is exactly the question
a GC asks, and collapsing it would answer the opposite one.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.estimate import copy
from app.estimate.range import Exposure
from app.takeoff.models import (
    CompanyLaborHoursOverride,
    CompanyLaborRate,
    CompanyMaterialPrice,
    Item,
    ItemMarketPrice,
    Project,
    ProjectLaborLine,
    ProjectMaterialPrice,
)
from app.takeoff.pricing import resolve_labor, resolve_material_price
from app.takeoff.totals import countable_items

# The resolvers' own source labels, mapped to the basis vocabulary.
# `None` means the number came from this job and nothing was assumed, so
# no assumption is written -- an empty disclosure is worse than none,
# because a reader counts the lines.
MATERIAL_BASIS: dict[str | None, str | None] = {
    "Supplier quote": "supplier_quote",
    "Project price": None,      # an estimator typed it for this job
    "Allowance": None,          # an estimator decided it for this job
    "Company price": "firm_default",
    "Market estimate": "market_estimate",
    "Regional baseline": "class_average",
    None: None,                 # nothing priced it; the line is unpriced
}

LABOR_BASIS: dict[str | None, str | None] = {
    "Estimator entered": None,
    "Company standard": "firm_default",
    "Company crew rate": "firm_default",
    "Estimated basis": "class_average",
    None: None,
}

# Bases that get one grouped line naming the count rather than one line
# per item.
_GROUPED = ("firm_default", "class_average")


def _loaded(db: DbSession, project: Project, exclude: set[uuid.UUID] | None):
    """Every countable item with its four resolver inputs, loaded in a
    fixed number of queries.

    Mirrors `pricing_router.get_labor` and `get_material_pricing`'s own
    loading, with one difference: the org comes from the project, not
    from a signed-in user. This runs in the worker, where there is no
    request and no user, and reading the org off the project is also the
    only correct answer -- the firm whose tables price a job is the firm
    that owns it, never whoever happened to trigger the run.
    """
    items = [i for i in db.scalars(countable_items(project.id)) if not (exclude and i.id in exclude)]
    if not items:
        return []

    ids = [i.id for i in items]
    names = {i.name for i in items}

    labor_lines = {r.item_id: r for r in db.scalars(
        select(ProjectLaborLine).where(ProjectLaborLine.item_id.in_(ids))
    )}
    material_overrides = {r.item_id: r for r in db.scalars(
        select(ProjectMaterialPrice).where(ProjectMaterialPrice.item_id.in_(ids))
    )}
    markets = {r.item_id: r for r in db.scalars(
        select(ItemMarketPrice).where(ItemMarketPrice.item_id.in_(ids))
    )}
    company_rates = db.get(CompanyLaborRate, project.org_id)
    company_hours = {r.item_name: r for r in db.scalars(
        select(CompanyLaborHoursOverride).where(
            CompanyLaborHoursOverride.org_id == project.org_id,
            CompanyLaborHoursOverride.item_name.in_(names),
        )
    )}
    company_prices = {r.item_name: r for r in db.scalars(
        select(CompanyMaterialPrice).where(
            CompanyMaterialPrice.org_id == project.org_id,
            CompanyMaterialPrice.item_name.in_(names),
        )
    )}

    loaded = []
    for item in items:
        labor = resolve_labor(
            item, project, labor_lines.get(item.id),
            company_rates=company_rates, company_hours=company_hours.get(item.name),
        )
        material = resolve_material_price(
            item, project, material_overrides.get(item.id),
            company_prices.get(item.name), market=markets.get(item.id),
        )
        loaded.append((item, labor, material))
    return loaded


def _grouped_line(template: dict, *, section: str, basis: str, items: list[Item],
                  value: str | None = None, unit: str | None = None) -> dict:
    """One assumption standing for every item that shares a basis.

    The count goes in `found` rather than being left for the reader to
    infer: "forty-two receptacles" and "one receptacle" are different
    disclosures, and a line that does not say which is a line that
    cannot be checked.
    """
    return {
        "section": section,
        "subject_kind": "project",
        "basis": basis,
        "title": template["title"],
        "found": template["found"].format(items=copy.plural(len(items), "line")),
        "why": template["why"],
        "where": template["where"],
        "value": value,
        "unit": unit,
        "source": "engine",
    }


def labor_assumptions(db: DbSession, project: Project, *,
                      exclude: set[uuid.UUID] | None = None) -> list[dict]:
    """The hours and the rate, each disclosed once if it was assumed.

    Two lines at most, by design. Every labor dollar on the document is
    hours times a rate, so those are the two numbers a reader needs to
    interrogate; a per-item breakdown would bury both.
    """
    loaded = _loaded(db, project, exclude)
    if not loaded:
        return []

    hours_groups: dict[str, list[Item]] = {}
    rate_groups: dict[str, list[Item]] = {}
    for item, labor, _ in loaded:
        # An unresolved line assumed nothing -- there is no number to
        # disclose, and Task 8 renders it as not priced instead.
        if labor.labor_cost is None:
            continue
        hours_basis = LABOR_BASIS.get(labor.hours_source_label)
        if hours_basis:
            hours_groups.setdefault(hours_basis, []).append(item)
        rate_basis = LABOR_BASIS.get(labor.rate_source_label)
        if rate_basis:
            rate_groups.setdefault(rate_basis, []).append(item)

    rows = []
    for basis, items in sorted(hours_groups.items()):
        template = copy.FIRM_HOURS if basis == "firm_default" else copy.ESTIMATED_HOURS
        rows.append(_grouped_line(template, section="labor", basis=basis, items=items))
    for basis, items in sorted(rate_groups.items()):
        template = copy.FIRM_RATE if basis == "firm_default" else copy.ESTIMATED_RATE
        rows.append(_grouped_line(template, section="labor", basis=basis, items=items))
    return rows


def material_assumptions(db: DbSession, project: Project, *,
                         exclude: set[uuid.UUID] | None = None) -> list[dict]:
    """Prices that did not come from this job.

    Firm-price-list lines are grouped; class averages are named one by
    one. See the module docstring for why the grouping is not uniform.
    """
    loaded = _loaded(db, project, exclude)
    if not loaded:
        return []

    firm_priced: list[Item] = []
    rows = []
    for item, _, material in loaded:
        basis = MATERIAL_BASIS.get(material.source_label)
        if basis == "firm_default":
            firm_priced.append(item)
        elif basis == "class_average":
            rows.append({
                "section": "material",
                "subject_kind": "item",
                "subject_id": item.id,
                "basis": "class_average",
                "title": copy.CLASS_AVERAGE["title"].format(name=item.name),
                "found": copy.CLASS_AVERAGE["found"],
                "why": copy.CLASS_AVERAGE["why"],
                "where": copy.CLASS_AVERAGE["where"].format(name=item.name),
                "value": copy.dollars(item.material_cost) or None,
                "source": "engine",
            })

    if firm_priced:
        rows.insert(0, _grouped_line(copy.FIRM_PRICE, section="material",
                                     basis="firm_default", items=firm_priced))
    return rows


def cost_exposures(db: DbSession, project: Project, *,
                   exclude: set[uuid.UUID] | None = None) -> list[Exposure]:
    """Dollars resting on each basis, for the budget range.

    Separate from the assumption rows on purpose: a market estimate is a
    counted line that still widens the range, and a quoted price is a
    counted line that does not. Collapsing the two outputs into one
    would force a choice between disclosing a quote as an assumption or
    pricing a market estimate as if it were quoted.

    Labor and material dollars are reported separately even when they
    sit on the same item, because they rest on different bases -- the
    hours can come from the firm's table while the material came from a
    supplier's quote.
    """
    loaded = _loaded(db, project, exclude)
    if not loaded:
        return []

    buckets: dict[str, Decimal] = {}
    for item, labor, material in loaded:
        material_basis = MATERIAL_BASIS.get(material.source_label)
        if material_basis:
            buckets[material_basis] = buckets.get(material_basis, Decimal("0")) + item.material_cost
        labor_basis = LABOR_BASIS.get(labor.rate_source_label) or LABOR_BASIS.get(labor.hours_source_label)
        if labor_basis and labor.labor_cost is not None:
            buckets[labor_basis] = buckets.get(labor_basis, Decimal("0")) + item.labor_cost
    return [Exposure(basis, dollars) for basis, dollars in sorted(buckets.items()) if dollars > 0]
