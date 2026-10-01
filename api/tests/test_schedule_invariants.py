"""The promises this feature makes about what it does not touch
(phases-and-timeline.md §1, §13).

A phase is a grouping of items that already exist, and a stage is a
grouping of hours already resolved. So: a single-phase project reads
exactly as it did before phases existed, moving every sheet into a
second phase changes no total and no status, and a re-run of the engine
never touches a phase an estimator set.
"""
from decimal import Decimal

import pytest

from app.schedule import phases as svc
from app.takeoff.models import CompanyLaborRate, Item, ItemLeadTime, ReviewStatus
from app.takeoff.totals import approved_totals


@pytest.fixture
def rates(db, org):
    row = CompanyLaborRate(
        org_id=org.id, journeyman_rate=Decimal("85"), foreman_rate=Decimal("95"), apprentice_rate=Decimal("55")
    )
    db.add(row)
    db.flush()
    return row


def _labor(client, project):
    return client.get(f"/api/projects/{project.id}/labor").json()


def _material(client, project):
    return client.get(f"/api/projects/{project.id}/material-pricing").json()


def _items(client, project):
    return client.get(f"/api/projects/{project.id}/snapshot").json()["items"]


def test_a_single_phase_project_reads_the_same_before_and_after_its_first_phase_exists(
    client, signed_in_user, project, sheet, item, rates, db
):
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.5, "crewJourneyman": 1})

    before = (approved_totals(db, project.id), _labor(client, project), _material(client, project), _items(client, project))

    # The read is what creates the implicit first phase.
    client.get(f"/api/projects/{project.id}/schedule")

    after = (approved_totals(db, project.id), _labor(client, project), _material(client, project), _items(client, project))

    assert after[0] == before[0]
    assert after[1] == before[1]
    assert after[2] == before[2]
    # The item rows gain a resolved phase once a phase row exists, and
    # nothing else about them moves.
    for old, new in zip(before[3], after[3]):
        assert old["phase_id"] is None and new["phase_id"] is not None
        assert new["phase_overridden"] is False
        assert {k: v for k, v in old.items() if k != "phase_id"} == {k: v for k, v in new.items() if k != "phase_id"}


def test_moving_every_sheet_into_a_second_phase_changes_no_total_and_no_status(
    client, signed_in_user, project, sheet, item, rates, db, dana
):
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.5, "crewJourneyman": 1})
    db.refresh(item)
    client.post(f"/api/items/{item.id}/approve", headers={"If-Match": str(item.version)})

    totals_before = approved_totals(db, project.id)
    labor_before = _labor(client, project)
    material_before = _material(client, project)

    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.assign_sheets(db, actor=dana, phase=second, sheet_ids=[sheet.id])
    db.commit()

    assert approved_totals(db, project.id) == totals_before
    assert _labor(client, project) == labor_before
    assert _material(client, project) == material_before
    db.refresh(item)
    assert item.status is ReviewStatus.APPROVED


def test_hiding_a_phase_is_not_a_thing_the_totals_can_see(client, signed_in_user, project, sheet, item, rates, db, dana):
    """There is no server-side notion of a hidden phase, and this is the
    test that says so: the schedule read never filters the totals query,
    so a phase the screen collapses cannot change a number."""
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 2, "crewJourneyman": 1})
    before = approved_totals(db, project.id)

    body = client.get(f"/api/projects/{project.id}/schedule").json()
    assert body["phases"], "the schedule read should have created the implicit first phase"

    assert approved_totals(db, project.id) == before


def test_a_rerun_leaves_a_phase_and_a_lead_time_an_estimator_set(client, signed_in_user, project, sheet, item, db, dana):
    """merge.py is the one write path for engine output and it never
    owned either field, so a re-run cannot move them. Asserted rather
    than assumed: this is the rule an engine change would break
    silently."""
    from app.takeoff import merge
    from app.takeoff.ingest import map_payload

    # An engine-produced item carries the cluster tag the re-run
    # recognises it by; the fixture's item has none until it is given
    # one, and without it the merge would treat this as a new item.
    item.source_tag = "R"
    db.flush()

    first = svc.first_phase(db, project, create=True)
    second = svc.create_phase(db, actor=dana, project=project, name="Phase 2", after_phase_id=first.id)
    svc.set_item_phase(db, actor=dana, item=item, phase_id=second.id)
    sheet.phase_id = second.id
    db.add(ItemLeadTime(item_id=item.id, flagged=True, lead_weeks=40, source="estimator",
                        source_label="Graybar", quoted_at=None))
    db.commit()

    # Through the engine's own payload shape, mapped exactly as a real
    # run maps it: this is the engine re-reporting the item it already
    # produced on this sheet.
    mapped = map_payload({
        "sheets": [{"id": "0", "number": sheet.number, "takeoff_id": "doc-1", "page": 0,
                    "width_pt": 2000, "height_pt": 1500, "unreadable": None, "kind": "plan",
                    "title": sheet.title}],
        "items": [{
            "name": item.name, "system": item.system, "category": item.category, "unit": item.unit,
            "quantity": float(item.quantity), "status": "ready", "sheet_id": "0", "symbol": item.symbol,
            "warning": None, "x": item.x, "y": item.y, "placements": [[item.x, item.y]],
            "tag": "R", "material_cost": 0.0, "labor_hours": 0.0, "labor_cost": 0.0,
            "total_cost": 0.0, "evidence_png_b64": None,
        }],
    })
    merge.merge_sheet(db, project=project, sheet=sheet, rows=mapped.items, ai_reading=None)
    db.commit()

    db.refresh(item)
    db.refresh(sheet)
    assert item.phase_id == second.id
    assert sheet.phase_id == second.id
    lead = db.get(ItemLeadTime, item.id)
    assert lead is not None and lead.lead_weeks == 40 and lead.source_label == "Graybar"


def test_the_schedule_never_invents_a_lead_time(client, signed_in_user, project, sheet, rates, db):
    """Distribution gear is flagged automatically, but a flag is not a
    date: with nothing quoted the row carries no weeks and no order-by,
    and no string anywhere supplies one."""
    gear = Item(
        project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Switchboard MSB-1",
        system="Power", category="Distribution", quantity=1, unit="EA", status=ReviewStatus.READY, x=1, y=1,
    )
    db.add(gear)
    db.flush()
    client.patch(f"/api/items/{gear.id}/labor", json={"hoursOverride": 42, "crewJourneyman": 1})
    client.patch(f"/api/projects/{project.id}/schedule-dates", json={"mobilizationDate": "2026-10-05"})

    body = client.get(f"/api/projects/{project.id}/schedule").json()
    lead = next(row for row in body["leads"] if row["item_id"] == str(gear.id))
    assert lead["lead_weeks"] is None
    assert lead["order_by"] is None and lead["order_by_week"] is None
    assert lead["passed"] is False and lead["note"] == ""
    assert lead["needed_by"] is not None  # the stage it is needed for is known; the lead time is not
