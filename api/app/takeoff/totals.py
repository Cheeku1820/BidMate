import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import (
    CompanyLaborHoursOverride,
    CompanyLaborRate,
    CompanyMaterialPrice,
    Item,
    ItemMarketPrice,
    Project,
    ProjectLaborLine,
    ProjectMaterialPrice,
    ReviewStatus,
    Sheet,
)
from app.takeoff.pricing import resolve_labor, resolve_material_price

# This module holds TWO aggregations over one exclusion predicate, and
# they are different numbers on purpose.
#
#   approved_totals -- what a person has stood behind. Feeds the review
#   drawer, the takeoff table, screen H, and the Excel export, all of
#   which are the firm's committed position on the job.
#
#   rom_totals -- what the job costs if the drawings are read as they
#   stand, approved or not. Feeds the Estimate summary workspace's
#   rough-order-of-magnitude document, which is handed to a GC for
#   budgeting and carries no approval step at all.
#
# Never present one as the other. A ROM shown where an approved total
# belongs is a number nobody confirmed appearing in a submitted bid --
# the single failure mode this product's status vocabulary exists to
# prevent. What keeps them honest is that both build on
# `countable_items()` below and neither re-states its exclusions.


@dataclass
class TotalsResult:
    by_system: dict[str, Decimal] = field(default_factory=dict)
    approved_count: int = 0
    remaining_count: int = 0
    attention_count: int = 0
    missing_count: int = 0
    approved_units: Decimal = Decimal("0")


def countable_items(project_id):
    """The one exclusion predicate every consumer of item counts starts
    from: not on a superseded sheet, not rejected (ROADMAP.md invariant
    2 -- "superseded sheets never contribute to totals," enforced here
    rather than by callers remembering to filter).

    Public rather than module-private because `projects.py`'s dashboard
    counts (`items_total`, `items_approved`, `warnings_open`,
    `missing_info`) are also "consumers of totals" in exactly the sense
    this docstring means -- ROADMAP.md invariant 1 wants totals computed
    in one place, and a second, hand-copied predicate there is how the
    dashboard and the drawer quietly disagree the day this clause changes.

    `project_id` accepts a column expression (e.g. `Project.id`) as
    readily as a concrete `uuid.UUID` -- SQLAlchemy's `==` builds a
    column-to-column comparison either way -- which is what lets
    `projects.py` call this correlated against the outer `Project` row
    rather than a fixed id.
    """
    return (
        select(Item)
        .join(Sheet, Sheet.id == Item.sheet_id)
        .where(Item.project_id == project_id, Sheet.superseded_at.is_(None), Item.rejected_at.is_(None))
    )


def approved_totals(db: DbSession, project_id: uuid.UUID) -> TotalsResult:
    rows = db.execute(
        countable_items(project_id)
        .with_only_columns(Item.system, Item.status, func.sum(Item.quantity), func.count())
        .group_by(Item.system, Item.status)
    ).all()

    result = TotalsResult()
    for system, status, quantity, count in rows:
        if status is ReviewStatus.APPROVED:
            result.by_system[system] = result.by_system.get(system, Decimal("0")) + quantity
            result.approved_units += quantity
            result.approved_count += count
        else:
            result.remaining_count += count
            if status is ReviewStatus.ATTENTION:
                result.attention_count += count
            elif status is ReviewStatus.MISSING:
                result.missing_count += count
    return result


_CENTS = Decimal("0.01")


