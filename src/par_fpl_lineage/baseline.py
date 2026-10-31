"""Parse the baseline repository: loader rows, view DDL and table DDL."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

LOADER_TABLE = "PAR_PORTAL_LOADER_INFO"


@dataclass
class LoaderRow:
    par_source: str
    par_table: str
    portal_view: str
    delivery_set: str | None
    locator: str


@dataclass
class ViewItem:
    """One entry of a view's select list."""

    kind: str  # column | constant | function | expression
    view_column: str
    source_column: str | None = None  # for kind=column
    text: str | None = None  # raw text for constant/function/expression


@dataclass
class ViewDef:
    name: str
    from_table: str
    dblink: str | None
    items: list[ViewItem]
    locator: str
    issues: list[str] = field(default_factory=list)
    """Additional UNION branches: (from_table, dblink, items in view-column order)."""
    extra_sources: list[tuple[str, str | None, list[ViewItem]]] = field(default_factory=list)


def _split_values(text: str) -> list[str | None]:
    """Split an INSERT values tuple, respecting single-quoted strings."""
    out: list[str | None] = []
    cur = ""
    in_quote = False
    for ch in text:
        if ch == "'":
            in_quote = not in_quote
            cur += ch
        elif ch == "," and not in_quote:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return [None if v.lower() == "null" else (v[1:-1].replace("''", "'") if v.startswith("'") else v) for v in out]


