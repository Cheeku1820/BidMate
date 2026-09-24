"""conversation_proposal

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-24 00:00:00.000000

docs/specs/conversation-panel-acts.md: an answer may carry one
proposal, and the thread remembers whether it was applied or
dismissed. Statuses are spelled out here rather than imported, per
0020/0021's convention.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '0027'
down_revision: Union[str, None] = '0026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECK = ("(proposal is null and proposal_status is null) "
          "or (proposal is not null and proposal_status in ('offered', 'applied', 'dismissed'))")


def upgrade() -> None:
    op.add_column('conversation_messages', sa.Column('proposal', JSONB, nullable=True))
    op.add_column('conversation_messages', sa.Column('proposal_status', sa.String(length=20), nullable=True))
    op.create_check_constraint('ck_conversation_messages_proposal_status', 'conversation_messages', _CHECK)


def downgrade() -> None:
    op.drop_constraint('ck_conversation_messages_proposal_status', 'conversation_messages', type_='check')
    op.drop_column('conversation_messages', 'proposal_status')
    op.drop_column('conversation_messages', 'proposal')
