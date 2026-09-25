"""One boolean column, added and dropped. Same shape as
test_migration_0024.py, and the same reason for calling the migration's
own `upgrade()`/`downgrade()` directly: the suite builds its schema with
`Base.metadata.create_all` rather than replaying the alembic chain, so
the `db` fixture's tables already carry the post-0025 column and
`downgrade()` finds exactly the schema it expects. Postgres DDL is
transactional, so the fixture's rollback leaves no trace either way.

What it guards beyond the round trip: the server default. The column is
`NOT NULL DEFAULT false`, which is what makes it safe to add to a
populated `items` table without a backfill -- a row inserted with no
value for it reads `false`, meaning "the engine wrote this name and
nobody has disagreed," which is what `merge._overwrite` needs to hear
about every row that existed before this column did.
"""
import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

_PATH = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0025_item_name_by_estimator.py"
_spec = importlib.util.spec_from_file_location("_migration_0025", _PATH)
migration_0025 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration_0025)


def _has_column(conn, table_name, column_name):
    return conn.execute(text(
        "select 1 from information_schema.columns where table_name = :t and column_name = :c"
    ), {"t": table_name, "c": column_name}).first() is not None


def test_downgrade_then_upgrade_round_trips_the_column(db, project, sheet):
    conn = db.connection()
    assert _has_column(conn, "items", "name_by_estimator")

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        migration_0025.downgrade()
    assert not _has_column(conn, "items", "name_by_estimator")

    with Operations.context(ctx):
        migration_0025.upgrade()
    assert _has_column(conn, "items", "name_by_estimator")


def test_a_row_predating_the_column_reads_as_engine_named(db, project, sheet):
    """An `INSERT` that names every other column and not this one -- what
    a row already in the table looks like to the new column."""
    conn = db.connection()
    conn.execute(text(
        "insert into items (id, project_id, sheet_id, symbol, name, description, system, category,"
        " quantity, unit, status, notes, version)"
        " values (gen_random_uuid(), :p, :s, 'generic', 'Unclassified symbol', '', 'Unknown',"
        " 'Unclassified', 3, 'ea', 'attention', '', 1)"
    ), {"p": project.id, "s": sheet.id})
    assert conn.execute(text(
        "select name_by_estimator from items where sheet_id = :s"
    ), {"s": sheet.id}).scalar_one() is False
