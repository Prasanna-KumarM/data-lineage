"""Table-level lineage summary: for each target column, one line per ultimate source (summary page).

Hop counts are mappings from the target: a direct mapping is 1 hop. Routes are counted, never
enumerated, so shared upstream cannot blow up the response.
"""
import sqlite3
import threading
from collections import OrderedDict
from typing import Any

from lineage_api.db import declared_only
from lineage_api.graph import StepGraph
from lineage_api.sources import _terminal_id, db_fingerprint

_TABLE_STEPS_SQL = """
    SELECT s.step_id, s.business_process_id, s.lineage_level, s.is_terminal, s.relation_type,
           s.root_target_column_id,
           s.source_object_id, s.source_column_id, s.source_object_name, s.source_column_name,
           s.target_object_id, s.target_column_id, s.driving_expression, s.result_expression,
           s.component_name, s.confidence_class, o.object_type
    FROM business_lineage_step s
    JOIN business_process bp ON bp.business_process_id = s.business_process_id
    LEFT JOIN canonical_object o ON o.object_id = s.source_object_id
    WHERE bp.project_name = ? AND s.root_target_object_id = ?
"""


def source_kind(object_type: str | None, leaf_relation_types: list[str] | set[str]) -> str:
    """Presentation class of an ultimate source, from how its leaf step relates it to the target."""
    types = set(leaf_relation_types)
    if "NOT_PERSISTED" in types:
        return "not_persisted"
    if "RUNTIME_FUNCTION_ASSIGNMENT" in types:
        return "function"
    if "CONSTANT_ASSIGNMENT" in types or object_type == "CONSTANT":
        return "constant"
    return "column"


def _analyze_column(steps: list[sqlite3.Row]) -> dict[str, Any]:
    graph = StepGraph(steps)
    reachable = graph.reachable()
    by_id = graph.by_id

    # stats[step][terminal] = (fewest hops, most hops, route count, child on the shortest route)
    stats: dict[str, dict[str, tuple[int, int, int, str | None]]] = {}
    terminals: dict[str, dict[str, Any]] = {}

    def order(step_id: str) -> tuple:
        s = by_id[step_id]
        return (s["source_object_name"], s["source_column_name"], step_id)

    for s in sorted((by_id[i] for i in reachable), key=lambda r: -r["lineage_level"]):
        kids = sorted(graph.kids_of(s), key=order)
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
            stats[s["step_id"]] = {tid: (1, 1, 1, None)}
            continue
        merged: dict[str, tuple[int, int, int, str | None]] = {}
        for kid in kids:
            for tid, (mn, mx, cnt, _) in stats[kid].items():
                cur = merged.get(tid)
                if cur is None:
                    merged[tid] = (mn + 1, mx + 1, cnt, kid)
                else:
                    best = kid if mn + 1 < cur[0] else cur[3]
                    merged[tid] = (min(cur[0], mn + 1), max(cur[1], mx + 1), cur[2] + cnt, best)
        stats[s["step_id"]] = merged

    roots = sorted((r for r in graph.root_ids() if r in reachable), key=order)
    column: dict[str, tuple[int, int, int, str]] = {}
    for root in roots:
        for tid, (mn, mx, cnt, _) in stats[root].items():
            cur = column.get(tid)
            if cur is None:
                column[tid] = (mn, mx, cnt, root)
            else:
                best = root if mn < cur[0] else cur[3]
                column[tid] = (min(cur[0], mn), max(cur[1], mx), cur[2] + cnt, best)

    def route(first_step: str, tid: str) -> list[dict[str, Any]]:
        out, step_id = [], first_step
        while step_id is not None:
            s = by_id[step_id]
            out.append(
                {
                    "endpoint": f"{s['source_object_name']}.{s['source_column_name']}",
                    "relation_type": s["relation_type"],
                    "component_name": s["component_name"],
                }
            )
            step_id = stats[step_id][tid][3]
        return out

    sources = []
    for tid, entry in terminals.items():
        mn, mx, cnt, first = column[tid]
        leaf_types = sorted(entry["leaf_relation_types"])
        sources.append(
            {
                "terminal_id": tid,
                "leaf_step_id": entry["leaf_step_id"],
                "object_name": entry["object_name"],
                "column_name": entry["column_name"],
                "object_type": entry["object_type"],
                "kind": source_kind(entry["object_type"], leaf_types),
                "condition": entry["condition"],
                "result_expression": entry["result_expression"],
                "leaf_relation_types": leaf_types,
                "hops_min": mn,
                "hops_max": mx,
                "route_count": cnt,
                "route": route(first, tid),
                "_sort": (entry["object_name"], entry["column_name"], entry["object_id"], entry["column_id"],
                          entry["condition"] or "", entry["result_expression"] or ""),
            }
        )
    sources.sort(key=lambda src: src["_sort"])
    for src in sources:
        del src["_sort"]

    kinds = {src["kind"] for src in sources}
    steps_used = [by_id[i] for i in reachable]
    flags = {
        "constant": "constant" in kinds,
        "function": "function" in kinds,
        "not_persisted": "not_persisted" in kinds,
        "case_branches": any(s["relation_type"] == "EXPRESSION" and s["driving_expression"] for s in steps_used),
        "inferred": any(s["confidence_class"] not in (None, "Explicit") for s in steps_used),
    }
    return {
        "has_lineage": True,
        "source_count": len(sources),
        "hops_min": min((s["hops_min"] for s in sources), default=None),
        "hops_max": max((s["hops_max"] for s in sources), default=None),
        "flags": flags,
        "sources": sources,
    }


