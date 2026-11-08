import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import (
    CompanyMaterialPrice,
    Item,
    ItemMarketPrice,
    Project,
    ProjectMaterialPrice,
    ReviewStatus,
    Sheet,
)

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


@dataclass
class RomTotals:
    """The ROM's item-level arithmetic.

    `cost_by_system` is DOLLARS, deliberately not sharing the name
    `TotalsResult.by_system` carries for a sum of *quantities*. One
    module holding two dicts called `by_system` that mean different
    things is a mistake waiting for a caller, and the ROM document shows
    money by system while the review drawer shows units.

    Deliberately holds no counted/assumed tally. Origin is a property of
    the assumption records, not of an item, and `app.estimate.assemble`
    is where those are already in hand -- keeping that out of here is
    what lets this stay a pure aggregation over `countable_items()`.
    """

    cost_by_system: dict[str, Decimal] = field(default_factory=dict)
    material_cost: Decimal = Decimal("0")
    labor_cost: Decimal = Decimal("0")
    labor_hours: Decimal = Decimal("0")
    direct_cost: Decimal = Decimal("0")
    item_count: int = 0
    unpriced_count: int = 0


def _has_a_price():
    """True where something priced this item, at any amount including zero.

    The three sources `pricing.resolve_material_price` resolves through,
    asked as existence rather than as a value -- because the question is
    not "what does it cost" but "did anything decide". An estimator's
    allowance of nothing, or work logged as by others, is a price
    somebody chose; printing "not priced" over it would be the opposite
    of the truth, and the ROM renders those two states differently.
    """
    return (
        exists().where(ProjectMaterialPrice.item_id == Item.id)
        | exists().where(
            (ItemMarketPrice.item_id == Item.id) & (ItemMarketPrice.outcome == "priced")
        )
        | exists().where(
            (CompanyMaterialPrice.org_id == Project.org_id)
            & (CompanyMaterialPrice.item_name == Item.name)
        )
    )


def rom_totals(
    db: DbSession,
    project_id: uuid.UUID,
    *,
    exclude: set[uuid.UUID] | None = None,
) -> RomTotals:
    """Every countable item, whatever its review status.

    No status filter, by design: a ROM is produced the moment processing
    finishes, before anybody has approved anything, and an estimate that
    only counted approved work would read as zero on a fresh project.
    The document says on its face that nothing in it is approved.

    `exclude` is how scope exclusions leave the number
    (`app.estimate.exclusions`). It is a keyword from the first commit
    rather than a later addition so there is never a second query that
    re-implements the exclusion with its own filters -- ROADMAP
    invariant 1.
    """
    query = countable_items(project_id).join(Project, Project.id == Item.project_id)
    if exclude:
        query = query.where(Item.id.not_in(exclude))

    rows = db.execute(
        query.with_only_columns(
            Item.system,
            func.sum(Item.material_cost),
            func.sum(Item.labor_cost),
            func.sum(Item.labor_hours),
            func.sum(Item.total_cost),
            func.count(),
            func.count().filter((Item.total_cost == 0) & ~_has_a_price()),
        ).group_by(Item.system)
    ).all()

    result = RomTotals()
    for system, material, labor, hours, total, count, unpriced in rows:
        result.cost_by_system[system] = result.cost_by_system.get(system, Decimal("0")) + total
        result.material_cost += material
        result.labor_cost += labor
        result.labor_hours += hours
        result.direct_cost += total
        result.item_count += count
        result.unpriced_count += unpriced
    return result
