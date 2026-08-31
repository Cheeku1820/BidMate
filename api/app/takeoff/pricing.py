"""Precedence resolution for Labor and Material Pricing (Task 3 of the
labor-material-pricing plan). Pure functions, no database access, so the
resolution logic is testable without Postgres -- the same reasoning
ingest.py's own docstring gives for staying a pure mapper.

Nothing here is pre-computed and stored: both resolve functions run
fresh against whatever the caller already loaded, matching ROADMAP.md
invariant 1 (totals computed in exactly one place).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

# A company price older than this reads as Needs attention ("Stale
# price") rather than Ready to review -- a fixed constant for this plan,
# not a company setting (design doc's Known limitations).
STALE_PRICE_DAYS = 180


@dataclass
class MaterialResolution:
    unit_price: Decimal | None
    source_label: str | None  # "Project price" | "Allowance" | "Company price" | "Regional baseline" | None
    status: str  # "ready" | "attention" | "missing" | "approved"
    basis_note: str = ""


@dataclass
class LaborResolution:
    hours_per_unit: Decimal | None
    hours_source_label: str | None
    rate: Decimal | None
    rate_source_label: str | None
    adjusted_hours: Decimal | None
    labor_cost: Decimal | None
    status: str
    basis_note: str = ""


def resolve_material_price(item, project, override, company_price) -> MaterialResolution:
    """`override` is a ProjectMaterialPrice row or None. `company_price`
    is a CompanyMaterialPrice row (already looked up by item.name by the
    caller) or None."""
    if override is not None:
        label = "Allowance" if override.source == "allowance" else "Project price"
        return MaterialResolution(unit_price=override.price_override, source_label=label, status="approved")

    if company_price is not None:
        stale = (date.today() - company_price.effective_date) > timedelta(days=STALE_PRICE_DAYS)
        status = "attention" if stale else "ready"
        label = "Company price"
        return MaterialResolution(unit_price=company_price.unit_price, source_label=label, status=status)

    if project.pricing_source == "llm" and item.quantity and item.material_cost:
        unit_price = item.material_cost / item.quantity
        return MaterialResolution(
            unit_price=unit_price, source_label="Regional baseline", status="ready",
            basis_note=project.pricing_note,
        )

    return MaterialResolution(unit_price=None, source_label=None, status="missing")


def _labor_override_has_any_field(override) -> bool:
    return any([
        override.hours_override is not None,
        override.rate_override is not None,
        override.crew_journeyman is not None,
        override.crew_foreman is not None,
        override.crew_apprentice is not None,
        override.adjustment_percent is not None,
    ])


def _resolve_hours(item, project, override, company_hours) -> tuple[Decimal | None, str | None]:
    if override is not None and override.hours_override is not None:
        return override.hours_override, "Estimator entered"
    if company_hours is not None:
        return company_hours.hours_per_unit, "Company standard"
    if project.pricing_source == "llm" and item.quantity and item.labor_hours:
        return item.labor_hours / item.quantity, "Estimated basis"
    return None, None


def _resolve_rate(item, project, override, company_rates) -> tuple[Decimal | None, str | None]:
    if override is not None and override.rate_override is not None:
        return override.rate_override, "Estimator entered"

    if override is not None and company_rates is not None:
        roles = [
            (override.crew_journeyman, company_rates.journeyman_rate),
            (override.crew_foreman, company_rates.foreman_rate),
            (override.crew_apprentice, company_rates.apprentice_rate),
        ]
        total_count = sum(count for count, _ in roles if count)
        if total_count:
            weighted = sum(Decimal(count) * rate for count, rate in roles if count)
            return weighted / Decimal(total_count), "Company crew rate"

    if project.pricing_source == "llm" and item.labor_hours:
        return item.labor_cost / item.labor_hours, "Estimated basis"

    return None, None


def resolve_labor(item, project, override, *, company_rates, company_hours) -> LaborResolution:
    """`override` is a ProjectLaborLine row or None. `company_rates` is
    the org's singleton CompanyLaborRate row or None. `company_hours` is
    a CompanyLaborHoursOverride row (already looked up by item.name) or
    None."""
    hours_per_unit, hours_label = _resolve_hours(item, project, override, company_hours)
    rate, rate_label = _resolve_rate(item, project, override, company_rates)

    if hours_per_unit is None or rate is None:
        status = "approved" if (override is not None and _labor_override_has_any_field(override)) else "missing"
        return LaborResolution(
            hours_per_unit=hours_per_unit, hours_source_label=hours_label,
            rate=rate, rate_source_label=rate_label,
            adjusted_hours=None, labor_cost=None, status=status,
        )

    adjustment_percent = override.adjustment_percent if override is not None and override.adjustment_percent is not None else Decimal("0")
    productivity_factor = company_rates.productivity_factor if company_rates is not None else Decimal("1")
    adjusted_hours = hours_per_unit * item.quantity * (1 + adjustment_percent / 100) * productivity_factor
    labor_cost = adjusted_hours * rate

    if override is not None and _labor_override_has_any_field(override):
        status = "approved"
    else:
        status = "ready"

    return LaborResolution(
        hours_per_unit=hours_per_unit, hours_source_label=hours_label,
        rate=rate, rate_source_label=rate_label,
        adjusted_hours=adjusted_hours, labor_cost=labor_cost, status=status,
        basis_note=project.pricing_note if (hours_label == "Estimated basis" or rate_label == "Estimated basis") else "",
    )
