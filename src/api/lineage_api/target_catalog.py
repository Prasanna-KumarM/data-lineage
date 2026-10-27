"""Resolve Aptitude Target components to the lineage roots they own."""
import hashlib
import json
import sqlite3
from collections import defaultdict
from typing import Any

from lineage_api.db import declared_only


def _id(prefix: str, *parts: str) -> str:
    payload = json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()}"


def _has_target_components(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='component'"
    ).fetchone() is not None


def _has_invocations(conn: sqlite3.Connection) -> bool:
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='business_process_invocation'"
    ).fetchone() is None:
        return False
    return conn.execute("SELECT 1 FROM business_process_invocation LIMIT 1").fetchone() is not None


def _calling_processes(
    conn: sqlite3.Connection, project: str, target_bp_id: str, target_bp_name: str, use_invocations: bool
) -> list[sqlite3.Row]:
    if use_invocations:
        return conn.execute(
            """SELECT DISTINCT caller.business_process_id,caller.business_process_name
               FROM business_process_invocation inv
               JOIN business_process caller ON caller.business_process_id=inv.calling_business_process_id
               WHERE caller.project_name=? AND inv.resolution_status='RESOLVED'
                 AND inv.referenced_business_process_id=?
               ORDER BY caller.business_process_name""",
            (project, target_bp_id),
        ).fetchall()
    return conn.execute(
        """SELECT DISTINCT caller.business_process_id,caller.business_process_name
           FROM component block
           JOIN business_process caller ON caller.business_process_id=block.business_process_id
           WHERE caller.project_name=? AND block.component_type='AptitudeServiceBlock'
             AND block.referenced_element_type='BusinessProcess'
             AND block.referenced_element_name=? AND block.referenced_project_name=?
           ORDER BY caller.business_process_name""",
        (project, target_bp_name, project),
    ).fetchall()