_INSERT_RE = re.compile(
    r"insert\s+into\s+\w*\.*" + LOADER_TABLE + r"\s*\(([^)]*)\)\s*values\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)


def find_loader_rows(baseline: Path) -> list[LoaderRow]:
    rows: list[LoaderRow] = []
    for folder in ("DML_baseline", "DML_delta"):
        root = baseline / folder
        if not root.is_dir():
            continue
        for file in sorted(root.rglob("*.sql")):
            text = file.read_text(errors="replace")
            for match in _INSERT_RE.finditer(text):
                cols = [c.strip() for c in match.group(1).split(",")]
                values = _split_values(match.group(2))
                row = dict(zip(cols, values))
                rows.append(
                    LoaderRow(
                        par_source=row.get("PAR_SOURCE") or "",
                        par_table=row.get("PAR_TABLE") or "",
                        portal_view=row.get("PORTAL_VIEW") or "",
                        delivery_set=row.get("PORTAL_DELIVERY_SET"),
                        locator=f"{file.relative_to(baseline)}",
                    )
                )
    return rows


def _split_select_list(text: str) -> list[str]:
    """Split a SELECT list on top-level commas (paren- and quote-aware)."""
    out, cur, depth, in_quote = [], "", 0, False
    for ch in text:
        if ch == "'":
            in_quote = not in_quote
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append(cur.strip())
                cur = ""
                continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


_VIEW_RE = re.compile(
    r"create\s+or\s+replace\s+(?:force\s+)?view\s+[\w.]*?(\w+)\s*(?:\((.*?)\))?"
    r"(?:\s+bequeath\s+\w+)?\s+as\s+(.*?)\s+from\s+([\w.]+)(@[\w.]+)?(.*?);?\s*/?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONST_RE = re.compile(r"^('[^']*'|-?\d+(?:\.\d+)?)(?:\s+as\s+(\w+))?$", re.IGNORECASE)
_FUNC_RE = re.compile(r"^(\w[\w.]*\s*\(\s*\)|sysdate|current_timestamp)(?:\s+as\s+(\w+))?$", re.IGNORECASE)
_PLAIN_COL_RE = re.compile(r"^(\w+)$")
_ALIAS_RE = re.compile(r"^(.*?)\s+as\s+(\w+)$", re.IGNORECASE | re.DOTALL)


def parse_view(text: str, locator: str) -> ViewDef | None:
    match = _VIEW_RE.search(text)
    if not match:
        return None
    name, col_list, select_list, from_table, dblink, tail = match.groups()
    select_list = re.sub(r"^\s*select\s+(?:distinct\s+)?", "", select_list, flags=re.IGNORECASE)
    view_cols = [c.strip() for c in col_list.split(",")] if col_list else []
    issues: list[str] = []
    if re.search(r"\bwhere\b|\bjoin\b|\bgroup\s+by\b", tail or "", re.IGNORECASE):
        issues.append("view has WHERE/JOIN/GROUP BY; column mapping may be incomplete")
    items: list[ViewItem] = []
    for index, raw in enumerate(_split_select_list(select_list)):
        view_col = view_cols[index] if index < len(view_cols) else None
        item = raw.strip()
        m = _CONST_RE.match(item)
        if m:
            items.append(ViewItem("constant", view_col or m.group(2) or m.group(1), text=m.group(1)))
            continue
        m = _FUNC_RE.match(item)
        if m:
            items.append(ViewItem("function", view_col or m.group(2) or m.group(1), text=m.group(1)))
            continue
        m = _PLAIN_COL_RE.match(item)
        if m:
            items.append(ViewItem("column", view_col or m.group(1), source_column=m.group(1)))
            continue
        m = _ALIAS_RE.match(item)
        if m and _PLAIN_COL_RE.match(m.group(1).strip()):
            items.append(ViewItem("column", view_col or m.group(2), source_column=m.group(1).strip()))
            continue
        items.append(ViewItem("expression", view_col or (m.group(2) if m else item), text=item))
        issues.append(f"select item not a plain column/constant/function: {item[:80]}")
    view = ViewDef(name=name.upper(), from_table=from_table.split(".")[-1].upper(), dblink=(dblink or "").lstrip("@") or None, items=items, locator=locator, issues=issues)
    # Additional UNION [ALL] branches map positionally to the same view columns.
    for branch in re.finditer(
        r"union\s+(?:all\s+)?(?:select\s+)?(.*?)\s+from\s+([\w.]+)(@[\w.]+)?", tail or "", re.IGNORECASE | re.DOTALL
    ):
        view.extra_sources.append(
            (branch.group(2).split(".")[-1].upper(), (branch.group(3) or "").lstrip("@") or None, _classify_items(_split_select_list(branch.group(1)), view_cols))
        )
    if view.extra_sources:
        view.issues.append(f"view UNIONs {len(view.extra_sources) + 1} tables; each branch is mapped separately")
    return view


def _classify_items(raw_items: list[str], view_cols: list[str]) -> list[ViewItem]:
    items: list[ViewItem] = []
    for index, raw in enumerate(raw_items):
        view_col = view_cols[index] if index < len(view_cols) else None
        item = raw.strip()
        m = _CONST_RE.match(item)
        if m:
            items.append(ViewItem("constant", view_col or m.group(2) or m.group(1), text=m.group(1)))
            continue
        m = _FUNC_RE.match(item)
        if m:
            items.append(ViewItem("function", view_col or m.group(2) or m.group(1), text=m.group(1)))
            continue
        m = _PLAIN_COL_RE.match(item)
        if m:
            items.append(ViewItem("column", view_col or m.group(1), source_column=m.group(1)))
            continue
        m = _ALIAS_RE.match(item)
        if m and _PLAIN_COL_RE.match(m.group(1).strip()):
            items.append(ViewItem("column", view_col or m.group(2), source_column=m.group(1).strip()))
            continue
        items.append(ViewItem("expression", view_col or (m.group(2) if m else item), text=item))
    return items


def find_views(baseline: Path) -> dict[str, ViewDef]:
    views: dict[str, ViewDef] = {}
    root = baseline / "Views"
    if not root.is_dir():
        return views
    for file in sorted(root.rglob("*.sql")):
        view = parse_view(file.read_text(errors="replace"), str(file.relative_to(baseline)))
        if view:
            views[view.name] = view
    return views


_TABLE_RE = re.compile(r"create\s+table\s+[\w.]*?(\w+)\s*\((.*?)\)\s*(?:\w[\w\s]*)?;", re.IGNORECASE | re.DOTALL)
_CONSTRAINT_START = ("constraint", "primary", "foreign", "unique", "check")


def parse_table_columns(text: str) -> list[str]:
    match = _TABLE_RE.search(text)
    if not match:
        return []
    columns = []
    for part in _split_select_list(match.group(2)):
        first = part.strip().split(None, 1)[0].strip('"').upper() if part.strip() else ""
        if first and not first.lower().startswith(_CONSTRAINT_START):
            columns.append(first)
    return columns


def find_table_columns(baseline: Path) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for folder in ("Tables_baseline", "Tables_delta"):
        root = baseline / folder
        if not root.is_dir():
            continue
        for file in sorted(root.rglob("*.sql")):
            text = file.read_text(errors="replace")
            for match in re.finditer(r"create\s+table\s+[\w.]*?(\w+)\s*\(", text, re.IGNORECASE):
                name = match.group(1).upper()
                cols = parse_table_columns(text[match.start():])
                if cols and name not in tables:
                    tables[name] = cols
    return tables
