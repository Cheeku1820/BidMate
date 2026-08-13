"""The nine mutation endpoints: PATCH /items/{id}, approve/reject/unreject,
DELETE /items/{id}, bulk-approve, scale, undo, redo.

The plan's sketch (docs/superpowers/plans/2026-08-07-backend-spine.md, Task
13) tests two things: the server-side missing-information refusal, and that
its copy names a recovery action. Everything else here comes from
task-13-brief.md's corrections:

- quantity travels as a JSON string, never a bare JSON number (decision 1)
- an explicit `notes: null` must reach review._validate_edit()'s refusal,
  not be silently dropped by exclude_none=True (decision 2)
- every mutation response is an explicit Pydantic model carrying the action
  label, the new version, and the affected state (decision 3)
- bulk-approve's skip codes carry estimator-facing copy, not bare machine
  codes (decision 4)
- undo/redo distinguish "nothing to undo" from "undone" with an explicit
  flag, not a null label ("Also required")
"""

import uuid as uuid_module
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text

from app.takeoff import bulk
from app.takeoff.models import Item, ReviewStatus, Warning, WarningReason


def _sign_in(client):
    response = client.post("/api/auth/login", json={"email": "dana@example.com", "password": "correct-horse"})
    assert response.status_code == 200, response.text


# --- The plan's two, verbatim ---


def test_approving_a_missing_information_item_is_refused_by_the_server(client, dana, project, sheet, item, db):
    item.status = ReviewStatus.MISSING
    db.flush()
    _sign_in(client)

    response = client.post(f"/api/items/{item.id}/approve")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "missing_information_blocks_approval"


def test_the_refusal_copy_names_a_recovery_action(client, dana, project, sheet, item, db):
    item.status = ReviewStatus.MISSING
    db.flush()
    _sign_in(client)

    message = client.post(f"/api/items/{item.id}/approve").json()["detail"]["message"]

    assert "Resolve the warning" in message
    assert "something went wrong" not in message.lower()


# --- Response shape (decision 3): label + version + affected state ---


def test_approve_returns_the_action_label_the_new_version_and_the_updated_item(client, dana, project, sheet, item):
    _sign_in(client)

    body = client.post(f"/api/items/{item.id}/approve").json()

    assert body["label"] == f"Approved {item.name}"
    assert body["version"]
    assert body["item"]["id"] == str(item.id)
    assert body["item"]["status"] == "approved"
    assert body["item"]["approved_by"] == "Dana Whitfield"


def test_approve_response_version_matches_what_the_next_snapshot_poll_would_return(
    client, dana, project, sheet, item
):
    _sign_in(client)

    approve_body = client.post(f"/api/items/{item.id}/approve").json()
    snapshot = client.get(f"/api/projects/{project.id}/snapshot")

    # The mutation's own version is authoritative and current: polling
    # again with it as If-None-Match must 304, proving the client's own
    # response already reflects the state a poll would return, rather
    # than needing a second round trip to catch up.
    again = client.get(
        f"/api/projects/{project.id}/snapshot", headers={"If-None-Match": approve_body["version"]}
    )
    assert again.status_code == 304
    assert snapshot.headers["etag"] == approve_body["version"]


def test_reject_and_unreject_round_trip_through_the_endpoint(client, dana, project, sheet, item):
    _sign_in(client)

    rejected = client.post(f"/api/items/{item.id}/reject").json()
    assert rejected["item"]["rejected"] is True
    assert rejected["label"] == f"Rejected {item.name}"

    restored = client.post(f"/api/items/{item.id}/unreject").json()
    assert restored["item"]["rejected"] is False
    assert restored["label"] == f"Restored {item.name}"


def test_delete_returns_no_item_since_none_remains(client, dana, project, sheet, item):
    _sign_in(client)

    body = client.delete(f"/api/items/{item.id}").json()

    assert body["item"] is None
    assert body["label"] == f"Deleted {item.name}"
    assert body["version"]

    snapshot = client.get(f"/api/projects/{project.id}/snapshot").json()
    assert all(i["id"] != str(item.id) for i in snapshot["items"])


# --- Quantity: Decimal in, string on the wire (decision 1) ---


def test_editing_quantity_as_a_json_string_round_trips_exactly(client, dana, project, sheet, item):
    _sign_in(client)

    body = client.patch(f"/api/items/{item.id}", json={"quantity": "184.55"}).json()

    assert body["item"]["quantity"] == "184.55"


