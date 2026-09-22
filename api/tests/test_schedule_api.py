"""The schedule routes end to end (phases-and-timeline.md §10).

Every test drives the API rather than the service functions, because
what these routes are for is the shape the client reads: one
`ScheduleOut` after any write, phases resolved for every item, and a
proposal that writes nothing until it is confirmed.
"""
from decimal import Decimal

import pytest

from app.takeoff.models import CompanyLaborRate, Item, ReviewStatus, Sheet


@pytest.fixture
def rates(db, org):
    row = CompanyLaborRate(
        org_id=org.id, journeyman_rate=Decimal("85"), foreman_rate=Decimal("95"), apprentice_rate=Decimal("55")
    )
    db.add(row)
    db.flush()
    return row


def _schedule(client, project):
    response = client.get(f"/api/projects/{project.id}/schedule")
    assert response.status_code == 200, response.text
    return response.json()


def _phase_named(body, name):
    return next(p for p in body["phases"] if p["name"] == name)


def test_a_project_with_no_phases_reads_as_one_implicit_phase(client, signed_in_user, project):
    body = _schedule(client, project)
    assert [p["name"] for p in body["phases"]] == ["Phase 1"]
    assert body["multi_phase"] is False
    assert body["relative"] is True
    assert body["manpower"] == [] and body["leads"] == []
    assert body["unscheduled_count"] == 0 and body["unscheduled_note"] == ""
    # The implicit phase carries the firm's two general-conditions lines.
    assert [line["label"] for line in body["phases"][0]["lines"]] == [
        "Final and daily cleanup",
        "Project planning, coordination and layout",
    ]


def test_an_item_without_resolved_labor_is_reported_not_guessed(client, signed_in_user, project, sheet, item):
    body = _schedule(client, project)
    assert body["unscheduled_count"] == 1
    assert "1 item isn't in the schedule yet" in body["unscheduled_note"]
    assert body["phases"][0]["bars"] == []


def test_resolved_labor_becomes_stage_bars_at_the_firm_default_split(client, signed_in_user, project, sheet, item, rates):
    # 14 receptacles at half an hour each is 7 direct hours. Devices
    # sends 45% of them to rough-in (3.15), and the phase's general
    # conditions -- 7% of the direct hours -- ride the bars in the same
    # proportion, which is the remaining 0.22.
    assert client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 0.5, "crewJourneyman": 1}).status_code == 200
    body = _schedule(client, project)
    bars = {bar["stage"]: bar for bar in body["phases"][0]["bars"]}
    assert Decimal(bars["rough_in"]["hours"]) == Decimal("3.37")
    assert bars["rough_in"]["crew"] == {"foreman": 1, "journeyman": 2, "apprentice": 2}
    assert bars["rough_in"]["sources"]["hours"] == "computed"
    assert bars["rough_in"]["label"] == "Rough-in"
    assert body["defaults_in_use"]["splits"] is True
    assert "demolition" not in bars and "gear" not in bars


def test_a_second_phase_owns_sheets_and_an_item_can_be_moved_on_its_own(client, signed_in_user, project, sheet, item, db):
    first = _schedule(client, project)["phases"][0]
    created = client.post(f"/api/projects/{project.id}/phases", json={"name": "Phase 2", "afterPhaseId": first["id"]})
    assert created.status_code == 201, created.text
    second = _phase_named(created.json(), "Phase 2")

    moved = client.put(f"/api/phases/{second['id']}/sheets", json={"sheetIds": [str(sheet.id)]})
    assert moved.status_code == 200, moved.text
    assert _phase_named(moved.json(), "Phase 2")["sheet_ids"] == [str(sheet.id)]

    snapshot = client.get(f"/api/projects/{project.id}/snapshot").json()
    row = next(i for i in snapshot["items"] if i["id"] == str(item.id))
    assert row["phase_id"] == second["id"] and row["phase_overridden"] is False

    back = client.patch(f"/api/items/{item.id}/phase", json={"phaseId": first["id"]})
    assert back.status_code == 200, back.text
    assert back.json()["phase_id"] == first["id"] and back.json()["phase_overridden"] is True

    body = _schedule(client, project)
    assert body["multi_phase"] is True
    assert _phase_named(body, "Phase 1")["items_moved_in"] == 1
    assert _phase_named(body, "Phase 2")["items_moved_out"] == 1

    inherit = client.patch(f"/api/items/{item.id}/phase", json={"phaseId": None})
    assert inherit.status_code == 200 and inherit.json()["phase_overridden"] is False


