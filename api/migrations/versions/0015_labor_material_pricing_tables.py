"""labor_material_pricing_tables

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-31 00:00:00.000001

Convention: revision ids match the versions/ filename sequence number.

Five new tables: three org-scoped company defaults (labor rates
singleton, sparse labor-hours overrides, sparse material prices) and two
project-scoped sparse per-item overrides (labor line, material price).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0015'
down_revision: Union[str, None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'company_labor_rates',
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('journeyman_rate', sa.Numeric(8, 2), nullable=False, server_default='0'),
        sa.Column('foreman_rate', sa.Numeric(8, 2), nullable=False, server_default='0'),
        sa.Column('apprentice_rate', sa.Numeric(8, 2), nullable=False, server_default='0'),
        sa.Column('productivity_factor', sa.Numeric(5, 3), nullable=False, server_default='1'),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'company_labor_hours_overrides',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_name', sa.String(length=300), nullable=False),
        sa.Column('hours_per_unit', sa.Numeric(8, 3), nullable=False),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('org_id', 'item_name', name='uq_company_labor_hours_item'),
    )
    op.create_table(
        'company_material_prices',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_name', sa.String(length=300), nullable=False),
        sa.Column('unit_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('org_id', 'item_name', name='uq_company_material_price_item'),
    )
    op.create_table(
        'project_labor_lines',
        sa.Column('item_id', UUID(as_uuid=True), sa.ForeignKey('items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('hours_override', sa.Numeric(8, 3), nullable=True),
        sa.Column('crew_journeyman', sa.Integer(), nullable=True),
        sa.Column('crew_foreman', sa.Integer(), nullable=True),
        sa.Column('crew_apprentice', sa.Integer(), nullable=True),
        sa.Column('rate_override', sa.Numeric(8, 2), nullable=True),
        sa.Column('adjustment_percent', sa.Numeric(6, 2), nullable=True),
        sa.Column('adjustment_reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'project_material_prices',
        sa.Column('item_id', UUID(as_uuid=True), sa.ForeignKey('items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('price_override', sa.Numeric(10, 2), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('project_material_prices')
    op.drop_table('project_labor_lines')
    op.drop_table('company_material_prices')
    op.drop_table('company_labor_hours_overrides')
    op.drop_table('company_labor_rates')
