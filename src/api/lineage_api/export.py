"""Build an Excel workbook for one target table's lineage summary."""
import io
import sqlite3
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_TARGET_FILL = PatternFill("solid", fgColor="DBEAFE")
_SOURCE_FILL = PatternFill("solid", fgColor="CFFAFE")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_WRAP = Alignment(vertical="top", wrap_text=True)

# Keep these in step with the UI badges (src/ui/src/components/relationStyle.ts).
RELATION_LABEL = {
    "EXPLICIT_INATTR": "Direct mapping",
    "EXPLICIT_PATHFROM_PATHTO": "Direct mapping (path)",
    "AUTO_MAP_BY_NAME": "Auto-mapped by name",
    "TRANSFORMATION_AUTO_MAP_BY_NAME": "Transformation auto-map",
    "EXPRESSION": "Expression",
    "CONSTANT_ASSIGNMENT": "Constant",
    "ENRICHMENT_LOOKUP": "Lookup",
    "RUNTIME_FUNCTION_ASSIGNMENT": "Function",
    "NOT_PERSISTED": "Not persisted",
}
_DIRECT = {"EXPLICIT_INATTR", "EXPLICIT_PATHFROM_PATHTO", "AUTO_MAP_BY_NAME"}

KIND_LABEL = {"column": "Column", "constant": "Constant", "function": "Function", "not_persisted": "Not persisted"}

_KIND_MEANING = {
    "Column": "The lineage ends at a column of a source table or file.",
    "Constant": "The column is filled by a constant value; nothing is read from a source.",
    "Function": "The column is filled by a runtime function; nothing is read from a source.",
    "Not persisted": "The value is computed and not stored; it is not read from a source.",
}


def _label(relation_type: str) -> str:
    return RELATION_LABEL.get(relation_type, relation_type.replace("_", " ").capitalize())


def _hop(step: dict[str, Any]) -> str:
    text = step["endpoint"]
    if step["relation_type"] not in _DIRECT:
        text += f" — {_label(step['relation_type'])}"
    return text


def _hops(source: dict[str, Any]) -> str:
    lo, hi = source["hops_min"], source["hops_max"]
    return f"{lo} hop" if lo == hi == 1 else (str(lo) if lo == hi else f"{lo}–{hi} hops")


def _extraction_timestamp(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("SELECT MAX(extraction_timestamp) FROM extraction_run").fetchone()
        return row[0] or "unknown"
    except sqlite3.Error:
        return "unknown"


def build_table_workbook(conn: sqlite3.Connection, project: str, object_name: str, summary: dict[str, Any]) -> bytes:
    """One row per target column and ultimate source; hops read left to right like the walkthrough."""
    columns = summary["columns"]
    max_route = max(
        (len(s["route"]) for c in columns for s in c["sources"]),
        default=0,
    )

    wb = Workbook()
    sheet = wb.active
    sheet.title = object_name[:31]
    headers = (
        ["Target table", "Target column"]
        + [f"Hop {i + 1}" for i in range(max_route)]
        + ["Ultimate source", "Source type", "When (condition)", "Value (result)", "Hops", "Path variants"]
    )
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _WRAP

    for column in columns:
        sources = column["sources"] or [None]
        for source in sources:
            row: list[Any] = [object_name, column["column_name"]]
            if source is None:
                row += [""] * max_route + ["No lineage", "", "", "", "", ""]
            else:
                route = [_hop(s) for s in source["route"]]
                row += route + [""] * (max_route - len(route))
                row += [
                    f"{source['object_name']}.{source['column_name']}",
                    KIND_LABEL.get(source["kind"], source["kind"]),
                    source["condition"] or "",
                    source["result_expression"] or "",
                    _hops(source),
                    source["route_count"],
                ]
            sheet.append(row)
            r = sheet.max_row
            sheet.cell(row=r, column=2).fill = _TARGET_FILL
            sheet.cell(row=r, column=3 + max_route).fill = _SOURCE_FILL
            for c in range(1, len(headers) + 1):
                sheet.cell(row=r, column=c).alignment = _WRAP

    sheet.freeze_panes = "C2"
    widths = [26, 24] + [30] * max_route + [32, 14, 34, 34, 10, 12]
    for i, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(i)].width = width

    legend = wb.create_sheet("How to read")
    rows = [
        ("Project", project),
        ("Database", _db_name(conn)),
        ("Extracted at", _extraction_timestamp(conn)),
        ("", ""),
        ("Hop 1 …", "The column read left to right: each hop is OBJECT.COLUMN that feeds the previous one. The last hop is the ultimate source."),
        ("", ""),
        ("Mapping kinds", ""),
        *[(_label(k), "") for k in RELATION_LABEL],
        ("", ""),
        ("Source types", ""),
        *[(label, _KIND_MEANING[label]) for label in _KIND_MEANING],
    ]
    for pair in rows:
        legend.append(list(pair))
    legend["A1"].font = Font(bold=True)
    legend.column_dimensions["A"].width = 34
    legend.column_dimensions["B"].width = 90
    for row in legend.iter_rows():
        for cell in row:
            cell.alignment = _WRAP

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _db_name(conn: sqlite3.Connection) -> str:
    try:
        return str(conn.execute("PRAGMA database_list").fetchone()[2]).rsplit("/", 1)[-1]
    except (sqlite3.Error, TypeError):
        return "unknown"