def test_the_last_phase_cannot_be_deleted(client, signed_in_user, project):
    first = _schedule(client, project)["phases"][0]
    response = client.delete(f"/api/phases/{first['id']}")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "last_phase"


def test_a_stage_plan_and_a_line_override_read_back_as_the_estimators(client, signed_in_user, project, sheet, item, rates):
    client.patch(f"/api/items/{item.id}/labor", json={"hoursOverride": 2, "crewJourneyman": 1})
    first = _schedule(client, project)["phases"][0]

    planned = client.put(
        f"/api/phases/{first['id']}/stages/rough_in",
        json={"journeyman": 4, "startDate": "2026-10-19"},
    )
    assert planned.status_code == 200, planned.text
    bar = {b["stage"]: b for b in planned.json()["phases"][0]["bars"]}["rough_in"]
    assert bar["crew"]["journeyman"] == 4
    assert bar["sources"]["journeyman"] == "estimator"
    assert bar["start"] == "2026-10-19"

    line = first["lines"][0]
    typed = client.patch(f"/api/phases/{first['id']}/lines/{line['id']}", json={"hours": 12})
    assert typed.status_code == 200, typed.text
    line_out = typed.json()["phases"][0]["lines"][0]
    assert line_out["source"] == "estimator" and Decimal(line_out["hours"]) == Decimal("12.00")

    reset = client.patch(f"/api/phases/{first['id']}/lines/{line['id']}", json={"hours": None})
    assert reset.json()["phases"][0]["lines"][0]["source"] == "computed"


def test_an_unknown_stage_is_a_404_not_a_500(client, signed_in_user, project):
    first = _schedule(client, project)["phases"][0]
    response = client.put(f"/api/phases/{first['id']}/stages/painting", json={"journeyman": 2})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "unknown_stage"


def test_a_flagged_item_without_a_quote_shows_no_order_date(client, signed_in_user, project, sheet, rates, db):
    gear = Item(
        project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Switchboard MSB-1",
        system="Power", category="Distribution", quantity=1, unit="EA", status=ReviewStatus.READY, x=100, y=100,
    )
    db.add(gear)
    db.flush()
    client.patch(f"/api/items/{gear.id}/labor", json={"hoursOverride": 42, "crewJourneyman": 1})

    body = _schedule(client, project)
    lead = next(l for l in body["leads"] if l["item_id"] == str(gear.id))
    assert lead["lead_weeks"] is None and lead["order_by"] is None and lead["source_label"] == ""
    assert lead["needed_for_stage"] == "gear" and lead["item_status"] == "ready"

    quoted = client.patch(f"/api/items/{gear.id}/lead-time", json={"leadWeeks": 40, "sourceLabel": "Graybar"})
    assert quoted.status_code == 200, quoted.text
    dated = client.patch(
        f"/api/projects/{project.id}/schedule-dates",
        json={"mobilizationDate": "2027-02-22", "expectedAwardDate": "2026-12-01"},
    )
    assert dated.status_code == 200, dated.text

    lead = next(l for l in dated.json()["leads"] if l["item_id"] == str(gear.id))
    assert lead["lead_weeks"] == 40 and lead["source"] == "estimator" and lead["source_label"] == "Graybar"
    assert lead["order_by"] is not None
    assert lead["passed"] is True and lead["note"].startswith("Order date has passed")


def test_a_company_lead_time_fills_an_item_that_has_none(client, signed_in_user, project, sheet, rates, db):
    gear = Item(
        project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Pad-mount transformer T-1",
        system="Power", category="Distribution", quantity=1, unit="EA", status=ReviewStatus.READY, x=10, y=10,
    )
    db.add(gear)
    db.flush()
    client.patch(f"/api/items/{gear.id}/labor", json={"hoursOverride": 10, "crewJourneyman": 1})

    saved = client.put(
        "/api/company/lead-times/transformer",
        json={"leadWeeks": 50, "sourceLabel": "Eaton rep", "quotedAt": "2026-09-01"},
    )
    assert saved.status_code == 200, saved.text

    lead = next(l for l in _schedule(client, project)["leads"] if l["item_id"] == str(gear.id))
    assert lead["lead_weeks"] == 50 and lead["source"] == "company" and lead["source_label"] == "Eaton rep"


