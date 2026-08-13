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

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.takeoff import bulk
from app.takeoff.models import Action, Item, ReviewStatus, Warning, WarningReason


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
    missing = _extra_item(db, project, sheet, ReviewStatus.MISSING, "Missing information item")
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
        json={"item_ids": [
            str(ready.id), str(attention.id), str(missing.id), str(already.id), str(rejected.id),
        ]},
    ).json()

    assert body["approved"] == [str(ready.id)]
    skipped_by_id = {row["item_id"]: row for row in body["skipped"]}

    # Needs attention and Missing information are two different skip
    # codes with two different recoveries, not one collapsed code --
    # CLAUDE.md's status vocabulary treats them as different states (one
    # resolvable by judgment call, one blocked with no override), and
    # bulk approval must preserve that distinction rather than merging
    # it into a single "not ready" bucket.
    assert skipped_by_id[str(attention.id)]["code"] == bulk.NEEDS_ATTENTION
    assert "attention" in skipped_by_id[str(attention.id)]["message"].lower()

    assert skipped_by_id[str(missing.id)]["code"] == bulk.MISSING_INFORMATION
    assert "resolve" in skipped_by_id[str(missing.id)]["message"].lower()

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


# =========================================================================
# Review round: findings from the Task 13 review
# =========================================================================


def _action_count(db, project_id):
    return len(db.scalars(select(Action).where(Action.project_id == project_id)).all())


def _read_via_a_separate_session(query, params):
    """Read a row through a brand-new connection/session, not the `db`
    fixture the `client` fixture also uses. `client` and `db` share one
    session in this harness (`client` overrides `get_db` with `lambda:
    db`), so asserting on `db`'s own view of a row only proves the
    Python object agrees with itself -- exactly what let review finding
    2 (the echoed-quantity divergence) ship originally. A second,
    independent connection can only see what was actually committed,
    which is the thing that matters here: what the *next* poll, from a
    *different* request and session, would actually read back.
    """
    engine = create_engine(settings.test_database_url)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        return session.execute(text(query), params).scalar_one()
    finally:
        session.close()
        engine.dispose()


# --- Finding 1: an empty or unknown-field PATCH wrote a phantom action ---


def test_empty_patch_is_refused_rather_than_writing_a_phantom_action(client, dana, project, sheet, item, db):
    """`PATCH {}` must not return 200 claiming an edit, write a row to the
    append-only action log, bump the version (forcing every other
    reviewer to re-fetch the whole snapshot), or add a no-op step to the
    *shared* undo stack whose tooltip would name an edit that never
    happened.
    """
    db.commit()
    _sign_in(client)
    before_count = _action_count(db, project.id)

    response = client.patch(f"/api/items/{item.id}", json={})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "no_changes_to_apply"
    assert _action_count(db, project.id) == before_count, "an empty patch must not write an action"


def test_patch_with_only_unknown_fields_is_refused_not_silently_ignored(client, dana, project, sheet, item, db):
    """`{"unit": "LF", "status": "approved"}` -- neither key is editable
    -- must not be silently reduced to an empty, successful no-op edit.
    `extra="forbid"` turns it into a 422 before the request ever reaches
    `review.edit_item()`.
    """
    db.commit()
    _sign_in(client)
    before_count = _action_count(db, project.id)

    response = client.patch(f"/api/items/{item.id}", json={"unit": "LF", "status": "approved"})

    assert response.status_code == 422
    assert _action_count(db, project.id) == before_count, "a refused patch must not write an action"

    stored_unit = _read_via_a_separate_session(
        "select unit from items where id = :id", {"id": str(item.id)}
    )
    assert stored_unit == "EA", "a refused patch must not silently change the row"


def test_a_mix_of_editable_and_unknown_fields_is_refused_wholesale(client, dana, project, sheet, item, db):
    """A body mixing one real editable field with one unknown key must
    not partially apply the editable one -- the whole request is
    malformed, not "apply what you understood."
    """
    db.commit()
    _sign_in(client)

    response = client.patch(f"/api/items/{item.id}", json={"quantity": "5.00", "unit": "LF"})

    assert response.status_code == 422
    stored_quantity = _read_via_a_separate_session(
        "select quantity from items where id = :id", {"id": str(item.id)}
    )
    assert stored_quantity == Decimal("14.00")


# --- Finding 2: the response echoed a quantity the database did not store ---


