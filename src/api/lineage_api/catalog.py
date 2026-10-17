"""Selector catalog read model: projects, target objects and target columns (UI-03).

The target population is whatever the extractor materialised as roots in
business_lineage_step; no second target-classification rule is applied here.
"""
import sqlite3
from typing import Any


def list_projects(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT bp.project_name
           FROM business_lineage_step s
           JOIN business_process bp ON bp.business_process_id = s.business_process_id
           WHERE bp.project_name IS NOT NULL
           ORDER BY bp.project_name"""
    ).fetchall()
    return [r[0] for r in rows]


def list_target_objects(conn: sqlite3.Connection, project: str) -> list[dict[str, Any]]:
    """One entry per target object ID; same-named objects stay separate via object_id."""
    rows = conn.execute(
        """SELECT s.root_target_object_id AS object_id,
                  s.root_target_object_name AS object_name,
                  o.source_project AS source_project,
                  bp.business_process_id AS business_process_id,
                  bp.business_process_name AS business_process_name,
                  COUNT(DISTINCT s.root_target_column_id) AS column_count
           FROM business_lineage_step s
           JOIN business_process bp ON bp.business_process_id = s.business_process_id
           LEFT JOIN canonical_object o ON o.object_id = s.root_target_object_id
           WHERE bp.project_name = ?
           GROUP BY s.root_target_object_id, bp.business_process_id
           ORDER BY s.root_target_object_name, o.source_project,
                    bp.business_process_name, s.root_target_object_id""",
        (project,),
    ).fetchall()

    objects: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = objects.setdefault(
            r["object_id"],
            {
                "object_id": r["object_id"],
                "object_name": r["object_name"],
                "source_project": r["source_project"],
                "business_processes": [],
                "column_count": 0,
            },
        )
        entry["business_processes"].append(
            {
                "business_process_id": r["business_process_id"],
                "business_process_name": r["business_process_name"],
            }
        )
        entry["column_count"] = max(entry["column_count"], r["column_count"])
    return list(objects.values())


def list_target_columns(
    conn: sqlite3.Connection, project: str, object_id: str
) -> list[dict[str, Any]]:
    """Columns of the target object that have lineage steps within the project."""
    rows = conn.execute(
        """SELECT s.root_target_column_id AS column_id,
                  s.root_target_column_name AS column_name,
                  COUNT(*) AS step_count
           FROM business_lineage_step s
           JOIN business_process bp ON bp.business_process_id = s.business_process_id
           WHERE bp.project_name = ? AND s.root_target_object_id = ?
           GROUP BY s.root_target_column_id
           ORDER BY s.root_target_column_name, s.root_target_column_id""",
        (project, object_id),
    ).fetchall()
    return [dict(r) for r in rows]


def search_target_objects(conn: sqlite3.Connection, project: str, query: str) -> list[dict[str, Any]]:
    """Target objects of the project whose name contains the text, ignoring case; no text lists all."""
    needle = query.strip().casefold()
    objects = list_target_objects(conn, project)
    return [o for o in objects if needle in o["object_name"].casefold()] if needle else objects
