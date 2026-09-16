"""jobs, classifications, scope_statements

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-15 00:00:00.000000

The schema behind B2 (docs/superpowers/specs/2026-08-18-bidmate-agent-
architecture-design.md): moving the takeoff engine behind the API so a
worker polls a queue instead of the browser posting straight to
localhost:8100.

`jobs` is the queue itself -- the worker claims a row with FOR UPDATE
SKIP LOCKED, so two workers can share it with no coordinator. The two
partial unique indexes are what make "at most one read in flight per
document" and "at most one classify in flight per project" true at the
database level, not just at the route that enqueues.

`classifications` holds one run's tag -> spec map and pricing basis,
written once by the classify job and read by every sheet job of that
run -- one row per run, enforced by a unique constraint on run_id.

`scope_statements` holds what the documents say the electrical work is,
found by the worker and settled by a person. Its `status` is
deliberately not the four review labels (found/confirmed/dismissed
describes whether a person has settled a *statement*, the same way a
note's confirmed/open describes a note rather than an item).

The five new columns (Document.page_count, Document.context_text,
Sheet.schedule_text, Sheet.region, Sheet.legend) are what the read job
writes so the classify and sheet jobs never have to re-open the source
file themselves.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = '0021'
down_revision: Union[str, None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Spelled out rather than interpolated from app.jobs.schemas / app.scope.
# schemas, matching 0020's convention: a migration is a record of what was
# applied at a point in time and must not change meaning when a constant
# it imported is later edited.
_JOB_KINDS = "'read', 'classify', 'sheet'"
_JOB_STATUSES = "'queued', 'running', 'done', 'failed'"
_SCOPE_KINDS = "'included', 'excluded', 'by_others', 'alternate'"
_SCOPE_STATUSES = "'found', 'confirmed', 'dismissed'"


def upgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=True),
        sa.Column('sheet_id', UUID(as_uuid=True), sa.ForeignKey('sheets.id', ondelete='CASCADE'), nullable=True),
        sa.Column('run_id', UUID(as_uuid=True), nullable=True),
        sa.Column('requested_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payload', JSONB(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='queued'),
        sa.Column('progress', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('locked_by', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('queued_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('not_before', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"kind in ({_JOB_KINDS})", name='ck_jobs_kind'),
        sa.CheckConstraint(f"status in ({_JOB_STATUSES})", name='ck_jobs_status'),
    )
    op.create_index('ix_jobs_org_id', 'jobs', ['org_id'])
    op.create_index('ix_jobs_project_id', 'jobs', ['project_id'])
    op.create_index('ix_jobs_run_id', 'jobs', ['run_id'])
    op.create_index('ix_jobs_poll', 'jobs', ['status', 'kind', 'queued_at'])
    op.create_index(
        'uq_jobs_read_in_flight', 'jobs', ['document_id'], unique=True,
        postgresql_where=sa.text("kind = 'read' AND status IN ('queued', 'running')"),
    )
    op.create_index(
        'uq_jobs_classify_in_flight', 'jobs', ['project_id'], unique=True,
        postgresql_where=sa.text("kind = 'classify' AND status IN ('queued', 'running')"),
    )

    op.create_table(
        'classifications',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', UUID(as_uuid=True), nullable=False),
        sa.Column('specs_by_tag', JSONB(), nullable=False),
        sa.Column('labor_rate', sa.Numeric(10, 2), nullable=False),
        sa.Column('material_factor', sa.Numeric(6, 3), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('location_note', sa.Text(), nullable=False, server_default=''),
        sa.Column('wiring_note', sa.Text(), nullable=False, server_default=''),
        sa.Column('unmatched_note', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('run_id', name='uq_classifications_run'),
    )
    op.create_index('ix_classifications_project_id', 'classifications', ['project_id'])

    op.create_table(
        'scope_statements',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('orgs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('page_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('text', sa.String(length=500), nullable=False),
        sa.Column('quote', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='found'),
        sa.Column('edited_text', sa.String(length=500), nullable=True),
        sa.Column('run_id', UUID(as_uuid=True), nullable=False),
        sa.Column('decided_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"kind in ({_SCOPE_KINDS})", name='ck_scope_kind'),
        sa.CheckConstraint(f"status in ({_SCOPE_STATUSES})", name='ck_scope_status'),
    )
    op.create_index('ix_scope_statements_org_id', 'scope_statements', ['org_id'])
    op.create_index('ix_scope_statements_project_id', 'scope_statements', ['project_id'])
    op.create_index('ix_scope_statements_document_id', 'scope_statements', ['document_id'])

    op.add_column('documents', sa.Column('page_count', sa.Integer(), nullable=True))
    op.add_column('documents', sa.Column('context_text', sa.Text(), nullable=False, server_default=''))
    op.add_column('sheets', sa.Column('schedule_text', sa.Text(), nullable=False, server_default=''))
    op.add_column('sheets', sa.Column('region', JSONB(), nullable=True))
    op.add_column('sheets', sa.Column('legend', JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('sheets', 'legend')
    op.drop_column('sheets', 'region')
    op.drop_column('sheets', 'schedule_text')
    op.drop_column('documents', 'context_text')
    op.drop_column('documents', 'page_count')

    op.drop_index('ix_scope_statements_document_id', table_name='scope_statements')
    op.drop_index('ix_scope_statements_project_id', table_name='scope_statements')
    op.drop_index('ix_scope_statements_org_id', table_name='scope_statements')
    op.drop_table('scope_statements')

    op.drop_index('ix_classifications_project_id', table_name='classifications')
    op.drop_table('classifications')

    op.drop_index('uq_jobs_classify_in_flight', table_name='jobs')
    op.drop_index('uq_jobs_read_in_flight', table_name='jobs')
    op.drop_index('ix_jobs_poll', table_name='jobs')
    op.drop_index('ix_jobs_run_id', table_name='jobs')
    op.drop_index('ix_jobs_project_id', table_name='jobs')
    op.drop_index('ix_jobs_org_id', table_name='jobs')
    op.drop_table('jobs')
