"""'What the tool analyzed' numbers behind a set of business-visible tables."""
import os
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from lineage_api.db import check_schema, declared_only, open_readonly

FIELDS = (
    "business_processes",
    "components",
    "mappings",
    "lineage_paths",
    "target_columns",
    "target_columns_with_lineage",
)


def _has_contributors(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='business_lineage_step_contributor'"
    ).fetchone() is not None


def table_stats(conn: sqlite3.Connection, tables: list[str]) -> dict[str, int]:
    """Counts behind the lineage of the given root target (table) names in one database."""
    marks = ",".join("?" for _ in tables)
    scoped = f"FROM business_lineage_step s WHERE s.root_target_object_name IN ({marks})"
    processes, components, paths = conn.execute(
        f"""SELECT COUNT(DISTINCT s.business_process_id), COUNT(DISTINCT s.component_id), COUNT(DISTINCT s.path_id)
            {scoped}""",
        tables,
    ).fetchone()
    if _has_contributors(conn):
        # Contributor relations are mappings too (the "N mappings" chip in the UI).
        mappings = conn.execute(
            f"""SELECT COUNT(*) FROM (
                    SELECT s.relation_id {scoped}
                    UNION
                    SELECT c.relation_id FROM business_lineage_step_contributor c
                    JOIN business_lineage_step s ON s.step_id = c.step_id
                    WHERE s.root_target_object_name IN ({marks})
                )""",
            tables + tables,
        ).fetchone()[0]
    else:
        mappings = conn.execute(f"SELECT COUNT(DISTINCT s.relation_id) {scoped}", tables).fetchone()[0]

    object_ids = [r[0] for r in conn.execute(f"SELECT DISTINCT s.root_target_object_id {scoped}", tables)]
    suffix = declared_only(conn, object_ids)
    omarks = ",".join("?" for _ in object_ids)
    total = (
        conn.execute(f"SELECT COUNT(*) FROM canonical_column WHERE object_id IN ({omarks}){suffix}", object_ids).fetchone()[0]
        if object_ids
        else 0
    )
    with_lineage = (
        conn.execute(
            f"""SELECT COUNT(DISTINCT s.root_target_column_id) {scoped}
                  AND s.root_target_column_id IN (
                      SELECT c.column_id FROM canonical_column c WHERE c.object_id IN ({omarks}){suffix})""",
            tables + object_ids,
        ).fetchone()[0]
        if object_ids
        else 0
    )
    return {
        "business_processes": processes,
        "components": components,
        "mappings": mappings,
        "lineage_paths": paths,
        "target_columns": total,
        "target_columns_with_lineage": with_lineage,
    }


def compute_stats(registry: Any, pairs: list[str]) -> dict[str, int]:
    """Sums table_stats over `project:table` pairs, one database per project."""
    by_project: dict[str, list[str]] = {}
    for pair in pairs:
        project, sep, table = pair.partition(":")
        if sep and table.strip():
            by_project.setdefault(project, []).append(table.strip())
    totals = dict.fromkeys(FIELDS, 0)
    for entry in registry.entries():
        tables = by_project.get(entry["project_name"])
        if not tables or not entry["ready"]:
            continue
        conn = open_readonly(entry["path"])
        try:
            check_schema(conn)
            stats = table_stats(conn, sorted(set(tables)))
        except sqlite3.Error:
            continue
        finally:
            conn.close()
        for key, value in stats.items():
            totals[key] += value
    return totals


class AnalysisStatsCache:
    """Remembers compute_stats until a database file changes."""

    def __init__(self, max_entries: int = 64) -> None:
        self._entries: OrderedDict[tuple, dict[str, int]] = OrderedDict()
        self._max_entries = max_entries
        self._lock = threading.Lock()

    @staticmethod
    def _fingerprint(path: Path) -> tuple:
        st = os.stat(path)
        return (os.path.realpath(path), st.st_mtime_ns, st.st_size)

    def get(self, registry: Any, pairs: list[str]) -> dict[str, int]:
        entries = registry.entries()
        key = (
            tuple(sorted((e["project_name"], self._fingerprint(e["path"])) for e in entries)),
            tuple(sorted(pairs)),
        )
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached
        computed = compute_stats(registry, pairs)
        with self._lock:
            self._entries[key] = computed
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return computed