_NO_LINEAGE = {
    "has_lineage": False,
    "source_count": 0,
    "hops_min": None,
    "hops_max": None,
    "flags": {"constant": False, "function": False, "not_persisted": False, "case_branches": False, "inferred": False},
    "sources": [],
}


def summarize_table(conn: sqlite3.Connection, project: str, object_id: str) -> dict[str, Any]:
    """Every declared column of the target object, with one entry per ultimate source."""
    by_column: dict[str, list[sqlite3.Row]] = {}
    for s in conn.execute(_TABLE_STEPS_SQL, (project, object_id)).fetchall():
        by_column.setdefault(s["root_target_column_id"], []).append(s)

    columns = conn.execute(
        f"SELECT column_id, column_name FROM canonical_column WHERE object_id = ?{declared_only(conn, [object_id])} ORDER BY column_name, column_id",
        (object_id,),
    ).fetchall()

    result = []
    for c in columns:
        steps = by_column.get(c["column_id"])
        detail = _analyze_column(steps) if steps else {**_NO_LINEAGE, "flags": dict(_NO_LINEAGE["flags"]), "sources": []}
        result.append({"column_id": c["column_id"], "column_name": c["column_name"], **detail})
    return {
        "object_id": object_id,
        "totals": {"columns": len(result), "with_lineage": sum(1 for c in result if c["has_lineage"])},
        "columns": result,
    }


class TableSummaryCache:
    """Remembers table summaries until the lineage database file changes."""

    def __init__(self, max_entries: int = 32) -> None:
        self._entries: OrderedDict[tuple, tuple[tuple, dict[str, Any]]] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()
        self.compute_count = 0

    def get(self, conn: sqlite3.Connection, project: str, object_id: str) -> dict[str, Any]:
        return self.get_computed(
            conn,
            (project, object_id),
            lambda: summarize_table(conn, project, object_id),
        )

    def get_computed(self, conn: sqlite3.Connection, key: tuple, compute) -> dict[str, Any]:
        fingerprint = db_fingerprint(conn)
        with self._lock:
            cached = self._entries.get(key)
            if cached and cached[0] == fingerprint:
                self._entries.move_to_end(key)
                return cached[1]
            summary = compute()
            self.compute_count += 1
            self._entries[key] = (fingerprint, summary)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
            return summary
