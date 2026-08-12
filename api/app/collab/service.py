"""Presence stub -- Task 12 replaces this module entirely.

`app.takeoff.snapshot` imports two names from here rather than depending on
`app.collab.models.Presence` (which does not exist yet): `active_presence`,
which backs `SnapshotOut.presence`, and `presence_signal`, the seam that
folds a presence-derived component into `snapshot.version()`.

Both are stubs because there is no `Presence` table to query yet -- Task 12
introduces `app.collab.models.Presence` and a real heartbeat, and swaps
these two bodies for real queries (`active_presence` becomes a scoped
`SELECT`; `presence_signal` becomes something like `max(seen_at)` plus a row
count over the project's presence rows, matching task-11-brief.md's
recommendation) without either caller changing.

Hoisted at module level, not imported inside the request handler the way
the plan's stale sketch did -- there is no circular import between
`app.takeoff.snapshot` and `app.collab.service` to dodge (this module
imports nothing from `app.takeoff`), so there was no reason to defer it.
"""

import uuid

from sqlalchemy.orm import Session as DbSession


def active_presence(db: DbSession, project_id: uuid.UUID, exclude: uuid.UUID | None) -> list:
    """Every other reviewer currently active on `project_id`, excluding
    `exclude` (normally the requesting user -- nobody needs their own
    cursor drawn back at them). Always empty until Task 12.
    """
    return []


def presence_signal(db: DbSession, project_id: uuid.UUID) -> str:
    """A cheap, deterministic fingerprint of `project_id`'s live presence,
    folded into `snapshot.version()` so a colleague's remote selection can
    bump the ETag even though a heartbeat writes no `Action` row -- see
    task-11-brief.md, decision 3. A constant until Task 12's `Presence`
    table exists to derive a real one from.
    """
    return "0"
