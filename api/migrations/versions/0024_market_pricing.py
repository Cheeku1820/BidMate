"""market_pricing

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-18 00:00:00.000000

docs/specs/estimate-first-pricing.md: the two market tables, the
project ZIP, the supplier fields on project_material_prices, and two
new job kinds. Job kinds are spelled out here rather than imported,
per 0020/0021's convention.

The ZIP backfill reads `location`'s trailing 5-digit token (optionally
followed by "-NNNN" and/or a trailing "USA"/"US") as the postal code,
and nothing else -- it does not parse or validate against any real ZIP
database. A location that happens to end in some other 5-digit number
is read as a ZIP by this same rule; it is editable afterwards on
project settings (Task 4). Task 3 reimplements this exact regex as a
tested pure function, `parse_zip`, so the two must stay in agreement.
"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = '0024'
down_revision: Union[str, None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = "'read', 'classify', 'sheet', 'render', 'price', 'price_sheet'"
_OLD_KINDS = "'read', 'classify', 'sheet', 'render'"


def upgrade() -> None:
    op.add_column('projects', sa.Column('postal_code', sa.String(length=10), nullable=True))
    conn = op.get_bind()
    for pid, location in conn.execute(sa.text("SELECT id, location FROM projects")).fetchall():
        m = re.search(r"\b(\d{5})(?:-\d{4})?\s*(?:USA?)?\s*$", location or "", re.IGNORECASE)
        if m:
            conn.execute(sa.text("UPDATE projects SET postal_code = :z WHERE id = :id"), {"z": m.group(1), "id": pid})

    op.add_column('project_material_prices', sa.Column('supplier_name', sa.String(length=200), nullable=False, server_default=''))
    op.add_column('project_material_prices', sa.Column('quote_date', sa.Date(), nullable=True))

    op.create_table(
        'market_lookups',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('query_key', sa.String(length=300), nullable=False),
        sa.Column('location_key', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('result', JSONB, nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('billed', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False),
        sa.UniqueConstraint('source', 'query_key', 'location_key', name='uq_market_lookup'),
    )
    op.create_index('ix_market_lookups_org_id', 'market_lookups', ['org_id'])
    op.create_index('ix_market_lookups_org_fetched', 'market_lookups', ['org_id', 'fetched_at'])

    op.create_table(
        'item_market_prices',
        sa.Column('item_id', UUID(as_uuid=True), sa.ForeignKey('items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('lookup_id', UUID(as_uuid=True), sa.ForeignKey('market_lookups.id', ondelete='SET NULL'), nullable=True),
        sa.Column('outcome', sa.String(length=20), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('query', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('unit_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('price_low', sa.Numeric(10, 2), nullable=True),
        sa.Column('price_high', sa.Numeric(10, 2), nullable=True),
        sa.Column('labor_rate_per_unit', sa.Numeric(10, 2), nullable=True),
        sa.Column('unit', sa.String(length=10), nullable=False, server_default=''),
        sa.Column('location_label', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_id', UUID(as_uuid=True), nullable=True),
    )

    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_KINDS})")


def downgrade() -> None:
    op.drop_constraint('ck_jobs_kind', 'jobs', type_='check')
    op.create_check_constraint('ck_jobs_kind', 'jobs', f"kind in ({_OLD_KINDS})")
    op.drop_table('item_market_prices')
    op.drop_index('ix_market_lookups_org_fetched', table_name='market_lookups')
    op.drop_index('ix_market_lookups_org_id', table_name='market_lookups')
    op.drop_table('market_lookups')
    op.drop_column('project_material_prices', 'quote_date')
    op.drop_column('project_material_prices', 'supplier_name')
    op.drop_column('projects', 'postal_code')
