# api/app/schedule/defaults.py
"""The firm's starting tables (phases-and-timeline.md §3.3-§3.4),
inserted once per org on first use -- never by the migration, because an
org created afterwards needs them too. A row that exists is left alone,
firm-edited or not: the seed fills gaps and never overwrites.

Every number here is 'the default' in the product's words -- not
'recommended', not 'industry standard'. The screen says so until a
row is firm_edited."""
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.schedule.stages import STAGES
from app.takeoff.models import (
    CompanyLeadTime, CompanyPhaseLineTemplate, CompanyScheduleSettings, CompanyStageCrew, CompanyStageSplit,
)

# category_label -> (demolition, rough_in, wire_pull, gear, trim, closeout)
SPLIT_SEED: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("Devices", (0, 45, 25, 0, 25, 5)),
    ("Power", (0, 45, 25, 0, 25, 5)),
    ("Lighting", (0, 25, 15, 0, 55, 5)),
    ("Fixtures", (0, 25, 15, 0, 55, 5)),
    ("Distribution", (0, 20, 10, 60, 5, 5)),
    ("Equipment", (0, 20, 10, 60, 5, 5)),
    ("Low voltage", (0, 35, 35, 0, 25, 5)),
    ("Boxes", (0, 90, 0, 0, 5, 5)),
    ("Demolition", (100, 0, 0, 0, 0, 0)),
    ("*", (0, 0, 0, 0, 95, 5)),
)

# stage -> (foreman, journeyman, apprentice)
CREW_SEED: dict[str, tuple[int, int, int]] = {
    "demolition": (0, 1, 1),
    "rough_in": (1, 2, 2),
    "wire_pull": (1, 2, 2),
    "gear": (1, 2, 0),
    "trim": (0, 2, 2),
    "closeout": (0, 1, 1),
}

TEMPLATE_SEED: tuple[tuple[str, str], ...] = (
    ("Final and daily cleanup", "3"),
    ("Project planning, coordination and layout", "4"),
)

FALLBACK_KEY = "*"


def category_key(label: str) -> str:
    return (label or "").strip().casefold() or FALLBACK_KEY


@dataclass
class CompanyTables:
    splits: dict[str, CompanyStageSplit] = field(default_factory=dict)
    crews: dict[str, CompanyStageCrew] = field(default_factory=dict)
    settings: CompanyScheduleSettings | None = None
    templates: list[CompanyPhaseLineTemplate] = field(default_factory=list)
    lead_times: dict[str, CompanyLeadTime] = field(default_factory=dict)


def ensure_defaults(db: DbSession, org_id: uuid.UUID) -> None:
    have = {s.category_key for s in db.scalars(select(CompanyStageSplit).where(CompanyStageSplit.org_id == org_id))}
    for label, pct in SPLIT_SEED:
        key = category_key(label)
        if key not in have:
            d, r, w, g, t, c = (Decimal(p) for p in pct)
            db.add(CompanyStageSplit(org_id=org_id, category_key=key, category_label=label,
                                     demolition=d, rough_in=r, wire_pull=w, gear=g, trim=t, closeout=c))
    have = {c.stage for c in db.scalars(select(CompanyStageCrew).where(CompanyStageCrew.org_id == org_id))}
    for stage in STAGES:
        if stage not in have:
            f, j, a = CREW_SEED[stage]
            db.add(CompanyStageCrew(org_id=org_id, stage=stage, foreman=f, journeyman=j, apprentice=a))
    if db.get(CompanyScheduleSettings, org_id) is None:
        db.add(CompanyScheduleSettings(org_id=org_id))
    if not db.scalars(select(CompanyPhaseLineTemplate).where(CompanyPhaseLineTemplate.org_id == org_id)).first():
        for order, (label, pct) in enumerate(TEMPLATE_SEED):
            db.add(CompanyPhaseLineTemplate(org_id=org_id, label=label, percent_of_direct_hours=Decimal(pct), sort_order=order))
    db.flush()


def load_company(db: DbSession, org_id: uuid.UUID) -> CompanyTables:
    ensure_defaults(db, org_id)
    return CompanyTables(
        splits={s.category_key: s for s in db.scalars(select(CompanyStageSplit).where(CompanyStageSplit.org_id == org_id))},
        crews={c.stage: c for c in db.scalars(select(CompanyStageCrew).where(CompanyStageCrew.org_id == org_id))},
        settings=db.get(CompanyScheduleSettings, org_id),
        templates=list(db.scalars(select(CompanyPhaseLineTemplate).where(CompanyPhaseLineTemplate.org_id == org_id).order_by(CompanyPhaseLineTemplate.sort_order))),
        lead_times={l.item_class: l for l in db.scalars(select(CompanyLeadTime).where(CompanyLeadTime.org_id == org_id))},
    )