def test_editing_quantity_to_three_decimal_places_is_refused_not_silently_rounded(
    client, dana, project, sheet, item, db
):
    """`Item.quantity` is `Numeric(12, 2)`. Postgres would round a
    three-decimal-place value on write without complaint, and
    `SessionLocal`'s `expire_on_commit=False` means a mutation response
    built right after that write would have echoed back the un-rounded
    value the service was handed (184.559), not what the row actually
    stores (184.56) -- an estimator sees "Saved" against a number the bid
    total is not using, with no notice the value changed underneath
    them. The fix rejects the value outright rather than quantizing it:
    the person decides the rounding, not the database.
    """
    db.commit()
    _sign_in(client)

    response = client.patch(f"/api/items/{item.id}", json={"quantity": "184.559"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_quantity"
    assert "184.56" in response.json()["detail"]["message"]

    stored_quantity = _read_via_a_separate_session(
        "select quantity from items where id = :id", {"id": str(item.id)}
    )
    assert stored_quantity == Decimal("14.00"), "a refused edit must not have changed the stored row"


# --- Finding 3 (tenancy guard blind to routes outside /api) lives in
# test_tenancy.py, next to the guard it fixes. ---


# --- Finding 4: the quantity string contract accepted literals that
# silently change the number ---


def test_quantity_with_pep515_underscore_grouping_is_refused(client, dana, project, sheet, item, db):
    """Python's `Decimal()` honours PEP 515 underscore grouping, so
    `"14_0"` parses as 140 -- a silent 10x on a bid quantity. The wire
    contract is a plain decimal literal, not whatever `Decimal()` itself
    is willing to accept.
    """
    db.commit()
    _sign_in(client)

    response = client.patch(f"/api/items/{item.id}", json={"quantity": "14_0"})

    assert response.status_code == 422
    stored_quantity = _read_via_a_separate_session(
        "select quantity from items where id = :id", {"id": str(item.id)}
    )
    assert stored_quantity == Decimal("14.00")


def test_quantity_with_surrounding_whitespace_is_refused(client, dana, project, sheet, item, db):
    """`Decimal()` strips surrounding whitespace, so `"  14 "` silently
    parses as plain 14 -- fine in this specific case, but not a contract
    a client should be able to rely on to smuggle formatting through.
    """
    db.commit()
    _sign_in(client)

    response = client.patch(f"/api/items/{item.id}", json={"quantity": "  14 "})

    assert response.status_code == 422


def test_quantity_in_scientific_notation_is_refused(client, dana, project, sheet, item, db):
    """`"1e-40"` is a syntactically valid `Decimal` literal that rounds
    to 0.00 once it reaches `Numeric(12, 2)` -- silently discarding
    whatever quantity the estimator actually meant to enter.
    """
    db.commit()
    _sign_in(client)

    response = client.patch(f"/api/items/{item.id}", json={"quantity": "1e-40"})

    assert response.status_code == 422
    stored_quantity = _read_via_a_separate_session(
        "select quantity from items where id = :id", {"id": str(item.id)}
    )
    assert stored_quantity == Decimal("14.00")


def test_quantity_as_a_plain_decimal_string_still_works(client, dana, project, sheet, item):
    """The stricter literal check must not reject the ordinary case --
    only reject the surprising ones.
    """
    _sign_in(client)

    body = client.patch(f"/api/items/{item.id}", json={"quantity": "184.55"}).json()

    assert body["item"]["quantity"] == "184.55"


# --- Finding 5: a fifth bulk-approve skip code with no copy would 500
# on a request whose writes had already committed ---


def test_an_unmapped_skip_code_falls_back_to_generic_copy_instead_of_a_bare_keyerror(monkeypatch, client, dana, project, sheet, db):
    """Simulates bulk.py reporting a skip code this endpoint's copy table
    doesn't know about -- the scenario a fifth code landing in bulk.py
    without a matching `_SKIP_COPY` entry would produce. Must not raise
    `KeyError` after the batch's real approvals have already been
    committed; must fall back to generic copy instead.
    """
    from app.takeoff import mutations as mutations_module

    ready = _extra_item(db, project, sheet, ReviewStatus.READY, "Ready item")
    mystery_id = uuid_module.uuid4()
    original_bulk_approve = bulk.bulk_approve

    def _bulk_approve_with_a_mystery_skip(db_, actor, project_id, item_ids):
        result = original_bulk_approve(db_, actor, project_id, item_ids)
        result.skipped[mystery_id] = "some_future_code_nobody_added_copy_for"
        return result

    monkeypatch.setattr(mutations_module.bulk, "bulk_approve", _bulk_approve_with_a_mystery_skip)
    _sign_in(client)

    response = client.post(
        f"/api/projects/{project.id}/items/bulk-approve", json={"item_ids": [str(ready.id)]}
    )

    assert response.status_code == 200, "an unmapped skip code must not turn into a 500 after a real commit"
    skipped_by_id = {row["item_id"]: row for row in response.json()["skipped"]}
    assert skipped_by_id[str(mystery_id)]["message"] == mutations_module._GENERIC_SKIP_MESSAGE


def test_the_skip_copy_table_is_total_against_bulks_known_codes():
    """The import-time half of the fix: catches a missing entry at
    collection time rather than waiting for a request to hit it.
    """
    from app.takeoff import mutations as mutations_module

    assert set(mutations_module._SKIP_COPY) == bulk.SKIP_CODES


# --- Finding 6: `not_ready_to_review` collapsed two different statuses
# with two different recoveries; covered end-to-end in
# test_bulk_approve_reports_each_skip_with_a_code_and_estimator_facing_copy
# above, which now asserts NEEDS_ATTENTION and MISSING_INFORMATION
# separately with their own copy. ---
