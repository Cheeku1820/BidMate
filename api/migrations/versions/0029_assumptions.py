"""assumptions

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-08 00:00:00.000000

docs/specs/rom-estimate.md: one table, holding the ROM's assumed lines
and the basis each was derived from.

No backfill. An existing project has no assumptions until a run
generates them, and a project with none renders as a ROM where every
line was counted -- which is the honest reading of "nothing has been
assumed yet", not a missing-data state.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0029'
down_revision: Union[str, None] = '0028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors app.estimate.basis -- SECTIONS, SUBJECT_KINDS, SOURCES, and
# BASIS's keys. Written as check constraints for the same reason
# `documents.status` is (migration 0020): the closed set is a domain
# rule, and a row that reaches the table through a script rather than
# through `validate_assumption` must still be refused.
_SECTIONS = "'scope', 'takeoff', 'labor', 'material'"
_SUBJECT_KINDS = "'project', 'sheet', 'item'"
_SOURCES = "'engine', 'estimator'"
_BASES = (
    "'supplier_quote', 'firm_default', 'market_estimate', 'class_average', "
    "'inferred', 'rule_of_thumb', 'scaled', 'standard_exclusion'"
)


def upgrade() -> None:
    op.create_table(
        'assumptions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('section', sa.String(20), nullable=False),
        sa.Column('subject_kind', sa.String(20), nullable=False, server_default='project'),
        # No foreign key on purpose: the target table depends on
        # subject_kind, and an orphan is resolved away by
        # app.estimate.exclusions rather than cascade-deleted.
        sa.Column('subject_id', UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('found', sa.Text(), nullable=False),
        sa.Column('why', sa.Text(), nullable=False),
        sa.Column('where', sa.Text(), nullable=False),
        sa.Column('basis', sa.String(30), nullable=False),
        sa.Column('value', sa.String(100), nullable=True),
        sa.Column('unit', sa.String(20), nullable=True),
        sa.Column('excluded_value', sa.Numeric(12, 2), nullable=True),
        sa.Column('source', sa.String(20), nullable=False, server_default='engine'),
        sa.Column('created_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"section in ({_SECTIONS})", name='ck_assumptions_section'),
        sa.CheckConstraint(f"subject_kind in ({_SUBJECT_KINDS})", name='ck_assumptions_subject_kind'),
        sa.CheckConstraint(f"source in ({_SOURCES})", name='ck_assumptions_source'),
        sa.CheckConstraint(f"basis in ({_BASES})", name='ck_assumptions_basis'),
    )
    op.create_index('ix_assumptions_project_id', 'assumptions', ['project_id'])
    op.create_index('ix_assumptions_project_section', 'assumptions', ['project_id', 'section'])


def downgrade() -> None:
    op.drop_index('ix_assumptions_project_section', table_name='assumptions')
    op.drop_index('ix_assumptions_project_id', table_name='assumptions')
    op.drop_table('assumptions')
