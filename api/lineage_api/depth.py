"""Remaining-hop depth for the actively selected step (UI-06)."""
import sqlite3
from typing import Any

from lineage_api.upstream import StepNotFound

_SUBTREE_SQL = """
    SELECT g.step_id, g.lineage_level, g.is_terminal,
           g.source_object_id, g.source_column_id, g.target_object_id, g.target_column_id
    FROM business_lineage_step s
    JOIN business_lineage_step g
      ON g.root_target_object_id = s.root_target_object_id
     AND g.root_target_column_id = s.root_target_column_id
     AND g.business_process_id IS s.business_process_id
     AND g.lineage_level >= s.lineage_level
    WHERE s.step_id = ?
"""


def get_remaining_depth(conn: sqlite3.Connection, step_id: str) -> dict[str, Any]:
    """Hops still to walk below the step; exact when all routes agree, else min/max."""
    rows = conn.execute(_SUBTREE_SQL, (step_id,)).fetchall()
    if not rows:
        raise StepNotFound(step_id)

    by_id = {r["step_id"]: r for r in rows}
    children: dict[str, list[str]] = {}
    index: dict[tuple, list[str]] = {}
    for r in rows:
        index.setdefault(
            (r["lineage_level"], r["target_object_id"], r["target_column_id"]), []
        ).append(r["step_id"])
    for r in rows:
        kids = [] if r["is_terminal"] else index.get(
            (r["lineage_level"] + 1, r["source_object_id"], r["source_column_id"]), []
        )
        children[r["step_id"]] = kids

    # Only steps below the selected one are visited; sibling branches never are.
    reachable: list[str] = []
    seen = {step_id}
    stack = [step_id]
    while stack:
        current = stack.pop()
        reachable.append(current)
        for kid in children[current]:
            if kid not in seen:
                seen.add(kid)
                stack.append(kid)

    low: dict[str, int] = {}
    high: dict[str, int] = {}
    for current in sorted(reachable, key=lambda sid: -by_id[sid]["lineage_level"]):
        kids = children[current]
        if not kids:
            low[current] = high[current] = 0
        else:
            low[current] = 1 + min(low[k] for k in kids)
            high[current] = 1 + max(high[k] for k in kids)

    mn, mx = low[step_id], high[step_id]
    return {
        "step_id": step_id,
        "is_terminal": mx == 0,
        "remaining_hops_exact": mn if mn == mx else None,
        "remaining_hops_min": mn,
        "remaining_hops_max": mx,
    }
