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
from app.takeoff import snapshot as snapshot_module
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

    review.approve_item(db, dana, item, item.version)
    db.flush()

    again = client.get(f"/api/projects/{project.id}/snapshot", headers={"If-None-Match": etag})
    assert again.status_code == 200


def test_no_response_field_exposes_processing_internals(client, db, dana, project, sheet, item):
    """A substring scan over the whole JSON body. This can false-positive
    on legitimate estimator content (an item genuinely named "Model 400
    panel" would trip "model") -- noted as a known limitation rather than
    weakened, per the brief.

    The `item` fixture alone has `evidence=None` and `notes=""`, so a scan
    against it can't fail no matter what the response actually contains --
    there's nothing there to leak from. Seeding a populated `evidence` blob
    (and a warning, which carries its own free-text fields) gives the scan
    something a real regression would actually show up in.
    """
    item.evidence = {"sheet": "E2.1", "excerpt": "Title block scale note, grid D-2"}
    db.add(Warning(item_id=item.id, reason=WarningReason.SCALE, title="Scale needs confirmation",
                    found="E2.1 shows two scale labels.", why="Measured conduit lengths may be wrong.",
                    fix="Select the scale that applies to this sheet.", where_="E2.1 title block"))
    db.flush()

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

    review.approve_item(db, dana, item, item.version)
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
    assert len(found_item["warnings"]) == 1
    assert found_item["warnings"][0]["id"] == str(warning.id)
    assert found_item["warnings"][0]["reason"] == "scale"
    assert found_item["warnings"][0]["title"] == "Scale needs confirmation"
    assert found_item["warnings"][0]["where"] == "E2.1 title block"
    assert found_item["status"] == "missing"


def test_an_item_with_two_live_warnings_returns_both_in_a_stable_order(client, db, dana, project, sheet, item):
    """Task 9's exact case: an item blocked by both a scale and a legend
    warning at once (tests/test_undo_redo.py exercises this at the service
    layer). `ItemOut.warnings` is a list precisely so neither warning is
    silently dropped -- and the order (Warning.reason, Warning.id) is
    queried explicitly so it can't shift between polls as Postgres's own
    row order changes, the way an unordered dict keyed by item id would.
    """
    legend = Warning(item_id=item.id, reason=WarningReason.LEGEND, title="Symbol not in legend",
                      found="This symbol does not appear in the E0.1 legend.",
                      why="It cannot be counted without knowing what it is.",
                      fix="Classify the symbol or confirm it against the legend.", where_="E0.1 legend")
    scale = Warning(item_id=item.id, reason=WarningReason.SCALE, title="Scale needs confirmation",
                     found="E2.1 shows two scale labels.", why="Measured conduit lengths may be wrong.",
                     fix="Select the scale that applies to this sheet.", where_="E2.1 title block")
    # Added in legend-then-scale order deliberately, to prove the response
    # order comes from the query's ORDER BY (reason, id) rather than
    # insertion order or the identity map's own bookkeeping.
    item.status = ReviewStatus.MISSING
    db.add_all([legend, scale])
    db.flush()

    _sign_in(client)
    body_first = client.get(f"/api/projects/{project.id}/snapshot").json()
    body_second = client.get(f"/api/projects/{project.id}/snapshot").json()

    for body in (body_first, body_second):
        found_item = next(i for i in body["items"] if i["id"] == str(item.id))
        warnings = found_item["warnings"]
        assert len(warnings) == 2
        # Postgres native enums order by declaration position, not
        # lexically -- WarningReason declares SCALE before LEGEND
        # (app/takeoff/models.py), so "scale" sorts first here even though
        # "legend" < "scale" as plain strings. Asserting the actual order
        # (rather than assuming alphabetical) is the point: this proves
        # the response order tracks the query's ORDER BY, not a fluke of
        # insertion order (legend was added to the session first, above)
        # or the identity map's own bookkeeping.
        assert [w["reason"] for w in warnings] == ["scale", "legend"]
        assert warnings[0]["id"] == str(scale.id)
        assert warnings[1]["id"] == str(legend.id)


