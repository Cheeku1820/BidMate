"""sheet kind

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-14 00:00:00.000000

Adds sheets.kind -- plan / schedule / legend / diagram / other -- so a
panel schedule stays visible in the sheet rail, labelled, without
contributing counted items. Defaulted to 'plan', which is what every
existing row was implicitly treated as, so no backfill.

What that means for rows already in the table, plainly:

- Every existing sheet becomes kind 'plan', with the title it already
  had (a constant "Electrical" or "Power plan" from the old engine, not
  a title read from the drawing). A schedule ingested before this
  branch is a 'plan' row until it is re-ingested.
- A project processed before this branch keeps its old sheet numbers.
  For Unalaska those were hash-ordered -- the old engine took the
  number from `max(set(ids), key=ids.count)`, and the same page could
  come out E3.1 in one process and E2.1 in the next.
- A re-run (POST /reprocess) matches incoming sheets to existing ones
  by number. It updates a matched sheet's kind and title from the new
  reading (reprocess.py), but it cannot repair a row whose stored
  number was wrong in the first place: the engine's correct number
  finds no match and lands as a new sheet beside the old one, and the
  old one keeps its items.

So: recreate demo projects rather than re-running them. There is no
data migration here because there is nothing on the row to derive the
right values from -- kind and title come from the title block, and the
title block is in the PDF, not in Postgres.
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
