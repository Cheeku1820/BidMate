"""symbol_matches table, match job kind

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-16 00:00:00.000000

B3b (docs/superpowers/sdd/accurate-symbol-marking): the schema behind
"find every one like this" -- the estimator draws a box around a symbol
and the worker searches the sheet for others like it. Adds a fifth job
kind, `match`, so the worker queue can carry that unit of work the same
way it already carries read/classify/sheet/render -- and a new table,
`symbol_matches`, one row per box drawn: `box` (the region as drawn, in
sheet units), `status` (its own closed-set axis, like `kind`, never one
of the four review labels), `matches` (what the worker found, named by
nobody until a person approves it), and `error` (estimator-facing copy
on failure). `jobs.symbol_match_id` links a match job back to the row
it is working on.

`symbol_matches` is created before `jobs.symbol_match_id` is added,
because the column's foreign key targets it. `ck_jobs_kind` has to be
dropped and recreated rather than altered in place -- Postgres has no
ALTER CHECK CONSTRAINT. Spelled out as a literal here, matching 0021's
and 0022's own convention: a migration is a record of what was applied
at a point in time and must not change meaning when
app.jobs.schemas.JOB_KINDS is later edited.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0023'
down_revision: Union[str, None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JOB_KINDS_OLD = "'read', 'classify', 'sheet', 'render'"
_JOB_KINDS_NEW = "'read', 'classify', 'sheet', 'render', 'match'"
_MATCH_STATUSES = "'pending', 'found', 'failed'"


def upgrade() -> None:
    op.create_table(
        'symbol_matches',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sheet_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sheets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('box', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('matches', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_symbol_matches_org_id', 'symbol_matches', ['org_id'])
    op.create_index('ix_symbol_matches_project_id', 'symbol_matches', ['project_id'])
    op.create_index('ix_symbol_matches_sheet_id', 'symbol_matches', ['sheet_id'])
    op.create_check_constraint('ck_symbol_matches_status', 'symbol_matches', f"status in ({_MATCH_STATUSES})")

    op.add_column('jobs', sa.Column('symbol_match_id', postgresql.UUID(as_uuid=True),
                                     sa.ForeignKey('symbol_matches.id', ondelete='CASCADE'), nullable=True))

    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_JOB_KINDS_NEW})")


def downgrade() -> None:
    # A match job row (kind='match') cannot satisfy the four-kind
    # constraint being restored below, so any that exist have to go
    # first -- otherwise the CHECK CONSTRAINT this recreates would be
    # violated by existing rows and this downgrade would fail outright
    # once a single match job had ever run. Match jobs are disposable
    # queue entries, not audit history (the append-only `actions` table
    # is that), so deleting them here loses nothing this migration is
    # responsible for preserving.
    op.execute("DELETE FROM jobs WHERE kind = 'match'")

    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_JOB_KINDS_OLD})")

    op.drop_column('jobs', 'symbol_match_id')

    op.drop_table('symbol_matches')
