"""PATCH /api/items/{item_id}/labor and /material-price -- the two
project-level override mutations -- plus the five company-scoped pricing
mutations and their audit log (CompanyAction)."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import InternalError, ProgrammingError

from app.takeoff.models import Action, ProjectLaborLine, ProjectMaterialPrice


def test_patch_labor_creates_a_row_and_commits_an_action(client, db, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    assert response.status_code == 200, response.text
    row = db.get(ProjectLaborLine, item.id)
    assert row is not None and float(row.hours_override) == 0.75
    action = db.scalars(select(Action).where(Action.kind == "labor_edit", Action.item_id == item.id)).one()
    assert action.actor_user_id == signed_in_user.id


def test_patch_labor_merges_onto_an_existing_row(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/labor", json={"crewJourneyman": 1})
    client.patch(f"/api/items/{item.id}/labor", json={"crewForeman": 1})
    row = db.get(ProjectLaborLine, item.id)
    assert row.crew_journeyman == 1 and row.crew_foreman == 1


def test_patch_labor_requires_at_least_one_field(client, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/labor", json={})
    assert response.status_code >= 400


def test_patch_material_price_creates_a_row(client, db, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/material-price",
                             json={"priceOverride": 15.5, "source": "project_price"})
    assert response.status_code == 200, response.text
    row = db.get(ProjectMaterialPrice, item.id)
    assert row is not None and float(row.price_override) == 15.5 and row.source == "project_price"


def test_patch_material_price_allowance_requires_a_reason(client, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/material-price",
                             json={"priceOverride": 15.5, "source": "allowance"})
    assert response.status_code >= 400


def test_patch_material_price_allowance_with_reason_succeeds(client, db, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/material-price",
                             json={"priceOverride": 15.5, "source": "allowance", "reason": "no vendor quote yet"})
    assert response.status_code == 200, response.text
    row = db.get(ProjectMaterialPrice, item.id)
    assert row.source == "allowance" and row.reason == "no vendor quote yet"


def test_a_company_rate_change_is_recorded(client, db, org, signed_in_user):
    """Attribution on the row says who touched it last; it cannot say what
    the rate was before, or that it changed twice. A pricing change moves
    every total on every project in the org, which is the kind of change an
    audit asks about."""
    from app.takeoff.models import CompanyAction

    client.put("/api/company/labor-rates", json={
        "journeymanRate": 68, "foremanRate": 82, "apprenticeRate": 41, "productivityFactor": 1.0})
    client.put("/api/company/labor-rates", json={
        "journeymanRate": 72, "foremanRate": 82, "apprenticeRate": 41, "productivityFactor": 1.0})

    rows = db.query(CompanyAction).filter(CompanyAction.org_id == org.id).order_by(CompanyAction.seq).all()
    assert len(rows) == 2
    assert rows[1].before["journeyman_rate"] == "68.00"
    assert rows[1].after["journeyman_rate"] == "72.00"
    assert rows[1].actor_user_id == signed_in_user.id


def test_patch_labor_404s_for_another_orgs_item(client, other_org_project, db, signed_in_user):
    from app.takeoff.models import Item, ReviewStatus, Sheet

    sheet = Sheet(project_id=other_org_project.id, number="E1.1", title="t", discipline="Electrical",
                  revision="", scale="", scale_options=[], plan="")
    db.add(sheet)
    db.flush()
    other_item = Item(project_id=other_org_project.id, sheet_id=sheet.id, symbol="receptacle",
                       name="Receptacle", system="Power", category="Devices", quantity=1,
                       unit="EA", status=ReviewStatus.READY)
    db.add(other_item)
    db.commit()

    response = client.patch(f"/api/items/{other_item.id}/labor", json={"hoursOverride": 1})
    assert response.status_code == 404


def test_get_labor_lists_every_countable_item(client, db, project, item, signed_in_user):
    response = client.get(f"/api/projects/{project.id}/labor")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pricing_source"] is None
    ids = [row["item_id"] for row in body["rows"]]
    assert str(item.id) in ids


def test_get_labor_row_missing_without_llm_pricing(client, project, item, signed_in_user):
    response = client.get(f"/api/projects/{project.id}/labor")
    row = next(r for r in response.json()["rows"] if r["item_id"] == str(item.id))
    assert row["status"] == "missing"


def test_get_labor_row_ready_when_project_priced_by_llm(client, db, project, item, signed_in_user):
    from decimal import Decimal

    project.pricing_source = "llm"
    # The engine-computed baselines `resolve_labor` reads for "Estimated
    # basis" are item.labor_hours (for hours) and item.labor_cost (for
    # the rate) -- the shared `item` fixture leaves both at their column
    # default of 0, which is falsy and would otherwise skip straight past
    # the llm branch into "missing" regardless of project.pricing_source.
    # Both are set here rather than on the shared fixture, since most
    # other tests using `item` don't want a labor baseline at all. A cost
    # with no hours behind it is what a $0/hr "Estimated basis" rate is
    # made of, which _resolve_rate now refuses to produce.
    item.labor_hours = Decimal("5")
    item.labor_cost = Decimal("390")
    db.commit()
    response = client.get(f"/api/projects/{project.id}/labor")
    row = next(r for r in response.json()["rows"] if r["item_id"] == str(item.id))
    assert row["status"] == "ready"
    assert row["hours_source_label"] == "Estimated basis"
    assert float(row["rate"]) == 78.0  # 390 / 5, never 0


def test_get_material_pricing_lists_every_countable_item(client, project, item, signed_in_user):
    response = client.get(f"/api/projects/{project.id}/material-pricing")
    assert response.status_code == 200, response.text
    ids = [row["item_id"] for row in response.json()["rows"]]
    assert str(item.id) in ids


def test_get_material_pricing_uses_company_price_when_present(client, db, org, project, item, signed_in_user):
    from app.takeoff.models import CompanyMaterialPrice

    db.add(CompanyMaterialPrice(org_id=org.id, item_name=item.name, unit_price=99, effective_date="2026-08-01"))
    db.commit()
    response = client.get(f"/api/projects/{project.id}/material-pricing")
    row = next(r for r in response.json()["rows"] if r["item_id"] == str(item.id))
    assert row["source_label"] == "Company price"
    assert float(row["unit_price"]) == 99.0


def test_get_material_pricing_round_trips_the_allowance_reason(client, project, item, signed_in_user):
    # Without this, a client that reloads has no way to know a row is an
    # existing allowance -- a follow-up price-only edit would silently
    # revert it to a plain project price and erase why the number was a
    # placeholder.
    client.patch(f"/api/items/{item.id}/material-price",
                 json={"priceOverride": 15.5, "source": "allowance", "reason": "no vendor quote yet"})
    response = client.get(f"/api/projects/{project.id}/material-pricing")
    row = next(r for r in response.json()["rows"] if r["item_id"] == str(item.id))
    assert row["source"] == "allowance"
    assert row["reason"] == "no vendor quote yet"


def test_get_material_pricing_source_is_none_with_no_override(client, project, item, signed_in_user):
    response = client.get(f"/api/projects/{project.id}/material-pricing")
    row = next(r for r in response.json()["rows"] if r["item_id"] == str(item.id))
    assert row["source"] is None
    assert row["reason"] == ""


def test_get_company_labor_rates_defaults_to_zero(client, signed_in_user):
    response = client.get("/api/company/labor-rates")
    assert response.status_code == 200, response.text
    assert response.json()["journeyman_rate"] == "0.00" or float(response.json()["journeyman_rate"]) == 0.0


def test_put_company_labor_rates_persists(client, db, org, signed_in_user):
    response = client.put("/api/company/labor-rates", json={
        "journeymanRate": 68, "foremanRate": 82, "apprenticeRate": 41, "productivityFactor": 0.97,
    })
    assert response.status_code == 200, response.text
    from app.takeoff.models import CompanyLaborRate
    row = db.get(CompanyLaborRate, org.id)
    assert float(row.journeyman_rate) == 68.0


def test_put_company_material_price_creates_and_updates(client, db, org, signed_in_user):
    response = client.put("/api/company/material-prices/20A%20duplex%20receptacle",
                           json={"unitPrice": 13.5, "effectiveDate": "2026-08-01"})
    assert response.status_code == 200, response.text
    response2 = client.put("/api/company/material-prices/20A%20duplex%20receptacle",
                            json={"unitPrice": 14.0, "effectiveDate": "2026-08-15"})
    assert response2.status_code == 200
    from app.takeoff.models import CompanyMaterialPrice
    row = db.scalars(select(CompanyMaterialPrice).where(
        CompanyMaterialPrice.org_id == org.id, CompanyMaterialPrice.item_name == "20A duplex receptacle",
    )).one()
    assert float(row.unit_price) == 14.0


def test_delete_company_material_price(client, db, org, signed_in_user):
    client.put("/api/company/material-prices/20A%20duplex%20receptacle",
               json={"unitPrice": 13.5, "effectiveDate": "2026-08-01"})
    response = client.delete("/api/company/material-prices/20A%20duplex%20receptacle")
    assert response.status_code == 204
    from app.takeoff.models import CompanyMaterialPrice
    remaining = db.scalars(select(CompanyMaterialPrice).where(CompanyMaterialPrice.org_id == org.id)).all()
    assert remaining == []


def test_get_company_material_prices_lists_all(client, org, signed_in_user):
    client.put("/api/company/material-prices/20A%20duplex%20receptacle", json={"unitPrice": 13.5, "effectiveDate": "2026-08-01"})
    response = client.get("/api/company/material-prices")
    names = [row["item_name"] for row in response.json()]
    assert "20A duplex receptacle" in names


def test_put_company_labor_hours_override(client, db, org, signed_in_user):
    response = client.put("/api/company/labor-hours-overrides/20A%20duplex%20receptacle",
                           json={"hoursPerUnit": 0.6})
    assert response.status_code == 200, response.text
    from app.takeoff.models import CompanyLaborHoursOverride
    row = db.scalars(select(CompanyLaborHoursOverride).where(
        CompanyLaborHoursOverride.org_id == org.id, CompanyLaborHoursOverride.item_name == "20A duplex receptacle",
    )).one()
    assert float(row.hours_per_unit) == 0.6


def test_patch_labor_rejects_a_negative_rate_or_hours(client, item, signed_in_user):
    """Neither hours nor a rate has a negative reading. A minus sign in a
    number field is a slip, and it would otherwise land in a total."""
    assert client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": -1}).status_code == 422
    assert client.patch(f"/api/items/{item.id}/labor", json={"rateOverride": -68}).status_code == 422


def test_patch_labor_allows_a_negative_adjustment_down_to_minus_100(client, db, item, signed_in_user):
    """A productivity credit is a legitimate negative -- -100% is the
    floor, because that is already zero hours."""
    assert client.patch(f"/api/items/{item.id}/labor", json={"adjustmentPercent": -15}).status_code == 200
    assert float(db.get(ProjectLaborLine, item.id).adjustment_percent) == -15
    assert client.patch(f"/api/items/{item.id}/labor", json={"adjustmentPercent": -101}).status_code == 422


def test_patch_material_price_rejects_a_negative_price(client, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/material-price",
                            json={"priceOverride": -5, "source": "project_price"})
    assert response.status_code == 422


def test_patch_labor_clears_a_text_field_sent_as_null(client, db, item, signed_in_user):
    """adjustment_reason and notes are NOT NULL. An explicit null means
    "clear it," which is the empty string here -- not a 500 on flush."""
    client.patch(f"/api/items/{item.id}/labor", json={"adjustmentReason": "crew unfamiliar with the gear"})
    response = client.patch(f"/api/items/{item.id}/labor", json={"adjustmentReason": None, "notes": None})
    assert response.status_code == 200, response.text
    row = db.get(ProjectLaborLine, item.id)
    db.refresh(row)
    assert row.adjustment_reason == "" and row.notes == ""


def test_company_material_price_change_is_recorded_with_full_precision(client, db, org, signed_in_user):
    """Same precision hazard as the labor-rates route: the "after"
    snapshot must reflect what Postgres actually stored (14.00 for a
    Numeric(10, 2) column), not whatever bare precision the request body
    carried (14) before the row was refreshed."""
    from app.takeoff.models import CompanyAction

    client.put("/api/company/material-prices/20A%20duplex%20receptacle",
               json={"unitPrice": 13.5, "effectiveDate": "2026-08-01"})
    client.put("/api/company/material-prices/20A%20duplex%20receptacle",
               json={"unitPrice": 14, "effectiveDate": "2026-08-15"})

    rows = db.query(CompanyAction).filter(
        CompanyAction.org_id == org.id, CompanyAction.kind == "company_material_price_edit",
    ).order_by(CompanyAction.seq).all()
    assert len(rows) == 2
    assert rows[1].before["unit_price"] == "13.50"
    assert rows[1].after["unit_price"] == "14.00"
    assert rows[1].actor_user_id == signed_in_user.id


def test_deleting_a_company_material_price_records_before_with_empty_after(client, db, org, signed_in_user):
    from app.takeoff.models import CompanyAction

    client.put("/api/company/material-prices/20A%20duplex%20receptacle",
               json={"unitPrice": 13.5, "effectiveDate": "2026-08-01"})
    response = client.delete("/api/company/material-prices/20A%20duplex%20receptacle")
    assert response.status_code == 204

    rows = db.query(CompanyAction).filter(
        CompanyAction.org_id == org.id, CompanyAction.kind == "company_material_price_delete",
    ).all()
    assert len(rows) == 1
    assert rows[0].before["unit_price"] == "13.50"
    assert rows[0].after == {}


def test_deleting_a_nonexistent_company_material_price_records_nothing(client, db, org, signed_in_user):
    """A DELETE against a row that never existed is a no-op today (the
    route silently succeeds with 204). It must not manufacture an audit
    row for a change that never happened."""
    from app.takeoff.models import CompanyAction

    response = client.delete("/api/company/material-prices/never-priced")
    assert response.status_code == 204
    rows = db.query(CompanyAction).filter(CompanyAction.org_id == org.id).all()
    assert rows == []


def test_company_labor_hours_override_change_is_recorded_with_full_precision(client, db, org, signed_in_user):
    """Same precision hazard, on the Numeric(8, 3) hours_per_unit
    column: a bare `1` in the request body must be recorded as the
    persisted "1.000", not "1"."""
    from app.takeoff.models import CompanyAction

    client.put("/api/company/labor-hours-overrides/20A%20duplex%20receptacle", json={"hoursPerUnit": 0.6})
    client.put("/api/company/labor-hours-overrides/20A%20duplex%20receptacle", json={"hoursPerUnit": 1})

    rows = db.query(CompanyAction).filter(
        CompanyAction.org_id == org.id, CompanyAction.kind == "company_labor_hours_override_edit",
    ).order_by(CompanyAction.seq).all()
    assert len(rows) == 2
    assert rows[1].before["hours_per_unit"] == "0.600"
    assert rows[1].after["hours_per_unit"] == "1.000"
    assert rows[1].actor_user_id == signed_in_user.id


def test_deleting_a_company_labor_hours_override_records_before_with_empty_after(client, db, org, signed_in_user):
    from app.takeoff.models import CompanyAction

    client.put("/api/company/labor-hours-overrides/20A%20duplex%20receptacle", json={"hoursPerUnit": 0.6})
    response = client.delete("/api/company/labor-hours-overrides/20A%20duplex%20receptacle")
    assert response.status_code == 204

    rows = db.query(CompanyAction).filter(
        CompanyAction.org_id == org.id, CompanyAction.kind == "company_labor_hours_override_delete",
    ).all()
    assert len(rows) == 1
    assert rows[0].before["hours_per_unit"] == "0.600"
    assert rows[0].after == {}


def test_deleting_a_nonexistent_company_labor_hours_override_records_nothing(client, db, org, signed_in_user):
    from app.takeoff.models import CompanyAction

    response = client.delete("/api/company/labor-hours-overrides/never-overridden")
    assert response.status_code == 204
    rows = db.query(CompanyAction).filter(CompanyAction.org_id == org.id).all()
    assert rows == []


def test_the_database_refuses_to_update_a_company_action(db, org, dana):
    """Mirrors test_action_log.py's guard tests for `actions`, against
    `company_actions` -- the append-only claim in CompanyAction's
    docstring is only true if the database enforces it too."""
    from app.takeoff.models import CompanyAction

    action = CompanyAction(org_id=org.id, actor_user_id=dana.id, kind="company_labor_rates_edit",
                            label="Changed labor rates", before={}, after={})
    db.add(action)
    db.flush()

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("update company_actions set label = 'rewritten' where id = :id"), {"id": action.id})


def test_the_database_refuses_to_delete_a_company_action(db, org, dana):
    from app.takeoff.models import CompanyAction

    action = CompanyAction(org_id=org.id, actor_user_id=dana.id, kind="company_labor_rates_edit",
                            label="Changed labor rates", before={}, after={})
    db.add(action)
    db.flush()

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("delete from company_actions where id = :id"), {"id": action.id})


def test_the_database_refuses_to_truncate_company_actions(db, org, dana):
    from app.takeoff.models import CompanyAction

    action = CompanyAction(org_id=org.id, actor_user_id=dana.id, kind="company_labor_rates_edit",
                            label="Changed labor rates", before={}, after={})
    db.add(action)
    db.flush()

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("truncate company_actions"))


def test_the_company_action_guard_survives_session_replication_role_replica(db, org, dana):
    """ORIGIN triggers stop firing under session_replication_role =
    replica; the guard was created ENABLE ALWAYS specifically so this
    doesn't open a bypass -- see test_action_log.py's equivalent test for
    `actions`. SET LOCAL so the setting is scoped to this transaction and
    undone automatically when the fixture rolls back."""
    from app.takeoff.models import CompanyAction

    action = CompanyAction(org_id=org.id, actor_user_id=dana.id, kind="company_labor_rates_edit",
                            label="Changed labor rates", before={}, after={})
    db.add(action)
    db.flush()
    db.execute(text("set local session_replication_role = replica"))

    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("update company_actions set label = 'rewritten' where id = :id"), {"id": action.id})
