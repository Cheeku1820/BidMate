"""conversation_messages

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-16 00:00:00.000000

Numbered 0023: 0022 is sheet_render, which landed first on main; this
migration was written as 0022 on its own branch and renumbered at
integration so the chain stays linear.

One row per turn of a project's conversation thread
(docs/specs/conversation-panel.md). `role` is constrained to the
product's two words, spelled out here rather than imported, matching
0020/0021's convention: a migration records what was applied and must
not change meaning when a constant is later edited.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = '0023'
down_revision: Union[str, None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conversation_messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('screen', JSONB, nullable=True),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("role in ('estimator', 'answer')", name='ck_conversation_messages_role'),
    )
    op.create_index('ix_conversation_messages_project_id', 'conversation_messages', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_conversation_messages_project_id', table_name='conversation_messages')
    op.drop_table('conversation_messages')
