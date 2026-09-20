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
    # Estimator-facing copy (product language rules, CLAUDE.md) -- not a
    # route name or an HTTP verb.
    assert rows[1].label == "Changed labor rates"


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
    # Estimator-facing copy (product language rules, CLAUDE.md) -- not a
    # route name or an HTTP verb.
    assert rows[1].label == "Changed the material price for 20A duplex receptacle"


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
    assert rows[0].label == "Removed the material price for 20A duplex receptacle"


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
    # Estimator-facing copy (product language rules, CLAUDE.md) -- not a
    # route name or an HTTP verb.
    assert rows[1].label == "Changed the labor hours override for 20A duplex receptacle"


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
    assert rows[0].label == "Removed the labor hours override for 20A duplex receptacle"


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


def test_patch_labor_records_the_persisted_precision_not_the_request_bodys(client, db, item, signed_in_user):
    """Same hazard as the company routes' "after" snapshot: hours_override
    is Numeric(8, 3), so a bare `1` in the request body must be recorded
    as the persisted "1.000" once Postgres normalizes it -- not "1", which
    is what the in-memory attribute would still hold immediately after
    flush and before a refresh."""
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 1})
    action = db.scalars(select(Action).where(Action.kind == "labor_edit", Action.item_id == item.id)).one()
    assert action.after["hours_override"] == "1.000"


def test_patch_material_price_records_the_persisted_precision_not_the_request_bodys(client, db, item, signed_in_user):
    """price_override is Numeric(10, 2); a bare `15` must be recorded as
    the persisted "15.00", not "15"."""
    client.patch(f"/api/items/{item.id}/material-price", json={"priceOverride": 15, "source": "project_price"})
    action = db.scalars(select(Action).where(
        Action.kind == "material_price_edit", Action.item_id == item.id,
    )).one()
    assert action.after["price_override"] == "15.00"


# --- pricing-grid: the PATCH routes return the resolved row ---


def test_get_labor_returns_the_adjustment_fields(client, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/labor",
                 json={"adjustmentPercent": 25, "adjustmentReason": "Mounting height above 16 ft"})
    response = client.get(f"/api/projects/{item.project_id}/labor")
    row = next(r for r in response.json()["rows"] if r["item_id"] == str(item.id))
    assert float(row["adjustment_percent"]) == 25.0
    assert row["adjustment_reason"] == "Mounting height above 16 ft"


def test_get_labor_adjustment_fields_are_empty_with_no_line(client, item, signed_in_user):
    response = client.get(f"/api/projects/{item.project_id}/labor")
    row = next(r for r in response.json()["rows"] if r["item_id"] == str(item.id))
    assert row["adjustment_percent"] is None
    assert row["adjustment_reason"] == ""


def test_patch_labor_returns_the_resolved_row(client, item, signed_in_user):
    """The grid patches one row from the response instead of refetching
    the list, so the PATCH body has to be the same row the list would
    return after the write."""
    response = client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["item_id"] == str(item.id)
    assert float(body["hours_per_unit"]) == 0.75
    assert body["hours_source_label"] == "Estimator entered"
    listed = next(r for r in client.get(f"/api/projects/{item.project_id}/labor").json()["rows"]
                  if r["item_id"] == str(item.id))
    assert listed == body


