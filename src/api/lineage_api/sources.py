"""Ultimate terminal-source resolver and per-session target cache (UI-05).

All steps of the selected target are loaded once, then every step is mapped to the
terminal sources reachable below it, so branch selection filters the right panel without
touching the database again.
"""
import os
import sqlite3
import threading
from collections import OrderedDict
from typing import Any

from lineage_api.graph import StepGraph
from lineage_api.upstream import StepNotFound

_STEPS_SQL = """
    SELECT s.step_id, s.business_process_id, s.lineage_level, s.is_terminal, s.relation_type,
           s.source_object_id, s.source_column_id, s.source_object_name, s.source_column_name,
           s.target_object_id, s.target_column_id, s.driving_expression, s.result_expression,
           o.object_type
    FROM business_lineage_step s
    JOIN business_process bp ON bp.business_process_id = s.business_process_id
    LEFT JOIN canonical_object o ON o.object_id = s.source_object_id
    WHERE bp.project_name = ?
      AND s.root_target_object_id = ? AND s.root_target_column_id = ?
"""


def _terminal_id(row: sqlite3.Row) -> str:
    """Endpoint plus the leaf step's expression, so CASE branches to one endpoint stay distinct."""
    base = f"{row['source_object_id']}|{row['source_column_id']}"
    if row["driving_expression"] is None and row["result_expression"] is None:
        return base
    return f"{base}|{row['driving_expression'] or ''}|{row['result_expression'] or ''}"


def resolve_terminal_sources(
    conn: sqlite3.Connection,
    project: str,
    object_id: str,
    column_id: str,
    business_process_id: str | None = None,
) -> dict[str, Any]:
    """Terminal sources of a target column and, for each step, the terminals below it."""
    sql = _STEPS_SQL
    params: tuple = (project, object_id, column_id)
    if business_process_id is not None:
        sql += " AND s.business_process_id = ?"
        params += (business_process_id,)
    steps = conn.execute(sql, params).fetchall()

    graph = StepGraph(steps)
    by_id, kids_of = graph.by_id, graph.kids_of
    reachable = graph.reachable()

    terminals: dict[str, dict[str, Any]] = {}
    below: dict[str, frozenset[str]] = {}

    # Deepest steps first so every child is resolved before its parent.
    for s in sorted((by_id[i] for i in reachable), key=lambda r: -r["lineage_level"]):
        kids = kids_of(s)
        if not kids:
            tid = _terminal_id(s)
            entry = terminals.setdefault(
                tid,
                {
                    "terminal_id": tid,
                    "leaf_step_id": s["step_id"],
                    "object_id": s["source_object_id"],
                    "column_id": s["source_column_id"],
                    "object_name": s["source_object_name"],
                    "column_name": s["source_column_name"],
                    "object_type": s["object_type"],
                    "condition": s["driving_expression"],
                    "result_expression": s["result_expression"],
                    "leaf_relation_types": set(),
                },
            )
            entry["leaf_relation_types"].add(s["relation_type"])
            below[s["step_id"]] = frozenset({tid})
        else:
            below[s["step_id"]] = frozenset().union(*(below[k] for k in kids))

    ordered = sorted(
        terminals.values(),
        key=lambda t: (
            t["object_name"], t["column_name"], t["object_id"], t["column_id"],
            t["condition"] or "", t["result_expression"] or "",
        ),
    )
    for t in ordered:
        t["leaf_relation_types"] = sorted(t["leaf_relation_types"])
    rank = {t["terminal_id"]: i for i, t in enumerate(ordered)}

    return {
        "project": project,
        "object_id": object_id,
        "column_id": column_id,
        "terminal_sources": ordered,
        "branch_terminals": {
            step_id: sorted(ids, key=rank.__getitem__) for step_id, ids in below.items()
        },
    }


def sources_for_step(resolved: dict[str, Any], step_id: str | None = None) -> list[dict[str, Any]]:
    """Terminal sources reachable through the step; all of them when no step is selected."""
    if step_id is None:
        return list(resolved["terminal_sources"])
    try:
        wanted = set(resolved["branch_terminals"][step_id])
    except KeyError:
        raise StepNotFound(step_id) from None
    return [t for t in resolved["terminal_sources"] if t["terminal_id"] in wanted]


def db_fingerprint(conn: sqlite3.Connection) -> tuple:
    """Identity of the lineage DB; changes when the file is regenerated or replaced."""
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row[2] if row else ""
    if not path:
        return ("memory", id(conn))
    st = os.stat(path)
    return (os.path.realpath(path), st.st_mtime_ns, st.st_size)


class TargetSourceCache:
    """Holds the resolved terminal sources of the active target for each session."""

    def __init__(self, max_sessions: int = 256) -> None:
        self._entries: OrderedDict[str, tuple[tuple, tuple, dict[str, Any]]] = OrderedDict()
        self._max_sessions = max_sessions
        self._lock = threading.Lock()
        self.compute_count = 0

    def get(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        project: str,
        object_id: str,
        column_id: str,
        business_process_id: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = db_fingerprint(conn)
        target = (project, object_id, column_id, business_process_id)
        with self._lock:
            cached = self._entries.get(session_id)
            if cached and cached[0] == fingerprint and cached[1] == target:
                self._entries.move_to_end(session_id)
                return cached[2]
            resolved = resolve_terminal_sources(conn, project, object_id, column_id, business_process_id)
            self.compute_count += 1
            self._entries[session_id] = (fingerprint, target, resolved)
            self._entries.move_to_end(session_id)
            while len(self._entries) > self._max_sessions:
                self._entries.popitem(last=False)
            return resolved

    def clear(self, session_id: str | None = None) -> None:
        with self._lock:
            if session_id is None:
                self._entries.clear()
            else:
                self._entries.pop(session_id, None)
