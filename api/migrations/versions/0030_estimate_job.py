"""estimate_job

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-08 00:00:00.000000

Widens `jobs.kind` to admit 'estimate' (rom-estimate.md). Its own
migration rather than part of 0029, because 0029 creates a table and
this alters a constraint on an existing one -- the same split 0025 made
when it added 'price' and 'price_sheet'.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0030'
down_revision: Union[str, None] = '0029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors app.jobs.schemas.JOB_KINDS.
_KINDS = "'read', 'classify', 'sheet', 'render', 'price', 'price_sheet', 'estimate'"
_OLD_KINDS = "'read', 'classify', 'sheet', 'render', 'price', 'price_sheet'"


def upgrade() -> None:
    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_KINDS})")


def downgrade() -> None:
    # Estimate jobs are regenerable from the project at any time, so
    # dropping their rows loses nothing an `estimate` job would not
    # rebuild on the next run. The assumptions themselves live in
    # `assumptions` and are 0029's to drop.
    op.execute("delete from jobs where kind = 'estimate'")
    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_OLD_KINDS})")
