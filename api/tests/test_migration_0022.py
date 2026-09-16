"""B3's migration must survive a downgrade after a render job has
actually been queued (whole-branch-review finding #2). `ck_jobs_kind`'s
three-kind form, recreated on downgrade, cannot be satisfied by an
existing kind='render' row -- the downgrade has to clear those rows
first, or it fails outright the moment a render job has ever run.

The test suite builds its schema with Base.metadata.create_all (see
conftest.py), not by replaying the alembic chain from 0001, so driving
alembic upgrade/downgrade against a full migration history isn't
available here. What *is* available, and exercises the real SQL rather
than a stand-in: 0022's own upgrade()/downgrade() functions, called
directly against the `db` fixture's connection -- whose tables already
carry the render columns and the four-kind constraint (models.py
defines the post-0022 shape), so downgrade() finds exactly the schema
it expects. Postgres DDL is transactional, so the fixture's own
teardown rollback leaves no trace regardless of outcome."""
import importlib.util
import inspect
import uuid
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

_PATH = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0022_sheet_render.py"
_spec = importlib.util.spec_from_file_location("_migration_0022", _PATH)
migration_0022 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration_0022)


def test_downgrade_source_deletes_render_jobs_before_recreating_the_constraint():
    """A structural backstop alongside the real-SQL test below: the
    DELETE must appear before ck_jobs_kind is dropped and recreated to
    its three-kind form, not after -- ordering it after would still
    violate the constraint on the way back up."""
    src = inspect.getsource(migration_0022.downgrade)
    delete_at = src.index("DELETE FROM jobs")
    constraint_at = src.index("create_check_constraint('ck_jobs_kind'")
    assert 0 <= delete_at < constraint_at


def test_downgrade_succeeds_against_a_render_job_row(db, project, sheet):
    """The real regression: without the DELETE, this raises
    IntegrityError/CheckViolation the moment a kind='render' row exists,
    because create_check_constraint validates existing rows against the
    constraint it creates."""
    conn = db.connection()
    conn.execute(text(
        "insert into jobs (id, org_id, project_id, sheet_id, kind, status, attempts, max_attempts, payload) "
        "values (:id, :org_id, :project_id, :sheet_id, 'render', 'queued', 0, 3, '{}'::jsonb)"
    ), {"id": str(uuid.uuid4()), "org_id": str(project.org_id), "project_id": str(project.id),
        "sheet_id": str(sheet.id)})

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        migration_0022.downgrade()   # would raise here, pre-fix, with the render row still present

    assert conn.execute(text("select kind from jobs")).scalar() is None   # the render row is gone
    assert conn.execute(text(
        "select 1 from information_schema.columns where table_name = 'sheets' and column_name = 'render_key'"
    )).first() is None

    # Leave the schema as 0022 found it (upgrade back) so anything else
    # sharing this connection within the test sees the expected shape;
    # the fixture's rollback is the real safety net either way.
    with Operations.context(ctx):
        migration_0022.upgrade()
