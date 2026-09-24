"""B3c's schema task: three columns, no constraint. Unlike 0023 there is
nothing to drop and recreate on downgrade -- `symbol_templates`,
`suggestions`, and `suggested_name` are each an independent
`op.add_column`/`op.drop_column`, so a source-order test guarding a
DELETE-before-constraint ordering doesn't apply here (see
test_migration_0023.py for that pattern, where it does).

What this test guards instead: the real SQL. It inserts a sheet with
`symbol_templates`, an item with `suggestions`, and a symbol match with
`suggested_name` set (through the ORM, so every other NOT NULL column
gets its normal Python-side default rather than being retyped by hand
here), runs `downgrade()` and confirms all three columns are actually
gone from `information_schema.columns`, then runs `upgrade()` again and
confirms they're back.

The test suite builds its schema with Base.metadata.create_all (see
conftest.py), not by replaying the alembic chain from 0001, so this
calls 0024's own upgrade()/downgrade() functions directly against the
`db` fixture's connection -- whose tables already carry the three
columns (models.py defines the post-0024 shape), so downgrade() finds
exactly the schema it expects. Postgres DDL is transactional, so the
fixture's own teardown rollback leaves no trace regardless of outcome.
"""
import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from app.takeoff.models import Item, SymbolMatch

_PATH = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0024_symbol_templates.py"
_spec = importlib.util.spec_from_file_location("_migration_0024", _PATH)
migration_0024 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration_0024)


def _has_column(conn, table_name, column_name):
    return conn.execute(text(
        "select 1 from information_schema.columns where table_name = :t and column_name = :c"
    ), {"t": table_name, "c": column_name}).first() is not None


def test_downgrade_then_upgrade_round_trips_the_three_columns(db, project, sheet, dana):
    sheet.symbol_templates = [{"description": "DUPLEX RECEPTACLE", "modifier": "", "rect": [0, 0, 10, 10],
                               "silhouette": "AAAA", "sheet_number": "E0.1"}]
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="generic", name="Unclassified symbol",
                system="Unknown", category="Unclassified", quantity=3, unit="ea",
                suggestions=[{"name": "Duplex receptacle", "sheet": "E0.1"}])
    match = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id,
                        box=[500, 375, 12, 12], created_by=dana.id, suggested_name="Duplex receptacle")
    db.add_all([item, match])
    db.flush()

    conn = db.connection()

    assert _has_column(conn, "sheets", "symbol_templates")
    assert _has_column(conn, "items", "suggestions")
    assert _has_column(conn, "symbol_matches", "suggested_name")

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        migration_0024.downgrade()

    assert not _has_column(conn, "sheets", "symbol_templates")
    assert not _has_column(conn, "items", "suggestions")
    assert not _has_column(conn, "symbol_matches", "suggested_name")

    with Operations.context(ctx):
        migration_0024.upgrade()

    assert _has_column(conn, "sheets", "symbol_templates")
    assert _has_column(conn, "items", "suggestions")
    assert _has_column(conn, "symbol_matches", "suggested_name")
