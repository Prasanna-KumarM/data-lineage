"""Where an ultimate source continues: the same table/column as a target in another project's DB."""
import sqlite3
from typing import Any

from lineage_api.catalog import list_target_columns as list_catalog_columns
from lineage_api.catalog import list_target_objects
from lineage_api.db import check_schema, open_readonly
from lineage_api.target_catalog import (
    _has_target_components,
    list_target_columns as list_component_columns,
    target_column_id,
    target_definitions,
)


def find_continuations(
    registry: Any, project: str, object_name: str, column_name: str
) -> list[dict[str, Any]]:
    """Other ready projects where object_name.column_name is a target column with lineage."""
    found: list[dict[str, Any]] = []
    for entry in registry.entries():
        other = entry["project_name"]
        if other == project or not entry["ready"]:
            continue
        conn = open_readonly(entry["path"])
        try:
            check_schema(conn)
            match = _match(conn, other, object_name, column_name)
        except sqlite3.Error:
            match = None
        finally:
            conn.close()
        if match:
            found.append({"project": other, **match})
    return found


def _match(conn: sqlite3.Connection, project: str, object_name: str, column_name: str) -> dict[str, Any] | None:
    if _has_target_components(conn):
        for target in target_definitions(conn, project):
            if target["object_name"] != object_name:
                continue
            if any(c["column_name"] == column_name for c in list_component_columns(conn, project, target["object_id"])):
                return {"object_id": target["object_id"], "column_id": target_column_id(target["object_id"], column_name)}
        return None
    for obj in list_target_objects(conn, project):
        if obj["object_name"] != object_name:
            continue
        for column in list_catalog_columns(conn, project, obj["object_id"]):
            if column["column_name"] == column_name:
                return {"object_id": obj["object_id"], "column_id": column["column_id"]}
    return None
