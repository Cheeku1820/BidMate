"""documents.status check constraint

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-15 00:00:00.000000

`documents.status` is a closed set of four -- 'uploaded', 'processing',
'processed', 'failed' (app.documents.schemas.DOC_STATUSES). Until this
it was a bare String(20) that would accept anything.

B1 only ever writes 'uploaded'. B2's worker writes the other three, and
a typo there would otherwise persist a status no screen knows how to
render, with no error at the point it went wrong. A new revision rather
than an edit to 0019: 0019 has been applied, and editing an applied
migration leaves every database that already ran it without the
constraint while alembic reports it as current.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0020'
down_revision: Union[str, None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Spelled out rather than interpolated from DOC_STATUSES: a migration is
# a record of what was applied at a point in time, and must not change
# meaning when a constant it imported is later edited.
_STATUSES = "'uploaded', 'processing', 'processed', 'failed'"


def upgrade() -> None:
    op.create_check_constraint('ck_documents_status', 'documents', f"status in ({_STATUSES})")


def downgrade() -> None:
    op.drop_constraint('ck_documents_status', 'documents', type_='check')
