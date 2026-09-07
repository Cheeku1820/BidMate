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
