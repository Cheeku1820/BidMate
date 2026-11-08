"""Task 11 of docs/plans/rom-estimate.md -- the estimator's override,
and the run's promise not to discard it.

The rule under test is CLAUDE.md's: the engine never discards a person's
judgment. It is the same rule `merge.py` enforces for an *Estimator
approved* item, applied to a different table -- and it is what makes the
override worth offering at all. A number you can type that the next run
quietly replaces is worse than no field.
"""
from decimal import Decimal

import pytest

from app.takeoff.models import Action, Assumption, Item, Project, ReviewStatus, Sheet
from app.worker.estimate_job import run as run_estimate_job
from tests.test_estimate_job import job_for


def url(assumption):
    return f"/api/assumptions/{assumption.id}"


def estimate_url(project):
    return f"/api/projects/{project.id}/estimate"


def undo_url(project):
    """Undo is project-scoped -- the stack is shared across the
    reviewers on one project (DESIGN.md), not global."""
    return f"/api/projects/{project.id}/undo"


def redo_url(project):
    return f"/api/projects/{project.id}/redo"


@pytest.fixture
def project_with_assumptions(db, org, signed_in_user):
    p = Project(org_id=org.id, name="Kittle's Saxony", revision_set_label="E1.1 Rev 3",
                pricing_source="llm", pricing_note="Indiana regional basis")
    db.add(p)
    db.flush()
    s = Sheet(project_id=p.id, number="EL101", title="Lighting plan", discipline="Electrical",
              revision="Rev 2", scale="", scale_options=[], plan="showroom")
    db.add(s)
    db.flush()
    db.add(Item(project_id=p.id, sheet_id=s.id, symbol="receptacle",
                name="20A duplex receptacle", system="Power", category="Devices",
                quantity=Decimal("1"), unit="ea", status=ReviewStatus.READY, x=100, y=100,
                material_cost=Decimal("100"), labor_cost=Decimal("40"),
                labor_hours=Decimal("2"), total_cost=Decimal("140")))
    db.flush()
    db.commit()
    return p


@pytest.fixture
def ceiling(db, project_with_assumptions):
    row = Assumption(
        project_id=project_with_assumptions.id, section="takeoff", basis="inferred",
        subject_kind="project", title="Showroom ceiling height",
        found="No reflected ceiling plan in the set",
        why="Fixture drop lengths depend on it", where="EL101",
        value="14", unit="ft", source="engine",
    )
    db.add(row)
    db.flush()
    db.commit()
    return row


def find_line(body, needle):
    for section in body["sections"]:
        for line in section["lines"]:
            if needle.lower() in line["title"].lower():
                return line
    raise AssertionError(f"no line matching {needle!r}")


# --- what an override does ---------------------------------------------


def test_override_flips_the_line_to_counted(client, project_with_assumptions, ceiling):
    body = client.patch(url(ceiling), json={"value": "16", "unit": "ft"}).json()
    line = find_line(body, "ceiling")
    assert line["origin"] == "counted"
    assert line["value"] == "16"
    assert "Entered by" in line["where"]


def test_override_names_the_person_so_a_reader_can_ask_them(client, ceiling, dana):
    body = client.patch(url(ceiling), json={"value": "16"}).json()
    line = find_line(body, "ceiling")
    assert dana.name in line["where"]
    assert dana.name in line["found"]


def test_override_leaves_the_qualifications_block(client, project_with_assumptions, ceiling):
    """It is no longer a condition of the price -- there is nothing for a
    reader to check beyond asking the person named on the line."""
    before = client.get(estimate_url(project_with_assumptions)).json()
    assert any("ceiling" in q["title"].lower() for q in before["qualifications"])

    client.patch(url(ceiling), json={"value": "16"})
    after = client.get(estimate_url(project_with_assumptions)).json()
    assert not any("ceiling" in q["title"].lower() for q in after["qualifications"])


def test_override_narrows_the_budget_range(client, project_with_assumptions, ceiling):
    """An entered number is not an estimate, so it stops carrying a
    derived basis's width."""
    body = client.patch(url(ceiling), json={"value": "16"}).json()
    line = find_line(body, "ceiling")
    assert line["basis"] == "estimator_entered"
    assert line["basis_label"] == "Entered by the estimator"


def test_override_moves_the_section_tally(client, project_with_assumptions, ceiling):
    before = client.get(estimate_url(project_with_assumptions)).json()
    takeoff_before = next(s for s in before["sections"] if s["key"] == "takeoff")

    after = client.patch(url(ceiling), json={"value": "16"}).json()
    takeoff_after = next(s for s in after["sections"] if s["key"] == "takeoff")

    assert takeoff_after["assumed_count"] == takeoff_before["assumed_count"] - 1
    assert takeoff_after["counted_count"] == takeoff_before["counted_count"] + 1


