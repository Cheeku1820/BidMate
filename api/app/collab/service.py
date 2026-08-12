"""Presence: a heartbeat, the active-window query, and the fingerprint
that folds presence into `snapshot.version()`.

Replaces the Task 11 stub entirely. That stub's own docstring recommended
`presence_signal` as `max(seen_at)` plus a row count -- task-12-brief.md
item 2 explains why that is wrong and this module does not do it: `seen_at`
changes on *every* heartbeat, so a signal keyed on it changes on
(effectively) every poll whenever anyone is actively using the project,
which sends a 200 back every time and makes the ETag worthless exactly
when it matters most. `presence_signal` instead fingerprints the active
*set* -- the sorted `(user_id, sheet_id, item_id)` tuples for rows inside
`ACTIVE_WINDOW` -- so a heartbeat that changes nothing about who is where
leaves the signal unchanged, and a heartbeat that moves a selection (or a
row simply ageing out of the window between polls, with no write at all)
changes it. See `test_presence.py`'s `presence_signal` tests for both
directions proven.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session as DbSession

from app.collab.models import Presence
from app.collab.schemas import PresenceOut
from app.identity.models import User

# The client's presence PUT runs on "a slower beat" than the three-second
# /snapshot poll (design doc, "Realtime"/"Client architecture" sections),
# but the exact cadence is a client concern this repo's src/ does not
# implement yet (CLAUDE.md: the conversation panel and every screen but F
# are unbuilt; presence has no client at all). Ten seconds is the
# assumption this module is built against -- generous enough that a
# reviewer's own tab backgrounding or a single delayed timer tick doesn't
# read as "gone," while still being well inside what a "slower beat than
# three seconds" plausibly means.
#
# Named and exported (not a bare literal folded into ACTIVE_WINDOW below)
# so the client port has one place to read the assumption from rather than
# re-deriving or duplicating it -- per task-12-brief.md's "Decisions to
# make and record."
ASSUMED_HEARTBEAT_INTERVAL = timedelta(seconds=10)

# Three heartbeats' worth of slack: comfortably longer than one heartbeat
# interval (the brief's requirement -- too tight and reviewers flicker in
# and out of each other's screens on every missed beat) while still
# bounding how long someone who has actually left a project keeps showing
# up as present. One missed heartbeat (a slow request, a backgrounded tab
# briefly throttled) does not evict a reviewer; two in a row starts to.
ACTIVE_WINDOW = ASSUMED_HEARTBEAT_INTERVAL * 3


def heartbeat(
    db: DbSession, user: User, project_id: uuid.UUID, sheet_id: uuid.UUID | None, item_id: uuid.UUID | None
) -> Presence:
    """Record `user`'s current position on `project_id`.

    A single upsert statement, not `db.get()` then `db.add()` on a miss
    (the plan's sketch, and task-12-brief.md item 4): presence is the
    highest-frequency write in the system -- the same reviewer open in two
    tabs, or a client retry, sends two heartbeats for the same
    `(user_id, project_id)` close enough together that a read-then-write
    window is a *when*, not an *if*, and the composite primary key turns
    that race into an `IntegrityError` under get-then-add. One
    `INSERT ... ON CONFLICT DO UPDATE` has no such window: Postgres
    resolves the conflict inside the statement itself.

    `.returning(Presence)` alone is **not** enough to avoid a stale read,
    and an earlier version of this docstring wrongly claimed it was. What
    is actually true: `db.get()` on the composite key would short-circuit
    to whatever instance the identity map already holds for
    `(user.id, project_id)` without re-querying at all, which is the
    stale-read hazard RETURNING was reached for in the first place. But
    when the ORM builds an entity from a RETURNING row it still goes
    through the identity map, and if an instance for that primary key is
    already present there, SQLAlchemy hands back *that* instance rather
    than a freshly populated one -- so a second `heartbeat()` call for the
    same `(user_id, project_id)` in the same session can return the exact
    same Python object the first call did, still carrying the first
    call's `sheet_id`/`item_id`/`seen_at`, RETURNING notwithstanding. The
    row written to the database is correct either way -- this is purely a
    question of what the ORM hands back to Python -- but a stale returned
    instance poisons every later ORM read in that session that touches
    the same row (`active_presence()`, concretely, since it feeds
    `/snapshot`), not just this function's own return value. Whether it
    bites is a function of the identity map's *weak* references: if
    nothing in the session holds the first call's instance alive between
    the two heartbeats, it is garbage-collected and the second call's
    RETURNING builds a fresh instance with no bug visible at all -- which
    is exactly the GC-timing-dependent shape the Task 10 review flagged as
    the hazard to design against, not just patch around.
    `execution_options={"populate_existing": True}` is what actually
    closes this: it tells the ORM to overwrite an already-present identity
    map entry's attributes from this statement's result rather than trust
    whatever it already had, so the same-object case is refreshed instead
    of returned untouched. See `test_heartbeat_refreshes_the_identity_
    mapped_instance_when_a_reference_is_held` in test_presence.py, which
    holds a reference across two heartbeats specifically so the test
    cannot pass by accident of GC timing the way a naive version of it
    would.
    """
    now = datetime.now(timezone.utc)
    stmt = pg_insert(Presence).values(
        user_id=user.id, project_id=project_id, sheet_id=sheet_id, item_id=item_id, seen_at=now
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Presence.user_id, Presence.project_id],
        set_={"sheet_id": stmt.excluded.sheet_id, "item_id": stmt.excluded.item_id, "seen_at": stmt.excluded.seen_at},
    ).returning(Presence)
    return db.execute(stmt, execution_options={"populate_existing": True}).scalars().one()


def active_presence(db: DbSession, project_id: uuid.UUID, exclude: uuid.UUID | None) -> list[PresenceOut]:
    """Every reviewer currently active on `project_id`, other than
    `exclude` (normally the requesting user -- nobody needs their own
    cursor drawn back at them).

    `exclude` is filtered in the `WHERE` clause, not by fetching every
    active row and dropping one in a Python list comprehension
    (task-12-brief.md item 5) -- there is no reason to pull a row across
    the wire only to throw it away, and doing the filter in SQL is not
    more code.
    """
    cutoff = datetime.now(timezone.utc) - ACTIVE_WINDOW
    conditions = [Presence.project_id == project_id, Presence.seen_at >= cutoff]
    if exclude is not None:
        conditions.append(Presence.user_id != exclude)
    rows = db.execute(select(Presence, User).join(User, User.id == Presence.user_id).where(*conditions)).all()
    return [
        PresenceOut(
            user_id=p.user_id, name=u.name, color=u.color, sheet_id=p.sheet_id, item_id=p.item_id, seen_at=p.seen_at
        )
        for p, u in rows
    ]


def presence_signal(db: DbSession, project_id: uuid.UUID) -> str:
    """A cheap, deterministic fingerprint of `project_id`'s live presence
    *set*, folded into `snapshot.version()` so a colleague's remote
    selection can bump the ETag even though a heartbeat writes no `Action`
    row (task-11-brief.md, decision 3).

    Deliberately not `max(seen_at)` plus a row count -- that changes on
    every single heartbeat regardless of whether anything a reviewer would
    actually see on screen changed, which defeats the ETag precisely when
    the project is in active use. This fingerprints
    `(user_id, sheet_id, item_id)` for every row inside `ACTIVE_WINDOW`
    instead: a pure heartbeat leaves that tuple unchanged, so the hash is
    unchanged, so the client gets a 304. Someone joining, leaving, or
    moving their selection changes a tuple, so the hash changes. A row
    ageing out of the window changes the *set* the next time this function
    runs, with no write involved at all, because the window is applied to
    `seen_at` at query time here -- not cached anywhere.

    Sorted explicitly before hashing: Postgres gives no row-order
    guarantee absent an ORDER BY, and an unstable order would make this
    function return two different fingerprints for the identical set on
    two successive calls, which breaks the "unchanged input, unchanged
    signal" half of the contract. Every field is converted to `str` before
    sorting or joining -- `sorted()` over tuples that mix `None` and `UUID`
    in the same position raises `TypeError` the moment two rows exist
    (Python does not define an ordering between `NoneType` and `UUID`),
    and `str(None)` ("None") cannot collide with `str()` of any real uuid,
    which is always a 36-character hyphenated hex string.
    """
    cutoff = datetime.now(timezone.utc) - ACTIVE_WINDOW
    rows = db.execute(
        select(Presence.user_id, Presence.sheet_id, Presence.item_id).where(
            Presence.project_id == project_id, Presence.seen_at >= cutoff
        )
    ).all()
    fingerprint = sorted((str(user_id), str(sheet_id), str(item_id)) for user_id, sheet_id, item_id in rows)
    raw = "|".join(",".join(row) for row in fingerprint)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
