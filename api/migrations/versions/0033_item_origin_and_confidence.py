"""item_origin_and_confidence

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-16 00:00:00.000000

`items.origin`, `items.confidence`, `items.confidence_reasons`, and the
project's building type (estimate-without-asking.md, slice 2).

**Why `origin` is stored rather than derived.** The obvious derivation
is "a line with no coordinates was guessed" -- and it is wrong in both
directions. A counted cluster whose placements failed to record has no
coordinates and is still counted; a companion allowance attached to a
sheet could be given coordinates and would still be a guess. The same
argument 0032 makes for `assumptions.origin`, which used to be read off
`source` and mislabelled every scope exclusion the documents stated.

It is also deliberately not `source_tag`. That column carries the
drawing's own symbol tag and drives cluster identity and "find every one
like this" (`takeoff/resolve_apply.py`), so a synthetic value written
there would fabricate a symbol cluster the resolve path would then offer
to apply across the set.

**No backfill, on purpose.** Every existing row is genuinely `counted`,
which is the server default. Every existing row's confidence is genuinely
unknown -- the engine computed one at classification time and discarded
it (`engine/rows.py`), so there is nothing to recover. The spec requires
NULL to render as an empty bar and sort last rather than be filled in
with an invented figure; a re-run scores them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0033'
down_revision: Union[str, None] = '0032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'items',
        sa.Column('origin', sa.String(20), nullable=False, server_default='counted'),
    )
    op.create_check_constraint(
        'ck_items_origin', 'items',
        "origin in ('counted', 'assumed')",
    )

    op.add_column('items', sa.Column('confidence', sa.SmallInteger(), nullable=True))
    # The meter is 1-10, and NULL means nothing has scored this line. A
    # stored 0 would be indistinguishable from the second state on
    # screen, since both draw an empty bar.
    op.create_check_constraint(
        'ck_items_confidence', 'items',
        'confidence is null or (confidence >= 1 and confidence <= 10)',
    )
    op.add_column(
        'items',
        sa.Column('confidence_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.add_column('projects', sa.Column('building_type', sa.String(100), nullable=True))
    op.add_column('projects', sa.Column('building_type_source', sa.String(20), nullable=True))
    op.create_check_constraint(
        'ck_projects_building_type_source', 'projects',
        "building_type_source is null or building_type_source in ('inferred', 'estimator')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_projects_building_type_source', 'projects', type_='check')
    op.drop_column('projects', 'building_type_source')
    op.drop_column('projects', 'building_type')

    op.drop_column('items', 'confidence_reasons')
    op.drop_constraint('ck_items_confidence', 'items', type_='check')
    op.drop_column('items', 'confidence')

    op.drop_constraint('ck_items_origin', 'items', type_='check')
    op.drop_column('items', 'origin')
