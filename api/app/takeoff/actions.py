import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.models import Action, Project


class CrossOrgActionError(Exception):
    """Raised when the actor's org does not own the project an action targets.

    commit() cannot leave attribution to chance, and attribution that is
    wrong is worse than attribution that is missing: a bug upstream of this
    function must not be able to write a cross-tenant row into a table
    nothing can ever correct.
    """


# Single source of truth for the append-only guard. The migration
# (migrations/versions/0004_actions.py) runs this against the real
# database; tests/conftest.py's `db` fixture re-runs it after
# Base.metadata.create_all, which does not execute migrations. Keeping the
# DDL in exactly one place means a future guard can't land in only one of
# the two paths and pass the suite while doing nothing in production.
ACTION_LOG_GUARD_DDL = """
create or replace function actions_are_append_only() returns trigger as $$
begin
    raise exception 'actions is append-only: % is not permitted', tg_op;
end;
$$ language plpgsql;

drop trigger if exists actions_no_update on actions;
drop trigger if exists actions_no_delete on actions;
drop trigger if exists actions_no_truncate on actions;

create trigger actions_no_update before update on actions
    for each statement execute function actions_are_append_only();
create trigger actions_no_delete before delete on actions
    for each statement execute function actions_are_append_only();
create trigger actions_no_truncate before truncate on actions
    for each statement execute function actions_are_append_only();

-- ORIGIN triggers (the default) stop firing when
-- session_replication_role is set to 'replica' -- a mode a logical
-- replication apply worker or a bulk-load script can set. ALWAYS
-- triggers fire regardless of that setting.
alter table actions enable always trigger actions_no_update;
alter table actions enable always trigger actions_no_delete;
alter table actions enable always trigger actions_no_truncate;

-- Belt and suspenders: the connecting role should not hold these
-- privileges at all, so the guard does not rest on the trigger alone.
-- CURRENT_USER, not a literal role name, because both the migration and
-- the test fixture run as whatever role the app itself connects as.
--
-- Two limits, written down rather than left implicit. (1) In this
-- project's docker-compose setup the connecting role ("takeoff") is a
-- Postgres superuser, and a superuser bypasses every privilege check --
-- this REVOKE is a no-op until a real deployment connects as a
-- non-superuser role (verified: `select rolsuper from pg_roles where
-- rolname = 'takeoff'` returns true). (2) Even under a non-superuser
-- role, the table owner can always GRANT the privilege back to itself,
-- and ALTER TABLE ... DISABLE TRIGGER / DROP TRIGGER remain available to
-- the owner regardless of this REVOKE. This guard stops accidents and
-- casual application-level tampering, not a determined holder of the
-- database credentials.
revoke update, delete, truncate on actions from current_user;
"""

ACTION_LOG_GUARD_TEARDOWN_DDL = """
drop trigger if exists actions_no_update on actions;
drop trigger if exists actions_no_delete on actions;
drop trigger if exists actions_no_truncate on actions;
drop function if exists actions_are_append_only();
"""


def _encode_snapshot_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    # datetime before date: datetime is a subclass of date, so checking
    # date first would encode every timestamp with .isoformat()'s date-only
    # behavior never actually running -- order matters here.
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def encode_snapshot(fields: dict) -> dict:
    """Make a before/after snapshot JSON-safe for the `before` / `after`
    JSONB columns.

    `Decimal` becomes `str`, so `Item.quantity` round-trips exactly --
    `float()` would silently lose precision. Enum members become
    `.value`, so `Item.status` stores "approved" rather than failing to
    serialize, or storing the unusable "ReviewStatus.APPROVED". `datetime`
    and `date` become `.isoformat()` strings (`Item.approved_at`,
    `Item.rejected_at`), and `uuid.UUID` becomes `str()`
    (`Item.approved_by_user_id`) -- both fields review.py's mutations
    snapshot on every approve/reject/unreject.

    Shallow only: it does not recurse into nested lists or dicts, because
    nothing in the current schema needs that. A Decimal, Enum, datetime,
    date, or UUID nested inside a list value still raises at commit()
    rather than silently mis-encoding -- extend this function first if
    that need shows up.

    `decode_snapshot_value()` below is the inverse, kept in this module
    so a future reader can't drift from what a writer actually did.
    """
    return {key: _encode_snapshot_value(value) for key, value in fields.items()}


def decode_snapshot_value(value, as_type):
    """Reverse `encode_snapshot()` for one field, given the type it
    should become.

    JSONB carries no type information of its own -- a stored string
    could be a plain string, an encoded Decimal, an encoded enum value,
    an isoformat datetime/date, or an encoded UUID -- so the caller has
    to say which. This is the one place that knows the encoding, for
    whichever task reconstructs prior item state from a stored snapshot.
    """
    if value is None:
        return None
    if as_type is Decimal:
        return Decimal(value)
    if isinstance(as_type, type) and issubclass(as_type, enum.Enum):
        return as_type(value)
    if as_type is datetime:
        return datetime.fromisoformat(value)
    if as_type is date:
        return date.fromisoformat(value)
    if as_type is uuid.UUID:
        return uuid.UUID(value)
    return value


def commit(
    db: DbSession,
    *,
    actor: User,
    project_id: uuid.UUID,
    kind: str,
    label: str,
    before: dict,
    after: dict,
    item_id: uuid.UUID | None = None,
    sheet_id: uuid.UUID | None = None,
    undoes_action_id: uuid.UUID | None = None,
) -> Action:
    """The only way anything in this module records a change.

    Every mutation routes through here so attribution and the audit trail
    cannot be forgotten by a future endpoint. Two things are enforced
    that a router must never be trusted to get right on its own:

    - The actor's org must own the project the action targets, checked
      here rather than assumed from whatever the caller passed in.
    - The row's `id` is assigned here, rather than left to the column's
      flush-time default, so a caller that chains
      `undoes_action_id=prior.id` before ever flushing never silently
      writes `None`.
    """
    project = db.get(Project, project_id)
    if project is None or project.org_id != actor.org_id:
        raise CrossOrgActionError(
            f"actor {actor.id} is not authorized to record actions for project {project_id}"
        )

    action = Action(
        id=uuid.uuid4(),
        project_id=project_id,
        kind=kind,
        label=label,
        before=encode_snapshot(before),
        after=encode_snapshot(after),
        item_id=item_id,
        sheet_id=sheet_id,
        actor_user_id=actor.id,
        undoes_action_id=undoes_action_id,
    )
    db.add(action)
    return action
