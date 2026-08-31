"""Precedence resolution for Labor and Material Pricing -- pure
functions, no database. Each tier is tested in isolation and confirmed
to be correctly skipped when a higher tier is present.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.takeoff.pricing import (
    STALE_PRICE_DAYS,
    resolve_labor,
    resolve_material_price,
)


class FakeItem:
    def __init__(self, name="20A duplex receptacle", quantity=Decimal("10"),
                 material_cost=Decimal("120"), labor_hours=Decimal("5"), labor_cost=Decimal("390")):
        self.name = name
        self.quantity = quantity
        self.material_cost = material_cost
        self.labor_hours = labor_hours
        self.labor_cost = labor_cost


class FakeProject:
    def __init__(self, pricing_source="llm", pricing_note="Rate based on Sacramento, CA area cost data."):
        self.pricing_source = pricing_source
        self.pricing_note = pricing_note


# ---- Material price ----

def test_material_price_project_override_wins_over_everything():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"price_override": Decimal("15"), "source": "project_price"})()
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": date.today()})()
    result = resolve_material_price(item, project, override, company)
    assert result.unit_price == Decimal("15")
    assert result.source_label == "Project price"


def test_material_price_allowance_label():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"price_override": Decimal("20"), "source": "allowance"})()
    result = resolve_material_price(item, project, override, None)
    assert result.unit_price == Decimal("20")
    assert result.source_label == "Allowance"


def test_material_price_company_price_wins_over_regional():
    item, project = FakeItem(), FakeProject()
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": date.today()})()
    result = resolve_material_price(item, project, None, company)
    assert result.unit_price == Decimal("13")
    assert result.source_label == "Company price"


def test_material_price_company_price_stale_after_180_days():
    item, project = FakeItem(), FakeProject()
    old = date.today() - timedelta(days=STALE_PRICE_DAYS + 1)
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": old})()
    result = resolve_material_price(item, project, None, company)
    assert result.status == "attention"


def test_material_price_company_price_not_stale_at_179_days():
    item, project = FakeItem(), FakeProject()
    recent = date.today() - timedelta(days=STALE_PRICE_DAYS - 1)
    company = type("C", (), {"unit_price": Decimal("13"), "effective_date": recent})()
    result = resolve_material_price(item, project, None, company)
    assert result.status == "ready"


def test_material_price_regional_baseline_only_when_llm_priced():
    item = FakeItem(material_cost=Decimal("120"), quantity=Decimal("10"))
    project = FakeProject(pricing_source="llm")
    result = resolve_material_price(item, project, None, None)
    assert result.unit_price == Decimal("12")
    assert result.source_label == "Regional baseline"
    assert result.status == "ready"


def test_material_price_missing_when_deterministically_priced():
    item = FakeItem(material_cost=Decimal("120"), quantity=Decimal("10"))
    project = FakeProject(pricing_source="deterministic")
    result = resolve_material_price(item, project, None, None)
    assert result.unit_price is None
    assert result.status == "missing"


def test_material_price_missing_when_pricing_source_is_none():
    item = FakeItem()
    project = FakeProject(pricing_source=None)
    result = resolve_material_price(item, project, None, None)
    assert result.status == "missing"


def test_material_price_missing_when_quantity_is_zero():
    item = FakeItem(quantity=Decimal("0"))
    project = FakeProject(pricing_source="llm")
    result = resolve_material_price(item, project, None, None)
    assert result.status == "missing"


# ---- Labor ----

def test_labor_hours_estimator_override_wins():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"hours_override": Decimal("0.75"), "crew_journeyman": None,
                               "crew_foreman": None, "crew_apprentice": None,
                               "rate_override": None, "adjustment_percent": None})()
    result = resolve_labor(item, project, override, company_rates=None, company_hours=None)
    assert result.hours_per_unit == Decimal("0.75")
    assert result.hours_source_label == "Estimator entered"


def test_labor_hours_company_standard_wins_over_baseline():
    item, project = FakeItem(), FakeProject()
    company_hours = type("H", (), {"hours_per_unit": Decimal("0.6")})()
    result = resolve_labor(item, project, None, company_rates=None, company_hours=company_hours)
    assert result.hours_per_unit == Decimal("0.6")
    assert result.hours_source_label == "Company standard"


def test_labor_hours_estimated_basis_only_when_llm_priced():
    item = FakeItem(labor_hours=Decimal("5"), quantity=Decimal("10"))
    project = FakeProject(pricing_source="llm")
    result = resolve_labor(item, project, None, company_rates=None, company_hours=None)
    assert result.hours_per_unit == Decimal("0.5")
    assert result.hours_source_label == "Estimated basis"


def test_labor_hours_missing_when_deterministically_priced():
    item = FakeItem(labor_hours=Decimal("5"), quantity=Decimal("10"))
    project = FakeProject(pricing_source="deterministic")
    result = resolve_labor(item, project, None, company_rates=None, company_hours=None)
    assert result.status == "missing"


def test_labor_rate_estimator_override_wins():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"hours_override": None, "rate_override": Decimal("90"),
                               "crew_journeyman": 1, "crew_foreman": None, "crew_apprentice": None,
                               "adjustment_percent": None})()
    company_rates = type("R", (), {"journeyman_rate": Decimal("68"), "foreman_rate": Decimal("82"),
                                    "apprentice_rate": Decimal("41"), "productivity_factor": Decimal("1")})()
    result = resolve_labor(item, project, override, company_rates=company_rates, company_hours=None)
    assert result.rate == Decimal("90")
    assert result.rate_source_label == "Estimator entered"


def test_labor_rate_crew_mix_blended_average():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"hours_override": None, "rate_override": None,
                               "crew_journeyman": 1, "crew_foreman": 0, "crew_apprentice": 1,
                               "adjustment_percent": None})()
    company_rates = type("R", (), {"journeyman_rate": Decimal("68"), "foreman_rate": Decimal("82"),
                                    "apprentice_rate": Decimal("40"), "productivity_factor": Decimal("1")})()
    result = resolve_labor(item, project, override, company_rates=company_rates, company_hours=None)
    assert result.rate == Decimal("54")  # (68 + 40) / 2
    assert result.rate_source_label == "Company crew rate"


def test_labor_rate_falls_back_to_estimated_basis_without_crew_mix():
    item = FakeItem(labor_cost=Decimal("390"), labor_hours=Decimal("5"))
    project = FakeProject(pricing_source="llm")
    result = resolve_labor(item, project, None, company_rates=None, company_hours=None)
    assert result.rate == Decimal("78")  # 390 / 5
    assert result.rate_source_label == "Estimated basis"


@pytest.mark.parametrize("labor_cost", [None, Decimal("0")])
def test_labor_rate_is_absent_not_zero_when_cost_is_missing(labor_cost):
    # Real hours with no cost behind them resolves to nothing at all. A
    # $0/hr rate labelled "Estimated basis" would read as a confirmed
    # figure; the honest answer is that no rate resolved.
    item = FakeItem(labor_hours=Decimal("5"), labor_cost=labor_cost)
    project = FakeProject(pricing_source="llm")
    result = resolve_labor(item, project, None, company_rates=None, company_hours=None)
    assert result.rate is None
    assert result.rate_source_label is None
    assert result.status == "missing"


def test_labor_final_cost_applies_adjustment_and_productivity_factor():
    item = FakeItem(quantity=Decimal("10"), labor_hours=Decimal("5"), labor_cost=Decimal("390"))
    project = FakeProject(pricing_source="llm")
    override = type("O", (), {"hours_override": None, "rate_override": None,
                               "crew_journeyman": None, "crew_foreman": None, "crew_apprentice": None,
                               "adjustment_percent": Decimal("10")})()
    company_rates = type("R", (), {"journeyman_rate": Decimal("0"), "foreman_rate": Decimal("0"),
                                    "apprentice_rate": Decimal("0"), "productivity_factor": Decimal("0.97")})()
    result = resolve_labor(item, project, override, company_rates=company_rates, company_hours=None)
    # base hours/unit = 0.5, * qty 10 = 5, * 1.10 adjustment, * 0.97 productivity
    expected_hours = Decimal("0.5") * Decimal("10") * Decimal("1.10") * Decimal("0.97")
    assert float(result.adjusted_hours) == pytest.approx(float(expected_hours), rel=1e-6)


def test_labor_estimator_approved_status_when_row_has_any_override_field_set():
    item, project = FakeItem(), FakeProject()
    override = type("O", (), {"hours_override": None, "rate_override": None,
                               "crew_journeyman": 1, "crew_foreman": None, "crew_apprentice": None,
                               "adjustment_percent": None})()
    result = resolve_labor(item, project, override, company_rates=None, company_hours=None)
    assert result.status == "approved"
