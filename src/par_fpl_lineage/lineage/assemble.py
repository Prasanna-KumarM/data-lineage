"""Turn loader rows + views + table columns into lineage rows, one Business Process per loader row."""
from __future__ import annotations

import sqlite3

from par_fpl_lineage.canonical.writer import CanonicalWriter, make_id
from par_fpl_lineage.config.settings import LOADER_COLUMNS, PROJECT
from par_fpl_lineage.models import Issue, LoaderRow, ViewDef

# Object scopes used in the generated database.
SCOPE_FPL = "FPL"      # tables read over the database link
SCOPE_PAR = "PAR"      # the portal view and the PAR table
SCOPE_FUNCTION = PROJECT
SCOPE_CONSTANT = "CONSTANT"


class _Mapper:
    """Writes the mapping rows of one target column of one loader row."""

    def __init__(self, writer: CanonicalWriter, bp: tuple[str, str], loader_cmp: tuple[str, str, str],
                 view_cmp: tuple[str, str, str], row: LoaderRow, view: ViewDef) -> None:
        self.w = writer
        self.bp = bp
        self.loader_cmp = loader_cmp
        self.view_cmp = view_cmp
        self.row = row
        self.view = view
        self.relations = 0

    def _write(self, rtype, src, dst, hop, path_id, component):
        rel = self.w.relation(rtype, component[0], src, dst, key=f"{self.bp[1]}|{dst[2]}|{src[0]}|{src[2]}|{hop}")
        if rel is None:
            return
        relation = {
            "relation_id": rel, "relation_type": rtype,
            "source_object_id": src[3], "source_column_id": src[4], "source_object_name": src[0], "source_column_name": src[2],
            "target_object_id": dst[3], "target_column_id": dst[4], "target_object_name": dst[0], "target_column_name": dst[2],
        }
        self.w.step(
            relation=relation, hop=hop, path_id=path_id, chain=self.chain,
            root=self.root, bp=self.bp, component=component,
        )
        self.relations += 1

    def column(self, col: str) -> None:
        row, view = self.row, self.view
        self.root = (
            self.w.object(row.par_table, SCOPE_PAR), self.w.column(row.par_table, SCOPE_PAR, col, True),
            row.par_table, col,
        )
        path_id = make_id("PTH", self.bp[0], col)
        if col in LOADER_COLUMNS:
            text = LOADER_COLUMNS[col]
            self.chain = f"{row.par_table}.{col} <- FUNCTION.{text}"
            src = ("FUNCTION", SCOPE_FUNCTION, text, self.w.object("FUNCTION", SCOPE_FUNCTION), self.w.column("FUNCTION", SCOPE_FUNCTION, text, False))
            dst = (row.par_table, SCOPE_PAR, col, self.root[0], self.root[1])
            self._write("RUNTIME_FUNCTION_ASSIGNMENT", src, dst, 1, path_id, self.loader_cmp)
            return
        item = next((i for i in view.sources[0].items if i.view_column == col), None)
        if item is None:
            self.w.on_issue("COLUMN_NOT_IN_VIEW", f"{row.par_table}.{col} is not a column of {view.name}", self.bp[1])
            return
        dst = (row.par_table, SCOPE_PAR, col, self.root[0], self.root[1])
        view_col = (view.name, SCOPE_PAR, col, self.w.object(view.name, SCOPE_PAR, "View"), self.w.column(view.name, SCOPE_PAR, col, True))
        self.chain = f"{row.par_table}.{col} <- {view.name}.{col}"
        self._write("EXPLICIT_INATTR", view_col, dst, 1, path_id, self.loader_cmp)
        for source in view.sources:
            branch_item = next((b for b in source.items if b.view_column == col), None)
            if branch_item is None:
                continue
            if branch_item.kind == "column":
                table = source.table
                src = (table, SCOPE_FPL, branch_item.source_column, self.w.object(table, SCOPE_FPL),
                       self.w.column(table, SCOPE_FPL, branch_item.source_column, True))
                self.chain = f"{row.par_table}.{col} <- {view.name}.{col} <- {table}.{branch_item.source_column}"
                self._write("EXPLICIT_INATTR", src, view_col, 2, path_id, self.view_cmp)
            elif branch_item.kind in ("constant", "function") and source is view.sources[0]:
                obj = "CONSTANT" if branch_item.kind == "constant" else "FUNCTION"
                scope = SCOPE_CONSTANT if branch_item.kind == "constant" else SCOPE_FUNCTION
                rtype = "CONSTANT_ASSIGNMENT" if branch_item.kind == "constant" else "RUNTIME_FUNCTION_ASSIGNMENT"
                text = branch_item.text or ""
                src = (obj, scope, text, self.w.object(obj, scope, obj if obj == "CONSTANT" else "DataObject"),
                       self.w.column(obj, scope, text, False))
                self.chain = f"{row.par_table}.{col} <- {view.name}.{col} <- {obj}.{text}"
                self._write(rtype, src, view_col, 2, path_id, self.view_cmp)
            elif branch_item.kind == "expression":
                self.w.on_issue("EXPRESSION_NOT_TRACED", f"{view.name}.{col} in {source.table}: {branch_item.text}", self.bp[1])


def assemble_loader_row(writer: CanonicalWriter, row: LoaderRow, view: ViewDef | None,
                        tables: dict[str, list[str]], used_bp_names: set[str]) -> int:
    """One loader row → its Business Process, components and column mappings. Returns relations written."""
    base_name = row.delivery_set or f"{row.par_source}_{row.portal_view}"
    bp_name, suffix = base_name, 2
    while bp_name in used_bp_names:
        bp_name = f"{base_name}_{suffix}"
        suffix += 1
    used_bp_names.add(bp_name)
    bp = writer.business_process(bp_name, PROJECT)
    if bp is None:
        return 0
    bp = (bp, bp_name)

    target_cmp = (writer.component(bp[0], "1", "AptitudeServiceTarget", row.par_table, ("Target", row.par_table, PROJECT)),
                  row.par_table, "AptitudeServiceTarget")
    loader_cmp = (writer.component(bp[0], "2", "PortalLoader", "PAR portal loader"), "PAR portal loader", "PortalLoader")

    if view is None:
        writer.on_issue("VIEW_MISSING", f"view {row.portal_view} not found in Views/", bp_name)
        return 0
    view_cmp = (writer.component(bp[0], "3", "OracleView", view.name), view.name, "OracleView")
    for note in view.issues:
        writer.on_issue("VIEW_PARSE", f"{view.name}: {note}", bp_name)

    target_cols = tables.get(row.par_table.upper())
    if not target_cols:
        target_cols = [item.view_column for item in view.sources[0].items]
        target_cols = list(dict.fromkeys([*LOADER_COLUMNS, *target_cols]))
        writer.on_issue("TABLE_DDL_MISSING", f"no table DDL for {row.par_table}; columns taken from the view", bp_name)

    mapper = _Mapper(writer, bp, loader_cmp, view_cmp, row, view)
    for col in list(dict.fromkeys(target_cols)):
        mapper.column(col)
    return mapper.relations
