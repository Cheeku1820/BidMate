"""company action log guard

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-07 00:00:00.000000

0016 created `company_actions` without the append-only guard `actions` has
had since 0004_actions.py -- the model's docstring claimed "append-only"
before anything enforced it. This migration closes that gap, following
0004's own precedent: no schema change to autogenerate, just
`op.execute()` of the guard DDL (and its teardown on downgrade), sourced
from `app.takeoff.models.COMPANY_ACTION_LOG_GUARD_DDL` so the migration
and tests/conftest.py's `db` fixture can never drift apart.

If you hit this on upgrade -- read this next paragraph before you touch
anything else. 0016 was originally generated as
`64c7dba14184_company_action_log.py` and renamed by hand, after the fact,
to `0016` to match this directory's sequential-id convention (see
0004_actions.py's docstring). If your database ran `upgrade head` on this
branch before that rename landed, its `alembic_version` row still holds
the old hash id, and every alembic command -- `current`, `upgrade`,
`downgrade`, even `stamp 0016` -- fails identically with:

    FAILED: Can't locate revision identified by '64c7dba14184'

That happens because alembic has to resolve the stamped revision to walk
history before it can do anything else, and `64c7dba14184` no longer
exists in versions/ -- the rename removed it, it did not alias it.
Recover with:

    alembic stamp --purge 0016
    alembic upgrade head

`--purge` clears the stale `alembic_version` row instead of trying to
resolve it; the `upgrade head` that follows re-syncs from `0016` and
applies this migration normally. Nothing about `company_actions` itself
is affected -- only the bookkeeping row alembic uses to track which
migration a database is on. No stub `64c7dba14184 -> 0016` bridge
revision was added to paper over this: the exposure is narrow (only a
teammate who ran `upgrade head` on this branch inside the single-commit
window between the original migration and its rename), and a permanent
no-op revision in the chain would outlive the branch that made it
necessary.
"""
from typing import Sequence, Union

from alembic import op

from app.takeoff.models import COMPANY_ACTION_LOG_GUARD_DDL, COMPANY_ACTION_LOG_GUARD_TEARDOWN_DDL

# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: Union[str, None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(COMPANY_ACTION_LOG_GUARD_DDL)


def downgrade() -> None:
    op.execute(COMPANY_ACTION_LOG_GUARD_TEARDOWN_DDL)
