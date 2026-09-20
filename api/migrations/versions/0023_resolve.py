"""reject_reason and resolve_note on items; symbol_resolutions

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-18 00:00:00.000000

docs/specs/say-what-it-is.md: the estimator's sentence lives on the item
(`resolve_note` on a reclassification, `reject_reason` on a rejection)
so it is visible in the spreadsheet and the export, not only in the
action log. `symbol_resolutions` is the per-project library a confirmed
resolution writes and the sheet job reads on a later run -- one row per
(project, tag), upserted on apply, never written by the engine itself.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0023'
down_revision: Union[str, None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('items', sa.Column('reject_reason', sa.Text(), nullable=True))
    op.add_column('items', sa.Column('resolve_note', sa.Text(), nullable=True))
    # The estimator's sentence as provenance on the action itself.
    op.add_column('actions', sa.Column('note', sa.Text(), nullable=True))
    op.create_table(
        'symbol_resolutions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('tag', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=300), nullable=False),
        sa.Column('system', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('catalog_id', sa.String(length=100), nullable=True),
        sa.Column('resolved_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'tag', name='uq_symbol_resolution_project_tag'),
    )


def downgrade() -> None:
    op.drop_table('symbol_resolutions')
    op.drop_column('actions', 'note')
    op.drop_column('items', 'resolve_note')
    op.drop_column('items', 'reject_reason')
