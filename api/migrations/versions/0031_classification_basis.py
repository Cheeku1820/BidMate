"""classification_basis

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-08 00:00:00.000000

One nullable column on `items` (rom-estimate.md): "inferred" when the
classifier named a cluster from surrounding context rather than from a
legend row that defines its tag.

No backfill, and NULL is the right answer for every existing row. NULL
means "not an inference", and for a row classified before this column
existed nobody knows either way -- recording an honest unknown as
"matched" would be the one reading that lets the ROM understate what it
assumed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0031'
down_revision: Union[str, None] = '0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('items', sa.Column('classification_basis', sa.String(30), nullable=True))
    # A closed vocabulary with one member today. `app.takeoff.ingest`
    # already drops anything else, and this is the second line of
    # defence for a row that reaches the table through a script --
    # the same discipline `ck_documents_status` applies.
    op.create_check_constraint(
        'ck_items_classification_basis', 'items',
        "classification_basis is null or classification_basis in ('inferred')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_items_classification_basis', 'items', type_='check')
    op.drop_column('items', 'classification_basis')
