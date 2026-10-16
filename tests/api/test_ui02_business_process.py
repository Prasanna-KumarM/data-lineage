import shutil
import sqlite3
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "api"))

from lineage_api.migrations import add_business_process_columns  # noqa: E402


@pytest.fixture()
def copy_conn(lineage_db_path, tmp_path):
    target = tmp_path / "lineage.db"
    shutil.copy(lineage_db_path, target)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    existing = {r[1] for r in connection.execute("PRAGMA table_info(business_lineage_step)")}
    for column in ("business_process_id", "business_process_name"):
        if column in existing:
            connection.execute(f"ALTER TABLE business_lineage_step DROP COLUMN {column}")
    yield connection
    connection.close()


def test_fills_business_process_for_every_step(copy_conn):
    add_business_process_columns(copy_conn)
    missing = copy_conn.execute(
        """SELECT COUNT(*) FROM business_lineage_step
           WHERE business_process_id IS NULL OR business_process_name IS NULL"""
    ).fetchone()[0]
    assert missing == 0


def test_values_match_component_join(copy_conn):
    add_business_process_columns(copy_conn)
    mismatches = copy_conn.execute(
        """SELECT COUNT(*) FROM business_lineage_step s
           JOIN component c ON c.component_id = s.component_id
           JOIN business_process bp ON bp.business_process_id = c.business_process_id
           WHERE s.business_process_id != bp.business_process_id
              OR s.business_process_name != bp.business_process_name"""
    ).fetchone()[0]
    assert mismatches == 0


def test_migration_is_idempotent(copy_conn):
    add_business_process_columns(copy_conn)
    before = copy_conn.execute("SELECT * FROM business_lineage_step ORDER BY step_id").fetchall()
    add_business_process_columns(copy_conn)
    after = copy_conn.execute("SELECT * FROM business_lineage_step ORDER BY step_id").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_existing_columns_and_row_count_unchanged(copy_conn):
    cols_before = [r[1] for r in copy_conn.execute("PRAGMA table_info(business_lineage_step)")]
    rows_before = copy_conn.execute("SELECT COUNT(*) FROM business_lineage_step").fetchone()[0]
    add_business_process_columns(copy_conn)
    cols_after = [r[1] for r in copy_conn.execute("PRAGMA table_info(business_lineage_step)")]
    assert cols_after[: len(cols_before)] == cols_before
    assert set(cols_after) - set(cols_before) == {"business_process_id", "business_process_name"}
    assert copy_conn.execute("SELECT COUNT(*) FROM business_lineage_step").fetchone()[0] == rows_before


def test_integrity_after_migration(copy_conn):
    add_business_process_columns(copy_conn)
    assert copy_conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert copy_conn.execute("PRAGMA foreign_key_check").fetchall() == []