def test_editing_quantity_as_a_bare_json_number_is_refused(client, dana, project, sheet, item):
    """A float must never touch the quantity path -- not even transiently
    on the way to Decimal. The API boundary refuses a JSON number outright
    rather than trusting pydantic's float-to-Decimal coercion to stay
    lossless for every value a client might send.
    """
    _sign_in(client)

    response = client.patch(f"/api/items/{item.id}", json={"quantity": 184.55})

    assert response.status_code == 422


def test_editing_quantity_to_a_negative_string_is_refused_by_the_service(client, dana, project, sheet, item):
    """A negative quantity is a valid Decimal literal, so it passes
    pydantic's own coercion -- it is `review._validate_edit()`'s job to
    refuse it, with recovery copy, not the API boundary's. Confirms that
    rule is actually reachable over HTTP once quantity travels as a
    string, not bypassed by the stricter string-only contract above.
    """
    _sign_in(client)

    response = client.patch(f"/api/items/{item.id}", json={"quantity": "-5"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_quantity"
    assert "cannot be negative" in response.json()["detail"]["message"]


def test_editing_quantity_as_a_bare_json_int_is_also_refused(client, dana, project, sheet, item):
    _sign_in(client)

    response = client.patch(f"/api/items/{item.id}", json={"quantity": 184})

    assert response.status_code == 422


def test_a_rejected_quantity_edit_leaves_the_stored_row_untouched(client, dana, project, sheet, item, db):
    _sign_in(client)

    client.patch(f"/api/items/{item.id}", json={"quantity": 184.55})

    row = db.execute(
        text("select quantity from items where id = :id"), {"id": str(item.id)}
    ).scalar_one()
    assert row == Decimal("14.00")


# --- notes: null must reach the service, not be silently dropped (decision 2) ---


def test_editing_notes_to_explicit_null_is_refused_by_the_service_not_silently_ignored(
    client, dana, project, sheet, item
):
    _sign_in(client)

    response = client.patch(f"/api/items/{item.id}", json={"notes": None})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "field_cannot_be_empty"
    assert "Notes cannot be removed entirely" in response.json()["detail"]["message"]


def test_editing_notes_to_an_empty_string_clears_it(client, dana, project, sheet, item):
    _sign_in(client)

    body = client.patch(f"/api/items/{item.id}", json={"notes": ""}).json()

    assert body["item"]["notes"] == ""


def test_omitting_notes_entirely_does_not_touch_it(client, dana, project, sheet, item, db):
    item.notes = "existing note"
    db.flush()
    _sign_in(client)

    body = client.patch(f"/api/items/{item.id}", json={"system": "Lighting"}).json()

    assert body["item"]["notes"] == "existing note"


# --- Bulk approve: skip codes carry estimator-facing copy (decision 4) ---


def _extra_item(db, project, sheet, status, name, **kwargs):
    fields = {
        "project_id": project.id, "sheet_id": sheet.id, "symbol": "switch", "name": name,
        "system": "Lighting", "category": "Devices", "quantity": 1, "unit": "EA", "status": status,
    }
    fields.update(kwargs)
    i = Item(**fields)
    db.add(i)
    db.flush()
    return i


def test_bulk_approve_reports_each_skip_with_a_code_and_estimator_facing_copy(client, dana, project, sheet, db):
    ready = _extra_item(db, project, sheet, ReviewStatus.READY, "Ready item")
    attention = _extra_item(db, project, sheet, ReviewStatus.ATTENTION, "Attention item")
    already = _extra_item(
        db, project, sheet, ReviewStatus.APPROVED, "Already approved item",
        approved_at=datetime.now(timezone.utc),
    )
    rejected = _extra_item(
        db, project, sheet, ReviewStatus.READY, "Rejected item",
        rejected_at=datetime.now(timezone.utc),
    )
    _sign_in(client)

    body = client.post(
        f"/api/projects/{project.id}/items/bulk-approve",
        json={"item_ids": [str(ready.id), str(attention.id), str(already.id), str(rejected.id)]},
    ).json()

    assert body["approved"] == [str(ready.id)]
    skipped_by_id = {row["item_id"]: row for row in body["skipped"]}

    assert skipped_by_id[str(attention.id)]["code"] == bulk.NOT_READY_TO_REVIEW
    assert "resolve" in skipped_by_id[str(attention.id)]["message"].lower()

    assert skipped_by_id[str(already.id)]["code"] == bulk.ALREADY_APPROVED
    assert "colleague" in skipped_by_id[str(already.id)]["message"].lower()

    assert skipped_by_id[str(rejected.id)]["code"] == bulk.REJECTED
    assert "restore" in skipped_by_id[str(rejected.id)]["message"].lower()

    for row in body["skipped"]:
        assert "successfully" not in row["message"].lower()
        assert "please" not in row["message"].lower()


def test_bulk_approve_reports_not_in_project_with_estimator_facing_copy(client, dana, project, sheet):
    """The fourth skip code -- an id the batch was asked to approve that
    does not resolve to a real item in this project at all (never
    existed, or belongs to a different project entirely).
    """
    _sign_in(client)
    missing_id = uuid_module.uuid4()

    body = client.post(
        f"/api/projects/{project.id}/items/bulk-approve", json={"item_ids": [str(missing_id)]}
    ).json()

    assert body["approved"] == []
    row = body["skipped"][0]
    assert row["item_id"] == str(missing_id)
    assert row["code"] == bulk.NOT_IN_PROJECT
    assert "refresh" in row["message"].lower()


def test_bulk_approve_response_carries_a_full_snapshot(client, dana, project, sheet, db):
    ready = _extra_item(db, project, sheet, ReviewStatus.READY, "Ready item")
    _sign_in(client)

    body = client.post(
        f"/api/projects/{project.id}/items/bulk-approve", json={"item_ids": [str(ready.id)]}
    ).json()

    assert body["snapshot"]["version"]
    ids = {i["id"] for i in body["snapshot"]["items"]}
    assert str(ready.id) in ids
    matched = next(i for i in body["snapshot"]["items"] if i["id"] == str(ready.id))
    assert matched["status"] == "approved"


# --- Scale confirmation ---


def test_set_scale_returns_the_action_label_and_a_snapshot_with_released_items(client, dana, project, sheet, db):
    blocked = Item(
        project_id=project.id, sheet_id=sheet.id, symbol="run", name='2" EMT conduit run',
        system="Power", category="Conduit and wire", quantity=184, unit="LF",
        status=ReviewStatus.MISSING, path=[[186, 226], [186, 430]],
    )
    db.add(blocked)
    db.flush()
    db.add(Warning(
        item_id=blocked.id, reason=WarningReason.SCALE, title="Missing scale reference",
        found="No scale label was found.", why="This run could not be measured.",
        fix="Set the drawing scale.", where_="E1.1 title block",
    ))
    db.flush()
    _sign_in(client)

    body = client.post(f"/api/sheets/{sheet.id}/scale", json={"value": "1/8\" = 1'-0\""}).json()

    assert "Set scale on" in body["label"]
    matched = next(i for i in body["snapshot"]["items"] if i["id"] == str(blocked.id))
    assert matched["status"] == "ready"
    assert matched["warnings"] == []


# --- Undo/redo: "nothing to undo" is explicit, not a null label ---


def test_undo_with_nothing_to_undo_says_so_explicitly(client, dana, project, sheet, item):
    _sign_in(client)

    body = client.post(f"/api/projects/{project.id}/undo").json()

    assert body["performed"] is False
    assert body["label"] is None
    assert body["snapshot"] is None


def test_undo_after_an_approve_reports_performed_true_with_a_label_and_a_snapshot(
    client, dana, project, sheet, item
):
    _sign_in(client)
    client.post(f"/api/items/{item.id}/approve")

    body = client.post(f"/api/projects/{project.id}/undo").json()

    assert body["performed"] is True
    assert body["label"] == f"Undid: Approved {item.name}"
    matched = next(i for i in body["snapshot"]["items"] if i["id"] == str(item.id))
    assert matched["status"] == "ready"


def test_redo_with_nothing_to_redo_says_so_explicitly(client, dana, project, sheet, item):
    _sign_in(client)

    body = client.post(f"/api/projects/{project.id}/redo").json()

    assert body["performed"] is False
    assert body["label"] is None
    assert body["snapshot"] is None


def test_redo_after_an_undo_reapplies_the_action(client, dana, project, sheet, item):
    _sign_in(client)
    client.post(f"/api/items/{item.id}/approve")
    client.post(f"/api/projects/{project.id}/undo")

    body = client.post(f"/api/projects/{project.id}/redo").json()

    assert body["performed"] is True
    assert body["label"] == f"Redid: Approved {item.name}"
    matched = next(i for i in body["snapshot"]["items"] if i["id"] == str(item.id))
    assert matched["status"] == "approved"


# --- Edit unblocks Needs attention when the missing field is supplied ---


def test_edit_response_reflects_a_status_change_caused_by_the_edit(client, dana, project, sheet, db):
    unclassified = _extra_item(
        db, project, sheet, ReviewStatus.ATTENTION, "Unclassified symbol", category="Unclassified",
    )
    _sign_in(client)

    body = client.patch(f"/api/items/{unclassified.id}", json={"category": "Devices"}).json()

    assert body["item"]["status"] == "ready"
