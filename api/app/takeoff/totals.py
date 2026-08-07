import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import Item, ReviewStatus, Sheet


@dataclass
class TotalsResult:
    by_system: dict[str, Decimal] = field(default_factory=dict)
    approved_count: int = 0
    remaining_count: int = 0
    attention_count: int = 0
    missing_count: int = 0
    approved_units: Decimal = Decimal("0")


def _countable(project_id: uuid.UUID):
    """Every consumer of totals starts here.

    Superseded sheets and rejected items are excluded inside this clause
    rather than by callers remembering to filter.
    """
    return (
        select(Item)
        .join(Sheet, Sheet.id == Item.sheet_id)
        .where(Item.project_id == project_id, Sheet.superseded_at.is_(None), Item.rejected_at.is_(None))
    )


def approved_totals(db: DbSession, project_id: uuid.UUID) -> TotalsResult:
    rows = db.execute(
        _countable(project_id)
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
