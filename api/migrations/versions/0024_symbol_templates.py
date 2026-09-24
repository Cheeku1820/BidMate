"""legend templates, item suggestions, suggested match name

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-24 00:00:00.000000

B3c (docs/superpowers/sdd/legend-named-clusters): schema for "the legend
suggests, the estimator names." Three columns, each an addition with no
existing rows to reconcile -- unlike 0023, nothing here is a closed set
enforced by a CHECK CONSTRAINT, so there is no constraint to drop and
recreate and the downgrade is three plain `op.drop_column` calls, in
reverse order, with no DELETE required first.

`sheets.symbol_templates` (JSONB, nullable) -- the legend rows a legend
sheet carries, each a glyph's silhouette plus the drafter's own words
for it, read once at upload; Classification ranks against them.
`items.suggestions` (JSONB, nullable) -- the ranked legend candidates an
unnamed item offers an estimator, names only, best first. `sym-
bol_matches.suggested_name` (String(300), default `''`) -- the name
Classification proposes for a drawn symbol search, before a person
confirms it.

All three are nullable or defaulted, so no backfill: an existing sheet's
`symbol_templates` reads NULL, an existing item's `suggestions` reads
NULL, and an existing symbol match's `suggested_name` reads `''`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0024'
down_revision: Union[str, None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sheets', sa.Column('symbol_templates', postgresql.JSONB(), nullable=True))
    op.add_column('items', sa.Column('suggestions', postgresql.JSONB(), nullable=True))
    op.add_column('symbol_matches', sa.Column('suggested_name', sa.String(length=300),
                                               nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('symbol_matches', 'suggested_name')
    op.drop_column('items', 'suggestions')
    op.drop_column('sheets', 'symbol_templates')
