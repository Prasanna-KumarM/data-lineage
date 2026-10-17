"""Relation and step detail service for the detail drawer (UI-07).

Values are exposed as stored in the generated lineage data; nothing is reinterpreted.
"""
import sqlite3
from typing import Any

from lineage_api.upstream import StepNotFound


class RelationNotFound(LookupError):
    pass


_RELATION_SQL = """
    SELECT r.relation_id, r.relation_type, r.expression_id,
           r.traversal_path, r.driving_expression, r.result_expression,
           r.source_object_id, r.source_column_id, r.target_object_id, r.target_column_id,
           so.object_name AS source_object_name, so.object_type AS source_object_type,
           sc.column_name AS source_column_name,
           tobj.object_name AS target_object_name, tobj.object_type AS target_object_type,
           tc.column_name AS target_column_name,
           c.component_id, c.component_name, c.component_type,
           bp.business_process_id, bp.business_process_name,
           cc.confidence_class, cc.confidence_reason_code, cc.confidence_reason
    FROM column_relation r
    LEFT JOIN canonical_object so ON so.object_id = r.source_object_id
    LEFT JOIN canonical_column sc ON sc.column_id = r.source_column_id
    LEFT JOIN canonical_object tobj ON tobj.object_id = r.target_object_id
    LEFT JOIN canonical_column tc ON tc.column_id = r.target_column_id
    LEFT JOIN component c ON c.component_id = r.component_id
    LEFT JOIN business_process bp ON bp.business_process_id = c.business_process_id
    LEFT JOIN canonical_confidence cc ON cc.relation_id = r.relation_id
    WHERE r.relation_id = ?
"""

_DEPENDENCY_SQL = """
    SELECT d.operand_order, d.operand_object_id AS object_id, d.operand_column_id AS column_id,
           o.object_name, o.object_type, c.column_name
    FROM expression_dependency d
    LEFT JOIN canonical_object o ON o.object_id = d.operand_object_id
    LEFT JOIN canonical_column c ON c.column_id = d.operand_column_id
    WHERE d.relation_id = ?
    ORDER BY d.operand_order, d.expression_dependency_id
"""


def _endpoint(row: sqlite3.Row, side: str) -> dict[str, Any]:
    return {
        "object_id": row[f"{side}_object_id"],
        "object_name": row[f"{side}_object_name"],
        "object_type": row[f"{side}_object_type"],
        "column_id": row[f"{side}_column_id"],
        "column_name": row[f"{side}_column_name"],
    }


def get_relation_detail(conn: sqlite3.Connection, relation_id: str) -> dict[str, Any]:
    row = conn.execute(_RELATION_SQL, (relation_id,)).fetchone()
    if row is None:
        raise RelationNotFound(relation_id)

    steps = conn.execute(
        "SELECT step_id FROM business_lineage_step WHERE relation_id = ? ORDER BY step_id",
        (relation_id,),
    ).fetchall()
    dependencies = [dict(d) for d in conn.execute(_DEPENDENCY_SQL, (relation_id,))]

    persistence = None
    if row["relation_type"] == "NOT_PERSISTED":
        persistence = {
            "status": "NOT_PERSISTED",
            "reason_code": row["confidence_reason_code"],
            "reason": row["confidence_reason"] or None,
        }

    return {
        "relation_id": row["relation_id"],
        "relation_type": row["relation_type"],
        "source": _endpoint(row, "source"),
        "target": _endpoint(row, "target"),
        "component": {
            "component_id": row["component_id"],
            "component_name": row["component_name"],
            "component_type": row["component_type"],
        },
        "business_process": {
            "business_process_id": row["business_process_id"],
            "business_process_name": row["business_process_name"],
        },
        "confidence": {
            "confidence_class": row["confidence_class"],
            "reason_code": row["confidence_reason_code"],
            "reason": row["confidence_reason"] or None,
        },
        "traversal_path": row["traversal_path"],
        "expression_id": row["expression_id"],
        "driving_expression": row["driving_expression"],
        "result_expression": row["result_expression"],
        "dependencies": dependencies,
        "persistence": persistence,
        "step_ids": [s[0] for s in steps],
    }


def get_step_detail(conn: sqlite3.Connection, step_id: str) -> dict[str, Any]:
    """Relation detail plus the step-level context (step, path position, Business Process)."""
    step = conn.execute(
        """SELECT step_id, path_id, lineage_level, hop_count, relation_id,
                  business_process_id, business_process_name
           FROM business_lineage_step WHERE step_id = ?""",
        (step_id,),
    ).fetchone()
    if step is None:
        raise StepNotFound(step_id)

    detail = get_relation_detail(conn, step["relation_id"])
    detail["step_id"] = step["step_id"]
    detail["path_id"] = step["path_id"]
    detail["lineage_level"] = step["lineage_level"]
    detail["hop_count"] = step["hop_count"]
    # The step's own Business Process is authoritative for this navigation context.
    detail["business_process"] = {
        "business_process_id": step["business_process_id"],
        "business_process_name": step["business_process_name"],
    }
    return detail
