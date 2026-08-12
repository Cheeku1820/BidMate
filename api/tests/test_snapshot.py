"""Read endpoints: /projects, /projects/{id}, /projects/{id}/snapshot,
/projects/{id}/totals -- and snapshot.version(), the ETag driving polling.

The plan's four tests (docs/superpowers/plans/2026-08-07-backend-spine.md,
Task 11) are a floor, not the set -- see task-11-brief.md for the corrections
applied here: undo_head/redo_head now take an actor, version() must use
Action.seq not created_at, the two unscoped queries in the sketch are
tenancy defects, **obj.__dict__ is unsafe on a SQLAlchemy model, and
GET /projects/{id} is missing from the sketch entirely.

The approve-item mutation endpoint doesn't exist until Task 13, so tests
here that need a mutation call app.takeoff.review directly against the same
`db` session the `client` fixture is wired to (app.dependency_overrides
returns that exact object), rather than posting to a route that doesn't
exist yet.
"""

import logging
from datetime import datetime, timezone

from app.identity.models import Org
from app.takeoff import review, undo
from app.takeoff import router as router_module
from app.takeoff.actions import CrossOrgActionError
from app.takeoff.models import Item, Project, ReviewStatus, Sheet, Warning, WarningReason


def _sign_in(client, email="dana@example.com", password="correct-horse"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _foreign_project(db):
    """A project in an org `dana` has no membership in -- for the
    tenancy tests. Matches test_undo_redo.py's `_foreign_project`."""
    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    other_project = Project(org_id=other_org.id, name="A different firm's project", revision_set_label="")
    db.add(other_project)
    db.flush()
    return other_project


# --- The plan's four, adjusted per the brief ---


def test_snapshot_returns_sheets_items_and_the_undo_head(client, dana, project, sheet, item):
    _sign_in(client)

    body = client.get(f"/api/projects/{project.id}/snapshot").json()

    assert [s["number"] for s in body["sheets"]] == ["E2.1"]
    assert body["items"][0]["name"] == "20A duplex receptacle"
    assert body["undo"]["can_undo"] is False
    assert body["undo"]["can_redo"] is False


def test_an_unchanged_project_answers_304(client, dana, project, sheet, item):
    _sign_in(client)
    first = client.get(f"/api/projects/{project.id}/snapshot")
    etag = first.headers["etag"]

    again = client.get(f"/api/projects/{project.id}/snapshot", headers={"If-None-Match": etag})

    assert again.status_code == 304
    # RFC 7232: a 304 still carries the ETag it matched against.
    assert again.headers["etag"] == etag


def test_the_version_changes_after_a_mutation(client, db, dana, project, sheet, item):
    _sign_in(client)
    etag = client.get(f"/api/projects/{project.id}/snapshot").headers["etag"]

    review.approve_item(db, dana, item)
    db.flush()

    again = client.get(f"/api/projects/{project.id}/snapshot", headers={"If-None-Match": etag})
    assert again.status_code == 200


def test_no_response_field_exposes_processing_internals(client, dana, project, sheet, item):
    """A substring scan over the whole JSON body. This can false-positive
    on legitimate estimator content (an item genuinely named "Model 400
    panel" would trip "model") -- noted as a known limitation rather than
    weakened, per the brief.
    """
    _sign_in(client)
    body = client.get(f"/api/projects/{project.id}/snapshot").text.lower()

    for forbidden in ("confidence", "model", "score", "pipeline"):
        assert forbidden not in body


# --- Beyond the plan's four: required by the brief ---


def test_the_version_is_stable_across_two_identical_reads(client, dana, project, sheet, item):
    """A version that changes when nothing changed makes the ETag
    worthless -- the client would never get a 304 and would poll forever.
    """
    _sign_in(client)
    first = client.get(f"/api/projects/{project.id}/snapshot").headers["etag"]
    second = client.get(f"/api/projects/{project.id}/snapshot").headers["etag"]

    assert first == second


def test_a_user_in_org_a_gets_404_not_403_for_org_bs_project_on_every_read_route(client, dana, db):
    _sign_in(client)
    other_project = _foreign_project(db)

    for path in (
        f"/api/projects/{other_project.id}",
        f"/api/projects/{other_project.id}/snapshot",
        f"/api/projects/{other_project.id}/totals",
    ):
        response = client.get(path)
        assert response.status_code == 404, f"{path} leaked a status other than 404: {response.status_code}"
        assert response.json()["detail"]["code"] == "project_not_found"


def test_get_projects_lists_only_the_callers_orgs_projects(client, dana, project, db):
    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    other_project = Project(org_id=other_org.id, name="Ferrovia's own project", revision_set_label="")
    db.add(other_project)
    db.flush()

    _sign_in(client)
    body = client.get("/api/projects").json()

    ids = {p["id"] for p in body}
    assert str(project.id) in ids
    assert str(other_project.id) not in ids


def test_unauthenticated_requests_get_401_on_every_read_route(client, project):
    for path in (
        "/api/projects",
        f"/api/projects/{project.id}",
        f"/api/projects/{project.id}/snapshot",
        f"/api/projects/{project.id}/totals",
    ):
        response = client.get(path)
        assert response.status_code == 401, f"{path} did not require a session: {response.status_code}"


def test_snapshot_includes_superseded_sheets_flagged_while_totals_excludes_their_items(client, db, dana, project):
    active = Sheet(project_id=project.id, number="E1.1", title="Power plan -- current",
                    discipline="Electrical", revision="Rev 3", scale='1/8" = 1\'-0"', scale_options=[], plan="warehouse")
    superseded = Sheet(project_id=project.id, number="E1.1", title="Power plan -- old",
                        discipline="Electrical", revision="Rev 2", scale='1/8" = 1\'-0"', scale_options=[],
                        plan="warehouse", superseded_at=datetime.now(timezone.utc))
    db.add_all([active, superseded])
    db.flush()

    live_item = Item(project_id=project.id, sheet_id=active.id, symbol="receptacle", name="Live receptacle",
                      system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.APPROVED)
    stale_item = Item(project_id=project.id, sheet_id=superseded.id, symbol="receptacle", name="Stale receptacle",
                       system="Power", category="Devices", quantity=99, unit="EA", status=ReviewStatus.APPROVED)
    db.add_all([live_item, stale_item])
    db.flush()

    _sign_in(client)
    body = client.get(f"/api/projects/{project.id}/snapshot").json()

    by_number_and_title = {(s["number"], s["title"]): s["superseded"] for s in body["sheets"]}
    assert by_number_and_title[("E1.1", "Power plan -- current")] is False
    assert by_number_and_title[("E1.1", "Power plan -- old")] is True

    totals = client.get(f"/api/projects/{project.id}/totals").json()
    assert totals["approved_units"] == "1.00"
    assert totals["approved_count"] == 1


def test_undo_reflects_real_state_after_an_approve_and_after_an_undo(client, db, dana, project, sheet, item):
    _sign_in(client)

    before = client.get(f"/api/projects/{project.id}/snapshot").json()
    assert before["undo"]["can_undo"] is False

    review.approve_item(db, dana, item)
    db.flush()

    after_approve = client.get(f"/api/projects/{project.id}/snapshot").json()
    assert after_approve["undo"]["can_undo"] is True
    assert after_approve["undo"]["undo_label"] == f"Approved {item.name}"
    assert after_approve["undo"]["undo_by"] == "Dana Whitfield"
    assert after_approve["undo"]["can_redo"] is False

    undo.undo(db, dana, project.id)
    db.flush()

    after_undo = client.get(f"/api/projects/{project.id}/snapshot").json()
    assert after_undo["undo"]["can_undo"] is False
    assert after_undo["undo"]["can_redo"] is True


# --- The endpoint the sketch listed in "Produces" but never implemented ---


def test_get_project_returns_the_project_and_its_sheets_with_scale_state(client, dana, project, sheet):
    _sign_in(client)

    body = client.get(f"/api/projects/{project.id}").json()

    assert body["id"] == str(project.id)
    assert body["name"] == project.name
    assert [s["number"] for s in body["sheets"]] == ["E2.1"]
    assert body["sheets"][0]["scale"] == "mixed"
    assert body["sheets"][0]["scale_options"] == []


# --- Item-level detail: warning reason, approved_by, rejected ---


def test_item_warning_exposes_its_typed_reason(client, db, dana, project, sheet, item):
    warning = Warning(item_id=item.id, reason=WarningReason.SCALE, title="Scale needs confirmation",
                       found="E2.1 shows two scale labels.", why="Measured conduit lengths may be wrong.",
                       fix="Select the scale that applies to this sheet.", where_="E2.1 title block")
    item.status = ReviewStatus.MISSING
    db.add(warning)
    db.flush()

    _sign_in(client)
    body = client.get(f"/api/projects/{project.id}/snapshot").json()

    found_item = next(i for i in body["items"] if i["id"] == str(item.id))
    assert found_item["warning"]["reason"] == "scale"
    assert found_item["warning"]["title"] == "Scale needs confirmation"
    assert found_item["warning"]["where"] == "E2.1 title block"
    assert found_item["status"] == "missing"


def test_approved_item_carries_the_approving_users_name_and_rejected_defaults_false(client, db, dana, project, sheet, item):
    review.approve_item(db, dana, item)
    db.flush()

    _sign_in(client)
    body = client.get(f"/api/projects/{project.id}/snapshot").json()

    found_item = next(i for i in body["items"] if i["id"] == str(item.id))
    assert found_item["approved_by"] == "Dana Whitfield"
    assert found_item["rejected"] is False
    assert found_item["status"] == "approved"


# --- CrossOrgActionError's HTTP handler (brief item 7, carried forward
# unresolved from Tasks 8 and 10) ---


def test_cross_org_action_error_maps_to_the_same_404_load_project_raises_not_a_403(
    client, dana, project, monkeypatch, caplog
):
    """`CrossOrgActionError` should be unreachable over HTTP: `load_project`
    already refuses a cross-org request for every project-scoped route
    before any service function that could raise it ever runs. This proves
    the handler registered in main.py still answers correctly if that gate
    is ever missing or bypassed, by forcing `load_project` itself to raise
    it directly -- the only way to exercise the handler without a real gate
    gap. Uncaught, this is a 500; the design says it must map to
    `load_project`'s own 404, not a 403, so a cross-org probe can't use the
    status code to tell "missing" from "not yours" apart.
    """

    def _raise(project_id, db, user):
        raise CrossOrgActionError(f"actor {user.id} is not authorized for project {project_id}")

    monkeypatch.setattr(router_module, "load_project", _raise)
    _sign_in(client)

    with caplog.at_level(logging.WARNING):
        response = client.get(f"/api/projects/{project.id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project_not_found"
    assert response.json()["detail"]["message"] == "That project is not available to your account."
    assert any("CrossOrgActionError" in record.message for record in caplog.records)
