"""render job kind, sheet render columns

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-16 00:00:00.000000

B3 (docs/superpowers/sdd/drawing-behind-the-markers): the schema behind
rendering each detected sheet into tiles behind the review canvas. Adds
a fourth job kind, `render`, so the worker queue can carry that unit of
work the same way it already carries read/classify/sheet -- and four
columns on `sheets` that the render job writes back: `render_key` (the
storage path the rendered page lives at -- never serialized to the
client, see SheetOut/sheet_out), `render_status` (its own closed-set
axis, like `kind`, never one of the four review labels), `render_error`
(estimator-facing copy on failure), and `max_zoom` (how far the canvas
can zoom into the rendered tiles).

`ck_jobs_kind` has to be dropped and recreated rather than altered in
place -- Postgres has no ALTER CHECK CONSTRAINT. Spelled out as a
literal here, matching 0021's own convention: a migration is a record
of what was applied at a point in time and must not change meaning
when app.jobs.schemas.JOB_KINDS is later edited.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0022'
down_revision: Union[str, None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JOB_KINDS_OLD = "'read', 'classify', 'sheet'"
_JOB_KINDS_NEW = "'read', 'classify', 'sheet', 'render'"
_RENDER_STATUSES = "'pending', 'rendered', 'failed'"


def upgrade() -> None:
    op.add_column('sheets', sa.Column('render_key', sa.String(length=300), nullable=True))
    op.add_column('sheets', sa.Column('render_status', sa.String(length=20), nullable=False, server_default='pending'))
    op.add_column('sheets', sa.Column('render_error', sa.Text(), nullable=False, server_default=''))
    op.add_column('sheets', sa.Column('max_zoom', sa.Integer(), nullable=True))
    op.create_check_constraint('ck_sheets_render_status', 'sheets', f"render_status in ({_RENDER_STATUSES})")

    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_JOB_KINDS_NEW})")


def downgrade() -> None:
    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_JOB_KINDS_OLD})")

    op.drop_constraint('ck_sheets_render_status', 'sheets', type_='check')
    op.drop_column('sheets', 'max_zoom')
    op.drop_column('sheets', 'render_error')
    op.drop_column('sheets', 'render_status')
    op.drop_column('sheets', 'render_key')
