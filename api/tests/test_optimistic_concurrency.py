"""Optimistic concurrency on the five single-item mutations (task-13b-
brief.md): `PATCH /items/{id}`, approve, reject, unreject, `DELETE
/items/{id}`. A stale `Item.version` is refused with 409 rather than
silently letting a client overwrite a concurrent change -- the failure
mode Task 13's report recorded as a known limitation ("no optimistic
concurrency ... last-write-wins at the field level").

Deliberately excludes bulk-approve, set_scale, and undo/redo from the
CLIENT-SUPPLIED check (task-13b-brief.md's out-of-scope list) -- those
are covered here only insofar as they must not break the guarantee the
five in-scope mutations provide: every path that mutates an `Item` bumps
`version`, or a later single-item check could be fooled by a batch that
moved the row without telling the counter.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.takeoff import bulk, review, scale as scale_module, undo
from app.takeoff.models import Item, ReviewStatus, Warning, WarningReason


def _sign_in(client, email="dana@example.com", password="correct-horse"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _read_via_a_separate_session(query, params):
    """Read a row through a brand-new connection/session, never the `db`
    fixture the `client` fixture also uses -- `client` and `db` share one
    session in this harness, so asserting on `db`'s own view only proves
    a Python object agrees with itself, exactly what let Task 13's
    quantity-echo bug ship originally. Mirrors
    test_mutation_endpoints.py's helper of the same name and purpose.
    """
    engine = create_engine(settings.test_database_url)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        return session.execute(text(query), params).scalar_one()
    finally:
        session.close()
        engine.dispose()


# =========================================================================
# Each of the five mutations refuses a stale version with 409, and the
# row is genuinely unchanged afterwards.
# =========================================================================


def test_approve_refuses_a_stale_version(client, dana, project, sheet, item, db):
    db.commit()
    _sign_in(client)
    stale = item.version + 1

    response = client.post(f"/api/items/{item.id}/approve", headers={"If-Match": str(stale)})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_item_version"
    stored_status = _read_via_a_separate_session("select status from items where id = :id", {"id": str(item.id)})
    stored_version = _read_via_a_separate_session("select version from items where id = :id", {"id": str(item.id)})
    assert stored_status == "ready", "a refused approve must not have changed status"
    assert stored_version == 1, "a refused approve must not have bumped the version"


def test_reject_refuses_a_stale_version(client, dana, project, sheet, item, db):
    db.commit()
    _sign_in(client)
    stale = item.version + 1

    response = client.post(f"/api/items/{item.id}/reject", headers={"If-Match": str(stale)})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_item_version"
    stored_rejected_at = _read_via_a_separate_session("select rejected_at from items where id = :id", {"id": str(item.id)})
    assert stored_rejected_at is None, "a refused reject must not have touched the row"


def test_unreject_refuses_a_stale_version(client, dana, project, sheet, item, db):
    _sign_in(client)
    rejected = client.post(f"/api/items/{item.id}/reject", headers={"If-Match": str(item.version)}).json()
    current_version = rejected["item"]["version"]
    db.commit()

    response = client.post(
        f"/api/items/{item.id}/unreject", headers={"If-Match": str(current_version + 1)}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_item_version"
    stored_rejected_at = _read_via_a_separate_session("select rejected_at from items where id = :id", {"id": str(item.id)})
    assert stored_rejected_at is not None, "a refused unreject must leave the item rejected"


def test_edit_refuses_a_stale_version(client, dana, project, sheet, item, db):
    db.commit()
    _sign_in(client)
    stale = item.version + 1

    response = client.patch(
        f"/api/items/{item.id}", json={"notes": "should never land"}, headers={"If-Match": str(stale)}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_item_version"
    stored_notes = _read_via_a_separate_session("select notes from items where id = :id", {"id": str(item.id)})
    assert stored_notes == "", "a refused edit must not have changed the row"


def test_delete_refuses_a_stale_version(client, dana, project, sheet, item, db):
    db.commit()
    _sign_in(client)
    stale = item.version + 1

    response = client.delete(f"/api/items/{item.id}", headers={"If-Match": str(stale)})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_item_version"
    stored_id = _read_via_a_separate_session("select id from items where id = :id", {"id": str(item.id)})
    assert stored_id is not None, "a refused delete must not have removed the row"


# =========================================================================
# The version actually increments on every mutating path, including
# approve and delete.
# =========================================================================


def test_approve_increments_the_version(client, dana, project, sheet, item):
    _sign_in(client)
    # Captured before the request, not read inline in the assertion --
    # `client` and the `db` fixture share one session in this harness, so
    # `item` is the SAME identity-mapped object the service mutates.
    # `item.version` evaluated after the call already reflects the bump.
    original_version = item.version

    body = client.post(f"/api/items/{item.id}/approve", headers={"If-Match": str(original_version)}).json()

    assert body["item"]["version"] == original_version + 1


def test_reject_and_unreject_each_increment_the_version(client, dana, project, sheet, item):
    _sign_in(client)
    original_version = item.version

    rejected = client.post(f"/api/items/{item.id}/reject", headers={"If-Match": str(original_version)}).json()
    assert rejected["item"]["version"] == original_version + 1

    unrejected = client.post(
        f"/api/items/{item.id}/unreject", headers={"If-Match": str(rejected["item"]["version"])}
    ).json()
    assert unrejected["item"]["version"] == rejected["item"]["version"] + 1


def test_edit_increments_the_version(client, dana, project, sheet, item):
    _sign_in(client)
    original_version = item.version

    body = client.patch(
        f"/api/items/{item.id}", json={"notes": "checked"}, headers={"If-Match": str(original_version)}
    ).json()

    assert body["item"]["version"] == original_version + 1


def test_delete_increments_the_version_before_the_row_is_removed(db, dana, item):
    """delete_item()'s response carries no item -- there is no row left
    for ItemOut to describe -- so the increment can only be proven at the
    service level, against the in-memory object right after `_apply_delete()`
    runs and before the session ever flushes the deletion. This is the
    "including delete" half of the brief's requirement: delete
    participates in the same bump discipline as its four siblings, even
    though nothing downstream can read the bumped value back out.
    """
    original_version = item.version

    action = review.delete_item(db, dana, item, original_version)

    assert item.version == original_version + 1
    assert action.before.get("version") is None, (
        "version must never ride along in the recorded snapshot -- see concurrency.py"
    )


# =========================================================================
# A correct version succeeds and returns the new version, so a client can
# chain edits without refetching.
# =========================================================================


def test_a_correct_version_succeeds_and_chaining_works_without_a_refetch(client, dana, project, sheet, item):
    _sign_in(client)

    first = client.patch(
        f"/api/items/{item.id}", json={"notes": "first edit"}, headers={"If-Match": str(item.version)}
    ).json()
    assert first["item"]["notes"] == "first edit"

    # Chained directly off the previous response's version, never off a
    # fresh GET -- this is the whole point of returning it.
    second = client.patch(
        f"/api/items/{item.id}",
        json={"notes": "second edit"},
        headers={"If-Match": str(first["item"]["version"])},
    ).json()
    assert second["item"]["notes"] == "second edit"
    assert second["item"]["version"] == first["item"]["version"] + 1


# =========================================================================
# The refusal names the other reviewer when the action log has one, and
# reads sensibly when it does not.
# =========================================================================


def test_the_refusal_names_the_reviewer_whose_write_landed_first(client, dana, project, sheet, item):
    _sign_in(client)
    # Captured before the approve call -- `item` is the same identity-
    # mapped object the service mutates in this shared-session harness,
    # so reading `item.version` after the call would already show the
    # bumped value and the second request below would no longer be stale.
    original_version = item.version
    # Dana's own approval is itself "the other reviewer's write" from the
    # point of view of a second, now-stale request -- the copy names
    # whoever the action log's most recent row for this item credits,
    # not necessarily a literally different person.
    client.post(f"/api/items/{item.id}/approve", headers={"If-Match": str(original_version)})

    response = client.post(f"/api/items/{item.id}/reject", headers={"If-Match": str(original_version)})

    assert response.status_code == 409
    message = response.json()["detail"]["message"]
    assert "Dana Whitfield" in message
    assert "changed this item after you loaded it" in message


def test_the_refusal_reads_sensibly_with_no_prior_action(client, dana, project, sheet, item):
    """A stale version on an item with no recorded action at all (the
    version and the actual row simply never matched, rather than a real
    concurrent write) must not crash the actor lookup, and must fall back
    to copy that still makes sense without a name.
    """
    _sign_in(client)

    response = client.post(f"/api/items/{item.id}/approve", headers={"If-Match": str(item.version + 5)})

    assert response.status_code == 409
    message = response.json()["detail"]["message"]
    # The generic fallback reads "This item changed..." (no name) rather
    # than "<Name> changed this item...", so the shared substring both
    # branches carry is "after you loaded it," not "changed this item."
    assert message == (
        "This item changed after you loaded it. Refresh the sheet to see the current value, then try again."
    )
    assert "None" not in message


# =========================================================================
# If-Match is required, not optional.
# =========================================================================


def test_missing_if_match_header_is_refused_on_every_single_item_mutation(client, dana, project, sheet, item):
    _sign_in(client)

    assert client.post(f"/api/items/{item.id}/approve").status_code == 422
    assert client.post(f"/api/items/{item.id}/reject").status_code == 422
    assert client.post(f"/api/items/{item.id}/unreject").status_code == 422
    assert client.patch(f"/api/items/{item.id}", json={"notes": "x"}).status_code == 422
    assert client.delete(f"/api/items/{item.id}").status_code == 422


# =========================================================================
# Undo/redo bump the version forward; they never restore the old one.
# =========================================================================


def test_undo_bumps_the_version_forward_rather_than_restoring_the_old_one(db, dana, project, item):
    original_version = item.version
    review.approve_item(db, dana, item, original_version)
    db.flush()
    approved_version = item.version
    assert approved_version == original_version + 1

    undo.undo(db, dana, project.id)
    db.flush()

    assert item.status is ReviewStatus.READY, "undo must restore the semantic fields"
    assert item.version == approved_version + 1, (
        "undo is itself a mutation and must move the counter forward, "
        "never reset it to the pre-approval value"
    )
    assert item.version != original_version


def test_redo_also_bumps_the_version_forward(db, dana, project, item):
    review.approve_item(db, dana, item, item.version)
    db.flush()
    undo.undo(db, dana, project.id)
    db.flush()
    version_after_undo = item.version

    undo.redo(db, dana, project.id)
    db.flush()

    assert item.status is ReviewStatus.APPROVED
    assert item.version == version_after_undo + 1


def test_a_version_held_from_before_an_undo_is_stale_after_it(client, dana, project, sheet, item):
    """The concrete consequence of undo bumping forward: a client that
    loaded the item right after approving it, then watches a colleague
    undo that approval, must not be able to write again using the
    version it saw right after its own approve.
    """
    _sign_in(client)
    approve_body = client.post(
        f"/api/items/{item.id}/approve", headers={"If-Match": str(item.version)}
    ).json()
    version_the_client_saw = approve_body["item"]["version"]

    undo_response = client.post(f"/api/projects/{project.id}/undo")
    assert undo_response.json()["performed"] is True

    response = client.post(
        f"/api/items/{item.id}/reject", headers={"If-Match": str(version_the_client_saw)}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_item_version"


# =========================================================================
# Out of scope for the client-supplied check, but must not break the
# guarantee: bulk-approve and set_scale still bump the items they touch.
# =========================================================================


def test_bulk_approve_bumps_the_items_version_so_a_later_single_item_check_sees_it(
    db, dana, project, sheet
):
    extra = Item(
        project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name="Bulk-approved receptacle",
        system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY,
    )
    db.add(extra)
    db.flush()
    original_version = extra.version

    result = bulk.bulk_approve(db, dana, project.id, [extra.id])
    db.flush()

    assert extra.id in result.approved
    assert extra.version == original_version + 1, (
        "bulk-approve is out of scope for the per-item version CHECK, but it "
        "must still bump the counter -- otherwise a later single-item "
        "mutation checked against the stale original version would wrongly "
        "succeed even though the row already moved"
    )


def test_set_scale_bumps_released_items_version(db, dana, project, sheet):
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
    original_version = blocked.version

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert blocked.status is ReviewStatus.READY
    assert blocked.version == original_version + 1
