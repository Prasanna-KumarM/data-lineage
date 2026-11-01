"""Id-safe writers for the canonical tables. Duplicate identifiers are skipped, never fatal."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Callable

IssueFn = Callable[[str, str, str | None], None]  # (reason_code, message, business_process)


def make_id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()}"


class CanonicalWriter:
    def __init__(self, conn: sqlite3.Connection, on_issue: IssueFn) -> None:
        self.conn = conn
        self.on_issue = on_issue
        self._objects: dict[tuple[str, str], str] = {}
        self._columns: dict[tuple[str, str], str] = {}
        self._relations: set[str] = set()
        self._steps: set[str] = set()
        self._business_processes: set[str] = set()

    def object(self, name: str, scope: str, object_type: str = "DataObject") -> str:
        key = (scope, name)
        if key not in self._objects:
            oid = make_id("OBJ", scope, name)
            self._objects[key] = oid
            self.conn.execute("INSERT INTO canonical_object VALUES (?,?,?,?)", (oid, name, object_type, scope))
        return self._objects[key]

    def column(self, object_name: str, scope: str, column_name: str, declared: bool) -> str:
        oid = self.object(object_name, scope)
        key = (oid, column_name)
        if key not in self._columns:
            cid = make_id("COL", oid, column_name)
            self._columns[key] = cid
            self.conn.execute(
                "INSERT INTO canonical_column VALUES (?,?,?,?,?,?)",
                (cid, oid, column_name, None, 1 if declared else 0, 0 if declared else 1),
            )
        return self._columns[key]

    def business_process(self, name: str, project: str) -> str | None:
        if name in self._business_processes:
            self.on_issue("DUPLICATE_BUSINESS_PROCESS", f"business process {name} already written; duplicate loader row skipped", None)
            return None
        self._business_processes.add(name)
        bp_id = make_id("BPR", project, name)
        self.conn.execute("INSERT INTO business_process VALUES (?,?,?,?,?)", (bp_id, project, name, "1", None))
        return bp_id

    def component(
        self, bp_id: str, local_block_id: str, component_type: str, name: str,
        referenced: tuple[str, str, str] | None = None,
    ) -> str:
        cid = make_id("CMP", bp_id, local_block_id)
        ref_type, ref_name, ref_project = referenced or (None, None, None)
        self.conn.execute(
            "INSERT INTO component VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cid, bp_id, local_block_id, component_type, name, 1, 1, ref_type, ref_name, ref_project),
        )
        return cid

    def relation(self, rtype: str, component_id: str, source: tuple[str, str], target: tuple[str, str], key: str) -> str | None:
        """One column_relation + confidence row. Returns None (and an issue) when the id is already written."""
        rel = make_id("MAP", key)
        if rel in self._relations:
            self.on_issue("DUPLICATE_RELATION", f"duplicate mapping skipped: {target[0]}.{target[1]} <- {source[0]}.{source[1]} ({rtype})", None)
            return None
        self._relations.add(rel)
        self.conn.execute(
            "INSERT INTO column_relation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rel, rtype, component_id, None, None, source[0], source[1], target[0], target[1], None, None, None, None),
        )
        self.conn.execute("INSERT INTO canonical_confidence VALUES (?,?,?,?,?)", (rel, rtype, "Explicit", rtype, None))
        return rel

    def step(self, *, relation: dict[str, Any], hop: int, path_id: str, chain: str,
             root: tuple[str, str, str, str], bp: tuple[str, str], component: tuple[str, str, str]) -> str | None:
        """One business_lineage_step + its contributor row; None when the id is already written."""
        step_id = make_id("BLS", relation["relation_id"], path_id, str(hop))
        if step_id in self._steps:
            self.on_issue("DUPLICATE_STEP", f"duplicate step skipped: {chain}", bp[1])
            return None
        self._steps.add(step_id)
        self.conn.execute(
            "INSERT INTO business_lineage_step (step_id,path_id,lineage_level,is_terminal,"
            "root_target_object_id,root_target_column_id,root_target_object_name,root_target_column_name,"
            "relation_id,relation_type,source_object_id,source_column_id,source_object_name,source_column_name,"
            "target_object_id,target_column_id,target_object_name,target_column_name,"
            "component_id,component_name,component_type,business_process_id,business_process_name,"
            "confidence_class,confidence_reason_code,traversal_path,driving_expression,result_expression,expression_id,"
            "hop_count,lineage_chain,complete_lineage_path,relation_type_path,component_path,driving_expression_path,result_expression_path)"
            f" VALUES ({','.join('?' for _ in range(36))})",
            (
                step_id, path_id, hop - 1, 0, root[0], root[1], root[2], root[3],
                relation["relation_id"], relation["relation_type"],
                relation["source_object_id"], relation["source_column_id"], relation["source_object_name"], relation["source_column_name"],
                relation["target_object_id"], relation["target_column_id"], relation["target_object_name"], relation["target_column_name"],
                component[0], component[1], component[2], bp[0], bp[1],
                "Explicit", relation["relation_type"], None, None, None, None,
                hop, chain, None, None, None, None, None,
            ),
        )
        self.conn.execute("INSERT INTO business_lineage_step_contributor VALUES (?,?)", (step_id, relation["relation_id"]))
        return step_id