def test_override_keeps_the_unit_when_none_is_sent(client, ceiling):
    body = client.patch(url(ceiling), json={"value": "16"}).json()
    assert find_line(body, "ceiling")["unit"] == "ft"


# --- attribution and undo ----------------------------------------------


def test_override_is_attributed(client, db, ceiling, dana):
    client.patch(url(ceiling), json={"value": "16"})
    db.expire_all()
    assert db.get(Assumption, ceiling.id).created_by_user_id == dana.id
    assert db.get(Assumption, ceiling.id).source == "estimator"


def test_override_lands_in_the_action_log(client, db, project_with_assumptions, ceiling, dana):
    client.patch(url(ceiling), json={"value": "16", "unit": "ft"})
    db.expire_all()
    action = db.query(Action).filter(Action.kind == "assumption_edit").one()
    assert action.actor_user_id == dana.id
    assert action.project_id == project_with_assumptions.id
    assert "16" in action.label


def test_override_is_undoable(client, db, project_with_assumptions, ceiling):
    original = client.get(estimate_url(project_with_assumptions)).json()
    client.patch(url(ceiling), json={"value": "16"})

    assert client.post(undo_url(project_with_assumptions)).status_code == 200
    db.expire_all()
    restored = client.get(estimate_url(project_with_assumptions)).json()
    assert find_line(restored, "ceiling")["value"] == "14"
    assert find_line(restored, "ceiling")["origin"] == "assumed"
    assert restored["qualifications"] == original["qualifications"]


def test_an_undone_override_can_be_redone(client, db, project_with_assumptions, ceiling):
    client.patch(url(ceiling), json={"value": "16"})
    client.post(undo_url(project_with_assumptions))
    assert client.post(redo_url(project_with_assumptions)).status_code == 200
    db.expire_all()
    body = client.get(estimate_url(project_with_assumptions)).json()
    assert find_line(body, "ceiling")["value"] == "16"
    assert find_line(body, "ceiling")["origin"] == "counted"


def test_undoing_an_override_whose_row_a_rerun_deleted_is_a_no_op(
        client, db, project_with_assumptions, ceiling):
    """A derived disclosure is regenerable, so there is nothing an
    estimator can do about the failure and nothing lost by the undo
    being a skip -- the opposite reading a pricing row gets, and for a
    reason: one is a person's entry, this one the next run rebuilds."""
    client.patch(url(ceiling), json={"value": "16"})
    db.expire_all()
    db.delete(db.get(Assumption, ceiling.id))
    db.commit()
    assert client.post(undo_url(project_with_assumptions)).status_code == 200


# --- the run's side of the rule ----------------------------------------


def test_override_survives_a_rerun(db, project_with_assumptions, ceiling, dana):
    """Review Focus 5, from the override's side."""
    from app.estimate.override import override

    override(db, row=ceiling, actor=dana, value="16")
    db.commit()

    job = job_for(project_with_assumptions, dana)
    db.add(job)
    db.flush()
    run_estimate_job(db, job)
    db.flush()

    kept = db.get(Assumption, ceiling.id)
    assert kept is not None
    assert kept.value == "16"
    assert kept.source == "estimator"


# --- what an override may not do ---------------------------------------


def test_a_scope_exclusion_cannot_be_overridden_with_a_number(client, db, project_with_assumptions):
    """Scope is changed by stating the scope. A typed number here would
    be an exclusion whose text says one thing and whose value says
    another."""
    row = Assumption(
        project_id=project_with_assumptions.id, section="scope", basis="standard_exclusion",
        subject_kind="project", title="Temporary power excluded",
        found="Not addressed", why="It is commonly the GC's", where="Scope documents",
        source="engine",
    )
    db.add(row)
    db.commit()
    response = client.patch(url(row), json={"value": "included"})
    assert response.status_code == 422
    assert "scope statement" in response.json()["detail"]["message"]


def test_an_empty_value_is_refused(client, ceiling):
    response = client.patch(url(ceiling), json={"value": "   "})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_override"


def test_an_overlong_value_is_refused(client, ceiling):
    response = client.patch(url(ceiling), json={"value": "x" * 101})
    assert response.status_code == 422


def test_an_overlong_unit_is_refused(client, ceiling):
    response = client.patch(url(ceiling), json={"value": "16", "unit": "x" * 21})
    assert response.status_code == 422


# --- tenancy -----------------------------------------------------------


