"""assumption_origin

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-08 00:00:00.000000

`assumptions.origin` -- the ROM's one axis, stored rather than derived
(rom-estimate.md, "Origin").

It used to be read off `source`: engine meant assumed, estimator meant
counted. That is wrong for one row the generator actually produces. An
exclusion the scope letter itself stated is written by the engine and is
nonetheless `counted`, because the spec's own definition of counted
includes "a scope statement extracted with a verbatim quote". Deriving
it tagged seven quoted fire-alarm rows "Assumed" and inflated the
assumed tally with work the documents spelled out.

Backfills every existing row to the value the old derivation produced,
so the column starts out agreeing with what was already on screen, and
the next run corrects the stated exclusions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0032'
down_revision: Union[str, None] = '0031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'assumptions',
        sa.Column('origin', sa.String(20), nullable=False, server_default='assumed'),
    )
    # What `_assumption_line` used to compute. Not a guess: it is exactly
    # the value the document was already rendering for these rows.
    op.execute("update assumptions set origin = 'counted' where source = 'estimator'")
    op.create_check_constraint(
        'ck_assumptions_origin', 'assumptions',
        "origin in ('assumed', 'counted')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_assumptions_origin', 'assumptions', type_='check')
    op.drop_column('assumptions', 'origin')
