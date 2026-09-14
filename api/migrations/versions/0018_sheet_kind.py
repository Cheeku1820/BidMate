"""sheet kind

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-14 00:00:00.000000

Adds sheets.kind -- plan / schedule / legend / diagram / other -- so a
panel schedule stays visible in the sheet rail, labelled, without
contributing counted items. Defaulted to 'plan', which is what every
existing row was implicitly treated as, so no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0018'
down_revision: Union[str, None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sheets', sa.Column('kind', sa.String(length=20), nullable=False, server_default='plan'))


def downgrade() -> None:
    op.drop_column('sheets', 'kind')
