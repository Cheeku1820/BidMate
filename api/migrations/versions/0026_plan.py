"""plan

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-21 00:00:00.000000

docs/specs/project-plan-screen.md: the two tables the project plan
owns. plan_decisions holds one row per derived line a person decided,
keyed by the line's stable entry key; plan_phases holds phases a person
stated. Nothing derived is stored. Statuses are spelled out here rather
than imported, per 0020/0021's convention.

Numbered 0026 on this branch; renumber at integration if another
stream's migration lands first (the repo has done this twice).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0026'
down_revision: Union[str, None] = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUSES = "'found', 'confirmed', 'dismissed', 'answered'"


def upgrade() -> None:
    op.create_table(
        'plan_decisions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entry_key', sa.String(length=300), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='found'),
        sa.Column('edited_text', sa.String(length=500), nullable=True),
        sa.Column('note_id', UUID(as_uuid=True), sa.ForeignKey('notes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('project_id', 'entry_key', name='uq_plan_decisions_project_key'),
        sa.CheckConstraint(f"status in ({_STATUSES})", name='ck_plan_decisions_status'),
    )
    op.create_index('ix_plan_decisions_project_id', 'plan_decisions', ['project_id'])

    op.create_table(
        'plan_phases',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_plan_phases_project_id', 'plan_phases', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_plan_phases_project_id', table_name='plan_phases')
    op.drop_table('plan_phases')
    op.drop_index('ix_plan_decisions_project_id', table_name='plan_decisions')
    op.drop_table('plan_decisions')
