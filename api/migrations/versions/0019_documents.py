"""documents

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-15 00:00:00.000000

The table behind B1 (docs/specs/documents-stored.md): one row per
uploaded file, with the hash the within-project duplicate rule keys on
and the storage key the blob lives under. `status`/`error` are written
by the worker from B2 on; B1 only ever writes 'uploaded'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0019'
down_revision: Union[str, None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'documents',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(length=300), nullable=False),
        sa.Column('doc_type', sa.String(length=20), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('storage_key', sa.String(length=300), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='uploaded'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('uploaded_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'sha256', name='uq_document_project_sha256'),
    )
    op.create_index('ix_documents_project_id', 'documents', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_documents_project_id', table_name='documents')
    op.drop_table('documents')
