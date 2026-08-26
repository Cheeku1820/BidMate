"""`Presence`, its heartbeat and active-window query, `PUT /api/presence`,
and `collab.service.presence_signal` -- the seam `snapshot.version()` folds
in so a colleague's remote selection can bump the ETag even though a
heartbeat writes no `Action` row (task-11-brief.md, decision 3).

The plan's three tests (docs/superpowers/plans/2026-08-07-backend-spine.md,
Task 12) are a floor -- see task-12-brief.md for the five corrections
applied here: migration 0006 not 0005, `presence_signal` must fingerprint
the active *set* rather than `max(seen_at)` (a signal keyed on `seen_at`
changes on every heartbeat and defeats the ETag whenever anyone is using
the project), `datetime.now(timezone.utc)` not `datetime.utcnow()`
throughout, an upsert rather than get-then-add to survive concurrent
heartbeats, and `exclude` filtered in SQL rather than in Python.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.auth.passwords import hash_password
from app.collab.service import ACTIVE_WINDOW, active_presence, heartbeat, presence_signal
from app.identity.models import Org, User
from app.takeoff.models import Project


def _sign_in(client, email="dana@example.com", password="correct-horse"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _foreign_project(db):
    """A project in an org `dana` has no membership in -- for the tenancy
    test. Matches test_snapshot.py's and test_undo_redo.py's
    `_foreign_project`."""
    other_org = Org(name="Ferrovia Electric")
    db.add(other_org)
    db.flush()
    other_project = Project(org_id=other_org.id, name="A different firm's project", revision_set_label="")
    db.add(other_project)
    db.flush()
    return other_project


def _colleague(db, org):
    """A second reviewer in `dana`'s own org -- for the "another reviewer
    shows up in presence" tests. No shared fixture for this exists yet
    (every other test file needing a second party only ever needed one in
    a *different* org, for tenancy), so it is local to this file rather
    than speculatively added to conftest.py.
    """
    u = User(org_id=org.id, email="priya@example.com", password_hash=hash_password("correct-horse"),
             name="Priya Nakamura", color="#c65911")
    db.add(u)
    db.flush()
    return u


# --- The plan's three, adjusted per the brief (timezone-aware throughout) ---


def test_a_heartbeat_shows_up_for_other_reviewers(db, org, project, sheet):
    colleague = _colleague(db, org)
    heartbeat(db, colleague, project.id, sheet.id, None)
    db.flush()

    seen = active_presence(db, project.id, exclude=None)

    assert seen[0].name == "Priya Nakamura"
    assert seen[0].sheet_id == sheet.id


def test_your_own_presence_is_excluded(db, dana, project, sheet):
    heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()

    assert active_presence(db, project.id, exclude=dana.id) == []


def test_stale_presence_disappears(db, dana, project, sheet):
    presence = heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()
    presence.seen_at = datetime.now(timezone.utc) - ACTIVE_WINDOW - timedelta(seconds=1)
    db.flush()

    assert active_presence(db, project.id, exclude=None) == []


# --- presence_signal, both directions (brief item 1 -- the finding most
# likely to be shipped broken) ---


def test_presence_signal_is_unchanged_by_a_heartbeat_that_moves_nothing(db, dana, project, sheet):
    heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()
    first = presence_signal(db, project.id)

    # A second heartbeat for the same user, same sheet, same item: the
    # active *set* -- (user_id, sheet_id, item_id) -- is identical, only
    # seen_at moved. A signal keyed on seen_at would change here; a
    # signal keyed on the set must not.
    heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()
    second = presence_signal(db, project.id)

    assert first == second


def test_presence_signal_changes_when_the_active_set_changes(db, dana, project, sheet, item):
    heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()
    before_selection = presence_signal(db, project.id)

    heartbeat(db, dana, project.id, sheet.id, item.id)
    db.flush()
    after_selection = presence_signal(db, project.id)

    assert before_selection != after_selection


def test_presence_signal_ignores_stale_rows(db, dana, project, sheet):
    baseline = presence_signal(db, project.id)

    presence = heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()
    presence.seen_at = datetime.now(timezone.utc) - ACTIVE_WINDOW - timedelta(seconds=1)
    db.flush()

    stale = presence_signal(db, project.id)
    assert stale == baseline


def test_presence_signal_tolerates_a_mix_of_null_and_real_sheet_ids(db, dana, org, project, sheet):
    """Sorting the fingerprint's tuples before hashing has to work when
    some rows carry `None` for `sheet_id`/`item_id` and others carry a
    real uuid in the same column -- a naive sort over raw values (rather
    than a uniform string conversion first) raises `TypeError` comparing
    `None` to a `UUID` the moment two rows exist. This test's two
    reviewers guarantee exactly that mix once both have heartbeat.
    """
    colleague = _colleague(db, org)
    heartbeat(db, dana, project.id, None, None)
    heartbeat(db, colleague, project.id, sheet.id, None)
    db.flush()

    signal = presence_signal(db, project.id)  # must not raise
    assert isinstance(signal, str) and signal


# --- Tenancy: a write gets the same gate as a read ---


def test_put_presence_for_another_orgs_project_is_refused_with_the_same_404(client, dana, db):
    _sign_in(client)
    other_project = _foreign_project(db)

    response = client.put("/api/presence", json={"project_id": str(other_project.id)})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project_not_found"


def test_put_presence_requires_authentication(client, project):
    response = client.put("/api/presence", json={"project_id": str(project.id)})
    assert response.status_code == 401


# --- The upsert: concurrent heartbeats must not collide ---


def test_two_heartbeats_for_the_same_user_produce_one_row_with_the_latest_sheet(db, dana, project, sheet):
    other_sheet_id = uuid.uuid4()

    heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()
    heartbeat(db, dana, project.id, other_sheet_id, None)
    db.flush()

    rows = active_presence(db, project.id, exclude=None)
    assert len(rows) == 1
    assert rows[0].sheet_id == other_sheet_id


def test_the_upsert_survives_two_heartbeats_in_the_same_flush(db, dana, project, sheet):
    """The failure mode the brief names explicitly: two heartbeats for the
    same (user_id, project_id) -- the same reviewer in two tabs, or a
    retry -- both landing before either has a chance to be read back.
    get-then-add loses this race with an IntegrityError on the composite
    primary key; a single upsert statement does not.
    """
    from app.collab.models import Presence
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.now(timezone.utc)
    stmt = pg_insert(Presence).values(
        user_id=dana.id, project_id=project.id, sheet_id=sheet.id, item_id=None, seen_at=now
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Presence.user_id, Presence.project_id],
        set_={"sheet_id": stmt.excluded.sheet_id, "item_id": stmt.excluded.item_id, "seen_at": stmt.excluded.seen_at},
    )
    db.execute(stmt)
    db.execute(stmt)
    db.flush()

    rows = active_presence(db, project.id, exclude=None)
    assert len(rows) == 1


def test_heartbeat_refreshes_the_identity_mapped_instance_when_a_reference_is_held(db, dana, project, sheet):
    """The identity-map staleness hazard from Task 10, reproduced with the
    precondition made explicit rather than left to GC timing.

    `Presence`'s identity map entries are held by weak reference. The
    test above (`test_two_heartbeats_for_the_same_user_produce_one_row_
    with_the_latest_sheet`) calls `heartbeat()` twice but never assigns
    the first call's return value to a name, so nothing keeps that
    instance alive between the two calls -- it is immediately eligible
    for collection, the identity map drops it, and the second call's
    `RETURNING` naturally builds a fresh object. That test would pass
    whether or not `heartbeat()` refreshes a live instance, which is
    exactly why it did not catch this: it exercises the bug's absence by
    accident of GC timing, not by construction. This test holds a live
    reference across both calls -- the same reviewer's browser tab would,
    in practice, hold onto whatever `heartbeat()` last returned -- so the
    identity map cannot drop the first instance, and the assertions below
    only pass if `heartbeat()` actually refreshes it in place.

    Also asserts the raw row via `text()`, bypassing the ORM identity map
    entirely, so a failure here can be told apart from a broken upsert: if
    the raw row were wrong too, the fix would be to the upsert statement,
    not to how the ORM reads its own result back.
    """
    other_sheet_id = uuid.uuid4()

    first = heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()
    held_reference = first  # kept alive deliberately -- see docstring

    second = heartbeat(db, dana, project.id, other_sheet_id, None)
    db.flush()

    assert second.sheet_id == other_sheet_id
    # Same identity-mapped instance (same primary key), refreshed in
    # place -- not merely a second, separately-correct object that leaves
    # `held_reference` (and anything else in the session still holding a
    # reference to the first call's result) pointing at stale data.
    assert held_reference.sheet_id == other_sheet_id

    # The read side: a fresh ORM query in the same session must not be
    # poisoned by a stale identity-mapped instance.
    rows = active_presence(db, project.id, exclude=None)
    assert rows[0].sheet_id == other_sheet_id

    # The write side, independently: raw SQL, no ORM identity map
    # involved at all. Distinguishes "the write is fine, only the ORM's
    # read of its own result was stale" (the actual bug here) from "the
    # upsert itself wrote the wrong value" (a different bug, in the SQL,
    # not in how the result is materialized).
    raw = db.execute(
        text("select sheet_id from presence where user_id = :uid and project_id = :pid"),
        {"uid": dana.id, "pid": project.id},
    ).one()
    assert raw.sheet_id == other_sheet_id


# --- A stale row disappears from both active_presence and presence_signal
# at once, with no write required -- the whole point of computing the
# signal at request time against seen_at >= cutoff rather than storing it ---


def test_a_stale_row_is_absent_from_active_presence_and_from_the_signal(db, dana, project, sheet):
    presence = heartbeat(db, dana, project.id, sheet.id, None)
    db.flush()
    fresh_signal = presence_signal(db, project.id)
    assert active_presence(db, project.id, exclude=None) != []

    presence.seen_at = datetime.now(timezone.utc) - ACTIVE_WINDOW - timedelta(seconds=1)
    db.flush()

    assert active_presence(db, project.id, exclude=None) == []
    assert presence_signal(db, project.id) != fresh_signal


# --- /snapshot actually carries presence now that the stub is gone ---


def test_snapshot_carries_a_colleagues_presence_with_name_and_color(client, db, dana, org, project, sheet):
    colleague = _colleague(db, org)
    heartbeat(db, colleague, project.id, sheet.id, None)
    db.flush()

    _sign_in(client)
    body = client.get(f"/api/projects/{project.id}/snapshot").json()

    assert len(body["presence"]) == 1
    assert body["presence"][0]["name"] == "Priya Nakamura"
    assert body["presence"][0]["color"] == "#c65911"
    assert body["presence"][0]["sheet_id"] == str(sheet.id)


def test_put_presence_endpoint_writes_a_row_the_next_snapshot_carries(client, db, dana, org, project, sheet):
    """A second `TestClient` against the same app -- its own cookie jar
    (so it signs in as a different reviewer without disturbing `client`'s
    session) but the same `app.dependency_overrides[get_db]`, which is set
    at the app level, not per-client -- so both clients read and write
    through the exact same `db` session the rest of this test uses.
    """
    from fastapi.testclient import TestClient

    _colleague(db, org)

    with TestClient(client.app) as colleague_client:
        login = colleague_client.post(
            "/api/auth/login", json={"email": "priya@example.com", "password": "correct-horse"}
        )
        assert login.status_code == 200
        put_response = colleague_client.put(
            "/api/presence", json={"project_id": str(project.id), "sheet_id": str(sheet.id)}
        )
    assert put_response.status_code == 204

    _sign_in(client)
    body = client.get(f"/api/projects/{project.id}/snapshot").json()

    assert len(body["presence"]) == 1
    assert body["presence"][0]["name"] == "Priya Nakamura"