def target_definitions(conn: sqlite3.Connection, project: str) -> list[dict[str, Any]]:
    """Group roots by Aptitude target name/project and retain their owning BP/root IDs.

    A Target component can have same-named canonical objects in multiple projects. Include
    every matching root in its Business Process so no relation mappings are dropped.
    """
    if not _has_target_components(conn):
        rows = conn.execute(
            """SELECT DISTINCT s.root_target_object_id AS object_id,
                              s.root_target_object_name AS object_name,
                              o.source_project AS source_project,
                              bp.business_process_id, bp.business_process_name,
                              COUNT(DISTINCT s.root_target_column_id) AS column_count
               FROM business_lineage_step s
               JOIN business_process bp ON bp.business_process_id=s.business_process_id
               LEFT JOIN canonical_object o ON o.object_id=s.root_target_object_id
               WHERE bp.project_name=?
               GROUP BY s.root_target_object_id,bp.business_process_id
               ORDER BY s.root_target_object_name,o.source_project,bp.business_process_name""",
            (project,),
        ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for r in rows:
            obj = grouped.setdefault(
                r["object_id"],
                {"object_id": r["object_id"], "object_name": r["object_name"],
                 "source_project": r["source_project"], "business_processes": [],
                 "column_count": 0, "_root_pairs": []},
            )
            obj["business_processes"].append(
                {"business_process_id": r["business_process_id"], "business_process_name": r["business_process_name"]}
            )
            obj["column_count"] = max(obj["column_count"], r["column_count"])
            obj["_root_pairs"].append((r["business_process_id"], r["object_id"]))
        return list(grouped.values())

    components = conn.execute(
        """SELECT DISTINCT t.business_process_id,bp.business_process_name,
                          t.referenced_element_name AS object_name,
                          t.referenced_project_name AS source_project
           FROM component t
           JOIN business_process bp ON bp.business_process_id=t.business_process_id
           WHERE bp.project_name=? AND t.component_type='AptitudeServiceTarget'
             AND t.referenced_element_type='Target'
           ORDER BY t.referenced_element_name,t.referenced_project_name,bp.business_process_name""",
        (project,),
    ).fetchall()

    use_invocations = _has_invocations(conn)
    grouped: dict[tuple[str, str | None], dict[str, Any]] = {}
    for component in components:
        calling_processes = _calling_processes(
            conn, project, component["business_process_id"], component["business_process_name"], use_invocations
        )
        processes = [(component["business_process_id"], component["business_process_name"])]
        processes.extend((p["business_process_id"], p["business_process_name"]) for p in calling_processes)
        key = (component["object_name"], component["source_project"])
        target = grouped.setdefault(
            key,
            {"object_name": component["object_name"], "source_project": component["source_project"],
             "business_processes": [], "_root_pairs": [], "_root_ids": set()},
        )
        for bp_id, bp_name in processes:
            if not any(p["business_process_id"] == bp_id for p in target["business_processes"]):
                target["business_processes"].append(
                    {"business_process_id": bp_id, "business_process_name": bp_name}
                )
            roots = conn.execute(
                """SELECT DISTINCT s.root_target_object_id AS object_id
                   FROM business_lineage_step s
                   WHERE s.business_process_id=? AND s.root_target_object_name=?
                   ORDER BY s.root_target_object_id""",
                (bp_id, component["object_name"]),
            ).fetchall()
            for root in roots:
                pair = (bp_id, root["object_id"])
                if pair not in target["_root_pairs"]:
                    target["_root_pairs"].append(pair)
                    target["_root_ids"].add(root["object_id"])

    results = []
    for (name, source_project), target in sorted(grouped.items()):
        target["object_id"] = _id("TARGET", project, source_project or "", name)
        root_ids = sorted(target.pop("_root_ids"))
        if not root_ids:
            continue
        marks = ",".join("?" for _ in root_ids)
        target["column_count"] = conn.execute(
            f"SELECT COUNT(DISTINCT column_name) FROM canonical_column WHERE object_id IN ({marks}){declared_only(conn, root_ids)}",
            root_ids,
        ).fetchone()[0]
        target["business_processes"].sort(key=lambda p: p["business_process_name"])
        results.append(target)
    return results


def find_target(conn: sqlite3.Connection, project: str, object_id: str) -> dict[str, Any] | None:
    return next((t for t in target_definitions(conn, project) if t["object_id"] == object_id), None)


def target_column_id(object_id: str, column_name: str) -> str:
    return _id("TCOL", object_id, column_name)


def _pair_filter(pairs: list[tuple[str, str]], alias: str = "s") -> str:
    return " OR ".join(
        f"({alias}.business_process_id=? AND {alias}.root_target_object_id=?)"
        for _ in pairs
    )


def _column_rows(conn: sqlite3.Connection, target: dict[str, Any]) -> list[dict[str, Any]]:
    root_ids = sorted({root_id for _, root_id in target["_root_pairs"]})
    if not root_ids:
        return []
    marks = ",".join("?" for _ in root_ids)
    names = [
        row[0]
        for row in conn.execute(
            f"SELECT DISTINCT column_name FROM canonical_column WHERE object_id IN ({marks}){declared_only(conn, root_ids)}",
            root_ids,
        )
    ]
    pairs = target["_root_pairs"]
    counts = {
        row["root_target_column_name"]: row["step_count"]
        for row in conn.execute(
            f"""SELECT s.root_target_column_name,COUNT(*) AS step_count
                FROM business_lineage_step s
                WHERE {_pair_filter(pairs)}
                GROUP BY s.root_target_column_name""",
            [value for pair in pairs for value in pair],
        )
    }
    return [
        {"column_id": target_column_id(target["object_id"], name),
         "column_name": name, "step_count": counts.get(name, 0)}
        for name in sorted(names)
    ]


def target_column_pairs(
    conn: sqlite3.Connection, project: str, object_id: str, column_id: str
) -> list[tuple[str, str, str]]:
    """Physical (BP, object, column) roots represented by a logical target column."""
    target = find_target(conn, project, object_id)
    if target is None:
        return []
    name_row = next(
        (r for r in _column_rows(conn, target) if r["column_id"] == column_id),
        None,
    )
    if name_row is None:
        return []
    pairs = target["_root_pairs"]
    return [
        tuple(row)
        for row in conn.execute(
            f"""SELECT DISTINCT s.business_process_id,s.root_target_object_id,s.root_target_column_id
                FROM business_lineage_step s JOIN canonical_column c
                  ON c.object_id=s.root_target_object_id AND c.column_id=s.root_target_column_id
                WHERE c.column_name=? AND ({_pair_filter(pairs)})""",
            [name_row["column_name"], *[value for pair in pairs for value in pair]],
        )
    ]


def list_target_columns(conn: sqlite3.Connection, project: str, object_id: str) -> list[dict[str, Any]]:
    target = find_target(conn, project, object_id)
    if target is None:
        return []
    return [row for row in _column_rows(conn, target) if row["step_count"] > 0]


def summarize_target(conn: sqlite3.Connection, project: str, object_id: str) -> dict[str, Any]:
    """Combine the physical root lineages owned by one Aptitude Target component."""
    from lineage_api.summary import _NO_LINEAGE, _analyze_column, source_kind

    target = find_target(conn, project, object_id)
    if target is None:
        raise LookupError(object_id)
    physical_ids = sorted({root_id for _, root_id in target["_root_pairs"]})
    marks = ",".join("?" for _ in physical_ids)
    names = [
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT column_name FROM canonical_column WHERE object_id IN ({marks}){declared_only(conn, physical_ids)} ORDER BY column_name",
            physical_ids,
        )
    ]
    pairs = target["_root_pairs"]
    sql = f"""SELECT s.step_id,s.business_process_id,s.lineage_level,s.is_terminal,s.relation_type,
                      s.root_target_object_id,s.root_target_column_id,s.root_target_column_name,
                      s.source_object_id,s.source_column_id,s.source_object_name,s.source_column_name,
                      s.target_object_id,s.target_column_id,s.driving_expression,s.result_expression,
                      s.component_name,s.confidence_class,o.object_type
               FROM business_lineage_step s
               LEFT JOIN canonical_object o ON o.object_id=s.source_object_id
               WHERE ({_pair_filter(pairs)})"""
    grouped_steps: dict[str, dict[tuple[str, str, str], list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    for step in conn.execute(sql, [value for pair in pairs for value in pair]):
        key = (step["business_process_id"], step["root_target_object_id"], step["root_target_column_id"])
        grouped_steps[step["root_target_column_name"]][key].append(step)

    columns = []
    for name in names:
        details = [_analyze_column(rows) for rows in grouped_steps.get(name, {}).values()]

        by_terminal: dict[str, dict[str, Any]] = {}
        for detail in details:
            for source in detail["sources"]:
                existing = by_terminal.get(source["terminal_id"])
                if existing is None:
                    by_terminal[source["terminal_id"]] = dict(source)
                else:
                    existing["hops_min"] = min(existing["hops_min"], source["hops_min"])
                    existing["hops_max"] = max(existing["hops_max"], source["hops_max"])
                    existing["route_count"] += source["route_count"]
                    existing["leaf_relation_types"] = sorted(
                        set(existing["leaf_relation_types"]) | set(source["leaf_relation_types"])
                    )
                    existing["kind"] = source_kind(
                        existing["object_type"], existing["leaf_relation_types"]
                    )
        sources = sorted(
            by_terminal.values(),
            key=lambda s: (s["object_name"], s["column_name"], s["terminal_id"]),
        )
        flags = {
            key: any(detail["flags"][key] for detail in details)
            for key in ("constant", "function", "not_persisted", "case_branches", "inferred")
        }
        columns.append(
            {
                "column_id": target_column_id(object_id, name),
                "column_name": name,
                "has_lineage": bool(sources),
                "source_count": len(sources),
                "hops_min": min((s["hops_min"] for s in sources), default=None),
                "hops_max": max((s["hops_max"] for s in sources), default=None),
                "flags": flags if sources else dict(_NO_LINEAGE["flags"]),
                "sources": sources,
            }
        )
    return {
        "object_id": object_id,
        "totals": {"columns": len(columns), "with_lineage": sum(c["has_lineage"] for c in columns)},
        "columns": columns,
    }
