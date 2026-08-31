"""PATCH /api/items/{item_id}/labor and /material-price -- the two
project-level override mutations."""
from sqlalchemy import select

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
    assert body["pricingSource"] is None
    ids = [row["itemId"] for row in body["rows"]]
    assert str(item.id) in ids


def test_get_labor_row_missing_without_llm_pricing(client, project, item, signed_in_user):
    response = client.get(f"/api/projects/{project.id}/labor")
    row = next(r for r in response.json()["rows"] if r["itemId"] == str(item.id))
    assert row["status"] == "missing"


def test_get_labor_row_ready_when_project_priced_by_llm(client, db, project, item, signed_in_user):
    from decimal import Decimal

    project.pricing_source = "llm"
    # The engine-computed baseline `resolve_labor` reads for "Estimated
    # basis" is item.labor_hours -- the shared `item` fixture leaves it
    # at its column default of 0, which is falsy and would otherwise
    # skip straight past the llm branch into "missing" regardless of
    # project.pricing_source. Set it here rather than on the shared
    # fixture, since most other tests using `item` don't want a
    # labor_hours baseline at all.
    item.labor_hours = Decimal("5")
    db.commit()
    response = client.get(f"/api/projects/{project.id}/labor")
    row = next(r for r in response.json()["rows"] if r["itemId"] == str(item.id))
    assert row["status"] == "ready"
    assert row["hoursSourceLabel"] == "Estimated basis"


def test_get_material_pricing_lists_every_countable_item(client, project, item, signed_in_user):
    response = client.get(f"/api/projects/{project.id}/material-pricing")
    assert response.status_code == 200, response.text
    ids = [row["itemId"] for row in response.json()["rows"]]
    assert str(item.id) in ids


def test_get_material_pricing_uses_company_price_when_present(client, db, org, project, item, signed_in_user):
    from app.takeoff.models import CompanyMaterialPrice

    db.add(CompanyMaterialPrice(org_id=org.id, item_name=item.name, unit_price=99, effective_date="2026-08-01"))
    db.commit()
    response = client.get(f"/api/projects/{project.id}/material-pricing")
    row = next(r for r in response.json()["rows"] if r["itemId"] == str(item.id))
    assert row["sourceLabel"] == "Company price"
    assert float(row["unitPrice"]) == 99.0