def _cents(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass
class ResolvedLine:
    """One countable item with the price the firm's own precedence chain
    actually resolves for it."""

    item: Item
    material_cost: Decimal          # resolved unit price x quantity
    labor_cost: Decimal
    labor_hours: Decimal
    material_basis: str | None      # pricing.MaterialResolution.source_label
    labor_hours_basis: str | None
    labor_rate_basis: str | None

    @property
    def total_cost(self) -> Decimal:
        return self.material_cost + self.labor_cost

    @property
    def priced(self) -> bool:
        """Whether anything priced this line, at any amount including
        zero. An estimator's allowance of nothing is a price somebody
        chose; printing "not priced" over it would be the opposite of
        the truth, and the ROM renders those two states differently."""
        return self.material_basis is not None


def resolved_lines(
    db: DbSession,
    project: Project,
    *,
    exclude: set[uuid.UUID] | None = None,
) -> list[ResolvedLine]:
    """Every countable item, priced through the firm's precedence chain.

    **Why this exists rather than reading `Item.material_cost`.** Those
    columns hold what the engine computed at ingest. The price an
    estimator actually sees on Labor pricing and Material pricing is
    resolved live, every read, through overrides, the firm's tables, and
    the market feed (`app.takeoff.pricing`) -- nothing writes a resolved
    price back onto the item. An aggregation over the stored columns
    therefore reports the engine's first guess and ignores every quote,
    every company price, and every number an estimator typed. A ROM
    built on it shows $140 for a line a supplier quoted at $500.

    Loaded in a fixed number of queries, mirroring
    `pricing_router.get_labor` and `get_material_pricing` -- with one
    difference: the org comes from the project, not from a signed-in
    user. This runs in the worker, where there is no request, and
    reading the org off the project is also the only correct answer:
    the firm whose tables price a job is the firm that owns it, never
    whoever happened to trigger the run.
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

    lines: list[ResolvedLine] = []
    for item in items:
        labor = resolve_labor(
            item, project, labor_lines.get(item.id),
            company_rates=company_rates, company_hours=company_hours.get(item.name),
        )
        material = resolve_material_price(
            item, project, material_overrides.get(item.id),
            company_prices.get(item.name), market=markets.get(item.id),
        )
        unit_price = material.unit_price
        lines.append(ResolvedLine(
            item=item,
            # Quantized to cents. `unit_price * quantity` multiplies two
            # Numerics and lands at four decimal places, which would put
            # "850.0000" on the wire for a document whose every other
            # figure is money.
            material_cost=_cents((unit_price * item.quantity) if unit_price is not None else Decimal("0")),
            labor_cost=_cents(labor.labor_cost if labor.labor_cost is not None else Decimal("0")),
            labor_hours=labor.adjusted_hours if labor.adjusted_hours is not None else Decimal("0"),
            material_basis=material.source_label,
            labor_hours_basis=labor.hours_source_label,
            labor_rate_basis=labor.rate_source_label,
        ))
    return lines


@dataclass
class RomTotals:
    """The ROM's arithmetic, over resolved prices.

    `cost_by_system` is DOLLARS, deliberately not sharing the name
    `TotalsResult.by_system` carries for a sum of *quantities*. One
    module holding two dicts called `by_system` that mean different
    things is a mistake waiting for a caller, and the ROM document shows
    money by system while the review drawer shows units.

    Deliberately holds no counted/assumed tally. Origin is a property of
    the assumption records, not of an item, and `app.estimate.assemble`
    is where those are already in hand.
    """

    cost_by_system: dict[str, Decimal] = field(default_factory=dict)
    material_cost: Decimal = Decimal("0")
    labor_cost: Decimal = Decimal("0")
    labor_hours: Decimal = Decimal("0")
    direct_cost: Decimal = Decimal("0")
    item_count: int = 0
    unpriced_count: int = 0
    # Systems carrying at least one line nothing priced, and how many.
    # A rolled-up system total that silently omits a line is a number
    # that looks complete and is not -- the ROM renders this beside the
    # system it belongs to.
    unpriced_by_system: dict[str, int] = field(default_factory=dict)


def rom_totals(
    db: DbSession,
    project: Project,
    *,
    exclude: set[uuid.UUID] | None = None,
) -> RomTotals:
    """Every countable item at its resolved price, whatever its status.

    No status filter, by design: a ROM is produced the moment processing
    finishes, before anybody has approved anything, and an estimate that
    only counted approved work would read as zero on a fresh project.
    The document says on its face that nothing in it is approved.

    `exclude` is how scope exclusions leave the number
    (`app.estimate.exclusions`), so there is never a second query that
    re-implements the exclusion with its own filters -- ROADMAP
    invariant 1.

    Takes a `Project` rather than a `project_id`: resolution needs the
    org's tables and the project's own pricing basis, and passing the
    row the caller already loaded is better than re-fetching it here.
    """
    result = RomTotals()
    for line in resolved_lines(db, project, exclude=exclude):
        system = line.item.system
        result.cost_by_system[system] = result.cost_by_system.get(system, Decimal("0")) + line.total_cost
        result.material_cost += line.material_cost
        result.labor_cost += line.labor_cost
        result.labor_hours += line.labor_hours
        result.direct_cost += line.total_cost
        result.item_count += 1
        if not line.priced:
            result.unpriced_count += 1
            result.unpriced_by_system[system] = result.unpriced_by_system.get(system, 0) + 1
    return result