def test_patch_material_price_returns_the_resolved_row(client, item, signed_in_user):
    response = client.patch(f"/api/items/{item.id}/material-price",
                            json={"priceOverride": 15.5, "source": "project_price"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["item_id"] == str(item.id)
    assert float(body["unit_price"]) == 15.5
    assert body["source"] == "project_price"
    assert body["source_label"] == "Project price"
    listed = next(r for r in client.get(f"/api/projects/{item.project_id}/material-pricing").json()["rows"]
                  if r["item_id"] == str(item.id))
    assert listed == body


# --- pricing-grid: clearing an entry ---


def test_patch_labor_with_null_hours_clears_the_override(client, db, item, signed_in_user):
    """An explicit null is 'go back to whatever is next' -- with no company
    standard and no engine baseline, that is Missing information, which is
    the honest state for 'I don't want a number here'."""
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    response = client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": None})
    assert response.status_code == 200, response.text
    assert db.get(ProjectLaborLine, item.id).hours_override is None
    body = response.json()
    assert body["hours_per_unit"] is None
    assert body["hours_source_label"] is None
    assert body["status"] == "missing"


def test_clearing_hours_falls_back_to_the_company_standard(client, db, org, item, signed_in_user):
    from decimal import Decimal

    from app.takeoff.models import CompanyLaborHoursOverride

    db.add(CompanyLaborHoursOverride(org_id=org.id, item_name=item.name, hours_per_unit=Decimal("0.4")))
    db.commit()
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    body = client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": None}).json()
    assert body["hours_source_label"] == "Company standard"
    assert float(body["hours_per_unit"]) == 0.4


def test_clearing_hours_records_null_in_after_and_undo_restores_it(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.75})
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": None})
    latest = db.scalars(
        select(Action).where(Action.kind == "labor_edit", Action.item_id == item.id).order_by(Action.seq.desc())
    ).first()
    assert latest.after["hours_override"] is None
    client.post(f"/api/projects/{item.project_id}/undo")
    db.expire_all()
    assert float(db.get(ProjectLaborLine, item.id).hours_override) == 0.75


def test_delete_material_price_removes_the_override_and_returns_the_row(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/material-price",
                 json={"priceOverride": 15.5, "source": "allowance", "reason": "no vendor quote yet"})
    response = client.delete(f"/api/items/{item.id}/material-price")
    assert response.status_code == 200, response.text
    assert db.get(ProjectMaterialPrice, item.id) is None
    body = response.json()
    assert body["item_id"] == str(item.id)
    assert body["unit_price"] is None
    assert body["source"] is None
    assert body["reason"] == ""
    assert body["status"] == "missing"


def test_delete_material_price_is_recorded_with_an_empty_after(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/material-price", json={"priceOverride": 15.5, "source": "project_price"})
    client.delete(f"/api/items/{item.id}/material-price")
    latest = db.scalars(
        select(Action).where(Action.kind == "material_price_edit", Action.item_id == item.id).order_by(Action.seq.desc())
    ).first()
    assert latest.after == {}
    assert float(latest.before["price_override"]) == 15.5
    assert latest.label == "Cleared material price for 20A duplex receptacle"


def test_delete_material_price_404s_when_there_is_nothing_to_clear(client, item, signed_in_user):
    response = client.delete(f"/api/items/{item.id}/material-price")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "no_material_price_to_clear"


def test_undo_restores_a_cleared_material_price(client, db, item, signed_in_user):
    client.patch(f"/api/items/{item.id}/material-price",
                 json={"priceOverride": 15.5, "source": "allowance", "reason": "no vendor quote yet"})
    client.delete(f"/api/items/{item.id}/material-price")
    client.post(f"/api/projects/{item.project_id}/undo")
    db.expire_all()
    row = db.get(ProjectMaterialPrice, item.id)
    assert row is not None
    assert float(row.price_override) == 15.5 and row.source == "allowance" and row.reason == "no vendor quote yet"


def test_patch_labor_adjustment_alone_leaves_the_row_missing(client, item, signed_in_user):
    """Tab lands on Adjustment on a Missing information row, +10, Enter:
    the row must not turn green beside "—" in Adj. hours and Labor cost.
    An entry approves a row only once both hours and rate resolve."""
    response = client.patch(f"/api/items/{item.id}/labor", json={"adjustmentPercent": 10})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "missing"
    assert body["adjusted_hours"] is None
    assert body["labor_cost"] is None
    assert float(body["adjustment_percent"]) == 10.0


def test_material_rows_carry_the_market_estimate(client, db, signed_in_user, project, sheet, item, org):
    from datetime import datetime, timezone
    from decimal import Decimal
    from app.takeoff.models import ItemMarketPrice, MarketLookup
    project.org_id = signed_in_user.org_id
    lk = MarketLookup(source="shopping", query_key="current cvt8-lscs-mv", location_key="Austin, TX", status="priced",
                      result={"sellers": [{"title": "t", "seller": "Codale", "price": 169.95, "link": "https://codale.example/x"}]},
                      fetched_at=datetime(2026, 9, 18, tzinfo=timezone.utc), billed=True, org_id=org.id)
    db.add(lk); db.flush()
    db.add(ItemMarketPrice(item_id=item.id, lookup_id=lk.id, outcome="priced", source="shopping", query="Current CVT8-LSCS-MV",
                           unit_price=Decimal("169.95"), price_low=Decimal("156.75"), price_high=Decimal("303.33"),
                           unit="EA", location_label="Austin, TX", fetched_at=lk.fetched_at))
    db.commit()
    r = client.get(f"/api/projects/{project.id}/material-pricing")
    row = r.json()["rows"][0]
    assert row["source_label"] == "Market estimate" and row["status"] == "attention"
    assert row["price_low"] == "156.75" and row["price_high"] == "303.33"
    assert row["market_evidence"] == [{"seller": "Codale", "price": 169.95, "link": "https://codale.example/x"}]
    assert row["basis_note"] == "Austin, TX, Sep 18" and row["market_warning"] is None


def test_material_rows_carry_the_outcome_warning(client, db, signed_in_user, project, sheet, item):
    from app.takeoff.models import ItemMarketPrice
    project.org_id = signed_in_user.org_id
    db.add(ItemMarketPrice(item_id=item.id, outcome="location_needed", source="onebuild", query="20A duplex receptacle"))
    db.commit()
    row = client.get(f"/api/projects/{project.id}/material-pricing").json()["rows"][0]
    assert row["status"] == "missing" and row["market_outcome"] == "location_needed"
    w = row["market_warning"]
    assert w["title"] == "Project location needed" and set(w) == {"title", "found", "why", "fix", "where"}
    assert w["where"].startswith("E2.1")


def test_refresh_queues_one_price_job(client, db, signed_in_user, project):
    from sqlalchemy import func, select
    from app.takeoff.models import Job
    project.org_id = signed_in_user.org_id; db.commit()
    assert client.post(f"/api/projects/{project.id}/market-pricing/refresh").status_code == 202
    assert client.post(f"/api/projects/{project.id}/market-pricing/refresh").json() == {"queued": False}
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "price", Job.project_id == project.id)) == 1
    assert client.get(f"/api/projects/{project.id}/material-pricing").json()["market_job"] == "queued"


def test_usage_counts_billed_lookups_this_month(client, db, signed_in_user, org):
    from datetime import datetime, timezone
    from app.takeoff.models import MarketLookup
    db.add(MarketLookup(source="onebuild", query_key="a", location_key="1", status="priced", result={},
                        fetched_at=datetime.now(timezone.utc), billed=True, org_id=signed_in_user.org_id))
    db.add(MarketLookup(source="onebuild", query_key="b", location_key="1", status="priced", result={},
                        fetched_at=datetime.now(timezone.utc), billed=False, org_id=signed_in_user.org_id))
    db.commit()
    assert client.get("/api/company/market-pricing/usage").json() == {"used": 1, "cap": 2000}
