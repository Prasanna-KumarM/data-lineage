"""Adds Business Process read-model columns to business_lineage_step (UI-02).

Temporary until the extractor writes these columns itself; the migration is idempotent.
"""
import sqlite3
import sys

COLUMNS = ("business_process_id", "business_process_name")


def _step_columns(conn: sqlite3.Connection) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(business_lineage_step)")}


def add_business_process_columns(conn: sqlite3.Connection) -> int:
    """Add missing columns and fill them from component/business_process; returns rows updated."""
    existing = _step_columns(conn)
    for column in COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE business_lineage_step ADD COLUMN {column} TEXT")

    cursor = conn.execute(
        """UPDATE business_lineage_step SET
             business_process_id = (SELECT c.business_process_id FROM component c
                                    WHERE c.component_id = business_lineage_step.component_id),
             business_process_name = (SELECT bp.business_process_name
                                      FROM component c
                                      JOIN business_process bp
                                        ON bp.business_process_id = c.business_process_id
                                      WHERE c.component_id = business_lineage_step.component_id)
           WHERE component_id IS NOT NULL"""
    )
    conn.commit()
    return cursor.rowcount


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m lineage_api.migrations <path-to-lineage.db>")
    with sqlite3.connect(sys.argv[1]) as connection:
        print(f"updated {add_business_process_columns(connection)} rows")
