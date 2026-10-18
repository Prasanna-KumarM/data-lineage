"""Whole lineage graph of one target column: endpoints as nodes, mappings as edges (graph view).

Edges point from the target side to the source side. A shared upstream endpoint is one node with
several incoming edges, so the size follows the distinct mappings rather than the number of routes.
"""
import sqlite3
from typing import Any

from lineage_api.graph import StepGraph
from lineage_api.sources import _terminal_id
from lineage_api.summary import source_kind

TARGET_ID = "target"

_STEPS_SQL = """
    SELECT s.step_id, s.business_process_id, s.lineage_level, s.is_terminal, s.relation_id, s.relation_type,
           s.source_object_id, s.source_column_id, s.source_object_name, s.source_column_name,
           s.target_object_id, s.target_column_id,
           s.root_target_object_name, s.root_target_column_name,
           s.driving_expression, s.result_expression, s.component_name, s.confidence_class,
           o.object_type
    FROM business_lineage_step s
    JOIN business_process bp ON bp.business_process_id = s.business_process_id
    LEFT JOIN canonical_object o ON o.object_id = s.source_object_id
    WHERE bp.project_name = ? AND s.root_target_object_id = ? AND s.root_target_column_id = ?
"""


def build_column_graph(conn: sqlite3.Connection, project: str, object_id: str, column_id: str) -> dict[str, Any]:
    steps = conn.execute(_STEPS_SQL, (project, object_id, column_id)).fetchall()
    graph = StepGraph(steps)
    reachable = sorted(graph.reachable(), key=lambda i: (graph.by_id[i]["lineage_level"], i))

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple, dict[str, Any]] = {}
    leaf_relations: dict[str, set[str]] = {}

    if reachable:
        first = graph.by_id[reachable[0]]
        nodes[TARGET_ID] = {
            "node_id": TARGET_ID,
            "role": "target",
            "object_name": first["root_target_object_name"],
            "column_name": first["root_target_column_name"],
            "object_type": None,
            "kind": None,
            "condition": None,
            "result_expression": None,
            "hops_min": 0,
            "hops_max": 0,
        }

    for step_id in reachable:
        s = graph.by_id[step_id]
        hop = s["lineage_level"] + 1
        if s["lineage_level"] == 0:
            from_id = TARGET_ID
        else:
            from_id = f"E|{s['target_object_id']}|{s['target_column_id']}"
        is_leaf = not graph.kids_of(s)
        if is_leaf:
            to_id = f"T|{_terminal_id(s)}"
            leaf_relations.setdefault(to_id, set()).add(s["relation_type"])
        else:
            to_id = f"E|{s['source_object_id']}|{s['source_column_id']}"

        node = nodes.get(to_id)
        if node is None:
            nodes[to_id] = {
                "node_id": to_id,
                "role": "source" if is_leaf else "intermediate",
                "object_name": s["source_object_name"],
                "column_name": s["source_column_name"],
                "object_type": s["object_type"],
                "kind": None,
                "condition": s["driving_expression"] if is_leaf else None,
                "result_expression": s["result_expression"] if is_leaf else None,
                "hops_min": hop,
                "hops_max": hop,
                "_object_type": s["object_type"],
            }
        else:
            node["hops_min"] = min(node["hops_min"], hop)
            node["hops_max"] = max(node["hops_max"], hop)

        key = (from_id, to_id, s["relation_id"])
        edge = edges.get(key)
        if edge is None:
            edges[key] = {
                "edge_id": f"{from_id}>{to_id}#{s['relation_id']}",
                "from_node": from_id,
                "to_node": to_id,
                "relation_id": s["relation_id"],
                "step_ids": [step_id],
                "relation_type": s["relation_type"],
                "component_name": s["component_name"],
                "condition": s["driving_expression"],
                "result_expression": s["result_expression"],
                "hop": hop,
            }
        else:
            edge["step_ids"].append(step_id)
            edge["hop"] = min(edge["hop"], hop)

    for node_id, node in nodes.items():
        if node["role"] == "source":
            node["kind"] = source_kind(node.pop("_object_type"), leaf_relations[node_id])
        else:
            node.pop("_object_type", None)

    ordered_nodes = sorted(
        nodes.values(), key=lambda n: (n["hops_min"], n["object_name"], n["column_name"], n["node_id"])
    )
    ordered_edges = sorted(edges.values(), key=lambda e: (e["hop"], e["from_node"], e["to_node"], e["edge_id"]))
    sources = [n for n in ordered_nodes if n["role"] == "source"]
    return {
        "project": project,
        "object_id": object_id,
        "column_id": column_id,
        "has_lineage": bool(reachable),
        "nodes": ordered_nodes,
        "edges": ordered_edges,
        "totals": {
            "nodes": len(ordered_nodes),
            "edges": len(ordered_edges),
            "sources": len(sources),
            "hops_max": max((n["hops_max"] for n in ordered_nodes), default=0),
        },
    }