def test_approved_item_carries_the_approving_users_name_and_rejected_defaults_false(client, db, dana, project, sheet, item):
    review.approve_item(db, dana, item, item.version)
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


# =========================================================================
# Fix round: findings from the Task 11 review
# =========================================================================

# --- Important 1: version() must be computed exactly once per request, and
# the same string must back both the ETag header and the response body.
# Computing it a second time as the last thing build() does is a real bug
# under READ COMMITTED (each statement takes its own fresh snapshot, so a
# concurrent commit landing mid-build() can produce a body whose version
# already accounts for a change the body's own item list doesn't carry
# yet) -- not reproducible against the test harness's single uncommitted
# transaction, so this pins the invariant instead of trying to force the
# race. ---


def test_version_is_computed_exactly_once_and_backs_both_the_header_and_the_body(
    client, dana, project, sheet, item, monkeypatch
):
    calls = []
    original_version = snapshot_module.version

    def counting_version(db, project_id):
        calls.append(project_id)
        return original_version(db, project_id)

    monkeypatch.setattr(snapshot_module, "version", counting_version)
    _sign_in(client)

    response = client.get(f"/api/projects/{project.id}/snapshot")

    assert response.status_code == 200
    assert len(calls) == 1, f"version() ran {len(calls)} times in one request; it must run exactly once"
    assert response.json()["version"] == response.headers["etag"]


# --- Important 2: an item with two live warnings must return both, in a
# stable order -- see test_an_item_with_two_live_warnings_returns_both_in_a_
# stable_order() above, alongside the other item-level warning tests. ---


# --- Important 3: authenticated, tenant-scoped, ETagged responses must
# never be cacheable by a shared cache. A session cookie alone does not
# make a response private under RFC 7234. ---


def test_authenticated_responses_carry_no_store_cache_headers(client, dana, project, sheet, item):
    _sign_in(client)

    response = client.get(f"/api/projects/{project.id}/snapshot")

    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"


def test_a_304_response_also_carries_no_store_cache_headers(client, dana, project, sheet, item):
    _sign_in(client)
    etag = client.get(f"/api/projects/{project.id}/snapshot").headers["etag"]

    response = client.get(f"/api/projects/{project.id}/snapshot", headers={"If-None-Match": etag})

    assert response.status_code == 304
    assert response.headers["cache-control"] == "private, no-store"


# --- Minor 4: nothing must ever let a 304 short-circuit ahead of the
# tenancy gate. The code already orders load_project() before version(),
# which is correct -- this pins that ordering against a future refactor
# that hoists the If-None-Match check above it, which would reintroduce
# exactly the existence oracle the 404 exists to remove. ---


def test_a_304_never_bypasses_the_tenancy_gate(client, dana, db):
    _sign_in(client)
    other_project = _foreign_project(db)

    response = client.get(
        f"/api/projects/{other_project.id}/snapshot",
        headers={"If-None-Match": "anything-at-all"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project_not_found"


# --- Minor 5: item order in the snapshot must be deterministic across
# polls, matching the ordering already applied to sheets. ---


def test_item_order_is_stable_across_repeated_polls(client, dana, project, sheet, item, db):
    second = Item(project_id=project.id, sheet_id=sheet.id, symbol="switch", name="Single-pole switch",
                  system="Power", category="Devices", quantity=6, unit="EA", status=ReviewStatus.READY)
    db.add(second)
    db.flush()

    _sign_in(client)
    first_order = [i["id"] for i in client.get(f"/api/projects/{project.id}/snapshot").json()["items"]]
    second_order = [i["id"] for i in client.get(f"/api/projects/{project.id}/snapshot").json()["items"]]

    assert first_order == second_order
    assert set(first_order) == {str(item.id), str(second.id)}
