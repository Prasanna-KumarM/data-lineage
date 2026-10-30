"""Assemble the lineage database from parsed baseline content."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from par_fpl_lineage.baseline import LoaderRow, ViewDef, find_loader_rows, find_table_columns, find_views
from par_fpl_lineage.schema import TABLES

PROJECT = "FPL"
# Filled by the loader procedure, not by the view.
LOADER_COLUMNS = {
    "PAR_ID": "PAR_SEQ.NEXTVAL",
    "PAR_PROCESSING_UNIT": "p_processing_unit (loader parameter)",
    "PAR_PROCESS_DATE": "l_process_date (loader)",
}


def _id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()}"


class Db:
    def __init__(self, conn: sqlite3.Connection, run_id: str) -> None:
        self.conn = conn
        self.run_id = run_id
        self.objects: dict[tuple[str, str], str] = {}
        self.columns: dict[tuple[str, str], str] = {}
        self.issue_count = 0

    def object(self, name: str, scope: str, otype: str = "DataObject") -> str:
        key = (scope, name)
        if key not in self.objects:
            oid = _id("OBJ", scope, name)
            self.objects[key] = oid
            self.conn.execute("INSERT INTO canonical_object VALUES (?,?,?,?)", (oid, name, otype, scope))
        return self.objects[key]

    def column(self, obj_name: str, scope: str, col: str, declared: bool) -> str:
        oid = self.object(obj_name, scope)
        key = (oid, col)
        if key not in self.columns:
            cid = _id("COL", oid, col)
            self.columns[key] = cid
            self.conn.execute(
                "INSERT INTO canonical_column VALUES (?,?,?,?,?,?)",
                (cid, oid, col, None, 1 if declared else 0, 0 if declared else 1),
            )
        return self.columns[key]

    def issue(self, reason: str, message: str, locator: str, bp_id: str | None = None) -> None:
        self.issue_count += 1
        self.conn.execute(
            "INSERT INTO extraction_issue VALUES (?,?,?,?,?,?,?,?)",
            (_id("EXI", self.run_id, str(self.issue_count)), self.run_id, "WARNING", reason, message, locator, bp_id, None),
        )

    def mapping(self, bp, component, rtype, src, dst, hop, path_id, chain):
        """One relation + one lineage step. src/dst: (object_name, scope, column)."""
        rel = _id("MAP", bp, dst[2], src[2], str(hop))
        s_obj, s_col = self.object(src[0], src[1]), self.column(*src[:2], src[2], False)
        d_obj, d_col = self.object(dst[0], dst[1]), self.column(*dst[:2], dst[2], True)
        self.conn.execute(
            "INSERT INTO column_relation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rel, rtype, component[0], None, None, s_obj, s_col, d_obj, d_col, None, None, None, None),
        )
        self.conn.execute(
            "INSERT INTO canonical_confidence VALUES (?,?,?,?,?)", (rel, rtype, "Explicit", rtype, None)
        )
        step = _id("BLS", rel)
        root_obj, root_col = self.columns_root[0], self.columns_root[1]
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
                step, path_id, hop - 1, 0, root_obj, root_col, self.columns_root[2], self.columns_root[3],
                rel, rtype, s_obj, s_col, src[0], src[2], d_obj, d_col, dst[0], dst[2],
                component[0], component[1], component[2], bp[0], bp[1],
                "Explicit", rtype, None, None, None, None, hop, chain, None, None, None, None, None,
            ),
        )
        self.conn.execute("INSERT INTO business_lineage_step_contributor VALUES (?,?)", (step, rel))


def build(baseline: Path, output: Path, source_filter: str | None = None) -> dict[str, int]:
    codebase = baseline / "par_owner" / "ins" / "DB_codebase"
    if not codebase.is_dir():
        raise SystemExit(f"DB_codebase not found under {baseline} (expected par_owner/ins/DB_codebase)")

    loader_rows = [r for r in find_loader_rows(codebase) if r.par_table and r.portal_view]
    if source_filter:
        loader_rows = [r for r in loader_rows if r.par_source == source_filter]
    views = find_views(codebase)
    tables = find_table_columns(codebase)

    run_id = hashlib.sha256(f"{PROJECT}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:32]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    conn = sqlite3.connect(output)
    for ddl in TABLES:
        conn.execute(ddl)
    conn.execute(
        "INSERT INTO extraction_run VALUES (?,?,?,?,?,?,?,?)",
        (run_id, str(baseline), None, "1.0.0", "1.0.0", "IDV1", datetime.now(timezone.utc).isoformat(), "SUCCESS"),
    )
    db = Db(conn, run_id)
    db.object("FUNCTION", PROJECT)
    db.object("CONSTANT", "CONSTANT", "CONSTANT")

    stats = {"loaders": 0, "relations": 0, "views_missing": 0}
    for row in loader_rows:
        view = views.get(row.portal_view.upper())
        bp_name = row.delivery_set or f"{row.par_source}_{row.par_table}"
        bp = (_id("BPR", PROJECT, bp_name), bp_name)
        conn.execute("INSERT INTO business_process VALUES (?,?,?,?,?)", (bp[0], PROJECT, bp[1], "1", None))
        loader_cmp = (_id("CMP", bp[0], "loader"), "PAR portal loader", "PortalLoader")
        target_cmp = (_id("CMP", bp[0], "target"), row.par_table, "AptitudeServiceTarget")
        conn.execute("INSERT INTO component VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (target_cmp[0], bp[0], "1", "AptitudeServiceTarget", row.par_table, 1, 1, "Target", row.par_table, PROJECT))
        conn.execute("INSERT INTO component VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (loader_cmp[0], bp[0], "2", "PortalLoader", "PAR portal loader", 1, 1, None, None, None))
        view_cmp = None
        if view:
            view_cmp = (_id("CMP", bp[0], "view"), view.name, "OracleView")
            conn.execute("INSERT INTO component VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (view_cmp[0], bp[0], "3", "OracleView", view.name, 1, 1, None, None, None))

        if not view:
            db.issue("VIEW_MISSING", f"View {row.portal_view} not found in Views/", row.locator, bp[0])
            stats["views_missing"] += 1

        target_cols = tables.get(row.par_table.upper())
        if not target_cols:
            if view:
                target_cols = [i.view_column for i in view.items]
            else:
                db.issue("NO_TABLE_DDL", f"No table DDL or view for {row.par_table}; skipped", row.locator, bp[0])
                continue
            target_cols = list(dict.fromkeys([*LOADER_COLUMNS, *target_cols]))
            db.issue("TABLE_DDL_MISSING", f"No table DDL for {row.par_table}; columns taken from the view", row.locator, bp[0])
        if not view:
            continue
        for note in view.issues:
            db.issue("VIEW_PARSE", f"{view.name}: {note}", view.locator, bp[0])

        db.columns_root = (db.object(row.par_table, "PAR"), None, row.par_table, None)
        by_view_col = {i.view_column: i for i in view.items}
        for col in target_cols:
            db.columns_root = (db.columns_root[0], db.column(row.par_table, "PAR", col, True), row.par_table, col)
            if col in LOADER_COLUMNS:
                db.mapping(bp, loader_cmp, "RUNTIME_FUNCTION_ASSIGNMENT",
                           ("FUNCTION", PROJECT, LOADER_COLUMNS[col]), (row.par_table, "PAR", col),
                           1, _id("MAP", bp[0], col, "loader"),
                           f"{row.par_table}.{col} <- FUNCTION.{LOADER_COLUMNS[col]}")
                continue
            item = by_view_col.get(col)
            if item is None:
                db.issue("COLUMN_NOT_IN_VIEW", f"{row.par_table}.{col} is not a column of {view.name}", view.locator, bp[0])
                continue
            path = _id("PTH", bp[0], col)
            db.mapping(bp, loader_cmp, "EXPLICIT_INATTR",
                       (view.name, "PAR", col), (row.par_table, "PAR", col),
                       1, path, f"{row.par_table}.{col} <- {view.name}.{col}")
            if item.kind == "column":
                src_scope = "FPL"
                db.mapping(bp, view_cmp, "EXPLICIT_INATTR",
                           (view.from_table, src_scope, item.source_column), (view.name, "PAR", col),
                           2, path, f"{row.par_table}.{col} <- {view.name}.{col} <- {view.from_table}.{item.source_column}")
                db.column(view.from_table, src_scope, item.source_column, True)
            elif item.kind == "constant":
                db.mapping(bp, view_cmp, "CONSTANT_ASSIGNMENT",
                           ("CONSTANT", "CONSTANT", item.text), (view.name, "PAR", col),
                           2, path, f"{row.par_table}.{col} <- {view.name}.{col} <- CONSTANT.{item.text}")
            elif item.kind == "function":
                db.mapping(bp, view_cmp, "RUNTIME_FUNCTION_ASSIGNMENT",
                           ("FUNCTION", PROJECT, item.text), (view.name, "PAR", col),
                           2, path, f"{row.par_table}.{col} <- {view.name}.{col} <- FUNCTION.{item.text}")
            else:
                db.issue("EXPRESSION_NOT_TRACED", f"{view.name}.{col} is computed by an expression: {item.text}", view.locator, bp[0])
        stats["loaders"] += 1

    stats["relations"] = conn.execute("SELECT COUNT(*) FROM column_relation").fetchone()[0]
    conn.commit()
    conn.close()
    stats["issues"] = db.issue_count
    return stats
