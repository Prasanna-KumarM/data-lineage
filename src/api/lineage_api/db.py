"""Read-only access to the generated lineage database."""
import sqlite3
from pathlib import Path
from urllib.parse import quote

ENV_DB_PATH = "LINEAGE_DB"

REQUIRED_COLUMNS = {
    "business_lineage_step": {
        "step_id", "path_id", "lineage_level", "is_terminal", "relation_id", "relation_type",
        "root_target_object_id", "root_target_column_id",
        "root_target_object_name", "root_target_column_name",
        "source_object_id", "source_column_id", "source_object_name", "source_column_name",
        "target_object_id", "target_column_id", "target_object_name", "target_column_name",
        "component_id", "component_name", "component_type",
        "confidence_class", "confidence_reason_code",
        "traversal_path", "driving_expression", "result_expression", "expression_id",
        "hop_count", "business_process_id", "business_process_name",
    },
    "business_process": {"business_process_id", "business_process_name", "project_name"},
    "canonical_object": {"object_id", "object_name", "object_type", "source_project"},
    "canonical_column": {"column_id", "object_id", "column_name"},
    "column_relation": {"relation_id", "relation_type", "expression_id"},
    "component": {"component_id", "business_process_id", "component_name", "component_type"},
    "canonical_confidence": {"relation_id", "confidence_class", "confidence_reason_code", "confidence_reason"},
    "expression_dependency": {"expression_dependency_id", "relation_id", "operand_order"},
}


class DatabaseNotConfigured(Exception):
    pass


class DatabaseUnavailable(Exception):
    pass


class SchemaMismatch(Exception):
    pass


def open_readonly(path: str | Path) -> sqlite3.Connection:
    """Open the DB so that no write is possible; any open or read failure means unavailable."""
    resolved = Path(path).expanduser().resolve()
    try:
        conn = sqlite3.connect(f"file:{quote(str(resolved))}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        raise DatabaseUnavailable(str(exc)) from exc
    return conn


def check_schema(conn: sqlite3.Connection) -> None:
    try:
        for table, required in REQUIRED_COLUMNS.items():
            present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            missing = required - present
            if missing:
                raise SchemaMismatch(f"{table} is missing: {', '.join(sorted(missing))}")
    except sqlite3.Error as exc:
        raise DatabaseUnavailable(str(exc)) from exc
