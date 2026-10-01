"""phases_and_schedule

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-21 00:00:00.000000

Written as 0026 on the stream-D branch and renumbered at integration to
sit behind what landed first: 0026_plan and 0027_conversation_proposal.

docs/specs/phases-and-timeline.md §11: phases, phase lines, stage
plans, item lead times, the four company tables, the singleton
settings row, and four columns. No backfill: the first phase is
created on first read, and the company seeds are inserted per org by
app.schedule.defaults.ensure_defaults, never here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0028'
down_revision: Union[str, None] = '0027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STAGES = "'demolition', 'rough_in', 'wire_pull', 'gear', 'trim', 'closeout'"


def _audit_cols():
    return [
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'phases',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('start_date', sa.Date, nullable=True),
        sa.Column('required_finish_date', sa.Date, nullable=True),
        sa.Column('notes', sa.Text, nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'sort_order', name='uq_phase_order', deferrable=True, initially='DEFERRED'),
    )
    op.create_table(
        'phase_lines',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('phase_id', UUID(as_uuid=True), sa.ForeignKey('phases.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(30), nullable=False, server_default='general_conditions'),
        sa.Column('label', sa.String(200), nullable=False),
        sa.Column('percent_of_direct_hours', sa.Numeric(5, 2), nullable=False),
        sa.Column('hours_override', sa.Numeric(10, 2), nullable=True),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        *_audit_cols(),
    )
    op.create_table(
        'phase_stage_plans',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('phase_id', UUID(as_uuid=True), sa.ForeignKey('phases.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('stage', sa.String(20), nullable=False),
        sa.Column('foreman', sa.Integer, nullable=True),
        sa.Column('journeyman', sa.Integer, nullable=True),
        sa.Column('apprentice', sa.Integer, nullable=True),
        sa.Column('productive_hours_per_day', sa.Numeric(4, 2), nullable=True),
        sa.Column('hours_override', sa.Numeric(10, 2), nullable=True),
        sa.Column('start_date', sa.Date, nullable=True),
        sa.Column('duration_days', sa.Integer, nullable=True),
        *_audit_cols(),
        sa.UniqueConstraint('phase_id', 'stage', name='uq_phase_stage'),
        sa.CheckConstraint(f"stage in ({_STAGES})", name='ck_phase_stage_plans_stage'),
    )
    op.create_table(
        'item_lead_times',
        sa.Column('item_id', UUID(as_uuid=True), sa.ForeignKey('items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('flagged', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('lead_weeks', sa.Integer, nullable=True),
        sa.Column('source', sa.String(20), nullable=True),
        sa.Column('source_label', sa.String(200), nullable=False, server_default=''),
        sa.Column('quoted_at', sa.Date, nullable=True),
        sa.Column('needed_for_stage', sa.String(20), nullable=False, server_default='gear'),
        *_audit_cols(),
        sa.CheckConstraint(f"needed_for_stage in ({_STAGES})", name='ck_item_lead_times_stage'),
        sa.CheckConstraint("source is null or source in ('supplier_quote', 'estimator')", name='ck_item_lead_times_source'),
    )
    op.create_table(
        'company_stage_splits',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('category_key', sa.String(100), nullable=False),
        sa.Column('category_label', sa.String(100), nullable=False),
        *[sa.Column(s, sa.Numeric(5, 2), nullable=False, server_default='0') for s in ('demolition', 'rough_in', 'wire_pull', 'gear', 'trim', 'closeout')],
        sa.Column('firm_edited', sa.Boolean, nullable=False, server_default='false'),
        *_audit_cols(),
        sa.UniqueConstraint('org_id', 'category_key', name='uq_company_stage_split'),
        sa.CheckConstraint('demolition + rough_in + wire_pull + gear + trim + closeout = 100', name='ck_company_stage_split_sum'),
    )
    op.create_table(
        'company_stage_crews',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('stage', sa.String(20), nullable=False),
        sa.Column('foreman', sa.Integer, nullable=False, server_default='0'),
        sa.Column('journeyman', sa.Integer, nullable=False, server_default='0'),
        sa.Column('apprentice', sa.Integer, nullable=False, server_default='0'),
        sa.Column('productive_hours_per_day', sa.Numeric(4, 2), nullable=False, server_default='6'),
        sa.Column('productivity_factor', sa.Numeric(5, 3), nullable=False, server_default='1'),
        sa.Column('max_crew', sa.Integer, nullable=False, server_default='6'),
        sa.Column('firm_edited', sa.Boolean, nullable=False, server_default='false'),
        *_audit_cols(),
        sa.UniqueConstraint('org_id', 'stage', name='uq_company_stage_crew'),
        sa.CheckConstraint(f"stage in ({_STAGES})", name='ck_company_stage_crews_stage'),
    )
    op.create_table(
        'company_schedule_settings',
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('lead_time_stale_days', sa.Integer, nullable=False, server_default='60'),
        *_audit_cols(),
    )
    op.create_table(
        'company_phase_line_templates',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('label', sa.String(200), nullable=False),
        sa.Column('percent_of_direct_hours', sa.Numeric(5, 2), nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        *_audit_cols(),
    )
    op.create_table(
        'company_lead_times',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_class', sa.String(50), nullable=False),
        sa.Column('lead_weeks', sa.Integer, nullable=False),
        sa.Column('source_label', sa.String(200), nullable=False),
        sa.Column('quoted_at', sa.Date, nullable=False),
        *_audit_cols(),
        sa.UniqueConstraint('org_id', 'item_class', name='uq_company_lead_time'),
    )
    op.add_column('sheets', sa.Column('phase_id', UUID(as_uuid=True), sa.ForeignKey('phases.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_sheets_phase_id', 'sheets', ['phase_id'])
    op.add_column('items', sa.Column('phase_id', UUID(as_uuid=True), sa.ForeignKey('phases.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_items_phase_id', 'items', ['phase_id'])
    op.add_column('projects', sa.Column('expected_award_date', sa.Date, nullable=True))
    op.add_column('projects', sa.Column('mobilization_date', sa.Date, nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'mobilization_date')
    op.drop_column('projects', 'expected_award_date')
    op.drop_index('ix_items_phase_id', table_name='items')
    op.drop_column('items', 'phase_id')
    op.drop_index('ix_sheets_phase_id', table_name='sheets')
    op.drop_column('sheets', 'phase_id')
    for table in ('company_lead_times', 'company_phase_line_templates', 'company_schedule_settings',
                  'company_stage_crews', 'company_stage_splits', 'item_lead_times',
                  'phase_stage_plans', 'phase_lines', 'phases'):
        op.drop_table(table)