def test_override_is_org_scoped(client, db, other_org_project):
    row = Assumption(
        project_id=other_org_project.id, section="takeoff", basis="inferred",
        subject_kind="project", title="Someone else's ceiling",
        found="f", why="w", where="EL101", value="14", unit="ft", source="engine",
    )
    db.add(row)
    db.commit()
    assert client.patch(url(row), json={"value": "16"}).status_code == 404


def test_a_missing_assumption_is_the_same_404(client, signed_in_user):
    import uuid as _uuid

    assert client.patch(f"/api/assumptions/{_uuid.uuid4()}", json={"value": "16"}).status_code == 404


def test_override_requires_a_signed_in_user(client, db, org):
    p = Project(org_id=org.id, name="Private", revision_set_label="")
    db.add(p)
    db.flush()
    row = Assumption(
        project_id=p.id, section="takeoff", basis="inferred", subject_kind="project",
        title="Ceiling", found="f", why="w", where="EL101", value="14", source="engine",
    )
    db.add(row)
    db.commit()
    assert client.patch(url(row), json={"value": "16"}).status_code == 401


# --- the review's findings, pinned -------------------------------------


def test_a_priced_line_cannot_be_overridden_here(client, db, project_with_assumptions):
    """Codex review, finding 3. The PATCH used to change the disclosure
    and nothing else, so overriding a $48,900 class-average note to 900
    left the line stating 900 while the estimate still carried 48,900.
    A price is entered on its own screen, which already writes through
    commit() and which the ROM reads."""
    row = Assumption(
        project_id=project_with_assumptions.id, section="material", basis="class_average",
        subject_kind="project", title="Switchboard SB-1",
        found="No quote on file", why="Gear moves a budget most", where="Material pricing",
        value="$48,900", source="engine",
    )
    db.add(row)
    db.commit()
    response = client.patch(url(row), json={"value": "900"})
    assert response.status_code == 422
    assert "Material pricing" in response.json()["detail"]["message"]


def test_a_labor_line_points_at_labor_pricing(client, db, project_with_assumptions):
    row = Assumption(
        project_id=project_with_assumptions.id, section="labor", basis="firm_default",
        subject_kind="project", title="Labor rate",
        found="No project rate set", why="Every labor dollar rests on it",
        where="Company settings", value="$68.00 / hr", source="engine",
    )
    db.add(row)
    db.commit()
    assert "Labor pricing" in client.patch(url(row), json={"value": "74"}).json()["detail"]["message"]


def test_an_entered_fact_says_the_next_run_applies_it(client, ceiling):
    """A ceiling height is what the next run reads, so the line must not
    imply the total already moved."""
    body = client.patch(url(ceiling), json={"value": "16"}).json()
    assert "next takeoff run" in find_line(body, "ceiling")["found"]


def test_an_override_survives_undo_regeneration_and_redo(db, project_with_assumptions, dana):
    """Codex review, finding 10. Undo restores source="engine", which
    makes the row eligible for deletion by the next regeneration -- and
    regeneration writes a fresh row with a NEW id. Redo used to look up
    the dead UUID, skip, and record a SUCCESSFUL compensating action
    that restored nothing. A market-pricing pass re-queues generation on
    its own, so this was reachable without a manual re-run.

    Built on a disclosure the generators actually produce, so the
    regeneration in the middle really does delete and replace the row --
    which is the whole mechanism under test.
    """
    from app.estimate.override import override
    from app.estimate.write import regenerate
    from app.takeoff import undo as undo_svc

    regenerate(db, project_with_assumptions)
    db.commit()
    row = db.query(Assumption).filter(
        Assumption.project_id == project_with_assumptions.id,
        Assumption.section == "takeoff",
        Assumption.basis == "rule_of_thumb",
    ).one()
    original_id, title = row.id, row.title

    override(db, row=row, actor=dana, value="45")
    db.commit()

    undo_svc.undo(db, actor=dana, project_id=project_with_assumptions.id)
    db.commit()
    db.expire_all()
    assert db.get(Assumption, original_id).value == "30"

    # The re-run deletes that engine row and writes a new one with a
    # different id.
    regenerate(db, project_with_assumptions)
    db.commit()
    db.expire_all()
    assert db.get(Assumption, original_id) is None

    undo_svc.redo(db, actor=dana, project_id=project_with_assumptions.id)
    db.commit()
    db.expire_all()

    survivors = db.query(Assumption).filter(
        Assumption.project_id == project_with_assumptions.id,
        Assumption.title == title,
    ).all()
    assert len(survivors) == 1, "the redo must land on the regenerated row, not duplicate it"
    assert survivors[0].value == "45"
    assert survivors[0].source == "estimator"
