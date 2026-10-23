"""Immediate-upstream navigation service (UI-04).

The children of a step are the steps of the same root target and Business Process, one level
deeper, whose target endpoint is this step's source endpoint. Steps are matched by endpoint,
not by path_id: two mappings that reach one endpoint share its upstream, and a branch the
user did not choose stays out because its endpoint differs.
"""
import sqlite3
from typing import Any


class StepNotFound(LookupError):
    pass


_CHOICE_SELECT = """
    SELECT c.step_id, c.relation_id, c.relation_type,
           c.source_object_id, c.source_column_id, c.source_object_name, c.source_column_name,
           c.target_object_id, c.target_column_id, c.target_object_name, c.target_column_name,
           c.component_id, c.component_name, c.component_type,
           c.business_process_id, c.business_process_name,
           c.confidence_class, c.confidence_reason_code,
           c.traversal_path, c.driving_expression, c.result_expression, c.expression_id,
           c.lineage_level, c.is_terminal,
           (SELECT COUNT(*) FROM business_lineage_step g
             WHERE g.root_target_object_id = c.root_target_object_id
               AND g.root_target_column_id = c.root_target_column_id
               AND g.business_process_id IS c.business_process_id
               AND g.lineage_level = c.lineage_level + 1
               AND g.target_object_id = c.source_object_id
               AND g.target_column_id = c.source_column_id
               AND c.is_terminal = 0) AS upstream_choice_count
"""

_ORDER = " ORDER BY c.source_object_name, c.source_column_name, c.step_id"


def _to_choice(row: sqlite3.Row) -> dict[str, Any]:
    choice = dict(row)
    count = choice["upstream_choice_count"]
    # Extractor-populated is_terminal wins; otherwise a leaf is a step with no children.
    choice["is_terminal"] = bool(choice["is_terminal"]) or count == 0
    choice["has_more_upstream"] = not choice["is_terminal"]
    return choice


def get_root_choices(
    conn: sqlite3.Connection,
    project: str,
    object_id: str,
    column_id: str,
    business_process_id: str | None = None,
) -> list[dict[str, Any]]:
    """Immediate upstream choices of the selected target column (level-0 steps)."""
    process_filter = " AND c.business_process_id = ?" if business_process_id is not None else ""
    params: tuple = (project, object_id, column_id)
    if business_process_id is not None:
        params += (business_process_id,)
    rows = conn.execute(
        _CHOICE_SELECT
        + """FROM business_lineage_step c
             JOIN business_process bp ON bp.business_process_id = c.business_process_id
             WHERE c.lineage_level = 0 AND bp.project_name = ?
               AND c.root_target_object_id = ? AND c.root_target_column_id = ?"""
        + process_filter
        + _ORDER,
        params,
    ).fetchall()
    return [_to_choice(r) for r in rows]


def get_upstream_choices(conn: sqlite3.Connection, step_id: str) -> list[dict[str, Any]]:
    """Immediate upstream choices of the source endpoint of the given step."""
    if conn.execute(
        "SELECT 1 FROM business_lineage_step WHERE step_id = ?", (step_id,)
    ).fetchone() is None:
        raise StepNotFound(step_id)
    rows = conn.execute(
        _CHOICE_SELECT
        + """FROM business_lineage_step p
             JOIN business_lineage_step c
               ON c.root_target_object_id = p.root_target_object_id
              AND c.root_target_column_id = p.root_target_column_id
              AND c.business_process_id IS p.business_process_id
              AND c.lineage_level = p.lineage_level + 1
              AND c.target_object_id = p.source_object_id
              AND c.target_column_id = p.source_column_id
             WHERE p.step_id = ? AND p.is_terminal = 0"""
        + _ORDER,
        (step_id,),
    ).fetchall()
    return [_to_choice(r) for r in rows]