def test_phases_are_proposed_from_sheet_families_and_written_only_on_confirm(client, signed_in_user, project, sheet, db):
    for number in ("XE-1.0", "XED-1.0"):
        db.add(Sheet(
            project_id=project.id, number=number, title="Phase 2 plan", discipline="Electrical",
            revision="", scale="", scale_options=[], plan="",
        ))
    db.flush()

    preview = client.post(f"/api/projects/{project.id}/phases/propose", json={})
    assert preview.status_code == 200, preview.text
    proposal = preview.json()
    # E2.1 and XE-1.0/XED-1.0 are two phase markers, not three sheet
    # families: the trailing D names a demolition sheet inside a phase.
    assert [p["name"] for p in proposal["phases"]] == ["E sheets", "XE sheets"]
    assert "Nothing changes until you confirm" in proposal["note"]
    assert _schedule(client, project)["multi_phase"] is False  # nothing written

    applied = client.post(f"/api/projects/{project.id}/phases/propose/apply", json=proposal)
    assert applied.status_code == 200, applied.text
    assert applied.json()["multi_phase"] is True
    assert len(applied.json()["phases"]) == 2

    undone = client.post(f"/api/projects/{project.id}/undo")
    assert undone.status_code == 200, undone.text
    after = _schedule(client, project)
    assert after["multi_phase"] is False
    assert [p["name"] for p in after["phases"]] == ["Phase 1"]


def test_one_sheet_family_proposes_nothing(client, signed_in_user, project, sheet):
    preview = client.post(f"/api/projects/{project.id}/phases/propose", json={})
    assert preview.json()["phases"] == []
    assert preview.json()["note"].startswith("No phasing found")


def test_the_company_split_table_refuses_a_row_that_does_not_total_100(client, signed_in_user):
    listed = client.get("/api/company/stage-splits")
    assert listed.status_code == 200
    assert any(row["category_key"] == "devices" for row in listed.json())
    assert all(row["firm_edited"] is False for row in listed.json())

    bad = client.put("/api/company/stage-splits/devices", json={
        "categoryLabel": "Devices", "demolition": 0, "roughIn": 45, "wirePull": 25,
        "gear": 0, "trim": 25, "closeout": 4,
    })
    assert bad.status_code == 400, bad.text
    assert bad.json()["detail"]["code"] == "split_must_total_100"

    good = client.put("/api/company/stage-splits/devices", json={
        "categoryLabel": "Devices", "demolition": 0, "roughIn": 50, "wirePull": 20,
        "gear": 0, "trim": 25, "closeout": 5,
    })
    assert good.status_code == 200, good.text
    assert good.json()["firm_edited"] is True


def test_the_fallback_split_cannot_be_removed(client, signed_in_user):
    client.get("/api/company/stage-splits")
    response = client.delete("/api/company/stage-splits/*")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "fallback_split_required"


def test_company_crews_and_settings_round_trip(client, signed_in_user):
    crews = client.get("/api/company/stage-crews")
    assert crews.status_code == 200
    assert [row["stage"] for row in crews.json()] == [
        "demolition", "rough_in", "wire_pull", "gear", "trim", "closeout"
    ]
    assert crews.json()[1]["label"] == "Rough-in"

    saved = client.put("/api/company/stage-crews/rough_in", json={
        "foreman": 1, "journeyman": 3, "apprentice": 1,
        "productiveHoursPerDay": 6, "productivityFactor": 1, "maxCrew": 8,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["journeyman"] == 3 and saved.json()["firm_edited"] is True

    settings = client.put("/api/company/schedule-settings", json={"leadTimeStaleDays": 30})
    assert settings.status_code == 200 and settings.json()["lead_time_stale_days"] == 30


def test_a_stale_company_lead_time_carries_a_four_field_warning(client, signed_in_user, project, sheet, rates, db):
    gear = Item(
        project_id=project.id, sheet_id=sheet.id, symbol="panel", name="Standby generator G-1",
        system="Power", category="Distribution", quantity=1, unit="EA", status=ReviewStatus.READY, x=10, y=10,
    )
    db.add(gear)
    db.flush()
    client.patch(f"/api/items/{gear.id}/labor", json={"hoursOverride": 10, "crewJourneyman": 1})
    client.put("/api/company/schedule-settings", json={"leadTimeStaleDays": 1})
    client.put("/api/company/lead-times/generator", json={
        "leadWeeks": 60, "sourceLabel": "Cummins rep", "quotedAt": "2026-01-05",
    })

    lead = next(l for l in _schedule(client, project)["leads"] if l["item_id"] == str(gear.id))
    assert lead["stale"] is True
    assert set(lead["warning"]) == {"title", "found", "why", "fix", "where"}
    assert "Cummins rep" in lead["warning"]["found"]
