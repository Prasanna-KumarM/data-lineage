"""Adds Business Process read-model columns to business_lineage_step (UI-02).

Temporary until the extractor writes these columns itself; the migration is idempotent.
"""
import hashlib
import json
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


# Steps that differ only in relation_id/component represent one path written by
# several mappings; they merge into one step with contributors recorded apart.
_CONTRIBUTORS_DDL = """
CREATE TABLE IF NOT EXISTS business_lineage_step_contributor (
    step_id TEXT NOT NULL,
    relation_id TEXT NOT NULL,
    PRIMARY KEY (step_id, relation_id)
)"""

_MERGE_VARYING = {"step_id", "path_id", "relation_id", "component_id", "component_name", "component_type", "expression_id"}


def _merge_key(row: sqlite3.Row, key_columns: list[str]) -> tuple:
    return tuple(row[c] for c in key_columns)


def _endpoint_chain_hash(*parts: str) -> str:
    return "PTH_" + hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def merge_duplicate_steps(conn: sqlite3.Connection) -> tuple[int, int]:
    """Merge steps identical except for relation/component; returns (groups merged, steps removed).

    Steps at the same level of one path position that differ only in relation/component
    collapse into one step. Path ids are then rebuilt from the endpoint chain, so every
    remaining step has its parent level inside its own path.
    """
    conn.row_factory = sqlite3.Row
    conn.execute(_CONTRIBUTORS_DDL)
    all_columns = [r[1] for r in conn.execute("PRAGMA table_info(business_lineage_step)")]
    key_columns = [c for c in all_columns if c not in _MERGE_VARYING]
    rows = conn.execute("SELECT * FROM business_lineage_step ORDER BY step_id").fetchall()

    groups: dict[tuple, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(_merge_key(row, key_columns), []).append(row)

    removed: dict[str, str] = {}  # removed step_id -> kept step_id
    contributors: dict[str, list[str]] = {}
    for members in groups.values():
        kept = members[0]
        relations: list[str] = []
        for m in members:
            if m["relation_id"] not in relations:
                relations.append(m["relation_id"])
        contributors[kept["step_id"]] = relations
        for m in members[1:]:
            removed[m["step_id"]] = kept["step_id"]

    merged_groups = sum(1 for m in groups.values() if len(m) > 1)
    for step_id, relation_ids in contributors.items():
        conn.executemany(
            "INSERT OR IGNORE INTO business_lineage_step_contributor (step_id, relation_id) VALUES (?, ?)",
            [(step_id, rid) for rid in relation_ids],
        )
    if removed:
        for gone, kept_id in removed.items():
            conn.execute("UPDATE column_relation SET path_step_id=? WHERE path_step_id=?", (kept_id, gone))
        marks = ",".join("?" for _ in removed)
        conn.execute(f"DELETE FROM business_lineage_step WHERE step_id IN ({marks})", list(removed))

    _rebuild_path_ids(conn)
    conn.commit()
    return merged_groups, len(removed)


def _rebuild_path_ids(conn: sqlite3.Connection) -> None:
    """Path id = endpoint chain from the root; parents are matched by endpoint, deepest ambiguity resolved by min id."""
    remaining = conn.execute(
        "SELECT step_id, path_id, lineage_level, root_target_object_id, root_target_column_id,"
        " business_process_id, source_object_id, source_column_id, target_object_id, target_column_id,"
        " relation_type, driving_expression, result_expression, is_terminal"
        " FROM business_lineage_step ORDER BY lineage_level, step_id"
    ).fetchall()
    by_level: dict[int, list[sqlite3.Row]] = {}
    for row in remaining:
        by_level.setdefault(row["lineage_level"], []).append(row)

    assigned: dict[str, str] = {}
    for row in by_level.get(0, []):
        assigned[row["step_id"]] = _endpoint_chain_hash(
            row["root_target_column_id"], str(row["business_process_id"]),
            row["source_object_id"], row["source_column_id"],
            row["relation_type"], str(row["driving_expression"]), str(row["result_expression"]), str(row["is_terminal"]),
        )
    for level in sorted(by_level):
        if level == 0:
            continue
        parents = by_level[level - 1]
        for row in by_level[level]:
            candidates = [
                p for p in parents
                if p["root_target_column_id"] == row["root_target_column_id"]
                and p["business_process_id"] == row["business_process_id"]
                and p["source_object_id"] == row["target_object_id"]
                and p["source_column_id"] == row["target_column_id"]
            ]
            known = [assigned[p["step_id"]] for p in candidates if p["step_id"] in assigned]
            if known:
                assigned[row["step_id"]] = min(known)
    for row in remaining:
        new_path = assigned.get(row["step_id"])
        if new_path and new_path != row["path_id"]:
            conn.execute("UPDATE business_lineage_step SET path_id=? WHERE step_id=?", (new_path, row["step_id"]))
