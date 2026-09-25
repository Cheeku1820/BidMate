"""items.name_by_estimator: who last wrote an item's name

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-25 00:00:00.000000

B3c follow-up. `name` was engine-owned until this branch made it an
editable field, and `merge._overwrite` still wrote it unconditionally --
so Start takeoff again silently reverted every accepted legend
suggestion and every hand-typed name on an item nobody had approved
yet, against CLAUDE.md's "the engine never discards a person's
judgment."

Distinguishing "the estimator chose this name" from "the engine wrote
it and nobody has disagreed" needs a stored signal, and there was none:
`version > 1` is bumped by a re-run itself, and the action log can say a
rename happened but not that it still stands (undo appends a
compensating row rather than removing the original, so a renamed-
then-undone item would read as estimator-named forever).

One boolean, `NOT NULL DEFAULT false` -- a Postgres fast default, so no
table rewrite and no backfill. `false` is the honest reading of every
existing row: an item whose name a person really did type before this
column existed loses its claim once, at the next re-run, and can be
retyped. The alternative default would claim estimator authorship for
every engine-written name in the database, which is the worse error --
it would freeze the engine out of names nobody ever chose.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0025'
down_revision: Union[str, None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('items', sa.Column('name_by_estimator', sa.Boolean(),
                                     nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('items', 'name_by_estimator')
